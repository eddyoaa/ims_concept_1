"""Kleiner Echtzeit-Synthesizer in numpy.

Signalweg (wie beim Mouthesizer: Quelle -> resonanter Tiefpass -> Verzerrung):

    N Oszillatoren (Saw/Pulse, polyBLEP) + Sub
        -> resonanter Tiefpass (Biquad, Cutoff/Q pro Block)
        -> Drive (tanh)
        -> Plucks (kurze Toene, z.B. beim Blinzeln)
        -> Feedback-Delay
        -> Panorama -> Stereo-Ausgang

Alle Parameter werden ueber `set()` als Zielwerte gesetzt und pro Audioblock
weich angeglichen, damit nichts knackt, wenn das Tracking springt.
"""

from __future__ import annotations

import threading

import numpy as np
from scipy.signal import lfilter


def _polyblep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """Korrektur gegen Aliasing an der Sprungstelle der Saegezahnwelle."""
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt[m]
    out[m] = x * x + x + x + 1.0
    return out


def _lowpass_coeffs(cutoff: float, q: float, sr: int):
    """RBJ-Cookbook Tiefpass."""
    cutoff = float(np.clip(cutoff, 20.0, sr * 0.45))
    q = float(max(q, 0.3))
    w0 = 2.0 * np.pi * cutoff / sr
    alpha = np.sin(w0) / (2.0 * q)
    cw = np.cos(w0)
    b = np.array([(1 - cw) / 2, 1 - cw, (1 - cw) / 2])
    a = np.array([1 + alpha, -2 * cw, 1 - alpha])
    return b / a[0], a / a[0]


class Synth:
    DEFAULTS = dict(
        cutoff=800.0,      # Hz
        q=1.0,             # Resonanz
        drive=1.0,         # 1 = clean, >1 = Verzerrung
        master=0.0,        # Gesamtlautstaerke 0..1
        pan=0.0,           # -1 links .. 1 rechts
        vibrato_depth=0.0, # Halbtoene
        vibrato_rate=5.0,  # Hz
        detune=0.08,       # Halbtoene zwischen den zwei Saws pro Stimme
        pulse_mix=0.0,     # 0 = Saw, 1 = Pulse
        sub=0.3,           # Sub-Oszillator (eine Oktave tiefer)
        delay_mix=0.15,
        delay_fb=0.35,
        delay_time=0.33,   # Sekunden
    )

    def __init__(self, voices: int = 1, sr: int = 48000, block: int = 256,
                 base_freq: float = 110.0):
        self.sr = sr
        self.block = block
        self.n = voices
        self._lock = threading.Lock()

        self.target = dict(self.DEFAULTS)
        self.cur = dict(self.DEFAULTS)
        self.freq_t = np.full(voices, base_freq, dtype=float)
        self.freq_c = self.freq_t.copy()
        self.amp_t = np.ones(voices, dtype=float) / voices
        self.amp_c = self.amp_t.copy()

        self._phase = np.zeros((voices, 3))  # saw A, saw B, sub
        self._lfo = 0.0
        self._zi = np.zeros(2)
        self._dbuf = np.zeros(sr * 2)
        self._didx = 0
        self._plucks: list[list[float]] = []  # [freq, phase, amp, decay]
        self._stream = None

    # ---------------------------------------------------------------- control
    def set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                if k not in self.target:
                    raise KeyError(k)
                self.target[k] = float(v)

    def set_voice(self, i: int, freq: float | None = None, amp: float | None = None):
        with self._lock:
            if freq is not None:
                self.freq_t[i] = max(float(freq), 10.0)
            if amp is not None:
                self.amp_t[i] = max(float(amp), 0.0)

    def pluck(self, freq: float, amp: float = 0.4, decay: float = 0.25):
        """Kurzer abklingender Ton (Trigger, z.B. Blinzeln/Klatschen)."""
        with self._lock:
            self._plucks.append([float(freq), 0.0, float(amp), float(decay)])

    # ------------------------------------------------------------------ audio
    def _smooth(self, frames: int):
        # ca. 30 ms Glaettung, unabhaengig von der Blockgroesse
        a = 1.0 - np.exp(-frames / (0.03 * self.sr))
        with self._lock:
            for k in self.cur:
                if k == "delay_time":  # Delayzeit springt nicht, sonst Pitch-Artefakte
                    self.cur[k] += (self.target[k] - self.cur[k]) * a * 0.2
                else:
                    self.cur[k] += (self.target[k] - self.cur[k]) * a
            f0 = self.freq_c.copy()
            a0 = self.amp_c.copy()
            # Tonhoehe logarithmisch glaetten (Portamento)
            self.freq_c = np.exp(np.log(self.freq_c) + (np.log(self.freq_t) - np.log(self.freq_c)) * a)
            self.amp_c += (self.amp_t - self.amp_c) * a
            plucks = self._plucks
            self._plucks = []
        return f0, a0, plucks

    def render(self, frames: int) -> np.ndarray:
        sr = self.sr
        f0, a0, new_plucks = self._smooth(frames)
        p = self.cur
        ramp = np.linspace(0.0, 1.0, frames, endpoint=False)

        # LFO fuer Vibrato
        lfo_ph = self._lfo + 2 * np.pi * p["vibrato_rate"] * np.arange(frames) / sr
        self._lfo = float(lfo_ph[-1] + 2 * np.pi * p["vibrato_rate"] / sr) % (2 * np.pi)
        vib = 2.0 ** (p["vibrato_depth"] * np.sin(lfo_ph) / 12.0)

        mix = np.zeros(frames)
        det = 2.0 ** (p["detune"] / 12.0)
        for v in range(self.n):
            f = (f0[v] + (self.freq_c[v] - f0[v]) * ramp) * vib
            amp = a0[v] + (self.amp_c[v] - a0[v]) * ramp
            voice = np.zeros(frames)
            for j, mult in enumerate((1.0, det, 0.5)):
                dt = f * mult / sr
                ph = (self._phase[v, j] + np.cumsum(dt)) % 1.0
                self._phase[v, j] = ph[-1]
                saw = 2.0 * ph - 1.0 - _polyblep(ph, dt)
                if j < 2:
                    # Pulse = Differenz zweier verschobener Saws
                    ph2 = (ph + 0.5) % 1.0
                    saw2 = 2.0 * ph2 - 1.0 - _polyblep(ph2, dt)
                    pulse = 0.5 * (saw - saw2)
                    voice += 0.5 * ((1 - p["pulse_mix"]) * saw + p["pulse_mix"] * pulse)
                else:
                    voice += p["sub"] * np.sin(2 * np.pi * ph)
            mix += voice * amp

        b, a = _lowpass_coeffs(p["cutoff"], p["q"], sr)
        y, self._zi = lfilter(b, a, mix, zi=self._zi)
        drive = max(p["drive"], 0.1)
        y = np.tanh(y * drive) / np.tanh(drive)

        # Plucks
        with self._lock:
            self._plucks.extend(new_plucks)
            alive = []
            t = np.arange(frames) / sr
            for pl in self._plucks:
                freq, ph, amp, decay = pl
                env = amp * np.exp(-t / decay)
                phases = ph + 2 * np.pi * freq * t
                y += env * (np.sin(phases) + 0.3 * np.sin(2 * phases))
                pl[1] = float(phases[-1] + 2 * np.pi * freq / sr)
                pl[2] = float(env[-1] * np.exp(-1.0 / (sr * decay)))
                if pl[2] > 1e-3:
                    alive.append(pl)
            self._plucks = alive

        # Delay (Delayzeit immer > Blocklaenge, daher vektorisierbar)
        n = len(self._dbuf)
        d = int(np.clip(p["delay_time"], frames / sr + 0.01, 1.9) * sr)
        idx = (self._didx + np.arange(frames)) % n
        delayed = self._dbuf[(idx - d) % n]
        self._dbuf[idx] = y + delayed * np.clip(p["delay_fb"], 0.0, 0.95)
        self._didx = int((self._didx + frames) % n)
        y = y + delayed * p["delay_mix"]

        y *= p["master"]
        pan = np.clip(p["pan"], -1, 1)
        l = np.cos((pan + 1) * np.pi / 4)
        r = np.sin((pan + 1) * np.pi / 4)
        out = np.stack([y * l, y * r], axis=1)
        return np.clip(out, -1.0, 1.0).astype(np.float32)

    # ---------------------------------------------------------------- device
    def _callback(self, outdata, frames, time_info, status):
        outdata[:] = self.render(frames)

    def start(self, device=None):
        import sounddevice as sd

        self._stream = sd.OutputStream(samplerate=self.sr, blocksize=self.block,
                                       channels=2, dtype="float32",
                                       callback=self._callback, device=device)
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
