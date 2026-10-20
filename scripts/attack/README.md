# Scénario d'attaque — RESILIENCE-ALPHA

Exercice **pédagogique autorisé**, dans le cadre du workshop MSPR. Ces outils ne visent que la
plateforme fictive du groupe, sur le réseau du consortium, et ne doivent être lancés que par vous,
depuis le **PC Attaquant (Kali)**.

## À quoi ça sert

Produire des signaux mesurables que la chaîne de résilience doit repérer : pare-feu applicatif,
limitation de débit, échecs de connexion répétés, pic de trafic. Ces signaux alimentent la
supervision (Prometheus / Loki / Grafana) puis le détecteur ML, qui déclenche la remédiation.

## Prérequis

- Le PC Attaquant (VM Kali en mode pont) est connecté au point d'accès du groupe `RESILIENCE-G<n>`.
- Python 3 (déjà présent sur Kali). **Aucune installation** : le script n'utilise que la bibliothèque standard.
- L'adresse de la passerelle, en général `http://192.168.137.1:8080` (le PC Hôte).

Vérifiez d'abord que la plateforme répond depuis Kali :

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.137.1:8080/healthz   # attendu : 200
```

## Lancer le scénario

```bash
# Scénario complet (toutes les phases, dans l'ordre)
python3 attack_suite.py --target http://192.168.137.1:8080 --phase all

# Une ou plusieurs phases
python3 attack_suite.py --target http://192.168.137.1:8080 --phase waf,flood

# Sans confirmation interactive (pour la démo)
python3 attack_suite.py --target http://192.168.137.1:8080 --phase all --yes
```

## Les phases

| Phase | Ce qu'elle fait | Signal attendu côté défense |
|---|---|---|
| `whoami` | Une requête étiquetée, pour retrouver l'IP source vue côté serveur | sert au test d'IP ci-dessous |
| `recon` | Balayage de chemins courants (`/admin`, `/.env`, `/.git/config`…) | beaucoup de 404 et 403 |
| `waf` | Sondes classiques : injection SQL, XSS, traversée de chemin, injection de commande | 403, requêtes bloquées par le pare-feu |
| `bruteforce` | Tentatives de connexion répétées avec de faux mots de passe | 401 puis 429, verrouillage du compte |
| `flood` | Pic de trafic court et borné (connexions persistantes) | 429, limitation de débit par IP |

Réglages utiles : `--bruteforce N` (nombre de tentatives), `--flood N` (requêtes du pic),
`--threads N` (fils du pic), `--delay S` (pause entre requêtes des phases séquentielles),
`--user NOM` (compte visé par la force brute). Les valeurs par défaut sont modestes et bornées.

## Test de l'IP source réelle (priorité)

Sous Windows, Docker Desktop peut masquer l'adresse de l'attaquant : les journaux montreraient
l'IP interne du pont Docker (`172.22.0.1`) au lieu de l'IP réelle de Kali. À vérifier **depuis Kali** :

1. Sur Kali, notez l'adresse réelle : `ip a` (interface du point d'accès, ex. `192.168.137.x`).
2. Lancez la phase whoami, qui affiche une étiquette unique :
   ```bash
   python3 attack_suite.py --target http://192.168.137.1:8080 --phase whoami --yes
   ```
3. Sur le **PC Hôte**, retrouvez la requête et l'IP enregistrée :
   ```bash
   docker compose logs gateway --since 2m | grep REDTEAM-WHOAMI-XXXXXX
   ```
4. Comparez le `client_ip` du journal à l'IP réelle de Kali.
   - **Identiques** → la passerelle voit la vraie IP ; le blocage par IP fonctionnera.
   - **Différents** (`172.22.0.1`) → Docker Desktop masque l'IP ; la remédiation devra s'appuyer
     sur d'autres critères (motif d'attaque, règle WAF, limitation globale) plutôt que sur l'IP seule.

## Observer les effets

Sur le PC Hôte, pendant et après l'attaque :

- **Grafana → Vue SOC** : <http://127.0.0.1:3000> — le graphe « Activité suspecte » montre le pic en direct ;
  les tableaux listent les règles du pare-feu déclenchées et les journaux de sécurité.
- Les alertes Prometheus de sécurité (`AttaqueApplicativeBloquee`, `LimitationDeDebit`,
  `ForceBruteConnexion`) passent en « firing » si les seuils sont franchis.

> Note sur les compteurs « total sur la période » de la Vue SOC : ils s'appuient sur `increase()`.
> La toute première fois qu'un type d'événement apparaît (ex. le premier 429 jamais vu), le total
> peut être légèrement sous-estimé ; le graphe en « taux par minute », lui, montre fidèlement le pic.
> En conditions de démo, le détecteur ML aura déjà généré un trafic de référence, donc les compteurs
> existent et sont justes.
