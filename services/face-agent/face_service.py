"""Service de reconnaissance faciale du back-office (tourne sur le PC Hôte).

Expose une petite API HTTP que la page de login du back-office appelle :
  - POST /recognize : regarde par la webcam USB, dit si la personne est reconnue,
                      et pilote la LED (vert clignotant si reconnue, rouge fixe sinon).
  - POST /led       : force un état de LED (utilisé après la saisie du mot de passe).

Les commandes LED sont publiées en MQTT (sujet resilience/backoffice/led), reçues
par l'ESP8266. Si le broker MQTT n'est pas joignable, la reconnaissance marche quand
même (la LED est un simple indicateur).

Lancer : .venv\\Scripts\\python -m uvicorn face_service:app --host 0.0.0.0 --port 8070
"""

import json
import os
import threading

import cv2
import paho.mqtt.client as mqtt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import face_lib as fl

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_LED = "resilience/backoffice/led"
VALID_STATES = {"off", "eteinte", "vert_clignotant", "vert_fixe", "rouge_fixe", "rouge_clignote"}

app = FastAPI(title="RESILIENCE-ALPHA face-agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # le back-office tourne sur le même hôte
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.Lock()
_camera = None
_detector = None
_recognizer = None
_known = {}
_mqtt = None


def _load_faces():
    if os.path.exists(fl.FACES_PATH):
        with open(fl.FACES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _get_camera():
    global _camera
    if _camera is None or not _camera.isOpened():
        _camera = fl.open_camera()  # auto : webcam USB
    return _camera


def _grab_frame(warmup=5):
    cam = _get_camera()
    frame = None
    for _ in range(warmup):
        ok, f = cam.read()
        if ok:
            frame = f
    return frame


def publish_led(state: str):
    if _mqtt is not None:
        try:
            _mqtt.publish(TOPIC_LED, state, qos=0, retain=False)
        except Exception:
            pass  # LED best-effort


@app.on_event("startup")
def startup():
    global _detector, _recognizer, _known, _mqtt
    _detector = fl.load_detector()
    _recognizer = fl.load_recognizer()
    _known = _load_faces()
    _mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="face-agent")
    try:
        _mqtt.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        _mqtt.loop_start()
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "enrolled": list(_known)}


@app.post("/recognize")
def recognize():
    """Capture une image et dit si la personne est reconnue. Pilote la LED."""
    with _lock:
        frame = _grab_frame()
        if frame is None:
            return {"recognized": False, "reason": "camera", "detail": "Pas d'image de la webcam."}
        face = fl.largest_face(fl.detect_faces(_detector, frame))
        if face is None:
            publish_led("rouge_fixe")
            return {"recognized": False, "reason": "no_face", "score": 0.0}
        feat = fl.embedding(_recognizer, frame, face)
        name, score = fl.best_match(_recognizer, feat, _known)

    if name:
        publish_led("vert_clignotant")
        return {"recognized": True, "name": name, "score": round(score, 3)}
    publish_led("rouge_fixe")
    return {"recognized": False, "reason": "unknown", "score": round(score, 3)}


class LedIn(BaseModel):
    state: str


@app.post("/led")
def led(body: LedIn):
    """Force un état de LED (vert_fixe si mot de passe bon, rouge_clignote si faux, off…)."""
    state = body.state.strip().lower()
    if state not in VALID_STATES:
        return {"ok": False, "detail": f"État inconnu : {state}"}
    publish_led(state)
    return {"ok": True, "state": state}


@app.post("/reload")
def reload_faces():
    """Recharge la base des visages (après un nouvel enrôlement)."""
    global _known
    with _lock:
        _known = _load_faces()
    return {"ok": True, "enrolled": list(_known)}
