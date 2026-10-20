#!/bin/sh
# Rôle en lecture seule pour postgres-exporter : statistiques du serveur, aucun accès aux données métier.
# Idempotent : peut être relancé sur une base existante (docker compose exec postgres sh /docker-entrypoint-initdb.d/02-monitoring.sh).
set -eu

MONITOR_PW="$(cat /run/secrets/db_monitor_password)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v monitor_pw="$MONITOR_PW" <<'EOSQL'
SELECT 'CREATE ROLE monitor_svc LOGIN CONNECTION LIMIT 3'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'monitor_svc') \gexec
ALTER ROLE monitor_svc PASSWORD :'monitor_pw';
GRANT pg_monitor TO monitor_svc;
GRANT CONNECT ON DATABASE resilience TO monitor_svc;
ALTER ROLE monitor_svc SET statement_timeout = '5s';
EOSQL
