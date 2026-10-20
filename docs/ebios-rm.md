# RESILIENCE-ALPHA — Analyse de risques EBIOS RM

> Version 0.1 — 19/10/2026 — pour validation coach (sprint 1)
> Auteur : Karim Boudali — Consortium G‹n›
> Ateliers 1 et 2 détaillés ; ateliers 3 à 5 en premier jet, complétés aux sprints 2 et 3.

## Contexte

**Banque Résilience** (fictive) est un établissement de paiement régional. Il traite les paiements de ses clients particuliers vers des commerçants partenaires.

Hypothèses d'activité, fictives et servant à chiffrer les impacts :
- environ 1 200 paiements par heure en journée ;
- montant moyen de 45 € ;
- 30 commerçants partenaires.

L'établissement est soumis à **DORA** (entité financière) et entre dans le champ de **NIS2**.

## Échelles

| Gravité | Signification |
|---|---|
| **G4 — Critique** | Atteinte à l'exactitude des comptes, ou arrêt des paiements de plus de 4 h. Incident majeur à notifier (DORA), perte de confiance durable |
| **G3 — Grave** | Paiements indisponibles plus de 30 min, ou fuite de données clients. Notification probable, plaintes, perte de chiffre d'affaires des partenaires |
| **G2 — Significative** | Service dégradé moins de 30 min, quelques opérations retardées puis rattrapées |
| **G1 — Mineure** | Gêne ponctuelle, sans impact client mesurable |

| Vraisemblance | Signification |
|---|---|
| **V4 — Quasi certaine** | Attaque courante, outillée, à la portée d'un attaquant peu qualifié |
| **V3 — Très vraisemblable** | Attaque fréquente contre le secteur financier, demande un peu de préparation |
| **V2 — Vraisemblable** | Demande une faille ou une compétence particulière |
| **V1 — Peu vraisemblable** | Demande des moyens importants ou un concours de circonstances |

---

## Atelier 1 — Cadrage et socle de sécurité

### Valeurs métier (ce qu'on protège)

| Réf. | Valeur métier | Biens supports |
|---|---|---|
| **VM1** | **Traiter les paiements** des clients | passerelle, payment-api, ledger-service, PostgreSQL, PC Hôte |
| **VM2** | **Tenir des comptes exacts** (soldes et historique) | ledger-service, PostgreSQL |
| **VM3** | **Authentifier les clients et opérateurs** | auth-service, Redis, clé de signature JWT |
| **VM4** | **Tracer les opérations** (preuve, investigation, notification) | journaux, Loki, Grafana |

### Événements redoutés

| Réf. | Événement redouté | Valeur | Impacts | Gravité |
|---|---|---|---|---|
| **ER1** | Les paiements sont indisponibles | VM1 | Environ 54 000 € de paiements bloqués par heure, partenaires pénalisés, image dégradée | **G3** (G4 au-delà de 4 h) |
| **ER2** | Des soldes ou des écritures sont falsifiés