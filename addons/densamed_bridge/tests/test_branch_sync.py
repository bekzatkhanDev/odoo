# -*- coding: utf-8 -*-
"""Smoke tests for the Branch feature (Deliverable 6).

Tests 1-3 are pure TransactionCase. Test 4 needs REAL concurrent PostgreSQL
transactions, which TransactionCase cannot give (everything shares one cursor)
— so it uses two independent psycopg2 connections against the DensaMed DB and
is skipped automatically when that DB is unreachable. This is documented here
because "TransactionCase + threads" silently serialises on cr._cnx and would
test nothing otherwise.
"""
import logging
import threading

from psycopg2 import OperationalError

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)


class TestBranchSyncBase(TransactionCase):
    """Shared fixtures: fake remote rows injected without touching network."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        # Enable the master switch for these tests only (config parameter is
        # rolled back with the TransactionCase transaction).
        cls.env['ir.config_parameter'].sudo().set_param(
            'densamed_bridge.enable_sync', 'True')
        cls.branch_a = {'branch_id': 9001, 'branch_code': 'TST-A',
                        'branch_name': 'Test Branch A', 'city': 'Bujumbura',
                        'address': 'Ave. Test 1', 'phone': '+257-000-0001',
                        'is_active': True}
        cls.branch_b = dict(cls.branch_a, branch_id=9002, branch_code='TST-B',
                            branch_name='Test Branch B', phone='+257-000-0002')
        cls.employee = {'employee_id': 7001, 'branch_id': 9001, 'role_id': 1,
                        'first_name': 'Ada', 'last_name': 'Tester',
                        'email': 'ada@example.com', 'phone': '+257-1',
                        'hire_date': fields.Date.today(), 'is_active': True,
                        'role_name': 'Pharmacist'}
        cls.role = {'role_id': 1, 'role_name': 'Pharmacist',
                    'description': 'Dispensing'}

    def patch_remote(self, branches=None, roles=None, employees=None):
        """Stub densamed.connection fetchers (no live DB needed)."""
        Conn = self.env['densamed.connection']
        b = list(branches if branches is not None else [self.branch_a, self.branch_b])
        r = list(roles if roles is not None else [self.role])
        e = list(employees if employees is not None else [self.employee])
        Conn._patch_method('get_branches', lambda model: b)
        Conn._patch_method('get_roles', lambda model: r)
        Conn._patch_method('get_employees', lambda model: e)


@tagged('post_install', '-at_install')
class TestBranchCompanySync(TestBranchSyncBase):

    # ------------------------------------------------------------------
    def test_01_sync_twice_is_idempotent(self):
        """Sync runs twice -> company count unchanged; second run creates 0;
        a renamed remote row makes the third run report rows_updated > 0."""
        Company = self.env['res.company'].with_context(active_test=False)
        self.patch_remote()
        base_count = Company.search_count([])

        log1 = self.env['densamed.sync'].cron_sync_branches()
        self.assertEqual(log1.state, 'success', log1.error)
        self.assertEqual(log1.rows_created, 2)          # TST-A + TST-B
        mid_count = Company.search_count([])
        self.assertEqual(mid_count, base_count + 2)

        log2 = self.env['densamed.sync'].cron_sync_branches()
        self.assertEqual(log2.state, 'success', log2.error)
        end_count = Company.search_count([])
        self.assertEqual(end_count, mid_count, 'second run must not duplicate companies')
        self.assertEqual(log2.rows_created, 0)

        # deterministic rows_updated > 0: mutate one remote row between passes
        renamed = dict(self.branch_a, branch_name='Test Branch A Renamed')
        self.patch_remote(branches=[renamed, self.branch_b])
        log3 = self.env['densamed.sync'].cron_sync_branches()
        self.assertEqual(log3.rows_created, 0)
        self.assertGreater(log3.rows_updated, 0)
        self.assertEqual(
            Company.search([('x_densamed_branch_id', '=', 9001)]).name,
            'Test Branch A Renamed')

    # ------------------------------------------------------------------
    def test_02_branch_user_cannot_read_other_company_quant(self):
        comp_a = self.env['res.company'].create({'name': 'Branch A'})
        comp_b = self.env['res.company'].create({'name': 'Branch B'})
        group_user = self.env.ref('densamed_bridge.group_densamed_branch_user')
        user_a = self.env['res.users'].create({
            'name': 'Pharmacist A', 'login': 'pharm_a@test',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id,
                                  group_user.id])],
            'company_id': comp_a.id,
            'company_ids': [(6, 0, [comp_a.id])],
        })
        product = self.env['product.product'].create({'name': 'Paracetamol 500mg'})
        loc_a = self.env['stock.location'].create(
            {'name': 'STOCK-A', 'usage': 'internal', 'company_id': comp_a.id})
        loc_b = self.env['stock.location'].create(
            {'name': 'STOCK-B', 'usage': 'internal', 'company_id': comp_b.id})
        quant_b = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id, 'location_id': loc_b.id,
            'company_id': comp_b.id, 'quantity': 5.0})
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id, 'location_id': loc_a.id,
            'company_id': comp_a.id, 'quantity': 7.0})
        with self.assertRaises(AccessError):
            quant_b.with_user(user_a).read(['quantity'])
        # own-company quant stays readable (rules are global=False + pinned to
        # our groups — nobody gets locked out of their own records)
        own = self.env['stock.quant'].with_user(user_a).search(
            [('company_id', '=', comp_a.id)])
        self.assertTrue(own, 'branch user must see its own quants')

    # ------------------------------------------------------------------
    def test_03_hq_reads_both_companies(self):
        comp_a = self.env['res.company'].create({'name': 'HQ Branch A'})
        comp_b = self.env['res.company'].create({'name': 'HQ Branch B'})
        hq_group = self.env.ref('densamed_bridge.group_densamed_hq')
        user_hq = self.env['res.users'].create({
            'name': 'HQ Analyst', 'login': 'hq@test',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id,
                                  hq_group.id])],
            'company_id': comp_a.id,
            'company_ids': [(6, 0, [comp_a.id, comp_b.id])],
        })
        self.assertIn(self.env.ref('base.group_multi_company'),
                      user_hq.groups_id,
                      'group_densamed_hq must imply base.group_multi_company')
        product = self.env['product.product'].create({'name': 'Amoxicillin'})
        loc_a = self.env['stock.location'].create(
            {'name': 'HQ-A', 'usage': 'internal', 'company_id': comp_a.id})
        loc_b = self.env['stock.location'].create(
            {'name': 'HQ-B', 'usage': 'internal', 'company_id': comp_b.id})
        q_a = self.env['stock.quant'].with_context(inventory_mode=True).create(
            {'product_id': product.id, 'location_id': loc_a.id,
             'company_id': comp_a.id, 'quantity': 1})
        q_b = self.env['stock.quant'].with_context(inventory_mode=True).create(
            {'product_id': product.id, 'location_id': loc_b.id,
             'company_id': comp_b.id, 'quantity': 2})
        seen = self.env['stock.quant'].with_user(user_hq).search(
            [('id', 'in', [q_a.id, q_b.id])])
        self.assertEqual(set(seen.ids), {q_a.id, q_b.id},
                         'HQ must read both branches (built-in multi-company rule)')

    # ------------------------------------------------------------------
    def test_04_inactive_branch_rows_are_skipped(self):
        self.patch_remote()
        self.env['densamed.sync'].cron_sync_branches()
        comp_b = self.env['res.company'].with_context(active_test=False).search(
            [('x_densamed_branch_id', '=', 9002)])
        comp_b.active = False
        emp_b = dict(self.employee, employee_id=7002, branch_id=9002)
        self.patch_remote(employees=[self.employee, emp_b])
        log = self.env['densamed.sync'].cron_sync_employees()
        self.assertEqual(log.state, 'success', log.error)
        self.assertGreaterEqual(log.rows_skipped, 1)   # employee of archived branch B
        self.assertFalse(comp_b.active,
                         'sync must NOT reactivate an archived branch company')


@tagged('post_install', '-at_install')
class TestApplyStockMovementConcurrency(TransactionCase):
    """Test 4: apply_stock_movement() under two concurrent inserts.

    Real concurrency requires separate DB transactions -> direct psycopg2
    connections to the DensaMed database (skipped if unavailable). Asserts:
      * no deadlock / serialization failure escapes (the advisory xact lock
        inside the trigger queues the writers),
      * final quantity_on_hand == sum(receipts) - sum(issues),
      * pg_locks shows zero advisory locks after commit (xact-scoped release);
        mid-flight we sample pg_locks and merely log whether we caught the
        lock (timing-sensitive, so not a hard assert).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter'].sudo()
        cls.dsn = dict(
            host=params.get_param('densamed.db.host', 'localhost'),
            port=int(params.get_param('densamed.db.port', '5432')),
            dbname=params.get_param('densamed.db.name', 'densamed'),
            user=params.get_param('densamed.db.user', 'odoo'),
            password=params.get_param('densamed.db.password', ''),
            connect_timeout=5)
        import psycopg2
        try:
            c = psycopg2.connect(**cls.dsn)
            c.close()
        except OperationalError as exc:
            raise cls.skipTest(
                cls, 'DensaMed DB unreachable for concurrency test: %s' % exc)
        cls.psycopg2 = psycopg2

    def _conn(self):
        return self.psycopg2.connect(**self.dsn)

    def test_concurrent_receipts_same_slot(self):
        import time
        conn_setup = self._conn()
        conn_setup.autocommit = True
        with conn_setup.cursor() as cur:
            cur.execute("SELECT w.warehouse_id, b.batch_id, b.medicine_id"
                        "  FROM public.warehouses w"
                        "  JOIN public.medicine_batches b ON b.medicine_id IS NOT NULL"
                        " ORDER BY w.warehouse_id, b.batch_id LIMIT 1")
            wh_id, batch_id, med_id = cur.fetchone()
            cur.execute("DELETE FROM densamed_fdw.stock_movements"
                        " WHERE reference LIKE 'TST-CONC%%'")
        conn_setup.close()

        results = {}

        def writer(tag, qty):
            c = self._conn()
            try:
                with c.cursor() as k:
                    k.execute(
                        "INSERT INTO densamed_fdw.stock_movements"
                        "(medicine_id,batch_id,warehouse_id,movement_type,quantity,reference)"
                        " VALUES (%s,%s,%s,'receipt',%s,%s)",
                        (med_id, batch_id, wh_id, qty, 'TST-CONC-%s' % tag))
                c.commit()
                results[tag] = 'ok'
            except Exception as exc:  # noqa: BLE001
                c.rollback()
                results[tag] = repr(exc)
            finally:
                c.close()

        t1 = threading.Thread(target=writer, args=('a', 40))
        t2 = threading.Thread(target=writer, args=('b', 60))
        t1.start()
        time.sleep(0.05)
        t2.start()
        # sample pg_locks while one writer may be parked behind the advisory lock
        watch = self._conn()
        watch.autocommit = True
        with watch.cursor() as w:
            w.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory'")
            advisory_seen = w.fetchone()[0]
        watch.close()
        t1.join(30)
        t2.join(30)

        blob = str(list(results.values()))
        self.assertNotIn('DeadlockDetected', blob, results)
        self.assertNotIn('SerializationFailure', blob, results)
        for tag in ('a', 'b'):
            self.assertEqual(results.get(tag), 'ok', results)

        check = self._conn()
        check.autocommit = True
        with check.cursor() as k:
            k.execute("SELECT quantity_on_hand FROM densamed_fdw.inventory"
                      " WHERE warehouse_id=%s AND batch_id=%s", (wh_id, batch_id))
            on_hand = k.fetchone()[0]
            k.execute("SELECT sum(CASE WHEN movement_type IN ('receipt','return','adjustment')"
                      "            THEN quantity ELSE -quantity END)"
                      "  FROM densamed_fdw.stock_movements"
                      " WHERE warehouse_id=%s AND batch_id=%s", (wh_id, batch_id))
            ledger = k.fetchone()[0]
            k.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory'")
            released = k.fetchone()[0]
        check.close()
        self.assertEqual(float(on_hand), float(ledger),
                         'inventory must equal receipts minus issues')
        self.assertGreaterEqual(float(on_hand), 100.0)
        self.assertEqual(released, 0, 'advisory xact locks must be released at commit')
        if not advisory_seen:
            _logger.info('pg_locks sampling raced too fast to catch the advisory '
                         'lock; correctness asserted by the totals above.')
