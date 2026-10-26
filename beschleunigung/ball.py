"""Ball-Auswertung: aus Beschleunigung werden Ball-Ereignisse und daraus Klang.

midi.py behandelt den Sensor wie einen Neigungs-Regler (Achse X kippen = Tonhöhe).
Für einen Ball passt das nicht: Ein Ball hat kein Oben, er dreht sich beliebig,
und im Flug misst der Sensor fast 0 g – midi.py wird genau dann still, wenn der
Ball in der Luft ist. Dieses Skript wertet stattdessen aus, was ein Ball TUT:

    Zustand   ruhe / bewegt / flug
    Abflug    der Ball verlässt die Hand (Messung fällt auf ~0 g = freier Fall)
    Landung   Fang oder Aufprall, mit Flugdauer und daraus grob der Wurfhöhe
    Stoß      kurzer harter Schlag ohne Flug (Kick, Schlag mit der Hand)
    Ruhe      der Ball liegt still
    Bewegung  0..1, wie stark er geschüttelt/bewegt wird (fortlaufend)
    Drehung   0..1, wie schnell er rollt oder gedreht wird (fortlaufend)

Was daraus klingt, steht in einer Zuordnung (JSON). Die lässt sich auf der Seite
http://127.0.0.1:8767 bearbeiten (zuordnung.html), dort sieht und hört man die
Ereignisse auch live. Ausgabe: virtueller MIDI-Port „Ball“ (ein Ball = ein Kanal),
optional OSC.

    python beschleunigung/ball.py                      # Ball(e) über WLAN (UDP 4210)
    python beschleunigung/ball.py --sim                # ohne Hardware: simulierte Würfe
    python beschleunigung/ball.py --aufnahme w.csv     # Rohdaten mitschreiben
    python beschleunigung/ball.py --datei w.csv        # Aufnahme abspielen (zum Feintunen)
    python beschleunigung/ball.py --serial /dev/cu.usbmodem1201
    python beschleunigung/ball.py --zuordnung meine.json --osc 127.0.0.1:9000
"""

import argparse
import csv
import json
import math
import os
import queue
import random
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HIER = os.path.dirname(os.path.abspath(__file__))
UDP_PORT = 4210
SEITE_PORT = 8767
G = 9.81

ZEILE = re.compile(
    r"ax=([+-]?\d+(?:\.\d+)?) ay=([+-]?\d+(?:\.\d+)?) az=([+-]?\d+(?:\.\d+)?)"
    r"(?:\s+t=(\d+))?(?:\s+n=(\d+))?(?:\s+id=(\d+))?"
)

# ---------------------------------------------------------------------------
# Schwellen. Alles in g bzw. Sekunden. Mit --aufnahme echte Würfe mitschneiden,
# mit --datei abspielen und hier nachjustieren.
# ---------------------------------------------------------------------------

FREI = 0.40          # darunter gilt der Ball als im freien Fall
FREI_MIN = 0.05      # so lange muss er frei fallen, bevor es ein Abflug ist
LANDE = 0.80         # darüber ist der Flug zu Ende (Fang/Aufprall)
FLUG_MAX = 3.0       # länger fliegt kein Ball im Raum; sonst Messfehler
STOSS = 0.45         # so viel Ruck ist ein Stoß (der MMA7660 kappt bei 1,5 g, viel mehr geht nicht)
STOSS_WARTEN = 0.08  # so lange nach dem Ruck warten: kommt ein Flug, war es ein Wurf
STOSS_PAUSE = 0.20   # Mindestabstand zwischen zwei Stößen
RUHE_BEWEGUNG = 0.06
RUHE_DREHUNG = 0.08
RUHE_ZEIT = 0.5      # so lange still, dann gilt er als liegend
RAUSCHEN = 0.03      # g Messrauschen, das zählt nicht als Bewegung
BEWEGUNG_VOLL = 0.5  # g Ruck = Bewegung 1.0
DREHUNG_VOLL = 720.0 # Grad pro Sekunde (2 Umdrehungen/s) = Drehung 1.0


def _glaetten(alt, neu, dt, tau):
    """Exponentielle Glättung mit Zeitkonstante tau, unabhängig von der Abtastrate."""
    k = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
    return alt + (neu - alt) * k


class BallErkennung:
    """Bekommt Messungen (t in s, ax/ay/az in g) und liefert Ereignisse."""

    def __init__(self, ball_id=1):
        self.id = ball_id
        self.zustand = "ruhe"
        self.t = None
        self.schwere = None        # geschätzte Richtung der Schwerkraft (nur außerhalb des Flugs)
        self.bewegung = 0.0
        self.drehung = 0.0
        self.betrag = 1.0
        self.frei_seit = None
        self.abflug_t = None
        self.landung_t = -10.0
        self.stoss_t = -10.0
        self.stoss_wartet = None   # (t, staerke)
        self.still_seit = None
        self.letzte_hoehe = 0.0

    def messung(self, t, ax, ay, az):
        ereignisse = []
        if self.t is None:
            self.t = t
            self.schwere = [ax, ay, az]
            return ereignisse
        dt = min(max(t - self.t, 0.001), 0.2)
        self.t = t
        m = math.sqrt(ax * ax + ay * ay + az * az)
        self.betrag = m

        # --- Flug -----------------------------------------------------------
        if self.zustand == "flug":
            dauer = t - self.abflug_t
            if m > LANDE or dauer > FLUG_MAX:
                hoehe = G * dauer * dauer / 8.0   # Wurf und Fang auf gleicher Höhe
                self.letzte_hoehe = hoehe
                self.zustand = "bewegt"
                self.landung_t = t
                self.frei_seit = None
                self.still_seit = None
                ereignisse.append(self._e("landung", dauer=round(dauer, 3), hoehe=round(hoehe, 2),
                                          staerke=round(min(1.0, dauer / 1.0), 3)))
            return ereignisse

        if m < FREI:
            if self.frei_seit is None:
                self.frei_seit = t - dt / 2
            if t - self.frei_seit >= FREI_MIN:
                self.zustand = "flug"
                self.abflug_t = self.frei_seit
                self.stoss_wartet = None   # der Ruck davor war der Wurf
                self.still_seit = None
                ereignisse.append(self._e("abflug"))
                return ereignisse
        else:
            self.frei_seit = None

        # --- Schwerkraft, Bewegung, Drehung --------------------------------
        vorher = self.schwere[:]
        self.schwere = [_glaetten(s, a, dt, 0.06) for s, a in zip(self.schwere, (ax, ay, az))]
        ruck = math.dist((ax, ay, az), self.schwere)
        self.bewegung = _glaetten(self.bewegung, min(1.0, max(0.0, ruck - RAUSCHEN) / BEWEGUNG_VOLL), dt, 0.15)

        lang_v, lang_n = math.hypot(*vorher), math.hypot(*self.schwere)
        if 0.6 < lang_n < 1.5 and lang_v > 0.3 and m > FREI:
            cos = sum(a * b for a, b in zip(vorher, self.schwere)) / (lang_v * lang_n)
            winkel = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            ziel = min(1.0, (winkel / dt) / DREHUNG_VOLL)
        else:
            ziel = self.drehung
        self.drehung = _glaetten(self.drehung, ziel, dt, 0.2)

        # --- Stoß --------------------------------------------------------
        # Ein Ruck allein ist noch kein Stoß: Beim Werfen gibt es auch einen Ruck,
        # direkt danach fällt der Ball aber frei. Darum erst entscheiden, wenn der
        # Ruck vorbei ist und STOSS_WARTEN lang kein freier Fall kam.
        # Gemessen am Betrag: der hängt nicht davon ab, wie der Ball gerade gedreht
        # ist. So wird schnelles Rollen nicht zum Stoß.
        heftig = abs(m - 1.0)
        if heftig > STOSS and t - self.stoss_t > STOSS_PAUSE and t - self.landung_t > 0.25:
            staerke = min(1.0, (heftig - STOSS) / 1.0 + 0.2)
            alt = self.stoss_wartet[1] if self.stoss_wartet else 0.0
            self.stoss_wartet = (t, max(alt, staerke))   # t = letzter Moment mit Ruck
        if self.frei_seit is not None:
            self.stoss_wartet = None
        elif self.stoss_wartet and t - self.stoss_wartet[0] >= STOSS_WARTEN:
            self.stoss_t = t
            ereignisse.append(self._e("stoss", staerke=round(self.stoss_wartet[1], 3)))
            self.stoss_wartet = None
            self.zustand = "bewegt"
            self.still_seit = None

        # --- Ruhe -----------------------------------------------------------
        still = self.bewegung < RUHE_BEWEGUNG and self.drehung < RUHE_DREHUNG
        if self.zustand == "ruhe":
            if not still and (self.bewegung > 2 * RUHE_BEWEGUNG or self.drehung > 2 * RUHE_DREHUNG):
                self.zustand = "bewegt"
                self.still_seit = None
        elif still:
            if self.still_seit is None:
                self.still_seit = t
            elif t - self.still_seit >= RUHE_ZEIT:
                self.zustand = "ruhe"
                ereignisse.append(self._e("ruhe"))
        else:
            self.still_seit = None
        return ereignisse

    def werte(self):
        return {"typ": "werte", "ball": self.id, "zustand": self.zustand,
                "bewegung": round(self.bewegung, 3), "drehung": round(self.drehung, 3),
                "betrag": round(self.betrag, 3)}

    def _e(self, art, **daten):
        return {"typ": "ereignis", "ball": self.id, "art": art, "t": round(self.t, 3), **daten}


# ---------------------------------------------------------------------------
# Zuordnung: welcher Ball was bei welcher Interaktion macht
# ---------------------------------------------------------------------------

SKALEN = {
    "moll_pentatonik": [0, 3, 5, 7, 10],
    "dur_pentatonik": [0, 2, 4, 7, 9],
    "dur": [0, 2, 4, 5, 7, 9, 11],
    "moll": [0, 2, 3, 5, 7, 8, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "ganzton": [0, 2, 4, 6, 8, 10],
    "chromatisch": list(range(12)),
}

# fortlaufende Werte -> MIDI-Steuerung
STEUERUNG = {"filter": 74, "lautstaerke": 7, "hall": 91, "vibrato": 1, "verzerrung": 77}

STANDARD = {
    "grundton": 48,
    "skala": "moll_pentatonik",
    "baelle": [
        {"id": 1, "name": "Softball", "typ": "softball", "farbe": "#e4572e", "klang": "pad",
         "kanal": 1, "oktave": 0, "aktiv": True,
         "aktionen": {
             "abflug": {"funktion": "ton_halten", "tonhoehe": "skala_schritt", "oktave": 0},
             "landung": {"funktion": "schlag", "tonhoehe": "flughoehe", "oktave": 1},
             "stoss": {"funktion": "schlag", "tonhoehe": "fest", "oktave": -1},
             "ruhe": {"funktion": "stille"},
             "drehung": {"funktion": "filter"},
             "bewegung": {"funktion": "lautstaerke"},
         }},
    ],
}


class Ausgabe:
    """Setzt Ereignisse nach der Zuordnung in MIDI (und OSC) um."""

    def __init__(self, midi=None, osc=None):
        self.midi = midi
        self.osc = osc
        self.zuordnung = json.loads(json.dumps(STANDARD))
        self.schritt = {}      # Ball-ID -> Position in der Skala
        self.gehalten = {}     # Ball-ID -> (kanal, [noten])
        self.aus_liste = []    # (zeitpunkt, kanal, note)
        self.letzte_cc = {}
        self.lock = threading.Lock()

    def setze_zuordnung(self, z):
        with self.lock:
            self._alles_aus()
            self.zuordnung = z
            self.schritt = {}

    def ball(self, ball_id):
        baelle = [b for b in self.zuordnung.get("baelle", []) if b.get("aktiv", True)]
        for b in baelle:
            if int(b.get("id", 0)) == ball_id:
                return b
        return baelle[0] if len(baelle) == 1 else None

    def _skalenton(self, b, stufe, oktave):
        skala = SKALEN.get(self.zuordnung.get("skala"), SKALEN["moll_pentatonik"])
        okt, rest = divmod(stufe, len(skala))
        note = (self.zuordnung.get("grundton", 48) + 12 * (b.get("oktave", 0) + oktave + okt)
                + skala[rest])
        return max(0, min(127, note))

    def _stufe(self, b, aktion, e):
        skala_len = len(SKALEN.get(self.zuordnung.get("skala"), SKALEN["moll_pentatonik"]))
        art = aktion.get("tonhoehe", "skala_schritt")
        if art == "fest":
            return 0
        if art == "zufall":
            return random.randrange(2 * skala_len)
        if art == "flughoehe" and "dauer" in e:
            anteil = max(0.0, min(1.0, (e["dauer"] - 0.1) / 1.1))
            return round(anteil * (2 * skala_len - 1))
        s = self.schritt.get(b["id"], -1) + 1
        self.schritt[b["id"]] = s % (2 * skala_len)
        return self.schritt[b["id"]]

    def ereignis(self, e):
        self._osc(f"/ball/{e['ball']}/{e['art']}", [e.get("staerke", 1.0), e.get("dauer", 0.0)])
        with self.lock:
            b = self.ball(e["ball"])
            if b is None:
                return
            kanal = max(0, min(15, int(b.get("kanal", 1)) - 1))
            jetzt = time.monotonic()
            if e["art"] in ("landung", "stoss", "abflug"):
                gehalten = self.gehalten.pop(b["id"], None)
                if gehalten:
                    for n in gehalten[1]:
                        self._send("note_off", channel=gehalten[0], note=n, velocity=0)
            aktion = b.get("aktionen", {}).get(e["art"], {})
            funktion = aktion.get("funktion", "nichts")
            if e["art"] == "ruhe":
                if funktion == "stille":
                    self._send("control_change", channel=kanal, control=123, value=0)
                return
            if funktion == "nichts":
                return
            stufe = self._stufe(b, aktion, e)
            okt = aktion.get("oktave", 0)
            if funktion == "akkord":
                noten = [self._skalenton(b, stufe + i, okt) for i in (0, 2, 4)]
            else:
                noten = [self._skalenton(b, stufe, okt)]
            staerke = e.get("staerke", 0.8)
            if funktion == "schlag":
                vel, laenge = 50 + round(77 * staerke), 0.1
            elif funktion == "ton_halten" and e["art"] == "abflug":
                vel, laenge = 100, None
            else:
                vel, laenge = 60 + round(50 * staerke), 0.5
            for n in noten:
                self._send("note_on", channel=kanal, note=n, velocity=max(1, min(127, vel)))
                if laenge:
                    self.aus_liste.append((jetzt + laenge, kanal, n))
            if laenge is None:
                self.gehalten[b["id"]] = (kanal, noten)

    def werte(self, w):
        self._osc(f"/ball/{w['ball']}/werte", [w["bewegung"], w["drehung"], w["betrag"]])
        with self.lock:
            b = self.ball(w["ball"])
            if b is None:
                return
            kanal = max(0, min(15, int(b.get("kanal", 1)) - 1))
            for groesse in ("bewegung", "drehung"):
                funktion = b.get("aktionen", {}).get(groesse, {}).get("funktion", "nichts")
                wert = w[groesse]
                schluessel = (kanal, funktion)
                if funktion == "tonhoehe":
                    bend = round(wert * 8191)
                    if self.letzte_cc.get(schluessel) != bend:
                        self.letzte_cc[schluessel] = bend
                        self._send("pitchwheel", channel=kanal, pitch=bend)
                elif funktion in STEUERUNG:
                    cc = round(wert * 127)
                    if self.letzte_cc.get(schluessel) != cc:
                        self.letzte_cc[schluessel] = cc
                        self._send("control_change", channel=kanal,
                                   control=STEUERUNG[funktion], value=cc)

    def takt(self):
        """Fällige Note-Offs senden. Regelmäßig aufrufen."""
        jetzt = time.monotonic()
        with self.lock:
            faellig = [x for x in self.aus_liste if x[0] <= jetzt]
            self.aus_liste = [x for x in self.aus_liste if x[0] > jetzt]
        for _, kanal, note in faellig:
            self._send("note_off", channel=kanal, note=note, velocity=0)

    def _alles_aus(self):
        for kanal in range(16):
            self._send("control_change", channel=kanal, control=123, value=0)
        self.gehalten.clear()
        self.aus_liste.clear()

    def schliessen(self):
        with self.lock:
            self._alles_aus()

    def _send(self, art, **werte):
        if self.midi is None:
            return
        import mido
        self.midi.send(mido.Message(art, **werte))

    def _osc(self, adresse, werte):
        if self.osc is not None:
            try:
                self.osc.send_message(adresse, werte)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Seite: zuordnung.html, Live-Ereignisse per Server-Sent Events
# ---------------------------------------------------------------------------

class Verteiler:
    def __init__(self):
        self.hoerer = set()
        self.lock = threading.Lock()

    def neu(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.hoerer.add(q)
        return q

    def weg(self, q):
        with self.lock:
            self.hoerer.discard(q)

    def senden(self, nachricht):
        with self.lock:
            for q in list(self.hoerer):
                try:
                    q.put_nowait(nachricht)
                except queue.Full:
                    pass


def seite_starten(ausgabe, verteiler, zuordnung_datei):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/zuordnung.html"):
                with open(os.path.join(HIER, "zuordnung.html"), "rb") as f:
                    self._antwort(f.read(), "text/html; charset=utf-8")
            elif self.path == "/zuordnung":
                self._antwort(json.dumps(ausgabe.zuordnung).encode(), "application/json")
            elif self.path == "/ereignisse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                q = verteiler.neu()
                try:
                    self.wfile.write(b"retry: 1000\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            nachricht = q.get(timeout=5)
                            self.wfile.write(f"data: {json.dumps(nachricht)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": da\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    verteiler.weg(q)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/zuordnung":
                self.send_error(404)
                return
            laenge = int(self.headers.get("Content-Length", 0))
            try:
                z = json.loads(self.rfile.read(laenge))
                assert isinstance(z.get("baelle"), list)
            except (ValueError, AssertionError):
                self.send_error(400)
                return
            ausgabe.setze_zuordnung(z)
            if zuordnung_datei:
                with open(zuordnung_datei, "w", encoding="utf-8") as f:
                    json.dump(z, f, ensure_ascii=False, indent=2)
            self._antwort(b"ok", "text/plain")

        def _antwort(self, daten, typ):
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(daten)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(daten)
            except BrokenPipeError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", SEITE_PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{SEITE_PORT}"


# ---------------------------------------------------------------------------
# Simulation: Messwerte wie vom MMA7660 im Ball (±1,5 g, 6 Bit, verrauscht)
# ---------------------------------------------------------------------------

def mma7660(x, y, z):
    def eine(w):
        w = max(-1.5, min(1.45, w + random.gauss(0, 0.02)))
        return round(w * 21.33) / 21.33
    return eine(x), eine(y), eine(z)


def simuliere(rate=100, runden=None, zufall=None):
    """Erzeugt (t, ax, ay, az): liegen, aufheben, werfen, fangen, rollen, fallen lassen."""
    rnd = zufall or random.Random(1)
    t, dt = 0.0, 1.0 / rate
    runde = 0

    def schwere(winkel):
        return (math.sin(winkel), 0.0, math.cos(winkel))

    def abschnitt(dauer, fn):
        nonlocal t
        n = int(dauer * rate)
        for i in range(n):
            yield (t, *mma7660(*fn(i / max(1, n), i * dt)))
            t += dt

    while runden is None or runde < runden:
        runde += 1
        winkel = rnd.uniform(0, math.pi)
        yield from abschnitt(1.0, lambda p, s: schwere(winkel))                       # liegt
        yield from abschnitt(0.5, lambda p, s: [g + 0.15 * math.sin(s * 9) for g in schwere(winkel)])  # aufheben
        yield from abschnitt(0.15, lambda p, s: (0.3, 0.4, 1.0 + 1.8 * math.sin(p * math.pi)))  # Wurfbewegung
        flug = rnd.uniform(0.35, 1.1)
        yield from abschnitt(flug, lambda p, s: (0.05, -0.03, 0.04))                  # Flug
        yield from abschnitt(0.08, lambda p, s: (-0.8, 1.2, 2.0))                     # Fang
        yield from abschnitt(0.8, lambda p, s: [g + 0.08 * math.sin(s * 13) for g in schwere(winkel)])  # halten
        dreh = rnd.uniform(4, 10)                                                     # rad/s
        yield from abschnitt(2.0, lambda p, s: schwere(winkel + dreh * s * (1 - p / 2)))  # rollen, wird langsamer
        ende = winkel + dreh * 2.0 / 2
        yield from abschnitt(0.4, lambda p, s: schwere(ende))
        for fall in (0.45, 0.3, 0.18):                                                 # fallen lassen + springen
            yield from abschnitt(fall, lambda p, s: (0.0, 0.02, 0.03))
            yield from abschnitt(0.03, lambda p, s: (0.2, 0.1, 1.5))
        yield from abschnitt(1.5, lambda p, s: schwere(0.2))                           # liegt
        yield from abschnitt(0.05, lambda p, s: (1.4, -1.4, 1.2))                      # Kick
        yield from abschnitt(1.0, lambda p, s: schwere(0.2 + 3 * s))                   # rollt weg


# ---------------------------------------------------------------------------
# Quellen und Hauptschleife
# ---------------------------------------------------------------------------

def quelle_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", UDP_PORT))
    s.settimeout(0.05)
    print(f"Warte auf Bälle an UDP {UDP_PORT}")
    while True:
        try:
            daten, _ = s.recvfrom(256)
        except socket.timeout:
            yield None
            continue
        yield daten.decode("ascii", "ignore")


def quelle_serial(port):
    import serial
    s = serial.Serial(port, 115200, timeout=0.05)
    time.sleep(2)
    s.reset_input_buffer()
    print(f"Lese Sensor von {port}")
    while True:
        zeile = s.readline()
        yield zeile.decode("ascii", "ignore") if zeile else None


def zerlegen(zeile, uhr_start):
    """Zeile -> (ball_id, t, ax, ay, az). Ohne t= gilt die Ankunftszeit."""
    treffer = ZEILE.search(zeile)
    if not treffer:
        return None
    ax, ay, az = (float(treffer.group(i)) for i in (1, 2, 3))
    t = int(treffer.group(4)) / 1000.0 if treffer.group(4) else time.monotonic() - uhr_start
    ball_id = int(treffer.group(6)) if treffer.group(6) else 1
    return ball_id, t, ax, ay, az


def main():
    ap = argparse.ArgumentParser(description="Ball-Ereignisse aus Beschleunigung, als MIDI/OSC")
    ap.add_argument("--serial", help="USB-Port statt WLAN")
    ap.add_argument("--sim", action="store_true", help="ohne Hardware: simulierte Würfe")
    ap.add_argument("--datei", help="Aufnahme (CSV) abspielen")
    ap.add_argument("--aufnahme", help="Rohdaten als CSV mitschreiben")
    ap.add_argument("--zuordnung", help="Zuordnung (JSON) laden; Änderungen von der Seite landen dort")
    ap.add_argument("--name", default="Ball", help="Name des MIDI-Ports")
    ap.add_argument("--kein-midi", action="store_true")
    ap.add_argument("--osc", help="OSC-Ziel, z. B. 127.0.0.1:9000")
    ap.add_argument("--keine-seite", action="store_true", help="Browser nicht öffnen")
    args = ap.parse_args()

    midi = None
    if not args.kein_midi:
        try:
            import mido
            midi = mido.open_output(args.name, virtual=True)
            print(f"MIDI-Port „{args.name}“ ist offen (ein Ball = ein Kanal).")
        except Exception as fehler:  # noqa: BLE001 – ohne MIDI trotzdem weiterlaufen
            print(f"Kein MIDI ({fehler}). Weiter nur mit Seite/OSC.")
    osc = None
    if args.osc:
        from pythonosc.udp_client import SimpleUDPClient
        host, port = args.osc.split(":")
        osc = SimpleUDPClient(host, int(port))

    ausgabe = Ausgabe(midi, osc)
    if args.zuordnung and os.path.exists(args.zuordnung):
        with open(args.zuordnung, encoding="utf-8") as f:
            ausgabe.setze_zuordnung(json.load(f))
    verteiler = Verteiler()
    adresse = seite_starten(ausgabe, verteiler, args.zuordnung)
    print(f"Zuordnung und Live-Ansicht: {adresse}")
    if not args.keine_seite:
        import webbrowser
        webbrowser.open(adresse)

    aufnahme = None
    if args.aufnahme:
        aufnahme_datei = open(args.aufnahme, "w", newline="")
        aufnahme = csv.writer(aufnahme_datei)
        aufnahme.writerow(["t", "ax", "ay", "az", "id"])

    erkennung = {}
    letzte_werte = {}
    uhr_start = time.monotonic()

    def verarbeiten(ball_id, t, ax, ay, az):
        if aufnahme:
            aufnahme.writerow([f"{t:.3f}", ax, ay, az, ball_id])
        e = erkennung.setdefault(ball_id, BallErkennung(ball_id))
        for ereignis in e.messung(t, ax, ay, az):
            print(f"Ball {ball_id}: {ereignis['art']:8s}"
                  + "".join(f"  {k}={v}" for k, v in ereignis.items()
                            if k in ("dauer", "hoehe", "staerke")))
            ausgabe.ereignis(ereignis)
            verteiler.senden(ereignis)
        jetzt = time.monotonic()
        if jetzt - letzte_werte.get(ball_id, 0) > 1 / 30:   # fortlaufende Werte mit 30 Hz
            letzte_werte[ball_id] = jetzt
            w = e.werte()
            ausgabe.werte(w)
            verteiler.senden(w)
        ausgabe.takt()

    try:
        if args.sim or args.datei:
            if args.sim:
                messungen = ((1, t, x, y, z) for t, x, y, z in simuliere())
                print("Simulation läuft: liegen, werfen, fangen, rollen, fallen lassen, Kick …")
            else:
                def aus_datei():
                    with open(args.datei, newline="") as f:
                        for r in csv.DictReader(f):
                            yield int(r.get("id") or 1), float(r["t"]), float(r["ax"]), float(r["ay"]), float(r["az"])
                messungen = aus_datei()
            start, t0 = time.monotonic(), None
            for ball_id, t, ax, ay, az in messungen:
                t0 = t if t0 is None else t0
                warten = (t - t0) - (time.monotonic() - start)
                if warten > 0:
                    time.sleep(warten)
                verarbeiten(ball_id, t, ax, ay, az)
            time.sleep(0.6)
            ausgabe.takt()
        else:
            zeilen = quelle_serial(args.serial) if args.serial else quelle_udp()
            for zeile in zeilen:
                if zeile is None:
                    ausgabe.takt()
                    continue
                teile = zerlegen(zeile, uhr_start)
                if teile:
                    verarbeiten(*teile)
    except KeyboardInterrupt:
        print()
    finally:
        ausgabe.schliessen()
        if midi:
            midi.close()
        if aufnahme:
            aufnahme_datei.close()


if __name__ == "__main__":
    main()
