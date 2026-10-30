# -*- coding: utf-8 -*-
from odoo import fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, readonly=True, copy=False,
                                 default='storage_locations')
    _sql_constraints = [
        ('densamed_location_uniq',
         'unique(densamed_model, densamed_id)',
         'A stock location can only map to one DensaMed storage_locations row.'),
    ]

    densamed_location_type = fields.Selection(
        selection=[('zone', 'Zone'), ('aisle', 'Aisle'),
                   ('shelf', 'Shelf'), ('bin', 'Bin')],
        string='DensaMed Type', readonly=True, copy=False)
