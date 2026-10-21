"""Briques communes de reconnaissance faciale (OpenCV YuNet + SFace).

YuNet détecte les visages ; SFace transforme un visage en une empreinte de 128 nombres.
Deux visages sont la même personne si la similarité cosinus dépasse un seuil.
"""

import os
import cv2
import numpy as np

BASE_DIR = os.path.dirname(__file__)
MODELS_DIR = os.path.join(BASE_DIR, "models")
DET_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
REC_PATH = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")

# Base des visages enrôlés : nom -> liste d'empreintes.
FACES_PATH = os.path.join(BASE_DIR, "faces.json")

# Seuil de reconnaissance en cosinus (recommandation SFace : 0.363).
# Plus haut = plus strict (moins de faux positifs).
COSINE_THRESHOLD = 0.363


def _check_models():
    for p in (DET_PATH, REC_PATH):
        if not os.path.exists(p):
            raise FileNotFoundError(
                "Modèles manquants. Lance d'abord : python download_models.py"
            )


def load_detector(size=(320, 320)):
    _check_models()
    return cv2.FaceDetectorYN.create(DET_PATH, "", size, 0.9, 0.3, 5000)


def load_recognizer():
    _check_models()
    return cv2.FaceRecognizerSF.create(REC_PATH, "")


def detect_faces(detector, frame):
    """Retourne la liste des visages détectés (chaque ligne : bbox + repères + score)."""
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    return faces if faces is not None else []


def largest_face(faces):
    """Le plus grand visage (le plus proche de la caméra), ou None."""
    if len(faces) == 0:
        return None
    return max(faces, key=lambda f: float(f[2]) * float(f[3]))


def embedding(recognizer, frame, face):
    """Empreinte (128 nombres) d'un visage détecté."""
    aligned = recognizer.alignCrop(frame, face)
    feat = recognizer.feature(aligned)
    return np.array(feat, dtype=np.float32)


def similarity(recognizer, feat_a, feat_b):
    """Similarité cosinus entre deux empreintes (plus c'est haut, plus c'est la même personne)."""
    return float(recognizer.match(feat_a, feat_b, cv2.FaceRecognizerSF_FR_COSINE))


def best_match(recognizer, feat, known):
    """Compare une empreinte à la base. Retourne (nom, score) ou (None, score)."""
    best_name, best_score = None, -1.0
    for name, feats in known.items():
        for ref in feats:
            s = similarity(recognizer, feat, np.array(ref, dtype=np.float32))
            if s > best_score:
                best_name, best_score = name, s
    if best_score >= COSINE_THRESHOLD:
        return best_name, best_score
    return None, best_score


# Repli si l'auto-détection de la webcam USB échoue.
DEFAULT_CAMERA_INDEX = 1


def find_usb_camera():
    """Index de la première caméra dont le nom contient « usb » (Windows), sinon None."""
    try:
        from pygrabber.dshow_graph import FilterGraph
        for i, name in enumerate(FilterGraph().get_input_devices()):
            if "usb" in name.lower():
                return i
    except Exception:
        pass
    return None


def open_camera(index=None):
    """Ouvre la webcam. Si index est None, choisit automatiquement la caméra USB.
    Sous Windows, DirectShow est plus fiable."""
    if index is None:
        found = find_usb_camera()
        index = found if found is not None else DEFAULT_CAMERA_INDEX
    backend = cv2.CAP_DSHOW if os.name == "nt" else 0
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la webcam (index {index}).")
    return cap
