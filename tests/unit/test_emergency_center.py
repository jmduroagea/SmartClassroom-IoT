import json

from common import messages, topics
from emergency_center.main import format_call, format_units_notification


def test_format_units_notification_valid():
    raw = messages.build(
        topics.ALERT_UNITS,
        ts="2026-11-10T21:15:03+00:00",
        emergency_id="em-12345",
        temp=41.5,
        person="Gloria",
    )
    payload = json.loads(raw)
    res = format_units_notification(payload)
    assert res == "UNITS NOTIFIED 21:15:03, emergency em-12345, 41.5 °C, person inside: Gloria"


def test_format_units_notification_null_person():
    raw = messages.build(
        topics.ALERT_UNITS,
        ts="2026-11-10T21:15:03+00:00",
        emergency_id="em-12345",
        temp=41.5,
        person=None,
    )
    payload = json.loads(raw)
    res = format_units_notification(payload)
    assert res == "UNITS NOTIFIED 21:15:03, emergency em-12345, 41.5 °C, person inside: null"


def test_format_units_notification_null_temp_defensive():
    payload = {
        "ts": "2026-11-10T21:15:03+00:00",
        "emergency_id": "em-12345",
        "temp": None,
        "person": None,
    }
    res = format_units_notification(payload)
    assert res == "UNITS NOTIFIED 21:15:03, emergency em-12345, null, person inside: null"


def test_format_call():
    raw = messages.build(
        topics.ALERT_CALL,
        ts="2026-11-10T21:17:03+00:00",
        emergency_id="em-12345",
        reason="not_evacuated",
    )
    payload = json.loads(raw)
    res = format_call(payload)
    assert res == "CALL 21:17:03 to 112, emergency em-12345, reason: not_evacuated"
