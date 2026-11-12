import time
from datetime import datetime

from common import topics
from common.bus import Payload
from common.config import load_config
from common.paho_bus import PahoBus

CLIENT_ID = "emergency-center"


def _extract_time(ts: str) -> str:
    """Extract HH:MM:SS without timezone offset from an ISO timestamp."""
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts.split("T")[1].split("+")[0].split("Z")[0] if "T" in ts else ts


def format_units_notification(payload: dict) -> str:
    """Turn an ALERT_UNITS payload into a readable line."""
    time_str = _extract_time(payload.get("ts", ""))
    emp_id = payload.get("emergency_id", "")
    temp = payload.get("temp")
    person = payload.get("person")

    temp_str = f"{temp} °C" if temp is not None else "null"
    person_str = str(person) if person is not None else "null"

    return f"UNITS NOTIFIED {time_str}, emergency {emp_id}, {temp_str}, person inside: {person_str}"


def format_call(payload: dict) -> str:
    """Turn an ALERT_CALL payload into a readable line."""
    time_str = _extract_time(payload.get("ts", ""))
    emp_id = payload.get("emergency_id", "")
    reason = payload.get("reason", "")

    return f"CALL {time_str} to 112, emergency {emp_id}, reason: {reason}"


def on_units(topic: str, payload: Payload) -> None:
    if isinstance(payload, dict):
        print(format_units_notification(payload), flush=True)


def on_call(topic: str, payload: Payload) -> None:
    if isinstance(payload, dict):
        print(format_call(payload), flush=True)


def main() -> None:
    config = load_config()
    bus = PahoBus(config, CLIENT_ID)

    bus.subscribe(topics.ALERT_UNITS, on_units)
    bus.subscribe(topics.ALERT_CALL, on_call)

    bus.start()
    print("Emergency Center running and waiting for alerts...", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bus.stop()


if __name__ == "__main__":
    main()
