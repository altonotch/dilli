#!/usr/bin/env bash
set -e

# This script runs only on initial database creation when PGDATA is empty.
# It enables PostGIS in template1 so that future databases inherit it,
# and in $POSTGRES_DB (the default database) if provided.

echo "[init] Enabling PostGIS extensions in template1 and default database (if set)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname template1 <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS postgis;
  CREATE EXTENSION IF NOT EXISTS postgis_topology;
EOSQL

if [[ -n "$POSTGRES_DB" ]]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS postgis_topology;
EOSQL
fi
