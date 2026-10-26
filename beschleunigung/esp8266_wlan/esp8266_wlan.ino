// MMA7660 am ESP8266MOD, Werte über WLAN.
//
// Verkabelung, alles an 3,3 V (nicht an 5 V):
//   GND -> GND
//   VCC -> 3V3
//   SDA -> GPIO4   (auf NodeMCU / D1 mini: D2)
//   SCL -> GPIO5   (auf NodeMCU / D1 mini: D1)
//
// Zwei WLAN-Arten:
//   EIGENES_WLAN = true   Der ESP macht ein eigenes WLAN auf (Name/Passwort unten),
//                         der Rechner verbindet sich damit. Geht nur mit EINEM Ball.
//   EIGENES_WLAN = false  Der ESP geht in ein vorhandenes WLAN (Router/Handy-Hotspot).
//                         So können mehrere Bälle gleichzeitig senden. Jeder Ball
//                         bekommt dann eine eigene BALL_ID.
//
// Jede Messung geht als eine Zeile per UDP an Port 4210:
//   mma7660 ax=0.02 ay=-0.01 az=1.00 t=123456 n=42 id=1
//   t  = Millisekunden seit Start (für saubere Flugzeiten trotz WLAN-Ruckeln)
//   n  = laufende Nummer (zeigt verlorene Pakete)
//   id = Ball-Nummer
// midi.py und ball.py lesen das. midi.py ignoriert t/n/id einfach.
//
// Wichtig für die Auswertung: Den Sensor möglichst in die MITTE des Balls setzen.
// Sitzt er außen, misst er beim Drehen im Flug die Fliehkraft mit und der Flug
// wird nicht mehr als Flug erkannt.

#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
extern "C" {
#include <user_interface.h>
}

const int BALL_ID = 1;

const bool EIGENES_WLAN = true;
const char *AP_NAME = "Beschleunigung";
const char *AP_PASS = "beschleunigung";
const char *WLAN_NAME = "Installation";   // nur bei EIGENES_WLAN = false
const char *WLAN_PASS = "passwort";

const int SDA_PIN = 4;
const int SCL_PIN = 5;
const int RATE_HZ = 100;   // der MMA7660 liefert 120 Messungen/s, 100 Hz passt darunter
const uint8_t ADDR = 0x4C;
const uint16_t UDP_PORT = 4210;

WiFiUDP udp;
bool sensorDa = false;
uint32_t nummer = 0;
uint32_t naechsteMessung = 0;

bool schreiben(uint8_t reg, uint8_t wert) {
  Wire.beginTransmission(ADDR);
  Wire.write(reg);
  Wire.write(wert);
  return Wire.endTransmission() == 0;
}

// Liest X/Y/Z. Ist bei einem Wert das Alert-Bit (0x40) gesetzt, wurde das Register
// gerade beschrieben und der Wert ist ungültig: dann noch einmal lesen.
bool lesen(uint8_t *puffer) {
  for (int versuch = 0; versuch < 4; versuch++) {
    Wire.beginTransmission(ADDR);
    Wire.write(0x00);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(ADDR, (uint8_t)3) != 3) return false;
    puffer[0] = Wire.read();
    puffer[1] = Wire.read();
    puffer[2] = Wire.read();
    if (!((puffer[0] | puffer[1] | puffer[2]) & 0x40)) return true;
  }
  return false;
}

int8_t sechsBit(uint8_t wert) {
  wert &= 0x3F;
  if (wert & 0x20) wert |= 0xC0;
  return (int8_t)wert;
}

void zeileSenden(const char *zeile) {
  if (!EIGENES_WLAN) {
    // im gemeinsamen WLAN an alle im Netz (Broadcast)
    IPAddress ip = WiFi.localIP();
    IPAddress maske = WiFi.subnetMask();
    IPAddress ziel(ip[0] | ~maske[0], ip[1] | ~maske[1], ip[2] | ~maske[2], ip[3] | ~maske[3]);
    udp.beginPacket(ziel, UDP_PORT);
    udp.write(zeile);
    udp.endPacket();
    return;
  }
  bool raus = false;
  struct station_info *si = wifi_softap_get_station_info();
  while (si) {
    IPAddress ip(si->ip.addr);
    udp.beginPacket(ip, UDP_PORT);
    udp.write(zeile);
    udp.endPacket();
    raus = true;
    si = STAILQ_NEXT(si, next);
  }
  wifi_softap_free_station_info();
  if (!raus) {
    udp.beginPacket(IPAddress(192, 168, 4, 255), UDP_PORT);
    udp.write(zeile);
    udp.endPacket();
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  WiFi.setSleepMode(WIFI_NONE_SLEEP);  // kein Stromsparen: weniger Verzögerung
  if (EIGENES_WLAN) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_NAME, AP_PASS);
    Serial.print("WLAN ");
    Serial.print(AP_NAME);
    Serial.print("  ");
    Serial.println(WiFi.softAPIP());
  } else {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WLAN_NAME, WLAN_PASS);
    Serial.print("verbinde mit ");
    Serial.println(WLAN_NAME);
    while (WiFi.status() != WL_CONNECTED) {
      delay(200);
      Serial.print(".");
    }
    Serial.println();
    Serial.println(WiFi.localIP());
  }
  udp.begin(UDP_PORT);

  Wire.beginTransmission(ADDR);
  if (Wire.endTransmission() != 0) {
    Serial.println("kein MMA7660 an 0x4C");
    return;
  }
  schreiben(0x07, 0x00);  // Standby, sonst lassen sich die Register nicht schreiben
  schreiben(0x08, 0x00);  // 120 Messungen pro Sekunde
  schreiben(0x07, 0x01);  // aktiv
  sensorDa = true;
  Serial.println("Sensor: mma7660");
  naechsteMessung = micros();
}

void loop() {
  if (!sensorDa) {
    delay(1000);
    return;
  }

  // fester Takt: unabhängig davon, wie lange Lesen und Senden dauern
  const uint32_t abstand = 1000000UL / RATE_HZ;
  if ((int32_t)(micros() - naechsteMessung) < 0) return;
  naechsteMessung += abstand;
  if ((int32_t)(micros() - naechsteMessung) > (int32_t)(5 * abstand)) {
    naechsteMessung = micros() + abstand;  // nach einem langen Hänger nicht hinterherhetzen
  }

  uint8_t roh[3];
  if (!lesen(roh)) return;
  const float faktor = 1.0f / 21.33f;  // ±1,5 g, 6 Bit
  float x = sechsBit(roh[0]) * faktor;
  float y = sechsBit(roh[1]) * faktor;
  float z = sechsBit(roh[2]) * faktor;

  char zeile[96];
  snprintf(zeile, sizeof(zeile), "mma7660 ax=%.2f ay=%.2f az=%.2f t=%lu n=%lu id=%d",
           x, y, z, (unsigned long)millis(), (unsigned long)nummer++, BALL_ID);
  zeileSenden(zeile);
}
