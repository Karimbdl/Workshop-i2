# Déploiement automatisé (Ansible)

Ansible déploie, vérifie et audite la plateforme RESILIENCE-ALPHA. Les playbooks sont
idempotents : on peut les relancer autant de fois qu'on veut, ils ne changent que ce qui doit
l'être.

## Pourquoi un conteneur

Ansible ne fonctionne pas sous Windows. Plutôt que d'imposer WSL ou une VM Linux, il est
embarqué dans une image (`ansible/Dockerfile`, basée sur `docker:29-cli`) qu'on appelle le
**poste de pilotage**. Le lanceur `scripts/ra.ps1` (ou `scripts/ra.sh`) le démarre avec :

- le socket Docker de l'hôte, pour piloter le moteur ;
- le dépôt monté à un chemin que Docker Desktop sait relier au disque Windows
  (`C:\Users\...` devient `/c/Users/...`).

Résultat : la seule dépendance est Docker, la même commande marche sous Windows, Linux et macOS,
et la version d'Ansible est figée dans l'image.

Le même conteneur sert aussi pour les commandes Compose manuelles (`ra.ps1 compose ...`). C'est
voulu : Compose compare la configuration au conteneur existant, chemins compris. Si on alterne
entre Compose lancé sous Windows et Compose lancé dans le conteneur, il voit des chemins
différents et recrée tous les conteneurs. En passant toujours par le lanceur, ça n'arrive jamais.

## Commandes

| Commande | Playbook | Effet |
|---|---|---|
| `ra.ps1 deploy` | `site.yml` | déploiement complet, vérification et audit |
| `ra.ps1 verifier` | `verifier.yml` | vérification + audit, aucune modification |
| `ra.ps1 desceller` | `desceller.yml` | descelle Vault après un redémarrage |
| `ra.ps1 arreter` | `arreter.yml` | arrête la plateforme, volumes conservés |
| `ra.ps1 sauvegarder` | `sauvegarder.yml` | sauvegarde chiffrée (PRA) |
| `ra.ps1 restaurer` | `restaurer.yml` | reconstruction avec les données (PRA) |
| `ra.ps1 compose <args>` | | `docker compose -p resilience-alpha <args>` |
| `ra.ps1 ansible <cmd>` | | commande libre dans le poste de pilotage |
| `ra.ps1 image` | | reconstruit l'image du poste de pilotage |

Toute option Ansible passe après la commande : `--check --diff`, `--tags audit`, `-v`,
`-e variable=valeur`.

## Rôles

```
site.yml
 ├── prerequis      moteur Docker joignable, Compose v2, mémoire, dépôt présent
 ├── secrets        secrets/ complet, sinon génération par init_secrets.py (no_log)
 ├── deploiement    docker compose up + attente des 23 services (running et healthy)
 ├── vault          amorçage, puis contrôle « initialisé et descellé »
 ├── verification   /healthz, /, /console/, routes internes cachées, WAF, smoke_test.py
 └── audit          contrôle de durcissement sur les conteneurs réellement lancés
```

### Ce que vérifie l'audit

Les contrôles portent sur l'état réel des conteneurs (`docker inspect`), pas sur le fichier
Compose. L'audit relève tous les écarts avant d'échouer, pour avoir un rapport complet.

- aucun conteneur en mode privilégié ;
- `no-new-privileges` activé partout ;
- socket Docker monté uniquement dans les deux proxys filtrants (`docker-proxy-ro`, `docker-proxy-rw`) ;
- seuls les ports prévus sont publiés : 8080 (passerelle) et 1883 (MQTT) sur le réseau,
  3000 (Grafana) et 8200 (Vault) sur `127.0.0.1` uniquement ;
- aucun fichier sensible suivi par git : `secrets/`, `.env`, empreintes faciales, modèles.

Le rapport liste aussi les conteneurs qui tournent en root parce que leur image l'impose
(proxys Docker, Postgres, Vault, Mosquitto).

## Variables

Dans `group_vars/all.yml` :

| Variable | Défaut | Rôle |
|---|---|---|
| `ra_build` | `policy` | `always` pour reconstruire les images |
| `ra_gateway_url` | `http://host.docker.internal:8080` | passerelle vue depuis le poste de pilotage |
| `ra_wait_timeout` | `240` | attente max des services (s) |
| `ra_min_docker_mem_gb` | `6` | seuil d'avertissement mémoire |
| `ra_services` | 23 services | services qui doivent tourner |
| `ra_ports_autorises` | voir fichier | ports publiés tolérés par l'audit |

## Sauvegarde et reprise après sinistre (PRA)

Ansible sait aussi **reconstruire la plateforme avec ses données** sur une autre machine.

### Ce qui est sauvegardé

| Élément | Pourquoi |
|---|---|
| Base PostgreSQL (schémas `auth`, `ledger`, `payment`) | comptes, soldes, virements, paiements |
| `secrets/` | les rôles de la base, les jetons et la clé JWT en dépendent |
| Modèle ML (volume `ml-model`) | évite de réapprendre le trafic normal |
| `services/face-agent/faces.json` | sinon le login du back-office ne reconnaît plus personne |

Vault n'est pas sauvegardé : l'amorçage le recharge entièrement depuis `secrets/`. Les
historiques de métriques et de journaux (Prometheus, Loki) ne le sont pas non plus : ils ne
servent pas à reprendre l'activité.

L'archive est chiffrée en **AES-256** (OpenSSL, dérivation PBKDF2 sur 200 000 itérations) avec
une phrase de passe, et accompagnée d'un fichier SHA-256. Le dossier de travail en clair est
effacé dans tous les cas, même en cas d'erreur. Les 7 dernières sauvegardes sont gardées dans
`backups/`, qui n'est pas versionné.

### Commandes

```powershell
.\scripts\ra.ps1 sauvegarder                                  # demande la phrase de passe
.\scripts\ra.ps1 restaurer                                    # dernière sauvegarde de backups/
.\scripts\ra.ps1 restaurer -e ra_archive=backups/<fichier>    # sauvegarde précise
```

La phrase de passe peut aussi venir de la variable d'environnement `RA_BACKUP_PASSPHRASE`.
Elle est transmise au conteneur par nom seulement et n'apparaît jamais dans une ligne de commande.

### Ce que fait la restauration

1. Contrôle SHA-256, déchiffrement, lecture du manifeste.
2. Remise en place des secrets. Si `secrets/` existe déjà et diffère, la restauration s'arrête
   sauf avec `-e ra_ecraser=true`.
3. Déploiement : sur une machine neuve, PostgreSQL crée ses rôles avec les secrets restaurés.
4. Arrêt des services qui écrivent en base, `pg_restore` en une seule transaction, restauration
   du modèle ML, redémarrage.
5. Descellement de Vault.
6. **Preuve** : l'empreinte des données (nombre de lignes par table, condensé MD5 des soldes,
   cohérence du grand livre) doit être identique à celle enregistrée dans le manifeste au moment
   de la sauvegarde. Sinon, le playbook échoue.
7. Vérification complète de la plateforme, puis affichage de la durée totale (RTO mesuré).

### Procédure PRA sur une machine neuve

1. Installer Docker et cloner le dépôt.
2. Copier l'archive `.tar.gz.enc` et son `.sha256` dans `backups/`.
3. `.\scripts\ra.ps1 restaurer`, puis saisir la phrase de passe.

### Essais réalisés (22/10/2026)

- Sauvegarde : 14 s, archive de 150 Ko, grand livre cohérent.
- Archive vérifiée (SHA-256 OK), déchiffrement refusé avec une mauvaise phrase de passe.
- Base restaurée dans un PostgreSQL vierge et isolé : empreinte **identique** (6 utilisateurs,
  7 comptes, 558 virements, 1 116 écritures, 567 paiements, même condensé des soldes,
  0 compte incohérent).

## Déployer sur un serveur Linux

L'inventaire (`inventory/hosts.yml`) contient un exemple commenté de machine distante en SSH.
Il suffit d'y copier le dépôt, de renseigner `ra_root` et de lancer `ra.sh deploy` depuis le
poste de pilotage. Les rôles sont les mêmes.

## Résultat sur le PC Hôte (22/10/2026)

- Premier `deploy` : 81 s, 23 services en marche, Vault descellé, 13/13 contrôles du test de
  bout en bout, 0 écart d'audit.
- Second `deploy` : 45 s, aucun service recréé (idempotence).
