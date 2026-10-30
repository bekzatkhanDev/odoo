#!/bin/bash
# Loads the DensaMed operational schema into ${DENSAMED_DB} (never into ${POSTGRES_DB}).
# ON_ERROR_STOP aborts the whole init if any statement fails -> no half-built DB.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DENSAMED_DB" -f /docker-entrypoint-initdb.d/sql/01-densamed-schema.sql
echo "[initdb] schema loaded into ${DENSAMED_DB}"
