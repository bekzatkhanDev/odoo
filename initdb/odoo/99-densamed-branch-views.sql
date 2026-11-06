-- =============================================================================
-- initdb/odoo/99-densamed-branch-views.sql
-- Runs in the ODOO database (initdb phase 3, after the odoo template DB is
-- created; mount this directory at /docker-entrypoint-initdb.d/odoo and apply
-- with:  psql -v ON_ERROR_STOP=1 -d odoo -f <file>).
-- Idempotent; safe before module install thanks to IF NOT EXISTS / OR REPLACE.
-- =============================================================================

SET client_encoding = 'UTF8';

-- -----------------------------------------------------------------------------
-- branch_scoped_stock_view: on-hand per branch (= company) built from the
-- standard Odoo tables. Filtered to companies carrying the DensaMed join key.
-- SELECT granted to the `odoo` db role ONLY.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.branch_scoped_stock_view AS
SELECT
    rc.x_densamed_branch_id          AS branch_id,
    rc.name                          AS branch_name,
    rp.ref                           AS branch_code,
    sl.id                            AS location_id,
    sl.name                          AS location_name,
    sw.id                            AS warehouse_id,
    sw.name                          AS warehouse_name,
    q.product_id                     AS product_product_id,
    pt.name                          AS product_name,
    l.name                           AS lot_name,
    l.expiration_date                AS expiry_date,
    sum(q.quantity)                  AS quantity_on_hand
  FROM stock_quant q
  JOIN stock_location sl           ON sl.id = q.location_id
  JOIN res_company rc              ON rc.id = COALESCE(q.company_id, sl.company_id)
  LEFT JOIN res_partner rp         ON rp.id = rc.partner_id
  LEFT JOIN stock_warehouse sw     ON sw.view_location_id = sl.id
                                   OR sw.lot_stock_id    = sl.id
  LEFT JOIN stock_lot l            ON l.id = q.lot_id
  LEFT JOIN product_product pp     ON pp.id = q.product_id
  LEFT JOIN product_template pt    ON pt.id = pp.product_tmpl_id
 WHERE rc.x_densamed_branch_id IS NOT NULL
   AND sl.usage = 'internal'
 GROUP BY rc.x_densamed_branch_id, rc.name, rp.ref,
          sl.id, sl.name, sw.id, sw.name,
          q.product_id, pt.name, l.name, l.expiration_date;

-- Role-based access: the odoo application role reads it; nobody else.
-- (CREATE ROLE odoo is owned by your provisioning; we do not create it here.)
GRANT SELECT ON public.branch_scoped_stock_view TO odoo;

-- -----------------------------------------------------------------------------
-- branch_dashboard_v — backing view for densamed_bridge.branch_dashboard
-- (_auto=False ORM model). Plain VIEW chosen over postgres_fdw/MATERIALIZED:
-- all inputs live in THIS database; refresh latency would add nothing.
-- (models/branch_dashboard.py recreates the same definition at module load;
-- shipped here too so DBAs can query it directly.)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.branch_dashboard_v AS
SELECT
    c.id                                    AS id,
    p.ref                                   AS branch_code,
    c.name                                  AS branch_name,
    c.active                                AS branch_active,
    (SELECT count(*) FROM stock_warehouse w
      WHERE w.company_id = c.id AND w.active)          AS warehouse_count,
    (SELECT count(*) FROM stock_lot l
      WHERE l.expiration_date IS NOT NULL
        AND l.expiration_date <= CURRENT_DATE + 30)    AS lots_expiring_30,
    (SELECT count(*) FROM stock_lot l
      WHERE l.expiration_date IS NOT NULL
        AND l.expiration_date <= CURRENT_DATE + 60)    AS lots_expiring_60,
    (SELECT count(*) FROM stock_lot l
      WHERE l.expiration_date IS NOT NULL
        AND l.expiration_date <= CURRENT_DATE + 90)    AS lots_expiring_90,
    COALESCE((SELECT count(*) FROM purchase_order po
               WHERE po.company_id = c.id
                 AND po.state NOT IN ('purchase','cancel','done')), 0) AS open_po_count,
    COALESCE((SELECT count(*) FROM sale_order so
               WHERE so.company_id = c.id
                 AND so.state NOT IN ('sale','cancel','done')), 0)     AS open_so_count,
    COALESCE((SELECT sum(q.quantity)
                FROM stock_quant q
                JOIN stock_location sl ON sl.id = q.location_id
               WHERE sl.usage = 'internal'
                 AND q.company_id = c.id), 0)          AS qty_on_hand
  FROM res_company c
  LEFT JOIN res_partner p ON p.id = c.partner_id
 WHERE c.x_densamed_branch_id IS NOT NULL;

GRANT SELECT ON public.branch_dashboard_v TO odoo;
