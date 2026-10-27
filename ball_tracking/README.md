# Prototyp: Ball-Tracking per Kamera

Eine Webcam verfolgt einen geworfenen Ball in Echtzeit, über seine Farbe (Standard: Grün). Position, Größe und Geschwindigkeit des Balls kommen pro Frame in einer Funktion an, aus der sich später Sounds auslösen lassen.

| Datei | Inhalt |
|---|---|
| `color_ball_tracking.py` | **Hauptscript:** Ball-Tracking über die Farbe, ohne Training, ohne GPU, mit Klang |
| `ball_sound.py` | Klang: Richtung → Ton (G/A), Geschwindigkeit → Lautstärke, Höhe → Filter |
| `camera_check.py` | findet heraus, welche Kamera-Nummer ein echtes Bild liefert |
| `realtime_ball_tracking.py` | Alternative mit YOLO (KI-Modell), langsamer, erkennt beliebige Sportbälle |

---

## 1. Einrichten (einmalig)

Im Ordner `ball_tracking`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Beim nächsten Mal reicht `source .venv/bin/activate`.

## 2. Kamera finden

```bash
python camera_check.py
```

Das Script testet die Kameras 0 bis 4 und gibt am Ende die passende Nummer aus, z. B. `--source 1`. Liefert keine Kamera ein Bild, braucht das Terminal Kamerazugriff: **Systemeinstellungen → Datenschutz & Sicherheit → Kamera → Terminal erlauben**, dann das Terminal mit Cmd+Q beenden und neu öffnen.

## 3. Starten

```bash
python color_ball_tracking.py --source 1
```

(Die `1` durch die Nummer aus Schritt 2 ersetzen.)

**Beim ersten Start kalibrieren:**

1. Ball in die Kamera halten und **im Fenster auf den Ball klicken**. Damit wird genau seine Farbe übernommen.
2. Mit **`m`** das Masken-Fenster öffnen: Weiß ist alles, was als Ball gilt. Die Regler so einstellen, dass möglichst nur der Ball weiß ist. Abgelehnte Flecken stehen grau im Bild, mit Grund („corners“ = eckig, „ragged“ = ausgefranst, „stretched“ = zu lang).
3. Mit **`s`** speichern. Die Einstellung landet in `color_settings.json` und wird beim nächsten Start automatisch geladen.

## Klang

Beim Start spielt das Script direkt Ton über die Lautsprecher:

| Ball | Klang |
|---|---|
| fliegt nach **rechts** (x wird größer) | Ton **G** (392 Hz) |
| fliegt nach **links** (x wird kleiner) | Ton **A** (440 Hz) |
| Geschwindigkeit | Lautstärke: ruhender Ball ist still, ab 1500 px/s volle Lautstärke |
| Höhe im Bild (y) | Filter: oben hell, unten dumpf |

Es gibt nur diese zwei Töne, kein Gleiten dazwischen. Links oben im Fenster stehen x, y, vx, vy, Geschwindigkeit, der aktuelle Ton, die Lautstärke und die Filterfrequenz als Zahlen.

„Rechts“ heißt rechts im Kamerabild. Mit `--mirror` wird das Bild gespiegelt wie ein Spiegel, dann ist rechts auf dem Bildschirm auch deine rechte Seite.

## Tasten

| Taste | Funktion |
|---|---|
| `1` / `2` / `3` | Version umschalten (auch per Regler oben im Fenster) |
| Klick auf den Ball | Farbe übernehmen |
| `m` | Maske, Regler und Debug-Ansicht ein/aus |
| `s` | Farbeinstellung speichern |
| `r` | zurück auf Standard-Grün |
| `q` / `Esc` | beenden |

## Versionen

| Version | Was sie kann |
|---|---|
| **v1** | nur Farbe: jeder runde grüne Fleck zählt |
| **v2** | + Formfilter: ignoriert gleichfarbige Dinge mit Ecken (Poster, Kartons, Klebeband) oder ausgefranstem Umriss (Pflanzen, Kleidung). Schnelle, verschmierte Bälle und Bälle, die am Bildrand reinfliegen, werden trotzdem erkannt. |
| **v3** | + Hand: Ist der Ball teilweise von der Hand verdeckt, wird ein Kreis an den sichtbaren Rand gelegt, so stimmen Mitte und Größe trotzdem. Verschwindet der Ball ganz in der Hand, wird seine Position bis zu 2 s gehalten. |

Standard ist v3. Mit `--version 2` startet eine andere.

## Farben der Markierung

| Farbe | Bedeutung |
|---|---|
| Grün | Ball sichtbar |
| Cyan | Ball teilweise verdeckt, Mitte aus dem sichtbaren Rand berechnet |
| Rot | Ball kurz nicht sichtbar, Position aus der Flugbahn vorhergesagt |
| Orange | Ball verschwunden, vermutlich in der Hand |

## Optionen

| Option | Bedeutung |
|---|---|
| `--source 1` | Kamera-Nummer oder Pfad zu einer Videodatei |
| `--version 3` | Start-Version (1, 2 oder 3) |
| `--strictness 0.7` | wie streng die Formprüfung ist (0..1). Höher = weniger Fehlalarme, aber verdeckte/verschmierte Bälle gehen eher verloren. Auch als Regler im Masken-Fenster. |
| `--hold-seconds 2` | wie lange ein Ball in der Hand gehalten wird |
| `--save out.mp4` | Ergebnis zusätzlich als Video speichern |
| `--mirror` | Bild spiegeln (Selfie-Ansicht) |
| `--max-speed 1500` | Geschwindigkeit in px/s für volle Lautstärke |
| `--no-audio` | ohne Ton |
| `--audio-device NAME` | anderes Audio-Ausgabegerät |
| `--audio-out test.wav` | Ton nicht abspielen, sondern synchron zum Video als WAV speichern (zum Testen mit Videodateien) |

## Eigene Logik einbauen

In `color_ball_tracking.py` steht oben die Funktion `on_ball()`. Sie wird pro Frame aufgerufen, solange ein Ball verfolgt wird, mit Position `x, y`, Radius (größer = näher an der Kamera), Geschwindigkeit `vx, vy` in Pixel pro Sekunde und `detected` (gesehen oder nur vorhergesagt). Dort lassen sich z. B. OSC-Nachrichten verschicken oder Töne auslösen. Wechselt `vy` das Vorzeichen, hat der Ball den höchsten Punkt erreicht oder ist aufgeprallt.

## Tipps

- **Licht ist der größte Hebel.** Im Dunkeln belichtet die Kamera länger: Der Ball verschmiert, die Bildrate sinkt, schnelle Würfe werden später erkannt.
- **Knallige Ballfarbe**, die sonst nirgends im Raum vorkommt (Neongrün, Pink, Orange).
- Mit `--save test.mp4` aufnehmen und danach in Ruhe mit `--source test.mp4` und verschiedenen Versionen vergleichen.
- Klang an einer Videodatei testen: `python color_ball_tracking.py --source test.mp4 --save out.mp4 --audio-out out.wav`, dann beides zusammenlegen mit `ffmpeg -i out.mp4 -i out.wav -c:v libx264 -c:a aac -shortest demo.mp4`.

## YOLO-Variante

`realtime_ball_tracking.py` erkennt Sportbälle mit einem vortrainierten KI-Modell statt über die Farbe. Dafür zusätzlich `pip install ultralytics`, dann:

```bash
python realtime_ball_tracking.py --source 1
```

Das Modell wird beim ersten Start automatisch geladen. Es ist allgemein trainiert („sports ball“) und erkennt einfarbige Bälle schlechter als der Farbtracker.
