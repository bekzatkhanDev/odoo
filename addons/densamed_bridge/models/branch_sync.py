# -*- coding: utf-8 -*-
"""Deliverable 1 — branches -> res.company, roles -> hr.job (+ role/group map),
employees -> hr.employee, all scoped by branch company.

Idempotent upsert contract (branches):
  1. match on x_densamed_branch_id (the join key) FIRST;
  2. fall back to partner ref == branch_code ONLY when no key match exists —
     this adopts a manually-created company instead of duplicating it;
  3. never duplicate on re-run: after step 2 the key is stamped, so the next
     pass matches on step 1.

Concurrency note (see also SQL addendum "Concurrency notes"): ir.cron jobs are
mutually exclusive per job row in a single worker pool, but two *different*
branch crons could still race with a manual create. The UNIQUE constraint on
x_densamed_branch_id plus the savepoint + UniqueViolation retry in
densamed.job_runner.run_job() is the defence; pg_advisory_xact_lock is NOT
needed because Odoo's ORM serialises cron execution (ir.cron runs one job at a
time per worker and _callback checks _is_active). We keep the advisory-lock
helper available for multi-worker deployments — see _advisory_lock().
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class DensamedBranchSync(models.AbstractModel):
    _inherit = 'densamed.sync'

    # ------------------------------------------------------------------
    # Advisory lock helper (optional hardening for multi-process crons)
    # ------------------------------------------------------------------
    @api.model
    def _advisory_lock(self, key):
        """Transaction-scoped advisory lock inside the ODOO database.
        Used only if a deployment runs several cron workers AND duplicates the
        job; otherwise the built-in ir.cron mutex is sufficient (see module
        docstring). Lock is released automatically at COMMIT/ROLLBACK."""
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (key,))

    # ------------------------------------------------------------------
    # branches -> res.company
    # ------------------------------------------------------------------
    @api.model
    def _sync_branches(self):
        Conn = self.env['densamed.connection']
        Company = self.env['res.company'].sudo()
        Partner = self.env['res.partner'].sudo()
        stats = {'created': 0, 'updated': 0, 'skipped': 0}

        for row in Conn.get_branches():
            code = (row['branch_code'] or '').strip()
            name = (row['branch_name'] or '').strip()
            addr = (row['address'] or '').strip()
            city = (row['city'] or '').strip()
            phone = (row['phone'] or '').strip()
            active = bool(row['is_active'])

            # 1) primary match: join key
            comp = Company.search([('x_densamed_branch_id', '=', row['branch_id'])],
                                  limit=1)
            # 2) fallback: branch_code mirrored on the company partner's ref
            if not comp and code:
                partner = Partner.search([('ref', '=', code),
                                          ('is_company', '=', True)], limit=1)
                if partner and partner.company_id:
                    comp = partner.company_id
                    comp.write({'x_densamed_branch_id': row['branch_id']})
                    stats['updated'] += 1

            try:
                if comp:
                    change = {}
                    if self._compare(comp, 'name', name):
                        change['name'] = name
                    # address fields live on the company's partner in Odoo 17
                    p = comp.partner_id
                    pchange = {}
                    if code and (p.ref or '') != code:
                        pchange['ref'] = code
                    if self._compare(p, 'city', city):
                        pchange['city'] = city
                    if self._compare(p, 'street', addr):
                        pchange['street'] = addr
                    if self._compare(p, 'phone', phone):
                        pchange['phone'] = phone
                    if pchange:
                        p.write(pchange)
                    # NEVER auto-reactivate: an inactive branch stays inactive
                    # until a human flips it (spec Deliverable 4).
                    if comp.active and not active:
                        change['active'] = False
                    if change:
                        comp.write(change)
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1
                else:
                    comp = Company.create({
                        'name': name,
                        'x_densamed_branch_id': row['branch_id'],
                    })
                    comp.partner_id.write({
                        'ref': code, 'city': city, 'street': addr, 'phone': phone,
                    })
                    stats['created'] += 1
            except Exception as exc:  # noqa: BLE001 - keep the batch alive
                _logger.warning('densamed_bridge: branch %s failed: %s',
                                row['branch_id'], exc)
                stats['skipped'] += 1

        # HQ members must belong to every branch company (record-rule support)
        Company._ensure_hq_membership()
        return stats

    # ------------------------------------------------------------------
    # roles -> hr.job  (job != security group; see role_group_map below)
    # ------------------------------------------------------------------
    @api.model
    def _sync_jobs(self):
        Conn = self.env['densamed.connection']
        Job = self.env['hr.job'].sudo()
        vals_list = []
        for row in Conn.get_roles():
            vals_list.append({
                'densamed_id': row['role_id'],
                'densamed_model': 'roles',
                'name': row['role_name'],
            })
        return self._upsert('hr.job', vals_list)

    # ------------------------------------------------------------------
    # employees -> hr.employee, company via x_densamed_branch_id
    # ------------------------------------------------------------------
    @api.model
    def _sync_employees(self):
        Conn = self.env['densamed.connection']
        branch_map = Conn._branch_company_map()          # includes inactive keys
        active_map = {k: v for k, v in branch_map.items() if v.active}
        Job = self.env['hr.job'].sudo()
        Employee = self.env['hr.employee'].sudo()
        stats = {'created': 0, 'updated': 0, 'skipped': 0}
        vals_list = []
        for row in Conn.get_employees():
            company = active_map.get(row['branch_id'])
            if not company:
                # branch missing OR branch company archived -> skip entirely.
                # Spec: sync must not touch records of inactive companies and
                # must not reactivate them.
                stats['skipped'] += 1
                continue
            job = Job.search([('densamed_model', '=', 'roles'),
                              ('densamed_id', '=', row['role_id'])], limit=1) \
                or Job.search([('name', '=ilike', row.get('role_name') or '')], limit=1)
            vals_list.append({
                'densamed_id': row['employee_id'],
                'densamed_model': 'employees',
                'name': '%s %s' % (row['first_name'], row['last_name']),
                'work_phone': row.get('phone') or False,
                'work_email': row.get('email') or False,
                'job_id': job.id if job else False,
                'company_id': company.id,
                'active': bool(row['is_active']),
            })
        # hr.employee has no densamed_* columns yet — attach them first
        self._ensure_employee_mapping(Employee)
        stats.update(self._upsert('hr.employee', vals_list))
        return stats

    @api.model
    def _ensure_employee_mapping(self, Employee):
        # columns added by models/hr_employee.py at table level; nothing to do
        # at runtime — hook kept so migration/tests can assert presence.
        return True

    # ------------------------------------------------------------------
    # Entry points used by the per-target crons (Deliverable 4)
    # ------------------------------------------------------------------
    @api.model
    def cron_sync_branches(self):
        return self.env['densamed.job_runner'].run_job(
            'branches->res.company', lambda env: self._sync_branches())

    @api.model
    def cron_sync_jobs(self):
        return self.env['densamed.job_runner'].run_job(
            'roles->hr.job', lambda env: self._sync_jobs())

    @api.model
    def cron_sync_employees(self):
        return self.env['densamed.job_runner'].run_job(
            'employees->hr.employee', lambda env: self._sync_employees())

    @api.model
    def cron_sync_products(self):
        return self.env['densamed.job_runner'].run_job(
            'medicines->product.template', lambda env: self._sync_products())

    @api.model
    def cron_sync_warehouses(self):
        return self.env['densamed.job_runner'].run_job(
            'warehouses->stock.warehouse', lambda env: self._sync_warehouses())

    @api.model
    def cron_sync_locations(self):
        return self.env['densamed.job_runner'].run_job(
            'storage_locations->stock.location', lambda env: self._sync_locations())

    @api.model
    def cron_sync_lots(self):
        return self.env['densamed.job_runner'].run_job(
            'medicine_batches->stock.lot', lambda env: self._sync_lots())
