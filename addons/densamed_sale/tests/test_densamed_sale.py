# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDensamedSale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.location = cls.warehouse.lot_stock_id
        cls.Quant = cls.env['stock.quant']

        cls.product = cls.env['product.product'].create({
            'name': 'Test Paracetamol 500',
            'type': 'product',
            'tracking': 'lot',
            'list_price': 100.0,
        })
        now = fields.Datetime.now()
        Lot = cls.env['stock.lot']
        cls.lot_early = Lot.create({
            'name': 'EARLY', 'product_id': cls.product.id, 'company_id': cls.company.id,
            'expiration_date': now + timedelta(days=30)})
        cls.lot_late = Lot.create({
            'name': 'LATE', 'product_id': cls.product.id, 'company_id': cls.company.id,
            'expiration_date': now + timedelta(days=90)})
        cls.lot_expired = Lot.create({
            'name': 'EXPIRED', 'product_id': cls.product.id, 'company_id': cls.company.id,
            'expiration_date': now - timedelta(days=5)})
        for lot, qty in ((cls.lot_early, 5), (cls.lot_late, 10), (cls.lot_expired, 20)):
            cls.Quant._update_available_quantity(cls.product, cls.location, qty, lot_id=lot)

    def _sale(self, qty, product=None, **vals):
        product = product or self.product
        return self.env['densamed.sale'].create(dict({
            'warehouse_id': self.warehouse.id,
            'line_ids': [(0, 0, {
                'product_id': product.id, 'quantity': qty, 'price_unit': 100.0})],
        }, **vals))

    def _qty(self, lot):
        return self.Quant._get_available_quantity(self.product, self.location, lot_id=lot)

    def test_fefo_splits_across_batches_and_skips_expired(self):
        sale = self._sale(8)
        sale.action_confirm()
        self.assertEqual(sale.state, 'completed')
        lots = {line.lot_id: line.quantity for line in sale.line_ids}
        self.assertEqual(lots, {self.lot_early: 5.0, self.lot_late: 3.0})
        self.assertEqual(self._qty(self.lot_early), 0.0)
        self.assertEqual(self._qty(self.lot_late), 7.0)
        self.assertEqual(self._qty(self.lot_expired), 20.0)
        self.assertEqual(sale.picking_id.state, 'done')
        self.assertEqual(sale.amount_total, 800.0)
        self.assertEqual(sale.amount_paid, 800.0)

    def test_not_enough_non_expired_stock(self):
        sale = self._sale(16)          # 15 sellable, expired batch must not count
        with self.assertRaises(UserError):
            sale.action_confirm()
        self.assertEqual(sale.state, 'draft')

    def test_prescription_required(self):
        rx = self.env['product.product'].create({
            'name': 'Test Rx', 'type': 'product', 'tracking': 'none',
            'list_price': 50.0, 'requires_prescription': True})
        self.Quant._update_available_quantity(rx, self.location, 10)
        sale = self._sale(1, product=rx)
        with self.assertRaises(UserError):
            sale.action_confirm()
        sale.prescription_ref = 'RX-001'
        sale.action_confirm()
        self.assertEqual(sale.state, 'completed')

    def test_return_restores_stock_and_refunds(self):
        sale = self._sale(8)
        sale.action_confirm()
        sale.action_return()
        self.assertEqual(sale.state, 'returned')
        self.assertEqual(sale.return_picking_id.state, 'done')
        self.assertEqual(self._qty(self.lot_early), 5.0)
        self.assertEqual(self._qty(self.lot_late), 10.0)
        self.assertEqual(sale.payment_ids.mapped('state'), ['refunded'])

    def test_completed_sale_is_locked(self):
        sale = self._sale(1)
        sale.action_confirm()
        with self.assertRaises(UserError):
            sale.line_ids[:1].write({'quantity': 2})
        with self.assertRaises(UserError):
            sale.unlink()

    def test_split_payment_must_match_total(self):
        sale = self._sale(2)
        self.env['densamed.sale.payment'].create(
            {'sale_id': sale.id, 'amount': 50.0, 'method': 'cash'})
        with self.assertRaises(UserError):
            sale.action_confirm()
        self.env['densamed.sale.payment'].create(
            {'sale_id': sale.id, 'amount': 150.0, 'method': 'card'})
        sale.action_confirm()
        self.assertEqual(sale.state, 'completed')
        self.assertEqual(sale.amount_due, 0.0)

    def test_percentage_discount_and_receipt_action(self):
        sale = self._sale(2)
        line = sale.line_ids
        line.write({'discount_percent': 10, 'discount_amount': 5})
        self.assertAlmostEqual(sale.amount_total, 175.0)
        sale.action_confirm()
        self.assertAlmostEqual(sale.margin_total, sum(sale.line_ids.mapped('margin_amount')))
        self.assertEqual(sale.item_count, 2)
        action = sale.action_print_receipt()
        self.assertEqual(action['type'], 'ir.actions.report')

    def test_discount_percent_validation(self):
        from odoo.exceptions import ValidationError
        sale = self._sale(1)
        with self.assertRaises(ValidationError):
            sale.line_ids.write({'discount_percent': 101})
