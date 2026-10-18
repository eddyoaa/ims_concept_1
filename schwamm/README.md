# Prototyp: Schwamm-Instrument

Ein nasser Schwamm ist Sensor und Klangquelle zugleich. Drücken macht den Klang tiefer, dichter und verhallter. Jedes Drücken kostet Wasser, bis das Instrument verstummt. Eintauchen bringt den Klang zurück.

| Datei | Inhalt |
|---|---|
| `schwamm_sensor/schwamm_sensor.ino` | Arduino-Sketch: misst die Leitfähigkeit des Schwamms |
| `schwamm.py` | Klangverarbeitung in Python: Tropfen/Mikro → Granular → Hall, plus Anzeige im Browser |
| `hoerprobe_simulation.wav` | 20 s Hörprobe aus dem Simulationsmodus (ohne Hardware erzeugt) |

---

## 1. Sofort ausprobieren, ohne Hardware

```bash
pip install numpy sounddevice
python schwamm.py
```

Im Browser öffnet sich eine Seite (http://127.0.0.1:8765) mit Schieberegler („Schwamm drücken“) und Knopf „In Wasser tauchen“. Lässt du den Regler los, springt er zurück wie ein Schwamm. Beenden mit Strg+C im Terminal. Statt echtem Wasser erklingen synthetische Tropfen. Wenn du länger drückst, sinkt die Nässe, und es wird still.

## 2. Teile für den echten Aufbau

- Arduino Uno oder Nano
- Haushaltsschwamm (ohne Kratzseite) und eine flache Schale
- 2 Stücke **Edelstahl**-Gitter oder -Blech, etwa schwammgroß (kein Kupfer, das korrodiert im Salzwasser)
- 10 kΩ Widerstand, Kabel mit Krokoklemmen
- Salzwasser: etwa 1 Teelöffel Salz auf 1 Liter
- Für den Klang: Piezo-Kontaktmikrofon und ein Audiointerface mit Instrumenteneingang (Hi-Z). Ein Piezo direkt am Laptop-Mikrofoneingang klingt sehr dünn.

## 3. Verkabelung

```
Arduino D7 ──── Gitter oben
                [ nasser Schwamm ]
Arduino A0 ──── Gitter unten
Arduino A0 ──── 10 kΩ ──── Arduino D8
```

Der Schwamm liegt zwischen den beiden Gittern, das untere liegt in der Schale. Der Piezo wird **unter die Schale** geklebt (Klebeband oder Knete) und ans Audiointerface angeschlossen.

Der Sketch wechselt bei jeder Messung die Stromrichtung und schaltet sonst ab. So korrodieren die Elektroden kaum, und es entstehen keine Gasbläschen.

## 4. Starten mit Hardware

1. Sketch mit der Arduino IDE hochladen. Im Seriellen Monitor (115200 Baud) solltest du Zahlen sehen: trocken nahe 0, nass höher, gedrückt noch höher.
2. Seriellen Monitor schließen, sonst ist der Port belegt.
3. Python starten:

```bash
pip install numpy sounddevice pyserial
python schwamm.py --geraete                           # Nummer des Audiointerfaces nachsehen
python schwamm.py --serial /dev/ttyACM0               # Sensor + synthetische Tropfen
python schwamm.py --serial /dev/ttyACM0 --mikro --eingang 2 --ausgang 2
```

Unter Windows heißt der Port `COM3` o. ä., auf dem Mac `/dev/tty.usbmodem…`.

**Kalibrieren:** Den Schwamm nach dem Start einmal richtig nass einlegen und ein paar Sekunden nicht drücken. Das Skript merkt sich den Ruhewert als „nass“ und alles darüber als „Druck“.

## 5. TouchDesigner anbinden

Das Skript schickt Druck und Nässe (0..1) per OSC an `127.0.0.1:7000`:

- `/schwamm/druck`
- `/schwamm/nass`

In TouchDesigner ein **OSC In CHOP** auf Port 7000 anlegen, dann stehen beide Werte als Kanäle bereit, z. B. für Visuals oder als Steuerung für eine eigene Klangverarbeitung in TD.

## 6. Was das Skript mit dem Klang macht

- **Quelle:** das Kontaktmikro, oder ohne Mikro synthetische Luftblasen-Tropfen. Die Tropfenrate steigt mit dem Druck.
- **Nässe** regelt die Gesamtlautstärke: trocken heißt still.
- **Granular:** Die letzten Sekunden werden in kurze Körner zerlegt und verlangsamt abgespielt. Mehr Druck ergibt mehr Körner, die tiefer klingen.
- **Hall:** Mehr Druck ergibt mehr und längeren Hall.

Alle Stellschrauben stehen als Zahlen direkt im Code (Klassen `Tropfen`, `Granular`, `Hall`, `Motor`).

## 7. Was noch offen ist

- Getestet ist nur die Klangverarbeitung: Sie läuft ohne Soundkarte und etwa 17-mal schneller als Echtzeit. Arduino-Sketch, Sensorauswertung und Audio-Ein-/Ausgabe sind ungetestet, weil hier keine Hardware dranhängt.
- Wie sich der Widerstand beim Drücken wirklich verhält, muss man ausprobieren. Drücken verdichtet das Wasser (Widerstand sinkt), drückt es aber auch heraus (Widerstand steigt). Falls der Wert beim Drücken fällt statt steigt, im Sketch `return 1023 - …` verwenden oder die Auswertung in `SensorLeser` anpassen.
- Ideen zum Weiterbauen: mehrere Schwämme als Stimmen, ein Hydrophon im Tauchbecken, sodass auch das Eintauchen klingt, oder ein Wasserbecken mit Pumpe, das sich langsam leert.
