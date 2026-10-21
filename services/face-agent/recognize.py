"""Reconnaissance en direct : la webcam affiche qui elle reconnaît.

Usage : python recognize.py
Un cadre VERT + le nom si la personne est reconnue, ROUGE + « Inconnu » sinon.
'q' pour quitter.
"""

import argparse
import json
import os

import cv2

import face_lib as fl


def load_faces():
    if not os.path.exists(fl.FACES_PATH):
        raise FileNotFoundError("Aucun visage enrôlé. Lance d'abord : python enroll.py --name <toi>")
    with open(fl.FACES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=None, help="index de la webcam (auto = USB)")
    args = ap.parse_args()

    known = load_faces()
    print(f"Visages connus : {', '.join(known) or 'aucun'}")

    detector = fl.load_detector()
    recognizer = fl.load_recognizer()
    cap = fl.open_camera(args.camera)

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        for face in fl.detect_faces(detector, frame):
            feat = fl.embedding(recognizer, frame, face)
            name, score = fl.best_match(recognizer, feat, known)
            x, y, w, h = map(int, face[:4])
            if name:
                color, label = (0, 200, 0), f"{name} ({score:.2f})"
            else:
                color, label = (0, 0, 230), f"Inconnu ({score:.2f})"
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, label, (x, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.imshow("Reconnaissance (q = quitter)", frame)
        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
