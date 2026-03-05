// Team Endeavor
// Date: 06/03/2026

#include <Wire.h>

void setup() {
  Serial.begin(115200);
  while (!Serial); // Wait for serial port
  
  Wire.begin(21, 22); // SDA=21, SCL=22 for ESP32
  
  Serial.println("\n╔══════════════════════════════╗");
  Serial.println("║   ZoneCast I2C Scanner       ║");
  Serial.println("╚══════════════════════════════╝");
  Serial.println("\nScanning I2C bus (SDA=21, SCL=22)...\n");
  
  int deviceCount = 0;
  
  for (byte address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();
    
    if (error == 0) {
      Serial.printf("✓ Device found at address: 0x%02X", address);
      
      // Identify common devices
      if (address == 0x3C || address == 0x3D) {
        Serial.print("  ← This is your OLED Display!");
      } else if (address == 0x68 || address == 0x69) {
        Serial.print("  ← This might be an MPU6050 (gyro/accel)");
      } else if (address == 0x76 || address == 0x77) {
        Serial.print("  ← This might be a BME280 (temp/humidity)");
      }
      Serial.println();
      deviceCount++;
    }
  }
  
  Serial.println();
  if (deviceCount == 0) {
    Serial.println("✗ No I2C devices found!");
    Serial.println();
    Serial.println("TROUBLESHOOTING:");
    Serial.println("  1. Check OLED VCC → ESP32 3.3V (not 5V!)");
    Serial.println("  2. Check OLED GND → ESP32 GND");
    Serial.println("  3. Check OLED SDA → GPIO 21");
    Serial.println("  4. Check OLED SCL → GPIO 22");
    Serial.println("  5. Check all wires are firmly in breadboard holes");
  } else {
    Serial.printf("Found %d device(s).\n", deviceCount);
    Serial.println("\nIf you see 0x3C → your OLED address is correct (default).");
    Serial.println("If you see 0x3D → change OLED_ADDR to 0x3D in the firmware.");
  }
  
  Serial.println("\nScan complete. You can now upload the main firmware.");
}

void loop() {
  // Nothing — this is a one-time scan
  delay(10000);
}
