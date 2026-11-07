#!/bin/bash
# Seeds master data into ${DENSAMED_DB}. Idempotent? No — runs only on empty volume, so plain INSERTs are fine.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DENSAMED_DB" -f /docker-entrypoint-initdb.d/sql/02-densamed-seed.sql
echo "[initdb] seed loaded into ${DENSAMED_DB}"
