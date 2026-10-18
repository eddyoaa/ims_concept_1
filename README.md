# Mouthesizer – Nachbau in drei Versionen

Nachbau von Michael Lyons' **Mouthesizer** (2003): Eine Kamera schaut auf den Mund,
die Mundform steuert einen Synthesizer. Dazu zwei Erweiterungen auf das ganze
Gesicht und den ganzen Körper.

| Script | Tracking | Idee |
|---|---|---|
| `01_mouthesizer.py` | Mund (MediaPipe Face Landmarker) | Original: Mundhöhe → Filter-Cutoff, Mundbreite → Resonanz/Verzerrung, Mundöffnung → Lautstärke |
| `02_face.py` | ganzes Gesicht (52 Mimik-Werte + Kopfhaltung) | Nicken spielt Töne, Lächeln, Augenbrauen, Backen, Blinzeln usw. formen den Klang |
| `03_body.py` | ganzer Körper (MediaPipe Pose) | Handhöhen spielen zwei Stimmen, Bewegung macht laut, Stillstand ist Stille (à la *Very Nervous System*) |

Alle drei erzeugen **selbst Klang** (eingebauter Synth in Python) und schicken
**gleichzeitig alle Werte per OSC** raus, z. B. an TouchDesigner oder vvvv.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Beim ersten Start wird das passende MediaPipe-Modell automatisch nach `models/` geladen.

## Starten

```bash
python 01_mouthesizer.py
python 02_face.py
python 03_body.py
```

Optionen (für alle drei gleich):

| Option | Bedeutung |
|---|---|
| `--camera 1` | andere Kamera (oder Pfad zu einer Videodatei) |
| `--no-audio` | kein eigener Sound, nur OSC (Klang kommt dann aus TD/vvvv) |
| `--osc 127.0.0.1:9000` | OSC-Ziel (Standard) |
| `--no-osc` | kein OSC |
| `--audio-device NAME` | anderes Audio-Ausgabegerät |
| `--no-mirror` | Kamerabild nicht spiegeln |
| `--headless` | ohne Fenster (z. B. in der Installation) |

Tasten im Fenster: `q` beenden, `c` Kalibrierung zurücksetzen,
in Version 1 zusätzlich `1`–`8` für den Grundton.

**Kalibrierung:** Die Wertebereiche starten mit Standardwerten und passen sich
automatisch an, wenn jemand weiter geht (Mund weiter auf, Arme weiter auseinander).
Kurz mal alles „ausreizen“, dann sitzt es. Bei einer neuen Person `c` drücken.

## Mappings

### 1 · Mouthesizer
| Geste | Klang |
|---|---|
| Mundhöhe | Cutoff des resonanten Tiefpass („Wah“) |
| Mundbreite | Resonanz + Verzerrung |
| Mundfläche (Innenlippe) | Lautstärke – Mund zu = still |

Der Mund wird rechts oben vergrößert eingeblendet, so wie Lyons' Kopfkamera ihn sah.

### 2 · Gesicht
| Geste | Klang |
|---|---|
| Kopf nicken (hoch/runter) | Tonhöhe (Moll-Pentatonik, 2 Oktaven) |
| Kopf drehen | Panorama links/rechts |
| Kopf neigen | Verstimmung / Chorus |
| Kiefer öffnen | Lautstärke + Cutoff |
| Lächeln | Resonanz + Quinte kommt dazu |
| Augenbrauen hoch | Vibrato |
| Backen aufblasen | Verzerrung |
| Kussmund | Pulse-Welle (hohler Klang) |
| Augen weit auf | Delay-Feedback |
| Blinzeln | Pluck eine Oktave höher |

### 3 · Körper
| Geste | Klang |
|---|---|
| linke / rechte Hand hoch | Ton von Stimme 1 / Stimme 2 |
| Hände auseinander | Cutoff (Arme auf = hell) |
| Bewegungsenergie | Lautstärke (stillstehen = leise) |
| Position links/rechts | Panorama |
| in die Hocke | Sub-Bass + Verzerrung |
| beide Hände über den Kopf | großer Delay-Raum |
| schneller Handschlag | Pluck |

## OSC-Adressen (für TouchDesigner / vvvv)

Alle Werte sind Floats, die meisten 0..1. In TouchDesigner einfach ein
**OSC In CHOP** auf Port `9000` anlegen, die Kanäle heißen dann wie die Adressen.

- **Mund:** `/mouth/present`, `/mouth/height`, `/mouth/width`, `/mouth/area`
- **Gesicht:** `/face/present`, `/face/jaw`, `/face/smile`, `/face/brows`, `/face/puff`,
  `/face/pucker`, `/face/eyewide`, `/face/nod`, `/face/turn`, `/face/tilt`,
  `/face/blink` (1 im Moment des Blinzelns), `/face/note_hz`,
  `/face/pitch_deg`, `/face/yaw_deg`, `/face/roll_deg`
- **Körper:** `/body/present`, `/body/left`, `/body/right`, `/body/spread`,
  `/body/energy`, `/body/center`, `/body/crouch`, `/body/space`,
  `/body/hit_l`, `/body/hit_r`, `/body/note1_hz`, `/body/note2_hz`

Mit `--no-audio` wird Python zum reinen Sensor und der Klang (oder Visuals)
entsteht komplett in TD/vvvv.

## Aufbau

```
mouthesizer/synth.py    Synth: Saw/Pulse-Oszillatoren + Sub → resonanter Tiefpass
                        → tanh-Drive → Plucks → Feedback-Delay → Stereo
mouthesizer/common.py   Kamera-Schleife, Modell-Download, OSC, HUD, Mapping-Helfer
01_mouthesizer.py       Version Mund
02_face.py              Version Gesicht
03_body.py              Version Körper
```

Eigene Mappings: In jedem Script steht in `process()` ein `synth.set(...)`-Block,
dort lässt sich jede Geste auf jeden Parameter legen. Verfügbare Parameter stehen
oben in `Synth.DEFAULTS`.

## Referenz

Michael J. Lyons, Michael Haehnel, Nobuji Tetsutani: *Designing, Playing, and
Performing with a Vision-based Mouth Interface*, NIME 2003.
