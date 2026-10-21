"""Trouver l'index de la bonne caméra.

Usage : python cameras.py
Ouvre chaque caméra trouvée l'une après l'autre, avec son NUMÉRO affiché à l'écran.
- ESPACE : passer à la caméra suivante
- q : quitter
Note le numéro de la webcam USB, puis lance enroll.py avec --camera <ce numéro>.
"""

import os
import cv2

BACKEND = cv2.CAP_DSHOW if os.name == "nt" else 0


def available(max_index=6):
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, BACKEND)
        ok = cap.isOpened() and cap.read()[0]
        cap.release()
        if ok:
            found.append(i)
    return found


def main():
    idx = available()
    if not idx:
        print("Aucune caméra détectée.")
        return
    print("Caméras trouvées aux index :", idx)

    for i in idx:
        cap = cv2.VideoCapture(i, BACKEND)
        print(f"Affichage caméra {i} — ESPACE = suivante, q = quitter")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.putText(frame, f"Camera index {i}", (15, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 220, 0), 3)
            cv2.imshow("Quelle camera ? (ESPACE=suivante, q=quitter)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):
                break
            if key == ord("q"):
                cap.release()
                cv2.destroyAllWindows()
                return
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
