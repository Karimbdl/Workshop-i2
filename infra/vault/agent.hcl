// Vault Agent : s'authentifie auprès de Vault avec l'AppRole du projet, puis
// RÉCUPÈRE les secrets et les ÉCRIT dans des fichiers (/vault/secrets/...).
// Les services lisent ces fichiers comme avant : leur code ne change pas.

vault {
  address = "http://vault:8200"
}

auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path                   = "/vault/agent-auth/role_id"
      secret_id_file_path                 = "/vault/agent-auth/secret_id"
      remove_secret_id_file_after_reading = false
    }
  }

  sink "file" {
    config = {
      path = "/vault/agent-auth/token"
    }
  }
}

// Secrets rendus pour les services migrés (consigne : rotation sans toucher au code).
template {
  contents    = "{{ with secret \"secret/data/resilience/internal_token\" }}{{ .Data.data.value }}{{ end }}"
  destination = "/vault/secrets/internal_token"
}

template {
  contents    = "{{ with secret \"secret/data/resilience/seed_users\" }}{{ .Data.data.value }}{{ end }}"
  destination = "/vault/secrets/seed_users"
}
