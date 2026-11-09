#!/usr/bin/env python3
"""
Brain (cerebro) - SmartClassroom IoT, runs on the Server Pi.

The only program that decides and the only one that writes to MongoDB.
Version 0: use case 1 (access control + voice assistant).
Use case 2 (thermal emergency) plugs in where the TODO(E) comments are.

Usage:
    MQTT_HOST=localhost MONGO_URI=mongodb://localhost:27017 python3 brain.py
"""
import json
import os
import threading
import time
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt
from pymongo import MongoClient
from pymongo.errors import PyMongoError

BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "smartroom")

# Timers and rules of use case 1
ASK_CARD_AFTER_S = 3
REMIND_AFTER_S = 5          # counted after the first prompt
WAITING_TIMEOUT_S = 30      # nobody scanned a card: back to IDLE
MAX_FAILED_CARDS = 3
ENV_SAVE_PERIOD_S = 60      # one temperature reading per minute in MongoDB
BUFFER_WINDOW_S = 30        # readings kept in memory for the emergency detector
FAN_SPEED_ON_HOT = 2

IDLE, WAITING, INSIDE, LOCKED = "IDLE", "WAITING_CARD", "INSIDE", "LOCKED"
# TODO(E): add EMERGENCY

db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)[DB_NAME]
lock = threading.RLock()     # MQTT callbacks and timers run in different threads


def now():
    return datetime.now()


class Brain:
    def __init__(self, client):
        self.client = client
        self.state = IDLE
        self.inside = None            # {"card_id": ..., "name": ...}
        self.failed_cards = 0
        self.timers = []
        self.last_temp = None
        self.last_env_saved = 0.0
        self.temp_buffer = deque()    # (timestamp, temp) of the last 30 s - for emergency.py
        self.fan_speed = 0
        self.fan_source = "system"

    # ------------------------------------------------------------ helpers ---
    def save(self, collection, doc):
        """Never let a database problem crash the brain (test T12)."""
        doc.setdefault("ts", now())
        try:
            db[collection].insert_one(doc)
        except PyMongoError as exc:
            print(f"[mongo] could not write to {collection}: {exc}")

    def publish(self, topic, payload):
        self.client.publish(topic, json.dumps(payload), qos=1)

    def say(self, text):
        print(f"[say] {text}")
        self.publish("glo/door/speaker/say", {"text": text})

    def set_pir(self, enabled):
        self.publish("glo/door/pir/enable", {"enabled": enabled})

    def set_mic(self, enabled):
        self.publish("glo/room/mic/enable", {"enabled": enabled})

    def set_led(self, mode):
        self.publish("glo/door/led/cmd", {"mode": mode})

    def set_fan(self, speed, source):
        self.fan_source = source
        self.publish("glo/room/fan/cmd", {"speed": speed})

    def set_state(self, state):
        print(f"[state] {self.state} -> {state}")
        self.state = state

    def start_timer(self, seconds, action):
        def run():
            with lock:
                action()
        t = threading.Timer(seconds, run)
        t.daemon = True
        t.start()
        self.timers.append(t)

    def cancel_timers(self):
        for t in self.timers:
            t.cancel()
        self.timers = []

    def temperature_sentence(self):
        if self.last_temp is None:
            return ""
        return f" The temperature is {round(self.last_temp)} degrees."

    # ------------------------------------------------------------- events ---
    def on_motion(self, _data):
        self.save("motion_log", {})
        if self.state != IDLE:
            return
        self.set_state(WAITING)
        self.start_timer(ASK_CARD_AFTER_S, self._ask_card)

    def _ask_card(self):
        if self.state == WAITING:
            self.say("Please scan your card.")
            self.start_timer(REMIND_AFTER_S, self._remind_card)

    def _remind_card(self):
        if self.state == WAITING:
            self.say("Reminder: please scan your card to enter.")
            self.start_timer(WAITING_TIMEOUT_S, self._waiting_timeout)

    def _waiting_timeout(self):
        if self.state == WAITING:
            self.set_state(IDLE)

    def on_card(self, data):
        card_id = data.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            return self.invalid("door", "rfid message without card_id")

        if self.state == LOCKED:
            self.save("access_log", {"card_id": card_id, "name": None, "type": "denied"})
            return
        if self.state == INSIDE:
            if card_id == self.inside["card_id"]:
                return self.exit_room()
            user = self.find_user(card_id)
            self.save("access_log", {"card_id": card_id, "name": user and user["name"], "type": "occupied"})
            return self.say("Room occupied.")

        # IDLE or WAITING_CARD
        user = self.find_user(card_id)
        if user:
            return self.enter_room(user)
        self.failed_cards += 1
        self.save("access_log", {"card_id": card_id, "name": None, "type": "denied"})
        if self.failed_cards >= MAX_FAILED_CARDS:
            self.cancel_timers()
            self.set_state(LOCKED)
            self.save("system_log", {"event": "locked", "device": "door", "detail": f"{self.failed_cards} unknown cards"})
            self.say("System locked.")
        else:
            self.say("Card not recognized.")

    def find_user(self, card_id):
        try:
            return db.users.find_one({"card_id": card_id})
        except PyMongoError as exc:
            print(f"[mongo] users lookup failed: {exc}")
            return None

    def enter_room(self, user):
        self.cancel_timers()
        self.failed_cards = 0
        self.inside = {"card_id": user["card_id"], "name": user["name"]}
        self.save("access_log", {"card_id": user["card_id"], "name": user["name"], "type": "in"})
        self.set_state(INSIDE)
        self.set_led("open")
        self.set_pir(False)
        self.set_mic(True)
        self.say(f"Welcome, {user['name']}.{self.temperature_sentence()}")

    def exit_room(self):
        name = self.inside["name"]
        self.save("access_log", {"card_id": self.inside["card_id"], "name": name, "type": "out"})
        self.inside = None
        self.set_led("open")
        self.say(f"Goodbye, {name}.")
        if self.fan_speed:
            self.set_fan(0, "system")
        self.set_mic(False)
        self.set_pir(True)
        self.set_state(IDLE)

    def on_voice(self, data):
        command = data.get("command")
        if command not in ("hot", "cold", "temp", "help"):
            return self.invalid("room", f"unknown voice command {command!r}")
        if self.state != INSIDE:          # TODO(E): also accept "help" in EMERGENCY
            return
        if command == "hot":
            if self.fan_speed:
                self.say("The fan is already on.")
            else:
                self.set_fan(FAN_SPEED_ON_HOT, "voice")
        elif command == "cold":
            if self.fan_speed:
                self.set_fan(0, "voice")
            else:
                self.say("The fan is already off.")
        elif command == "temp":
            self.say(self.temperature_sentence().strip() or "I have no temperature reading yet.")
        elif command == "help":
            self.publish("glo/alert/call", {"ts": now().isoformat(timespec="seconds"),
                                            "reason": "help", "emergency_id": None})
            self.save("system_log", {"event": "help_call", "device": "room", "detail": ""})
            self.say("Emergency services have been called.")

    def on_env(self, data):
        temp = data.get("temp")
        if not isinstance(temp, (int, float)):
            return self.invalid("room", "env message without numeric temp")
        self.last_temp = float(temp)
        t = time.time()
        self.temp_buffer.append((t, self.last_temp))
        while self.temp_buffer and t - self.temp_buffer[0][0] > BUFFER_WINDOW_S:
            self.temp_buffer.popleft()
        # TODO(E): emergency.check(self.temp_buffer) -> start_emergency()
        if t - self.last_env_saved >= ENV_SAVE_PERIOD_S:
            self.last_env_saved = t
            self.save("env", {"temp": self.last_temp})

    def on_fan_state(self, data):
        speed = data.get("speed")
        if speed not in (0, 1, 2, 3):
            return self.invalid("room", "fan state with invalid speed")
        self.fan_speed = speed
        self.save("fan_log", {"speed": speed, "source": self.fan_source})

    def on_web(self, data):
        action = data.get("action")
        if action == "fan":
            speed = data.get("speed")
            if speed in (0, 1, 2, 3):           # TODO(E): refuse during EMERGENCY
                self.set_fan(speed, "web")
        elif action == "unlock":
            if self.state == LOCKED:
                self.failed_cards = 0
                self.save("system_log", {"event": "unlocked", "device": "web", "detail": ""})
                self.set_state(IDLE)
        elif action == "new_card":
            card_id, name = data.get("card_id"), data.get("name")
            if isinstance(card_id, str) and card_id and isinstance(name, str) and name:
                try:
                    db.users.insert_one({"card_id": card_id, "name": name, "created_at": now()})
                    print(f"[users] new card {card_id} -> {name}")
                except PyMongoError as exc:      # duplicate card_id, DB down...
                    print(f"[users] could not add {card_id}: {exc}")
        # TODO(E): simulate_emergency, end_emergency
        else:
            self.invalid("web", f"unknown action {action!r}")

    def on_device_status(self, device, payload):
        if payload in ("online", "offline"):
            self.save("system_log", {"event": payload, "device": device, "detail": ""})

    def invalid(self, device, detail):
        print(f"[invalid] {device}: {detail}")
        self.save("system_log", {"event": "invalid_msg", "device": device, "detail": detail})


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="brain")
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    brain = Brain(client)

    handlers = {
        "glo/door/motion": brain.on_motion,
        "glo/door/rfid": brain.on_card,
        "glo/room/voice": brain.on_voice,
        "glo/room/env": brain.on_env,
        "glo/room/fan/state": brain.on_fan_state,
        "glo/web/cmd": brain.on_web,
    }

    def on_connect(c, _userdata, _flags, reason_code, _props):
        print(f"[mqtt] connected to {BROKER}:{PORT} ({reason_code})")
        c.subscribe([(t, 1) for t in handlers] + [("glo/door/status", 1), ("glo/room/status", 1)])

    def on_message(_c, _userdata, msg):
        with lock:
            if msg.topic in ("glo/door/status", "glo/room/status"):
                return brain.on_device_status(msg.topic.split("/")[1], msg.payload.decode(errors="ignore"))
            try:
                data = json.loads(msg.payload.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("not a JSON object")
            except (ValueError, UnicodeDecodeError):
                return brain.invalid(msg.topic, "malformed JSON")
            handlers[msg.topic](data)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, keepalive=30)
    print(f"[brain] state {brain.state}, database {DB_NAME}")
    client.loop_forever()


if __name__ == "__main__":
    main()
