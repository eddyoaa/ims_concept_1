// 3-Achsen-Beschleunigungssensor am Joy-IT R3DIP (Uno-kompatibel)
//
// Verkabelung (I2C):
//   GND  -> GND
//   VCC  -> 5V
//   SCL  -> A5
//   SDA  -> A4
//
// Der Sketch sucht den Sensor auf dem I2C-Bus und liest X/Y/Z.
// Erkannt werden MMA7660, ADXL345, MPU-6050 und LIS3DH.
//
// Ausgabe: eine Zeile pro Messung, z. B.
//   adxl345  ax=0.02 ay=-0.01 az=1.00
//
// MIDI entsteht auf dem Rechner: python beschleunigung/midi.py
// öffnet den virtuellen Port „Beschleunigung“ (X=CC16, Y=CC17, Z=CC18).

#include <Wire.h>

const int RATE_HZ = 50;

const uint8_t ADDR_MMA7660 = 0x4C;
const uint8_t ADDR_ADXL345_LOW = 0x53;
const uint8_t ADDR_ADXL345_HIGH = 0x1D;
const uint8_t ADDR_MPU6050 = 0x68;
const uint8_t ADDR_LIS3DH = 0x18;
const uint8_t ADDR_LIS3DH_ALT = 0x19;

uint8_t sensorAdresse = 0;
enum SensorArt { KEIN, MMA7660, ADXL345, MPU6050, LIS3DH };
SensorArt sensorArt = KEIN;

bool i2cSchreiben(uint8_t reg, uint8_t wert) {
  Wire.beginTransmission(sensorAdresse);
  Wire.write(reg);
  Wire.write(wert);
  return Wire.endTransmission() == 0;
}

bool i2cLesen(uint8_t reg, uint8_t *puffer, uint8_t laenge) {
  Wire.beginTransmission(sensorAdresse);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(sensorAdresse, laenge) != laenge) return false;
  for (uint8_t i = 0; i < laenge; i++) puffer[i] = Wire.read();
  return true;
}

uint8_t i2cByte(uint8_t adresse, uint8_t reg) {
  Wire.beginTransmission(adresse);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom(adresse, (uint8_t)1) != 1) return 0xFF;
  return Wire.read();
}

bool vorhanden(uint8_t adresse) {
  Wire.beginTransmission(adresse);
  return Wire.endTransmission() == 0;
}

int8_t sechsBit(uint8_t wert) {
  wert &= 0x3F;
  if (wert & 0x20) wert |= 0xC0;
  return (int8_t)wert;
}

bool sensorStarten() {
  if (vorhanden(ADDR_MMA7660)) {
    sensorAdresse = ADDR_MMA7660;
    sensorArt = MMA7660;
    i2cSchreiben(0x07, 0x00);  // Standby, sonst lassen sich die Register nicht schreiben
    i2cSchreiben(0x08, 0x00);  // 120 Messungen pro Sekunde
    i2cSchreiben(0x07, 0x01);  // aktiv
    return true;
  }

  if (vorhanden(ADDR_ADXL345_LOW) && i2cByte(ADDR_ADXL345_LOW, 0x00) == 0xE5) {
    sensorAdresse = ADDR_ADXL345_LOW;
  } else if (vorhanden(ADDR_ADXL345_HIGH) && i2cByte(ADDR_ADXL345_HIGH, 0x00) == 0xE5) {
    sensorAdresse = ADDR_ADXL345_HIGH;
  }
  if (sensorAdresse == ADDR_ADXL345_LOW || sensorAdresse == ADDR_ADXL345_HIGH) {
    sensorArt = ADXL345;
    i2cSchreiben(0x2D, 0x08);  // Messmodus
    i2cSchreiben(0x31, 0x0B);  // ±16 g, volle Auflösung
    return true;
  }

  if (vorhanden(ADDR_MPU6050) && i2cByte(ADDR_MPU6050, 0x75) == 0x68) {
    sensorAdresse = ADDR_MPU6050;
    sensorArt = MPU6050;
    i2cSchreiben(0x6B, 0x00);  // aufwecken
    i2cSchreiben(0x1C, 0x00);  // ±2 g
    return true;
  }

  uint8_t lis = 0;
  if (vorhanden(ADDR_LIS3DH) && i2cByte(ADDR_LIS3DH, 0x0F) == 0x33) lis = ADDR_LIS3DH;
  else if (vorhanden(ADDR_LIS3DH_ALT) && i2cByte(ADDR_LIS3DH_ALT, 0x0F) == 0x33) lis = ADDR_LIS3DH_ALT;
  if (lis) {
    sensorAdresse = lis;
    sensorArt = LIS3DH;
    i2cSchreiben(0x20, 0x57);  // 100 Hz, X/Y/Z an
    i2cSchreiben(0x23, 0x00);  // ±2 g
    return true;
  }

  return false;
}

void busZeigen() {
  Serial.print("kein bekannter Sensor. Adressen auf dem Bus:");
  bool irgendwas = false;
  for (uint8_t adresse = 1; adresse < 127; adresse++) {
    if (!vorhanden(adresse)) continue;
    irgendwas = true;
    Serial.print(" 0x");
    if (adresse < 16) Serial.print("0");
    Serial.print(adresse, HEX);
  }
  if (!irgendwas) Serial.print(" keine");
  Serial.println();
}

bool beschleunigungLesen(float *x, float *y, float *z) {
  uint8_t roh[6];
  int16_t rx, ry, rz;
  float faktor;

  if (sensorArt == MMA7660) {
    if (!i2cLesen(0x00, roh, 3)) return false;
    rx = sechsBit(roh[0]);
    ry = sechsBit(roh[1]);
    rz = sechsBit(roh[2]);
    faktor = 1.0f / 21.33f;  // ±1,5 g, 6 Bit
  } else if (sensorArt == ADXL345) {
    if (!i2cLesen(0x32, roh, 6)) return false;
    rx = (int16_t)(roh[1] << 8 | roh[0]);
    ry = (int16_t)(roh[3] << 8 | roh[2]);
    rz = (int16_t)(roh[5] << 8 | roh[4]);
    faktor = 0.004f;  // 4 mg/LSB bei voller Auflösung
  } else if (sensorArt == MPU6050) {
    if (!i2cLesen(0x3B, roh, 6)) return false;
    rx = (int16_t)(roh[0] << 8 | roh[1]);
    ry = (int16_t)(roh[2] << 8 | roh[3]);
    rz = (int16_t)(roh[4] << 8 | roh[5]);
    faktor = 1.0f / 16384.0f;  // ±2 g
  } else if (sensorArt == LIS3DH) {
    if (!i2cLesen(0x28 | 0x80, roh, 6)) return false;
    rx = (int16_t)(roh[1] << 8 | roh[0]);
    ry = (int16_t)(roh[3] << 8 | roh[2]);
    rz = (int16_t)(roh[5] << 8 | roh[4]);
    faktor = 1.0f / 16384.0f;
  } else {
    return false;
  }

  *x = rx * faktor;
  *y = ry * faktor;
  *z = rz * faktor;
  return true;
}

const char *sensorName() {
  if (sensorArt == MMA7660) return "mma7660";
  if (sensorArt == ADXL345) return "adxl345";
  if (sensorArt == MPU6050) return "mpu6050";
  if (sensorArt == LIS3DH) return "lis3dh";
  return "keiner";
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  delay(50);

  if (sensorStarten()) {
    Serial.print("Sensor: ");
    Serial.print(sensorName());
    Serial.print(" an 0x");
    Serial.println(sensorAdresse, HEX);
  } else {
    busZeigen();
  }
}

void loop() {
  if (sensorArt == KEIN) {
    delay(1000);
    if (sensorStarten()) {
      Serial.print("Sensor: ");
      Serial.print(sensorName());
      Serial.print(" an 0x");
      Serial.println(sensorAdresse, HEX);
    }
    return;
  }

  float x, y, z;
  if (beschleunigungLesen(&x, &y, &z)) {
    Serial.print(sensorName());
    Serial.print(" ax=");
    Serial.print(x, 2);
    Serial.print(" ay=");
    Serial.print(y, 2);
    Serial.print(" az=");
    Serial.println(z, 2);
  } else {
    Serial.println("lesefehler");
  }
  delay(1000 / RATE_HZ);
}
