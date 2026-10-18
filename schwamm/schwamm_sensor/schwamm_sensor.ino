// Schwamm-Sensor
// Misst die Leitfähigkeit eines nassen Schwamms und schickt sie per Serial.
//
// Verkabelung (Spannungsteiler mit Polwechsel):
//   Pin D7 ── Elektrode oben ── [Schwamm] ── Elektrode unten ── A0
//   A0 ── 10 kΩ Widerstand ── Pin D8
//
// Der Strom fließt bei jeder Messung abwechselnd in beide Richtungen und
// nur für wenige Mikrosekunden. Das verhindert, dass die Elektroden im
// Salzwasser durch Elektrolyse schnell korrodieren.
//
// Ausgabe: eine Zahl pro Zeile, 0 (trocken / kein Kontakt) bis 1023 (sehr nass / fest gedrückt)

const int PIN_A = 7;
const int PIN_B = 8;
const int PIN_MESS = A0;
const int RATE_HZ = 50;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_A, INPUT);
  pinMode(PIN_B, INPUT);
}

int messen() {
  // Richtung 1: Strom von D7 durch den Schwamm nach D8
  pinMode(PIN_A, OUTPUT);
  pinMode(PIN_B, OUTPUT);
  digitalWrite(PIN_A, HIGH);
  digitalWrite(PIN_B, LOW);
  delayMicroseconds(50);
  int vorwaerts = analogRead(PIN_MESS);           // hoch = Schwamm leitet gut

  // Richtung 2: umgekehrt, gleicht die Ladung wieder aus
  digitalWrite(PIN_A, LOW);
  digitalWrite(PIN_B, HIGH);
  delayMicroseconds(50);
  int rueckwaerts = 1023 - analogRead(PIN_MESS);  // gleiche Bedeutung wie vorwaerts

  // Ruhezustand: kein Strom
  pinMode(PIN_A, INPUT);
  pinMode(PIN_B, INPUT);

  return (vorwaerts + rueckwaerts) / 2;
}

void loop() {
  // 4 Messungen mitteln gegen Rauschen
  long summe = 0;
  for (int i = 0; i < 4; i++) summe += messen();
  Serial.println(summe / 4);
  delay(1000 / RATE_HZ);
}
