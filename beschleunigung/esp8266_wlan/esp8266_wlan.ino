// MMA7660 am ESP8266MOD, Werte über WLAN.
//
// Verkabelung, alles an 3,3 V (nicht an 5 V):
//   GND -> GND
//   VCC -> 3V3
//   SDA -> GPIO4   (auf NodeMCU / D1 mini: D2)
//   SCL -> GPIO5   (auf NodeMCU / D1 mini: D1)
//
// Der ESP macht ein eigenes WLAN auf:
//   Name:     Beschleunigung
//   Passwort: beschleunigung
// Der Rechner verbindet sich damit. Die Zeilen gehen per UDP an Port 4210,
// midi.py macht daraus den MIDI-Port.

#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
extern "C" {
#include <user_interface.h>
}

const int SDA_PIN = 4;
const int SCL_PIN = 5;
const int RATE_HZ = 50;
const uint8_t ADDR = 0x4C;
const uint16_t UDP_PORT = 4210;

const char *AP_NAME = "Beschleunigung";
const char *AP_PASS = "beschleunigung";

WiFiUDP udp;

bool schreiben(uint8_t reg, uint8_t wert) {
  Wire.beginTransmission(ADDR);
  Wire.write(reg);
  Wire.write(wert);
  return Wire.endTransmission() == 0;
}

bool lesen(uint8_t *puffer) {
  Wire.beginTransmission(ADDR);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(ADDR, (uint8_t)3) != 3) return false;
  puffer[0] = Wire.read();
  puffer[1] = Wire.read();
  puffer[2] = Wire.read();
  return true;
}

int8_t sechsBit(uint8_t wert) {
  wert &= 0x3F;
  if (wert & 0x20) wert |= 0xC0;
  return (int8_t)wert;
}

void zeileSenden(const String &zeile) {
  bool raus = false;
  struct station_info *si = wifi_softap_get_station_info();
  while (si) {
    IPAddress ip(si->ip.addr);
    udp.beginPacket(ip, UDP_PORT);
    udp.write(zeile.c_str());
    udp.endPacket();
    raus = true;
    si = STAILQ_NEXT(si, next);
  }
  wifi_softap_free_station_info();
  if (!raus) {
    udp.beginPacket(IPAddress(192, 168, 4, 255), UDP_PORT);
    udp.write(zeile.c_str());
    udp.endPacket();
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_NAME, AP_PASS);
  udp.begin(UDP_PORT);
  Serial.print("WLAN ");
  Serial.print(AP_NAME);
  Serial.print("  ");
  Serial.println(WiFi.softAPIP());

  Wire.beginTransmission(ADDR);
  if (Wire.endTransmission() != 0) {
    Serial.println("kein MMA7660 an 0x4C");
    return;
  }
  schreiben(0x07, 0x00);
  schreiben(0x08, 0x00);
  schreiben(0x07, 0x01);
  Serial.println("Sensor: mma7660");
}

void loop() {
  uint8_t roh[3];
  if (!lesen(roh)) {
    delay(1000 / RATE_HZ);
    return;
  }
  float faktor = 1.0f / 21.33f;
  float x = sechsBit(roh[0]) * faktor;
  float y = sechsBit(roh[1]) * faktor;
  float z = sechsBit(roh[2]) * faktor;

  char zeile[64];
  snprintf(zeile, sizeof(zeile), "mma7660 ax=%.2f ay=%.2f az=%.2f", x, y, z);
  zeileSenden(zeile);
  Serial.println(zeile);
  delay(1000 / RATE_HZ);
}
