import json
import logging
import time
from common.config import load_config
from common.paho_bus import PahoBus
from common.topics import DOOR_RFID, DOOR_SPEAKER_SAY, ROOM_TEMP, ROOM_MOTION, ROOM_FAN
from server.brain.core.state_machine import StateMachine
from server.brain.adapters.mongo_repository import MongoRepository

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO)

    # 1. Load config properly using common module
    config = load_config()

    # 2. Instantiate repository with injected config
    repo = MongoRepository(config)
    sm = StateMachine()

    # 3. Use PahoBus instead of raw mqtt client
    bus = PahoBus(config=config, client_id="brain")

    def handle_rfid(topic, payload):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
            card_id = data.get("card_id")
            if not card_id:
                return

            user = repo.find_user_by_card(card_id)
            user_name = user["name"] if user else None

            actions = sm.process_card_scan(card_id, user_name)

            for action in actions:
                if action["type"] == "say":
                    bus.publish(DOOR_SPEAKER_SAY, {"text": action["text"]})
                elif action["type"] == "log_access":
                    repo.log_access(
                        card_id=action["card_id"],
                        access_type=action["event_type"],
                        name=action["name"],
                        ts=bus.clock.now(),
                    )
                elif action["type"] == "log_system":
                    repo.log_system(
                        event=action["level"],
                        device="brain",
                        detail=action["msg"],
                        ts=bus.clock.now(),
                    )
        except Exception as e:
            logger.error(f"[Brain] Error processing RFID message: {e}")

    def handle_temp(topic, payload):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
            temp = data.get("temp")
            if temp is not None:
                repo.log_env(float(temp), bus.clock.now())
        except Exception as e:
            logger.error(f"[Brain] Error processing temperature message: {e}")

    def handle_motion(topic, payload):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
            detected = data.get("detected")
            if detected is not None:
                repo.log_motion(bool(detected), bus.clock.now())
        except Exception as e:
            logger.error(f"[Brain] Error processing motion message: {e}")

    def handle_fan(topic, payload):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
            speed = data.get("speed")
            if speed is not None:
                repo.log_fan(int(speed), bus.clock.now())
        except Exception as e:
            logger.error(f"[Brain] Error processing fan message: {e}")

    # Register subscriptions
    bus.subscribe(DOOR_RFID, handle_rfid)
    bus.subscribe(ROOM_TEMP, handle_temp)
    bus.subscribe(ROOM_MOTION, handle_motion)
    bus.subscribe(ROOM_FAN, handle_fan)

    logger.info("[Brain] Starting PahoBus loop...")
    bus.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("[Brain] Shutting down...")
        bus.stop()


if __name__ == "__main__":
    main()
