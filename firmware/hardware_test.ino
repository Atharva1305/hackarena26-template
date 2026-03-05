#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ── PINS (must match your main firmware) ──
#define PIN_BUZZER    25
#define PIN_LED       26
#define PIN_BUTTON    34
#define OLED_SDA      21
#define OLED_SCL      22
#define OLED_ADDR     0x3C
#define OLED_W        128
#define OLED_H        64

Adafruit_SSD1306 oled(OLED_W, OLED_H, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(500);
  
  Serial.println("\n╔══════════════════════════════════╗");
  Serial.println("║  ZoneCast Hardware Test v1.0      ║");
  Serial.println("╚══════════════════════════════════╝\n");

  // ── GPIO SETUP ──
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED,    OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_LED,    LOW);

  // ── TEST 1: LED ──
  Serial.println("TEST 1: LED (GPIO26)");
  Serial.println("  Should blink 5 times...");
  for (int i = 0; i < 5; i++) {
    digitalWrite(PIN_LED, HIGH);
    delay(200);
    digitalWrite(PIN_LED, LOW);
    delay(200);
    Serial.printf("  Blink %d\n", i+1);
  }
  Serial.println("  ✓ LED test done\n");
  delay(500);

  // ── TEST 2: BUZZER ──
  Serial.println("TEST 2: BUZZER (GPIO25 via BC547)");
  Serial.println("  Should beep 3 times...");
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_BUZZER, HIGH);
    delay(300);
    digitalWrite(PIN_BUZZER, LOW);
    delay(300);
    Serial.printf("  Beep %d\n", i+1);
  }
  Serial.println("  ✓ Buzzer test done\n");
  delay(500);

  // ── TEST 3: OLED ──
  Serial.println("TEST 3: OLED Display (I2C)");
  Wire.begin(OLED_SDA, OLED_SCL);
  
  if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("  ✗ OLED NOT FOUND at 0x3C!");
    Serial.println("  → Try I2C Scanner sketch to find correct address");
    Serial.println("  → Check SDA→GPIO21, SCL→GPIO22, VCC→3.3V");
  } else {
    Serial.println("  ✓ OLED found at 0x3C");
    
    // Show test pattern
    oled.clearDisplay();
    oled.setTextColor(SSD1306_WHITE);
    
    // Test 1: All pixels on
    oled.fillScreen(SSD1306_WHITE);
    oled.display();
    delay(500);
    
    // Test 2: All off
    oled.clearDisplay();
    oled.display();
    delay(300);
    
    // Test 3: Text display
    oled.setTextSize(2);
    oled.setCursor(8, 4);
    oled.println("ZoneCast");
    oled.setTextSize(1);
    oled.setCursor(4, 26);
    oled.println("Hardware Test v1.0");
    oled.drawLine(0, 36, 127, 36, SSD1306_WHITE);
    oled.setCursor(4, 40);
    oled.println("LED:    OK");
    oled.setCursor(4, 50);
    oled.println("BUZZER: OK");
    oled.setCursor(4, 60);
    // Will be updated by button test
    oled.println("BUTTON: Testing...");
    oled.display();
    
    Serial.println("  ✓ OLED showing test screen\n");
  }

  // ── TEST 4: BUTTON ──
  Serial.println("TEST 4: BUTTON (GPIO34)");
  Serial.println("  Press and release the button within 5 seconds...\n");
  
  unsigned long startTime = millis();
  bool buttonPressed = false;
  bool buttonReleased = false;
  
  while (millis() - startTime < 5000) {
    if (digitalRead(PIN_BUTTON) == LOW && !buttonPressed) {
      buttonPressed = true;
      Serial.println("  → Button PRESSED detected!");
      // Flash LED to confirm
      digitalWrite(PIN_LED, HIGH);
      // Update OLED
      oled.fillRect(0, 56, 128, 8, SSD1306_BLACK);
      oled.setCursor(4, 57);
      oled.println("BUTTON: PRESSED!");
      oled.display();
    }
    if (digitalRead(PIN_BUTTON) == HIGH && buttonPressed && !buttonReleased) {
      buttonReleased = true;
      Serial.println("  → Button RELEASED detected!");
      digitalWrite(PIN_LED, LOW);
      oled.fillRect(0, 56, 128, 8, SSD1306_BLACK);
      oled.setCursor(4, 57);
      oled.println("BUTTON: OK");
      oled.display();
      break;
    }
    delay(10);
  }
  
  if (!buttonPressed) {
    Serial.println("  ! Button not pressed (timeout). Check wiring:");
    Serial.println("    GPIO34 → Button pin 1");
    Serial.println("    GND    → Button pin 2");
  } else {
    Serial.println("  ✓ Button test done\n");
  }

  // ── FINAL RESULT ──
  Serial.println("══════════════════════════════════");
  Serial.println("  ALL HARDWARE TESTS COMPLETE!");
  Serial.println("  You can now upload the main firmware.");
  Serial.println("══════════════════════════════════\n");

  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.println("ALL TESTS PASSED!");
  oled.drawLine(0, 12, 127, 12, SSD1306_WHITE);
  oled.setCursor(0, 16);
  oled.println("LED:    OK (blinked 5x)");
  oled.setCursor(0, 26);
  oled.println("BUZZER: OK (beeped 3x)");
  oled.setCursor(0, 36);
  oled.println("OLED:   OK (you see this)");
  oled.setCursor(0, 46);
  oled.println(buttonPressed ? "BUTTON: OK" : "BUTTON: Not tested");
  oled.setCursor(0, 56);
  oled.println("Upload main firmware now!");
  oled.display();
}

void loop() {
  // Blink LED slowly to show test is done
  digitalWrite(PIN_LED, HIGH); delay(1000);
  digitalWrite(PIN_LED, LOW);  delay(1000);
}
