"""Unit tests of the message bus port and FakeBus (common/bus.py)."""

import pytest

from common import topics
from common.bus import FakeBus, topic_matches
from common.messages import InvalidMessage

TS = "2026-11-10T11:00:00"
RFID_PAYLOAD = '{"ts": "2026-11-10T11:00:00", "card_id": "0F00A1B2C3"}'


# --- Wildcards --------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern, topic, expected",
    [
        ("glo/door/rfid", "glo/door/rfid", True),
        ("glo/door/rfid", "glo/door/motion", False),
        ("glo/alert/#", "glo/alert/call", True),
        ("glo/alert/#", "glo/alert/units", True),
        ("glo/alert/#", "glo/door/rfid", False),
        ("glo/+/status", "glo/door/status", True),
        ("glo/+/status", "glo/room/status", True),
        ("glo/+/status", "glo/door/led/cmd", False),
        ("glo/door", "glo/door/rfid", False),
    ],
)
def test_topic_matches(pattern, topic, expected):
    assert topic_matches(pattern, topic) is expected


# --- Publishing -------------------------------------------------------------


def test_publish_records_the_message():
    bus = FakeBus()
    bus.publish(topics.DOOR_SPEAKER_SAY, text="Welcome, Gloria.")
    assert bus.published == [(topics.DOOR_SPEAKER_SAY, {"text": "Welcome, Gloria."})]
    assert bus.published_on(topics.DOOR_SPEAKER_SAY) == [{"text": "Welcome, Gloria."}]


def test_wrong_message_is_never_published():
    bus = FakeBus()
    with pytest.raises(InvalidMessage):
        bus.publish(topics.ROOM_FAN_CMD, speed=9)
    assert bus.published == []


# --- Receiving --------------------------------------------------------------


def test_handler_receives_the_checked_message():
    bus = FakeBus()
    received = []
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: received.append((topic, data)))
    bus.inject(topics.DOOR_RFID, RFID_PAYLOAD)
    assert received == [(topics.DOOR_RFID, {"ts": TS, "card_id": "0F00A1B2C3"})]


def test_bytes_payload_is_accepted():
    bus = FakeBus()
    received = []
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: received.append(data))
    bus.inject(topics.DOOR_RFID, RFID_PAYLOAD.encode("utf-8"))
    assert received == [{"ts": TS, "card_id": "0F00A1B2C3"}]


def test_invalid_message_is_discarded_and_logged(caplog):
    bus = FakeBus()
    received = []
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: received.append(data))
    bus.inject(topics.DOOR_RFID, '{"ts": "2026-11-10T11:00:00"}')  # no card_id
    bus.inject(topics.DOOR_RFID, "not json")
    assert received == []
    assert "discarded invalid message" in caplog.text


def test_handlers_only_receive_their_topic():
    bus = FakeBus()
    received = []
    bus.subscribe(topics.DOOR_MOTION, lambda topic, data: received.append(topic))
    bus.inject(topics.DOOR_RFID, RFID_PAYLOAD)
    assert received == []


def test_status_topic_gives_plain_text():
    bus = FakeBus()
    received = []
    bus.subscribe("glo/+/status", lambda topic, data: received.append((topic, data)))
    bus.inject(topics.DOOR_STATUS, "offline")
    bus.inject(topics.ROOM_STATUS, b"online")
    bus.inject(topics.ROOM_STATUS, "sleeping")  # invalid: discarded
    assert received == [(topics.DOOR_STATUS, "offline"), (topics.ROOM_STATUS, "online")]


def test_wildcard_subscription_receives_every_alert():
    bus = FakeBus()
    received = []
    bus.subscribe(topics.ALERT_ALL, lambda topic, data: received.append(topic))
    bus.inject(topics.ALERT_CALL, '{"ts": "2026-11-10T11:00:00", "reason": "help", "emergency_id": null}')
    assert received == [topics.ALERT_CALL]


def test_a_failing_handler_does_not_stop_the_others(caplog):
    bus = FakeBus()
    received = []

    def broken(topic, data):
        raise RuntimeError("bug in a handler")

    bus.subscribe(topics.DOOR_RFID, broken)
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: received.append(data["card_id"]))
    bus.inject(topics.DOOR_RFID, RFID_PAYLOAD)
    assert received == ["0F00A1B2C3"]
    assert "handler for glo/door/rfid failed" in caplog.text


def test_start_and_stop():
    bus = FakeBus()
    bus.start()
    assert bus.started
    bus.stop()
    assert not bus.started
