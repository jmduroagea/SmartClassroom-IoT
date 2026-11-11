"""MQTT payloads: how each message is built and checked.

The contract lives in the FIELDS table: for each topic, which fields the message
has and their type. One function, validate(), checks any message against it.
build() creates a message to publish and parse() checks a received one.
A wrong message raises InvalidMessage, which says what is wrong.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from common import topics

# Allowed values (also part of the contract)
FAN_SPEEDS = (0, 1, 2, 3)  # 0 = stopped, 1-3 = speed levels
LED_COLORS = ("green", "red")
LED_MODES = ("pulse", "blink", "off")  # pulse = on for 3 s, then the Door Pi switches it off
VOICE_COMMANDS = ("hot", "cold", "temp", "help")
CALL_REASONS = ("help", "not_evacuated")
STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"

# Fire alarm: while it is on, the Door Pi says ALARM_TEXT every ALARM_INTERVAL_SECONDS
ALARM_TEXT = "Fire alert. Please leave the room now."
ALARM_INTERVAL_SECONDS = 3

# Field types. NULLABLE_STR accepts a text or null (None in Python).
NULLABLE_STR = (str, type(None))
NULLABLE_FLOAT = (int, float, type(None))  # a number or null; JSON may send 22 instead of 22.0

# The contract: topic -> {field name: type}
FIELDS = {
    topics.DOOR_MOTION: {"ts": str},
    topics.DOOR_RFID: {"ts": str, "card_id": str},
    topics.DOOR_SPEAKER_SAY: {"text": str},
    topics.DOOR_PIR_ENABLE: {"enabled": bool},
    topics.DOOR_LED_CMD: {"color": str, "mode": str},
    topics.DOOR_ALARM: {"enabled": bool},
    topics.ROOM_ENV: {"ts": str, "temp": float},
    topics.ROOM_VOICE: {"ts": str, "command": str},
    topics.ROOM_MIC_ENABLE: {"enabled": bool},
    topics.ROOM_FAN_CMD: {"speed": int},
    topics.ROOM_FAN_STATE: {"ts": str, "speed": int},
    topics.WEB_CMD: {"action": str},
    topics.ALERT_UNITS: {"ts": str, "emergency_id": str, "temp": NULLABLE_FLOAT, "person": NULLABLE_STR},
    topics.ALERT_CALL: {"ts": str, "reason": str, "emergency_id": NULLABLE_STR},
}

# Fields whose value must be one of a fixed list
ALLOWED_VALUES = {
    (topics.DOOR_LED_CMD, "color"): LED_COLORS,
    (topics.DOOR_LED_CMD, "mode"): LED_MODES,
    (topics.ROOM_VOICE, "command"): VOICE_COMMANDS,
    (topics.ROOM_FAN_CMD, "speed"): FAN_SPEEDS,
    (topics.ROOM_FAN_STATE, "speed"): FAN_SPEEDS,
    (topics.ALERT_CALL, "reason"): CALL_REASONS,
}

# glo/web/cmd: the extra fields depend on the action
WEB_ACTIONS = {
    "fan": {"speed": int},
    "unlock": {},
    "new_card": {"card_id": str, "name": str},
    "simulate_emergency": {},
    "end_emergency": {},
}

# Delivery guarantee per topic: alerts must arrive exactly once (QoS 2)
DEFAULT_QOS = 1
# The subscription to every alert needs QoS 2 too: MQTT delivers with the lower
# of the publish and subscribe QoS, so a QoS 1 subscription would lose the guarantee.
QOS = {topics.ALERT_UNITS: 2, topics.ALERT_CALL: 2, topics.ALERT_ALL: 2}


class InvalidMessage(ValueError):
    """A message that does not follow the contract. The text says why."""


def qos(topic: str) -> int:
    return QOS.get(topic, DEFAULT_QOS)


def build(topic: str, **fields) -> str:
    """Create the JSON text of a message, checking it first.

    Example: build(topics.DOOR_RFID, ts="2026-11-10T11:00:00", card_id="0F00A1B2C3")
    """
    validate(topic, fields)
    return json.dumps(fields, allow_nan=False)


def parse(topic: str, payload: bytes | str) -> dict:
    """Turn a received payload into a dict, or raise InvalidMessage."""
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidMessage(f"{topic}: not valid JSON") from exc
    validate(topic, data)
    return data


def validate(topic: str, data) -> None:
    """Check a message against the contract. Raise InvalidMessage if it is wrong."""
    if topic not in FIELDS:
        raise InvalidMessage(f"unknown topic {topic!r}")
    if not isinstance(data, dict):
        raise InvalidMessage(f"{topic}: the message must be a JSON object")

    expected = dict(FIELDS[topic])
    if topic == topics.WEB_CMD:
        action = data.get("action")
        if action not in WEB_ACTIONS:
            raise InvalidMessage(f"{topic}: unknown action {action!r}")
        expected.update(WEB_ACTIONS[action])

    _check_fields(topic, data, expected)

    for (allowed_topic, field), values in ALLOWED_VALUES.items():
        if allowed_topic == topic and data[field] not in values:
            raise InvalidMessage(f"{topic}: {field}={data[field]!r} must be one of {values}")
    if topic == topics.WEB_CMD and data["action"] == "fan" and data["speed"] not in FAN_SPEEDS:
        raise InvalidMessage(f"{topic}: speed={data['speed']!r} must be one of {FAN_SPEEDS}")


def parse_status(payload: bytes | str) -> str:
    """Status messages are plain text, not JSON: 'online' or 'offline'."""
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    if text not in (STATUS_ONLINE, STATUS_OFFLINE):
        raise InvalidMessage(f"status must be {STATUS_ONLINE!r} or {STATUS_OFFLINE!r}, got {text!r}")
    return text


def _check_fields(topic: str, data: dict, expected: dict) -> None:
    missing = [name for name in expected if name not in data]
    if missing:
        raise InvalidMessage(f"{topic}: missing field(s) {missing}")
    unknown = [name for name in data if name not in expected]
    if unknown:
        raise InvalidMessage(f"{topic}: unknown field(s) {unknown}")
    for name, expected_type in expected.items():
        value = data[name]
        if not _has_type(value, expected_type):
            raise InvalidMessage(f"{topic}: {name}={value!r} has the wrong type")
        if isinstance(value, str) and not value:
            raise InvalidMessage(f"{topic}: {name} must not be empty")
        # NaN and infinity are not valid JSON: Express could not read the message.
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidMessage(f"{topic}: {name}={value!r} must be a finite number")
    if "ts" in data:
        try:
            datetime.fromisoformat(data["ts"])
        except ValueError as exc:
            raise InvalidMessage(f"{topic}: ts={data['ts']!r} is not an ISO 8601 time") from exc


def _has_type(value, expected_type) -> bool:
    # In Python, True and False are also integers: never accept them as numbers.
    if isinstance(value, bool):
        return expected_type is bool or (isinstance(expected_type, tuple) and bool in expected_type)
    if expected_type is float:
        return isinstance(value, (int, float))  # JSON may send 22 instead of 22.0
    return isinstance(value, expected_type)
