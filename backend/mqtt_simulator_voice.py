#!/usr/bin/env python3
"""
ZoneCast NEXUS - ESP32 Device Simulator v3.0
Smart Zoned Emergency Communication System
HackArena'26 - IoT & Smart Infrastructure

Requirements:
    pip install paho-mqtt pyttsx3

Usage:
    python mqtt_simulator.py

Voice Engine (auto-detected):
    Windows : SAPI5 via pyttsx3 or PowerShell fallback
    macOS   : pyttsx3 or system 'say' command
    Linux   : pyttsx3 or espeak fallback
"""

import paho.mqtt.client as mqtt
import json
import time
import threading
import os
import platform
import uuid
import random
from datetime import datetime

# ──────────────────────────────────────────────────────────────────
#  OPTIONAL: pyttsx3 for best voice quality
# ──────────────────────────────────────────────────────────────────
try:
    import pyttsx3
    TTS_ENGINE = "pyttsx3"
except ImportError:
    TTS_ENGINE = "system"

# ──────────────────────────────────────────────────────────────────
#  MQTT CONFIG
# ──────────────────────────────────────────────────────────────────
BROKER   = "broker.hivemq.com"
PORT     = 1883
PREFIX   = "zonecast"

# ──────────────────────────────────────────────────────────────────
#  ZONE DEFINITIONS
# ──────────────────────────────────────────────────────────────────
ZONES = [
    {"id": "zone_1", "device_id": "ZC_Z1_001", "label": "Zone 1", "desc": "Lobby / Reception",      "floor": 1},
    {"id": "zone_2", "device_id": "ZC_Z2_001", "label": "Zone 2", "desc": "Cafeteria / Canteen",     "floor": 1},
    {"id": "zone_3", "device_id": "ZC_Z3_001", "label": "Zone 3", "desc": "Server Room / IT",        "floor": 1},
    {"id": "zone_4", "device_id": "ZC_Z4_001", "label": "Zone 4", "desc": "Office Block A",          "floor": 2},
    {"id": "zone_5", "device_id": "ZC_Z5_001", "label": "Zone 5", "desc": "Conference Room A",       "floor": 2},
    {"id": "zone_6", "device_id": "ZC_Z6_001", "label": "Zone 6", "desc": "Office Block B + Lab",    "floor": 2},
    {"id": "zone_7", "device_id": "ZC_Z7_001", "label": "Zone 7", "desc": "Research Laboratory",     "floor": 3},
    {"id": "zone_8", "device_id": "ZC_Z8_001", "label": "Zone 8", "desc": "Management Floor",        "floor": 3},
    {"id": "zone_9", "device_id": "ZC_Z9_001", "label": "Zone 9", "desc": "Rooftop / Utilities",     "floor": 3},
]

# ──────────────────────────────────────────────────────────────────
#  TERMINAL FORMATTING
# ──────────────────────────────────────────────────────────────────
class Clr:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BLUE   = "\033[94m"
    WHITE  = "\033[97m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

# ──────────────────────────────────────────────────────────────────
#  ALERT METADATA
# ──────────────────────────────────────────────────────────────────
ALERT_META = {
    "FIRE":       {"color": Clr.RED,    "header_fill": "#", "voice_prefix": "FIRE EMERGENCY"},
    "EARTHQUAKE": {"color": Clr.YELLOW, "header_fill": "=", "voice_prefix": "EARTHQUAKE WARNING"},
    "MEDICAL":    {"color": Clr.CYAN,   "header_fill": "-", "voice_prefix": "MEDICAL EMERGENCY"},
    "SECURITY":   {"color": Clr.BLUE,   "header_fill": "#", "voice_prefix": "SECURITY ALERT"},
    "GAS":        {"color": Clr.YELLOW, "header_fill": "~", "voice_prefix": "GAS LEAK WARNING"},
    "DRILL":      {"color": Clr.GREEN,  "header_fill": ".", "voice_prefix": "EMERGENCY DRILL"},
    "ALERT":      {"color": Clr.RED,    "header_fill": "#", "voice_prefix": "EMERGENCY ALERT"},
}

SEV_LABEL = {1: "LOW",      2: "MEDIUM",   3: "CRITICAL"}
SEV_COLOR = {1: Clr.GREEN,  2: Clr.YELLOW, 3: Clr.RED}
SEV_BEEP  = {1: "Slow  500ms on / 700ms off",
             2: "Medium 250ms on / 250ms off",
             3: "Fast   80ms on  /  80ms off  [CRITICAL]"}

def now():
    return datetime.now().strftime("%H:%M:%S")

def datestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ──────────────────────────────────────────────────────────────────
#  TEXT WRAP UTILITY
# ──────────────────────────────────────────────────────────────────
def wrap_text(text, width):
    """Wrap text into lines no longer than width characters."""
    words  = text.split()
    lines  = []
    current = ""
    for word in words:
        if len(current) + len(word) + (1 if current else 0) <= width:
            current += (" " if current else "") + word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

# ──────────────────────────────────────────────────────────────────
#  VOICE ENGINE
# ──────────────────────────────────────────────────────────────────
_tts_engine   = None
_tts_lock     = threading.Lock()
_voice_thread = None
_voice_stop   = threading.Event()

def init_tts():
    global _tts_engine
    if TTS_ENGINE != "pyttsx3":
        return
    try:
        _tts_engine = pyttsx3.init()
        _tts_engine.setProperty("rate",   148)
        _tts_engine.setProperty("volume", 1.0)
        voices = _tts_engine.getProperty("voices")
        for v in voices:
            name = v.name.lower()
            if any(k in name for k in ["zira", "hazel", "samantha", "female", "woman"]):
                _tts_engine.setProperty("voice", v.id)
                break
    except Exception as e:
        print(f"  [VOICE] pyttsx3 init error: {e}. Using system fallback.")
        _tts_engine = None

def _os_speak(text):
    """OS-level TTS fallback."""
    system = platform.system()
    safe   = text.replace('"', "").replace("'", "").replace(";", "").replace("\n", " ")
    try:
        if system == "Darwin":
            os.system(f'say -r 148 "{safe}"')
        elif system == "Linux":
            os.system(f'espeak -s 145 -a 200 "{safe}" 2>/dev/null')
        elif system == "Windows":
            ps = (
                f'Add-Type -AssemblyName System.Speech; '
                f'$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                f'$s.Rate = 1; $s.Volume = 100; $s.Speak("{safe}")'
            )
            os.system(f'powershell -NoProfile -Command "{ps}" 2>nul')
    except Exception:
        pass

def speak_once(text):
    """Speak text exactly once, blocking until complete."""
    with _tts_lock:
        try:
            if _tts_engine:
                _tts_engine.say(text)
                _tts_engine.runAndWait()
            else:
                _os_speak(text)
        except Exception:
            try:
                _os_speak(text)
            except Exception:
                pass

def speak_repeating(announcement_text, interval_seconds, stop_event):
    """
    Speak the announcement, pause, then repeat until stop_event is set.
    This runs in its own thread so it doesn't block anything else.
    """
    while not stop_event.is_set():
        speak_once(announcement_text)
        # Wait between repetitions, but check stop_event frequently
        for _ in range(interval_seconds * 2):
            if stop_event.is_set():
                return
            time.sleep(0.5)

def stop_voice():
    """Stop the repeating voice loop."""
    global _voice_thread, _voice_stop
    _voice_stop.set()
    if _tts_engine:
        try:
            _tts_engine.stop()
        except Exception:
            pass

def start_repeating_voice(text, interval=12):
    """Start a background thread that repeats the voice alert every interval seconds."""
    global _voice_thread, _voice_stop
    # Stop any existing voice loop first
    stop_voice()
    time.sleep(0.3)
    # Start fresh
    _voice_stop = threading.Event()
    _voice_thread = threading.Thread(
        target=speak_repeating,
        args=(text, interval, _voice_stop),
        daemon=True
    )
    _voice_thread.start()

def build_announcement(zone_label, zone_desc, floor, alert_type, message, severity):
    sev_word = {1: "advisory level", 2: "warning level", 3: "critical level"}[min(severity, 3)]
    prefix   = ALERT_META.get(alert_type, ALERT_META["ALERT"])["voice_prefix"]
    return (
        f"Attention. Attention. {prefix}. "
        f"{zone_label}, {zone_desc}, Floor {floor}. "
        f"Severity: {sev_word}. "
        f"{message}. "
        f"This is an automated ZoneCast emergency broadcast. "
        f"Please follow all emergency procedures immediately."
    )

def build_clear_announcement(zone_label, zone_desc):
    return (
        f"All clear. All clear. "
        f"{zone_label}, {zone_desc}. "
        f"The emergency has been resolved. "
        f"Normal operations may resume. "
        f"This is an automated ZoneCast all-clear broadcast."
    )

# ──────────────────────────────────────────────────────────────────
#  DISPLAY FUNCTIONS
# ──────────────────────────────────────────────────────────────────
WIDTH = 62   # Total box width (inner content width = WIDTH - 4)
INNER = WIDTH - 4

def divider(char="-", color=Clr.DIM):
    print(f"{color}  +{char * (WIDTH - 2)}+{Clr.RESET}")

def box_row(text, color=Clr.RESET, align="left"):
    if align == "center":
        content = text.center(INNER)
    elif align == "right":
        content = text.rjust(INNER)
    else:
        content = text.ljust(INNER)
    print(f"  |{color} {content} {Clr.RESET}|")

def blank_row():
    box_row("")

def print_boot_screen(zone):
    """Simulate ESP32 OLED boot sequence."""
    col = Clr.CYAN
    print(f"\n{col}  +{'-' * (WIDTH - 2)}+")
    box_row(f"ZoneCast NEXUS  v3.0  [ BOOTING ]", col, "center")
    divider("-", col)
    box_row(f"Device  : {zone['device_id']}", col)
    box_row(f"Zone    : {zone['label']}  -  {zone['desc']}", col)
    box_row(f"Floor   : {zone['floor']}", col)
    divider("-", col)

    # Loading bar
    total_steps = INNER - 2
    for i in range(0, total_steps + 1, 4):
        filled  = "#" * i
        empty   = "." * (total_steps - i)
        pct     = int(i / total_steps * 100)
        bar_str = f"[{filled}{empty}]  {pct:3d}%"
        print(f"\r  | {col}{bar_str.ljust(INNER)}{Clr.RESET} |", end="", flush=True)
        time.sleep(0.03)

    print()
    box_row("Status  : ONLINE  -  Listening for alerts", Clr.GREEN)
    print(f"  +{'-' * (WIDTH - 2)}+{Clr.RESET}")

def print_standby_screen(zone):
    col = Clr.DIM
    print(f"\n{col}  +{'-' * (WIDTH - 2)}+")
    box_row("ZoneCast NEXUS  v3.0  [ STANDBY ]", col, "center")
    divider("-", col)
    box_row(f"Zone    : {zone['label']}", col)
    box_row(f"Location: {zone['desc']}", col)
    box_row(f"Floor   : {zone['floor']}", col)
    box_row(f"MQTT    : Connected  -  {BROKER}", col)
    box_row(f"Status  : STANDBY  -  Listening for alerts", col)
    print(f"  +{'-' * (WIDTH - 2)}+{Clr.RESET}")

def print_alert_screen(zone, data):
    """
    Render a full terminal OLED simulation of the alert screen.
    Mirrors exactly what the ESP32 OLED displays.
    """
    atype    = data.get("type",     "ALERT")
    message  = data.get("message",  "Emergency!")
    severity = data.get("severity", 2)
    ts_str   = data.get("timestamp", datestamp())

    meta     = ALERT_META.get(atype, ALERT_META["ALERT"])
    col      = meta["color"]
    fill     = meta["header_fill"]
    sev_col  = SEV_COLOR[min(severity, 3)]
    sev_lbl  = SEV_LABEL[min(severity, 3)]
    beep_str = SEV_BEEP[min(severity, 3)]

    # Word-wrap the message
    msg_lines = wrap_text(message, INNER - 2)

    # Severity progress bar (text-based)
    bar_filled = int((severity / 3) * (INNER - 10))
    bar_empty  = (INNER - 10) - bar_filled
    sev_bar    = "[" + "#" * bar_filled + "." * bar_empty + "]"

    print(f"\n{col}  +{fill * (WIDTH - 2)}+")

    # Alert type header
    header = f"  {atype} ALERT  |  {zone['label']}  |  Floor {zone['floor']}  "
    box_row(header, col, "center")

    divider(fill, col)

    # Location
    box_row(f"Location   : {zone['desc']}", col)
    box_row(f"Device     : {zone['device_id']}", col)
    box_row(f"Received   : {now()}", col)

    divider("-", col)

    # Message block
    box_row("MESSAGE :", col)
    for ln in msg_lines:
        box_row(f"  {ln}", Clr.WHITE)

    # Pad to at least 3 message lines for consistent look
    for _ in range(max(0, 3 - len(msg_lines))):
        blank_row()

    divider("-", col)

    # Severity block
    sev_display = f"{sev_lbl:8}  {sev_bar}"
    print(f"  | {col}Severity   : {sev_col}{Clr.BOLD}{sev_display}{Clr.RESET}{col}{' ' * max(0, INNER - 13 - len(sev_display))} {Clr.RESET}|")

    box_row(f"Buzzer     : {beep_str}", col)
    box_row(f"LED        : {'Flashing Red (continuous)' if severity == 3 else 'Blinking'}", col)
    box_row(f"Voice      : Repeating every 12 seconds", col)

    divider("-", col)
    box_row("Press ACK button on device to acknowledge.", col)
    print(f"  +{fill * (WIDTH - 2)}+{Clr.RESET}")

    print(f"\n  {Clr.BOLD}[VOICE]{Clr.RESET}  Announcement started - repeating until cleared.\n")

def print_clear_screen(zone):
    col = Clr.GREEN
    print(f"\n{col}  +{'=' * (WIDTH - 2)}+")
    box_row("ALL CLEAR", col, "center")
    divider("=", col)
    box_row(f"Zone     : {zone['label']}  -  {zone['desc']}", col)
    box_row(f"Time     : {now()}", col)
    box_row(f"Status   : Emergency resolved.", col)
    box_row(f"Action   : Normal operations may resume.", col)
    box_row(f"Voice    : All-clear announcement playing.", col)
    print(f"  +{'=' * (WIDTH - 2)}+{Clr.RESET}\n")

def print_status_table(devices):
    """Print a compact status table for all simulated devices."""
    online_count   = sum(1 for d in devices if d.status == "online")
    alerting_count = sum(1 for d in devices if d.status == "alert_active")
    offline_count  = sum(1 for d in devices if d.status == "offline")

    print(f"\n{Clr.DIM}  {'─' * (WIDTH + 2)}")
    print(f"  System Status  |  {Clr.GREEN}Online: {online_count}{Clr.DIM}  "
          f"|  {Clr.RED}Alerting: {alerting_count}{Clr.DIM}  "
          f"|  Offline: {offline_count}  "
          f"|  {now()}")
    print(f"  {'─' * (WIDTH + 2)}")

    # Column headers
    print(f"  {'Device':<14}  {'Zone':<8}  {'Location':<25}  {'Floor':<6}  {'Status':<12}")
    print(f"  {'─'*14}  {'─'*8}  {'─'*25}  {'─'*6}  {'─'*12}")

    for d in devices:
        if d.status == "alert_active":
            status_str = f"{Clr.RED}ALERTING{Clr.DIM}"
            atype = d.alert.get("type", "?") if d.alert else "?"
            status_str = f"{Clr.RED}ALERTING ({atype}){Clr.DIM}"
        elif d.status == "online":
            status_str = f"{Clr.GREEN}ONLINE{Clr.DIM}"
        else:
            status_str = f"OFFLINE"

        print(f"  {d.zone['device_id']:<14}  {d.zone['id']:<8}  "
              f"{d.zone['desc']:<25}  {str(d.zone['floor']):<6}  {status_str}{Clr.RESET}")

    print(f"{Clr.DIM}  {'─' * (WIDTH + 2)}{Clr.RESET}\n")

# ──────────────────────────────────────────────────────────────────
#  GLOBAL DEVICE LIST (for status table access)
# ──────────────────────────────────────────────────────────────────
_all_devices = []

# ──────────────────────────────────────────────────────────────────
#  ZONE DEVICE CLASS
# ──────────────────────────────────────────────────────────────────
class ZoneDevice:
    def __init__(self, zone_info, voice_enabled=True):
        self.zone          = zone_info
        self.status        = "offline"
        self.alert         = None
        self.client        = None
        self.running       = True
        self.voice_enabled = voice_enabled
        self._stop_voice   = threading.Event()
        self._voice_thread = None

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
            "alert_type": self.alert.get("type", "") if self.alert else "",
            "fw_version": "3.0-SIM",
        })
        topic = f"{PREFIX}/status/{self.zone['device_id']}"
        self.client.publish(topic, payload, qos=0, retain=True)

    def _start_repeating_voice(self, announcement):
        """Stop any current voice loop and start a new repeating one for this device."""
        # Signal old thread to stop
        self._stop_voice.set()
        if self._voice_thread and self._voice_thread.is_alive():
            self._voice_thread.join(timeout=1.5)

        # Fresh stop event for new loop
        self._stop_voice = threading.Event()

        def _loop(text, stop_evt):
            while not stop_evt.is_set():
                speak_once(text)
                # Wait 12 seconds between repeats, checking for stop every 0.5s
                for _ in range(24):
                    if stop_evt.is_set():
                        return
                    time.sleep(0.5)

        self._voice_thread = threading.Thread(
            target=_loop,
            args=(announcement, self._stop_voice),
            daemon=True
        )
        self._voice_thread.start()

    def _stop_voice_loop(self):
        self._stop_voice.set()
        if _tts_engine:
            try:
                _tts_engine.stop()
            except Exception:
                pass

    def on_alert(self, payload_str):
        try:
            data  = json.loads(payload_str)
            atype = data.get("type", "ALERT")

            # ── ALL-CLEAR ──────────────────────────────────────
            if atype == "CLEAR":
                self._stop_voice_loop()
                self.alert  = None
                self.status = "online"
                self.publish_status("online")
                print_clear_screen(self.zone)
                print_status_table(_all_devices)

                if self.voice_enabled:
                    ann = build_clear_announcement(
                        self.zone["label"], self.zone["desc"]
                    )
                    # Play once - no repeat needed for all-clear
                    threading.Thread(target=speak_once, args=(ann,), daemon=True).start()
                return

            # ── ACTIVE ALERT ───────────────────────────────────
            self.alert  = data
            self.status = "alert_active"
            self.publish_status("alert_active")

            print_alert_screen(self.zone, data)
            print_status_table(_all_devices)

            if self.voice_enabled:
                ann = build_announcement(
                    self.zone["label"],
                    self.zone["desc"],
                    self.zone["floor"],
                    atype,
                    data.get("message", "Emergency."),
                    data.get("severity", 2),
                )
                self._start_repeating_voice(ann)

        except Exception as e:
            print(f"  [ERROR] {self.zone['device_id']} parse error: {e}")

    def heartbeat_loop(self):
        while self.running:
            time.sleep(30)
            if self.running:
                self.publish_status(self.status)

# ──────────────────────────────────────────────────────────────────
#  SIMULATOR RUNNER
# ──────────────────────────────────────────────────────────────────
def run_simulator(selected_zones, voice_enabled):
    global _all_devices
    clients = []
    devices = []

    print(f"\n{Clr.BOLD}{Clr.CYAN}  {'=' * WIDTH}")
    print(f"  ZoneCast NEXUS  -  Device Simulator v3.0")
    print(f"  Zones      : {len(selected_zones)}")
    print(f"  Voice      : {'Enabled  -  Repeats every 12s until cleared' if voice_enabled else 'Disabled'}")
    print(f"  TTS Engine : {TTS_ENGINE}")
    print(f"  Broker     : {BROKER}:{PORT}")
    print(f"  {'=' * WIDTH}{Clr.RESET}\n")

    init_tts()

    for zone_info in selected_zones:
        device    = ZoneDevice(zone_info, voice_enabled=voice_enabled)
        client_id = f"ZC_{zone_info['id']}_{uuid.uuid4().hex[:8]}"
        client    = mqtt.Client(client_id=client_id, clean_session=True)
        client.reconnect_delay_set(min_delay=3, max_delay=30)

        def make_callbacks(dev):
            def on_connect(c, ud, flags, rc):
                RC_CODES = {
                    1: "Wrong protocol version",
                    2: "Client ID rejected",
                    3: "Broker unavailable",
                    4: "Bad credentials",
                    5: "Not authorized (too many connections - will retry)",
                }
                if rc == 0:
                    c.subscribe(f"{PREFIX}/{dev.zone['id']}/alert", 1)
                    c.subscribe(f"{PREFIX}/all/alert", 1)
                    dev.status = "online"
                    dev.publish_status("online")
                    print_boot_screen(dev.zone)
                else:
                    reason = RC_CODES.get(rc, f"Unknown error rc={rc}")
                    print(f"  [{now()}] {dev.zone['device_id']}  connect failed: {reason}")

            def on_message(c, ud, msg):
                dev.on_alert(msg.payload.decode())

            def on_disconnect(c, ud, rc):
                dev.status = "offline"
                if rc != 0:
                    wait = random.randint(5, 15)
                    print(f"  [{now()}] {dev.zone['device_id']}  disconnected (rc={rc}) - reconnecting in {wait}s")
                    def _reconnect():
                        time.sleep(wait)
                        try:
                            c.reconnect()
                        except Exception as e:
                            print(f"  [{now()}] {dev.zone['device_id']}  reconnect failed: {e}")
                    threading.Thread(target=_reconnect, daemon=True).start()

            return on_connect, on_message, on_disconnect

        cb_conn, cb_msg, cb_disc = make_callbacks(device)
        client.on_connect    = cb_conn
        client.on_message    = cb_msg
        client.on_disconnect = cb_disc
        device.client        = client
        devices.append(device)

        try:
            client.connect(BROKER, PORT, keepalive=60)
            client.loop_start()
            clients.append(client)
            time.sleep(1.5)  # HiveMQ rate limit: stagger connections
        except Exception as e:
            print(f"  [ERROR] Could not connect {zone_info['device_id']}: {e}")

    _all_devices = devices

    # Start heartbeat threads
    for device in devices:
        t = threading.Thread(target=device.heartbeat_loop, daemon=True)
        t.start()

    # Wait for all MQTT connections to settle
    time.sleep(2.0)

    print(f"\n{Clr.GREEN}  All {len(devices)} device(s) connected and listening.{Clr.RESET}")
    print(f"  Open the dashboard or run mqtt_test.py to send an alert.")
    print(f"  Press Ctrl+C to stop.\n")

    print_status_table(devices)

    # Voice test
    if voice_enabled:
        print(f"  [VOICE]  Playing voice test...")
        speak_once("ZoneCast NEXUS ready. Voice alerts active.")
        print(f"  [VOICE]  Test complete. Alerts will repeat every 12 seconds.\n")

    try:
        while True:
            time.sleep(10)
            print_status_table(devices)
    except KeyboardInterrupt:
        print(f"\n  Shutting down...")
        for device in devices:
            device.running = False
            device._stop_voice_loop()
            device.publish_status("offline")
        time.sleep(1)
        for client in clients:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
        print(f"  All devices disconnected. Goodbye.\n")

# ──────────────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────────────
def main():
    os.system("cls" if platform.system() == "Windows" else "clear")

    print(f"{Clr.BOLD}{Clr.CYAN}")
    print("  ZoneCast NEXUS  -  ESP32 Device Simulator v3.0")
    print("  Smart Zoned Emergency Communication System")
    print(f"  HackArena'26  -  IoT and Smart Infrastructure")
    print(f"{Clr.RESET}")
    print(f"  {'─' * 50}")

    # Zone selection
    print(f"\n  Select zones to simulate:\n")
    for i, z in enumerate(ZONES):
        fc = [Clr.GREEN, Clr.YELLOW, Clr.CYAN][z["floor"] - 1]
        print(f"  {i+1:2}.  {fc}{z['device_id']}{Clr.RESET}  -  {z['label']:<8}  "
              f"{z['desc']:<28}  Floor {z['floor']}")

    print(f"\n   A  -  All 9 zones")
    print(f"  F1  -  Floor 1 only  (Zones 1-3)")
    print(f"  F2  -  Floor 2 only  (Zones 4-6)")
    print(f"  F3  -  Floor 3 only  (Zones 7-9)")
    print(f"\n  Or enter zone numbers separated by commas  e.g.  1,3,5")

    raw = input(f"\n  Choice: ").strip().upper()

    if raw == "A":
        selected = ZONES
    elif raw == "F1":
        selected = ZONES[0:3]
    elif raw == "F2":
        selected = ZONES[3:6]
    elif raw == "F3":
        selected = ZONES[6:9]
    else:
        try:
            nums     = [int(x.strip()) - 1 for x in raw.split(",")]
            selected = [ZONES[n] for n in nums if 0 <= n < len(ZONES)]
        except ValueError:
            print(f"  Invalid input. Defaulting to Zone 1.")
            selected = [ZONES[0]]

    if not selected:
        print(f"  No valid zones selected. Exiting.")
        return

    # Voice selection
    print(f"\n  {'─' * 50}")
    print(f"\n  Voice Alerts")
    print(f"  When an alert arrives, the system will speak the announcement")
    print(f"  aloud and repeat it every 12 seconds until cleared.")
    print(f"  TTS engine detected: {TTS_ENGINE}")

    v_raw         = input(f"\n  Enable voice alerts? [Y/n]: ").strip().lower()
    voice_enabled = (v_raw != "n")

    print()
    run_simulator(selected, voice_enabled)


if __name__ == "__main__":
    main()
