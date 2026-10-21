# Reconnaissance faciale — PC Hôte

Tourne **sur le PC Hôte** (hors Docker : accès direct à la webcam USB). Détection YuNet +
reconnaissance SFace (OpenCV), sur le processeur, sans GPU.

## Installation (une fois)

```bash
cd services/face-agent
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt
python download_models.py      # télécharge les 2 modèles
```

## Enrôler ton visage

```bash
python enroll.py --name karim
```
Regarde la caméra, bouge un peu la tête, appuie sur **ESPACE** pour capturer (7 fois).
Refais la commande avec un autre `--name` pour ajouter d'autres personnes.

## Vérifier que ça marche

```bash
python recognize.py
```
- Ton visage → cadre **vert** + ton nom.
- Un visage inconnu → cadre **rouge** + « Inconnu ».

`q` pour quitter.

## Régler la sévérité

Dans `face_lib.py`, `COSINE_THRESHOLD` (défaut `0.363`) :
- plus **haut** = plus strict (moins de faux positifs, mais peut rejeter à tort),
- plus **bas** = plus permissif.

## Fichiers

| Fichier | Rôle |
|---|---|
| `download_models.py` | télécharge les modèles YuNet + SFace |
| `enroll.py` | enrôle un visage depuis la webcam |
| `recognize.py` | reconnaissance en direct (test visuel) |
| `face_lib.py` | briques communes (détection, empreinte, comparaison) |
| `faces.json` | empreintes enrôlées — **données biométriques, hors dépôt** |

Prochaine étape : exposer une petite API (ex. `/recognize`) que la page de login du
back-office appellera pour débloquer le mot de passe et piloter la LED.
