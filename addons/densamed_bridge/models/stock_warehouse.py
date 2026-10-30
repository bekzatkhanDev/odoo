# -*- coding: utf-8 -*-
"""warehouses -> stock.warehouse, company-scoped through the branch map.

Deliverable 2 requirement: every synced warehouse must carry the correct
company_id. warehouses.branch_id is resolved via
densamed.connection._branch_company_map() (x_densamed_branch_id join key).
Rows whose branch company is INACTIVE are skipped entirely (spec Deliverable 4)
and never reactivated by the sync.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, readonly=True, copy=False,
                                 default='warehouses')
    _sql_constraints = [
        ('densamed_warehouse_uniq',
         'unique(densamed_model, densamed_id)',
         'A warehouse can only map to one DensaMed warehouses row.'),
    ]

    branch_code = fields.Char(string='Branch Code', readonly=True, copy=False)
    location_description = fields.Text(string='Location Description',
                                       readonly=True, copy=False)
    x_densamed_branch_id = fields.Integer(
        string='DensaMed Branch ID', related='company_id.x_densamed_branch_id',
        store=True, readonly=True, index=True)

    @api.model
    def create(self, vals):
        """Force company scoping on creation even if a caller forgets:
        derive from the mapped branch when possible."""
        if vals.get('densamed_id') and not vals.get('company_id'):
            comp = self.env['res.company'].sudo().search(
                [('x_densamed_branch_id', '=', vals.get('densamed_branch_id') or -1)],
                limit=1)
            if comp:
                vals['company_id'] = comp.id
        return super().create(vals)
