#!/usr/bin/env bash
set -euo pipefail

# A dedicated pg_monitor member keeps postgres_exporter away from the app's
# superuser credentials. This runs only when PostgreSQL initializes a fresh
# data directory; deploy-docker.sh also reconciles the role for existing data.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 <<'SQL'
\getenv exporter_user POSTGRES_EXPORTER_USER
\getenv exporter_password POSTGRES_EXPORTER_PASSWORD

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'exporter_user', :'exporter_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'exporter_user');
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'exporter_user', :'exporter_password');
\gexec

SELECT format('GRANT pg_monitor TO %I', :'exporter_user');
\gexec
SQL
