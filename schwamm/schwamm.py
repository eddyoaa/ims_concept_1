"""
Schwamm-Instrument: Prototyp

Ein nasser Schwamm ist Sensor und Klangquelle zugleich.
- Der Arduino misst, wie gut der Schwamm leitet (Druck + Nässe).
- Ein Kontaktmikro nimmt das Glucksen und Tropfen auf.
- Dieses Skript verarbeitet den Klang live: Je fester man drückt, desto
  tiefer, dichter und verhallter wird er. Trocknet der Schwamm aus,
  verstummt das Instrument.

Start:
  python schwamm.py                          # Simulation: Schieberegler + synthetische Tropfen
  python schwamm.py --serial /dev/ttyACM0    # echter Sensor (Windows: COM3 o. ä.)
  python schwamm.py --serial COM3 --mikro    # echter Sensor + Kontaktmikro als Klangquelle
  python schwamm.py --geraete                # Audiogeräte auflisten
  python schwamm.py --offline test.wav       # ohne Soundkarte: 20 s Testklang als WAV rendern

Zusätzlich gehen Druck und Nässe per OSC an 127.0.0.1:7000
(/schwamm/druck, /schwamm/nass), z. B. für ein OSC In CHOP in TouchDesigner.
"""

import argparse
import socket
import struct
import threading
import time
import wave

import numpy as np

SR = 44100
BLOCK = 512


# ---------------------------------------------------------------------------
# Zustand: Druck und Nässe, 0..1
# ---------------------------------------------------------------------------

class Zustand:
    def __init__(self):
        self.druck = 0.0
        self.nass = 1.0
        self.roh = 0


class Simulation:
    """Ohne Hardware: Druck kommt vom Schieberegler, jedes Drücken kostet Wasser."""

    def __init__(self, zustand):
        self.z = zustand
        self.regler = 0.0

    def schritt(self, dt):
        self.z.druck = self.regler * self.z.nass
        self.z.nass = max(0.0, self.z.nass - self.regler * dt * 0.08)

    def eintauchen(self):
        self.z.nass = 1.0


class SensorLeser:
    """
    Liest die Werte vom Arduino und trennt sie in Nässe und Druck.

    Ruhewert (nicht gedrückt) = wie nass der Schwamm gerade ist.
    Wert über dem Ruhewert   = wie fest gedrückt wird.
    Der Ruhewert folgt schnell nach unten und nur langsam nach oben,
    damit Drücken nicht als "nasser" verstanden wird.
    """

    def __init__(self, zustand, port):
        import serial  # pyserial
        self.z = zustand
        self.ser = serial.Serial(port, 115200, timeout=1)
        self.ruhe = None
        self.max_ruhe = 1.0
        threading.Thread(target=self._lesen, daemon=True).start()

    def _lesen(self):
        while True:
            zeile = self.ser.readline().strip()
            try:
                wert = int(zeile)
            except ValueError:
                continue
            self.z.roh = wert
            v = wert / 1023.0
            if self.ruhe is None:
                self.ruhe = v
            if v < self.ruhe:
                self.ruhe += (v - self.ruhe) * 0.3
            else:
                self.ruhe += (v - self.ruhe) * 0.002
            self.max_ruhe = max(self.max_ruhe * 0.9999, self.ruhe, 0.05)
            self.z.nass = min(1.0, self.ruhe / self.max_ruhe)
            spielraum = max(1.0 - self.ruhe, 0.05)
            self.z.druck = float(np.clip((v - self.ruhe) / spielraum * 2.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Klang
# ---------------------------------------------------------------------------

class Tropfen:
    """Synthetische Wassertropfen (Blasenresonanz: kurzer, steigender Sinus)."""

    def __init__(self, rng):
        self.rng = rng
        self.aktiv = []  # [frequenz, phase, alter, dauer, lautstaerke]

    def block(self, n, druck, nass):
        rate = (1.5 + 30.0 * druck) * nass  # Tropfen pro Sekunde
        neue = self.rng.poisson(rate * n / SR)
        for _ in range(neue):
            self.aktiv.append([self.rng.uniform(500, 2200), 0.0, 0,
                               int(SR * self.rng.uniform(0.015, 0.07)),
                               self.rng.uniform(0.2, 0.6)])
        out = np.zeros(n)
        t = np.arange(n)
        weiter = []
        for tr in self.aktiv:
            f0, phase, alter, dauer, amp = tr
            tt = (alter + t) / SR
            f = f0 * (1 + 8.0 * tt)                       # Tonhöhe steigt wie bei einer Luftblase
            ph = phase + np.cumsum(2 * np.pi * f / SR)
            huelle = np.exp(-(alter + t) / (dauer / 4.0))
            out += amp * np.sin(ph) * huelle
            tr[1] = ph[-1]
            tr[2] = alter + n
            if tr[2] < dauer * 3:
                weiter.append(tr)
        self.aktiv = weiter
        return out


class Granular:
    """Zerlegt die letzten Sekunden Klang in Körner und spielt sie verlangsamt ab."""

    def __init__(self, rng, sekunden=3.0):
        self.rng = rng
        self.puffer = np.zeros(int(SR * sekunden))
        self.pos = 0
        self.koerner = []  # [lesepos, rate, alter, laenge, amp]

    def schreiben(self, x):
        n = len(x)
        idx = (self.pos + np.arange(n)) % len(self.puffer)
        self.puffer[idx] = x
        self.pos = (self.pos + n) % len(self.puffer)

    def block(self, n, druck):
        dichte = 40.0 * druck ** 1.5  # Körner pro Sekunde
        for _ in range(self.rng.poisson(dichte * n / SR)):
            laenge = int(SR * self.rng.uniform(0.08, 0.35))
            start = self.pos - int(SR * self.rng.uniform(0.4, 2.5))
            rate = (1.0 - 0.7 * druck) * self.rng.uniform(0.85, 1.15)  # fester = tiefer
            self.koerner.append([float(start), rate, 0, laenge, self.rng.uniform(0.4, 0.9)])
        out = np.zeros(n)
        t = np.arange(n)
        weiter = []
        L = len(self.puffer)
        for k in self.koerner:
            lese, rate, alter, laenge, amp = k
            rest = min(n, laenge - alter)
            if rest <= 0:
                continue
            p = lese + t[:rest] * rate
            i0 = np.floor(p).astype(int)
            frac = p - i0
            s = self.puffer[i0 % L] * (1 - frac) + self.puffer[(i0 + 1) % L] * frac
            fenster = np.sin(np.pi * (alter + t[:rest]) / laenge) ** 2
            out[:rest] += amp * s * fenster
            k[0] = lese + rest * rate
            k[2] = alter + rest
            if k[2] < laenge:
                weiter.append(k)
        self.koerner = weiter
        return out


class Hall:
    """Einfacher Hall aus vier Rückkopplungs-Delays (alle länger als ein Block)."""

    LAENGEN = (1601, 1867, 2053, 2251)

    def __init__(self):
        self.linien = [np.zeros(l) for l in self.LAENGEN]
        self.pos = [0] * len(self.LAENGEN)

    def block(self, x, menge):
        n = len(x)
        rueck = 0.55 + 0.35 * menge
        out = np.zeros(n)
        for i, linie in enumerate(self.linien):
            L = len(linie)
            idx = (self.pos[i] + np.arange(n)) % L
            alt = linie[idx].copy()
            linie[idx] = x + alt * rueck
            self.pos[i] = (self.pos[i] + n) % L
            out += alt
        return out / len(self.linien)


class Motor:
    def __init__(self, zustand, mikro=False):
        self.z = zustand
        self.mikro = mikro
        rng = np.random.default_rng()
        self.tropfen = Tropfen(rng)
        self.granular = Granular(rng)
        self.hall = Hall()
        self.druck = 0.0
        self.nass = 1.0

    def verarbeiten(self, eingang, n):
        # Regelwerte glätten, damit es nicht knackt
        self.druck += (self.z.druck - self.druck) * 0.2
        self.nass += (self.z.nass - self.nass) * 0.05
        d, w = self.druck, self.nass

        if self.mikro and eingang is not None:
            quelle = eingang * 4.0 * w
        else:
            quelle = self.tropfen.block(n, d, w)

        self.granular.schreiben(quelle)
        koerner = self.granular.block(n, d)
        trocken = quelle * (1.0 - 0.5 * d) + koerner * (0.3 + 0.9 * d)
        nass_signal = self.hall.block(trocken, d)
        mix = trocken + nass_signal * (0.2 + 0.8 * d)
        return np.tanh(mix * 0.8)


# ---------------------------------------------------------------------------
# OSC (minimal, ohne Zusatzbibliothek)
# ---------------------------------------------------------------------------

def _osc_str(s):
    b = s.encode() + b"\0"
    return b + b"\0" * (-len(b) % 4)


def osc_nachricht(adresse, wert):
    return _osc_str(adresse) + _osc_str(",f") + struct.pack(">f", float(wert))


class OscSender:
    def __init__(self, ziel=("127.0.0.1", 7000)):
        self.ziel = ziel
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def senden(self, z):
        for adr, w in (("/schwamm/druck", z.druck), ("/schwamm/nass", z.nass)):
            try:
                self.sock.sendto(osc_nachricht(adr, w), self.ziel)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Oberfläche
# ---------------------------------------------------------------------------

SEITE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Schwamm</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; --bg:#f4f4f4; --fg:#111; --leer:#ddd; --voll:#2a7ab0; }
  @media (prefers-color-scheme: dark) { :root { --bg:#1e1e1e; --fg:#eee; --leer:#3a3a3a; --voll:#4aa3df; } }
  body { background:var(--bg); color:var(--fg); font:16px -apple-system, system-ui, sans-serif;
         max-width:420px; margin:40px auto; padding:0 16px; }
  .balken { height:22px; background:var(--leer); border-radius:4px; overflow:hidden; margin:6px 0 18px; }
  .balken div { height:100%; width:0; background:var(--voll); transition:width .05s; }
  input[type=range] { width:100%; margin:8px 0 16px; }
  button { font:inherit; padding:8px 16px; }
  .klein { opacity:.6; font-size:14px; }
</style></head><body>
<h2>Schwamm</h2>
<div>Druck</div><div class="balken"><div id="druck"></div></div>
<div>Nässe</div><div class="balken"><div id="nass"></div></div>
<div id="sim" hidden>
  <div>Schwamm drücken (Simulation)</div>
  <input id="regler" type="range" min="0" max="100" value="0">
  <button id="tauchen">In Wasser tauchen</button>
</div>
<p class="klein" id="roh"></p>
<script>
  const regler = document.getElementById('regler');
  regler.oninput = () => fetch('/regler?v=' + regler.value / 100);
  // Beim Loslassen springt der Regler zurück, wie ein Schwamm
  regler.onpointerup = () => { regler.value = 0; regler.oninput(); };
  document.getElementById('tauchen').onclick = () => fetch('/eintauchen');
  async function tick() {
    try {
      const z = await (await fetch('/zustand')).json();
      document.getElementById('druck').style.width = (z.druck * 100) + '%';
      document.getElementById('nass').style.width = (z.nass * 100) + '%';
      document.getElementById('sim').hidden = !z.sim;
      document.getElementById('roh').textContent = z.sim ? '' : 'Sensor roh: ' + z.roh;
    } catch (e) {}
    setTimeout(tick, 50);
  }
  tick();
</script></body></html>
"""


def oberflaeche(zustand, sim, osc, port=8765):
    """Kleine Webseite im Browser statt eines Tk-Fensters (Tk zeichnet auf macOS oft leer)."""
    import json
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                self._antwort(SEITE, "text/html; charset=utf-8")
            elif url.path == "/zustand":
                self._antwort(json.dumps({"druck": zustand.druck, "nass": zustand.nass,
                                          "roh": zustand.roh, "sim": sim is not None}),
                              "application/json")
            elif url.path == "/regler" and sim:
                sim.regler = float(parse_qs(url.query).get("v", ["0"])[0])
                self._antwort("ok", "text/plain")
            elif url.path == "/eintauchen" and sim:
                sim.eintauchen()
                self._antwort("ok", "text/plain")
            else:
                self.send_error(404)

        def _antwort(self, text, typ):
            daten = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    adresse = f"http://127.0.0.1:{port}"
    print(f"Oberfläche: {adresse}  (beenden mit Strg+C)")
    webbrowser.open(adresse)

    letzte = time.time()
    try:
        while True:
            time.sleep(1 / 30)
            jetzt = time.time()
            if sim:
                sim.schritt(jetzt - letzte)
            letzte = jetzt
            osc.senden(zustand)
    except KeyboardInterrupt:
        server.shutdown()

# ---------------------------------------------------------------------------

def offline_rendern(pfad, sekunden=20):
    """Ohne Soundkarte: simuliert Drücken, Austrocknen und Eintauchen und schreibt eine WAV."""
    z = Zustand()
    sim = Simulation(z)
    motor = Motor(z)
    bloecke = []
    for b in range(int(sekunden * SR / BLOCK)):
        t = b * BLOCK / SR
        sim.regler = max(0.0, np.sin(t * 0.9)) ** 2   # rhythmisches Drücken
        if abs(t - 12.0) < BLOCK / SR:
            sim.eintauchen()
        sim.schritt(BLOCK / SR)
        bloecke.append(motor.verarbeiten(None, BLOCK))
    audio = np.concatenate(bloecke)
    with wave.open(pfad, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    print(f"{pfad} geschrieben, Spitze {np.max(np.abs(audio)):.2f}")


def main():
    ap = argparse.ArgumentParser(description="Schwamm-Instrument")
    ap.add_argument("--serial", help="Port des Arduino, z. B. /dev/ttyACM0 oder COM3")
    ap.add_argument("--mikro", action="store_true", help="Kontaktmikro als Klangquelle")
    ap.add_argument("--eingang", type=int, help="Nummer des Audio-Eingangs (siehe --geraete)")
    ap.add_argument("--ausgang", type=int, help="Nummer des Audio-Ausgangs")
    ap.add_argument("--geraete", action="store_true", help="Audiogeräte auflisten")
    ap.add_argument("--offline", metavar="WAV", help="Testklang als WAV rendern")
    args = ap.parse_args()

    if args.offline:
        offline_rendern(args.offline)
        return

    import sounddevice as sd
    if args.geraete:
        print(sd.query_devices())
        return

    z = Zustand()
    sim = None if args.serial else Simulation(z)
    if args.serial:
        SensorLeser(z, args.serial)
    motor = Motor(z, mikro=args.mikro)

    if args.mikro:
        def callback(indata, outdata, frames, t, status):
            outdata[:, 0] = motor.verarbeiten(indata[:, 0].astype(float), frames)
        stream = sd.Stream(samplerate=SR, blocksize=BLOCK, channels=1, callback=callback,
                           device=(args.eingang, args.ausgang))
    else:
        def callback(outdata, frames, t, status):
            outdata[:, 0] = motor.verarbeiten(None, frames)
        stream = sd.OutputStream(samplerate=SR, blocksize=BLOCK, channels=1,
                                 callback=callback, device=args.ausgang)

    with stream:
        oberflaeche(z, sim, OscSender())


if __name__ == "__main__":
    main()
