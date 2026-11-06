# -*- coding: utf-8 -*-
{
    'name': 'DensaMed Bridge',
    'version': '17.0.1.1.0',                    # branch feature bump (migration 17.0.1.1.0)
    'category': 'Inventory',
    'summary': 'One-way sync of the DensaMed operational PostgreSQL schema into Odoo master data',
    'description': """
DensaMed Bridge
===============
Read-only sync of medicines, warehouses, storage locations and medicine batches
from the `densamed` PostgreSQL database into Odoo Community 17.

Branches model: one densamed.branches row == one res.company (x_densamed_branch_id
join key). Warehouses, employees, purchase/sale orders and stock moves are scoped
through company_id -> record rules, branch switcher UI and multi-company P&L come
from Odoo core. Includes per-target crons, a sync log with 30-day retention,
branch security groups, role->group mapping with a MANUAL apply wizard, and a
SQL-view backed Branch Dashboard.
""",
    'author': 'DensaMed',
    'website': 'https://densamed.example',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'stock',
        'purchase',
        'sale_management',
        'hr',                       # NEW: hr.employee / hr.job
        'sales_team',               # NEW: group_sale_manager for the Manager role map
    ],
    'external_dependencies': {
        'python': ['psycopg2'],
    },
    'data': [
        'security/groups.xml',                              # NEW
        'security/densamed_branch_rules.xml',               # NEW
        'security/densamed_bridge_security.xml',
        'security/ir.model.access.csv',
        'views/densamed_sync_views.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/stock_warehouse_views.xml',
        'views/stock_location_views.xml',
        'views/stock_lot_views.xml',
        'views/branch_views.xml',                           # NEW
    ],
    'application': True,
    'installable': True,
}
