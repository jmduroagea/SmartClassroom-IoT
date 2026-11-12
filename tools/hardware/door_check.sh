#!/usr/bin/env bash
# Hardware check of the DOOR Pi (Pi 6): every device on its own, without the brain.
# Read-only: it changes nothing on the Pi. Safe to repeat. Issues #11 and #70.
#
#     ./tools/hardware/door_check.sh SERVER_IP        e.g. 10.12.220.101
#
# Run it after setup_door.sh, with the door program stopped (it uses the GPIO pins
# and the serial port). Follow the instructions on screen. Everything is also saved
# to ~/check_door.txt, and the measured values are listed again at the end as
# "FACT key=value": paste that summary to Claude, plus your notes.
set -u

# ---- Settings ----------------------------------------------------------------
SERVER_IP="${1:-}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$HOME/smartroom-venv/bin/python"
LOG_FILE="$HOME/check_door.txt"
BROKER_PORT=1883
MQTT_ROUNDTRIPS=10
CONFIG_TXT=/boot/config.txt
CMDLINE_TXT=/boot/cmdline.txt
SERIAL_LINK=/dev/serial0
PIR_WATCH_SECONDS=30
RFID_WATCH_SECONDS=20
RFID_OTHER_BAUD=115200
RFID_OTHER_BAUD_SECONDS=5

if [[ ! "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 SERVER_IP   (the IP of the Server Pi, e.g. 10.12.220.101)"
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "No $PYTHON: run deploy/setup_door.sh first."
  exit 1
fi

exec > >(tee "$LOG_FILE") 2>&1      # everything on screen also goes to the log file
FACTS_FILE="$(mktemp)"
export SERVER_IP BROKER_PORT MQTT_ROUNDTRIPS PIR_WATCH_SECONDS RFID_WATCH_SECONDS
export RFID_OTHER_BAUD RFID_OTHER_BAUD_SECONDS SERIAL_LINK FACTS_FILE
export PYTHONPATH="$REPO_DIR"       # so the checks use the project's own code
export PYTHONUNBUFFERED=1           # show Python output live over ssh

fact() { echo "FACT $1=$2" | tee -a "$FACTS_FILE"; }
step() { echo; echo "===== $* ====="; }
ask() { read -r -p "  $1 [y/n] " answer < /dev/tty; fact "$2" "${answer:-?}"; }

echo "Door Pi check, $(date), repository at $(git -C "$REPO_DIR" log -1 --format=%h)"
fact throttled_at_start "$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"

# ---- First-time configuration (Tutorial 2) ---------------------------------------
step "0/5 FIRST-TIME CONFIGURATION (UART for the RFID reader, as in Tutorial 2)"
fact config_enable_uart "$(grep -c '^enable_uart=1' "$CONFIG_TXT")"
fact config_bt_disabled "$(grep -cE '^dtoverlay=(pi3-)?disable-bt' "$CONFIG_TXT")"
fact console_on_serial "$(grep -cE 'console=(serial0|ttyAMA0|ttyS0)' "$CMDLINE_TXT")"
fact serial0_points_to "$(readlink -f "$SERIAL_LINK" 2>/dev/null || echo missing)"
fact hciuart "$(systemctl is-enabled hciuart 2>/dev/null || echo absent)"
fact user_groups "$(id -nG | tr ' ' ',')"
echo "Expected: enable_uart=1, bt_disabled=1, console_on_serial=0, serial0 -> /dev/ttyAMA0,"
echo "hciuart disabled, and the groups include dialout, gpio and audio."

# ---- MQTT to the Server Pi -----------------------------------------------------
step "1/5 MQTT ROUND TRIP TO THE SERVER PI ($SERVER_IP)"
"$PYTHON" - <<'EOF'
import os, threading, time
import paho.mqtt.client as mqtt
host, port = os.environ["SERVER_IP"], int(os.environ["BROKER_PORT"])
rounds, topic, WAIT_SECONDS = int(os.environ["MQTT_ROUNDTRIPS"]), "glo/hwtest/door", 5
facts = open(os.environ["FACTS_FILE"], "a")
def fact(k, v):
    print(f"FACT {k}={v}"); facts.write(f"FACT {k}={v}\n"); facts.flush()
received = threading.Event()
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = lambda c, u, m: received.set()
try:
    client.connect(host, port, keepalive=10)
except Exception as exc:
    fact("mqtt_connect", f"FAILED ({exc}) - is the Server Pi on, with Mosquitto?"); raise SystemExit
client.subscribe(topic, qos=1); client.loop_start(); time.sleep(1)
times = []
for _ in range(rounds):
    received.clear(); start = time.time()
    client.publish(topic, "ping", qos=1)
    if received.wait(WAIT_SECONDS):
        times.append((time.time() - start) * 1000)
client.loop_stop(); client.disconnect()
fact("mqtt_roundtrips_ok", f"{len(times)}/{rounds}")
if times:
    fact("mqtt_roundtrip_ms_avg", f"{sum(times) / len(times):.1f}")
EOF

# ---- LEDs ----------------------------------------------------------------------
step "2/5 LEDS (watch them)"
"$PYTHON" - <<'EOF'
import time
import RPi.GPIO as GPIO
from door.adapters.leds import PIN_BY_COLOR
from door.core.door_core import PULSE_SECONDS
ON_SECONDS = 2
GPIO.setwarnings(False); GPIO.setmode(GPIO.BCM)
for pin in PIN_BY_COLOR.values():
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
for color, pin in PIN_BY_COLOR.items():
    print(f"  {color} (GPIO{pin}) on for {ON_SECONDS} s"); GPIO.output(pin, GPIO.HIGH)
    time.sleep(ON_SECONDS); GPIO.output(pin, GPIO.LOW); time.sleep(0.5)
print(f"  green pulse: {PULSE_SECONDS} s, as on entry")
GPIO.output(PIN_BY_COLOR["green"], GPIO.HIGH); time.sleep(PULSE_SECONDS)
GPIO.output(PIN_BY_COLOR["green"], GPIO.LOW)
GPIO.cleanup(list(PIN_BY_COLOR.values()))
EOF
ask "Did green light first, then red, then green again? Bright enough to see in the room?" leds_ok

# ---- PIR -----------------------------------------------------------------------
step "3/5 PIR (wave in front of it a few times, with pauses, for ${PIR_WATCH_SECONDS} s)"
"$PYTHON" - <<'EOF'
import os, time
import RPi.GPIO as GPIO
from door.adapters.pir import PIR_PIN
WATCH = int(os.environ["PIR_WATCH_SECONDS"]); POLL_SECONDS = 0.05
facts = open(os.environ["FACTS_FILE"], "a")
def fact(k, v):
    print(f"FACT {k}={v}"); facts.write(f"FACT {k}={v}\n"); facts.flush()
GPIO.setwarnings(False); GPIO.setmode(GPIO.BCM); GPIO.setup(PIR_PIN, GPIO.IN)
start, last, rose_at, highs = time.time(), GPIO.input(PIR_PIN), None, []
print(f"  GPIO{PIR_PIN} at start: {last}")
while time.time() - start < WATCH:
    now, value = time.time(), GPIO.input(PIR_PIN)
    if value != last:
        if value:
            rose_at = now; print(f"  {now - start:5.1f} s  motion")
        elif rose_at is not None:
            highs.append(now - rose_at); print(f"  {now - start:5.1f} s  back to 0 after {highs[-1]:.1f} s")
        last = value
    time.sleep(POLL_SECONDS)
fact("pir_detections", len(highs) + (1 if last else 0))
if highs:
    fact("pir_high_seconds", f"min {min(highs):.1f} max {max(highs):.1f}")
GPIO.cleanup(PIR_PIN)
EOF

# ---- Speaker -------------------------------------------------------------------
step "4/5 USB SPEAKER AND ESPEAK-NG"
fact speaker_cards "$(aplay -l 2>/dev/null | grep -c '^card')"
aplay -l 2>/dev/null | grep '^card'
fact default_card_is_usb "$(aplay -L 2>/dev/null | grep -A1 '^default' | grep -ci usb)"
"$PYTHON" - <<'EOF'
import os, subprocess, time
from common.messages import ALARM_INTERVAL_SECONDS, ALARM_TEXT
from door.adapters.speaker import COMMAND
facts = open(os.environ["FACTS_FILE"], "a")
def fact(k, v):
    print(f"FACT {k}={v}"); facts.write(f"FACT {k}={v}\n"); facts.flush()
for name, text in [("welcome", "Welcome, Gloria. The temperature is 21.5 degrees."), ("alarm", ALARM_TEXT)]:
    print(f"  saying: {text}")
    start = time.time()
    done = subprocess.run(COMMAND, input=text, text=True, capture_output=True)
    fact(f"espeak_{name}_seconds", f"{time.time() - start:.2f}")
    if done.returncode:
        fact(f"espeak_{name}_error", done.stderr.strip())
fact("alarm_interval_seconds", ALARM_INTERVAL_SECONDS)
EOF
ask "Did you HEAR both sentences from the USB speaker?" speaker_heard
echo "  If espeak_alarm_seconds is longer than alarm_interval_seconds, the alarm sentences overlap."

# ---- RFID ----------------------------------------------------------------------
step "5/5 RFID READER (hold a card on it, take it away, try another, for ${RFID_WATCH_SECONDS} s)"
"$PYTHON" - <<'EOF'
import os, time
import serial
from door.adapters.rfid import BAUD_RATE, FRAME_BODY, START, parse_frame
link = os.environ["SERIAL_LINK"]; WATCH = int(os.environ["RFID_WATCH_SECONDS"])
OTHER, OTHER_SECONDS = int(os.environ["RFID_OTHER_BAUD"]), int(os.environ["RFID_OTHER_BAUD_SECONDS"])
facts = open(os.environ["FACTS_FILE"], "a")
def fact(k, v):
    print(f"FACT {k}={v}"); facts.write(f"FACT {k}={v}\n"); facts.flush()
port = serial.Serial(link, BAUD_RATE, timeout=1)
start, frames, bad, ids, raw_shown = time.time(), [], 0, {}, False
while time.time() - start < WATCH:
    if port.read(1) != START:
        continue
    body = port.read(FRAME_BODY)
    if not raw_shown:
        print(f"  first raw frame: {START + body!r}"); raw_shown = True
    card = parse_frame(body)
    if card is None:
        bad += 1; print(f"  {time.time() - start:5.1f} s  bad frame {body!r}")
    else:
        frames.append(time.time()); ids[card] = ids.get(card, 0) + 1
        print(f"  {time.time() - start:5.1f} s  card {card}")
port.close()
fact("rfid_valid_frames", len(frames)); fact("rfid_bad_frames", bad)
fact("rfid_cards", ids or "none")
if len(frames) > 1:
    gaps = [b - a for a, b in zip(frames, frames[1:]) if b - a < 1]
    if gaps:
        fact("rfid_repeat_seconds", f"{min(gaps):.2f}")  # while a card is held on the reader
if not frames:
    print(f"  nothing at {BAUD_RATE}: trying {OTHER} for {OTHER_SECONDS} s, hold a card")
    port = serial.Serial(link, OTHER, timeout=OTHER_SECONDS)
    fact(f"rfid_bytes_at_{OTHER}", repr(port.read(FRAME_BODY + 1))); port.close()
EOF

# 0x0 = fine. Anything else: the power supply is not enough.
fact throttled_at_end "$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"

step "SUMMARY (paste this to Claude, plus what you saw)"
cat "$FACTS_FILE"
rm -f "$FACTS_FILE"
echo; echo "Saved to $LOG_FILE"
