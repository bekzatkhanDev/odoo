#!/bin/sh
# Seeds master data into ${DENSAMED_DB}. Not idempotent by design: this hook only
# ever runs against an empty postgres_data volume, so plain INSERTs are fine.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DENSAMED_DB" \
     -f /sql/02-densamed-seed.sql
echo "[initdb] seed loaded into ${DENSAMED_DB}"
