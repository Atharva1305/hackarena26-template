#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║   ZoneCast NEXUS — ESP32 Device Simulator                        ║
║                                                                  ║
║   Use this to simulate 1–9 ESP32 zone nodes WITHOUT real         ║
║   hardware. Perfect for demo prep or if devices aren't ready.    ║
║                                                                  ║
║   HOW TO RUN:                                                    ║
║     pip install paho-mqtt                                        ║
║     python mqtt_simulator.py                                     ║
║                                                                  ║
║   WHAT IT DOES:                                                  ║
║     - Creates virtual ESP32 devices for each zone               ║
║     - Publishes heartbeat status every 30 seconds               ║
║     - Subscribes to zone alert topics                           ║
║     - When alert arrives: prints it as if OLED is showing it    ║
║     - When CLEAR arrives: clears the "device"                   ║
║     - Dashboard will show all zones as ONLINE / ALERTING        ║
╚══════════════════════════════════════════════════════════════════╝
"""

import paho.mqtt.client as mqtt
import json
import time
import threading
import sys
from datetime import datetime

BROKER = "broker.hivemq.com"
PORT   = 1883
PREFIX = "zonecast"

# Define all 9 zones
ZONES = [
    {"id": "zone_1", "device_id": "ZC_Z1_001", "label": "Zone 1", "desc": "Lobby/Reception",       "floor": 1},
    {"id": "zone_2", "device_id": "ZC_Z2_001", "label": "Zone 2", "desc": "Cafeteria/Canteen",      "floor": 1},
    {"id": "zone_3", "device_id": "ZC_Z3_001", "label": "Zone 3", "desc": "Server Room/IT",         "floor": 1},
    {"id": "zone_4", "device_id": "ZC_Z4_001", "label": "Zone 4", "desc": "Office Block A",         "floor": 2},
    {"id": "zone_5", "device_id": "ZC_Z5_001", "label": "Zone 5", "desc": "Conference Room A",      "floor": 2},
    {"id": "zone_6", "device_id": "ZC_Z6_001", "label": "Zone 6", "desc": "Office Block B + Lab",   "floor": 2},
    {"id": "zone_7", "device_id": "ZC_Z7_001", "label": "Zone 7", "desc": "Research Laboratory",    "floor": 3},
    {"id": "zone_8", "device_id": "ZC_Z8_001", "label": "Zone 8", "desc": "Management Floor",       "floor": 3},
    {"id": "zone_9", "device_id": "ZC_Z9_001", "label": "Zone 9", "desc": "Rooftop/Utilities",      "floor": 3},
]

# Terminal colors
R='\033[91m'; G='\033[92m'; Y='\033[93m'; C='\033[96m'; B='\033[94m'; W='\033[1m'; X='\033[0m'

def ts():
    return datetime.now().strftime("%H:%M:%S")

class ZoneDevice:
    def __init__(self, zone_info):
        self.zone    = zone_info
        self.status  = "online"
        self.alert   = None
        self.client  = None
        self.running = True

    def publish_status(self, status):
        self.status = status
        payload = json.dumps({
            "device_id":  self.zone["device_id"],
            "zone":       self.zone["id"],
            "zone_label": self.zone["label"],
            "status":     status,
            "ip":         f"192.168.1.{10 + ZONES.index(self.zone)}",
            "rssi":       -45 - (ZONES.index(self.zone) * 2),
            "uptime_s":   int(time.time() % 86400),
            "free_heap":  180000,
            "alert_type": self.alert.get("type","") if self.alert else "",
            "fw_version": "3.0-SIM"
        })
        topic = f"{PREFIX}/status/{self.zone['device_id']}"
        self.client.publish(topic, payload, qos=0, retain=True)

    def on_alert(self, payload_str):
        try:
            data = json.loads(payload_str)
            atype = data.get("type", "ALERT")
            
            if atype == "CLEAR":
                self.alert = None
                self.publish_status("online")
                self.print_oled_clear()
                return

            self.alert = data
            self.publish_status("alert_active")
            self.print_oled_alert(data)
        except Exception as e:
            print(f"[SIM] Parse error: {e}")

    def print_oled_alert(self, data):
        idx = ZONES.index(self.zone)
        colors = [R, Y, C, B, G, R, Y, C, B]
        col = colors[idx % len(colors)]
        sev_stars = "★" * data.get("severity", 1) + "☆" * (3 - data.get("severity", 1))
        msg = data.get("message", "")[:50]
        print(f"\n{col}{'─'*60}")
        print(f"  🖥  {self.zone['label']} ({self.zone['desc']}) — FLOOR {self.zone['floor']}")
        print(f"  ┌{'─'*54}┐")
        print(f"  │  !! {data.get('type','ALERT')} ALERT !!  Severity: {sev_stars}        │")
        print(f"  │  {msg:<52}  │")
        print(f"  │  BUZZER: {'FAST BEEP' if data.get('severity',1) >= 3 else 'MEDIUM BEEP' if data.get('severity',1)==2 else 'SLOW BEEP'}    LED: FLASHING               │")
        print(f"  └{'─'*54}┘")
        print(f"  Device: {self.zone['device_id']}{X}")

    def print_oled_clear(self):
        print(f"\n{G}  ✔  {self.zone['label']} — ALL CLEAR — Normal ops resumed{X}")

    def heartbeat_loop(self):
        while self.running:
            time.sleep(30)
            if self.running:
                self.publish_status(self.status)


def run_simulator(selected_zones):
    clients = []
    devices = []

    print(f"\n{W}{C}{'═'*60}")
    print("  ZONECAST NEXUS — DEVICE SIMULATOR")
    print(f"  Simulating {len(selected_zones)} zone(s)")
    print(f"{'═'*60}{X}\n")

    for zone_info in selected_zones:
        device = ZoneDevice(zone_info)
        client_id = f"SIM_{zone_info['device_id']}_{int(time.time())}"
        client = mqtt.Client(client_id=client_id, clean_session=True)

        def make_callbacks(dev):
            def on_connect(c, ud, f, rc):
                if rc == 0:
                    # Subscribe to zone-specific and broadcast topics
                    c.subscribe(f"{PREFIX}/{dev.zone['id']}/alert", 1)
                    c.subscribe(f"{PREFIX}/all/alert", 1)
                    dev.publish_status("online")
                    print(f"{G}[{ts()}] {dev.zone['device_id']} ONLINE — Sub: {PREFIX}/{dev.zone['id']}/alert{X}")

            def on_message(c, ud, msg):
                dev.on_alert(msg.payload.decode())

            return on_connect, on_message

        on_conn, on_msg = make_callbacks(device)
        client.on_connect = on_conn
        client.on_message = on_msg
        device.client = client
        devices.append(device)

        try:
            client.connect(BROKER, PORT, keepalive=60)
            client.loop_start()
            clients.append(client)
            time.sleep(0.3)  # Stagger connections
        except Exception as e:
            print(f"{R}[ERROR] Could not connect {zone_info['device_id']}: {e}{X}")

    # Start heartbeat threads
    for device in devices:
        t = threading.Thread(target=device.heartbeat_loop, daemon=True)
        t.start()

    print(f"\n{G}All {len(devices)} virtual devices connected and listening.{X}")
    print(f"{C}Dashboard will now show these zones as ONLINE.{X}")
    print(f"{Y}Send an alert from the dashboard or mqtt_test.py to see devices respond.{X}")
    print(f"\n{W}Press Ctrl+C to stop the simulator.{X}\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{Y}Shutting down simulator...{X}")
        for device in devices:
            device.running = False
            device.publish_status("offline")
        time.sleep(1)
        for client in clients:
            client.loop_stop()
            client.disconnect()
        print(f"{G}All virtual devices disconnected.{X}\n")


def main():
    print(f"\n{W}{C}")
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║    ZONECAST NEXUS — ESP32 Device Simulator   ║")
    print("  ╚══════════════════════════════════════════════╝")
    print(f"{X}")
    print("  Which zones do you want to simulate?\n")
    
    for i, z in enumerate(ZONES):
        print(f"  {Y}{i+1}{X} → {z['label']} ({z['desc']}) — Floor {z['floor']}")
    
    print(f"\n  {Y}A{X} → Simulate ALL 9 zones")
    print(f"  {Y}F1{X} → Floor 1 only (Zones 1-3)")
    print(f"  {Y}F2{X} → Floor 2 only (Zones 4-6)")
    print(f"  {Y}F3{X} → Floor 3 only (Zones 7-9)")
    
    print(f"\n  Or enter zone numbers separated by commas (e.g. 1,2,3)")
    
    choice = input(f"\n  {W}Your choice: {X}").strip().upper()
    
    if choice == "A":
        selected = ZONES
    elif choice == "F1":
        selected = ZONES[0:3]
    elif choice == "F2":
        selected = ZONES[3:6]
    elif choice == "F3":
        selected = ZONES[6:9]
    else:
        try:
            nums = [int(x.strip())-1 for x in choice.split(",")]
            selected = [ZONES[n] for n in nums if 0 <= n < len(ZONES)]
        except:
            print(f"{R}Invalid choice. Simulating Zone 1 only.{X}")
            selected = [ZONES[0]]
    
    if not selected:
        print(f"{R}No valid zones selected. Exiting.{X}")
        return
    
    run_simulator(selected)

if __name__ == "__main__":
    main()
