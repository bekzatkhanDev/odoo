# -*- coding: utf-8 -*-
"""Branch dashboard (Deliverable 3).

APPROACH CHOSEN — plain SQL VIEW + _auto=False ORM wrapper, NOT a materialised
view, and NOT postgres_fdw. Reasoning:
  * postgres_fdw would need CREATE SERVER / USER MAPPING to reach another
    database on the SAME instance; all tables we aggregate (stock_lot,
    stock_quant, purchase_order, sale_order) live in the ODOO database anyway.
  * A materialised view adds REFRESH latency + an extra cron for no gain at
    pharmacy row counts; a live VIEW is never stale and costs four indexed
    sub-counts per branch row.
  * Odoo reads it through a Model with _auto = False exactly like its own
    reporting models (e.g. stock.report_lot_location).
The same DDL is shipped raw in sql/branch_scoped_stock_view.sql for DBAs.
"""
from odoo import fields, models, tools


class DensamedBranchDashboard(models.Model):
    _name = 'densamed_bridge.branch_dashboard'
    _description = 'DensaMed Branch Dashboard'
    _auto = False
    _table = 'densamed_branch_dashboard_v'
    _order = 'branch_code'

    id = fields.BigInt(string='Company ID', readonly=True)          # res.company.id
    branch_code = fields.Char(readonly=True)
    branch_name = fields.Char(readonly=True)
    branch_active = fields.Boolean(readonly=True)
    warehouse_count = fields.Integer(readonly=True, string='Active Warehouses')
    lots_expiring_30 = fields.Integer(readonly=True, string='Lots Expiring ≤30d')
    lots_expiring_60 = fields.Integer(readonly=True, string='Lots Expiring ≤60d')
    lots_expiring_90 = fields.Integer(readonly=True, string='Lots Expiring ≤90d')
    open_po_count = fields.Integer(readonly=True, string='Open Purchase Orders')
    open_so_count = fields.Integer(readonly=True, string='Open Sales Orders')
    qty_on_hand = fields.Float(readonly=True, string='Total On Hand')

    def init(self):
        """Create/replace the backing view at module (re)load.

        Optional-module guard: purchase.order / sale.order tables exist only if
        `purchase` / `sale_management` are installed; the view is assembled
        dynamically and substitutes literal 0 when a table is absent, so the
        bridge stays installable on an inventory-only database.
        """
        cr = self.env.cr
        tools.drop_view_if_exists(cr, self._table)

        def table_exists(name):
            cr.execute("SELECT to_regclass(%s) IS NOT NULL", ('public.' + name,))
            return cr.fetchone()[0]

        po = ("(SELECT count(*) FROM purchase_order po"
              " WHERE po.company_id = c.id"
              " AND po.state NOT IN ('purchase','cancel','done'))"
              if table_exists('purchase_order') else "0")
        so = ("(SELECT count(*) FROM sale_order so"
              " WHERE so.company_id = c.id"
              " AND so.state NOT IN ('sale','cancel','done'))"
              if table_exists('sale_order') else "0")

        cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    c.id                                    AS id,
                    p.ref                                   AS branch_code,
                    c.name                                  AS branch_name,
                    c.active                                AS branch_active,
                    (SELECT count(*) FROM stock_warehouse w
                      WHERE w.company_id = c.id AND w.active)          AS warehouse_count,
                    -- Lots are company-scoped through their product; products
                    -- synced by this bridge stay GLOBAL (company_id unset), so
                    -- every branch sees them (spec Deliverable 2). Counting
                    -- all lots here matches that global product master.
                    (SELECT count(*) FROM stock_lot l
                      WHERE l.expiration_date IS NOT NULL
                        AND l.expiration_date <= CURRENT_DATE + 30)    AS lots_expiring_30,
                    (SELECT count(*) FROM stock_lot l
                      WHERE l.expiration_date IS NOT NULL
                        AND l.expiration_date <= CURRENT_DATE + 60)    AS lots_expiring_60,
                    (SELECT count(*) FROM stock_lot l
                      WHERE l.expiration_date IS NOT NULL
                        AND l.expiration_date <= CURRENT_DATE + 90)    AS lots_expiring_90,
                    %s                                      AS open_po_count,
                    %s                                      AS open_so_count,
                    COALESCE((SELECT sum(q.quantity)
                                FROM stock_quant q
                                JOIN stock_location sl ON sl.id = q.location_id
                               WHERE sl.usage = 'internal'
                                 AND q.company_id = c.id), 0)          AS qty_on_hand
                  FROM res_company c
                  LEFT JOIN res_partner p ON p.id = c.partner_id
                 WHERE c.x_densamed_branch_id IS NOT NULL
            )
        """ % (self._table, po, so))
