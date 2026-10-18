"""Gemeinsame Bausteine fuer alle drei Versionen: Kamera, Modelle, OSC, HUD, Mapping."""

from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS = {
    "face": ("face_landmarker.task",
             "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task"),
    "pose": ("pose_landmarker_full.task",
             "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_full/float16/1/pose_landmarker_full.task"),
}


def model_path(kind: str) -> str:
    """Laedt das MediaPipe-Modell beim ersten Start nach models/ herunter."""
    name, url = MODELS[kind]
    path = MODEL_DIR / name
    if not path.exists():
        MODEL_DIR.mkdir(exist_ok=True)
        print(f"Lade Modell {name} ...")
        urllib.request.urlretrieve(url, path)
    return str(path)


# ------------------------------------------------------------------ mapping
def lin(x, lo, hi, out_lo=0.0, out_hi=1.0, clip=True):
    t = (x - lo) / (hi - lo) if hi != lo else 0.0
    if clip:
        t = min(max(t, 0.0), 1.0)
    return out_lo + t * (out_hi - out_lo)


def expmap(t, lo, hi):
    """0..1 -> lo..hi exponentiell (fuer Frequenzen)."""
    t = min(max(t, 0.0), 1.0)
    return lo * (hi / lo) ** t


class Smooth:
    """Exponentielle Glaettung gegen Tracking-Zittern."""

    def __init__(self, alpha=0.35, value=0.0):
        self.alpha = alpha
        self.value = value

    def __call__(self, x):
        self.value += (x - self.value) * self.alpha
        return self.value


class AutoRange:
    """Normiert einen Messwert auf 0..1 und erweitert den Bereich selbst,
    wenn jemand weiter geht als die Startwerte. Taste 'c' setzt zurueck."""

    def __init__(self, lo, hi):
        self.lo0, self.hi0 = lo, hi
        self.reset()

    def reset(self):
        self.lo, self.hi = self.lo0, self.hi0

    def __call__(self, x):
        self.lo = min(self.lo, x)
        self.hi = max(self.hi, x)
        return lin(x, self.lo, self.hi)


SCALES = {
    "minor_pent": [0, 3, 5, 7, 10],
    "major_pent": [0, 2, 4, 7, 9],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "chromatic": list(range(12)),
}


def quantize(t, root_midi=45, octaves=2, scale="minor_pent"):
    """0..1 -> Frequenz einer Note aus der Skala (Standard: A2 Moll-Pentatonik)."""
    steps = SCALES[scale]
    notes = [root_midi + 12 * o + s for o in range(octaves) for s in steps] + [root_midi + 12 * octaves]
    i = int(round(min(max(t, 0.0), 1.0) * (len(notes) - 1)))
    return midi_to_hz(notes[i])


def midi_to_hz(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


# ---------------------------------------------------------------------- OSC
class Osc:
    """Schickt alle Steuerwerte per OSC raus (z.B. an TouchDesigner OSC In CHOP
    oder vvvv). Ist python-osc nicht installiert oder --no-osc gesetzt, passiert nichts."""

    def __init__(self, target: str | None, prefix: str):
        self.client = None
        self.prefix = prefix
        if not target:
            return
        try:
            from pythonosc.udp_client import SimpleUDPClient
        except ImportError:
            print("python-osc fehlt, OSC deaktiviert")
            return
        host, port = target.rsplit(":", 1)
        self.client = SimpleUDPClient(host, int(port))
        print(f"OSC -> {host}:{port}  (Adressen {prefix}/...)")

    def send(self, values: dict):
        if self.client is None:
            return
        for k, v in values.items():
            self.client.send_message(f"{self.prefix}/{k}", float(v))


# ---------------------------------------------------------------------- CLI
def base_args(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--camera", default="0", help="Kamera-Index oder Videodatei (Standard 0)")
    ap.add_argument("--osc", default="127.0.0.1:9000", help="OSC-Ziel host:port")
    ap.add_argument("--no-osc", action="store_true", help="kein OSC senden")
    ap.add_argument("--no-audio", action="store_true",
                    help="keinen eigenen Sound erzeugen, nur OSC (Klang in TD/vvvv)")
    ap.add_argument("--audio-device", default=None, help="sounddevice Ausgabegeraet")
    ap.add_argument("--no-mirror", action="store_true", help="Bild nicht spiegeln")
    ap.add_argument("--headless", action="store_true", help="kein Fenster (z.B. fuer Installation)")
    return ap


# ---------------------------------------------------------------------- HUD
def draw_bars(frame, values: dict, x=10, y=10, w=180):
    """Zeichnet links oben fuer jeden Wert 0..1 einen Balken."""
    for i, (name, v) in enumerate(values.items()):
        yy = y + i * 22
        v = float(min(max(v, 0.0), 1.0))
        cv2.rectangle(frame, (x, yy), (x + w, yy + 16), (40, 40, 40), -1)
        cv2.rectangle(frame, (x, yy), (x + int(w * v), yy + 16), (80, 200, 255), -1)
        cv2.putText(frame, name, (x + w + 8, yy + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1, cv2.LINE_AA)


def draw_points(frame, pts, color=(0, 255, 120), r=1):
    h, w = frame.shape[:2]
    for p in pts:
        cv2.circle(frame, (int(p.x * w), int(p.y * h)), r, color, -1)


# --------------------------------------------------------------------- loop
def run(args, process, title: str, on_key=None):
    """Kamera-Schleife. `process(frame_rgb, frame_bgr, timestamp_ms)` gibt ein
    dict mit Werten 0..1 fuer das HUD zurueck."""
    cam = int(args.camera) if str(args.camera).isdigit() else args.camera
    cap = cv2.VideoCapture(cam)
    if not cap.isOpened():
        raise SystemExit(f"Kamera {args.camera} laesst sich nicht oeffnen")
    t0 = time.monotonic()
    last_ts = -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if not args.no_mirror:
                frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts = int((time.monotonic() - t0) * 1000)
            ts = max(ts, last_ts + 1)  # MediaPipe will streng steigende Zeitstempel
            last_ts = ts
            hud = process(rgb, frame, ts)
            if args.headless:
                continue
            if hud:
                draw_bars(frame, hud)
            cv2.putText(frame, f"{title}  |  q: beenden  c: kalibrieren",
                        (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(title, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if on_key:
                on_key(chr(key) if key < 255 else "")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()


def dist(a, b, aspect=1.0):
    """Abstand zweier Landmarks; aspect = Bildbreite/Bildhoehe, damit x und y
    im gleichen Massstab sind."""
    return float(np.hypot((a.x - b.x) * aspect, a.y - b.y))
