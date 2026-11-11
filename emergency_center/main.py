from common.config import load_config
from common.paho_bus import PahoBus
from common import topics

def format_units_notification(payload: dict) -> str:
    """Pure function to turn a unit payload into a readable line."""
    ts = payload.get("ts", "")
    time_str = ts.split("T")[1] if "T" in ts else ts

    emp_id = payload.get("emergency_id", "")
    temp = payload.get("temperature")
    person = payload.get("person")

    temp_str = f"{temp} °C" if temp is not None else "null"
    person_str = str(person) if person is not None else "null"

    return f"UNITS NOTIFIED {time_str}, emergency {emp_id}, {temp_str}, person inside: {person_str}"

def format_call(payload: dict) -> str:
    """Pure function to turn a call payload into a readable line."""
    ts = payload.get("ts", "")
    time_str = ts.split("T")[1] if "T" in ts else ts
    number = payload.get("number", "")
    reason = payload.get("reason", "")

    return f"CALL {time_str} to {number}, reason: {reason}"

def handle_message(topic: str, payload: dict):
    """Route and print incoming messages based on the topic."""
    if topics.topic_matches(topics.ALERT_UNITS, topic) or "units" in topic:
        print(format_units_notification(payload), flush=True)
    elif topics.topic_matches(topics.ALERT_CALL, topic) or "call" in topic:
        print(format_call(payload), flush=True)

def main():
    config = load_config()
    bus = PahoBus(host=config.mqtt_host)

    bus.subscribe(topics.ALERT_UNITS, handle_message)
    bus.subscribe(topics.ALERT_CALL, handle_message)

    bus.start()
    print("Emergency Center running and waiting for alerts...", flush=True)

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bus.stop()

if __name__ == "__main__":
    main()
