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

    # Master switch for ALL bridge crons. Default False: crons ship active=True
    # but run_job() logs state='skipped' and touches nothing until an admin
    # flips this — protects a fresh/demo database from surprise writes.
    densamed_enable_sync = fields.Boolean(
        string='Enable DensaMed sync crons',
        config_parameter='densamed_bridge.enable_sync',
        default=False)

    @api.onchange('densamed_db_port')
    def _onchange_densamed_db_port(self):
        if self.densamed_db_port:
            self.densamed_db_port = ''.join(c for c in self.densamed_db_port if c.isdigit())

    def action_test_densamed_connection(self):
        self.ensure_one()
        self.execute()
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
        Runner = self.env['densamed.job_runner']
        Sync = self.env['densamed.sync']
        report = {}
        # ordered by dependency; each goes through run_job -> savepoint + log
        for name, fn in (
            ('branches', Sync.cron_sync_branches),
            ('jobs', Sync.cron_sync_jobs),
            ('employees', Sync.cron_sync_employees),
            ('products', Sync.cron_sync_products),
            ('warehouses', Sync.cron_sync_warehouses),
            ('locations', Sync.cron_sync_locations),
            ('lots', Sync.cron_sync_lots),
        ):
            log = fn()
            report[name] = '%s c=%s u=%s s=%s' % (
                log.state, log.rows_created, log.rows_updated, log.rows_skipped)
        msg = ', '.join('%s: %s' % (k, v) for k, v in report.items())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'title': 'DensaMed sync finished',
                       'message': msg or 'Nothing to do.', 'sticky': True},
        }
