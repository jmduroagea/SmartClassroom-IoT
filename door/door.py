#!/usr/bin/env python3
"""
Door Pi (Pi Puerta) - SmartClassroom IoT

Reads the PIR sensor and the RFID reader and publishes them over MQTT.
Speaks the texts the server sends and drives the door LED.
The Pi never decides anything: it only measures and obeys (see the MQTT contract).

Usage:
    python3 door.py --simulate            # on a laptop: keyboard instead of sensors
    python3 door.py                       # on the Raspberry Pi with real hardware
    MQTT_HOST=10.12.220.120 python3 door.py

In simulate mode, type a card id + Enter to "scan a card", or "m" + Enter for motion.
"""
import argparse
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))

T_MOTION = "glo/door/motion"
T_RFID = "glo/door/rfid"
T_SAY = "glo/door/speaker/say"
T_PIR_ENABLE = "glo/door/pir/enable"
T_LED = "glo/door/led/cmd"
T_STATUS = "glo/door/status"

PIR_PIN = 17      # BCM numbering (physical pin 11)
LED_PIN = 27      # BCM numbering (physical pin 13)
RFID_PORT = "/dev/ttyAMA0"
CARD_DEBOUNCE_S = 2.0   # the reader repeats the same card while it is held

pir_enabled = True
speech_queue = queue.Queue()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- hardware ---
class SimulatedHardware:
    """Keyboard and screen instead of sensors, for working without a Pi."""

    def speak(self, text):
        print(f"\U0001F50A {text}")

    def led(self, mode):
        print(f"\U0001F4A1 LED -> {mode}")

    def run_inputs(self, on_card, on_motion):
        print("Type a card id + Enter to scan a card, 'm' + Enter for motion.")
        while True:
            line = input().strip()
            if not line:
                continue
            if line.lower() == "m":
                on_motion()
            else:
                on_card(line)

    def cleanup(self):
        pass


class RealHardware:
    """PIR on GPIO17, RFID on the UART, USB speaker with pico2wave, LED on GPIO27."""

    def __init__(self):
        import RPi.GPIO as GPIO
        import serial
        self.GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIR_PIN, GPIO.IN)
        GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)
        self.serial = serial.Serial(RFID_PORT, 9600, timeout=1)
        self._blink_stop = threading.Event()

    def speak(self, text):
        # pico2wave works offline; aplay plays the file on the default (USB) card.
        wav = "/tmp/smartroom_say.wav"
        subprocess.run(["pico2wave", "-l", "en-US", "-w", wav, text], check=False)
        subprocess.run(["aplay", "-q", wav], check=False)

    def led(self, mode):
        self._blink_stop.set()
        if mode == "open":
            self.GPIO.output(LED_PIN, self.GPIO.HIGH)
            threading.Timer(3, lambda: self.GPIO.output(LED_PIN, self.GPIO.LOW)).start()
        elif mode == "blink":
            self._blink_stop = threading.Event()
            threading.Thread(target=self._blink, args=(self._blink_stop,), daemon=True).start()
        else:
            self.GPIO.output(LED_PIN, self.GPIO.LOW)

    def _blink(self, stop):
        state = False
        while not stop.is_set():
            state = not state
            self.GPIO.output(LED_PIN, state)
            time.sleep(0.5)
        self.GPIO.output(LED_PIN, self.GPIO.LOW)

    def _read_card(self):
        # Same protocol as Tutorial 2: 0x02, 10 ID chars, 2 checksum chars, 0x03.
        if self.serial.read() != b"\x02":
            return None
        raw = self.serial.read(12).decode("ascii", errors="ignore")
        return raw[:10] if len(raw) >= 10 else None

    def run_inputs(self, on_card, on_motion):
        self.GPIO.add_event_detect(PIR_PIN, self.GPIO.RISING,
                                   callback=lambda _ch: on_motion(), bouncetime=2000)
        last_card, last_time = None, 0.0
        while True:
            try:
                card = self._read_card()
            except Exception as exc:          # loose wire, serial glitch...
                print(f"[rfid] read error: {exc}")
                time.sleep(1)
                continue
            if card and (card != last_card or time.time() - last_time > CARD_DEBOUNCE_S):
                last_card, last_time = card, time.time()
                on_card(card)

    def cleanup(self):
        self.GPIO.cleanup()


# -------------------------------------------------------------------- MQTT ---
def build_client(hw):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="door-pi")
    # If the Pi dies, the broker publishes "offline" for us (last will).
    client.will_set(T_STATUS, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(c, _userdata, _flags, reason_code, _props):
        print(f"[mqtt] connected to {BROKER}:{PORT} ({reason_code})")
        c.subscribe([(T_SAY, 1), (T_PIR_ENABLE, 1), (T_LED, 1)])
        c.publish(T_STATUS, "online", qos=1, retain=True)

    def on_disconnect(_c, _userdata, _flags, reason_code, _props):
        print(f"[mqtt] disconnected ({reason_code}), reconnecting...")

    def on_message(_c, _userdata, msg):
        global pir_enabled
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            print(f"[mqtt] ignored invalid message on {msg.topic}")
            return
        if msg.topic == T_SAY and isinstance(data.get("text"), str):
            speech_queue.put(data["text"])
        elif msg.topic == T_PIR_ENABLE and isinstance(data.get("enabled"), bool):
            pir_enabled = data["enabled"]
            print(f"[pir] enabled = {pir_enabled}")
        elif msg.topic == T_LED and data.get("mode") in ("open", "blink", "off"):
            hw.led(data["mode"])

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    return client


def speech_worker(hw):
    # Speaking takes seconds: do it in its own thread so MQTT never blocks.
    while True:
        hw.speak(speech_queue.get())


def main():
    parser = argparse.ArgumentParser(description="SmartClassroom Door Pi")
    parser.add_argument("--simulate", action="store_true", help="keyboard instead of sensors")
    args = parser.parse_args()

    hw = SimulatedHardware() if args.simulate else RealHardware()
    client = build_client(hw)
    client.connect_async(BROKER, PORT, keepalive=30)
    client.loop_start()
    threading.Thread(target=speech_worker, args=(hw,), daemon=True).start()

    def on_card(card_id):
        print(f"[rfid] {card_id}")
        client.publish(T_RFID, json.dumps({"ts": now_iso(), "card_id": card_id}), qos=1)

    def on_motion():
        if pir_enabled:
            print("[pir] motion")
            client.publish(T_MOTION, json.dumps({"ts": now_iso()}), qos=1)

    try:
        hw.run_inputs(on_card, on_motion)
    except KeyboardInterrupt:
        pass
    finally:
        client.publish(T_STATUS, "offline", qos=1, retain=True)
        client.loop_stop()
        hw.cleanup()


if __name__ == "__main__":
    main()
