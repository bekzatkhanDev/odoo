# -*- coding: utf-8 -*-
{
    'name': 'DensaMed Bridge',
    'version': '17.0.1.0.0',
    'category': 'Inventory',
    'summary': 'One-way sync of the DensaMed operational PostgreSQL schema into Odoo master data',
    'description': """
DensaMed Bridge (Odoo 17 Community)
===================================
Reads the *densamed* database with psycopg2 (a second, strictly separate
database inside the same PostgreSQL instance) and mirrors master data into
the *odoo* database:

    densamed.medicines          ->  product.template / product.product
    densamed.warehouses         ->  stock.warehouse
    densamed.storage_locations  ->  stock.location
    densamed.medicine_batches   ->  stock.lot (+ expiration_date)

Design rules enforced by this module
------------------------------------
* READ-ONLY on densamed: every remote query is a SELECT; the bridge never
  INSERT/UPDATE/DELETEs operational rows, and never writes to stock.quant or
  stock.move — quantities stay under standard Odoo routing.
* Idempotent upserts keyed on `densamed_id` + `densamed_model` SQL constraints.
* A cron (`ir.cron`) runs the whole pipeline; a manual "Sync now" action and a
  settings panel expose host/port/db/user/password for non-Docker installs.
""",
    'author': 'DensaMed ERP Team',
    'website': 'https://densamed.local',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'stock',
    ],
    'external_dependencies': {
        'python': ['psycopg2'],
    },
    'data': [
        'security/densamed_bridge_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/densamed_sync_views.xml',
        'views/product_template_views.xml',
        'views/stock_warehouse_views.xml',
        'views/stock_location_views.xml',
        'views/stock_lot_views.xml',
        'data/ir_cron_data.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
