# -*- coding: utf-8 -*-
"""Read-only psycopg2 access to the *densamed* database.

Connection parameters come from environment variables (injected by docker-compose)
and can be overridden per-database in ir.config_parameter (Settings panel).
Every query exposed here is a SELECT — the bridge never mutates operational data.
"""
import logging
import os

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - dependency declared in the manifest
    psycopg2 = None
    RealDictCursor = None


ENV_MAP = {
    'densamed.db.host': 'DENSAMED_DB_HOST',
    'densamed.db.port': 'DENSAMED_DB_PORT',
    'densamed.db.name': 'DENSAMED_DB_NAME',
    'densamed.db.user': 'DENSAMED_DB_USER',
    'densamed.db.password': 'DENSAMED_DB_PASSWORD',
}
DEFAULTS = {
    'densamed.db.host': 'db',
    'densamed.db.port': '5432',
    'densamed.db.name': 'densamed',
    'densamed.db.user': 'odoo',
    'densamed.db.password': '',
}


class DensamedConnection(models.AbstractModel):
    _name = 'densamed.connection'
    _description = 'DensaMed PostgreSQL Connection (read-only)'

    @api.model
    def _params(self):
        """ir.config_parameter wins over env vars; env vars win over defaults."""
        icp = self.env['ir.config_parameter'].sudo()
        out = {}
        for key, envvar in ENV_MAP.items():
            value = icp.get_param(key) or os.environ.get(envvar) or DEFAULTS[key]
            out[key] = str(value)
        return out

    @api.model
    def _connect(self):
        if psycopg2 is None:
            raise UserError(self.env._(
                "The python package 'psycopg2' is not installed inside the Odoo container. "
                "Install it or use the official odoo:17.0 image which ships it."))
        p = self._params()
        try:
            conn = psycopg2.connect(
                host=p['densamed.db.host'],
                port=int(p['densamed.db.port']),
                dbname=p['densamed.db.name'],
                user=p['densamed.db.user'],
                password=p['densamed.db.password'],
                connect_timeout=10,
                application_name='odoo_densamed_bridge',
            )
        except psycopg2.Error as exc:
            _logger.error("DensaMed connection failed: %s", exc)
            raise UserError(self.env._(
                "Cannot reach the DensaMed database '%(db)s' on %(host)s:%(port)s (%s)")
                % {'db': p['densamed.db.name'], 'host': p['densamed.db.host'],
                   'port': p['densamed.db.port'], 'err': exc}) from exc
        # Hard guarantee: this connection may only read, and must never idle in
        # a transaction holding locks on the operational schema.
        conn.set_session(readonly=True, autocommit=True)
        return conn

    @api.model
    def fetchall(self, query, params=None):
        """Run a SELECT against densamed and return a list of dicts."""
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cr:
                cr.execute(query, params or ())
                return cr.fetchall()
        finally:
            conn.close()

    @api.model
    def action_test_connection(self):
        """Used by the Settings button; returns a human-readable status string."""
        rows = self.fetchall(
            "SELECT current_database() AS db, "
            "       (SELECT count(*) FROM public.medicines) AS medicines, "
            "       (SELECT count(*) FROM public.warehouses) AS warehouses, "
            "       (SELECT count(*) FROM public.storage_locations) AS locations, "
            "       (SELECT count(*) FROM public.medicine_batches) AS batches"
        )
        r = rows[0]
        return self.env._(
            "Connected to '%(db)s': %(m)s medicines, %(w)s warehouses, "
            "%(l)s storage locations, %(b)s batches.") % {
            'db': r['db'], 'm': r['medicines'], 'w': r['warehouses'],
            'l': r['locations'], 'b': r['batches']}

    # ------------------------------------------------------------------
    # Source queries (READ-ONLY). Column order matches the sync mappers.
    # ------------------------------------------------------------------
    SQL_MEDICINES = """
        SELECT m.medicine_id,
               m.barcode,
               m.trade_name,
               m.generic_name,
               c.category_name,
               f.manufacturer_name,
               m.dosage_form,
               m.strength,
               m.unit_of_measure,
               m.retail_price,
               m.requires_prescription,
               m.min_stock,
               m.is_active
          FROM public.medicines m
          LEFT JOIN public.categories c     USING (category_id)
          LEFT JOIN public.manufacturers f  USING (manufacturer_id)
         ORDER BY m.medicine_id
    """

    SQL_WAREHOUSES = """
        SELECT w.warehouse_id,
               w.warehouse_name,
               w.location_description,
               b.branch_code,
               b.branch_name,
               b.city,
               w.branch_id
          FROM public.warehouses w
          JOIN public.branches b USING (branch_id)
         ORDER BY w.warehouse_id
    """

    SQL_STORAGE_LOCATIONS = """
        SELECT l.location_id,
               l.warehouse_id,
               l.parent_id,
               l.location_code,
               l.location_type,
               l.is_active
          FROM public.storage_locations l
      ORDER BY l.warehouse_id, l.location_id
    """

    # One row per batch: the warehouse where that batch is currently held
    # (largest on-hand balance wins; ties break on lowest warehouse_id).
    # LEFT() keeps the result identical whether or not inventory.location_id
    # exists yet (added by initdb/sql/99-inventory-control.sql).
    SQL_BATCHES = """
        SELECT mb.batch_id,
               mb.medicine_id,
               mb.batch_number,
               mb.expiry_date,
               mb.manufacture_date,
               mb.purchase_price,
               mb.received_date,
               (SELECT i.warehouse_id
                  FROM public.inventory i
                 WHERE i.batch_id = mb.batch_id
                 GROUP BY i.warehouse_id
                 ORDER BY SUM(i.quantity_on_hand) DESC, i.warehouse_id
                 LIMIT 1) AS warehouse_id,
               (SELECT LEFT(COALESCE(SUM(i.quantity_on_hand), 0)::text, 20)
                  FROM public.inventory i
                 WHERE i.batch_id = mb.batch_id) AS qty_on_hand
          FROM public.medicine_batches mb
      ORDER BY mb.batch_id
    """

    @api.model
    def get_medicines(self):
        return self.fetchall(self.SQL_MEDICINES)

    @api.model
    def get_warehouses(self):
        return self.fetchall(self.SQL_WAREHOUSES)

    @api.model
    def get_storage_locations(self):
        return self.fetchall(self.SQL_STORAGE_LOCATIONS)

    @api.model
    def get_batches(self):
        return self.fetchall(self.SQL_BATCHES)
