# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # mapping keys so employees participate in the same idempotent upsert as
    # every other entity (densamed_model + densamed_id pair).
    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, readonly=True, copy=False,
                                 default='employees')
    _sql_constraints = [
        ('densamed_employee_uniq', 'unique(densamed_model, densamed_id)',
         'An employee can only map to one DensaMed employees row.'),
    ]
    x_densamed_branch_id = fields.BigInt(
        string='DensaMed Branch ID', related='company_id.x_densamed_branch_id',
        store=True, index=True, readonly=True)
