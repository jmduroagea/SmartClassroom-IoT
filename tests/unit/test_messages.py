"""Unit tests of the MQTT contract (common/messages.py)."""

import json

import pytest

from common import messages, topics
from common.messages import InvalidMessage

TS = "2026-11-10T11:00:00"


# --- Valid messages are accepted -------------------------------------------


def test_build_valid_rfid_message():
    text = messages.build(topics.DOOR_RFID, ts=TS, card_id="0F00A1B2C3")
    assert json.loads(text) == {"ts": TS, "card_id": "0F00A1B2C3"}


def test_parse_valid_message_from_bytes():
    payload = b'{"ts": "2026-11-10T11:00:00", "temp": 22.4}'
    assert messages.parse(topics.ROOM_ENV, payload) == {"ts": TS, "temp": 22.4}


def test_integer_temperature_is_accepted():
    messages.validate(topics.ROOM_ENV, {"ts": TS, "temp": 22})


def test_null_person_is_accepted_in_alert():
    messages.validate(
        topics.ALERT_UNITS, {"ts": TS, "emergency_id": "e1", "temp": 41.5, "person": None}
    )


@pytest.mark.parametrize(
    "data",
    [
        {"action": "fan", "speed": 2},
        {"action": "unlock"},
        {"action": "new_card", "card_id": "0F00A1B2C3", "name": "Gloria"},
        {"action": "simulate_emergency"},
        {"action": "end_emergency"},
    ],
)
def test_every_web_action_is_accepted(data):
    messages.validate(topics.WEB_CMD, data)


def test_every_topic_has_a_qos():
    assert messages.qos(topics.DOOR_RFID) == 1
    assert messages.qos(topics.ALERT_UNITS) == 2
    assert messages.qos(topics.ALERT_CALL) == 2


# --- Missing field ---------------------------------------------------------


def test_missing_field_is_rejected():
    with pytest.raises(InvalidMessage, match="missing"):
        messages.validate(topics.DOOR_RFID, {"ts": TS})


def test_missing_field_of_a_web_action_is_rejected():
    with pytest.raises(InvalidMessage, match="missing"):
        messages.validate(topics.WEB_CMD, {"action": "new_card", "card_id": "0F00A1B2C3"})


def test_build_refuses_an_incomplete_message():
    with pytest.raises(InvalidMessage):
        messages.build(topics.ROOM_FAN_CMD)


# --- Wrong type ------------------------------------------------------------


@pytest.mark.parametrize(
    "topic, data",
    [
        (topics.ROOM_ENV, {"ts": TS, "temp": "22.4"}),  # text instead of number
        (topics.DOOR_PIR_ENABLE, {"enabled": "yes"}),  # text instead of true/false
        (topics.ROOM_FAN_CMD, {"speed": True}),  # true is not a speed
        (topics.DOOR_RFID, {"ts": TS, "card_id": 1234}),  # number instead of text
    ],
)
def test_wrong_type_is_rejected(topic, data):
    with pytest.raises(InvalidMessage, match="wrong type"):
        messages.validate(topic, data)


# --- Other invalid messages ------------------------------------------------


@pytest.mark.parametrize(
    "topic, data",
    [
        (topics.ROOM_FAN_CMD, {"speed": 9}),
        (topics.DOOR_LED_CMD, {"mode": "disco"}),
        (topics.ROOM_VOICE, {"ts": TS, "command": "dance"}),
        (topics.WEB_CMD, {"action": "fan", "speed": 7}),
    ],
)
def test_value_outside_the_allowed_list_is_rejected(topic, data):
    with pytest.raises(InvalidMessage, match="must be one of"):
        messages.validate(topic, data)


def test_unknown_web_action_is_rejected():
    with pytest.raises(InvalidMessage, match="unknown action"):
        messages.validate(topics.WEB_CMD, {"action": "open_the_door"})


def test_unknown_field_is_rejected():
    with pytest.raises(InvalidMessage, match="unknown field"):
        messages.validate(topics.DOOR_RFID, {"ts": TS, "card_id": "0F00A1B2C3", "cardid": "x"})


def test_empty_text_is_rejected():
    with pytest.raises(InvalidMessage, match="empty"):
        messages.validate(topics.DOOR_RFID, {"ts": TS, "card_id": ""})


def test_bad_timestamp_is_rejected():
    with pytest.raises(InvalidMessage, match="ISO 8601"):
        messages.validate(topics.DOOR_MOTION, {"ts": "yesterday"})


@pytest.mark.parametrize("payload", [b"not json", b"\xff\xfe", b"[1, 2]"])
def test_payload_that_is_not_a_json_object_is_rejected(payload):
    with pytest.raises(InvalidMessage):
        messages.parse(topics.DOOR_MOTION, payload)


def test_unknown_topic_is_rejected():
    with pytest.raises(InvalidMessage, match="unknown topic"):
        messages.validate("glo/door/rfdi", {"ts": TS})


# --- Status messages (plain text) ------------------------------------------


def test_status_online_and_offline_are_accepted():
    assert messages.parse_status(b"online") == "online"
    assert messages.parse_status("offline") == "offline"


def test_other_status_is_rejected():
    with pytest.raises(InvalidMessage):
        messages.parse_status(b"sleeping")
