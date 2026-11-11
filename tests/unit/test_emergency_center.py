from emergency_center.main import format_units_notification, format_call

def test_format_units_notification_valid():
    payload = {
        "ts": "2026-11-10T21:15:03",
        "emergency_id": "em-12345",
        "temperature": 41.5,
        "person": "Gloria"
    }
    res = format_units_notification(payload)
    assert res == "UNITS NOTIFIED 21:15:03, emergency em-12345, 41.5 °C, person inside: Gloria"

def test_format_units_notification_nulls():
    payload = {
        "ts": "2026-11-10T21:15:03",
        "emergency_id": "em-12345",
        "temperature": None,
        "person": None
    }
    res = format_units_notification(payload)
    assert res == "UNITS NOTIFIED 21:15:03, emergency em-12345, null, person inside: null"

def test_format_call():
    payload = {
        "ts": "2026-11-10T21:17:03",
        "number": "112",
        "reason": "not_evacuated"
    }
    res = format_call(payload)
    assert res == "CALL 21:17:03 to 112, reason: not_evacuated"
