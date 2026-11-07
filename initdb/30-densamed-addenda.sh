#!/bin/bash
# Deliverable C: storage_locations, stock_movements, inventory trigger, FEFO function.
# Same file is mounted at /sql for manual re-runs:
#   docker compose exec db psql -v ON_ERROR_STOP=1 -U odoo -d densamed -f /sql/99-inventory-control.sql
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DENSAMED_DB" -f /docker-entrypoint-initdb.d/sql/99-inventory-control.sql
echo "[initdb] inventory addenda loaded into ${DENSAMED_DB}"
