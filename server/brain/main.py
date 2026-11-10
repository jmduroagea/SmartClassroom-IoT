import json
import paho.mqtt.client as mqtt
from common.topics import DOOR_RFID, DOOR_SPEAKER_SAY
from server.brain.core.state_machine import StateMachine
from server.brain.adapters.mongo_repository import MongoRepository

def main():
    sm = StateMachine()
    repo = MongoRepository()

    def on_connect(client, userdata, flags, rc):
        print(f"[Brain] Connected to MQTT broker with result code {rc}")
        client.subscribe(DOOR_RFID)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            card_id = payload.get("card_id")

            if not card_id:
                return

            user = repo.find_user_by_card(card_id)
            user_name = user["name"] if user else None

            actions = sm.process_card_scan(card_id, user_name)

            for action in actions:
                if action["type"] == "say":
                    client.publish(DOOR_SPEAKER_SAY, json.dumps({"text": action["text"]}))
                elif action["type"] == "log_access":
                    repo.log_access(action["event_type"], action["card_id"], action["name"])
                elif action["type"] == "log_system":
                    repo.log_system(action["level"], action["msg"])

        except Exception as e:
            print(f"[Brain] Error processing message: {e}")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("localhost", 1883, 60)
    print("[Brain] Server started, listening for events...")
    client.loop_forever()

if __name__ == "__main__":
    main()
