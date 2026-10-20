# Playbook d'attaque — RESILIENCE-ALPHA

> Version 0.1 — 19/10/2026 — Auteur : Karim Boudali — Consortium G‹n›
> Exercice de sécurité **pédagogique et autorisé** (workshop MSPR), sur une plateforme **fictive**.

Ce document décrit le scénario d'attaque joué pendant la démonstration : ce qui est attaqué,
comment, et **ce que la plateforme doit faire seule en réponse**. Les commandes détaillées sont
dans `scripts/attack/kali-playbook.md` ; le rejeu automatisé est dans `scripts/attack/attack_suite.py`.

## 1. Cadre et règles d'engagement

| Élément | Valeur |
|---|---|
| Cible autorisée | La passerelle du groupe uniquement : `http://192.168.137.1:8080` |
| Périmètre interdit | Toute autre machine, tout autre réseau, Internet |
| Poste attaquant | PC physique distinct, VM Kali en mode pont, sur le point d'accès `RESILIENCE-G‹n›` |
| Données | Entièrement fictives ; aucun paiement ni identifiant réel |
| Objectif | **Se faire détecter** pour déclencher la chaîne détection → remédiation, pas contourner la défense |
| Limites | Les phases de charge sont bornées (nombre de requêtes et durée fixés) : test de disponibilité, pas déni de service |

## 2. Dispositif

```
PC Attaquant (Kali)  ──  point d'accès Wi-Fi RESILIENCE-G‹n›  ──  PC Hôte (192.168.137.1:8080)
   nmap, nikto,                                                     Passerelle WAF  →  services
   sqlmap, ffuf,                                                    Supervision (Prometheus/Loki/Grafana)
   hydra, ab/wrk                                                    Détecteur ML → Remédiation
```

Seule la passerelle est exposée. La supervision et la console restent sur le PC Hôte (`127.0.0.1`).

## 3. Scénario chronométré

L'attaque suit une progression classique (reconnaissance → intrusion → charge). Chaque étape produit
un signal que la défense doit transformer en détection puis en action automatique.

| # | Étape | Outil Kali | Signal produit | Détection attendue | Remédiation attendue |
|---|---|---|---|---|---|
| 1 | Reconnaissance réseau | `nmap` | connexions, balayage de ports | trafic inhabituel ; preuve que seul 8080 est exposé | — (surveillance) |
| 2 | Énumération de chemins | `gobuster` / `ffuf` | rafale de 404/403 | pic de 404, IP source très active | durcissement des limites de débit |
| 3 | Scan de vulnérabilités | `nikto` | centaines de requêtes suspectes | pic de blocages WAF (403) | bannissement ou limitation de la source |
| 4 | Injection SQL | `sqlmap` | charges SQL sur un paramètre | règle « SQL Injection » du WAF, 403 en série | source bloquée ; alerte sécurité |
| 5 | Force brute | `ffuf` / `patator` / `hydra` | connexions répétées, 401 puis 429 | `login_failed`/`login_blocked`, alerte `ForceBruteConnexion` | verrouillage du compte, limitation renforcée |
| 6 | Pic de trafic (borné) | `ab` / `wrk` | montée des 429 | alerte `LimitationDeDebit` | limitation par IP, maintien du service |
| 7 | Test d'IP source | `curl` étiqueté | une requête tracée | — | décide du critère de blocage (IP ou autre) |

## 4. Preuve de résilience (le cœur de la démo)

La reprise ne se prouve pas par un simple redémarrage, mais par un **nouveau paiement réussi** après
l'incident, avec un grand livre cohérent :

1. **Avant** : un paiement de référence passe (COMPLETED), le grand livre est cohérent.
2. **Pendant** : l'attaque dégrade le service ; la supervision détecte l'anomalie.
3. **Remédiation automatique** (sans intervention humaine) : blocage de la source / durcissement /
   redémarrage / révocation de sessions selon le type d'incident.
4. **Vérification automatique** : un **paiement sonde** est rejoué et réussit ; le contrôle d'intégrité
   repasse au vert ; les paiements restés en attente sont finalisés.

Déjà démontré sans attaque : un paiement bloqué par une panne du grand livre reste « en attente »,
puis se finalise seul au retour du service, sans double débit.

## 5. Critères de réussite

- [ ] L'attaque est bien visible dans la Vue SOC (pic d'activité suspecte, règles WAF déclenchées).
- [ ] Au moins une alerte Prometheus de sécurité passe en « firing ».
- [ ] La remédiation se déclenche **sans action manuelle**.
- [ ] Le paiement sonde réussit après la remédiation ; le grand livre est cohérent.
- [ ] Aucune donnée falsifiée, aucun double débit.

## 6. Test de l'IP source réelle (à faire en premier)

Sous Windows, Docker Desktop peut masquer l'adresse de l'attaquant (les journaux montreraient l'IP
interne du pont Docker au lieu de celle de Kali). Procédure dans `scripts/attack/kali-playbook.md`, § 7.

- IP réelle de Kali visible dans les journaux → la remédiation peut **bannir par IP**.
- IP masquée (`172.22.0.1`) → la remédiation s'appuiera sur d'autres critères : **motif d'attaque,
  règle WAF déclenchée, limitation globale**, plutôt que l'IP seule.

Ce résultat conditionne la logique du moteur de remédiation ; il doit être tranché avant de la figer.

## 7. Références

- Commandes prêtes à l'emploi : `scripts/attack/kali-playbook.md`
- Rejeu automatisé (utile pour la vidéo de 60 s) : `scripts/attack/attack_suite.py`
- Architecture de la plateforme : `docs/architecture.md`
