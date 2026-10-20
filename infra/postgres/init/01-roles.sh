#!/bin/sh
# Un rôle et un schéma par service : chaque service ne voit que ses propres tables.
set -eu

AUTH_PW="$(cat /run/secrets/db_auth_password)"
LEDGER_PW="$(cat /run/secrets/db_ledger_password)"
PAYMENT_PW="$(cat /run/secrets/db_payment_password)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v auth_pw="$AUTH_PW" -v ledger_pw="$LEDGER_PW" -v payment_pw="$PAYMENT_PW" <<'EOSQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE resilience FROM PUBLIC;

CREATE ROLE auth_svc    LOGIN PASSWORD :'auth_pw'    CONNECTION LIMIT 30;
CREATE ROLE ledger_svc  LOGIN PASSWORD :'ledger_pw'  CONNECTION LIMIT 30;
CREATE ROLE payment_svc LOGIN PASSWORD :'payment_pw' CONNECTION LIMIT 30;

GRANT CONNECT ON DATABASE resilience TO auth_svc, ledger_svc, payment_svc;

CREATE SCHEMA auth    AUTHORIZATION auth_svc;
CREATE SCHEMA ledger  AUTHORIZATION ledger_svc;
CREATE SCHEMA payment AUTHORIZATION payment_svc;

ALTER ROLE auth_svc    SET search_path = auth;
ALTER ROLE ledger_svc  SET search_path = ledger;
ALTER ROLE payment_svc SET search_path = payment;

-- Garde-fous contre les requêtes qui monopolisent la base pendant une attaque.
ALTER ROLE auth_svc    SET statement_timeout = '5s';
ALTER ROLE ledger_svc  SET statement_timeout = '5s';
ALTER ROLE payment_svc SET statement_timeout = '5s';
EOSQL
