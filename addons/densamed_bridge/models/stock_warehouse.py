# -*- coding: utf-8 -*-
from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, readonly=True, copy=False, default='warehouses')
    _sql_constraints = [
        ('densamed_warehouse_uniq',
         'unique(densamed_model, densamed_id)',
         'A warehouse can only map to one DensaMed warehouses row.'),
    ]

    branch_code = fields.Char(string='Branch Code', readonly=True, copy=False)
    location_description = fields.Text(string='Location Description', readonly=True, copy=False)
