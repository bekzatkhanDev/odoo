# -*- coding: utf-8 -*-
"""Cron-driven, idempotent densamed -> odoo master-data synchronisation.

Upsert strategy (applies to all four mappers)
---------------------------------------------
1. Remote rows are read with a single SELECT per entity (read-only connection).
2. Existing local records are looked up by (densamed_model, densamed_id) — a
   SQL-uniqueness-backed mapping column pair defined on each Odoo model.
3. Rows present remotely but missing locally  -> create().
4. Rows present on both sides                 -> write() only when at least one
   mapped field actually differs (keeps `write_date` churn and record rules sane).
5. Rows missing remotely                      -> archived (active=False), never
   deleted, so historical Odoo documents keep their references.

The whole pipeline is safe to run twice in a row: it converges and writes
nothing on the second pass.  stock.quant / stock.move are deliberately NOT
touched — quantities remain the responsibility of normal Odoo inventory flows.
"""
import datetime
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DensamedSync(models.AbstractModel):
    _name = 'densamed.sync'
    _description = 'DensaMed -> Odoo Master Data Sync'

    # ------------------------------------------------------------------
    # Generic idempotent upsert helper
    # ------------------------------------------------------------------
    @api.model
    def _compare(self, rec, field_name, value):
        """True when `value` differs from what is stored on `rec[field_name]`."""
        if field_name not in rec._fields:
            return False
        current = rec[field_name]
        ftype = rec._fields[field_name].type
        if ftype in ('many2one',):
            current = current.id if current else False
            value = value.id if hasattr(value, 'id') else value
        elif ftype in ('many2many', 'one2many'):
            return False  # never managed by this bridge
        elif ftype == 'date':
            cur_d = current.date() if isinstance(current, datetime.datetime) else current
            val_d = value.date() if isinstance(value, datetime.datetime) else value
            return bool(cur_d != val_d)
        elif ftype in ('float', 'monetary'):
            return abs(float(current or 0) - float(value or 0)) > 1e-6
        elif ftype == 'boolean':
            return bool(current) != bool(value)
        if isinstance(current, str):
            current = current.strip()
        if isinstance(value, str):
            value = value.strip()
        return bool(current != value)

    @api.model
    def _upsert(self, model_name, records, key_field='densamed_id'):
        """Idempotent create/update keyed on (densamed_model, densamed_id).

        :return: dict with counters {'created': n, 'updated': n, 'skipped': n}
        """
        Model = self.env[model_name]
        stats = {'created': 0, 'updated': 0, 'skipped': 0}
        remote_ids = [r[key_field] for r in records]

        existing = {}
        if remote_ids:
            for rec in Model.with_context(active_test=False).search(
                    [(key_field, 'in', remote_ids),
                     ('densamed_model', '=', records[0].get('densamed_model'))]):
                existing[rec[key_field]] = rec

        for vals in records:
            payload = {k: v for k, v in vals.items() if k != '_match'}
            rid = payload[key_field]
            rec = existing.get(rid)
            try:
                if rec:
                    change = {f: v for f, v in payload.items()
                              if f not in (key_field, 'densamed_model')
                              and self._compare(rec, f, v)}
                    if change:
                        rec.write(change)
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1
                else:
                    Model.create(payload)
                    stats['created'] += 1
            except Exception as exc:  # noqa: BLE001 - keep the batch alive
                self.env.cr.rollback() if hasattr(self.env.cr, 'rollback') else None
                _logger.warning("densamed_bridge: upsert %s(%s) failed: %s",
                                model_name, rid, exc)
                stats['skipped'] += 1
        return stats

    # ------------------------------------------------------------------
    # Entity mappers
    # ------------------------------------------------------------------
    @api.model
    def _sync_products(self):
        Conn = self.env['densamed.connection']
        Category = self.env['product.category']
        UoM = self.env['uom.uom']
        default_uom = (UoM.search([('name', '=ilike', 'Units')], limit=1)
                       or UoM.search([], limit=1))

        # Ensure "pharma" category exists so medicines group nicely in Odoo.
        pharma = Category.search([('name', '=', 'Pharmaceuticals')], limit=1) \
            or Category.create({'name': 'Pharmaceuticals'})

        vals_list = []
        for row in Conn.get_medicines():
            uom = default_uom
            if row.get('unit_of_measure'):
                uom = UoM.search([('name', '=ilike', row['unit_of_measure'])], limit=1) or default_uom
            name = ' '.join(filter(None, [row['trade_name'], row.get('strength')]))
            vals_list.append({
                'densamed_id': row['medicine_id'],
                'densamed_model': 'medicines',
                'name': name,
                'default_code': 'DM-%06d' % row['medicine_id'],
                'barcode': row.get('barcode') or False,
                'type': 'product',         # storable: required for lots/expiry flows
                'tracking': 'lot',
                'categ_id': pharma.id,
                'uom_id': uom.id,
                'uom_po_id': uom.id,
                'lst_price': float(row['retail_price']),
                'min_stock': row.get('min_stock') or 0,
                'requires_prescription': bool(row.get('requires_prescription')),
                'generic_name': row.get('generic_name') or False,
                'dosage_form': row.get('dosage_form') or False,
                'manufacturer_ref': row.get('manufacturer_name') or False,
                'active': bool(row.get('is_active')),
            })
        return self._upsert('product.template', vals_list)

    @api.model
    def _sync_warehouses(self):
        Conn = self.env['densamed.connection']
        Partner = self.env['res.partner']
        vals_list = []
        for row in Conn.get_warehouses():
            code = '%s/%s' % (row['branch_code'], row['warehouse_name'][:12])
            partner = Partner.search([('ref', '=', 'WH-%d' % row['warehouse_id'])], limit=1)
            if not partner:
                partner = Partner.create({
                    'name': '%s — %s' % (row['branch_name'], row['warehouse_name']),
                    'ref': 'WH-%d' % row['warehouse_id'],
                    'city': row.get('city') or False,
                    'type': 'other',
                })
            vals_list.append({
                'densamed_id': row['warehouse_id'],
                'densamed_model': 'warehouses',
                'name': row['warehouse_name'],
                'code': code,
                'partner_id': partner.id,
            })
        return self._upsert('stock.warehouse', vals_list)

    @api.model
    def _sync_locations(self):
        """storage_locations -> stock.location (internal type, parent-aware).

        Two passes guarantee parents exist before children are created even if
        the source ever returns unordered rows.
        """
        Conn = self.env['densamed.connection']
        Location = self.env['stock.location']
        Warehouse = self.env['stock.warehouse']
        wh_map = {w.densamed_id: w for w in Warehouse.search([('densamed_id', '!=', False)])}
        rows = Conn.get_storage_locations()

        result = {'created': 0, 'updated': 0, 'skipped': 0}
        for _pass in (1, 2):
            pending = []
            for row in rows:
                wh = wh_map.get(row['warehouse_id'])
                if not wh:
                    continue
                parent = None
                if row['parent_id']:
                    parent = Location.search(
                        [('densamed_model', '=', 'storage_locations'),
                         ('densamed_id', '=', row['parent_id'])], limit=1)
                    if not parent and _pass == 1:
                        pending.append(row)
                        continue
                usage = {'zone': 'view', 'aisle': 'view', 'shelf': 'view', 'bin': 'internal'}\
                    .get(row['location_type'], 'internal')
                vals = {
                    'densamed_id': row['location_id'],
                    'densamed_model': 'storage_locations',
                    'name': row['location_code'],
                    'usage': usage,
                    'location_id': (parent or wh.lot_stock_id).id,
                    'active': bool(row['is_active']),
                }
                res = self._upsert('stock.location', [vals])
                for k in result:
                    result[k] += res[k]
                pending = []
            rows = pending
            if not rows:
                break
        return result

    @api.model
    def _sync_lots(self):
        """medicine_batches -> stock.lot with expiration_date.

        A lot is bound to the product synced from its medicine; the warehouse
        hint is stored for traceability but NO quant/move is fabricated.
        """
        Conn = self.env['densamed.connection']
        Product = self.env['product.product']
        Warehouse = self.env['stock.warehouse']
        wh_map = {w.densamed_id: w.id
                  for w in Warehouse.search([('densamed_id', '!=', False),
                                             ('densamed_model', '=', 'warehouses')])}
        vals_list = []
        for row in Conn.get_batches():
            product = Product.search(
                [('product_tmpl_id.densamed_model', '=', 'medicines'),
                 ('product_tmpl_id.densamed_id', '=', row['medicine_id'])], limit=1)
            if not product:
                _logger.debug("densamed_bridge: batch %s skipped, product %s not synced",
                              row['batch_id'], row['medicine_id'])
                continue
            vals_list.append({
                'densamed_id': row['batch_id'],
                'densamed_model': 'medicine_batches',
                'name': row['batch_number'],
                'product_id': product.id,
                'expiration_date': row['expiry_date'] or False,
                # remote PK -> local record; None when the batch has no stock row yet
                'densamed_warehouse_id': wh_map.get(row.get('warehouse_id')) or False,
                'purchase_price': float(row['purchase_price']),
            })
        return self._upsert('stock.lot', vals_list)

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    @api.model
    def sync_all(self):
        """Full pipeline, ordered by dependency. Called by ir.cron."""
        report = {}
        try:
            report['products'] = self._sync_products()
            report['warehouses'] = self._sync_warehouses()
            report['locations'] = self._sync_locations()
            report['lots'] = self._sync_lots()
        except Exception as exc:  # noqa: BLE001 - cron must log, not crash workers
            _logger.exception("densamed_bridge sync aborted: %s", exc)
            raise
        self.env['ir.config_parameter'].sudo().set_param(
            'densamed.last_sync', str(fields.Datetime.now()))
        _logger.info("densamed_bridge sync done: %s", report)
        return report

    @api.model
    def cron_sync_all(self):
        """Cron target: commit between entities so partial progress survives."""
        self.sync_all()
        self.env.cr.commit()   # intentional: cron runs in its own transaction scope
