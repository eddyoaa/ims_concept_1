"""Version 2: ganzes Gesicht.

Erweitert den Mouthesizer auf Mimik und Kopfhaltung. MediaPipe liefert 52
"Blendshapes" (Mimik-Werte 0..1) plus die Kopfrotation.

    Kopf nicken (hoch/runter) -> Tonhoehe (Moll-Pentatonik, 2 Oktaven)
    Kopf drehen (links/rechts)-> Panorama
    Kopf neigen               -> Verstimmung (Chorus-Breite)
    Kiefer oeffnen            -> Lautstaerke + Cutoff
    Laecheln                  -> Resonanz + Quinte dazu
    Augenbrauen hoch          -> Vibrato
    Backen aufblasen          -> Verzerrung
    Kussmund                  -> Pulse-Welle (hohler Klang)
    Augen weit auf            -> Delay-Feedback
    Blinzeln (beide Augen)    -> Pluck eine Oktave hoeher

Tasten: c Kalibrierung zuruecksetzen, q beenden.
"""

import math

import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from mouthesizer.common import (AutoRange, Osc, Smooth, base_args, draw_points,
                                expmap, lin, model_path, quantize, run)
from mouthesizer.synth import Synth


NOSE, CHIN = 1, 152
EYE_L, EYE_R = 33, 263
CHEEK_L, CHEEK_R = 234, 454


def head_angles(m):
    """Nick-, Dreh- und Neigewinkel (Grad) aus der 4x4-Transformationsmatrix."""
    r = np.asarray(m)[:3, :3]
    pitch = math.degrees(math.asin(-np.clip(r[1, 2], -1, 1)))
    yaw = math.degrees(math.atan2(r[0, 2], r[2, 2]))
    roll = math.degrees(math.atan2(r[1, 0], r[1, 1]))
    return pitch, yaw, roll


def main():
    args = base_args("Gesichts-Synth: Mimik und Kopfhaltung steuern Klang").parse_args()

    landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=model_path("face")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True))

    synth = None
    if not args.no_audio:
        synth = Synth(voices=2)
        synth.set(delay_time=0.28)
        synth.start(args.audio_device)
    osc = Osc(None if args.no_osc else args.osc, "/face")

    # Nicken/Drehen direkt aus Landmarks, damit die Richtung immer stimmt:
    # Nase relativ zu Augenlinie/Kinn bzw. relativ zu beiden Wangen
    r_pitch = AutoRange(0.24, 0.42)
    r_yaw = AutoRange(0.35, 0.65)
    sm = {}
    blink = {"closed": False}

    def smooth(name, x, a=0.35):
        if name not in sm:
            sm[name] = Smooth(a, x)
        return sm[name](x)

    def process(rgb, frame, ts):
        res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
        if not res.face_landmarks:
            if synth:
                synth.set(master=0.0)
            osc.send({"present": 0})
            return {"kein Gesicht": 0}

        bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
        pitch, yaw, roll = head_angles(res.facial_transformation_matrixes[0])
        lm = res.face_landmarks[0]
        eye_y = (lm[EYE_L].y + lm[EYE_R].y) / 2
        nod_raw = (lm[NOSE].y - eye_y) / max(lm[CHIN].y - eye_y, 1e-3)  # klein = Kopf hoch
        turn_raw = (lm[NOSE].x - lm[CHEEK_L].x) / max(lm[CHEEK_R].x - lm[CHEEK_L].x, 1e-3)

        v = {
            "jaw": smooth("jaw", bs["jawOpen"]),
            "smile": smooth("smile", (bs["mouthSmileLeft"] + bs["mouthSmileRight"]) / 2),
            "brows": smooth("brows", bs["browInnerUp"]),
            "puff": smooth("puff", bs["cheekPuff"]),
            "pucker": smooth("pucker", bs["mouthPucker"]),
            "eyewide": smooth("eyewide", (bs["eyeWideLeft"] + bs["eyeWideRight"]) / 2),
            "nod": smooth("nod", 1.0 - r_pitch(nod_raw), 0.25),
            "turn": smooth("turn", r_yaw(turn_raw), 0.25),
            "tilt": smooth("tilt", lin(abs(roll), 0, 25), 0.25),
        }
        blink_now = (bs["eyeBlinkLeft"] + bs["eyeBlinkRight"]) / 2
        triggered = blink_now > 0.55 and not blink["closed"]
        blink["closed"] = blink_now > 0.35 if blink["closed"] else blink_now > 0.55

        note = quantize(v["nod"], root_midi=45, octaves=2)
        if synth:
            synth.set_voice(0, freq=note, amp=0.6)
            synth.set_voice(1, freq=note * 1.5, amp=0.45 * v["smile"])
            synth.set(
                master=0.15 + 0.65 * v["jaw"],
                cutoff=expmap(0.25 + 0.75 * v["jaw"], 120, 7000),
                q=0.8 + 10.0 * v["smile"],
                vibrato_depth=0.6 * v["brows"],
                drive=1.0 + 6.0 * v["puff"],
                pulse_mix=v["pucker"],
                delay_fb=0.2 + 0.7 * v["eyewide"],
                delay_mix=0.12 + 0.3 * v["eyewide"],
                pan=v["turn"] * 2 - 1,
                detune=0.05 + 0.5 * v["tilt"],
            )
            if triggered:
                synth.pluck(note * 2, amp=0.35)

        osc.send({"present": 1, **v, "blink": float(triggered), "note_hz": note,
                  "pitch_deg": pitch, "yaw_deg": yaw, "roll_deg": roll})

        if not args.headless:
            draw_points(frame, lm[::3], r=1)
        return {
            "Nicken -> Ton": v["nod"], "Drehen -> Pan": v["turn"], "Neigen -> Chorus": v["tilt"],
            "Kiefer -> Lautst.": v["jaw"], "Laecheln -> Reso": v["smile"],
            "Brauen -> Vibrato": v["brows"], "Backen -> Drive": v["puff"],
            "Kussmund -> Pulse": v["pucker"], "Augen weit -> Delay": v["eyewide"],
            "Blinzeln -> Pluck": blink_now,
        }

    def on_key(k):
        if k == "c":
            r_pitch.reset()
            r_yaw.reset()

    try:
        run(args, process, "Gesichts-Synth", on_key)
    finally:
        if synth:
            synth.stop()


if __name__ == "__main__":
    main()
