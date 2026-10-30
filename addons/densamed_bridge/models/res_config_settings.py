# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    densamed_db_host = fields.Char(string='DensaMed Host', config_parameter='densamed.db.host')
    densamed_db_port = fields.Char(string='DensaMed Port', config_parameter='densamed.db.port')
    densamed_db_name = fields.Char(string='DensaMed Database', config_parameter='densamed.db.name')
    densamed_db_user = fields.Char(string='DensaMed User', config_parameter='densamed.db.user')
    densamed_db_password = fields.Char(
        string='DensaMed Password', config_parameter='densamed.db.password')
    densamed_last_sync = fields.Char(
        string='Last Sync', readonly=True, config_parameter='densamed.last_sync')

    @api.onchange('densamed_db_port')
    def _onchange_densamed_db_port(self):
        # keep it numeric-ish; stored as text in ir.config_parameter
        if self.densamed_db_port:
            self.densamed_db_port = ''.join(c for c in self.densamed_db_port if c.isdigit())

    def action_test_densamed_connection(self):
        self.ensure_one()
        self.execute()  # persist parameters before probing
        msg = self.env['densamed.connection'].action_test_connection()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'title': 'DensaMed Bridge',
                       'message': msg, 'sticky': False},
        }

    def action_sync_densamed_now(self):
        self.ensure_one()
        self.execute()
        report = self.env['densamed.sync'].sync_all()
        msg = ', '.join('%s: %s' % (k, v) for k, v in report.items())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'title': 'DensaMed sync finished',
                       'message': msg or 'Nothing to do.', 'sticky': True},
        }
