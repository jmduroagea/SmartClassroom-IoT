# SmartClassroom IoT

IoT project week, Université Toulouse Capitole (Ignacio, José María, Gloria).

A connected classroom with two use cases:

1. **Access control and voice assistant**: a PIR sensor detects someone at the door, they scan their RFID card, a speaker welcomes them and says the temperature, and they control a fan by voice ("I'm hot", "I'm cold") or from the web app.
2. **Thermal emergency and evacuation**: a fast temperature rise (≥ 5 °C in 30 s) triggers an emergency from any state: fan stopped, door LED blinking, evacuation message, simulated emergency calls.

## Architecture

| Device | Program | Role |
| --- | --- | --- |
| Door Pi | `door/door.py` | PIR, RFID reader, USB speaker, door LED |
| Room Pi | `room/room.py` | DS18B20 (every 2 s), USB microphone (Vosk), FS90R fan |
| Server Pi | Mosquitto + `server/brain.py` | Broker; state machine; the only writer to MongoDB |
| Server Pi | `server/web/server.js` | Express API + AngularJS web app (port 3001) |
| etu-web2 or laptop | MongoDB | Database `smartroom` |

Device Pis only talk to the broker. The web never talks to the Pis: it publishes on `glo/web/cmd` and the brain decides.

## MQTT contract

All payloads are JSON (except `status`). `ts` = ISO 8601 time.

| Topic | From → to | Payload |
| --- | --- | --- |
| `glo/door/motion` | Door Pi → brain | `{"ts"}` |
| `glo/door/rfid` | Door Pi → brain | `{"ts", "card_id"}` |
| `glo/door/speaker/say` | brain → Door Pi | `{"text"}` |
| `glo/door/pir/enable` | brain → Door Pi | `{"enabled": true/false}` |
| `glo/door/led/cmd` | brain → Door Pi | `{"mode": "open" / "blink" / "off"}` |
| `glo/room/env` | Room Pi → brain | `{"ts", "temp"}` every 2 s |
| `glo/room/voice` | Room Pi → brain | `{"ts", "command": "hot" / "cold" / "temp" / "help"}` |
| `glo/room/mic/enable` | brain → Room Pi | `{"enabled": true/false}` |
| `glo/room/fan/cmd` | brain → Room Pi | `{"speed": 0-3}` |
| `glo/room/fan/state` | Room Pi → brain | `{"ts", "speed"}` |
| `glo/web/cmd` | Express → brain | `{"action": "fan" / "unlock" / "new_card" / "simulate_emergency" / "end_emergency", ...}` |
| `glo/alert/units`, `glo/alert/call` | brain → emergency centre | see specification |
| `glo/door/status`, `glo/room/status` | each Pi (last will, retained) | `online` / `offline` |

## Running it on laptops (no Raspberry Pi needed)

1. **Broker**: install Mosquitto and run `mosquitto -c server/mosquitto/smartroom.conf -v`.
2. **Database**: MongoDB on etu-web2 or locally, then:
   ```bash
   pip install -r requirements.txt
   MONGO_URI=mongodb://localhost:27017 python3 server/setup_db.py
   ```
3. **Brain**: `MQTT_HOST=localhost MONGO_URI=mongodb://localhost:27017 python3 server/brain.py`
4. **Simulated Pis**: `python3 door/door.py --simulate` and `python3 room/room.py --simulate`
5. **Web**: `cd server/web && npm install && npm start`, then open http://localhost:3001

Windows (PowerShell): set variables with `$env:MQTT_HOST="10.12.220.120"` before running the command.

Test without any Pi: `mosquitto_pub -h localhost -t glo/door/rfid -m '{"ts":"2026-11-09T15:00:00","card_id":"CARD_GLORIA"}'`

## On the Raspberry Pis

- **Door Pi**: enable the UART and disable Bluetooth (Tutorial 2), `sudo apt install python3-serial libttspico-utils`, then `MQTT_HOST=<server ip> python3 door.py`.
- **Room Pi**: enable 1-Wire in `raspi-config`, `pip install vosk sounddevice`, download `vosk-model-small-en-us-0.15`, then `MQTT_HOST=<server ip> python3 room.py`.

## Libraries

| Library | Where | Why |
| --- | --- | --- |
| paho-mqtt | Python programs | MQTT client seen in class |
| pymongo | brain | MongoDB driver seen in class |
| RPi.GPIO | Door Pi, Room Pi | PIR input, LED, PWM for the fan |
| pyserial | Door Pi | RFID reader on the UART (Tutorial 2) |
| pico2wave | Door Pi | Offline text-to-speech |
| vosk + sounddevice | Room Pi | Offline speech-to-text, limited to our phrases |
| express | web | Required by the assignment |
| mongodb | web | Official Node.js driver |
| mqtt | web | Publishes web commands to the broker |
| angular 1.8 | web | Required; served locally, not from a CDN |
