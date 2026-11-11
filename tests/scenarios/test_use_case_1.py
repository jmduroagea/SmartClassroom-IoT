"""Use case 1, end to end: access control, fan and voice assistant.

The test plays the Door Pi and the Room Pi over MQTT and a user on the web.
`sim` is a clean system (see conftest.py). setup_db.py created the test users.
"""

import pytest

from common import messages, topics
from tests.scenarios.simulation import BASE_TEMPERATURE, now_ts

GLORIA = "CARD_GLORIA"
IGNACIO = "CARD_IGNACIO"
UNKNOWN_CARD = "CARD_NOBODY"
NEW_CARD = "CARD_ADA"
NEW_NAME = "Ada"
CARDS_TO_LOCK = 3
FAN_SPEED_ON_HOT = 2
FAN_OFF = 0
WARMER_TEMPERATURE = 25.0
REMINDER_TIMEOUT = 15  # the prompt comes 3 s after motion, the reminder 5 s later


def scan(sim, card_id):
    sim.publish(topics.DOOR_RFID, ts=now_ts(), card_id=card_id)


def enter(sim, card_id, name):
    """Scan a card and wait until the entry is completely over."""
    scan(sim, card_id)
    sim.wait_for_status(lambda status: status["inside"] == name)
    # The web shows the entry before the brain has sent all its orders. Wait
    # for every one of them, so none arrives late and confuses the next check.
    sim.said(containing="Welcome")
    sim.wait_for_message(topics.DOOR_LED_CMD)
    sim.wait_for_message(topics.DOOR_PIR_ENABLE, lambda order: order["enabled"] is False)
    sim.wait_for_message(topics.ROOM_MIC_ENABLE, lambda order: order["enabled"] is True)
    sim.forget_messages()


def leave(sim, card_id):
    """Scan the card of the person inside and wait until the exit is completely over."""
    scan(sim, card_id)
    sim.wait_for_status(lambda status: status["inside"] is None)
    sim.said(containing="Goodbye")
    sim.wait_for_message(topics.DOOR_LED_CMD)
    sim.wait_for_message(topics.DOOR_PIR_ENABLE, lambda order: order["enabled"] is True)
    sim.wait_for_message(topics.ROOM_MIC_ENABLE, lambda order: order["enabled"] is False)
    sim.forget_messages()


def confirm_fan(sim, speed):
    """Play the Room Pi: confirm the fan moved, and wait until the web shows it."""
    sim.publish(topics.ROOM_FAN_STATE, ts=now_ts(), speed=speed)
    sim.wait_for_status(lambda status: status["fanSpeed"] == speed)


# --- Access control -------------------------------------------------------------


def test_known_card_enters(sim):
    scan(sim, GLORIA)

    welcome = sim.said(containing="Welcome")
    assert "Gloria" in welcome
    assert str(round(BASE_TEMPERATURE)) in welcome
    sim.wait_for_message(topics.DOOR_LED_CMD, lambda order: order["mode"] == "open")
    sim.wait_for_message(topics.DOOR_PIR_ENABLE, lambda order: order["enabled"] is False)
    sim.wait_for_message(topics.ROOM_MIC_ENABLE, lambda order: order["enabled"] is True)
    sim.wait_for_status(lambda status: status["inside"] == "Gloria")


def test_same_card_leaves(sim):
    enter(sim, GLORIA, "Gloria")

    scan(sim, GLORIA)

    assert "Gloria" in sim.said(containing="Goodbye")
    sim.wait_for_message(topics.ROOM_MIC_ENABLE, lambda order: order["enabled"] is False)
    sim.wait_for_message(topics.DOOR_PIR_ENABLE, lambda order: order["enabled"] is True)
    sim.wait_for_status(lambda status: status["inside"] is None)


def test_second_person_is_refused_while_occupied(sim):
    enter(sim, GLORIA, "Gloria")

    scan(sim, IGNACIO)

    sim.said(containing="occupied")
    assert sim.status()["inside"] == "Gloria"


def test_unknown_card_is_rejected(sim):
    scan(sim, UNKNOWN_CARD)

    sim.said(containing="not recognized")
    assert sim.status()["inside"] is None


def test_three_unknown_cards_lock_until_unlocked_from_web(sim):
    for _ in range(CARDS_TO_LOCK):
        scan(sim, UNKNOWN_CARD)
    sim.said(containing="locked")
    sim.wait_for_status(lambda status: status["locked"])

    # While locked, even a known card stays outside.
    sim.forget_messages()
    scan(sim, GLORIA)
    sim.assert_nothing_on(topics.DOOR_SPEAKER_SAY)
    assert sim.status()["inside"] is None

    status_code, _body = sim.post("/api/unlock")
    assert status_code == 200
    sim.wait_for_status(lambda status: not status["locked"])

    scan(sim, GLORIA)
    sim.wait_for_status(lambda status: status["inside"] == "Gloria")


def test_motion_asks_for_card_then_reminds(sim):
    sim.publish(topics.DOOR_MOTION, ts=now_ts())

    sim.said(containing="scan your card", timeout=REMINDER_TIMEOUT)
    sim.said(containing="Reminder", timeout=REMINDER_TIMEOUT)


def test_card_registered_from_web_can_enter(sim):
    status_code, _body = sim.post("/api/users", {"card_id": NEW_CARD, "name": NEW_NAME})
    assert status_code == 200
    # The web only sends the request; the brain is the one that saves the card.
    sim.wait_for(lambda: NEW_CARD in [user["card_id"] for user in sim.get("/api/users")])

    scan(sim, NEW_CARD)

    sim.wait_for_status(lambda status: status["inside"] == NEW_NAME)


# --- Fan --------------------------------------------------------------------------


def test_fan_from_web_shows_only_the_confirmed_speed(sim):
    status_code, _body = sim.post("/api/fan", {"speed": 3})
    assert status_code == 200

    # The order reaches the Room Pi...
    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == 3)
    # ...but the web keeps the old speed until the Room Pi confirms it moved.
    assert sim.status()["fanSpeed"] == 0
    confirm_fan(sim, 3)


def test_every_fan_level_from_web_is_ordered_and_confirmed(sim):
    levels = sorted(messages.FAN_SPEEDS)
    # Off goes last, so every step is a real change from the one before.
    for level in levels[1:] + levels[:1]:
        status_code, _body = sim.post("/api/fan", {"speed": level})
        assert status_code == 200
        sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order, level=level: order["speed"] == level)
        confirm_fan(sim, level)


def test_fan_stops_when_person_leaves(sim):
    enter(sim, GLORIA, "Gloria")
    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="hot")
    speed = sim.wait_for_message(topics.ROOM_FAN_CMD)["speed"]
    confirm_fan(sim, speed)
    sim.forget_messages()

    scan(sim, GLORIA)

    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == FAN_OFF)


def test_web_shows_when_room_pi_goes_offline(sim):
    """T5: the Room Pi's last will says "offline", and the web shows it."""
    sim.publish_raw(topics.ROOM_STATUS, messages.STATUS_ONLINE)
    sim.wait_for_status(lambda status: status["devices"]["room"] == messages.STATUS_ONLINE)

    sim.publish_raw(topics.ROOM_STATUS, messages.STATUS_OFFLINE)

    sim.wait_for_status(lambda status: status["devices"]["room"] == messages.STATUS_OFFLINE)


@pytest.mark.parametrize("body", [{"speed": 9}, {"speed": "fast"}, {}])
def test_web_rejects_invalid_fan_speed(sim, body):
    """T8: an invalid command never reaches the broker."""
    status_code, _body = sim.post("/api/fan", body)

    assert status_code == 400
    sim.assert_nothing_on(topics.ROOM_FAN_CMD)


# --- Voice assistant ----------------------------------------------------------------


def test_voice_hot_turns_fan_on_when_inside(sim):
    enter(sim, GLORIA, "Gloria")

    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="hot")

    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == FAN_SPEED_ON_HOT)


def test_voice_temperature_is_answered_when_inside(sim):
    enter(sim, GLORIA, "Gloria")

    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="temp")

    assert str(round(BASE_TEMPERATURE)) in sim.said(containing="degrees")


def test_voice_temperature_uses_the_latest_reading(sim):
    enter(sim, GLORIA, "Gloria")
    sim.publish(topics.ROOM_ENV, ts=now_ts(), temp=WARMER_TEMPERATURE)

    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="temp")

    sim.said(containing=f"{round(WARMER_TEMPERATURE)} degrees")


def test_voice_help_calls_the_emergency_centre(sim):
    enter(sim, GLORIA, "Gloria")

    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="help")

    assert sim.wait_for_message(topics.ALERT_CALL)["reason"] == "help"
    sim.said(containing="Emergency services")


def test_voice_is_ignored_when_room_is_empty(sim):
    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="hot")

    sim.assert_nothing_on(topics.ROOM_FAN_CMD)


def test_voice_is_ignored_after_leaving(sim):
    enter(sim, GLORIA, "Gloria")
    leave(sim, GLORIA)

    sim.publish(topics.ROOM_VOICE, ts=now_ts(), command="hot")

    sim.assert_nothing_on(topics.ROOM_FAN_CMD)


# --- Robustness -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "topic, payload",
    [
        (topics.DOOR_RFID, "this is not JSON"),
        (topics.DOOR_RFID, '{"ts": "2026-11-10T12:00:00"}'),
        (topics.DOOR_RFID, '{"ts": "2026-11-10T12:00:00", "card_id": 12345}'),
        (topics.ROOM_ENV, '{"ts": "2026-11-10T12:00:00", "temp": "hot"}'),
        (topics.ROOM_VOICE, '{"ts": "2026-11-10T12:00:00", "command": "dance"}'),
        (topics.ROOM_FAN_STATE, "[1, 2, 3]"),
    ],
)
def test_malformed_message_is_discarded_and_system_keeps_working(sim, topic, payload):
    """T7: a message that breaks the contract changes nothing and breaks nothing."""
    sim.publish_raw(topic, payload)

    scan(sim, GLORIA)
    sim.wait_for_status(lambda status: status["inside"] == "Gloria")
