#!/usr/bin/env python3
"""
Room Pi (Pi Aula) - SmartClassroom IoT

Publishes the temperature every 2 s, publishes recognised voice commands,
and drives the fan (FS90R continuous servo) as the server orders.
The Pi never decides anything: it only measures and obeys (see the MQTT contract).

Usage:
    python3 room.py --simulate        # on a laptop: fake temperature, keyboard as microphone
    python3 room.py                   # on the Raspberry Pi with real hardware
    MQTT_HOST=10.12.220.120 VOSK_MODEL=/home/pi/vosk-model-small-en-us-0.15 python3 room.py

In simulate mode, type hot / cold / temp / help + Enter to "speak",
and "+5" + Enter to add 5 degrees (to test the emergency).
"""
import argparse
import glob
import json
import os
import random
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
VOSK_MODEL = os.getenv("VOSK_MODEL", "vosk-model-small-en-us-0.15")

T_ENV = "glo/room/env"
T_VOICE = "glo/room/voice"
T_MIC_ENABLE = "glo/room/mic/enable"
T_FAN_CMD = "glo/room/fan/cmd"
T_FAN_STATE = "glo/room/fan/state"
T_STATUS = "glo/room/status"

FAN_PIN = 18                 # BCM numbering (physical pin 12)
ENV_PERIOD_S = 2
# FS90R at 50 Hz: 7.5 % = stopped, towards 10 % = faster. Calibrate on Thursday.
FAN_DUTY = {0: 7.5, 1: 8.5, 2: 9.2, 3: 10.0}

# Phrase -> command. Vosk only listens for these words (grammar), which
# makes recognition much more reliable. "[unk]" absorbs everything else.
PHRASES = {
    "i'm hot": "hot",
    "i'm cold": "cold",
    "what's the temperature": "temp",
    "help": "help",
}

mic_enabled = False


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- hardware ---
class SimulatedHardware:
    def __init__(self):
        self.temp = 21.0
        self.offset = 0.0

    def read_temp(self):
        self.temp += random.uniform(-0.1, 0.1)
        return round(self.temp + self.offset, 2)

    def set_fan(self, speed):
        print(f"\U0001F300 fan speed -> {speed}")

    def listen(self, on_command):
        print("Type hot / cold / temp / help to speak, '+5' to heat the sensor.")
        while True:
            line = input().strip().lower()
            if line.startswith("+") or line.startswith("-"):
                try:
                    self.offset += float(line)
                    print(f"[sim] temperature offset = {self.offset}")
                except ValueError:
                    pass
            elif line in PHRASES.values():
                on_command(line)

    def cleanup(self):
        pass


class RealHardware:
    def __init__(self):
        import RPi.GPIO as GPIO
        self.GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(FAN_PIN, GPIO.OUT)
        self.pwm = GPIO.PWM(FAN_PIN, 50)
        self.pwm.start(FAN_DUTY[0])
        sensors = glob.glob("/sys/bus/w1/devices/28-*/w1_slave")
        if not sensors:
            raise RuntimeError("No DS18B20 found: enable 1-Wire in raspi-config and check wiring")
        self.sensor_file = sensors[0]

    def read_temp(self):
        # w1_slave has two lines: "... YES" (CRC ok) and "... t=22437" (milli-degrees).
        with open(self.sensor_file) as f:
            lines = f.read().splitlines()
        if not lines or not lines[0].endswith("YES"):
            raise IOError("DS18B20 CRC error")
        return round(int(lines[1].split("t=")[1]) / 1000.0, 2)

    def set_fan(self, speed):
        self.pwm.ChangeDutyCycle(FAN_DUTY[speed])

    def listen(self, on_command):
        import queue
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer

        model = Model(VOSK_MODEL)
        grammar = json.dumps(list(PHRASES.keys()) + ["[unk]"])
        rec = KaldiRecognizer(model, 16000, grammar)
        audio = queue.Queue()

        def callback(indata, _frames, _time, _status):
            audio.put(bytes(indata))

        with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                               channels=1, callback=callback):
            while True:
                data = audio.get()
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                    if text in PHRASES:
                        on_command(PHRASES[text])

    def cleanup(self):
        self.pwm.stop()
        self.GPIO.cleanup()


# -------------------------------------------------------------------- MQTT ---
def build_client(hw):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="room-pi")
    client.will_set(T_STATUS, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(c, _userdata, _flags, reason_code, _props):
        print(f"[mqtt] connected to {BROKER}:{PORT} ({reason_code})")
        c.subscribe([(T_MIC_ENABLE, 1), (T_FAN_CMD, 1)])
        c.publish(T_STATUS, "online", qos=1, retain=True)

    def on_message(c, _userdata, msg):
        global mic_enabled
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            print(f"[mqtt] ignored invalid message on {msg.topic}")
            return
        if msg.topic == T_MIC_ENABLE and isinstance(data.get("enabled"), bool):
            mic_enabled = data["enabled"]
            print(f"[mic] enabled = {mic_enabled}")
        elif msg.topic == T_FAN_CMD and data.get("speed") in FAN_DUTY:
            hw.set_fan(data["speed"])
            # Confirm the real state, so the web shows what actually happened.
            c.publish(T_FAN_STATE, json.dumps({"ts": now_iso(), "speed": data["speed"]}), qos=1)

    client.on_connect = on_connect
    client.on_message = on_message
    return client


def temperature_loop(hw, client):
    while True:
        try:
            temp = hw.read_temp()
            client.publish(T_ENV, json.dumps({"ts": now_iso(), "temp": temp}), qos=1)
        except Exception as exc:     # sensor unplugged, CRC error... keep running (test T6)
            print(f"[temp] read error: {exc}")
        time.sleep(ENV_PERIOD_S)


def main():
    parser = argparse.ArgumentParser(description="SmartClassroom Room Pi")
    parser.add_argument("--simulate", action="store_true", help="fake sensors, keyboard as microphone")
    args = parser.parse_args()

    hw = SimulatedHardware() if args.simulate else RealHardware()
    client = build_client(hw)
    client.connect_async(BROKER, PORT, keepalive=30)
    client.loop_start()
    threading.Thread(target=temperature_loop, args=(hw, client), daemon=True).start()

    def on_command(command):
        if mic_enabled:
            print(f"[voice] {command}")
            client.publish(T_VOICE, json.dumps({"ts": now_iso(), "command": command}), qos=1)
        else:
            print(f"[voice] '{command}' ignored: microphone disabled")

    try:
        hw.listen(on_command)
    except KeyboardInterrupt:
        pass
    finally:
        client.publish(T_STATUS, "offline", qos=1, retain=True)
        client.loop_stop()
        hw.cleanup()


if __name__ == "__main__":
    main()
