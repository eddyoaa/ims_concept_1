"""Beschleunigung als MIDI, mit einer Seite zum Trennen der Achsen.

Der ESP8266 schickt die Messwerte per UDP (Port 4210). Dieses Skript
macht daraus einen virtuellen MIDI-Port namens „Beschleunigung“.
Mit --serial geht weiterhin der Joy-IT über USB.

Jede Achse ist die Neigung, unabhängig von den anderen. Waagrecht ist 64.
Wie schnell der Ball sich dreht oder bewegt, steuert die Lautstärke.
Kanal 1:

    X Neigung  ->  Tonhöhe (Pitch Bend)
    Y Neigung  ->  CC 17
    Z Neigung  ->  CC 18
    Bewegung   ->  Lautstärke CC 7

Auf http://127.0.0.1:8766 lässt sich jede Achse einzeln senden. Für MIDI-Learn
in Helm „Nur X“ (oder Y, Z) drücken, dann Learn: es kommt nur diese eine
Steuerung an.

    python beschleunigung/midi.py
    python beschleunigung/midi.py --serial /dev/cu.usbmodem1201
"""

import argparse
import json
import re
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import mido
import serial

ZEILE = re.compile(
    r"ax=([+-]?\d+(?:\.\d+)?) ay=([+-]?\d+(?:\.\d+)?) az=([+-]?\d+(?:\.\d+)?)"
)
ACHSEN = ("X", "Y", "Z")
CCS = (16, 17, 18)
KANAL = 0  # MIDI-Kanal 1
SEITE_PORT = 8766
UDP_PORT = 4210
GLATT = 0.35      # Neigung folgt, ohne zu zittern
TEMPO_GLATT = 0.3  # Lautstärke folgt der Bewegung
RAUSCHEN = 0.012   # g je Messung, darunter gilt als still
TEMPO_VOLL = 0.07  # so viel Änderung je Messung ist volle Lautstärke
NOTE = 48         # C3

SEITE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Beschleunigung</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; --bg:#f4f4f4; --fg:#111; --leer:#ddd; --voll:#2a7ab0; --karte:#fff; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#1e1e1e; --fg:#eee; --leer:#3a3a3a; --voll:#4aa3df; --karte:#2a2a2a; }
  }
  body { background:var(--bg); color:var(--fg); font:16px -apple-system, system-ui, sans-serif;
         max-width:440px; margin:40px auto; padding:0 16px; }
  .klein { opacity:.6; font-size:14px; }
  .reihe { display:flex; gap:8px; margin:18px 0; }
  button { font:inherit; padding:8px 14px; border-radius:6px; border:1px solid #8884; background:var(--karte); color:inherit; }
  button.an { background:var(--voll); color:#fff; border-color:transparent; }
  .karte { background:var(--karte); border-radius:8px; padding:12px 14px; margin:10px 0; }
  .karte.aus { opacity:.4; }
  .kopf { display:flex; justify-content:space-between; align-items:baseline; }
  .balken { height:22px; background:var(--leer); border-radius:4px; overflow:hidden; margin-top:8px; }
  .balken div { height:100%; width:0; background:var(--voll); }
  .cc { font-variant-numeric:tabular-nums; }
  h3 { font-size:15px; margin:22px 0 8px; }
  .ziel { font-size:14px; margin-top:4px; }
</style></head><body>
<h2>Beschleunigung</h2>
<p class="klein">Neigung und Bewegung sind getrennt. Jede Achse kippt für sich. Drehen und Bewegen macht laut, Stillstand ist leise.</p>

<h3>Von selbst</h3>
<div class="karte">
  <div class="kopf"><b>Ton C3</b><span id="ton">Ton aus</span></div>
  <p class="ziel">Nichts lernen. In Helm bei der Amplitude Envelope <b>S</b> nach oben, sonst verklingt er.</p>
</div>
<div class="karte">
  <div class="kopf"><b>Lautstärke</b><span class="cc" id="laut">CC 7 = 0</span></div>
  <div class="balken"><div id="lautbalken"></div></div>
  <p class="ziel">Wie schnell er sich dreht oder bewegt. Helm: Volume unten rechts.</p>
  <div class="reihe"><button id="lernlaut" type="button">Anlernen</button></div>
</div>

<h3>In Helm lernen</h3>
<p class="klein">In Helm am Regler <b>Learn MIDI Assignment</b>, dann hier <b>Anlernen</b>. Es läuft nur diese Steuerung, bis du <b>Stopp</b> drückst.</p>
<button id="stopp" type="button" hidden>Stopp</button>
<div id="karten"></div>
<script>
  const ziele = [
    ["X", "Tonhöhe. In Helm Pitch Bend auf 12 stellen, dann ist die volle Neigung eine Oktave.", false],
    ["Y", "Filter Resonance, Schieber rechts an der Kurve", true],
    ["Z", "Panorama, links und rechts", true]
  ];
  const karten = document.getElementById("karten");
  ziele.forEach(([name, ziel, lernbar], i) => {
    const el = document.createElement("div");
    el.className = "karte";
    el.innerHTML = `<div class="kopf"><b>${name}</b><span class="cc"></span></div>
      <div class="balken"><div></div></div>
      <p class="ziel">${ziel}</p>` + (lernbar
        ? `<div class="reihe"><button class="lern" type="button">Anlernen</button></div>` : "");
    const knopf = el.querySelector(".lern");
    if (knopf) knopf.onclick = () => fetch("/lernen?was=" + i);
    karten.appendChild(el);
  });
  document.getElementById("lernlaut").onclick = () => fetch("/lernen?was=laut");
  document.getElementById("stopp").onclick = () => fetch("/stopp");
  function setzen(el, text) {
    if (el.textContent !== text) el.textContent = text;
  }
  async function tick() {
    try {
      const z = await (await fetch("/zustand")).json();
      setzen(document.getElementById("ton"), z.ton ? "Ton an" : "Ton aus");
      setzen(document.getElementById("laut"), "CC 7 = " + z.laut);
      document.getElementById("lautbalken").style.width = (z.laut / 127 * 100) + "%";
      document.getElementById("lernlaut").classList.toggle("an", z.lernen === "laut");
      const stopp = document.getElementById("stopp");
      if (stopp.hidden !== !z.lernen) stopp.hidden = !z.lernen;
      z.achsen.forEach((a, i) => {
        const karte = karten.children[i];
        setzen(karte.querySelector(".cc"), i === 0 ? "Mitte 64, jetzt " + a.wert : "CC " + a.cc + " = " + a.wert);
        karte.querySelector(".balken div").style.width = (a.wert / 127 * 100) + "%";
        const knopf = karte.querySelector(".lern");
        if (knopf) knopf.classList.toggle("an", z.lernen === String(i));
      });
    } catch (e) {}
    setTimeout(tick, 50);
  }
  tick();
</script></body></html>
"""


def als_cc(g):
    return max(0, min(127, round((g + 1.0) * 63.5)))


def als_bend(g):
    return int(max(-1.0, min(1.0, g)) * 8191)


class Stand:
    def __init__(self):
        self.g = [0.0, 0.0, 0.0]
        self.cc = [0, 0, 0]
        self.an = [True, True, True]
        self.frisch = True
        self.glatt = [0.0, 0.0, 0.0]
        self.vorher = None
        self.tempo = 0.0
        self.letzter = [None, None, None]
        self.letzter_bend = None
        self.ton = False
        self.zuletzt_bewegt = 0.0
        self.letzter_laut = None
        self.lernen = ""
        self.lauf = 0
        self.midi = None
        self.lock = threading.Lock()


def starte_anlernen(stand, control, achse, name):
    with stand.lock:
        if stand.midi is None or stand.lernen == name:
            return
        stand.lauf += 1
        meine = stand.lauf
        stand.lernen = name

    def lauf():
        schritte = (12, 48, 96, 127, 64)
        i = 0
        try:
            while True:
                with stand.lock:
                    if stand.lauf != meine:
                        return
                wert = schritte[i % len(schritte)]
                i += 1
                stand.midi.send(mido.Message("control_change", channel=KANAL, control=control, value=wert))
                with stand.lock:
                    if stand.lauf != meine:
                        return
                    if achse is None:
                        stand.letzter_laut = wert
                    else:
                        stand.cc[achse] = wert
                        stand.letzter[achse] = wert
                time.sleep(0.12)
        finally:
            with stand.lock:
                if stand.lauf == meine:
                    stand.lernen = ""
    threading.Thread(target=lauf, daemon=True).start()


def oberflaeche(stand):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                self._antwort(SEITE, "text/html; charset=utf-8")
            elif url.path == "/zustand":
                with stand.lock:
                    daten = {"ton": stand.ton, "laut": stand.letzter_laut or 0, "lernen": stand.lernen, "achsen": [
                        {"name": ACHSEN[i], "cc": CCS[i], "wert": stand.cc[i],
                         "g": stand.g[i], "an": stand.an[i]} for i in range(3)]}
                self._antwort(json.dumps(daten), "application/json")
            elif url.path == "/um":
                i = int(parse_qs(url.query).get("i", ["0"])[0])
                with stand.lock:
                    if 0 <= i < 3:
                        stand.an[i] = not stand.an[i]
                self._antwort("ok", "text/plain")
            elif url.path == "/nur":
                i = int(parse_qs(url.query).get("i", ["0"])[0])
                with stand.lock:
                    stand.an = [n == i for n in range(3)]
                self._antwort("ok", "text/plain")
            elif url.path == "/stopp":
                with stand.lock:
                    stand.lauf += 1
                    stand.lernen = ""
                self._antwort("ok", "text/plain")
            elif url.path == "/lernen":
                was = parse_qs(url.query).get("was", [""])[0]
                if was == "laut":
                    starte_anlernen(stand, 7, None, "laut")
                elif was in ("0", "1", "2"):
                    i = int(was)
                    starte_anlernen(stand, CCS[i], i, was)
                self._antwort("ok", "text/plain")
            elif url.path == "/alle":
                with stand.lock:
                    stand.an = [True, True, True]
                self._antwort("ok", "text/plain")
            else:
                self.send_error(404)

        def _antwort(self, text, typ):
            daten = text.encode()
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    adresse = f"http://127.0.0.1:{SEITE_PORT}"
    print(f"Oberfläche: {adresse}")
    webbrowser.open(adresse)
    return adresse


def main():
    ap = argparse.ArgumentParser(description="Beschleunigungssensor als MIDI-CC")
    ap.add_argument("--serial", help="USB-Port des Joy-IT, sonst kommt die Messung über WLAN")
    ap.add_argument("--name", default="Beschleunigung", help="Name des MIDI-Ports")
    args = ap.parse_args()

    stand = Stand()
    oberflaeche(stand)

    if args.serial:
        quelle = serial.Serial(args.serial, 115200, timeout=1)
        time.sleep(2)  # Board startet nach dem Öffnen neu
        quelle.reset_input_buffer()
        def naechste_zeile():
            return quelle.readline()
        print(f"Lese Sensor von {args.serial}")
    else:
        quelle = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        quelle.bind(("0.0.0.0", UDP_PORT))
        quelle.settimeout(1.0)
        def naechste_zeile():
            try:
                daten, _ = quelle.recvfrom(256)
            except socket.timeout:
                return b""
            return daten
        print(f"Warte auf WLAN-Pakete an UDP {UDP_PORT}")

    midi = mido.open_output(args.name, virtual=True)
    stand.midi = midi
    print(f"MIDI-Port „{args.name}“ ist offen. Beenden mit Strg+C.")

    try:
        while True:
            treffer = ZEILE.search(naechste_zeile().decode("ascii", "ignore"))
            if not treffer:
                continue
            werte = [float(treffer.group(i)) for i in (1, 2, 3)]
            with stand.lock:
                if stand.frisch:
                    stand.glatt = werte[:]
                    stand.frisch = False
                else:
                    stand.glatt = [alt + (neu - alt) * GLATT
                                   for alt, neu in zip(stand.glatt, werte)]
                stand.g = stand.glatt
                if stand.vorher is None:
                    tempo_roh = 0.0
                else:
                    tempo_roh = sum((a - b) ** 2 for a, b in zip(stand.glatt, stand.vorher)) ** 0.5
                stand.vorher = stand.glatt[:]
                stand.tempo += (max(0.0, tempo_roh - RAUSCHEN) - stand.tempo) * TEMPO_GLATT
                if not stand.ton and not stand.lernen:
                    stand.ton = True
                    midi.send(mido.Message("note_on", channel=KANAL, note=NOTE, velocity=100))
                if stand.lernen:
                    continue
                for achse, g in enumerate(stand.glatt):
                    cc = als_cc(g)
                    stand.cc[achse] = cc
                    if achse == 0:
                        bend = als_bend(g)
                        if bend != stand.letzter_bend:
                            stand.letzter_bend = bend
                            midi.send(mido.Message("pitchwheel", channel=KANAL, pitch=bend))
                        continue
                    if not stand.an[achse] or cc == stand.letzter[achse]:
                        continue
                    stand.letzter[achse] = cc
                    midi.send(mido.Message("control_change", channel=KANAL,
                                           control=CCS[achse], value=cc))
                laut = max(0, min(127, round(min(stand.tempo / TEMPO_VOLL, 1.0) * 127)))
                if laut != stand.letzter_laut:
                    stand.letzter_laut = laut
                    midi.send(mido.Message("control_change", channel=KANAL, control=7, value=laut))
    except KeyboardInterrupt:
        print()
    finally:
        if stand.ton:
            midi.send(mido.Message("note_off", channel=KANAL, note=NOTE, velocity=0))
        midi.close()
        quelle.close()


if __name__ == "__main__":
    main()
