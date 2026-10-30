# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ---- DensaMed mapping keys (SQL-level uniqueness, safe across Odoo restarts)
    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, index=True, readonly=True, copy=False)
    _sql_constraints = [
        ('densamed_product_uniq',
         'unique(densamed_model, densamed_id)',
         'A product template can only map to one DensaMed medicine row.'),
    ]

    # ---- Mirrored pharma attributes
    generic_name = fields.Char(string='Generic Name', readonly=True, copy=False)
    dosage_form = fields.Char(string='Dosage Form', readonly=True, copy=False)
    manufacturer_ref = fields.Char(string='Manufacturer (DensaMed)', readonly=True, copy=False)
    requires_prescription = fields.Boolean(string='Requires Prescription', readonly=True, copy=False)
    min_stock = fields.Integer(string='Min. Stock (DensaMed)', readonly=True, copy=False)
    densamed_source = fields.Char(
        string='DensaMed Source', compute='_compute_densamed_source', store=True)

    def _compute_densamed_source(self):
        for tmpl in self:
            tmpl.densamed_source = (
                'medicines#%d' % tmpl.densamed_id if tmpl.densamed_id else '')
