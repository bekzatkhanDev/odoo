# -*- coding: utf-8 -*-
"""Pharmacy counter sale (Сату).

Stock side: completing a sale validates a STANDARD outgoing stock.picking with
lot-level stock.move.line records; returning validates the reverse incoming
picking. Nothing here writes stock.quant directly, so on-hand quantities and
valuation always follow Odoo core. The picking is created with sudo() so a
cashier needs no inventory rights beyond reading lots/locations.
"""
from collections import defaultdict
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from .densamed_sale_payment import PAYMENT_METHODS

# Fields that must not change once the sale left draft.
_PROTECTED_AFTER_DRAFT = {'company_id', 'warehouse_id', 'partner_id', 'date', 'prescription_ref'}


class DensamedSale(models.Model):
    _name = 'densamed.sale'
    _description = 'Pharmacy Sale'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Receipt No.', required=True, copy=False, readonly=True, index=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Branch', required=True, index=True,
        default=lambda self: self.env.company)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True, check_company=True,
        default=lambda self: self._default_warehouse(), tracking=True,
        domain="[('company_id', '=', company_id)]")
    user_id = fields.Many2one(
        'res.users', string='Cashier', required=True, readonly=True,
        default=lambda self: self.env.user, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Customer', tracking=True)
    date = fields.Datetime(
        string='Sale Date', required=True, copy=False, default=fields.Datetime.now)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('returned', 'Returned'),
    ], string='Status', required=True, default='draft', copy=False,
        index=True, tracking=True)

    line_ids = fields.One2many('densamed.sale.line', 'sale_id', string='Medicines', copy=True)
    payment_ids = fields.One2many('densamed.sale.payment', 'sale_id', string='Payments', copy=False)
    default_payment_method = fields.Selection(
        PAYMENT_METHODS, string='Payment Method', default='cash',
        help='Used to create the full payment automatically when no payment '
             'is entered before completing the sale.')

    prescription_ref = fields.Char(string='Prescription No.', copy=False)
    requires_prescription = fields.Boolean(
        string='Contains Rx medicines', compute='_compute_requires_prescription')

    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount_total = fields.Monetary(
        string='Total', compute='_compute_amount_total', store=True)
    amount_paid = fields.Monetary(string='Paid', compute='_compute_payment_amounts')
    amount_due = fields.Monetary(string='Balance', compute='_compute_payment_amounts')

    item_count = fields.Integer(string='Units Sold', compute='_compute_sales_kpis', store=True)
    margin_total = fields.Monetary(string='Gross Profit', compute='_compute_sales_kpis', store=True)
    customer_reference = fields.Char(string='Customer Reference', copy=False)

    @api.depends('line_ids.quantity', 'line_ids.margin_amount')
    def _compute_sales_kpis(self):
        for sale in self:
            sale.item_count = sum(sale.line_ids.mapped('quantity'))
            sale.margin_total = sum(sale.line_ids.mapped('margin_amount'))

    def action_print_receipt(self):
        self.ensure_one()
        return self.env.ref('densamed_sale.action_report_densamed_receipt').report_action(self)

    picking_id = fields.Many2one('stock.picking', string='Delivery', readonly=True, copy=False)
    return_picking_id = fields.Many2one('stock.picking', string='Return', readonly=True, copy=False)
    note = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Defaults / computes
    # ------------------------------------------------------------------
    @api.model
    def _default_warehouse(self):
        return self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)

    @api.depends('line_ids.product_id.requires_prescription')
    def _compute_requires_prescription(self):
        for sale in self:
            sale.requires_prescription = any(
                sale.line_ids.mapped('product_id.requires_prescription'))

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for sale in self:
            sale.amount_total = sum(sale.line_ids.mapped('subtotal'))

    @api.depends('amount_total', 'payment_ids.amount', 'payment_ids.state')
    def _compute_payment_amounts(self):
        for sale in self:
            paid = sum(sale.payment_ids.filtered(
                lambda p: p.state == 'completed').mapped('amount'))
            sale.amount_paid = paid
            sale.amount_due = sale.amount_total - paid

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id)
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'densamed.sale') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if _PROTECTED_AFTER_DRAFT & set(vals) and any(s.state != 'draft' for s in self):
            raise UserError(_('Only a draft sale can be modified.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_processed(self):
        if any(sale.state in ('completed', 'returned') for sale in self):
            raise UserError(_('A completed or returned sale cannot be deleted. '
                              'Return it instead.'))

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_confirm(self):
        """Complete the sale: validate, allocate batches, pay, move stock."""
        for sale in self:
            sale = sale.with_company(sale.company_id)
            sale._check_can_confirm()
            sale._allocate_lots()
            sale._check_lines_stock()
            # Freeze unit cost at checkout for reproducible historical margins.
            for line in sale.line_ids:
                line.cost_unit = line.product_id.with_company(sale.company_id).standard_price
            sale._ensure_payment()
            picking = sale._create_stock_picking()
            sale.write({'picking_id': picking.id, 'state': 'completed'})
            sale.message_post(body=_('Sale completed. Delivery %s validated.', picking.name))
        return True

    def action_return(self):
        """Return the whole sale: reverse stock move, refund payments."""
        for sale in self:
            if sale.state != 'completed':
                raise UserError(_('Only a completed sale can be returned.'))
            sale = sale.with_company(sale.company_id)
            picking = sale._create_stock_picking(returning=True)
            sale.payment_ids.filtered(lambda p: p.state == 'completed').write(
                {'state': 'refunded'})
            sale.write({'return_picking_id': picking.id, 'state': 'returned'})
            sale.message_post(body=_('Sale returned. Return %s validated.', picking.name))
        return True

    def action_cancel(self):
        if any(sale.state != 'draft' for sale in self):
            raise UserError(_('Only a draft sale can be cancelled.'))
        self.write({'state': 'cancelled'})
        self.payment_ids.filtered(lambda p: p.state in ('pending', 'completed')).write(
            {'state': 'cancelled'})
        return True

    def action_draft(self):
        if any(sale.state != 'cancelled' for sale in self):
            raise UserError(_('Only a cancelled sale can be set back to draft.'))
        self.write({'state': 'draft'})
        return True

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delivery'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _check_can_confirm(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft sale can be completed.'))
        if not self.line_ids:
            raise UserError(_('Add at least one medicine before completing the sale.'))
        if self.requires_prescription and not (self.prescription_ref or '').strip():
            names = ', '.join(self.line_ids.filtered('requires_prescription')
                              .mapped('product_id.display_name'))
            raise UserError(_('A prescription number is required for: %s', names))

    @api.model
    def _is_lot_expired(self, lot, today):
        return bool(lot.expiration_date) and lot.expiration_date.date() < today

    def _check_lines_stock(self):
        """Every line has a valid, non-expired batch and enough stock."""
        self.ensure_one()
        location = self.warehouse_id.lot_stock_id
        today = fields.Date.context_today(self)
        Quant = self.env['stock.quant'].sudo()
        needed = defaultdict(float)
        for line in self.line_ids:
            product = line.product_id
            if product.tracking != 'none' and not line.lot_id:
                raise UserError(_('No batch could be assigned to %s.', product.display_name))
            if line.lot_id and self._is_lot_expired(line.lot_id, today):
                raise UserError(_('Batch %(lot)s of %(product)s is expired.',
                                  lot=line.lot_id.name, product=product.display_name))
            needed[(product, line.lot_id)] += line.quantity
        for (product, lot), qty in needed.items():
            available = Quant._get_available_quantity(product, location, lot_id=lot or None)
            if float_compare(available, qty, precision_rounding=product.uom_id.rounding) < 0:
                raise UserError(_(
                    'Not enough stock for %(product)s%(lot)s: requested %(qty)s, available %(avail)s.',
                    product=product.display_name,
                    lot=_(' (batch %s)', lot.name) if lot else '',
                    qty=qty, avail=available))

    # ------------------------------------------------------------------
    # FEFO batch allocation
    # ------------------------------------------------------------------
    def _get_fefo_lots(self, product, location, today):
        """[(lot, free_qty)] of non-expired batches, earliest expiry first."""
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
        ])
        free_by_lot = defaultdict(float)
        for quant in quants:
            free_by_lot[quant.lot_id] += quant.quantity - quant.reserved_quantity
        lots = [(lot, qty) for lot, qty in free_by_lot.items()
                if qty > 0 and not self._is_lot_expired(lot, today)]
        lots.sort(key=lambda item: (
            item[0].expiration_date is None,
            item[0].expiration_date or datetime.min,
            item[0].id))
        return lots

    def _allocate_lots(self):
        """Fill the batch on lines that have none; split lines across batches."""
        self.ensure_one()
        location = self.warehouse_id.lot_stock_id
        today = fields.Date.context_today(self)
        taken = defaultdict(float)      # (product_id, lot_id) -> qty already committed
        for line in self.line_ids.filtered('lot_id'):
            taken[(line.product_id.id, line.lot_id.id)] += line.quantity
        candidates = {}
        pending = self.line_ids.filtered(
            lambda l: not l.lot_id and l.product_id.tracking != 'none')
        for line in pending:
            product = line.product_id
            rounding = product.uom_id.rounding
            if product.id not in candidates:
                candidates[product.id] = self._get_fefo_lots(product, location, today)
            allocations = []
            remaining = line.quantity
            for lot, available in candidates[product.id]:
                free = available - taken[(product.id, lot.id)]
                if float_compare(free, 0.0, precision_rounding=rounding) <= 0:
                    continue
                qty = min(free, remaining)
                allocations.append((lot, qty))
                taken[(product.id, lot.id)] += qty
                remaining -= qty
                if float_is_zero(remaining, precision_rounding=rounding):
                    remaining = 0.0
                    break
            if float_compare(remaining, 0.0, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Not enough non-expired stock for %(product)s: requested %(qty)s, '
                    'short by %(short)s.',
                    product=product.display_name, qty=line.quantity, short=remaining))
            self._apply_allocations(line, allocations)

    def _apply_allocations(self, line, allocations):
        """First batch goes on the existing line, others on copies (discount prorated)."""
        total_qty = line.quantity
        total_discount = line.discount_amount
        discount_left = total_discount
        for index, (lot, qty) in enumerate(allocations):
            is_last = index == len(allocations) - 1
            discount = discount_left if is_last else self.currency_id.round(
                total_discount * qty / total_qty)
            discount_left -= discount
            vals = {'lot_id': lot.id, 'quantity': qty, 'discount_amount': discount}
            if index == 0:
                line.write(vals)
            else:
                line.copy(vals)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def _ensure_payment(self):
        self.ensure_one()
        completed = self.payment_ids.filtered(lambda p: p.state == 'completed')
        paid = sum(completed.mapped('amount'))
        total = self.amount_total
        if not completed:
            if total > 0:
                self.env['densamed.sale.payment'].create({
                    'sale_id': self.id,
                    'amount': total,
                    'method': self.default_payment_method or 'cash',
                    'state': 'completed',
                })
        elif float_compare(paid, total, precision_rounding=self.currency_id.rounding) != 0:
            raise UserError(_(
                'The payments (%(paid)s) must equal the sale total (%(total)s).',
                paid=paid, total=total))

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------
    def _create_stock_picking(self, returning=False):
        """Create and validate the outgoing (or reverse incoming) picking."""
        self.ensure_one()
        warehouse = self.warehouse_id
        customers = self.env.ref('stock.stock_location_customers')
        if returning:
            picking_type, src, dest = warehouse.in_type_id, customers, warehouse.lot_stock_id
        else:
            picking_type, src, dest = warehouse.out_type_id, warehouse.lot_stock_id, customers

        env_sudo = self.env['stock.picking'].sudo().with_company(self.company_id).env
        picking = env_sudo['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'company_id': self.company_id.id,
        })

        lines_by_product = defaultdict(list)
        for line in self.line_ids:
            lines_by_product[line.product_id].append(line)

        moves = []
        for product, lines in lines_by_product.items():
            move = env_sudo['stock.move'].create({
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': sum(l.quantity for l in lines),
                'product_uom': product.uom_id.id,
                'picking_id': picking.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'company_id': self.company_id.id,
                'origin': self.name,
            })
            moves.append((move, lines))
        picking.action_confirm()

        for move, lines in moves:
            # Drop any automatic reservation; we set the exact batches ourselves.
            move.move_line_ids.unlink()
            qty_by_lot = defaultdict(float)
            for line in lines:
                qty_by_lot[line.lot_id] += line.quantity
            for lot, qty in qty_by_lot.items():
                env_sudo['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': src.id,
                    'location_dest_id': dest.id,
                    'lot_id': lot.id,
                    'quantity': qty,
                    'picked': True,
                    'company_id': self.company_id.id,
                })
            move.picked = True

        picking.with_context(
            skip_immediate=True, skip_backorder=True, skip_sms=True,
        ).button_validate()
        if picking.state != 'done':
            raise UserError(_('The stock transfer %s could not be validated.', picking.name))
        return picking
