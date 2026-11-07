# DensaMed Sales 17.0.2.0.0 — enhancement notes

Added: percentage discounts combined with fixed discounts; historical cost snapshot and gross-profit analysis (manager only); unit-count KPI; customer reference; printable QWeb PDF receipt; extra list/search/pivot metrics. Existing FEFO, prescription verification, multi-payments, stock transfers, refunds and branch rules are retained.

## Deployment
1. Back up the PostgreSQL database and filestore.
2. Add `addons/` to Odoo 17 addons_path; keep existing DensaMed modules installed.
3. Restart Odoo and upgrade `densamed_sale` (`-u densamed_sale -d YOUR_DB --stop-after-init`).
4. Grant Cashier / Sales Manager groups and check menus and the receipt action.
5. Test in staging with tracked medicines and multiple batches before production.

## Important
Profit is indicative gross profit based on standard_price captured at checkout, not accounting profit. It excludes taxes, overhead and subsequent cost adjustments. PDF receipt is not a fiscal receipt and does not replace local fiscalization requirements. No AI forecasting or JS POS terminal is included in this version. This package was statically checked, not run against a live Odoo server.
