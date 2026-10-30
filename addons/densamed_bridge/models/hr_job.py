# -*- coding: utf-8 -*-
from odoo import fields, models


class HrJob(models.Model):
    _inherit = 'hr.job'

    densamed_id = fields.Integer(index=True, readonly=True, copy=False)
    densamed_model = fields.Char(size=32, readonly=True, copy=False,
                                 default='roles')
    _sql_constraints = [
        ('densamed_job_uniq', 'unique(densamed_model, densamed_id)',
         'A job can only map to one DensaMed roles row. NOTE: a role is a JOB '
         '(what you do), never a security group (what you may see) — group '
         'assignment goes through densamed_bridge.role_group_map + the manual '
         'Apply branch roles wizard.'),
    ]
