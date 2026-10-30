#!/bin/sh
# Loads the DensaMed operational schema into ${DENSAMED_DB} (never into ${POSTGRES_DB}).
# ON_ERROR_STOP aborts on the first failing statement -> no half-built schema.
# POSIX sh only: the postgres image runs this with /bin/sh (dash), which has no pipefail.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DENSAMED_DB" \
     -f /sql/01-densamed-schema.sql
echo "[initdb] schema loaded into ${DENSAMED_DB}"
