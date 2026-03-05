#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// Optional: uncomment to enable RGB LED and voice
// #include <Adafruit_NeoPixel.h>
// #include "DFRobotDFPlayerMini.h"

// ─────────────────────────────────────────────────────
//  ★ CONFIGURE THESE FOR EACH DEVICE ★
// ─────────────────────────────────────────────────────
#define WIFI_SSID       "Atharva"
#define WIFI_PASSWORD   "11111111"
#define MQTT_BROKER     "broker.hivemq.com"
#define MQTT_PORT       1883
#define MQTT_PREFIX     "zonecast"

// Unique per device — change for each ESP32 you flash
#define ZONE_ID         "zone_1"
#define DEVICE_ID       "ZC_Z1_001"
#define ZONE_LABEL      "Zone 1"
#define ZONE_DESC       "Lobby/Reception"

// ─────────────────────────────────────────────────────
//  PIN MAP
// ─────────────────────────────────────────────────────
#define PIN_BUZZER      5    // NPN transistor base via 1kΩ
#define PIN_ACK_BTN     34    // Acknowledge button (INPUT_PULLUP)
#define PIN_LED_RED     4    // Status LED red
#define PIN_LED_GREEN   2    // Status LED green (or NeoPixel data)

// OLED
#define OLED_SDA        21
#define OLED_SCL        22
#define OLED_ADDR       0x3C
#define OLED_W          128
#define OLED_H          64

// ─────────────────────────────────────────────────────
//  OBJECTS
// ─────────────────────────────────────────────────────
Adafruit_SSD1306 oled(OLED_W, OLED_H, &Wire, -1);
WiFiClient       netClient;
PubSubClient     mqtt(netClient);

// ─────────────────────────────────────────────────────
//  MQTT TOPICS (auto-constructed)
// ─────────────────────────────────────────────────────
const String TOPIC_MY_ZONE  = String(MQTT_PREFIX) + "/" + ZONE_ID + "/alert";
const String TOPIC_ALL      = String(MQTT_PREFIX) + "/all/alert";
const String TOPIC_STATUS   = String(MQTT_PREFIX) + "/status/" + DEVICE_ID;
const String TOPIC_ACK      = String(MQTT_PREFIX) + "/ack/" + DEVICE_ID;

// ─────────────────────────────────────────────────────
//  STATE MACHINE
// ─────────────────────────────────────────────────────
enum DeviceState { STATE_BOOT, STATE_CONNECTING, STATE_STANDBY, STATE_ALERT, STATE_CLEARED };
DeviceState state = STATE_BOOT;

struct AlertData {
  String type;
  String message;
  int    severity;     // 1=Low, 2=Medium, 3=Critical
  unsigned long duration;  // ms (0 = indefinite)
  String timestamp;
  bool   acknowledged;
};
AlertData currentAlert;
bool alertActive = false;

// ─────────────────────────────────────────────────────
//  TIMING
// ─────────────────────────────────────────────────────
unsigned long alertStartMs       = 0;
unsigned long lastHeartbeat      = 0;
unsigned long lastReconnectAttempt = 0;
unsigned long lastDisplayUpdate  = 0;
unsigned long lastBuzzerToggle   = 0;
unsigned long lastScrollTime     = 0;
unsigned long displayCycleMs     = 0;

bool buzzerOn          = false;
int  buzzerOnDuration  = 200;
int  buzzerOffDuration = 300;
int  scrollOffset      = 0;
int  displayPage       = 0;

const int RECONNECT_INTERVAL = 5000;
const int HEARTBEAT_INTERVAL = 30000;

// ─────────────────────────────────────────────────────
//  SETUP
// ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n╔═══════════════════════════╗");
  Serial.println("║  ZoneCast NEXUS Node v3.0 ║");
  Serial.printf("║  Zone: %-18s║\n", ZONE_ID);
  Serial.printf("║  ID:   %-18s║\n", DEVICE_ID);
  Serial.println("╚═══════════════════════════╝");

  // GPIO
  pinMode(PIN_BUZZER,    OUTPUT);
  pinMode(PIN_LED_RED,   OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_ACK_BTN,   INPUT_PULLUP);
  digitalWrite(PIN_BUZZER,    LOW);
  digitalWrite(PIN_LED_RED,   LOW);
  digitalWrite(PIN_LED_GREEN, LOW);

  // OLED
  Wire.begin(OLED_SDA, OLED_SCL);
  if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("[ERROR] OLED init failed!");
  }
  oled.clearDisplay();

  // Boot animation
  playBootAnimation();

  // Network
  connectWiFi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setBufferSize(600);
  connectMQTT();

  state = STATE_STANDBY;
  showStandby();
  Serial.println("[ZoneCast] Ready for alerts.");
}

// ─────────────────────────────────────────────────────
//  LOOP
// ─────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // Maintain MQTT
  if (!mqtt.connected() && (now - lastReconnectAttempt > RECONNECT_INTERVAL)) {
    lastReconnectAttempt = now;
    if (WiFi.status() != WL_CONNECTED) connectWiFi();
    connectMQTT();
  }
  mqtt.loop();

  // Handle alert state
  if (alertActive) {
    handleBuzzer(now);
    handleStatusLEDs(now);

    // Auto-expire
    if (currentAlert.duration > 0 && (now - alertStartMs > currentAlert.duration)) {
      clearAlert("[AUTO-EXPIRE]");
    }

    // Scroll display every 80ms
    if (now - lastScrollTime > 80) {
      lastScrollTime = now;
      showAlertScrolling();
      scrollOffset++;
    }

    // Cycle display pages every 3s
    if (now - displayCycleMs > 3000) {
      displayCycleMs = now;
      displayPage = (displayPage + 1) % 2;
    }

    // ACK button
    if (!currentAlert.acknowledged && digitalRead(PIN_ACK_BTN) == LOW) {
      delay(50);  // debounce
      if (digitalRead(PIN_ACK_BTN) == LOW) {
        acknowledgeAlert();
      }
    }
  } else {
    // Standby: green LED slow pulse
    if (now % 2000 < 100) { digitalWrite(PIN_LED_GREEN, HIGH); }
    else                   { digitalWrite(PIN_LED_GREEN, LOW); }
  }

  // Heartbeat
  if (now - lastHeartbeat > HEARTBEAT_INTERVAL) {
    lastHeartbeat = now;
    publishStatus("online");
  }

  // Standby display refresh every 5s
  if (!alertActive && now - lastDisplayUpdate > 5000) {
    lastDisplayUpdate = now;
    showStandby();
  }
}

// ─────────────────────────────────────────────────────
//  WIFI CONNECTION
// ─────────────────────────────────────────────────────
void connectWiFi() {
  showStatus("WiFi", "Connecting...", String(WIFI_SSID));
  Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries++ < 40) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] IP: %s  RSSI: %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
    showStatus("WiFi OK", WiFi.localIP().toString(), "RSSI: " + String(WiFi.RSSI()) + " dBm");
    delay(1000);
  } else {
    Serial.println("\n[WiFi] FAILED — will retry");
    showStatus("WiFi FAIL", "Check credentials", "Retrying...");
    delay(2000);
  }
}

// ─────────────────────────────────────────────────────
//  MQTT CONNECTION
// ─────────────────────────────────────────────────────
void connectMQTT() {
  showStatus("MQTT", "Connecting...", String(MQTT_BROKER));
  String clientId = String("ZC_") + DEVICE_ID + "_" + String(random(0xffff), HEX);

  if (mqtt.connect(clientId.c_str())) {
    Serial.println("[MQTT] Connected!");

    // Subscribe to zone-specific + broadcast
    mqtt.subscribe(TOPIC_MY_ZONE.c_str(), 1);
    mqtt.subscribe(TOPIC_ALL.c_str(),     1);

    Serial.printf("[MQTT] Sub: %s\n", TOPIC_MY_ZONE.c_str());
    Serial.printf("[MQTT] Sub: %s\n", TOPIC_ALL.c_str());

    publishStatus("online");
    showStatus("MQTT OK", String(MQTT_BROKER), "Subscribed");
    delay(800);
  } else {
    Serial.printf("[MQTT] Failed (rc=%d)\n", mqtt.state());
    showStatus("MQTT FAIL", "rc=" + String(mqtt.state()), "Retrying...");
    delay(1000);
  }
}

// ─────────────────────────────────────────────────────
//  MQTT MESSAGE HANDLER
// ─────────────────────────────────────────────────────
void onMqttMessage(char* topic, byte* payload, unsigned int len) {
  Serial.printf("[MQTT] Msg on: %s (%d bytes)\n", topic, len);

  // Parse JSON
  // Expected payload:
  // { "type":"FIRE", "message":"Evacuate now...", "severity":3, "duration":60000, "timestamp":"..." }
  char buf[600];
  len = min(len, (unsigned int)599);
  memcpy(buf, payload, len);
  buf[len] = '\0';

  StaticJsonDocument<600> doc;
  DeserializationError err = deserializeJson(doc, buf);
  if (err) {
    Serial.printf("[JSON] Error: %s\n", err.c_str());
    return;
  }

  const char* type    = doc["type"]     | "ALERT";
  const char* message = doc["message"]  | "Emergency!";
  int sev             = doc["severity"] | 2;
  unsigned long dur   = doc["duration"] | 0;
  const char* ts      = doc["timestamp"]| "";

  Serial.printf("[ALERT] Type=%s Sev=%d Dur=%lu\n", type, sev, dur);

  if (strcmp(type, "CLEAR") == 0) {
    clearAlert("[REMOTE-CLEAR]");
    return;
  }

  // Activate alert
  currentAlert.type         = String(type);
  currentAlert.message      = String(message);
  currentAlert.severity     = sev;
  currentAlert.duration     = dur;
  currentAlert.timestamp    = String(ts);
  currentAlert.acknowledged = false;

  alertActive    = true;
  alertStartMs   = millis();
  scrollOffset   = 0;
  displayPage    = 0;
  displayCycleMs = millis();
  state          = STATE_ALERT;

  // Buzzer timing by severity
  if (sev >= 3)      { buzzerOnDuration = 80;  buzzerOffDuration = 80;  }
  else if (sev == 2) { buzzerOnDuration = 250; buzzerOffDuration = 250; }
  else               { buzzerOnDuration = 500; buzzerOffDuration = 700; }

  publishStatus("alert_active");
  buzzerOn = true;
  digitalWrite(PIN_BUZZER, HIGH);
  lastBuzzerToggle = millis();
}

// ─────────────────────────────────────────────────────
//  BUZZER CONTROL (non-blocking)
// ─────────────────────────────────────────────────────
void handleBuzzer(unsigned long now) {
  if (currentAlert.acknowledged) {
    // Slow beep after ack
    if (buzzerOn && now - lastBuzzerToggle > 1000) {
      buzzerOn = false; digitalWrite(PIN_BUZZER, LOW); lastBuzzerToggle = now;
    } else if (!buzzerOn && now - lastBuzzerToggle > 3000) {
      buzzerOn = true; digitalWrite(PIN_BUZZER, HIGH); lastBuzzerToggle = now;
    }
    return;
  }
  if (buzzerOn  && now - lastBuzzerToggle >= (unsigned long)buzzerOnDuration)  { buzzerOn = false; digitalWrite(PIN_BUZZER, LOW);  lastBuzzerToggle = now; }
  if (!buzzerOn && now - lastBuzzerToggle >= (unsigned long)buzzerOffDuration) { buzzerOn = true;  digitalWrite(PIN_BUZZER, HIGH); lastBuzzerToggle = now; }
}

// ─────────────────────────────────────────────────────
//  STATUS LEDS
// ─────────────────────────────────────────────────────
void handleStatusLEDs(unsigned long now) {
  if (currentAlert.acknowledged) {
    digitalWrite(PIN_LED_RED,   LOW);
    digitalWrite(PIN_LED_GREEN, (now % 2000 < 200) ? HIGH : LOW);
    return;
  }
  // Red LED mirrors buzzer for visual flash
  digitalWrite(PIN_LED_RED,   buzzerOn ? HIGH : LOW);
  digitalWrite(PIN_LED_GREEN, LOW);
}

// ─────────────────────────────────────────────────────
//  ALERT ACK
// ─────────────────────────────────────────────────────
void acknowledgeAlert() {
  currentAlert.acknowledged = true;
  Serial.println("[ACK] Alert acknowledged by operator.");
  publishStatus("alert_acknowledged");

  // Publish ACK to broker
  StaticJsonDocument<128> doc;
  doc["device_id"] = DEVICE_ID;
  doc["zone"]      = ZONE_ID;
  doc["type"]      = currentAlert.type;
  doc["acked_at"]  = millis();
  char buf[128];
  serializeJson(doc, buf);
  mqtt.publish(TOPIC_ACK.c_str(), buf, false);

  // Show ACK screen briefly
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(10, 10);
  oled.println("RECEIVED");
  oled.setTextSize(1);
  oled.setCursor(5, 38);
  oled.println("Alert acknowledged.");
  oled.setCursor(5, 50);
  oled.println("Awaiting all-clear.");
  oled.display();
  delay(2000);
}

// ─────────────────────────────────────────────────────
//  CLEAR ALERT
// ─────────────────────────────────────────────────────
void clearAlert(const char* reason) {
  alertActive = false;
  state       = STATE_STANDBY;
  digitalWrite(PIN_BUZZER,    LOW);
  digitalWrite(PIN_LED_RED,   LOW);
  digitalWrite(PIN_LED_GREEN, HIGH);
  buzzerOn = false;
  Serial.printf("[CLEAR] Alert cleared: %s\n", reason);
  publishStatus("online");

  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(12, 8);
  oled.println("ALL CLEAR");
  oled.setTextSize(1);
  oled.setCursor(5, 35);
  oled.println("Emergency resolved.");
  oled.setCursor(5, 47);
  oled.println("Normal ops resumed.");
  oled.display();

  delay(500);
  digitalWrite(PIN_LED_GREEN, LOW);
  delay(3000);
  showStandby();
}

// ─────────────────────────────────────────────────────
//  PUBLISH STATUS
// ─────────────────────────────────────────────────────
void publishStatus(const char* status) {
  StaticJsonDocument<300> doc;
  doc["device_id"]   = DEVICE_ID;
  doc["zone"]        = ZONE_ID;
  doc["zone_label"]  = ZONE_LABEL;
  doc["status"]      = status;
  doc["ip"]          = WiFi.localIP().toString();
  doc["rssi"]        = WiFi.RSSI();
  doc["uptime_s"]    = millis() / 1000;
  doc["free_heap"]   = ESP.getFreeHeap();
  doc["alert_type"]  = alertActive ? currentAlert.type : "";
  doc["fw_version"]  = "3.0";

  char buf[300];
  serializeJson(doc, buf);
  mqtt.publish(TOPIC_STATUS.c_str(), buf, true);  // retained = true
  Serial.printf("[STATUS] %s → %s\n", DEVICE_ID, status);
}

// ─────────────────────────────────────────────────────
//  OLED — BOOT ANIMATION
// ─────────────────────────────────────────────────────
void playBootAnimation() {
  // Frame 1: ZoneCast logo
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(4, 2);
  oled.print("ZoneCast");
  oled.setTextSize(1);
  oled.setCursor(22, 24);
  oled.print("NEXUS  v3.0");
  oled.setCursor(0, 40);
  oled.print("Zone: "); oled.print(ZONE_ID);
  oled.setCursor(0, 52);
  oled.print("ID:   "); oled.print(DEVICE_ID);
  oled.display();
  delay(1500);

  // Loading bar animation
  for (int i = 0; i <= 128; i += 4) {
    oled.clearDisplay();
    oled.setTextSize(1);
    oled.setCursor(0, 0);
    oled.print("ZoneCast NEXUS v3.0");
    oled.drawLine(0, 15, 127, 15, SSD1306_WHITE);
    oled.setCursor(0, 22);
    oled.print("Initializing...");
    oled.drawRect(0, 48, 128, 10, SSD1306_WHITE);
    oled.fillRect(0, 48, i, 10, SSD1306_WHITE);
    oled.display();
    delay(18);
  }
  delay(300);
}

// ─────────────────────────────────────────────────────
//  OLED — STATUS SCREEN
// ─────────────────────────────────────────────────────
void showStatus(String title, String line1, String line2) {
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.print("["); oled.print(title); oled.print("]");
  oled.drawLine(0, 10, 127, 10, SSD1306_WHITE);
  oled.setCursor(0, 14);
  oled.print(line1);
  oled.setCursor(0, 26);
  oled.print(line2);
  oled.display();
}

// ─────────────────────────────────────────────────────
//  OLED — STANDBY SCREEN
// ─────────────────────────────────────────────────────
void showStandby() {
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);

  // Header
  oled.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  oled.setTextColor(SSD1306_BLACK);
  oled.setTextSize(1);
  oled.setCursor(2, 2);
  oled.print("ZONECAST NEXUS  STANDBY");
  oled.setTextColor(SSD1306_WHITE);

  // Zone info
  oled.setCursor(0, 15);
  oled.print("Zone : "); oled.print(ZONE_ID);
  oled.setCursor(0, 25);
  oled.print("Desc : "); oled.print(ZONE_DESC);
  oled.setCursor(0, 35);
  oled.print("IP   : "); oled.print(WiFi.localIP().toString());
  oled.setCursor(0, 45);
  oled.print("RSSI : "); oled.print(WiFi.RSSI()); oled.print(" dBm");
  oled.setCursor(0, 55);
  oled.print("Status: "); oled.print(mqtt.connected() ? "ONLINE" : "OFFLINE");

  // Border
  oled.drawRect(0, 0, 128, 64, SSD1306_WHITE);
  oled.display();
}

// ─────────────────────────────────────────────────────
//  OLED — ALERT SCREEN (with horizontal scroll)
// ─────────────────────────────────────────────────────
void showAlertScrolling() {
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);

  // Severity-based header
  const char* sevLabel = currentAlert.severity >= 3 ? "!! CRITICAL !!" :
                         currentAlert.severity == 2 ? "! WARNING !" : "ADVISORY";

  // Invert for critical
  if (currentAlert.severity >= 3) {
    oled.fillRect(0, 0, 128, 12, SSD1306_WHITE);
    oled.setTextColor(SSD1306_BLACK);
  }
  oled.setTextSize(1);
  oled.setCursor(2, 2);

  // Center the header
  int hlen = strlen(sevLabel);
  int hx   = max(0, (20 - hlen) / 2);
  oled.print(currentAlert.type + " " + String(sevLabel));
  oled.setTextColor(SSD1306_WHITE);

  // Zone identifier
  oled.setCursor(0, 14);
  oled.print("Zone: "); oled.print(ZONE_ID);
  if (currentAlert.acknowledged) { oled.setCursor(75, 14); oled.print("[ACK]"); }

  // Divider
  oled.drawLine(0, 24, 127, 24, SSD1306_WHITE);

  // Scrolling message
  // Pad message with spaces for smooth scroll
  String padded = "    " + currentAlert.message + "    ";
  int charCount = padded.length();
  int scrollMax = charCount * 6;  // 6 pixels per char
  int xOffset   = -(scrollOffset % scrollMax);

  oled.setCursor(xOffset, 28);
  oled.setTextSize(1);
  // Print twice for seamless loop
  oled.print(padded + padded);

  // Page 2: show instructions
  oled.setCursor(0, 44);
  if (displayPage == 0) {
    oled.print("Press BTN to ACK");
  } else {
    oled.print("Uptime: ");
    oled.print((millis() - alertStartMs) / 1000);
    oled.print("s");
  }

  // Bottom severity bar
  int barLen = map(currentAlert.severity, 1, 3, 40, 127);
  oled.fillRect(0, 56, barLen, 8, SSD1306_WHITE);
  oled.setCursor(barLen + 2, 57);
  oled.print("SEV ");
  oled.print(currentAlert.severity);

  oled.display();
}

// ─────────────────────────────────────────────────────
//  HELPER: WORD WRAP for OLED
// ─────────────────────────────────────────────────────
void printWrapped(String text, int x, int y, int maxCharsPerLine) {
  int start = 0;
  int line  = 0;
  while (start < (int)text.length() && line < 3) {
    int end = min(start + maxCharsPerLine, (int)text.length());
    oled.setCursor(x, y + line * 10);
    oled.print(text.substring(start, end));
    start = end;
    line++;
  }
}
