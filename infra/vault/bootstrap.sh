#!/bin/sh
# Amorçage de Vault pour RESILIENCE-ALPHA :
#   - initialise Vault au premier démarrage (1 clé de descellement, pour la démo)
#   - le descelle (à chaque démarrage s'il est scellé)
#   - charge les secrets du projet dans le moteur KV v2
#   - crée une politique en lecture seule + un AppRole, et dépose role_id/secret_id
#     pour que Vault Agent puisse s'authentifier.
# Idempotent : relançable sans casser l'état existant.

set -u

export VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
INIT=/vault/init/init.txt
AUTH=/vault/agent-auth

echo "[bootstrap] attente de Vault..."
# vault status : 0 = descellé, 2 = scellé (mais joignable), autre = pas prêt.
while true; do
  vault status >/dev/null 2>&1
  rc=$?
  { [ "$rc" = "0" ] || [ "$rc" = "2" ]; } && break
  sleep 1
done

# À partir d'ici on veut que toute erreur arrête le script.
set -e

# Initialisation au premier lancement seulement.
if vault status 2>/dev/null | grep -q 'Initialized.*false'; then
  echo "[bootstrap] initialisation de Vault"
  vault operator init -key-shares=1 -key-threshold=1 > "$INIT"
fi

if [ ! -f "$INIT" ]; then
  echo "[bootstrap] ERREUR : Vault initialisé mais $INIT absent (volume perdu ?)." >&2
  exit 1
fi

UNSEAL=$(awk '/Unseal Key 1:/ {print $NF}' "$INIT")
ROOT=$(awk '/Initial Root Token:/ {print $NF}' "$INIT")

# Descellement si nécessaire.
if vault status 2>/dev/null | grep -q 'Sealed.*true'; then
  echo "[bootstrap] descellement"
  vault operator unseal "$UNSEAL" >/dev/null
fi

export VAULT_TOKEN="$ROOT"

# Moteur de secrets KV v2.
vault secrets enable -path=secret kv-v2 >/dev/null 2>&1 || true

# Chargement de tous les secrets du projet (depuis /seeds, monté en lecture seule).
for f in /seeds/*; do
  [ -f "$f" ] || continue
  name=$(basename "$f")
  vault kv put "secret/resilience/$name" value=@"$f" >/dev/null
  echo "[bootstrap] secret chargé : $name"
done

# Politique : lecture seule des secrets du projet.
vault policy write resilience-read - >/dev/null <<'EOF'
path "secret/data/resilience/*" {
  capabilities = ["read"]
}
EOF

# AppRole : identité machine pour Vault Agent.
vault auth enable approle >/dev/null 2>&1 || true
vault write auth/approle/role/resilience \
  token_policies=resilience-read token_ttl=1h token_max_ttl=4h secret_id_ttl=0 >/dev/null
vault read -field=role_id auth/approle/role/resilience/role-id > "$AUTH/role_id"
vault write -f -field=secret_id auth/approle/role/resilience/secret-id > "$AUTH/secret_id"

echo "[bootstrap] AppRole prêt (role_id + secret_id déposés dans $AUTH)"
echo "[bootstrap] TERMINÉ"
