<#
.SYNOPSIS
  Lanceur d'exploitation de RESILIENCE-ALPHA (Ansible + Compose dans un conteneur).

.DESCRIPTION
  Ansible ne tourne pas sous Windows : ce script lance le poste de pilotage
  (image construite depuis ansible/Dockerfile) avec le socket Docker et le dépôt
  montés. Les commandes Compose passent par le même conteneur, pour que la stack
  soit toujours gérée avec les mêmes chemins (sinon Compose recrée les conteneurs).

.EXAMPLE
  .\scripts\ra.ps1 deploy                      # déploiement complet + vérification + audit
  .\scripts\ra.ps1 deploy -e ra_build=always   # idem en reconstruisant les images
  .\scripts\ra.ps1 verifier                    # contrôle sans rien modifier
  .\scripts\ra.ps1 desceller                   # après un redémarrage : descelle Vault
  .\scripts\ra.ps1 arreter                     # arrête la plateforme (données conservées)
  .\scripts\ra.ps1 compose ps                  # n'importe quelle commande docker compose
  .\scripts\ra.ps1 compose up -d --build admin-api
  .\scripts\ra.ps1 image                       # reconstruit l'image du poste de pilotage
#>
# Pas de bloc param() : PowerShell capterait des options comme « -c » ou « -e »
# destinées à Ansible ou Compose. On transmet tous les arguments tels quels.
$Commande = if ($args.Count -gt 0) { [string]$args[0] } else { "aide" }
$Reste = if ($args.Count -gt 1) { [string[]]$args[1..($args.Count - 1)] } else { @() }

$ErrorActionPreference = "Stop"
$Image = "resilience-alpha/ops:1"
$Racine = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# C:\Users\x\projet -> /c/Users/x/projet : chemin que Docker Desktop sait relier au disque Windows.
$Lecteur = $Racine.Substring(0, 1).ToLower()
$RacineConteneur = "/" + $Lecteur + ($Racine.Substring(2) -replace "\\", "/")

function Construire-Image {
  Write-Host "Construction de l'image du poste de pilotage ($Image)..."
  docker build -t $Image (Join-Path $Racine "ansible")
  if ($LASTEXITCODE -ne 0) { throw "Échec de la construction de l'image." }
}

function Lancer([string[]]$Cmd) {
  docker image inspect $Image *> $null
  if ($LASTEXITCODE -ne 0) { Construire-Image }
  $opts = @(
    "run", "--rm", "--init",
    "-v", "/var/run/docker.sock:/var/run/docker.sock",
    "-v", "${Racine}:${RacineConteneur}",
    "-w", $RacineConteneur,
    "-e", "RA_ROOT=$RacineConteneur",
    "-e", "ANSIBLE_CONFIG=$RacineConteneur/ansible/ansible.cfg",
    # Transmise par nom seulement : la valeur n'apparaît jamais dans la ligne de commande.
    "-e", "RA_BACKUP_PASSPHRASE",
    "--add-host", "host.docker.internal:host-gateway"
  )
  if (-not [Console]::IsOutputRedirected) { $opts += "-t" }
  # Docker écrit sa progression sur stderr : sous PowerShell 5.1, avec « Stop », une sortie
  # redirigée (2>&1) deviendrait une erreur fatale. Le code de retour fait foi.
  $ErrorActionPreference = "Continue"
  & docker @opts $Image @Cmd
  exit $LASTEXITCODE
}

function Demander-Phrase {
  if ($env:RA_BACKUP_PASSPHRASE) { return }
  $s = Read-Host "Phrase de passe de la sauvegarde (12 caractères min.)" -AsSecureString
  $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { $env:RA_BACKUP_PASSPHRASE = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

function Playbook([string]$Nom) {
  Lancer (@("ansible-playbook", "$RacineConteneur/ansible/$Nom") + $Reste)
}

switch ($Commande) {
  "deploy"    { Playbook "site.yml" }
  "verifier"  { Playbook "verifier.yml" }
  "desceller" { Playbook "desceller.yml" }
  "arreter"   { Playbook "arreter.yml" }
  "sauvegarder" { Demander-Phrase; Playbook "sauvegarder.yml" }
  "restaurer"   { Demander-Phrase; Playbook "restaurer.yml" }
  "compose"   { Lancer (@("docker", "compose", "-p", "resilience-alpha") + $Reste) }
  "ansible"   { Lancer $Reste }
  "image"     { Construire-Image }
  default {
    Write-Host @"
Usage : .\scripts\ra.ps1 <commande> [options]

  deploy      déploiement complet (prérequis, secrets, compose, Vault, vérification, audit)
  verifier    vérification + audit, sans rien modifier
  desceller   descelle Vault (après un redémarrage du PC ou de Docker)
  arreter     arrête la plateforme (ajouter -e ra_purger=true pour effacer les données)
  sauvegarder sauvegarde chiffrée dans backups/ (base, secrets, modèle ML, visages)
  restaurer   restaure la dernière sauvegarde (ou -e ra_archive=backups/<fichier>)
  compose ... commande docker compose sur le projet (ps, logs, up -d --build <service>...)
  ansible ... commande libre dans le poste de pilotage (ansible-playbook, ansible-lint...)
  image       reconstruit l'image du poste de pilotage

Options Ansible utiles : --check --diff, --tags verification, -e ra_build=always
"@
  }
}
