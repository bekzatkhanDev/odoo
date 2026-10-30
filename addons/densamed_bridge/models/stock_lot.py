# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, readonly=True, copy=False,
                                 default='medicine_batches')
    _sql_constraints = [
        ('densamed_lot_uniq',
         'unique(densamed_model, densamed_id)',
         'A lot can only map to one DensaMed medicine_batches row.'),
    ]

    # Warehouse the batch is held in inside the operational schema. Informational
    # only: the bridge never creates stock.quant / stock.move records.
    densamed_warehouse_id = fields.Many2one(
        'stock.warehouse', string='DensaMed Warehouse',
        readonly=True, copy=False, index=True)
    purchase_price = fields.Float(string='Batch Purchase Price', readonly=True, copy=False)
    days_to_expiry = fields.Integer(
        string='Days To Expiry', compute='_compute_days_to_expiry', store=True)

    @api.depends('expiration_date')
    def _compute_days_to_expiry(self):
        today = fields.Date.today()
        for lot in self:
            lot.days_to_expiry = (
                (lot.expiration_date - today).days if lot.expiration_date else -1)
