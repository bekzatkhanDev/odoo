# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

PAYMENT_METHODS = [
    ('cash', 'Cash'),
    ('card', 'Card'),
    ('bank_transfer', 'Bank transfer'),
    ('other', 'Other'),
]

PAYMENT_STATES = [
    ('pending', 'Pending'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
    ('refunded', 'Refunded'),
]


class DensamedSalePayment(models.Model):
    """Mirrors densamed.payments rows that belong to a sale."""
    _name = 'densamed.sale.payment'
    _description = 'Pharmacy Sale Payment'
    _order = 'date, id'

    sale_id = fields.Many2one(
        'densamed.sale', string='Sale', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='sale_id.company_id', store=True, index=True, readonly=True)
    currency_id = fields.Many2one(related='sale_id.currency_id', readonly=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    amount = fields.Monetary(required=True)
    method = fields.Selection(PAYMENT_METHODS, string='Method', required=True, default='cash')
    state = fields.Selection(PAYMENT_STATES, string='Status', required=True, default='completed')

    _sql_constraints = [
        ('amount_positive', 'CHECK(amount > 0)', 'A payment amount must be greater than zero.'),
    ]

    def write(self, vals):
        # Status changes (refund on return) are allowed at any time; money fields are not.
        if {'amount', 'method', 'sale_id', 'date'} & set(vals) \
                and any(p.sale_id.state != 'draft' for p in self):
            raise UserError(_('Payments can only be changed while the sale is a draft.'))
        return super().write(vals)

    def unlink(self):
        if any(p.sale_id.state != 'draft' for p in self):
            raise UserError(_('Payments can only be deleted while the sale is a draft.'))
        return super().unlink()
