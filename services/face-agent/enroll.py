"""Enrôler un visage : capturer quelques photos de référence depuis la webcam.

Usage : python enroll.py --name karim
Puis regarde la caméra, bouge un peu la tête ; appuie sur ESPACE pour capturer,
ou laisse faire la capture automatique. 'q' pour quitter.
"""

import argparse
import json
import os

import cv2

import face_lib as fl

SHOTS = 7  # nombre d'empreintes gardées par personne


def load_faces():
    if os.path.exists(fl.FACES_PATH):
        with open(fl.FACES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_faces(faces):
    with open(fl.FACES_PATH, "w", encoding="utf-8") as f:
        json.dump(faces, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="nom de la personne à enrôler")
    ap.add_argument("--camera", type=int, default=None, help="index de la webcam (auto = USB)")
    args = ap.parse_args()

    detector = fl.load_detector()
    recognizer = fl.load_recognizer()
    cap = fl.open_camera(args.camera)

    captured = []
    print(f"Enrôlement de « {args.name} ». Regarde la caméra. ESPACE = capturer, q = fin.")

    while len(captured) < SHOTS:
        ok, frame = cap.read()
        if not ok:
            continue
        faces = fl.detect_faces(detector, frame)
        face = fl.largest_face(faces)

        view = frame.copy()
        if face is not None:
            x, y, w, h = map(int, face[:4])
            cv2.rectangle(view, (x, y), (x + w, y + h), (0, 200, 0), 2)
        cv2.putText(view, f"{args.name} : {len(captured)}/{SHOTS}  (ESPACE)",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
        cv2.imshow("Enrolement", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord(" ") and face is not None:
            captured.append(fl.embedding(recognizer, frame, face).tolist())
            print(f"  capturé {len(captured)}/{SHOTS}")

    cap.release()
    cv2.destroyAllWindows()

    if not captured:
        print("Aucune capture, rien d'enregistré.")
        return

    faces = load_faces()
    faces[args.name] = captured
    save_faces(faces)
    print(f"Enregistré : {args.name} ({len(captured)} empreintes) dans {fl.FACES_PATH}")


if __name__ == "__main__":
    main()
