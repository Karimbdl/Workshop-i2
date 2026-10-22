# RESILIENCE-ALPHA

Plateforme de paiement en ligne fictive (la néobanque **Devolut**) construite pour le workshop
EPSI M2 « PROJECT RESILIENCE-ALPHA ».

L'idée : une plateforme qui se fait attaquer, qui **détecte seule** l'attaque par apprentissage
automatique, qui **se répare seule**, et qui le prouve par un nouveau paiement réussi avec un
grand livre comptable cohérent. Un conteneur qui redémarre ne suffit pas comme preuve : c'est le
paiement témoin qui compte.

Toutes les données sont fictives. Tout tourne sur un seul PC (le PC Hôte), en conteneurs Docker,
sauf la reconnaissance faciale qui a besoin d'accéder directement à la webcam USB.

---

## Sommaire

1. [Le scénario de démonstration](#1-le-scénario-de-démonstration)
2. [Architecture](#2-architecture)
3. [Les composants](#3-les-composants)
4. [Consigne additionnelle 1 : login du back-office par reconnaissance faciale](#4-consigne-additionnelle-1--login-du-back-office-par-reconnaissance-faciale)
5. [Sécurité mise en place](#5-sécurité-mise-en-place)
6. [Installation et démarrage](#6-installation-et-démarrage)
7. [Adresses et comptes](#7-adresses-et-comptes)
8. [Jouer la démo](#8-jouer-la-démo)
9. [Dépannage](#9-dépannage)
10. [Limites connues](#10-limites-connues)
11. [Arborescence](#11-arborescence)
12. [Documentation](#12-documentation)

---

## 1. Le scénario de démonstration

```
 1. Trafic normal         des faux clients se connectent, consultent, paient
        │
 2. Attaque               depuis un PC Kali : scan, injection SQL, force brute, surcharge
        │
 3. Défense immédiate     WAF (403), limitation de débit (429), verrouillage de compte
        │
 4. Détection ML          le détecteur voit l'anomalie dans les métriques et la classe
        │                 (force_brute, intrusion_applicative, disponibilite, integrite...)
 5. Remédiation auto      le moteur applique le playbook adapté au type d'incident
        │                 (redémarrage de service, contrôle d'intégrité, confinement...)
 6. Preuve de reprise     un paiement témoin de 1,00 € passe par la passerelle → COMPLETED
        │
 7. Supervision           tout est visible en direct dans la console admin et dans Grafana
```

Cette chaîne a été jouée de bout en bout avec une vraie attaque depuis une VM Kali sur le réseau
local : le détecteur a ouvert et classé deux incidents différents (injection SQL →
`intrusion_applicative`, force brute → `force_brute`), le moteur les a traités, et le paiement
témoin est passé.

---

## 2. Architecture

```
                         PC Attaquant (Kali)            Navigateur client / opérateur
                                 │                                  │
                                 ▼                                  ▼
                 ┌──────────────────────────────────────────────────────────────┐
  port 8080  ──▶ │  PASSERELLE  Nginx + ModSecurity (OWASP CRS), limites de     │
  (seul accès)   │              débit, liste d'IP bannies, CSP                  │
                 └──────┬──────────────┬──────────────┬──────────────┬──────────┘
                        │ /            │ /console/    │ /api/...     │ /api/admin/
                        ▼              ▼              ▼              ▼
                  Site client    Console admin   auth-service    admin-api
                  (React)        (React)         payment-api        │
                                                 ledger-service     │
                                                      │             │
                                         PostgreSQL ◀─┤             │
                                         Redis ◀──────┘             │
                                                                    ▼
   Prometheus ◀── exporteurs, services          ml-detector ──▶ remediation-engine
   Loki ◀──────── Alloy (journaux Docker)       (IsolationForest)   │  proxy Docker restreint
   Grafana ◀───── Prometheus + Loki                                 │  paiement témoin
                                                                    ▼
   Vault ──▶ Vault Agent ──▶ secrets rendus pour admin-api et remediation-engine

   ─── Hors Docker, sur le PC Hôte ────────────────────────────────────────────────
   Webcam USB ──▶ face-agent (OpenCV, :8070) ──MQTT──▶ Mosquitto (:1883) ──WiFi──▶ ESP8266 + LED
```

Le schéma complet est dans `docs/architecture.png` (source Mermaid : `docs/architecture.mmd`).

### Cloisonnement réseau

Les services sont répartis sur des réseaux Docker séparés. La plupart sont **internes** (aucune
sortie vers Internet, aucun port publié).

| Réseau | Interne | Qui est dessus |
|---|---|---|
| `edge` | non | passerelle (publie le port 8080) |
| `app` | oui | services métier, fronts, admin-api, moteur de remédiation |
| `data` | oui | PostgreSQL, Redis et les services qui les utilisent |
| `obs` | oui | Prometheus, Loki, Alloy, exporteurs, détecteur ML |
| `dockerapi-ro` | oui | proxy Docker en lecture seule, pour Alloy |
| `dockerapi-rw` | oui | proxy Docker restreint, pour le moteur de remédiation |
| `vault` | oui | serveur Vault, amorçage, agent |
| `mgmt` | non | Grafana et Vault, publiés sur `127.0.0.1` uniquement |
| `iot` | non | broker MQTT (doit être joignable par l'ESP8266 sur le LAN) |

Depuis le réseau local, on ne voit que **8080** (passerelle) et **1883** (MQTT). Grafana et Vault
ne sont accessibles que depuis le PC Hôte lui-même.

---

## 3. Les composants

Environ 23 conteneurs, plus le service de reconnaissance faciale et la carte ESP8266.

### Applications

| Composant | Techno | Rôle |
|---|---|---|
| `gateway` | Nginx + ModSecurity, OWASP CRS | Seul point d'entrée. WAF, limites de débit par IP, liste d'IP bannies, routage, en-têtes de sécurité |
| `frontend` | React, Vite, Tailwind | Espace client Devolut : connexion, solde, historique, virement. Refuse les comptes opérateurs |
| `admin-frontend` | React, Vite, Tailwind | Back-office servi sur `/console/` : login par reconnaissance faciale, supervision, actions, habilitations |
| `auth-service` | FastAPI | Connexion, jetons JWT RS256 (clés publiées en JWKS), MFA TOTP obligatoire pour `operator` et `admin`, verrouillage après échecs (Redis), gestion des comptes opérateurs |
| `payment-api` | FastAPI | Paiements avec `Idempotency-Key` (pas de double débit), statut `PENDING` puis réconciliation automatique toutes les 15 s |
| `ledger-service` | FastAPI | Grand livre en partie double, contrôle d'intégrité toutes les 30 s, gel d'un compte ou gel global |
| `admin-api` | FastAPI | API de la console. Vérifie le rôle, agrège détecteur + Prometheus, relaie les actions vers le moteur |
| `postgres` | PostgreSQL 16 | Un rôle et un schéma par service, pas d'accès croisé |
| `redis` | Redis | Compteurs d'échecs de connexion et verrous |

### Détection et réponse

| Composant | Rôle |
|---|---|
| `ml-detector` | Lit une douzaine d'indicateurs dans Prometheus toutes les 15 s (blocages WAF, 429, 403, échecs de login, latence, services en ligne, intégrité...). Apprend le trafic normal avec un **IsolationForest**, note chaque mesure, ouvre un incident et le classe. Garde-fous : seuil de score, déclencheur dur sur z-score ≥ 3, signaux durs (intégrité, service tombé), anti-rebond (2 mesures pour ouvrir, 4 pour fermer) |
| `remediation-engine` | Interroge le détecteur toutes les 5 s. À chaque nouvel incident, applique le playbook du type, puis lance un **paiement témoin** (compte `probe`, 1,00 €, à travers la passerelle, jusqu'à 6 essais). Garde un historique. Porte aussi les actions manuelles : blocage d'IP, gel du grand livre |
| `docker-proxy-rw` | Proxy vers le socket Docker qui n'autorise que la gestion des conteneurs (redémarrage, signal). Pas d'`exec`, pas d'images, pas de volumes |

Playbooks par type d'incident :

| Incident | Action |
|---|---|
| `disponibilite` | redémarre les conteneurs du projet qui ne tournent plus |
| `integrite` | relance le contrôle d'intégrité du grand livre |
| `force_brute` / `intrusion_applicative` | vérifie que le confinement WAF et les verrous sont actifs |
| `surcharge` | vérifie que la limitation de débit joue son rôle |

### Supervision

| Composant | Rôle |
|---|---|
| `prometheus` | Collecte les métriques, 12 règles d'alerte (`infra/prometheus/alerts.yml`) |
| `loki` + `alloy` | Collecte des journaux Docker (via un proxy en lecture seule). Alloy fabrique aussi des compteurs à partir des journaux de la passerelle |
| `nginx-exporter`, `postgres-exporter`, `redis-exporter` | Métriques de l'infrastructure |
| `grafana` | Deux tableaux de bord : « Vue d'ensemble » et « Vue SOC » (avec une section détection ML). Générés par `scripts/build_dashboards.py` |

### Secrets

| Composant | Rôle |
|---|---|
| `vault` | Vrai serveur HashiCorp Vault (pas le mode dev), stockage fichier, interface web |
| `vault-bootstrap` | Conteneur ponctuel : initialise, descelle, charge les 11 secrets en KV v2, crée la politique `resilience-read` et le rôle AppRole. Peut être relancé sans risque |
| `vault-agent` | S'authentifie en AppRole et écrit les secrets dans un volume lu par `admin-api` et `remediation-engine` |

Les services migrés lisent d'abord `/vault/secrets`, puis retombent sur les secrets Docker
(`/run/secrets`) si Vault est scellé. La démo ne casse donc pas si Vault n'est pas prêt.

---

## 4. Consigne additionnelle 1 : login du back-office par reconnaissance faciale

Demande de l'école : renforcer l'accès au back-office avec une reconnaissance faciale (webcam
branchée sur le PC Hôte) et un objet connecté qui affiche l'état avec une LED rouge/verte.

### Déroulé du login

```
 Identifiant saisi
      │
      ▼
 Webcam activée, vidéo en direct ──▶ reconnaissance (YuNet + SFace)
      │                                   │
      │ reconnu                           │ non reconnu
      ▼                                   ▼
 LED verte clignotante              LED rouge fixe 30 s, identifiant vidé
 champ mot de passe débloqué        1 nouvel essai, puis blocage 5 min
      │
      ├── mauvais mot de passe ──▶ LED rouge clignote 10 fois, retour au début
      │
      ▼ bon mot de passe (+ code MFA)
 LED verte fixe 30 s, la console s'ouvre
```

Un voyant à l'écran reproduit les mêmes états que la LED physique.

### Les pièces

| Pièce | Où | Détail |
|---|---|---|
| `services/face-agent` | PC Hôte, hors Docker | FastAPI sur `127.0.0.1:8070`. OpenCV YuNet (détection) + SFace (empreinte), sur le processeur. Endpoints `/recognize`, `/snapshot` (vidéo), `/enroll`, `/faces`, `/led`. Rouvre la webcam tout seul si elle renvoie des images noires |
| `mqtt` | Docker | Mosquitto, port 1883, sujet `resilience/backoffice/led` |
| `firmware/led-backoffice` | ESP8266 NodeMCU | PlatformIO (CLion). Se connecte au WiFi et au broker, pilote la LED selon le message reçu. Autotest vert puis rouge au démarrage |
| Écran Habilitations | Console admin | Création d'opérateurs (avec QR code MFA), activation, suppression, **enrôlement du visage depuis la console** |

### Câblage de la LED

LED bicolore à cathode commune, deux résistances de 220 Ω.

| Broche ESP8266 | via | Patte de la LED |
|---|---|---|
| D1 | résistance 220 Ω | rouge |
| D2 | résistance 220 Ω | verte |
| G | fil direct | commune (la plus longue) |

Si les couleurs sont inversées au démarrage, échanger `PIN_ROUGE` et `PIN_VERT` dans
`firmware/led-backoffice/src/main.cpp`.

### États de la LED (messages MQTT)

| Message | Effet | Quand |
|---|---|---|
| `off` | éteinte | par défaut |
| `vert_clignotant` | vert clignotant | visage reconnu, saisie du mot de passe |
| `vert_fixe` | vert fixe 30 s | mot de passe validé |
| `rouge_fixe` | rouge fixe 30 s | visage non reconnu |
| `rouge_clignote` | rouge, 10 clignotements | mot de passe faux |

---

## 5. Sécurité mise en place

**En entrée**
- WAF ModSecurity avec les règles OWASP CRS : injection SQL, XSS, traversée de chemin bloquées (403).
- Limites de débit par IP sur l'API et plus strictes sur le login (429), nombre de connexions par IP plafonné.
- Liste d'IP bannies modifiable à chaud depuis la console (rechargement de Nginx sans coupure).
- CSP stricte, différente pour le site client et pour la console.

**Authentification**
- JWT signés en RS256, vérifiés par chaque service via JWKS.
- MFA TOTP obligatoire pour les rôles `operator` et `admin`.
- Verrouillage du compte après plusieurs échecs.
- Back-office : visage + mot de passe + code MFA.

**Métier**
- Clé d'idempotence sur chaque paiement, pas de double débit en cas de rejeu.
- Comptabilité en partie double avec verrouillage des lignes (`SELECT ... FOR UPDATE`) et contrôle
  d'intégrité permanent. Le détecteur a d'ailleurs trouvé un vrai bug de mise à jour perdue sous
  forte concurrence, corrigé dans `services/ledger-service/app/ledger.py`.
- Gel global du grand livre en cas d'urgence.

**Infrastructure**
- Conteneurs sans privilèges (`cap_drop: ALL`, `no-new-privileges`, utilisateur non-root), limites CPU / mémoire / processus.
- Réseaux internes, un seul port applicatif publié.
- Le socket Docker n'est jamais monté directement : deux proxys filtrants (lecture seule pour Alloy, actions limitées pour le moteur).
- Secrets générés en local, jamais versionnés, servis par Vault.
- L'admin-api refuse de bloquer l'adresse IP de l'opérateur qui fait la demande (évite de se fermer la porte au nez).

---

## 6. Installation et démarrage

### Prérequis

- **Docker Desktop** avec WSL2 (testé sous Windows 11). 8 Go de RAM alloués suffisent.
  C'est tout ce qu'il faut pour déployer : Ansible tourne dans un conteneur.
- **Python 3.11+** pour les scripts. Les scripts n'utilisent que la bibliothèque standard, sauf
  `init_secrets.py` qui utilise `cryptography` ou, à défaut, `openssl`.
- **Node.js** seulement pour lancer la console en mode développement.
- Pour la consigne 1 : une webcam USB, une carte ESP8266 NodeMCU, une LED bicolore, deux
  résistances de 220 Ω, et **PlatformIO** (`python -m pip install platformio`).

### Étape 1 : générer les secrets

```bash
python scripts/init_secrets.py
```

Crée le dossier `secrets/` (ignoré par git) et affiche les comptes de démonstration avec leurs
mots de passe et, pour `ops` et `admin`, la clé TOTP à ajouter dans une application
d'authentification. **Noter ces valeurs.** Pour tout régénérer : `--force`.

### Étape 2 : configuration (facultatif)

Les valeurs par défaut conviennent. Pour changer les ports ou les limites de débit :

```bash
cp .env.example .env
```

### Étape 3 : déployer avec Ansible

Le déploiement est automatisé par Ansible (dossier `ansible/`). Ansible ne tourne pas sous
Windows : il est embarqué dans un conteneur « poste de pilotage » qui pilote le Docker du PC
Hôte. Seul Docker est nécessaire. Le lanceur construit l'image tout seul à la première utilisation.

```powershell
.\scripts\ra.ps1 deploy          # Windows
```
```bash
scripts/ra.sh deploy             # Linux / macOS
```

Le playbook `site.yml` enchaîne six rôles, tous idempotents (on peut le relancer sans risque) :

| Rôle | Ce qu'il fait |
|---|---|
| `prerequis` | vérifie le moteur Docker, Compose, la mémoire allouée, la présence du dépôt |
| `secrets` | génère les secrets manquants, sans jamais les afficher |
| `deploiement` | `docker compose up` (construit les images si besoin), attend que les 23 services soient en marche et sains |
| `vault` | relance l'amorçage, vérifie que Vault est initialisé et descellé |
| `verification` | passerelle, site client, console, routes internes cachées, WAF, puis le test de bout en bout |
| `audit` | contrôle les conteneurs lancés : pas de mode privilégié, `no-new-privileges` partout, socket Docker réservé aux proxys, seuls les ports autorisés publiés, aucun secret ni donnée biométrique dans git |

Les autres commandes du lanceur :

```powershell
.\scripts\ra.ps1 verifier                     # contrôle + audit, sans rien modifier
.\scripts\ra.ps1 desceller                    # après un redémarrage du PC ou de Docker
.\scripts\ra.ps1 deploy -e ra_build=always    # reconstruit les images après une modification du code
.\scripts\ra.ps1 deploy --tags verification   # un seul rôle
.\scripts\ra.ps1 arreter                      # arrête (données conservées ; -e ra_purger=true pour tout effacer)
.\scripts\ra.ps1 sauvegarder                  # sauvegarde chiffrée : base, secrets, modèle ML, visages
.\scripts\ra.ps1 restaurer                    # reconstruction avec les données (PRA), ici ou sur une machine neuve
.\scripts\ra.ps1 compose ps                   # toute commande docker compose sur le projet
.\scripts\ra.ps1 compose up -d --build admin-api
```

La sauvegarde et la reprise après sinistre (PRA) sont détaillées dans `ansible/README.md`.

> **Important** : une fois la plateforme déployée par Ansible, passer par `ra.ps1 compose ...`
> plutôt que par `docker compose ...` lancé directement sous Windows. Les deux voient les chemins
> du dépôt différemment (`C:\...` contre `/c/...`), et Compose recréerait alors tous les conteneurs.

Sans Ansible, la plateforme se lance aussi à la main avec `docker compose up -d --build`. Vault
est alors à desceller avec `docker compose up -d --force-recreate vault-bootstrap` après chaque
redémarrage.

### Étape 4 : vérifier

`ra.ps1 deploy` et `ra.ps1 verifier` lancent déjà le test de bout en bout. Pour le lancer seul :

```bash
python scripts/smoke_test.py
```

Teste le parcours complet à travers la passerelle : connexion, consultation, paiement,
idempotence, solde insuffisant, jeton absent ou invalide, blocage d'une injection SQL par le WAF,
routes internes invisibles. Code de sortie 0 si tout passe. Pour viser une autre machine :
`--base-url http://<ip>:8080`.

### Étape 5 : reconnaissance faciale (PC Hôte)

Une seule fois :

```bash
cd services/face-agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python download_models.py
```

Puis à chaque session :

```bash
.venv\Scripts\python -m uvicorn face_service:app --host 127.0.0.1 --port 8070
```

L'enrôlement des visages se fait depuis la console (onglet **Habilitations**). En ligne de
commande, il existe aussi `python enroll.py --name <identifiant>` (arrêter le service avant, il
garde la webcam). Les empreintes sont stockées dans `faces.json`, qui n'est **pas versionné**
(donnée biométrique).

### Étape 6 : l'ESP8266

1. Câbler la LED (voir [section 4](#câblage-de-la-led)).
2. Dans `firmware/led-backoffice/src/main.cpp`, remplir `WIFI_SSID`, `WIFI_PASSWORD` et
   `MQTT_HOST` (l'IP du PC Hôte sur ce réseau).
3. Brancher la carte en USB et téléverser :

   ```bash
   cd firmware/led-backoffice
   python -m platformio run -t upload
   ```

4. Au démarrage, la LED fait vert puis rouge : le câblage est bon.

L'ESP8266 ne fonctionne qu'en **WiFi 2,4 GHz**. Le point d'accès mobile de Windows 11 ne marche
pas avec cette carte ; utiliser un vrai routeur ou le partage de connexion d'un téléphone
(sur iPhone : activer « Maximiser la compatibilité »). Le PC Hôte doit être sur le même réseau.

Test manuel d'un état sans passer par le login :

```bash
curl -X POST http://127.0.0.1:8070/led -H "Content-Type: application/json" -d '{"state":"vert_fixe"}'
```

Le détail est dans `firmware/led-backoffice/README.md`.

### Arrêter

```bash
docker compose down        # arrête et supprime les conteneurs
docker compose down -v     # idem + efface les volumes (base, métriques, modèle ML, Vault)
```

---

## 7. Adresses et comptes

### Interfaces

| Interface | Adresse | Accès |
|---|---|---|
| Site client Devolut | <http://localhost:8080> | LAN |
| Console admin | <http://localhost:8080/console/> | LAN, mais la webcam doit être sur le PC Hôte |
| Console admin (développement) | <http://localhost:5174> (`cd services/admin && npm install && npm run dev`) | PC Hôte |
| Grafana | <http://127.0.0.1:3000> (utilisateur `admin`, mot de passe dans `secrets/grafana_admin_password`) | PC Hôte uniquement |
| Vault | <http://127.0.0.1:8200> (méthode Token, jeton racine ci-dessous) | PC Hôte uniquement |
| Service visage | <http://127.0.0.1:8070> | PC Hôte uniquement |
| Broker MQTT | `<ip du PC Hôte>:1883` | LAN |

Jeton racine de Vault :

```bash
docker run --rm -v resilience-alpha_vault-init:/i hashicorp/vault:1.18 sh -c 'awk "/Initial Root Token:/{print \$NF}" /i/init.txt'
```

### Comptes de démonstration

Les mots de passe sont générés par `init_secrets.py` et stockés dans `secrets/seed_users`.

| Identifiant | Rôle | Usage |
|---|---|---|
| `alice`, `bob`, `chloe` | client | site client |
| `probe` | client | paiement témoin du moteur de remédiation (caché de la liste des bénéficiaires) |
| `ops` | operator | console admin (visage + mot de passe + MFA) |
| `admin` | admin | console admin, avec en plus l'écran Habilitations |

---

## 8. Jouer la démo

### 1. Faire vivre la plateforme

```bash
python scripts/traffic/normal_traffic.py                    # en continu
python scripts/traffic/normal_traffic.py --duration 600     # 10 minutes
python scripts/traffic/normal_traffic.py --intensity calme  # calme | moyen | actif
```

Ce trafic sert aussi de **référence au détecteur ML**. Avant la démo, le laisser tourner une
dizaine de minutes pour que le modèle apprenne sur une base solide.

### 2. Ouvrir les écrans

- La console admin (`/console/`), connecté en `ops` ou `admin` : incidents en direct, état des
  services, historique des remédiations, boutons d'action.
- Grafana, tableau « Vue SOC » : blocages WAF, 429, échecs de login, score du détecteur.

### 3. Attaquer

Exercice pédagogique autorisé, uniquement contre la passerelle du projet.

- **Depuis Kali** (VM en accès par pont sur le même réseau que le PC Hôte), avec les vrais outils :
  `nmap`, `nikto`, `sqlmap`, `ffuf`, `hydra`, `ab`. Commandes exactes dans
  `scripts/attack/kali-playbook.md`.
- **Rejeu automatique** (sans dépendance) :

  ```bash
  python scripts/attack/attack_suite.py --help
  ```

  Phases : `recon`, `waf`, `bruteforce`, `flood`. Les phases de charge sont bornées en nombre de
  requêtes et en durée.

Une attaque doit **durer** (une trentaine de secondes ou plus) : un pic très court est lissé par
la fenêtre de calcul des métriques.

### 4. Ce qu'on doit voir

| Moment | Où | Signal |
|---|---|---|
| L'attaque frappe | Grafana SOC | pics de 403 (WAF), 429 (débit), 401 / verrouillages |
| ~20 s après | Console | un incident apparaît, avec son type et son score |
| Juste après | Console, Remédiations | playbook appliqué puis « paiement témoin OK » |
| Toujours | Site client | un client peut encore payer |

Depuis la console, l'opérateur peut aussi agir à la main : relancer une remédiation, geler ou
dégeler le grand livre, bloquer ou débloquer une IP.

---

## 9. Dépannage

| Problème | Solution |
|---|---|
| Un compte de démo est verrouillé après une force brute | Purger les verrous Redis : `docker exec resilience-alpha-redis-1 redis-cli -a "$(cat secrets/redis_password)" --no-auth-warning --scan --pattern 'fail:*'` puis `DEL` sur chaque clé |
| Vault scellé après un redémarrage | `.\scripts\ra.ps1 desceller` |
| La vidéo de la webcam est noire | Le service se rétablit tout seul en ~1,5 s. Sinon, redémarrer `face_service`. Vérifier qu'aucune autre application n'utilise la webcam |
| Visage non reconnu alors qu'il est enrôlé | Regarder la webcam en face (pas l'écran en dessous). Seuil réglable dans `face_lib.py` (`COSINE_THRESHOLD`, 0.363 par défaut) |
| L'ESP8266 ne se connecte pas au WiFi | Réseau 2,4 GHz obligatoire, pas le point d'accès mobile de Windows 11 |
| Modification de `infra/gateway/default.conf.template` sans effet | `docker compose up -d --force-recreate gateway` |
| Accès bloqué après avoir banni sa propre IP | Remettre `infra/gateway/blocklist/banned.conf` à ses deux lignes d'en-tête puis `docker exec resilience-alpha-gateway-1 nginx -s reload` |
| Le détecteur se trompe ou crie au loup | Faire tourner le trafic normal ~10 min puis réentraîner (`POST /internal/train` sur `ml-detector`) |
| Rôle `monitor_svc` absent après remise à zéro de la base | Relancer `infra/postgres/init/02-monitoring.sh` (sous Windows avec `MSYS_NO_PATHCONV=1`) |

---

## 10. Limites connues

- **IP source masquée par Docker Desktop.** Sous Windows, Docker Desktop réécrit l'adresse des
  clients extérieurs (tout le monde apparaît en `172.22.0.1`, même depuis Kali). Le blocage par
  IP fonctionne (testé), mais ne peut pas distinguer l'attaquant de l'opérateur sur cette
  installation. La défense repose donc ici sur le WAF, la limitation de débit et le verrouillage
  de compte. Sur un hôte Linux, l'IP réelle serait visible.
- **MQTT sans authentification.** Le broker accepte les connexions anonymes pour la démo. À
  sécuriser (utilisateurs + TLS) avant toute vraie mise en service.
- **Gel global du grand livre en mémoire.** Un redémarrage de `ledger-service` le lève.
- **Paiement refusé pendant un gel.** Le client voit `REJECTED`, sans le motif précis.
- **Vault** : une seule clé de descellement, stockée dans un volume local. Suffisant pour la
  démo, pas pour de la production.
- **Restent à faire** : assistant RAG (Ollama + LangChain), volet gouvernance (PCA/PRA, NIS2,
  DORA), analyse EBIOS RM complète.

---

## 11. Arborescence

```
resilience-alpha/
├── docker-compose.yml          orchestration de tous les conteneurs
├── .env.example                ports et limites de débit
├── ansible/                    déploiement automatisé (playbooks, rôles, image du poste de pilotage)
├── docs/                       architecture, analyse de risque, playbook d'attaque, consigne 1
├── firmware/
│   └── led-backoffice/         firmware ESP8266 (PlatformIO)
├── infra/
│   ├── gateway/                configuration Nginx + liste d'IP bannies
│   ├── prometheus/             collecte et règles d'alerte
│   ├── loki/  alloy/           journaux
│   ├── grafana/                tableaux de bord et sources de données
│   ├── postgres/init/          rôles et schémas par service
│   ├── mosquitto/              broker MQTT
│   └── vault/                  serveur, agent, script d'amorçage
├── scripts/
│   ├── ra.ps1 / ra.sh          lanceur : Ansible et Compose via le poste de pilotage
│   ├── init_secrets.py         génération des secrets et des comptes
│   ├── smoke_test.py           test de bout en bout
│   ├── build_dashboards.py     génération des tableaux Grafana
│   ├── traffic/                faux clients légitimes
│   └── attack/                 suite d'attaque + mémo Kali
├── secrets/                    généré en local, jamais versionné
└── services/
    ├── common/                 code Python partagé (secrets, JWT, logs, base)
    ├── python.Dockerfile       image unique pour tous les services Python
    ├── frontend/               site client Devolut
    ├── admin/                  console admin (login visage, supervision, habilitations)
    ├── auth-service/
    ├── payment-api/
    ├── ledger-service/
    ├── admin-api/
    ├── ml-detector/
    ├── remediation-engine/
    └── face-agent/             reconnaissance faciale, tourne sur le PC Hôte
```

---

## 12. Documentation

| Document | Contenu |
|---|---|
| `docs/architecture.md` | Dossier d'architecture : rôle de chaque composant, flux, choix techniques |
| `docs/architecture.png` | Schéma d'architecture |
| `ansible/README.md` | Déploiement automatisé : playbooks, rôles, variables, poste de pilotage |
| `docs/ebios-rm.md` | Analyse de risques EBIOS RM (brouillon) |
| `docs/playbook-attaque.md` | Scénario d'attaque, règles d'engagement, réponses attendues |
| `docs/consigne-additionnelle-1.md` | Conception de la reconnaissance faciale et de l'objet connecté |
| `scripts/attack/kali-playbook.md` | Commandes Kali, chacune reliée au signal défensif attendu |
| `services/face-agent/README.md` | Installation et usage de la reconnaissance faciale |
| `firmware/led-backoffice/README.md` | Câblage, téléversement et test de l'ESP8266 |
