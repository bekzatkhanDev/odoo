#!/bin/sh
# Deliverable C + branch addendum: storage_locations, stock_movements, inventory
# triggers, FEFO function and the role_group_map table.
# Every file below is idempotent, so it can also be re-applied by hand later:
#   docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" \
#       -d densamed -f /sql/97-branch-addendum.sql
set -eu

for f in 97-branch-addendum.sql 99-inventory-control.sql; do
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DENSAMED_DB" \
         -f "/sql/${f}"
    echo "[initdb] ${f} loaded into ${DENSAMED_DB}"
done
