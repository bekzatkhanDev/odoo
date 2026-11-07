# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class DensamedSaleLine(models.Model):
    """Mirrors densamed.sale_items: one medicine batch sold on one receipt."""
    _name = 'densamed.sale.line'
    _description = 'Pharmacy Sale Line'
    _order = 'sale_id, id'

    sale_id = fields.Many2one(
        'densamed.sale', string='Sale', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='sale_id.company_id', store=True, index=True, readonly=True)
    currency_id = fields.Many2one(related='sale_id.currency_id', readonly=True)
    date = fields.Datetime(related='sale_id.date', store=True, readonly=True)
    state = fields.Selection(related='sale_id.state', store=True, readonly=True)

    product_id = fields.Many2one(
        'product.product', string='Medicine', required=True,
        domain="[('type', '=', 'product'), ('sale_ok', '=', True)]")
    product_uom_id = fields.Many2one(related='product_id.uom_id', readonly=True)
    requires_prescription = fields.Boolean(
        related='product_id.requires_prescription', readonly=True)
    lot_id = fields.Many2one(
        'stock.lot', string='Batch', copy=False,
        domain="[('product_id', '=', product_id)]",
        help='Leave empty: the batch is chosen automatically by FEFO '
             '(earliest expiry first) when the sale is completed.')
    expiration_date = fields.Datetime(
        related='lot_id.expiration_date', string='Expiry', readonly=True)
    available_qty = fields.Float(
        string='Available', compute='_compute_available_qty',
        digits='Product Unit of Measure',
        help='On hand minus reserved in the sale warehouse (for the chosen batch, '
             'or all batches when none is chosen).')

    quantity = fields.Float(
        string='Quantity', required=True, default=1.0, digits='Product Unit of Measure')
    price_unit = fields.Float(string='Unit Price', required=True, digits='Product Price')
    discount_amount = fields.Monetary(string='Discount', default=0.0)
    discount_percent = fields.Float(string='Discount %', default=0.0, digits=(5, 2))
    cost_unit = fields.Float(string='Cost at Sale', digits='Product Price', copy=False,
                             readonly=True, help='Snapshot of standard cost at checkout.')
    margin_amount = fields.Monetary(string='Gross Profit', compute='_compute_margin', store=True)
    subtotal = fields.Monetary(string='Subtotal', compute='_compute_subtotal', store=True)

    # ------------------------------------------------------------------
    @api.depends('quantity', 'price_unit', 'discount_amount', 'discount_percent')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit * (1 - line.discount_percent / 100.0) - line.discount_amount

    @api.depends('subtotal', 'quantity', 'cost_unit')
    def _compute_margin(self):
        for line in self:
            line.margin_amount = line.subtotal - line.quantity * line.cost_unit

    @api.depends('product_id', 'lot_id' , 'sale_id.warehouse_id')
    def _compute_available_qty(self):
        Quant = self.env['stock.quant'].sudo()
        for line in self:
            warehouse = line.sale_id.warehouse_id
            if not line.product_id or not warehouse:
                line.available_qty = 0.0
                continue
            line.available_qty = Quant._get_available_quantity(
                line.product_id, warehouse.lot_stock_id,
                lot_id=line.lot_id or None)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.lst_price
            self.lot_id = False

    # ------------------------------------------------------------------
    @api.constrains('quantity', 'price_unit', 'discount_amount', 'discount_percent')
    def _check_amounts(self):
        for line in self:
            rounding = line.product_uom_id.rounding or 0.01
            if float_compare(line.quantity, 0.0, precision_rounding=rounding) <= 0:
                raise ValidationError(_('Quantity must be greater than zero.'))
            if line.price_unit < 0:
                raise ValidationError(_('Unit price cannot be negative.'))
            if not 0 <= line.discount_percent <= 100:
                raise ValidationError(_('Discount percentage must be between 0 and 100.'))
            if line.discount_amount < 0:
                raise ValidationError(_('Discount cannot be negative.'))
            if float_compare(line.discount_amount, line.quantity * line.price_unit * (1 - line.discount_percent / 100.0),
                             precision_rounding=line.currency_id.rounding or 0.01) > 0:
                raise ValidationError(_('Discount cannot exceed the line amount.'))

    @api.constrains('lot_id', 'product_id')
    def _check_lot_product(self):
        for line in self:
            if line.lot_id and line.lot_id.product_id != line.product_id:
                raise ValidationError(_('The batch does not belong to the selected medicine.'))

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        sale_ids = [vals['sale_id'] for vals in vals_list if vals.get('sale_id')]
        if any(sale.state != 'draft' for sale in self.env['densamed.sale'].browse(sale_ids)):
            raise UserError(_('Lines can only be added while the sale is a draft.'))
        return super().create(vals_list)

    def write(self, vals):
        if any(line.sale_id.state != 'draft' for line in self):
            raise UserError(_('Lines can only be changed while the sale is a draft.'))
        return super().write(vals)

    def unlink(self):
        if any(line.sale_id.state != 'draft' for line in self):
            raise UserError(_('Lines can only be deleted while the sale is a draft.'))
        return super().unlink()
