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
_latest_ts = 0.0        # instant de la dernière image fraîche
_running = True
_cam = None             # webcam ouverte (partagée avec le chien de garde)
_force_reset = False    # demandé par le chien de garde si la webcam ne répond plus

# Chien de garde caméra. La webcam est rouverte automatiquement dans trois cas :
#   - images noires d'affilée (webcam happée par un autre programme, veille…) ;
#   - plus aucune image (lecture en échec, ou lecture bloquée dans le pilote) ;
#   - image figée : la webcam renvoie toujours exactement la même image.
BLACK_MEAN = 6.0                # seuil de luminosité moyenne (0 = noir total)
BLACK_FRAMES_BEFORE_RESET = 25  # ~1,5 s d'images noires
FAILED_READS_BEFORE_RESET = 40  # ~2 s de lectures en échec
FROZEN_SECONDS = 3.0            # image identique pendant 3 s = figée
STALE_SECONDS = 3.0             # au-delà, l'image n'est plus utilisée (vidéo, reconnaissance)
WATCHDOG_SECONDS = 4.0          # lecture bloquée au-delà : on force la réouverture


def _load_faces():
    if os.path.exists(fl.FACES_PATH):
        with open(fl.FACES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _reopen(cam, raison=""):
    """Referme proprement la webcam et la rouvre."""
    global _cam
    print(f"[camera] réouverture de la webcam ({raison})", flush=True)
    try:
        if cam is not None:
            cam.release()
    except Exception:
        pass
    time.sleep(0.5)
    _cam = fl.open_camera()
    return _cam


def _signature(frame):
    """Empreinte légère d'une image, pour repérer une image figée."""
    return hash(frame[::32, ::32].tobytes())


def _capture_loop():
    """Lit la webcam en continu et garde la dernière image fraîche."""
    global _latest, _latest_ts, _cam, _force_reset
    cam = None
    black_streak = failed = 0
    last_sig, same_since = None, time.time()
    while _running:
        try:
            if cam is None or not cam.isOpened() or _force_reset:
                cam = _reopen(cam, "demandée par le chien de garde") if _force_reset else fl.open_camera()
                _cam, _force_reset = cam, False
                black_streak = failed = 0
                last_sig, same_since = None, time.time()
            ok, frame = cam.read()
            if not ok or frame is None:
                failed += 1
                if failed >= FAILED_READS_BEFORE_RESET:
                    cam = _reopen(cam, "plus d'image")
                    failed = 0
                time.sleep(0.05)
                continue
            failed = 0
            if float(frame.mean()) < BLACK_MEAN:
                black_streak += 1
                if black_streak >= BLACK_FRAMES_BEFORE_RESET:
                    cam = _reopen(cam, "images noires")
                    black_streak = 0
                continue
            black_streak = 0
            sig = _signature(frame)
            now = time.time()
            if sig != last_sig:
                last_sig, same_since = sig, now
            elif now - same_since > FROZEN_SECONDS:
                cam = _reopen(cam, "image figée")
                last_sig, same_since = None, time.time()
                continue
            with _frame_lock:
                _latest, _latest_ts = frame, now
        except Exception as exc:
            try:
                cam = _reopen(cam, f"erreur : {exc}")
            except Exception:
                cam = None
            black_streak = failed = 0
            time.sleep(1.0)
    if cam is not None:
        cam.release()


def _watchdog_loop():
    """Signale à la boucle de capture de rouvrir la webcam si elle ne fournit plus d'image.

    IMPORTANT : on ne touche JAMAIS à la webcam depuis ce fil. Une VideoCapture
    d'OpenCV n'est pas « thread-safe » : la fermer ici pendant que la boucle lit
    provoque un plantage natif (segfault). On se contente de lever un drapeau, et
    c'est la boucle de capture, elle seule, qui ferme et rouvre la webcam.
    """
    global _force_reset
    while _running:
        time.sleep(1.0)
        if _latest_ts and time.time() - _latest_ts > WATCHDOG_SECONDS and not _force_reset:
            print("[camera] aucune image depuis plusieurs secondes : réouverture demandée", flush=True)
            _force_reset = True


def camera_age():
    return None if not _latest_ts else round(time.time() - _latest_ts, 1)


def _get_latest():
    """Dernière image, seulement si elle est fraîche (sinon None : pas de reconnaissance sur une image périmée)."""
    with _frame_lock:
        if _latest is None or time.time() - _latest_ts > STALE_SECONDS:
            return None
        return _latest.copy()


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
    threading.Thread(target=_watchdog_loop, daemon=True).start()


@app.on_event("shutdown")
def shutdown():
    global _running
    _running = False


@app.get("/health")
def health():
    age = camera_age()
    return {"status": "ok", "enrolled": list(_known),
            "camera_ok": age is not None and age <= STALE_SECONDS, "camera_age_s": age}


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


@app.get("/faces")
def list_faces():
    """Liste des visages enrôlés (sans les données biométriques)."""
    return {"enrolled": sorted(_known), "count": len(_known)}


@app.delete("/faces/{name}")
def delete_face(name: str):
    """Retire un visage enrôlé."""
    global _known
    known = _load_faces()
    if name not in known:
        return {"ok": False, "detail": f"Visage « {name} » introuvable."}
    del known[name]
    with open(fl.FACES_PATH, "w", encoding="utf-8") as f:
        json.dump(known, f)
    _known = known
    return {"ok": True, "enrolled": sorted(known)}


@app.post("/reload")
def reload_faces():
    global _known
    _known = _load_faces()
    return {"ok": True, "enrolled": list(_known)}
