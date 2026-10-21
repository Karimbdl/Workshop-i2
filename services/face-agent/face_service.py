"""Service de reconnaissance faciale du back-office (tourne sur le PC Hôte).

Expose une petite API HTTP que la page de login du back-office appelle :
  - GET  /stream    : flux vidéo en direct de la webcam (avec cadre + nom sur le visage).
  - POST /recognize : dit si la personne est reconnue, et pilote la LED.
  - POST /led       : force un état de LED (après la saisie du mot de passe).
  - POST /reload    : recharge la base des visages.

Une seule tâche de fond lit la webcam en continu ; le flux et la reconnaissance
travaillent sur la dernière image. Les commandes LED sont publiées en MQTT.

Lancer : .venv\\Scripts\\python -m uvicorn face_service:app --host 0.0.0.0 --port 8070
"""

import json
import os
import threading
import time

import cv2
import paho.mqtt.client as mqtt
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import face_lib as fl

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_LED = "resilience/backoffice/led"
VALID_STATES = {"off", "eteinte", "vert_clignotant", "vert_fixe", "rouge_fixe", "rouge_clignote"}

app = FastAPI(title="RESILIENCE-ALPHA face-agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_detector = None
_recognizer = None
_known = {}
_mqtt = None

_frame_lock = threading.Lock()
_latest = None          # dernière image de la webcam (BGR)
_running = True


def _load_faces():
    if os.path.exists(fl.FACES_PATH):
        with open(fl.FACES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _capture_loop():
    """Lit la webcam en continu et garde la dernière image."""
    global _latest
    cam = None
    while _running:
        try:
            if cam is None or not cam.isOpened():
                cam = fl.open_camera()  # auto : webcam USB
            ok, frame = cam.read()
            if ok:
                with _frame_lock:
                    _latest = frame
            else:
                time.sleep(0.05)
        except Exception:
            time.sleep(0.5)
    if cam is not None:
        cam.release()


def _get_latest():
    with _frame_lock:
        return None if _latest is None else _latest.copy()


def _annotate(frame):
    """Dessine un cadre + le nom (ou « Inconnu ») sur chaque visage."""
    for fc in fl.detect_faces(_detector, frame):
        feat = fl.embedding(_recognizer, frame, fc)
        name, score = fl.best_match(_recognizer, feat, _known)
        x, y, w, h = map(int, fc[:4])
        if name:
            color, label = (0, 200, 0), f"{name}"
        else:
            color, label = (0, 0, 230), "Inconnu"
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        cv2.putText(frame, label, (x, max(20, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return frame


def publish_led(state: str):
    if _mqtt is not None:
        try:
            _mqtt.publish(TOPIC_LED, state, qos=0, retain=False)
        except Exception:
            pass


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
    threading.Thread(target=_capture_loop, daemon=True).start()


@app.on_event("shutdown")
def shutdown():
    global _running
    _running = False


@app.get("/health")
def health():
    return {"status": "ok", "enrolled": list(_known)}


def _mjpeg():
    while True:
        frame = _get_latest()
        if frame is None:
            time.sleep(0.05)
            continue
        frame = _annotate(frame)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(0.06)  # ~15 images/s


@app.get("/stream")
def stream():
    """Flux vidéo en direct (MJPEG) de la webcam, avec cadre + nom."""
    return StreamingResponse(_mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/snapshot")
def snapshot():
    """Une image instantanée annotée (le site la rafraîchit en boucle = vidéo fiable)."""
    frame = _get_latest()
    if frame is None:
        return Response(status_code=503)
    frame = _annotate(frame)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return Response(status_code=500)
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


class RecognizeIn(BaseModel):
    username: str | None = None


@app.post("/recognize")
def recognize(body: RecognizeIn | None = None):
    """Dit si la personne est reconnue (et correspond à l'identifiant). Pilote la LED.

    Cherche le visage pendant quelques secondes (le temps que la personne regarde la
    caméra) et valide dès qu'il est reconnu.
    """
    username = body.username.strip() if (body and body.username) else None
    expected_known = bool(username) and username in _known

    deadline = time.time() + 3.0
    saw_face = False
    best_name, best_score = None, -1.0

    while time.time() < deadline:
        frame = _get_latest()
        if frame is not None:
            face = fl.largest_face(fl.detect_faces(_detector, frame))
            if face is not None:
                saw_face = True
                feat = fl.embedding(_recognizer, frame, face)
                name, score = fl.best_match(_recognizer, feat, _known)
                if score > best_score:
                    best_name, best_score = name, score
                ok = name is not None and (not expected_known or name == username)
                if ok:
                    publish_led("vert_clignotant")
                    return {"recognized": True, "name": name, "score": round(score, 3)}
        time.sleep(0.1)

    publish_led("rouge_fixe")
    if not saw_face:
        return {"recognized": False, "reason": "no_face", "score": 0.0}
    reason = "mismatch" if (best_name and expected_known and best_name != username) else "unknown"
    return {"recognized": False, "reason": reason, "name": best_name, "score": round(best_score, 3)}


class LedIn(BaseModel):
    state: str


@app.post("/led")
def led(body: LedIn):
    state = body.state.strip().lower()
    if state not in VALID_STATES:
        return {"ok": False, "detail": f"État inconnu : {state}"}
    publish_led(state)
    return {"ok": True, "state": state}


class EnrollIn(BaseModel):
    name: str
    shots: int = 7


@app.post("/enroll")
def enroll(body: EnrollIn):
    """Enrôle un visage depuis le flux en cours (pas de conflit de caméra)."""
    global _known
    name = body.name.strip()
    if not name:
        return {"ok": False, "detail": "Nom vide."}
    feats = []
    tries = 0
    while len(feats) < body.shots and tries < body.shots * 25:
        tries += 1
        frame = _get_latest()
        if frame is not None:
            fc = fl.largest_face(fl.detect_faces(_detector, frame))
            if fc is not None:
                feats.append(fl.embedding(_recognizer, frame, fc).tolist())
        time.sleep(0.1)
    if not feats:
        return {"ok": False, "detail": "Aucun visage détecté. Mets-toi face à la caméra."}
    known = _load_faces()
    known[name] = feats
    with open(fl.FACES_PATH, "w", encoding="utf-8") as f:
        json.dump(known, f)
    _known = known
    return {"ok": True, "name": name, "shots": len(feats), "enrolled": list(known)}


@app.post("/reload")
def reload_faces():
    global _known
    _known = _load_faces()
    return {"ok": True, "enrolled": list(_known)}
