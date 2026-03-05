// Team Endeavor

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// ──────────────────────────────────────────────
//  CONFIGURATION — Edit these for your setup
// ──────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// MQTT Broker — use HiveMQ public broker for hackathon demo
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* MQTT_USER     = "";          // Leave empty for public broker
const char* MQTT_PASS     = "";

// Zone Identity — change per device (e.g., "zone_1", "zone_2", "zone_3")
const char* ZONE_ID       = "zone_1";
const char* DEVICE_ID     = "ESP32_Z1_001";

// MQTT Topics
// Each device subscribes to its zone topic AND the broadcast topic
String TOPIC_ZONE      = String("zonecast/") + ZONE_ID + "/alert";
String TOPIC_BROADCAST = "zonecast/all/alert";
String TOPIC_STATUS    = String("zonecast/status/") + DEVICE_ID;

// ──────────────────────────────────────────────
//  PIN DEFINITIONS
// ──────────────────────────────────────────────
#define BUZZER_PIN    14    // GPIO14 → NPN Base (via 1kΩ resistor)
#define LED_PIN       2    // GPIO26 → LED anode (via 220Ω resistor)
#define OLED_SDA      21    // I2C SDA
#define OLED_SCL      22    // I2C SCL
#define OLED_WIDTH    128
#define OLED_HEIGHT   64
#define OLED_RESET    -1    // Reset pin (-1 if sharing Arduino reset)

// ──────────────────────────────────────────────
//  GLOBALS
// ──────────────────────────────────────────────
WiFiClient        espClient;
PubSubClient      mqttClient(espClient);
Adafruit_SSD1306  display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);

bool  alertActive     = false;
int   alertSeverity   = 0;   // 1=Low, 2=Medium, 3=High/Critical
String alertMessage   = "";
String alertType      = "";
unsigned long alertStart = 0;
unsigned long alertDuration = 0;  // ms, 0 = indefinite

// Buzzer pattern state
unsigned long lastBuzzerToggle = 0;
bool buzzerState = false;
int buzzerOnTime  = 200;
int buzzerOffTime = 300;

// ──────────────────────────────────────────────
//  SETUP
// ──────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println("\n[ZoneCast] Booting...");

  // GPIO init
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN,    OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN,    LOW);

  // OLED init
  Wire.begin(OLED_SDA, OLED_SCL);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("[ERROR] OLED not found!");
  }
  showBootScreen();

  // WiFi
  connectWiFi();

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMqttMessage);
  mqttClient.setBufferSize(512);
  connectMQTT();

  showStandbyScreen();
  Serial.println("[ZoneCast] Ready.");
}

// ──────────────────────────────────────────────
//  MAIN LOOP
// ──────────────────────────────────────────────
void loop() {
  // Maintain MQTT connection
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();

  // Handle active alert
  if (alertActive) {
    runBuzzerPattern();
    blinkLED();

    // Auto-clear after duration
    if (alertDuration > 0 && (millis() - alertStart > alertDuration)) {
      clearAlert();
    }
  }

  // Publish heartbeat every 30s
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 30000) {
    lastHeartbeat = millis();
    publishStatus("online");
  }
}

// ──────────────────────────────────────────────
//  WIFI CONNECTION
// ──────────────────────────────────────────────
void connectWiFi() {
  Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  showConnectingScreen("WiFi");

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    showIPScreen(WiFi.localIP().toString());
  } else {
    Serial.println("\n[WiFi] FAILED. Check credentials.");
    showErrorScreen("WiFi Failed");
  }
}

// ──────────────────────────────────────────────
//  MQTT CONNECTION & SUBSCRIPTION
// ──────────────────────────────────────────────
void connectMQTT() {
  Serial.print("[MQTT] Connecting...");
  showConnectingScreen("MQTT");

  while (!mqttClient.connected()) {
    String clientId = String("ZoneCast-") + DEVICE_ID;
    if (mqttClient.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)) {
      Serial.println(" Connected!");

      // Subscribe to zone-specific and broadcast topics
      mqttClient.subscribe(TOPIC_ZONE.c_str());
      mqttClient.subscribe(TOPIC_BROADCAST.c_str());

      Serial.printf("[MQTT] Subscribed: %s\n", TOPIC_ZONE.c_str());
      Serial.printf("[MQTT] Subscribed: %s\n", TOPIC_BROADCAST.c_str());

      publishStatus("online");
    } else {
      Serial.printf(" Failed (rc=%d). Retry in 5s\n", mqttClient.state());
      delay(5000);
    }
  }
}

// ──────────────────────────────────────────────
//  MQTT MESSAGE HANDLER
// ──────────────────────────────────────────────
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  Serial.printf("[MQTT] Message on topic: %s\n", topic);

  // Parse JSON payload
  // Expected format:
  // {
  //   "type": "FIRE",          // FIRE, EARTHQUAKE, MEDICAL, SECURITY, DRILL, CLEAR
  //   "message": "Evacuate now via stairwell A",
  //   "severity": 3,           // 1=Low, 2=Medium, 3=Critical
  //   "duration": 60000,       // ms, 0 = stay until cleared
  //   "timestamp": "2026-03-04T10:00:00"
  // }

  char json[512];
  length = min(length, (unsigned int)511);
  memcpy(json, payload, length);
  json[length] = '\0';

  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, json);

  if (err) {
    Serial.printf("[JSON] Parse error: %s\n", err.c_str());
    return;
  }

  const char* type     = doc["type"]     | "ALERT";
  const char* message  = doc["message"]  | "Emergency Alert!";
  int severity         = doc["severity"] | 2;
  unsigned long dur    = doc["duration"] | 0;

  // Handle CLEAR command
  if (String(type) == "CLEAR") {
    clearAlert();
    return;
  }

  // Activate alert
  activateAlert(String(type), String(message), severity, dur);
}

// ──────────────────────────────────────────────
//  ALERT ACTIVATION
// ──────────────────────────────────────────────
void activateAlert(String type, String message, int severity, unsigned long duration) {
  alertActive   = true;
  alertType     = type;
  alertMessage  = message;
  alertSeverity = severity;
  alertStart    = millis();
  alertDuration = duration;

  // Set buzzer pattern based on severity
  if (severity >= 3) {
    buzzerOnTime  = 100;  // Fast beep = critical
    buzzerOffTime = 100;
  } else if (severity == 2) {
    buzzerOnTime  = 300;  // Medium beep
    buzzerOffTime = 300;
  } else {
    buzzerOnTime  = 500;  // Slow beep = informational
    buzzerOffTime = 700;
  }

  Serial.printf("[ALERT] Type: %s | Severity: %d | Msg: %s\n",
                type.c_str(), severity, message.c_str());

  showAlertScreen(type, message, severity);
  publishStatus("alert_active");
}

// ──────────────────────────────────────────────
//  ALERT CLEAR
// ──────────────────────────────────────────────
void clearAlert() {
  alertActive = false;
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN,    LOW);
  Serial.println("[ALERT] Cleared.");
  showStandbyScreen();
  publishStatus("online");
}

// ──────────────────────────────────────────────
//  BUZZER PATTERN (non-blocking)
// ──────────────────────────────────────────────
void runBuzzerPattern() {
  unsigned long now = millis();
  if (buzzerState && (now - lastBuzzerToggle >= (unsigned long)buzzerOnTime)) {
    buzzerState = false;
    digitalWrite(BUZZER_PIN, LOW);
    lastBuzzerToggle = now;
  } else if (!buzzerState && (now - lastBuzzerToggle >= (unsigned long)buzzerOffTime)) {
    buzzerState = true;
    digitalWrite(BUZZER_PIN, HIGH);
    lastBuzzerToggle = now;
  }
}

// ──────────────────────────────────────────────
//  LED BLINK (non-blocking)
// ──────────────────────────────────────────────
void blinkLED() {
  // LED mirrors buzzer
  digitalWrite(LED_PIN, buzzerState ? HIGH : LOW);
}

// ──────────────────────────────────────────────
//  STATUS PUBLISHER
// ──────────────────────────────────────────────
void publishStatus(const char* status) {
  StaticJsonDocument<256> doc;
  doc["device_id"] = DEVICE_ID;
  doc["zone"]      = ZONE_ID;
  doc["status"]    = status;
  doc["ip"]        = WiFi.localIP().toString();
  doc["rssi"]      = WiFi.RSSI();
  doc["uptime_s"]  = millis() / 1000;

  char buf[256];
  serializeJson(doc, buf);
  mqttClient.publish(TOPIC_STATUS.c_str(), buf, true);  // retained
}

// ──────────────────────────────────────────────
//  OLED DISPLAY FUNCTIONS
// ──────────────────────────────────────────────
void showBootScreen() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(10, 5);
  display.println("ZoneCast");
  display.setTextSize(1);
  display.setCursor(15, 28);
  display.println("Smart Emergency");
  display.setCursor(20, 38);
  display.println("Comm System");
  display.setCursor(25, 54);
  display.printf("Zone: %s", ZONE_ID);
  display.display();
  delay(2000);
}

void showConnectingScreen(const char* what) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.printf("Connecting to %s...", what);
  display.display();
}

void showIPScreen(String ip) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("WiFi Connected!");
  display.setCursor(0, 16);
  display.println(ip);
  display.display();
  delay(1500);
}

void showErrorScreen(const char* error) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("ERROR:");
  display.setCursor(0, 14);
  display.println(error);
  display.display();
}

void showStandbyScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("[ ZoneCast ]");
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);
  display.setCursor(0, 14);
  display.printf("Zone : %s\n", ZONE_ID);
  display.setCursor(0, 24);
  display.printf("ID   : %s\n", DEVICE_ID);
  display.setCursor(0, 34);
  display.printf("RSSI : %d dBm\n", WiFi.RSSI());
  display.setCursor(0, 44);
  display.println("Status: STANDBY");
  display.setCursor(0, 54);
  display.println("Listening for alerts...");
  display.display();
}

void showAlertScreen(String type, String message, int severity) {
  display.clearDisplay();

  // Header bar
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.printf("!! %s ALERT !!", type.c_str());

  // Severity indicator
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 15);
  display.print("Level: ");
  for (int i = 0; i < severity; i++) display.print("*");
  display.print(" (");
  if (severity == 1)      display.print("LOW)");
  else if (severity == 2) display.print("MED)");
  else                    display.print("CRIT)");

  // Message (word-wrap manually)
  display.setCursor(0, 26);
  // Display first 64 chars of message across 3 lines
  String line1 = message.substring(0, 21);
  String line2 = message.substring(21, 42);
  String line3 = message.substring(42, 63);
  display.println(line1);
  display.println(line2);
  display.println(line3);

  // Zone footer
  display.drawLine(0, 54, 127, 54, SSD1306_WHITE);
  display.setCursor(0, 56);
  display.printf("Zone: %s", ZONE_ID);

  display.display();
}
