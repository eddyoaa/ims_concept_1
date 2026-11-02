# Prototyp: Ball-Tracking per Kamera

Eine Webcam verfolgt **zwei** geworfene Bälle in Echtzeit, jeweils über ihre Farbe (Standard: Ball 1 Grün, Ball 2 Pink). Position, Größe und Geschwindigkeit jedes Balls kommen pro Frame in einer Funktion an, aus der sich Sounds auslösen lassen.

Die Bälle brauchen **verschiedene Farben**. Dadurch bleibt Ball 1 immer Ball 1, auch wenn sich die Bälle kreuzen. Mit `--balls 1` läuft alles wie früher mit nur einem Ball.

| Datei | Inhalt |
|---|---|
| `color_ball_tracking.py` | **Hauptscript:** Ball-Tracking über die Farbe, ohne Training, ohne GPU, mit Klang |
| `ball_sound.py` | Klang: eine Stimme pro Ball. Richtung → Ton, Geschwindigkeit → Lautstärke, Höhe → Filter |
| `multicam_ball_tracking.py` | zwei Kameras (vorne + seitlich): Tiefe (z) und Ausfallsicherheit, wenn ein Ball in einer Kamera verdeckt ist |
| `camera_check.py` | findet heraus, welche Kamera-Nummer ein echtes Bild liefert |
| `sync_videos.py` | synchronisiert Aufnahmen mehrerer Kameras (z. B. Mac + 2 iPhones) über den Ton |
| `make_midi.py` | MIDI-Cues zum Video aus der Auswertung (Würfe als Noten, x/y/z/Tempo als CC) |
| `analyze_videos.py` | wertet synchronisierte Videos aus: Datensatz mit der Ballposition im Raum (x, y, z) pro Bild |
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

## Mit mehreren Geräten aufnehmen und synchronisieren

Statt live kann man auch mit mehreren Geräten getrennt aufnehmen (z. B. Mac vorne, ein iPhone seitlich, eins an der Decke) und die Videos danach mit `sync_videos.py` zeitlich übereinanderlegen.

**Aufnehmen:**

1. iPhones: gleiche Bildrate (am besten 60 fps), **HDR-Video aus** (Einstellungen → Kamera → Video aufnehmen), Belichtung und Fokus sperren (lange aufs Bild tippen, „AE/AF-Sperre“), Stabilisierung „Erweitert“ und Action-Modus aus. Fest montieren.
2. Mac: QuickTime → Ablage → Neue Videoaufnahme, **mit Mikrofon**.
3. Alle Aufnahmen starten, dann **einmal laut klatschen**, so dass alle Kameras die Hände sehen. Noch besser: einen Ball auf den Boden fallen lassen. Am Ende noch einmal klatschen.

**Synchronisieren:** Alle Videos einer Aufnahme in einen eigenen Ordner legen, z. B. `aufnahmen/take1/`. Die Dateinamen werden zu den Namen der Ausgaben, also am besten gleich sprechend benennen (`mac.mov`, `iphone_seite.mov`, `iphone_decke.mov`). Dann:

```bash
python sync_videos.py aufnahmen/take1
```

Das Script sucht das Klatschen in allen Tonspuren, schneidet alle Videos auf den gemeinsamen Teil und schreibt sie mit gleichem Start, gleicher Länge und gleicher Bildrate (60 fps) nach `aufnahmen/take1/synced/`:

| Datei | Inhalt |
|---|---|
| `mac.mp4`, `iphone_seite.mp4`, ... | die synchronisierten Videos: Bild Nr. N ist in allen derselbe Moment |
| `preview.mp4` | alle Kameras nebeneinander, zum Prüfen |
| `offsets.json` | die gefundenen Zeitversätze |

Im Terminal steht pro Video der Versatz und eine „confidence“. Steht dort `UNSURE`, wurde kein gemeinsames Geräusch gefunden: lauter klatschen oder `--window` erhöhen. Hat man am Ende auch geklatscht, prüft das Script dort, ob die Videos über die Zeit auseinanderlaufen.

**Prüfen:** `preview.mp4` öffnen und Bild für Bild durch das Klatschen gehen (in QuickTime mit den Pfeiltasten). Die Hände sollten in allen Bildern im selben Bild zusammenkommen. Ist eine Kamera ein Bild daneben, mit `--shift` korrigieren (ein Bild bei 60 fps = 0.0167 s). Positiv = die Kamera zeigt alles ein Bild später:

```bash
python sync_videos.py aufnahmen/take1 --shift iphone_decke.mov=0.0167
```

Danach lassen sich die Videos direkt auswerten, z. B.:

```bash
python multicam_ball_tracking.py --source aufnahmen/take1/synced/mac.mp4 --side aufnahmen/take1/synced/iphone_seite.mp4
```

| Option | Bedeutung |
|---|---|
| `--fps 60` | Bildrate der Ausgaben |
| `--ref mac.mov` | Referenzvideo (Standard: erstes nach Name) |
| `--window 60` | so viele Sekunden am Anfang jedes Videos werden nach dem Klatschen durchsucht. Erhöhen, wenn die Kameras weit auseinander gestartet wurden. |
| `--shift DATEI=SEKUNDEN` | Versatz einer Kamera von Hand korrigieren (mehrfach möglich) |
| `--only-offsets` | nur Versätze bestimmen, keine Videos schreiben |
| `--no-preview` | kein `preview.mp4` |

Braucht `ffmpeg` (Mac: `brew install ffmpeg`).

**Grenzen:** Eine Kamera mit 30 fps (z. B. die Mac-Kamera) liefert jedes Bild doppelt. Ihr Bild ist bis zu einem halben 30-fps-Bild (17 ms) ungenau, mehr gibt die Kamera nicht her.

## Datensatz: Ballposition im Raum aus mehreren Videos

`analyze_videos.py` nimmt synchronisierte Videos (gleicher Start, gleiche Bildrate, z. B. aus `sync_videos.py` oder sauber geschnitten) und berechnet für jedes Bild, wo der Ball im Raum ist.

**Kameras:** `--front` ist Pflicht, dazu mindestens eine weitere (`--side` und/oder `--top`). Die Winkel müssen nicht stimmen: Das Script findet selbst heraus, wie die Kameras zueinander stehen. Der Ball ist das Kalibrierobjekt.

**1. Farben wählen (einmal pro Aufnahme):**

```bash
python analyze_videos.py "../Video cutting" --front "Video vorne.mp4" --side "Video Seite.mp4" --top "video oben.mp4" --balls 1 --setup
```

Pro Kamera öffnet sich ein Fenster. Mit dem Regler „Frame“ zu einem Bild gehen, in dem der Ball gut zu sehen ist, und den Ball anklicken (Linksklick = Ball 1, Rechtsklick = Ball 2). Die Kreise zeigen, was erkannt wird. `m` öffnet die Maske mit Reglern, `n` speichert und geht zur nächsten Kamera.

**2. Auswerten:**

```bash
python analyze_videos.py "../Video cutting" --balls 1 --ball-diameter 0.2 --video
```

Die Kameras aus Schritt 1 werden gemerkt. `--ball-diameter` ist der Balldurchmesser in Metern (nachmessen!). Dann ist der Datensatz in Metern, sonst in Ballradien. `--video` schreibt zusätzlich `check_<kamera>.mp4` mit den erkannten Bällen zum Kontrollieren.

**Ergebnis** im Unterordner `analysis/`:

| Datei | Inhalt |
|---|---|
| `balls_3d.csv` | **der Datensatz:** `frame, time_s, ball, x, y, z, vx, vy, vz, seen_by` |
| `tracks_2d.csv` | Rohdaten pro Kamera in Pixeln (Position, Radius, Breite, Status) |
| `mapping.json` | wie die Kameras gefunden wurden und wie gut sie zusammenpassen |
| `ignored_<kamera>.png` | Stellen mit Ballfarbe, die sich nie bewegen (Sticker, Klebeband), werden ignoriert |

**Koordinaten:** x = links → rechts aus Sicht der vorderen Kamera, y = Höhe (nach oben), z = Tiefe (weg von der vorderen Kamera). Der kleinste Wert der Aufnahme ist jeweils 0. `vx, vy, vz` sind Geschwindigkeiten pro Sekunde. Eine Zeile gibt es nur, wenn mindestens zwei Kameras den Ball sehen.

**Im Terminal prüfen:** Unter „Cameras as found“ steht, in welchem Winkel jede Kamera zur vorderen steht und wie gut sie passt (`error` in Ballradien, unter 0.5 ist gut). Passt eine Kamera nicht zur vorderen, wird sie für 3D weggelassen und das wird gemeldet.

**So funktioniert es:** Ein Ball, der doppelt so weit weg ist, sieht halb so groß aus und bewegt sich im Bild halb so weit. Teilt man den Abstand zur Bildmitte durch die Ballgröße, ist die Perspektive herausgerechnet. Dann findet das Script aus allen Bildern, in denen mehrere Kameras den Ball sehen, wo jede Kamera steht (affine „Structure from Motion“). Im Test mit künstlichen Würfen liegt das Ergebnis 2–3 cm neben der echten Flugbahn.

**Aufnahme-Tipps für gute Daten:**
- **Normales Objektiv (1x)**, nicht Ultraweitwinkel (0.5x). Am Bildrand verbiegt das Weitwinkel die Geometrie.
- Der Ball sollte möglichst die **ganze Flugbahn** im Bild bleiben, auch oben. Ein Ball, der aus dem Bild fliegt oder am Rand angeschnitten ist, liefert falsche Werte.
- Die Kameras sollten **möglichst verschiedene Richtungen** haben (z. B. 90° zueinander), dann ist die Tiefe genauer.
- **Hohe Bildrate** (60 fps) und viel Licht gegen Bewegungsunschärfe.

| Option | Bedeutung |
|---|---|
| `--front / --side / --top DATEI` | Videos der Kameras (Dateiname im Ordner) |
| `--setup` | Farben wählen |
| `--balls 1` | Anzahl Bälle (1 oder 2) |
| `--ball-diameter 0.2` | Balldurchmesser in Metern → Datensatz in Metern |
| `--video` | Kontrollvideos mit erkannten Bällen schreiben |
| `--start 5 --end 20` | nur diesen Abschnitt (Sekunden) auswerten |
| `--min-radius 4` | kleinere Flecken ignorieren (für sehr kleine Bälle senken) |
| `--keep-static` | Stellen mit Ballfarbe, die sich nie bewegen, nicht ausblenden |
| `--no-perspective` | ohne Perspektivkorrektur (wenn die Ballgröße schlecht gemessen wird) |

## MIDI-Cues zum Video

Aus der Auswertung von `analyze_videos.py` macht `make_midi.py` eine MIDI-Datei, die genau zum Video passt:

```bash
python make_midi.py "../Video cutting"
```

Ergebnis in `analysis/`: `ball_cues.mid` und `cues.csv` (dieselben Cues als Liste mit Zeit und Bildnummer).

**In der DAW:** Projekt auf **120 BPM** stellen, die MIDI-Datei an Takt 1 legen, das Video bei 0:00. Dann sitzt jeder Cue auf dem richtigen Bild.

Alles auf MIDI-Kanal 1, mit denselben CCs wie `beschleunigung/midi.py`:

| MIDI | Bedeutung |
|---|---|
| Note C3 (48) | Wurf: an, wenn der Ball die Hand verlässt, aus beim Fangen. Anschlagstärke = wie schnell der Wurf ist |
| Note D3 (50) | kurz am höchsten Punkt |
| Note E3 (52) | kurz beim Fangen |
| CC 16 | x (links → rechts aus Sicht der vorderen Kamera) |
| CC 17 | Höhe (oben = 127) |
| CC 18 | Tiefe (weg von der vorderen Kamera = 127) |
| CC 7 | Geschwindigkeit des Balls (ruhig = 0) |
| Marker | „Wurf 1“, „Wurf 2“, … in der Zeitleiste |

Ein Wurf ist, wenn sich der Ball schneller als 12 Ballradien pro Sekunde bewegt (gehalten: 0–10, fliegend: 20–60). Wird zu viel oder zu wenig als Wurf erkannt, `--threshold` anpassen (z. B. `--threshold 15`). Mit `--min-flight 0.4` fallen kurze Bewegungen weg, z. B. wenn jemand mit dem Ball läuft.

## YOLO-Variante

`realtime_ball_tracking.py` erkennt Sportbälle mit einem vortrainierten KI-Modell statt über die Farbe. Dafür zusätzlich `pip install ultralytics`, dann:

```bash
python realtime_ball_tracking.py --source 1
```

Das Modell wird beim ersten Start automatisch geladen. Es ist allgemein trainiert („sports ball“) und erkennt einfarbige Bälle schlechter als der Farbtracker.
