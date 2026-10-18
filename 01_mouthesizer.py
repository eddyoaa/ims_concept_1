"""Version 1: Mouthesizer (nach Michael Lyons, 2003).

Wie im Original wird nur die Mundform gemessen:
    Mundhoehe   -> Cutoff des resonanten Tiefpass ("Wah")
    Mundbreite  -> Resonanz + Verzerrung
    Mundflaeche -> Lautstaerke (Mund zu = still)

Lyons hat eine Kamera am Kopf montiert, die nur den Mund sieht. Hier sieht die
Webcam das ganze Gesicht, wir schneiden den Mund aber aus und zeigen ihn gross
rechts oben, so wie das Original-Kamerabild.

Tasten: 1-8 Grundton waehlen, c Kalibrierung zuruecksetzen, q beenden.
"""

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from mouthesizer.common import (AutoRange, Osc, Smooth, base_args, dist, expmap,
                                lin, midi_to_hz, model_path, run)
from mouthesizer.synth import Synth

# Face-Mesh-Indizes
UPPER, LOWER = 13, 14          # Innenlippe oben/unten
LEFT, RIGHT = 61, 291          # Mundwinkel
EYE_L, EYE_R = 33, 263         # aeussere Augenwinkel (Massstab)
INNER_LIP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415,
             308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
ROOTS = [45, 47, 48, 50, 52, 53, 55, 57]  # A2 .. A3 (Tasten 1-8)


def polygon_area(pts):
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def main():
    args = base_args("Mouthesizer: Mundform steuert einen Synthesizer").parse_args()

    landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=model_path("face")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1))

    synth = None
    if not args.no_audio:
        synth = Synth(voices=2)
        synth.set(sub=0.4, delay_mix=0.1)
        synth.set_voice(0, freq=midi_to_hz(45), amp=0.6)
        synth.set_voice(1, freq=midi_to_hz(52), amp=0.3)  # Quinte
        synth.start(args.audio_device)
    osc = Osc(None if args.no_osc else args.osc, "/mouth")

    # Startbereiche (relativ zum Augenabstand), erweitern sich automatisch
    r_height = AutoRange(0.02, 0.45)
    r_width = AutoRange(0.6, 0.9)
    r_area = AutoRange(0.002, 0.2)
    s = {k: Smooth(0.4) for k in ("height", "width", "area")}

    def process(rgb, frame, ts):
        res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
        if not res.face_landmarks:
            if synth:
                synth.set(master=0.0)
            osc.send({"present": 0})
            return {"kein Gesicht": 0}
        lm = res.face_landmarks[0]
        h, w = frame.shape[:2]
        aspect = w / h
        scale = dist(lm[EYE_L], lm[EYE_R], aspect)

        height = s["height"](r_height(dist(lm[UPPER], lm[LOWER], aspect) / scale))
        width = s["width"](r_width(dist(lm[LEFT], lm[RIGHT], aspect) / scale))
        area_raw = polygon_area([(lm[i].x * aspect, lm[i].y) for i in INNER_LIP]) / scale ** 2
        area = s["area"](r_area(area_raw))

        if synth:
            synth.set(
                cutoff=expmap(height, 150, 6000),
                q=lin(width, 0, 1, 0.8, 14.0),
                drive=lin(width, 0, 1, 1.0, 5.0),
                master=lin(area, 0.05, 0.6, 0.0, 0.8),
            )
        osc.send({"present": 1, "height": height, "width": width, "area": area})

        if not args.headless:
            pts = np.array([(lm[i].x * w, lm[i].y * h) for i in INNER_LIP], np.int32)
            cv2.polylines(frame, [pts], True, (0, 255, 120), 1, cv2.LINE_AA)
            # Mund-Ausschnitt vergroessert (wie Lyons' Kopfkamera)
            cx, cy = int((lm[LEFT].x + lm[RIGHT].x) / 2 * w), int((lm[UPPER].y + lm[LOWER].y) / 2 * h)
            r = int(scale * w * 0.55)
            x0, y0 = max(cx - r, 0), max(cy - r // 2, 0)
            crop = frame[y0:cy + r // 2, x0:cx + r].copy()
            if crop.size:
                crop = cv2.resize(crop, (240, 120))
                frame[10:130, w - 250:w - 10] = crop
                cv2.rectangle(frame, (w - 250, 10), (w - 10, 130), (255, 255, 255), 1)
        return {"Hoehe -> Cutoff": height, "Breite -> Resonanz": width, "Flaeche -> Lautst.": area}

    def on_key(k):
        if k == "c":
            for r in (r_height, r_width, r_area):
                r.reset()
        elif synth and k in "12345678" and k:
            root = ROOTS[int(k) - 1]
            synth.set_voice(0, freq=midi_to_hz(root))
            synth.set_voice(1, freq=midi_to_hz(root + 7))

    try:
        run(args, process, "Mouthesizer", on_key)
    finally:
        if synth:
            synth.stop()


if __name__ == "__main__":
    main()
