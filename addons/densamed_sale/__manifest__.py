# -*- coding: utf-8 -*-
{
    'name': 'DensaMed Pharmacy Sales (Сату)',
    'version': '17.0.2.0.0',
    'category': 'Sales',
    'summary': 'Pharmacy counter sales: FEFO lot picking, prescription check, '
               'split payments, stock moves and returns',
    'description': """
DensaMed Pharmacy Sales (Сату)
==============================
Counter-sale module for the DensaMed pharmacy chain (Odoo 17 Community).

* One sale = one receipt (densamed.sale) in one branch (= res.company) and one
  warehouse. Status flow mirrors densamed.sales: draft -> completed ->
  returned / cancelled.
* Medicine lines pick a batch (stock.lot) automatically by FEFO (first expired,
  first out); lines are split across batches when one batch is not enough.
  Expired batches are never sold.
* Prescription-only medicines (product.template.requires_prescription, synced
  by densamed_bridge) require a prescription number on the sale.
* Payments: cash / card / bank transfer / other, split payments supported; a
  full payment is auto-created from the chosen method when none is entered.
* Completing a sale validates a standard outgoing stock.picking (lot-level
  stock.move.line), so on-hand quantities and valuation stay correct.
  Returning a sale validates the reverse incoming picking and refunds payments.
* Branch isolation through multi-company record rules + bridge HQ group.
""",
    'author': 'DensaMed',
    'website': 'https://densamed.example',
    'license': 'LGPL-3',
    'depends': [
        'densamed_bridge',      # branch groups, requires_prescription, lots
        'product_expiry',       # stock.lot.expiration_date (needed for FEFO)
        'stock',
        'mail',
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/rules.xml',
        'data/ir_sequence_data.xml',
        'views/densamed_sale_views.xml',
        'reports/sale_receipt.xml',
        'views/densamed_sale_line_views.xml',
        'views/menus.xml',
    ],
    'application': True,
    'installable': True,
}
