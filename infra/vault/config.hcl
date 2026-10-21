// Serveur Vault RESILIENCE-ALPHA (stockage persistant sur fichier, réseau interne).
// TLS désactivé : Vault n'est joignable que sur le réseau interne `vault` du compose.
storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

// Pas de verrouillage mémoire : évite d'exiger la capacité IPC_LOCK dans le conteneur.
disable_mlock = true
api_addr      = "http://vault:8200"
ui            = true
