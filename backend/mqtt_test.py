#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║   ZoneCast NEXUS — MQTT Test & Debug Tool                        ║
║   Use this to test your MQTT connection and send test alerts     ║
╚══════════════════════════════════════════════════════════════════╝

HOW TO RUN:
  1. Install: pip install paho-mqtt
  2. Run:     python mqtt_test.py

WHAT IT DOES:
  - Connects to HiveMQ public broker
  - Subscribes to all ZoneCast topics
  - Lets you send test alerts from your terminal
  - Shows incoming device status messages
"""

import paho.mqtt.client as mqtt
import json
import time
import sys
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────
BROKER   = "broker.hivemq.com"
PORT     = 1883
PREFIX   = "zonecast"
CLIENT_ID = f"ZoneCast_TestTool_{int(time.time())}"

# ── COLORS FOR TERMINAL ──────────────────────────────
class Color:
    RED    = '\033[91m'
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    CYAN   = '\033[96m'
    BLUE   = '\033[94m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'

def log(tag, msg, color=Color.CYAN):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}] [{tag}]{Color.RESET} {msg}")

# ── MQTT CALLBACKS ───────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log("MQTT", f"Connected to {BROKER}:{PORT}", Color.GREEN)
        # Subscribe to all ZoneCast topics
        topics = [
            (f"{PREFIX}/status/#", 0),
            (f"{PREFIX}/ack/#", 0),
            (f"{PREFIX}/all/alert", 0),
            (f"{PREFIX}/zone_1/alert", 0),
            (f"{PREFIX}/zone_2/alert", 0),
            (f"{PREFIX}/zone_3/alert", 0),
        ]
        for topic, qos in topics:
            client.subscribe(topic, qos)
            log("SUB", f"Subscribed: {topic}", Color.BLUE)
    else:
        log("ERROR", f"Connection failed with code {rc}", Color.RED)

def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode())
        if "status" in topic:
            color = Color.GREEN if payload.get("status") == "online" else Color.YELLOW
            log("DEVICE", 
                f"{payload.get('device_id','?')} [{payload.get('zone','?')}] "
                f"→ {payload.get('status','?')} | "
                f"RSSI: {payload.get('rssi','?')}dBm | "
                f"IP: {payload.get('ip','?')}",
                color)
        elif "ack" in topic:
            log("ACK", f"Alert acknowledged by {payload.get('device_id','?')}", Color.GREEN)
        elif "alert" in topic:
            log("ALERT", f"Alert on [{topic}]: {payload.get('type','?')} — {payload.get('message','?')[:60]}", Color.RED)
    except:
        log("RAW", f"[{topic}] {msg.payload.decode()[:100]}", Color.YELLOW)

def on_disconnect(client, userdata, rc):
    if rc != 0:
        log("MQTT", "Unexpected disconnect. Reconnecting...", Color.YELLOW)

# ── ALERT SENDER ─────────────────────────────────────
def send_alert(client, zone, alert_type, message, severity=3, duration=60):
    topic = f"{PREFIX}/{zone}/alert"
    payload = json.dumps({
        "type":      alert_type,
        "message":   message,
        "severity":  severity,
        "duration":  duration * 1000,
        "timestamp": datetime.now().isoformat(),
        "sender":    "ZoneCast_TestTool"
    })
    result = client.publish(topic, payload, qos=1)
    if result.rc == 0:
        log("SEND", f"Alert sent to [{topic}]: {alert_type} (Sev {severity})", Color.RED)
    else:
        log("ERROR", f"Failed to publish to {topic}", Color.RED)

def send_clear(client):
    topic = f"{PREFIX}/all/alert"
    payload = json.dumps({
        "type": "CLEAR", "message": "All clear.", 
        "severity": 0, "duration": 0,
        "timestamp": datetime.now().isoformat()
    })
    client.publish(topic, payload, qos=1)
    log("CLEAR", "ALL-CLEAR sent to all zones", Color.GREEN)

# ── INTERACTIVE MENU ─────────────────────────────────
def print_menu():
    print(f"\n{Color.BOLD}{Color.CYAN}{'═'*55}")
    print("  ZONECAST NEXUS — MQTT TEST TOOL")
    print(f"{'═'*55}{Color.RESET}")
    print(f"  {Color.YELLOW}1{Color.RESET} → Send FIRE alert to zone_1")
    print(f"  {Color.YELLOW}2{Color.RESET} → Send FIRE alert to zone_2")
    print(f"  {Color.YELLOW}3{Color.RESET} → Send MEDICAL alert to zone_3")
    print(f"  {Color.YELLOW}4{Color.RESET} → Send EARTHQUAKE to ALL zones")
    print(f"  {Color.YELLOW}5{Color.RESET} → Send DRILL to ALL zones (low severity)")
    print(f"  {Color.YELLOW}6{Color.RESET} → Send SECURITY LOCKDOWN to zone_1")
    print(f"  {Color.YELLOW}7{Color.RESET} → Send ALL-CLEAR")
    print(f"  {Color.YELLOW}8{Color.RESET} → Custom alert (you type everything)")
    print(f"  {Color.YELLOW}9{Color.RESET} → Run automated demo sequence")
    print(f"  {Color.YELLOW}0{Color.RESET} → Exit")
    print(f"{Color.CYAN}{'═'*55}{Color.RESET}")
    print(f"  Listening for device messages in background...")
    print(f"{Color.CYAN}{'─'*55}{Color.RESET}")

def run_demo_sequence(client):
    log("DEMO", "Starting automated demo sequence...", Color.BOLD)
    
    steps = [
        (2,  "zone_1", "FIRE",      "FIRE EMERGENCY! Evacuate Zone 1 via stairwell A immediately. Do not use elevators.", 3),
        (5,  "zone_2", "MEDICAL",   "Medical emergency in Zone 2. Clear the area. Paramedics en route.", 2),
        (5,  "zone_3", "SECURITY",  "Security alert in Zone 3. Lockdown initiated. Remain at your workstations.", 3),
        (5,  "all",    "CLEAR",     "All clear. Emergencies resolved. Resume normal operations.", 0),
    ]
    
    for delay, zone, atype, msg, sev in steps:
        log("DEMO", f"Waiting {delay}s...", Color.YELLOW)
        time.sleep(delay)
        if atype == "CLEAR":
            send_clear(client)
        else:
            send_alert(client, zone, atype, msg, sev)
    
    log("DEMO", "Demo sequence complete!", Color.GREEN)

# ── MAIN ─────────────────────────────────────────────
def main():
    print(f"\n{Color.BOLD}{Color.CYAN}")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     ZONECAST NEXUS — MQTT Test Tool      ║")
    print("  ║     Connecting to HiveMQ broker...       ║")
    print(f"  ╚══════════════════════════════════════════╝{Color.RESET}\n")

    client = mqtt.Client(client_id=CLIENT_ID, clean_session=True)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    try:
        client.connect(BROKER, PORT, keepalive=60)
    except Exception as e:
        log("ERROR", f"Could not connect: {e}", Color.RED)
        print("\nMake sure you have internet access and paho-mqtt installed:")
        print("  pip install paho-mqtt")
        sys.exit(1)

    client.loop_start()
    time.sleep(1.5)  # Wait for connection

    while True:
        print_menu()
        try:
            choice = input(f"\n  {Color.BOLD}Enter choice: {Color.RESET}").strip()
        except KeyboardInterrupt:
            break

        if choice == "1":
            send_alert(client, "zone_1", "FIRE",
                "FIRE EMERGENCY! Evacuate Zone 1 immediately via stairwell A. Do not use elevators. Proceed to assembly point.", 3)
        elif choice == "2":
            send_alert(client, "zone_2", "FIRE",
                "FIRE EMERGENCY! Evacuate Zone 2 immediately via stairwell B. Keep low. Do not use elevators.", 3)
        elif choice == "3":
            send_alert(client, "zone_3", "MEDICAL",
                "Medical emergency in Zone 3. Clear the corridor immediately. Do not block access. Paramedics are en route.", 2)
        elif choice == "4":
            send_alert(client, "all", "EARTHQUAKE",
                "EARTHQUAKE! DROP COVER AND HOLD ON. Move away from windows. Take cover under sturdy furniture now.", 3, 120)
        elif choice == "5":
            send_alert(client, "all", "DRILL",
                "EMERGENCY DRILL IN PROGRESS. This is a test. Please follow all evacuation procedures to the nearest exit.", 1, 30)
        elif choice == "6":
            send_alert(client, "zone_1", "SECURITY",
                "SECURITY LOCKDOWN. Lock all doors. Move away from windows. Do not open doors for anyone. Await all-clear.", 3)
        elif choice == "7":
            send_clear(client)
        elif choice == "8":
            print()
            zone    = input("  Zone ID (e.g. zone_1 or all): ").strip()
            atype   = input("  Alert type (FIRE/EARTHQUAKE/MEDICAL/SECURITY/GAS/DRILL): ").strip().upper()
            msg     = input("  Message: ").strip()
            sev     = int(input("  Severity (1/2/3): ").strip() or "3")
            dur     = int(input("  Duration seconds (0=indefinite): ").strip() or "60")
            send_alert(client, zone, atype, msg, sev, dur)
        elif choice == "9":
            run_demo_sequence(client)
        elif choice == "0":
            break
        else:
            log("ERROR", "Invalid choice. Try again.", Color.YELLOW)

    log("MQTT", "Disconnecting...", Color.YELLOW)
    client.loop_stop()
    client.disconnect()
    print(f"\n{Color.GREEN}Goodbye!{Color.RESET}\n")

if __name__ == "__main__":
    main()
