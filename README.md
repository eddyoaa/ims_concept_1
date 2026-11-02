# Ball als Instrument

Geworfene Bälle machen Klang. Eine oder zwei Kameras verfolgen zwei farbige Bälle in Echtzeit. Flugrichtung, Geschwindigkeit, Höhe und Tiefe steuern einen Synthesizer.

| Ordner | Inhalt |
|---|---|
| [`ball_tracking/`](ball_tracking/README.md) | **Hauptprojekt:** Ball-Tracking per Kamera mit Klang |
| [`beschleunigung/`](beschleunigung/) | Prototyp: Ball mit Beschleunigungssensor (ESP8266, WLAN), Neigung und Bewegung als MIDI |
| [`schwamm/`](schwamm/README.md) | Prototyp: nasser Schwamm als Sensor und Klangquelle |

## Schnellstart

```bash
cd ball_tracking
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python camera_check.py                                     # Kamera-Nummern finden
python color_ball_tracking.py --source 0                   # eine Kamera
python multicam_ball_tracking.py --source 0 --side 1       # zwei Kameras (Tiefe)
python sync_videos.py aufnahmen/take1                       # Videos mehrerer Geräte synchronisieren
```

Beim nächsten Mal reichen `cd ball_tracking` und `source .venv/bin/activate`. Steht `(.venv)` vor der Eingabezeile, ist alles bereit.

Im Fenster jeden Ball einmal anklicken (Linksklick = Ball 1, Rechtsklick = Ball 2), damit seine Farbe übernommen wird, dann mit `s` speichern. Die ausführliche Anleitung steht in [`ball_tracking/README.md`](ball_tracking/README.md).

## Was es kann

- **Zwei Bälle** in verschiedenen Farben (Standard: Grün und Pink). Die Farbe sagt, welcher Ball welcher ist, auch wenn sie sich kreuzen.
- **Verdeckung:** Ist ein Ball teilweise von der Hand verdeckt, stimmen Mitte und Größe trotzdem. Verschwindet er kurz, wird seine Position aus der Flugbahn vorhergesagt.
- **Zwei Kameras** (optional): Eine vorne, eine seitlich, z. B. Mac und iPhone. Die zweite liefert die Tiefe und übernimmt, wenn ein Ball in der ersten verdeckt ist. Die Höhe beider Kameras wird automatisch abgeglichen.
- **Klang:** Jeder Ball hat eine eigene Stimme.

| Ball | Klang |
|---|---|
| fliegt nach rechts / links | Ball 1: G / A, Ball 2: D / E |
| Geschwindigkeit | Lautstärke (ruhender Ball ist still) |
| Höhe im Bild | Filter (oben hell, unten dumpf) |

Eigene Klang- oder OSC-Logik lässt sich in `on_ball()` (eine Kamera) bzw. `on_ball_3d()` (zwei Kameras) einbauen.

## Dateien in `ball_tracking/`

| Datei | Inhalt |
|---|---|
| `color_ball_tracking.py` | Tracking über die Farbe mit einer Kamera, mit Klang |
| `multicam_ball_tracking.py` | dasselbe mit zwei Kameras: x, y und z (Tiefe) |
| `ball_sound.py` | Klang: eine Stimme pro Ball |
| `camera_check.py` | findet heraus, welche Kamera-Nummern ein Bild liefern |
| `realtime_ball_tracking.py` | Alternative mit YOLO (KI-Modell), ein Ball, langsamer |
