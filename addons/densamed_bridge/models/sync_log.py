# -*- coding: utf-8 -*-
"""Sync log + job runner (Deliverable 4).

Every cron target calls run_job('<name>') which:
  * refuses to do anything unless res.config.settings.densamed_enable_sync
    (ir.config_parameter 'densamed_bridge.enable_sync') is True — crons ship
    active=True but stay inert until an admin flips the switch, so a fresh DB
    with demo data being loaded never receives surprise writes;
  * wraps the work in savepoints so one bad remote row cannot poison the batch;
  * persists ONE row here (never ir.logging — not query-friendly).
"""
import logging
from datetime import timedelta

from psycopg2.errors import UniqueViolation

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ENABLE_PARAM = 'densamed_bridge.enable_sync'


class DensamedSyncLog(models.Model):
    _name = 'densamed_bridge.sync_log'
    _description = 'DensaMed Bridge Sync Log'
    _order = 'started_at desc, id desc'

    sync_name = fields.Char(required=True, index=True)
    started_at = fields.Datetime(required=True, index=True)
    finished_at = fields.Datetime()
    duration_ms = fields.Integer(compute='_compute_duration_ms', store=True)
    rows_created = fields.Integer(default=0)
    rows_updated = fields.Integer(default=0)
    rows_skipped = fields.Integer(default=0)
    state = fields.Selection(
        [('running', 'Running'), ('success', 'Success'),
         ('skipped', 'Skipped (sync disabled)'), ('error', 'Error')],
        default='running', required=True)
    error = fields.Text()

    @api.depends('started_at', 'finished_at')
    def _compute_duration_ms(self):
        for row in self:
            if row.started_at and row.finished_at:
                delta = fields.Datetime.to_datetime(row.finished_at) \
                    - fields.Datetime.to_datetime(row.started_at)
                row.duration_ms = int(delta.total_seconds() * 1000)

    # ------------------------------------------------------------------
    @api.model
    def cron_purge_old_logs(self):
        """Nightly retention job: keep the last 30 days."""
        cutoff = fields.Datetime.now() - timedelta(days=30)
        old = self.sudo().search([('started_at', '<', cutoff)])
        n = len(old)
        old.unlink()
        _logger.info('densamed_bridge: purged %s sync_log rows older than %s', n, cutoff)
        return n


class DensamedJobRunner(models.AbstractModel):
    _name = 'densamed.job_runner'
    _description = 'DensaMed Bridge Job Runner (savepoint + log + retry)'

    # ------------------------------------------------------------------
    @api.model
    def _sync_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            ENABLE_PARAM, 'False').lower() in ('1', 'true', 'yes', 'on')

    @api.model
    def _retry_exceptions(self):
        # UniqueViolation: concurrent manual entry vs cron on medicine_batches
        # (medicine_id, batch_number) UNIQUE — see SQL addendum notes.
        return (UniqueViolation,)

    @api.model
    def run_job(self, name, fn):
        """Execute `fn(env)` under a savepoint, log the outcome, retry once on
        UniqueViolation. Returns the log row (for tests/UI)."""
        Log = self.env['densamed_bridge.sync_log']
        log = Log.create({'sync_name': name, 'started_at': fields.Datetime.now(),
                          'state': 'running'})
        if not self._sync_enabled():
            log.write({'state': 'skipped',
                       'finished_at': fields.Datetime.now(),
                       'error': "densamed_bridge.enable_sync is False — set it in "
                                "Settings > DensaMed Bridge to activate syncing."})
            return log
        for attempt in (1, 2):
            try:
                # Savepoint: a failing remote row rolls back only this job's
                # partial ORM writes, never the whole cron transaction.
                with self.env.cr.savepoint():
                    stats = fn(self.env) or {}
                log.write({'state': 'success',
                           'finished_at': fields.Datetime.now(),
                           'rows_created': stats.get('created', 0),
                           'rows_updated': stats.get('updated', 0),
                           'rows_skipped': stats.get('skipped', 0)})
                return log
            except self._retry_exceptions() as exc:
                self.env.cr.rollback()  # release aborted-transaction state
                _logger.warning('densamed_bridge job %s: UniqueViolation (attempt %s): %s',
                                name, attempt, exc)
                if attempt == 2:
                    log.write({'state': 'error',
                               'finished_at': fields.Datetime.now(),
                               'error': 'UniqueViolation after retry: %s' % exc})
                    return log
                # Upsert-mode rerun: mappers match on the densamed_* keys, so a
                # second pass converts INSERT clashes into UPDATEs.
            except Exception as exc:  # noqa: BLE001 - cron must log, not crash workers
                _logger.exception('densamed_bridge job %s failed: %s', name, exc)
                log.write({'state': 'error',
                           'finished_at': fields.Datetime.now(),
                           'error': '%s: %s' % (type(exc).__name__, exc)})
                return log
        return log
