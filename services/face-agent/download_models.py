"""Télécharge les deux modèles OpenCV nécessaires (une seule fois).

- YuNet  : détection de visage.
- SFace  : reconnaissance (empreinte du visage).

Les modèles viennent du dépôt officiel OpenCV Zoo. Lancer : python download_models.py
"""

import os
import sys
import urllib.request

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

MODELS = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    for name, url in MODELS.items():
        dest = os.path.join(MODELS_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"OK (déjà là) : {name}")
            continue
        print(f"Téléchargement : {name} ...")
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"  -> {dest} ({os.path.getsize(dest)//1024} Ko)")
        except Exception as exc:
            print(f"  ÉCHEC : {exc}")
            print(f"  Télécharge-le à la main depuis :\n    {url}\n  et place-le dans {MODELS_DIR}")
            sys.exit(1)
    print("Modèles prêts.")


if __name__ == "__main__":
    main()
