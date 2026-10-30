#!/bin/bash
# docker-entrypoint-initdb.d hook: runs ONLY while postgres_data is empty.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ${DENSAMED_DB:?DENSAMED_DB env var required}
        ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
    GRANT ALL PRIVILEGES ON DATABASE ${DENSAMED_DB} TO ${POSTGRES_USER};
EOSQL
echo "[initdb] database ${DENSAMED_DB} created (separate from ${POSTGRES_DB})"
