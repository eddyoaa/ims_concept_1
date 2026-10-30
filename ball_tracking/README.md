# Prototyp: Ball-Tracking per Kamera

Eine Webcam verfolgt **zwei** geworfene Bälle in Echtzeit, jeweils über ihre Farbe (Standard: Ball 1 Grün, Ball 2 Pink). Position, Größe und Geschwindigkeit jedes Balls kommen pro Frame in einer Funktion an, aus der sich Sounds auslösen lassen.

Die Bälle brauchen **verschiedene Farben**. Dadurch bleibt Ball 1 immer Ball 1, auch wenn sich die Bälle kreuzen. Mit `--balls 1` läuft alles wie früher mit nur einem Ball.

| Datei | Inhalt |
|---|---|
| `color_ball_tracking.py` | **Hauptscript:** Ball-Tracking über die Farbe, ohne Training, ohne GPU, mit Klang |
| `ball_sound.py` | Klang: eine Stimme pro Ball. Richtung → Ton, Geschwindigkeit → Lautstärke, Höhe → Filter |
| `multicam_ball_tracking.py` | zwei Kameras (vorne + seitlich): Tiefe (z) und Ausfallsicherheit, wenn ein Ball in einer Kamera verdeckt ist |
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

1. Beide Bälle in die Kamera halten. **Linksklick auf Ball 1**, **Rechtsklick auf Ball 2**. Damit wird jeweils genau die Farbe übernommen. (Alternativ: mit `b` den aktiven Ball wechseln, Linksklick gilt immer für den aktiven Ball. Er ist im Fenster umrandet.)
2. Mit **`m`** das Masken-Fenster öffnen. Es zeigt die Maske des aktiven Balls: Weiß ist alles, was als dieser Ball gilt. Die Regler so einstellen, dass möglichst nur der Ball weiß ist. Mit `b` zum anderen Ball wechseln. Abgelehnte Flecken stehen grau im Bild, mit Grund („corners“ = eckig, „ragged“ = ausgefranst, „stretched“ = zu lang).
3. Mit **`s`** speichern. Die Einstellung beider Bälle landet in `color_settings.json` und wird beim nächsten Start automatisch geladen. Eine alte Datei mit nur einem Ball wird für Ball 1 übernommen.

Überschneiden sich die Farbbereiche der beiden Bälle, steht im Terminal eine Warnung. Dann können beide Tracker denselben Ball verfolgen.

## Klang

Beim Start spielt das Script direkt Ton über die Lautsprecher:

Jeder Ball hat seine eigene Stimme, beide klingen gleichzeitig.

| Ball | Ball 1 | Ball 2 |
|---|---|---|
| fliegt nach **rechts** (x wird größer) | Ton **G** (392 Hz) | Ton **D** (587 Hz) |
| fliegt nach **links** (x wird kleiner) | Ton **A** (440 Hz) | Ton **E** (659 Hz) |

| Ball | Klang |
|---|---|
| Geschwindigkeit | Lautstärke: ruhender Ball ist still, ab 1500 px/s volle Lautstärke |
| Höhe im Bild (y) | Filter: oben hell, unten dumpf |

Es gibt pro Ball nur diese zwei Töne, kein Gleiten dazwischen. Oben im Fenster steht pro Ball ein Feld mit x, y, vx, vy, Geschwindigkeit, dem aktuellen Ton, der Lautstärke und der Filterfrequenz.

„Rechts“ heißt rechts im Kamerabild. Mit `--mirror` wird das Bild gespiegelt wie ein Spiegel, dann ist rechts auf dem Bildschirm auch deine rechte Seite.

## Tasten

| Taste | Funktion |
|---|---|
| `1` / `2` / `3` | Version umschalten (auch per Regler oben im Fenster) |
| `b` / `Tab` | aktiven Ball wechseln (für Klick, Regler und `r`) |
| Linksklick auf einen Ball | Farbe für den aktiven Ball übernehmen |
| Rechtsklick auf einen Ball | Farbe für Ball 2 übernehmen |
| `m` | Maske (aktiver Ball), Regler und Debug-Ansicht ein/aus |
| `s` | Farbeinstellung beider Bälle speichern |
| `r` | aktiven Ball auf seine Standardfarbe zurücksetzen |
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
| Grün | Ball sichtbar (die Zahl daneben sagt, welcher Ball) |
| Cyan | Ball teilweise verdeckt, Mitte aus dem sichtbaren Rand berechnet |
| Rot | Ball kurz nicht sichtbar, Position aus der Flugbahn vorhergesagt |
| Orange | Ball verschwunden, vermutlich in der Hand |

## Optionen

| Option | Bedeutung |
|---|---|
| `--source 1` | Kamera-Nummer oder Pfad zu einer Videodatei |
| `--balls 2` | Anzahl Bälle (1 oder 2) |
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

In `color_ball_tracking.py` steht oben die Funktion `on_ball()`. Sie wird pro Frame und Ball aufgerufen, solange der Ball verfolgt wird, mit der Ball-Nummer `ball` (0 = Ball 1, 1 = Ball 2), Position `x, y`, Radius (größer = näher an der Kamera), Geschwindigkeit `vx, vy` in Pixel pro Sekunde und `detected` (gesehen oder nur vorhergesagt). Dort lassen sich z. B. OSC-Nachrichten verschicken oder Töne auslösen. Wechselt `vy` das Vorzeichen, hat der Ball den höchsten Punkt erreicht oder ist aufgeprallt.

## Tipps

- **Licht ist der größte Hebel.** Im Dunkeln belichtet die Kamera länger: Der Ball verschmiert, die Bildrate sinkt, schnelle Würfe werden später erkannt.
- **Knallige Ballfarbe**, die sonst nirgends im Raum vorkommt (Neongrün, Pink, Orange).
- Mit `--save test.mp4` aufnehmen und danach in Ruhe mit `--source test.mp4` und verschiedenen Versionen vergleichen.
- Klang an einer Videodatei testen: `python color_ball_tracking.py --source test.mp4 --save out.mp4 --audio-out out.wav`, dann beides zusammenlegen mit `ffmpeg -i out.mp4 -i out.wav -c:v libx264 -c:a aac -shortest demo.mp4`.

## Zwei Kameras: Tiefe und Verdeckung

`multicam_ball_tracking.py` nimmt eine zweite Kamera dazu, die von der **Seite** auf die Szene schaut, ungefähr im rechten Winkel zur vorderen:

| Kamera | liefert |
|---|---|
| vorne (`--source`) | x (links/rechts) und y (Höhe) |
| seitlich (`--side`) | z (Tiefe: nah/fern von der vorderen Kamera) und y |

```bash
python camera_check.py                                      # beide Kamera-Nummern finden
python multicam_ball_tracking.py --source 0 --side 1
```

**Einrichten:**

1. Beide Kameras so aufstellen, dass sie den ganzen Wurfbereich sehen. Die Seitenkamera möglichst im rechten Winkel zur vorderen.
2. Im Fenster (links vorne, rechts seitlich) jeden Ball **in beiden Bildern** anklicken: Linksklick = aktiver Ball, Rechtsklick = Ball 2. Jede Kamera hat ihre eigenen Farbeinstellungen, weil Licht und Weißabgleich verschieden sind.
3. Die Bälle ein paar Sekunden **auf und ab** bewegen. Dabei gleicht das Script die Höhe der beiden Kameras automatisch ab. Fertig ist es, wenn unten „y sync: ok“ steht. Eine Kalibrierung mit Schachbrett ist nicht nötig.
4. Ball auf die vordere Kamera zu bewegen: z sollte kleiner werden. Wird es größer, mit `--side-flip` neu starten.
5. `s` speichert die Farben: vorne in `color_settings.json`, seitlich in `color_settings_side.json`.

**Was passiert bei Verdeckung:** Verliert eine Kamera einen Ball (z. B. Hand davor), übernimmt die andere. Die Höhe läuft dann weiter mit, der Ton auch. Nur die Koordinate, die allein die verdeckte Kamera misst (x oder z), wird auf dem letzten Wert gehalten. Im Feld „seen by“ steht, welche Kamera den Ball gerade sieht.

**Anzeige:** unten pro Ball x, y, z (jeweils 0 bis 1) und die Klangwerte, rechts eine **Draufsicht** (x/z) mit beiden Bällen.

**Klang:** wie beim Script mit einer Kamera. Die Lautstärke rechnet jetzt auch die Bewegung in die Tiefe mit. Ein Ball, der direkt auf die vordere Kamera zufliegt, bleibt also nicht mehr stumm. Wofür z sonst klingen soll, kann man in `on_ball_3d()` (oben im Script) selbst einbauen.

**Tasten:** wie oben, zusätzlich `c` = aktive Kamera wechseln (für Maske, Regler und `r`).

**Optionen:** dieselben wie oben, dazu:

| Option | Bedeutung |
|---|---|
| `--side 1` | Seitenkamera (Nummer oder Videodatei) |
| `--side-flip` | Tiefenrichtung umdrehen |
| `--side-mirror` | Bild der Seitenkamera spiegeln |

**Grenzen:** Perspektive wird ignoriert. Die Werte sind „grobes 3D“: gut zum Steuern von Klang, nicht zum Messen. Die Kameras nehmen nicht exakt gleichzeitig auf; das Script verschiebt jede Position entlang der Flugbahn auf denselben Zeitpunkt. Bei zwei Webcams an einem USB-Anschluss kann die Bildrate sinken. Dann die Kameras an verschiedene Anschlüsse stecken.

## YOLO-Variante

`realtime_ball_tracking.py` erkennt Sportbälle mit einem vortrainierten KI-Modell statt über die Farbe. Dafür zusätzlich `pip install ultralytics`, dann:

```bash
python realtime_ball_tracking.py --source 1
```

Das Modell wird beim ersten Start automatisch geladen. Es ist allgemein trainiert („sports ball“) und erkennt einfarbige Bälle schlechter als der Farbtracker.
