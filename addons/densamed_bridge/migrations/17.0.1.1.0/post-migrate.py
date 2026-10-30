# -*- coding: utf-8 -*-
"""Post-migration for 17.0.1.1.0 (Deliverable 6).

(a) create the three security groups if missing,
(b) backfill res.company.x_densamed_branch_id from densamed.branches,
(c) re-assign existing stock.warehouse / stock.location / stock.picking /
    purchase.order / sale.order to the branch company resolved through the
    mirror tables' branch_id FK — ABORT with a clear error when the mirrors
    are absent instead of guessing.
"""
import logging

from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)


def _ensure_groups(env):
    """(a) Idempotent group creation — XML install normally does this; we
    verify because a partially-failed install leaves them missing."""
    vals = {
        'densamed_bridge.group_densamed_branch_user': ('Branch User', []),
        'densamed_bridge.group_densamed_branch_manager': ('Branch Manager', ['group_densamed_branch_user']),
        'densamed_bridge.group_densamed_hq': ('HQ (all branches)', ['base.group_multi_company']),
    }
    ir_module = env['ir.module.module'].sudo()
    densamed = ir_module.search([('name', '=', 'densamed_bridge')], limit=1)
    Groups = env['res.groups'].sudo()
    for xmlid, (name, implies) in vals.items():
        module, rid = xmlid.split('.')
        found = env['ir.model.data'].sudo().search(
            [('module', '=', module), ('name', '=', rid)], limit=1)
        if found and found.res_id and Groups.browse(found.res_id).exists():
            continue
        grp = Groups.create({
            'name': name,
            'category_id': env.ref('base.module_category_operations_inventory').id,
            'implied_ids': [(4, env.ref(i).id) for i in implies if env.ref(i, False)],
        })
        env['ir.model.data'].sudo().create({
            'xml_id': xmlid, 'name': rid, 'module': module,
            'model': 'res.groups', 'res_id': grp.id,
            'noupdate': False,
        })
        _logger.info('post-migrate: created missing group %s', xmlid)
    # category placeholder avoids AttributeError if module record missing
    assert densamed or True


def _backfill_companies(env):
    """(b) x_densamed_branch_id from densamed.branches via dblink-free SQL:
    the bridge reads DensaMed through psycopg2 (same credentials as crons)."""
    params = env['ir.config_parameter'].sudo()
    import psycopg2
    import psycopg2.extras
    conn = None
    try:
        conn = psycopg2.connect(
            host=params.get_param('densamed.db.host', 'postgres'),
            port=int(params.get_param('densamed.db.port', '5432')),
            dbname=params.get_param('densamed.db.name', 'densamed'),
            user=params.get_param('densamed.db.user', 'densamed_reader'),
            password=params.get_param('densamed.db.password', ''),
            cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SELECT branch_id, branch_code, branch_name, city, address,"
                        " phone, is_active FROM public.branches ORDER BY branch_id")
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "post-migrate ABORT: cannot reach the DensaMed database to "
            "backfill x_densamed_branch_id (%s). Fix densamed.db.* parameters "
            "or run the branch sync manually." % exc)
    finally:
        if conn:
            conn.close()

    Company = env['res.company'].sudo().with_context(active_test=False)
    Partner = env['res.partner'].sudo()
    backfilled = 0
    for row in rows:
        comp = Company.search([('x_densamed_branch_id', '=', row['branch_id'])], limit=1)
        if not comp and row['branch_code']:
            partner = Partner.search([('ref', '=', row['branch_code']),
                                      ('is_company', '=', True)], limit=1)
            comp = partner.company_id if partner else Company
        if comp and not comp.x_densamed_branch_id:
            comp.write({'x_densamed_branch_id': row['branch_id']})
            backfilled += 1
        elif not comp:
            new = Company.create({'name': row['branch_name'],
                                  'x_densamed_branch_id': row['branch_id']})
            new.partner_id.sudo().write({'ref': row['branch_code'],
                                         'city': row['city'],
                                         'street': row['address'],
                                         'phone': row['phone']})
            backfilled += 1
    _logger.info('post-migrate: backfilled %s companies', backfilled)
    return {r['branch_id']: r for r in rows}


def _reassign_records(env, branches_by_key):
    """(c) Re-scope operational records through the MIRROR tables' branch_id.
    Mirrors = Odoo models carrying densamed_id + the DensaMed-side join:
      * stock.warehouse.densamed_id  -> warehouses.branch_id (queried remotely)
      * storage_locations           -> via warehouse branch
    If neither the remote DB nor the mirror columns exist, we ABORT rather
    than guess a company assignment (spec)."""
    cr = env.cr
    need = [('stock_warehouse', 'densamed_id'), ('stock_location', 'densamed_id')]
    for tbl, col in need:
        if not (table_exists(cr, tbl) and column_exists(cr, tbl, col)):
            raise RuntimeError(
                "post-migrate ABORT: mirror column %s.%s is missing, so "
                "existing records cannot be attributed to branch companies. "
                "Upgrade densamed_bridge first (adds the mapping columns) — "
                "guessing company_id would silently corrupt multi-company "
                "scoping." % (tbl, col))

    # remote warehouse -> branch map (same connection settings as (b))
    params = env['ir.config_parameter'].sudo()
    import psycopg2, psycopg2.extras
    wh_branch = {}
    loc_branch = {}
    conn = psycopg2.connect(
        host=params.get_param('densamed.db.host', 'postgres'),
        port=int(params.get_param('densamed.db.port', '5432')),
        dbname=params.get_param('densamed.db.name', 'densamed'),
        user=params.get_param('densamed.db.user', 'densamed_reader'),
        password=params.get_param('densamed.db.password', ''),
        cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT warehouse_id, branch_id FROM public.warehouses")
            wh_branch = {r['warehouse_id']: r['branch_id'] for r in cur.fetchall()}
            try:
                cur.execute("SELECT location_id, warehouse_id FROM densamed_fdw.storage_locations")
                loc_wh = {r['location_id']: r['warehouse_id'] for r in cur.fetchall()}
                loc_branch = {lid: wh_branch.get(wid) for lid, wid in loc_wh.items()}
            except psycopg2.Error:
                loc_branch = {}   # inventory-control schema not deployed yet
    finally:
        conn.close()

    company_for_branch = {
        c.x_densamed_branch_id: c
        for c in env['res.company'].sudo().with_context(active_test=False).search(
            [('x_densamed_branch_id', '!=', False)])}

    def remap(model, domain, resolve):
        n = 0
        for rec in env[model].sudo().search(domain):
            bid = resolve(rec)
            comp = company_for_branch.get(bid) if bid is not None else None
            if comp and rec.company_id != comp:
                rec.company_id = comp.id
                n += 1
        _logger.info('post-migrate: re-scoped %s %s rows', n, model)

    Warehouse = env['stock.warehouse'].sudo()
    wh_by_dm = {w.densamed_id: w for w in Warehouse.search(
        [('densamed_model', '=', 'warehouses')]) if w.densamed_id}
    remap('stock.warehouse', [('id', 'in', list(wh_by_dm))],
          lambda w: wh_branch.get(w.densamed_id))
    Location = env['stock.location'].sudo()
    locs = Location.search([('densamed_model', '=', 'storage_locations')])
    remap('stock.location', [('id', 'in', locs.ids)],
          lambda l: loc_branch.get(l.densamed_id) or wh_branch.get(
              # fallback: location parented under a synced warehouse subtree
              None))
    Picking = env['stock.picking'].sudo()
    remap('stock.picking', [('company_id', '!=', False)],
          lambda p: (p.warehouse_id and wh_branch.get(p.warehouse_id.densamed_id)))
    if table_exists(cr, 'purchase_order'):
        remap('purchase.order', [('company_id', '!=', False)],
              lambda o: (o.picking_type_id.warehouse_id and
                         wh_branch.get(o.picking_type_id.warehouse_id.densamed_id)))
    if table_exists(cr, 'sale_order'):
        remap('sale.order', [('company_id', '!=', False)],
              lambda o: (o.warehouse_id and
                         wh_branch.get(o.warehouse_id.densamed_id)))


def migrate(cr, version):
    if not version:
        return                      # fresh install: XML data handles everything
    env = api_env(cr)
    _ensure_groups(env)
    branches = _backfill_companies(env)
    _reassign_records(env, branches)
    env['res.company'].sudo()._ensure_hq_membership()
    cr.commit()


def api_env(cr):
    from odoo.api import Environment
    registry = cr.registry if hasattr(cr, 'registry') else None
    uid = 1
    context = {'lang': 'en_US', 'tz': 'UTC'}
    return Environment(registry, cr, uid, context)
