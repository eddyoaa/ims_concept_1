"""Klang zum Ball-Tracking: pro Ball zwei Toene, plus Filter und Lautstaerke.

    Ball fliegt nach rechts (x wird groesser)  -> Ball 1: G4 (392 Hz), Ball 2: D5 (587 Hz)
    Ball fliegt nach links  (x wird kleiner)   -> Ball 1: A4 (440 Hz), Ball 2: E5 (659 Hz)
    Geschwindigkeit                            -> Lautstaerke (Ball still = leise)
    Hoehe im Bild (y)                          -> Tiefpass-Filter (oben hell, unten dumpf)

Jeder Ball hat eine eigene Stimme (ToneSynth). Der Mixer addiert alle Stimmen
in einen gemeinsamen Audio-Stream.

Klangquelle pro Stimme ist eine einzelne Saegezahnwelle (ein Ton mit Obertoenen, damit
der Filter etwas zum Formen hat). Kein Gleiten zwischen den Toenen, kein Hall,
keine Zusatztoene. Der Ton wechselt sofort; nur Lautstaerke und Filter werden
ein paar Millisekunden geglaettet, damit nichts knackt.
"""

from __future__ import annotations

import threading

import numpy as np
from scipy.signal import lfilter

NOTE_RIGHT = ("G", 392.00)   # G4
NOTE_LEFT = ("A", 440.00)    # A4

# (rechts, links) pro Ball
NOTE_PAIRS = [
    (NOTE_RIGHT, NOTE_LEFT),               # Ball 1: G4 / A4
    (("D", 587.33), ("E", 659.25)),        # Ball 2: D5 / E5
]


def _polyblep(t, dt):
    """Glaettet den Sprung der Saegezahnwelle (weniger Aliasing/Zischen)."""
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt
    out[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt
    out[m] = x * x + x + x + 1.0
    return out


def _lowpass(cutoff, sr, q=0.707):
    """Biquad-Tiefpass (RBJ). q=0.707: keine Resonanzspitze, also kein Pfeifen."""
    cutoff = float(np.clip(cutoff, 20.0, sr * 0.45))
    w0 = 2.0 * np.pi * cutoff / sr
    alpha = np.sin(w0) / (2.0 * q)
    cw = np.cos(w0)
    b = np.array([(1 - cw) / 2, 1 - cw, (1 - cw) / 2])
    a = np.array([1 + alpha, -2 * cw, 1 - alpha])
    return b / a[0], a / a[0]


class ToneSynth:
    """Ein Oszillator -> Tiefpass -> Lautstaerke. Thread-sicher steuerbar."""

    def __init__(self, sr=48000, block=256, gain=0.35):
        self.sr, self.block, self.gain = sr, block, gain
        self._lock = threading.Lock()
        self.freq = NOTE_RIGHT[1]
        self.amp_t = 0.0
        self.amp_c = 0.0
        self.cut_t = 1000.0
        self.cut_c = 1000.0
        self._phase = 0.0
        self._zi = np.zeros(2)
        self._stream = None

    def set(self, freq=None, volume=None, cutoff=None):
        with self._lock:
            if freq is not None:
                self.freq = float(freq)
            if volume is not None:
                self.amp_t = float(np.clip(volume, 0.0, 1.0))
            if cutoff is not None:
                self.cut_t = float(cutoff)

    def render(self, frames):
        sr = self.sr
        with self._lock:
            freq, amp_t, cut_t = self.freq, self.amp_t, self.cut_t
        # ~15 ms Glaettung fuer Lautstaerke und Filter
        a = 1.0 - np.exp(-frames / (0.015 * sr))
        amp0 = self.amp_c
        self.amp_c += (amp_t - self.amp_c) * a
        self.cut_c = float(np.exp(np.log(self.cut_c) + (np.log(cut_t) - np.log(self.cut_c)) * a))

        dt = freq / sr
        ph = (self._phase + dt * np.arange(1, frames + 1)) % 1.0
        self._phase = float(ph[-1])
        saw = 2.0 * ph - 1.0 - _polyblep(ph, dt)

        b, a_ = _lowpass(self.cut_c, sr)
        y, self._zi = lfilter(b, a_, saw, zi=self._zi)
        y *= np.linspace(amp0, self.amp_c, frames, endpoint=False) * self.gain
        y = np.clip(y, -1.0, 1.0).astype(np.float32)
        return np.stack([y, y], axis=1)

    def start(self, device=None):
        import sounddevice as sd

        def cb(outdata, frames, time_info, status):
            outdata[:] = self.render(frames)

        self._stream = sd.OutputStream(samplerate=self.sr, blocksize=self.block, channels=2,
                                       dtype="float32", callback=cb, device=device)
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class Mixer:
    """Addiert mehrere Stimmen in einen Audio-Stream (oder rendert offline)."""

    def __init__(self, synths, sr=48000, block=256):
        self.synths, self.sr, self.block = synths, sr, block
        self._stream = None

    def render(self, frames):
        out = sum(s.render(frames) for s in self.synths)
        return np.clip(out, -1.0, 1.0).astype(np.float32)

    def start(self, device=None):
        import sounddevice as sd

        def cb(outdata, frames, time_info, status):
            outdata[:] = self.render(frames)

        self._stream = sd.OutputStream(samplerate=self.sr, blocksize=self.block, channels=2,
                                       dtype="float32", callback=cb, device=device)
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class BallSound:
    """Uebersetzt Ball-Position und -Geschwindigkeit in Ton, Lautstaerke, Filter."""

    def __init__(self, width, height, max_speed=1500.0, min_speed=40.0, dir_threshold=60.0,
                 cutoff_low=150.0, cutoff_high=8000.0, notes=(NOTE_RIGHT, NOTE_LEFT), gain=0.35):
        self.w, self.h = width, height
        self.max_speed = max_speed        # px/s, ab hier volle Lautstaerke
        self.min_speed = min_speed        # px/s, darunter still
        self.dir_threshold = dir_threshold  # px/s, erst ab hier zaehlt eine Richtung
        self.cutoff_low, self.cutoff_high = cutoff_low, cutoff_high
        self.note_right, self.note_left = notes
        self.synth = ToneSynth(gain=gain)
        self.direction = None             # "right" / "left"
        self.info = {}

    def update(self, pos, vx, vy, vz=0.0):
        """pos=None: kein Ball -> Stille. vz: Tiefen-Geschwindigkeit (zweite Kamera), zaehlt
        bei der Lautstaerke mit. Gibt die aktuellen Werte fuers HUD zurueck."""
        if pos is None:
            self.synth.set(volume=0.0)
            self.direction = None
            self.info = {"note": "-", "direction": None, "volume": 0.0,
                         "cutoff": self.synth.cut_t, "speed": 0.0}
            return self.info

        x, y = pos
        # Richtung mit Schwelle: kleines Zittern um 0 wechselt den Ton nicht
        if vx > self.dir_threshold:
            self.direction = "right"
        elif vx < -self.dir_threshold:
            self.direction = "left"

        speed = float(np.sqrt(vx * vx + vy * vy + vz * vz))
        t = (speed - self.min_speed) / (self.max_speed - self.min_speed)
        volume = float(np.clip(t, 0.0, 1.0)) if self.direction else 0.0

        # oben (y=0) hell, unten (y=h) dumpf, exponentiell wie das Ohr hoert
        ty = float(np.clip(1.0 - y / self.h, 0.0, 1.0))
        cutoff = self.cutoff_low * (self.cutoff_high / self.cutoff_low) ** ty

        name, freq = self.note_right if self.direction != "left" else self.note_left
        self.synth.set(freq=freq, volume=volume, cutoff=cutoff)
        self.info = {"note": name if self.direction else "-", "direction": self.direction,
                     "volume": volume,
                     "cutoff": cutoff, "speed": speed}
        return self.info
