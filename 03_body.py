"""Version 3: ganzer Koerper.

Der Mouthesizer-Gedanke (Koerperform -> Filter/Synth) auf den ganzen Koerper
uebertragen, mit einer Prise "Very Nervous System" (Rokeby): Bewegung macht
Klang, Stillstand ist Stille.

    Linke Hand Hoehe          -> Ton Stimme 1 (Moll-Pentatonik)
    Rechte Hand Hoehe         -> Ton Stimme 2
    Abstand der Haende        -> Cutoff (Arme auf = hell)
    Bewegungsenergie          -> Lautstaerke (stillstehen = leise)
    Position im Raum (links/rechts) -> Panorama
    In die Hocke gehen        -> Sub-Bass + Verzerrung
    Beide Haende ueber Kopf   -> grosser Delay-Raum
    Schneller Handschlag      -> Pluck

Tasten: c Kalibrierung zuruecksetzen, q beenden.
"""

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from mouthesizer.common import (AutoRange, Osc, Smooth, base_args, dist, expmap,
                                lin, model_path, quantize, run)
from mouthesizer.synth import Synth

NOSE = 0
SH_L, SH_R = 11, 12
EL_L, EL_R = 13, 14
WR_L, WR_R = 15, 16
HIP_L, HIP_R = 23, 24
KN_L, KN_R = 25, 26
AN_L, AN_R = 27, 28
SKELETON = [(SH_L, SH_R), (SH_L, EL_L), (EL_L, WR_L), (SH_R, EL_R), (EL_R, WR_R),
            (SH_L, HIP_L), (SH_R, HIP_R), (HIP_L, HIP_R), (HIP_L, KN_L), (KN_L, AN_L),
            (HIP_R, KN_R), (KN_R, AN_R)]


def main():
    args = base_args("Koerper-Synth: Bewegung und Haltung steuern Klang").parse_args()

    landmarker = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=model_path("pose")),
        running_mode=vision.RunningMode.VIDEO, num_poses=1))

    synth = None
    if not args.no_audio:
        synth = Synth(voices=2)
        synth.set(delay_time=0.4, sub=0.2)
        synth.start(args.audio_device)
    osc = Osc(None if args.no_osc else args.osc, "/body")

    r_spread = AutoRange(0.3, 3.5)
    r_crouch = AutoRange(0.2, 0.8)
    sm = {}
    state = {"prev": None, "prev_ts": None, "env": 0.0, "hit": [False, False]}

    def smooth(name, x, a=0.35):
        if name not in sm:
            sm[name] = Smooth(a, x)
        return sm[name](x)

    def process(rgb, frame, ts):
        res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
        if not res.pose_landmarks:
            state["prev"] = None
            if synth:
                synth.set(master=0.0)
            osc.send({"present": 0})
            return {"keine Person": 0}
        lm = res.pose_landmarks[0]
        h, w = frame.shape[:2]
        aspect = w / h
        pts = np.array([(p.x * aspect, p.y) for p in lm])

        shoulder_y = (lm[SH_L].y + lm[SH_R].y) / 2
        hip_y = (lm[HIP_L].y + lm[HIP_R].y) / 2
        torso = max(hip_y - shoulder_y, 0.05)
        shoulder_w = max(dist(lm[SH_L], lm[SH_R], aspect), 0.03)

        # Handhoehe: 0 = Huefte, 1 = eine Rumpflaenge ueber den Schultern
        def hand_height(i):
            return lin(hip_y - lm[i].y, 0.0, 2.0 * torso)

        left = smooth("left", hand_height(WR_L), 0.3)
        right = smooth("right", hand_height(WR_R), 0.3)
        spread = smooth("spread", r_spread(dist(lm[WR_L], lm[WR_R], aspect) / shoulder_w))
        center = smooth("center", lin((lm[HIP_L].x + lm[HIP_R].x) / 2, 0.15, 0.85), 0.2)
        # Hocke: Huefte nah an den Knoecheln (relativ zur Rumpflaenge)
        ankle_y = (lm[AN_L].y + lm[AN_R].y) / 2
        crouch = smooth("crouch", 1.0 - r_crouch(lin(ankle_y - hip_y, 0, 2.0 * torso)), 0.2)
        above = float(lm[WR_L].y < lm[NOSE].y and lm[WR_R].y < lm[NOSE].y)
        space = smooth("space", above, 0.08)

        # Bewegungsenergie = mittlere Geschwindigkeit aller Punkte (Rumpflaengen/s)
        energy_raw, hits = 0.0, [False, False]
        if state["prev"] is not None:
            dt = max((ts - state["prev_ts"]) / 1000.0, 1e-3)
            vel = np.linalg.norm(pts - state["prev"], axis=1) / torso / dt
            energy_raw = float(np.mean(vel))
            for k, i in enumerate((WR_L, WR_R)):
                fast = vel[i] > 8.0
                hits[k] = fast and not state["hit"][k]
                state["hit"][k] = vel[i] > 5.0 if state["hit"][k] else fast
        state["prev"], state["prev_ts"] = pts, ts
        # Huellkurve: schnell rauf, langsam runter
        state["env"] = max(lin(energy_raw, 0.05, 2.5), state["env"] * 0.93)
        energy = state["env"]

        n1 = quantize(left, root_midi=45, octaves=2)
        n2 = quantize(right, root_midi=52, octaves=2)
        if synth:
            synth.set_voice(0, freq=n1, amp=0.5)
            synth.set_voice(1, freq=n2, amp=0.5)
            synth.set(
                master=0.85 * energy,
                cutoff=expmap(spread, 150, 8000),
                q=2.0 + 6.0 * (1 - spread),
                pan=center * 2 - 1,
                sub=0.2 + 0.8 * crouch,
                drive=1.0 + 5.0 * crouch,
                delay_fb=0.3 + 0.6 * space,
                delay_mix=0.15 + 0.45 * space,
            )
            for k, hit in enumerate(hits):
                if hit:
                    synth.pluck((n1, n2)[k] * 2, amp=0.4, decay=0.35)

        v = {"left": left, "right": right, "spread": spread, "energy": energy,
             "center": center, "crouch": crouch, "space": space}
        osc.send({"present": 1, **v, "hit_l": float(hits[0]), "hit_r": float(hits[1]),
                  "note1_hz": n1, "note2_hz": n2})

        if not args.headless:
            for a, b in SKELETON:
                cv2.line(frame, (int(lm[a].x * w), int(lm[a].y * h)),
                         (int(lm[b].x * w), int(lm[b].y * h)), (0, 255, 120), 2, cv2.LINE_AA)
            for i in (WR_L, WR_R):
                cv2.circle(frame, (int(lm[i].x * w), int(lm[i].y * h)), 8, (80, 200, 255), -1)
        return {"Hand L -> Ton 1": left, "Hand R -> Ton 2": right,
                "Abstand -> Cutoff": spread, "Bewegung -> Lautst.": energy,
                "Position -> Pan": center, "Hocke -> Bass": crouch,
                "Haende hoch -> Raum": space}

    def on_key(k):
        if k == "c":
            for r in (r_spread, r_crouch):
                r.reset()

    try:
        run(args, process, "Koerper-Synth", on_key)
    finally:
        if synth:
            synth.stop()


if __name__ == "__main__":
    main()
