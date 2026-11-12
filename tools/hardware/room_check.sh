#!/usr/bin/env bash
# Hardware check of the ROOM Pi (Pi 26): every device on its own, without the brain.
# Read-only: it changes nothing on the Pi. Safe to repeat. Issues #14, #15 and #70.
#
#     ./tools/hardware/room_check.sh SERVER_IP        e.g. 10.12.220.101
#
# Run it after setup_room.sh, with the program stopped (it uses the microphone and
# the servo). Follow the instructions on screen and answer its questions. Everything is also saved to
# ~/check_room.txt, and the measured values are listed again at the end as
# "FACT key=value": paste that summary to Claude, plus your notes.
set -u

# ---- Settings ----------------------------------------------------------------
SERVER_IP="${1:-}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$HOME/smartroom-venv/bin/python"
LOG_FILE="$HOME/check_room.txt"
BROKER_PORT=1883
MQTT_ROUNDTRIPS=10
DS18B20_READS=15
VOSK_MODEL="$HOME/vosk-model-small-en-us-0.15"
CLIP_SECONDS=4
SAMPLE_RATE=16000
SERVO_HOLD_SECONDS=3

if [[ ! "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 SERVER_IP   (the IP of the Server Pi, e.g. 10.12.220.101)"
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "No $PYTHON: run deploy/setup_room.sh first."
  exit 1
fi

exec > >(tee "$LOG_FILE") 2>&1      # everything on screen also goes to the log file
FACTS_FILE="$(mktemp)"
export SERVER_IP BROKER_PORT MQTT_ROUNDTRIPS DS18B20_READS VOSK_MODEL SAMPLE_RATE
export SERVO_HOLD_SECONDS FACTS_FILE
export PYTHONPATH="$REPO_DIR"       # so the checks use the project's own code
export PYTHONUNBUFFERED=1           # show Python output live over ssh

fact() { echo "FACT $1=$2" | tee -a "$FACTS_FILE"; }
step() { echo; echo "===== $* ====="; }
countdown() { for i in $(seq "$1" -1 1); do echo "  $i..."; sleep 1; done; echo "  NOW"; }
ask() { read -r -p "  $1 [y/n] " answer < /dev/tty; fact "$2" "${answer:-?}"; }
note() { read -r -p "  $1 " answer < /dev/tty; fact "$2" "${answer:-?}"; }
usb_card() { "$1" -l 2>/dev/null | awk '/^card/ && /USB/ {gsub(":",""); print $2; exit}'; }

echo "Room Pi check, $(date), repository at $(git -C "$REPO_DIR" log -1 --format=%h)"
fact throttled_at_start "$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"

# ---- First-time configuration (1-Wire for the DS18B20) ----------------------------
step "0/4 FIRST-TIME CONFIGURATION (1-Wire for the DS18B20)"
fact config_w1_overlay "$(grep -c '^dtoverlay=w1-gpio' /boot/config.txt)"
fact w1_modules_loaded "$(lsmod | grep -cE '^w1_(gpio|therm)')"
fact user_groups "$(id -nG | tr ' ' ',')"
echo "Expected: config_w1_overlay=1, w1_modules_loaded=2 (w1_therm only loads once a probe"
echo "is found), and the groups include gpio and audio."

# ---- MQTT to the Server Pi -----------------------------------------------------
step "1/4 MQTT ROUND TRIP TO THE SERVER PI ($SERVER_IP)"
"$PYTHON" - <<'EOF'
import os, threading, time
import paho.mqtt.client as mqtt
host, port = os.environ["SERVER_IP"], int(os.environ["BROKER_PORT"])
rounds, topic, WAIT_SECONDS = int(os.environ["MQTT_ROUNDTRIPS"]), "glo/hwtest/room", 5
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
    fact("mqtt_roundtrip_ms_max", f"{max(times):.1f}")
EOF

# ---- DS18B20 -------------------------------------------------------------------
step "2/4 DS18B20 TEMPERATURE PROBE (through the program's own adapter)"
"$PYTHON" - <<'EOF'
import glob, os, statistics, time
from room.adapters.ds18b20 import W1_SLAVE_PATTERN, DS18B20Sensor
from room.core.ports import SensorError
READS = int(os.environ["DS18B20_READS"])
facts = open(os.environ["FACTS_FILE"], "a")
def fact(k, v):
    print(f"FACT {k}={v}"); facts.write(f"FACT {k}={v}\n"); facts.flush()
paths = sorted(glob.glob(W1_SLAVE_PATTERN))
fact("ds18b20_found", len(paths))
if not paths:
    print("No probe: check the wiring (data on GPIO4 with 4.7 kOhm to 3.3 V) and that 1-Wire is on.")
    raise SystemExit
print("Raw w1_slave (copy it into tests/unit/test_room_reading.py as a real capture):")
print(open(paths[0]).read())
sensor, values, durations, errors = DS18B20Sensor(), [], [], []
for _ in range(READS):
    start = time.time()
    try:
        values.append(sensor.read())
    except SensorError as exc:
        errors.append(str(exc))
    durations.append(time.time() - start)
fact("ds18b20_read_s_avg", f"{statistics.mean(durations):.2f}")
fact("ds18b20_read_s_max", f"{max(durations):.2f}")
fact("ds18b20_discarded", f"{len(errors)}/{READS} {sorted(set(errors))}")
if values:
    fact("ds18b20_min_max", f"{min(values)}..{max(values)}")
    fact("ds18b20_stdev", f"{statistics.pstdev(values):.3f}")
EOF

# ---- Microphone and Vosk -------------------------------------------------------
step "3/4 MICROPHONE AND VOSK"
MIC_CARD=$(usb_card arecord)
fact mic_usb_card "${MIC_CARD:-none}"
if [[ -z "${MIC_CARD:-}" ]]; then
  echo "No USB microphone found (arecord -l). Skipping Vosk."
elif [[ ! -d "$VOSK_MODEL" ]]; then
  fact vosk_model "MISSING at $VOSK_MODEL"
else
  record() {  # $1 = clip name, $2 = instruction
    echo; echo "$2 (recording $CLIP_SECONDS s in:)"; countdown 3
    arecord -q -D "plughw:$MIC_CARD,0" -f S16_LE -r "$SAMPLE_RATE" -c 1 -d "$CLIP_SECONDS" "/tmp/clip_$1.wav"
  }
  record silence  "Stay QUIET"
  record hot      "Say: Ok Computer, I'm hot"
  record cold     "Say: Ok Computer, I'm cold"
  record temp     "Say: Ok Computer, what's the temperature"
  record help     "Say: Ok Computer, help"
  record far      "Step back 2 metres and say: Ok Computer, I'm hot"
  record no_wake  "Say only: I'm hot   (without the wake word: it must be IGNORED)"
  record other    "Say something else: The weather is nice today"
  "$PYTHON" - <<'EOF'
import audioop, json, os, time, wave
from vosk import KaldiRecognizer, Model, SetLogLevel
from room.adapters.vosk_mic import accepted_text, grammar
from room.core import voice
facts = open(os.environ["FACTS_FILE"], "a")
def fact(k, v):
    print(f"FACT {k}={v}"); facts.write(f"FACT {k}={v}\n"); facts.flush()
SetLogLevel(-1)
CHUNK_BYTES = 8000
model_dir = os.environ["VOSK_MODEL"]
words_file = os.path.join(model_dir, "graph", "words.txt")
if os.path.exists(words_file):
    vocabulary = {line.split()[0] for line in open(words_file)}
    for word in ["ok", "okay", "computer", "i'm", "hot", "cold", "what's", "temperature", "help"]:
        fact(f"vosk_vocab_{word}", word in vocabulary)
start = time.time(); model = Model(model_dir)
fact("vosk_model_load_s", f"{time.time() - start:.1f}")

def recognise(frames, rate, with_grammar):
    if with_grammar:
        recognizer = KaldiRecognizer(model, rate, grammar())   # what the program uses
    else:
        recognizer = KaldiRecognizer(model, rate)              # free: is it "ok" or "okay"?
    recognizer.SetWords(True)
    for i in range(0, len(frames), CHUNK_BYTES):
        recognizer.AcceptWaveform(frames[i:i + CHUNK_BYTES])
    return recognizer.FinalResult()

for name in ["silence", "hot", "cold", "temp", "help", "far", "no_wake", "other"]:
    audio = wave.open(f"/tmp/clip_{name}.wav")
    frames, rate = audio.readframes(audio.getnframes()), audio.getframerate()
    fact(f"mic_rms_{name}", audioop.rms(frames, audio.getsampwidth()))
    start = time.time()
    result_json = recognise(frames, rate, with_grammar=True)
    fact(f"vosk_{name}_process_s", f"{time.time() - start:.2f}")
    result = json.loads(result_json)
    confidences = [round(w["conf"], 2) for w in result.get("result", [])]
    fact(f"vosk_{name}_text", repr(result.get("text", "")))
    if confidences:
        fact(f"vosk_{name}_conf", f"words {confidences} lowest {min(confidences)} "
                                  f"average {sum(confidences) / len(confidences):.2f}")
    text = accepted_text(result_json)          # the program's rule, current thresholds
    fact(f"vosk_{name}_accepted", repr(text))
    fact(f"vosk_{name}_command", voice.command_for(text) if text else None)
    free = json.loads(recognise(frames, rate, with_grammar=False))
    fact(f"vosk_{name}_free_text", repr(free.get("text", "")))
EOF
  rm -f /tmp/clip_*.wav
fi

# ---- FS90R servo ----------------------------------------------------------------
step "4/4 FS90R SERVO (watch it and write down what it does at each step)"
"$PYTHON" - <<'EOF'
import os, time
import RPi.GPIO as GPIO
from room.adapters.servo_fan import DUTY_CYCLE_BY_SPEED, FAN_PIN, PWM_FREQUENCY_HZ, STOPPED
HOLD_SECONDS = int(os.environ["SERVO_HOLD_SECONDS"])
WIDE = [8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 12.0]   # where does the speed stop growing?
GPIO.setwarnings(False); GPIO.setmode(GPIO.BCM); GPIO.setup(FAN_PIN, GPIO.OUT)
pwm = GPIO.PWM(FAN_PIN, PWM_FREQUENCY_HZ); pwm.start(DUTY_CYCLE_BY_SPEED[STOPPED])
print("A) The program's table: are the speeds clearly different, and is 0 really stopped?")
for speed, duty in sorted(DUTY_CYCLE_BY_SPEED.items()):
    print(f"   speed {speed} = duty {duty}%"); pwm.ChangeDutyCycle(duty); time.sleep(HOLD_SECONDS)
print("B) Wider sweep: at which value does it stop getting faster?")
for duty in WIDE:
    print(f"   duty {duty}%"); pwm.ChangeDutyCycle(duty); time.sleep(HOLD_SECONDS)
pwm.ChangeDutyCycle(DUTY_CYCLE_BY_SPEED[STOPPED]); time.sleep(1)
pwm.stop(); GPIO.cleanup(FAN_PIN)
EOF
ask "At speed 0, was the servo completely still?" servo_stops_at_0
ask "Were speeds 1, 2 and 3 clearly different from each other?" servo_speeds_distinct
note "In the wide sweep, from which duty % did it stop getting faster?" servo_max_useful_duty

# 0x0 = fine. Anything else after the servo test: the power supply is not enough.
fact throttled_at_end "$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"

step "SUMMARY (paste this to Claude)"
cat "$FACTS_FILE"
rm -f "$FACTS_FILE"
echo; echo "Saved to $LOG_FILE"
