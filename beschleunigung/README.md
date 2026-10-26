# Beschleunigung im Ball

| Datei | Inhalt |
|---|---|
| `esp8266_wlan/esp8266_wlan.ino` | ESP8266 + MMA7660 im Ball, schickt 100 Messungen/s per UDP (mit Zeitstempel und Ball-ID) |
| `beschleunigung.ino` | Joy-IT/Uno-Variante über USB |
| `midi.py` | alte Auswertung: Sensor als Neigungs-Regler (gut für einen Controller in der Hand) |
| `ball.py` | **neue Auswertung für den Ball:** Abflug, Landung, Stoß, Ruhe, Drehung, Bewegung → MIDI/OSC |
| `zuordnung.html` | Seite zum Zuordnen: welcher Ball bei welcher Interaktion welchen Klang macht, mit Simulation und Live-Ansicht |

## Warum eine neue Auswertung

`midi.py` liest jede Achse als Neigung (X kippen = Tonhöhe). Bei einem Ball geht das nicht auf:

- Ein Ball hat kein Oben. Welche Achse gerade „X“ ist, hängt davon ab, wie er zufällig liegt. Beim Rollen pendeln alle drei Achsen, der Ton eiert.
- Im Flug misst der Sensor fast **0 g** (freier Fall). Alle Achsen stehen dann auf „waagrecht“ und die Bewegungs-Lautstärke fällt auf null. Der Ball wird genau in dem Moment still, in dem er fliegt.
- Es gibt nur einen Dauerton. Werfen, Fangen, Aufprallen sind keine eigenen Ereignisse.
- Die Glättung verschluckt kurze Schläge, und ohne Zeitstempel werden Zeiten durch das WLAN-Ruckeln ungenau.

`ball.py` wertet stattdessen den **Betrag** der Beschleunigung aus. Der hängt nicht davon ab, wie der Ball gedreht ist:

| Was | Woran erkannt | Daraus |
|---|---|---|
| Abflug | Betrag fällt unter 0,4 g, mindestens 50 ms lang | Ton an |
| Landung | Betrag steigt nach dem Flug über 0,8 g | Flugdauer → Wurfhöhe ≈ g·t²/8, Lautstärke, Tonhöhe |
| Stoß | Betrag weicht stark von 1 g ab und **kein** Flug folgt (sonst war es der Wurf) | Schlag |
| Ruhe | kaum Ruck und keine Drehung, 0,5 s lang | Ausklingen |
| Drehung | wie schnell sich die Richtung der Schwerkraft im Ball dreht | fortlaufend 0..1 |
| Bewegung | Ruck um die Schwerkraft herum | fortlaufend 0..1 |

Lässt man den Ball fallen, wird jeder Aufsprung eine eigene Landung mit kürzerer Flugzeit. Das ergibt von selbst einen Rhythmus.

## Starten

```bash
pip install mido python-rtmidi pyserial python-osc
python beschleunigung/ball.py --sim       # ohne Ball: simulierte Würfe
python beschleunigung/ball.py             # mit Ball über WLAN
```

Es öffnet sich http://127.0.0.1:8767 mit der Zuordnungsseite. Dort kommen die echten Ereignisse an, und jede Änderung der Zuordnung gilt sofort für den MIDI-Port **„Ball“** (Ball 1 = Kanal 1 usw., im Synth Polyphonie einschalten).

Weitere Optionen:

| Option | Bedeutung |
|---|---|
| `--aufnahme wuerfe.csv` | Rohdaten mitschreiben |
| `--datei wuerfe.csv` | Aufnahme abspielen, z. B. um Schwellen in `ball.py` oben nachzustellen |
| `--zuordnung zuordnung.json` | Zuordnung laden, Änderungen von der Seite landen dort |
| `--osc 127.0.0.1:9000` | zusätzlich OSC: `/ball/<id>/abflug`, `/landung`, `/stoss`, `/ruhe`, `/werte` |
| `--serial PORT` | Sensor über USB statt WLAN |
| `--kein-midi` | nur Seite/OSC |

## Mehrere Bälle

Mit `EIGENES_WLAN = true` macht jeder ESP ein eigenes WLAN auf, der Rechner kann aber nur in einem davon sein. Für mehrere Bälle in der Firmware `EIGENES_WLAN = false` setzen, ein gemeinsames WLAN (Router oder Handy-Hotspot) eintragen und jedem Ball eine eigene `BALL_ID` geben. Die Pakete gehen dann als Broadcast ins Netz, `ball.py` trennt sie nach ID.

## Grenzen des MMA7660

- **±1,5 g:** Wurf, Fang und Aufprall haben viel mehr. Der Sensor kappt, deshalb lässt sich die Wucht eines Aufpralls nicht messen. Die Flugzeit funktioniert trotzdem gut.
- **Keine Drehrate:** Im Flug sieht der Sensor keine Schwerkraft und damit auch keine Drehung.
- **Sensor in die Mitte setzen.** Sitzt er außen, misst er beim Drehen die Fliehkraft. Bei 3 cm Abstand und 2 Umdrehungen pro Sekunde sind das schon 0,5 g, und der Flug wird nicht mehr erkannt.

Besser wäre ein IMU mit Gyroskop und großem Messbereich, z. B. MPU-6050 (±16 g, ±2000 °/s), BMI270 oder LSM6DSO. Für harte Aufpralle gibt es Sensoren bis ±200 g (ADXL375).
