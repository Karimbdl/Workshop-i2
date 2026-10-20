# RESILIENCE-ALPHA

Plateforme de paiement fictive (groupe **Devolut**) servant de support au workshop MSPR M2.
L'objectif : montrer qu'une plateforme peut subir une attaque, la détecter toute seule par
apprentissage automatique, et se rétablir sans qu'un humain intervienne. La preuve de reprise
est un nouveau paiement qui passe avec un grand livre cohérent, pas juste un conteneur qui
redémarre.

Tout tourne en conteneurs Docker sur une seule machine. Les données sont entièrement fictives.

## Ce qu'il y a dedans

- **Passerelle** Nginx + ModSecurity (OWASP CRS), seul point d'entrée exposé (port 8080).
- **Site client** React + Tailwind.
- **Services métier** en Python/FastAPI : `auth-service` (JWT RS256, MFA), `payment-api`
  (idempotence, anti-rejeu), `ledger-service` (comptabilité en partie double).
- **Données** : PostgreSQL (un rôle et un schéma par service) et Redis (anti force brute).
- **Supervision** : Prometheus, Loki + Alloy, Grafana (vue SOC), et un détecteur ML qui lit
  les métriques et les journaux.

Le détail est dans `docs/architecture.md` (schéma, rôle de chaque composant) et l'analyse de
risque dans `docs/ebios-rm.md`.

## Prérequis

- **Docker Desktop** avec WSL2 (testé sous Windows 11).
- **Python 3.11+** pour les scripts (secrets, test, trafic). Pas de dépendance à installer :
  les scripts n'utilisent que la bibliothèque standard, sauf `init_secrets.py` qui sait générer
  la clé JWT avec `cryptography` ou, à défaut, avec `openssl`.

## Démarrage

### 1. Générer les secrets

Les secrets ne sont jamais versionnés. On les génère une fois, en local :

```bash
python scripts/init_secrets.py
```

Le script crée le dossier `secrets/` et affiche les comptes de démonstration avec leurs mots de
passe (à noter quelque part, ils servent pour se connecter et pour le test de bout en bout).
Pour tout régénérer : `python scripts/init_secrets.py --force`.

### 2. Configurer l'environnement (optionnel)

Les valeurs par défaut suffisent. Pour les changer :

```bash
cp .env.example .env
```

### 3. Lancer la plateforme

```bash
docker compose up -d --build
```

Le premier build prend quelques minutes (images Python et build du front). Pour suivre
l'état des conteneurs :

```bash
docker compose ps
```

### 4. Accéder aux interfaces

- **Site client** : <http://localhost:8080> — connexion avec un compte affiché à l'étape 1
  (ex. `alice`).
- **Grafana (vue SOC)** : <http://127.0.0.1:3000> — utilisateur `admin`, mot de passe dans
  `secrets/grafana_admin_password`. Publié sur `127.0.0.1` uniquement.

## Vérifier que tout marche

Test du parcours complet (connexion, consultation, paiement) à travers la passerelle, WAF
compris :

```bash
python scripts/smoke_test.py
```

Code de sortie 0 si tout passe. On peut viser une autre machine avec
`--base-url http://192.168.137.1:8080`.

## Faire vivre la démo

Générer du trafic de faux clients légitimes (sert aussi de référence au détecteur ML) :

```bash
python scripts/traffic/normal_traffic.py                 # en continu
python scripts/traffic/normal_traffic.py --duration 600  # 10 min puis s'arrête
python scripts/traffic/normal_traffic.py --intensity calme
```

Le scénario d'attaque (exercice pédagogique autorisé, à lancer depuis le PC attaquant) est
documenté à part : voir `scripts/attack/README.md`.

## Arrêter

```bash
docker compose down            # arrête et supprime les conteneurs
docker compose down -v         # idem + supprime les volumes (base, métriques, journaux)
```

## Arborescence

```
resilience-alpha/
├── docker-compose.yml      orchestration des conteneurs
├── .env.example            variables de la passerelle (débit, ports)
├── docs/                   architecture et analyse de risque EBIOS RM
├── infra/                  config passerelle, Prometheus, Loki, Grafana, Postgres
├── scripts/                secrets, test, trafic, génération des dashboards, attaque
├── secrets/                généré en local, jamais versionné
└── services/               code des microservices + front
```
