#!/bin/sh
# docker-entrypoint-initdb.d hook: runs ONLY while the postgres_data volume is empty.
#
# Two hard rules for anything mounted into /docker-entrypoint-initdb.d:
#   1) POSIX sh + LF line endings. The postgres image executes these files
#      directly, so "cannot execute: required file not found" means a bad
#      shebang or CRLF line endings (Windows checkout / git core.autocrlf),
#      NOT a missing package. Keep `set -eu` only — dash has no `pipefail`.
#   2) Do not rely on $POSTGRES_DB existing here: docker-entrypoint.sh creates
#      it right before running this directory, but connecting to the maintenance
#      database "postgres" is always safe.
set -eu

: "${DENSAMED_DB:?DENSAMED_DB env var required (set it in .env)}"
db="${DENSAMED_DB}"

# Idempotent guard: harmless on a truly fresh volume, saves us if the entrypoint
# ever re-runs init scripts against an already-initialised cluster.
if psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -tAc \
     "SELECT 1 FROM pg_database WHERE datname = '${db}'" | grep -q 1; then
    echo "[initdb] database ${db} already exists, skipping creation"
else
    createdb --username "$POSTGRES_USER" --encoding=UTF8 \
             --template=template0 --lc-collate=C --lc-ctype=C "$db"
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
	GRANT ALL PRIVILEGES ON DATABASE ${db} TO ${POSTGRES_USER};
EOSQL

echo "[initdb] database ${db} created (separate from the Odoo DB ${POSTGRES_DB:-postgres})"
