"""Enrôler un visage depuis le service en marche (regarde la caméra pendant l'appel).

Usage : python enroll_live.py ops
Le service doit tourner (port 8070). Pas de conflit de caméra : c'est le service
qui capture. Mets-toi bien face à la webcam pendant les ~2 secondes de capture.
"""

import json
import sys
import urllib.request

name = sys.argv[1] if len(sys.argv) > 1 else input("Nom à enrôler : ")
req = urllib.request.Request(
    "http://127.0.0.1:8070/enroll",
    data=json.dumps({"name": name}).encode(),
    headers={"Content-Type": "application/json"},
)
print("Capture en cours, regarde la caméra…")
print(json.load(urllib.request.urlopen(req, timeout=30)))
