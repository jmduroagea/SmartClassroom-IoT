"""Use case 1, end to end: access control, fan and voice assistant.

The test plays the Door Pi over MQTT and a user on the web. The Room Pi is its
own container (fake hardware on sim/ topics, see the README): the test sets its
temperature, speaks to its microphone and checks that its fan moved.
`sim` is a clean system (see conftest.py). setup_db.py created the test users.
"""

import time

import pytest

from common import messages, topics
from tests.scenarios import simulation
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
WEB_PASSWORD = "simulation"  # the default in compose.yaml

SIM_TEMP = "sim/room/temp"
SIM_VOICE = "sim/room/voice"
SIM_FAN = "sim/room/fan"
SPEAK_ATTEMPTS = 3
SPEAK_WAIT = 2.0  # seconds for the Room Pi to turn a phrase into a command


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


def fan_moved(sim, speed):
    """Wait until the Room Pi's fan moved to the speed and the web shows it."""
    sim.wait_for_message(SIM_FAN, lambda report: report["speed"] == speed)
    sim.wait_for_status(lambda status: status["fanSpeed"] == speed)


def speak(sim, phrase):
    """Say a phrase to the Room Pi's microphone and wait until it sends the command.

    The order to switch the microphone on and the phrase reach the Room Pi on two
    different connections, so the phrase could arrive first and be ignored: it is
    said again, a few times at most."""
    for _ in range(SPEAK_ATTEMPTS):
        sim.publish_sim(SIM_VOICE, text=phrase)
        try:
            return sim.wait_for_message(topics.ROOM_VOICE, timeout=SPEAK_WAIT)
        except AssertionError:
            continue
    raise AssertionError(f"the Room Pi never sent a command for {phrase!r}")


# --- Access control -------------------------------------------------------------


def test_known_card_enters(sim):
    scan(sim, GLORIA)

    welcome = sim.said(containing="Welcome")
    assert "Gloria" in welcome
    assert str(round(BASE_TEMPERATURE)) in welcome
    sim.wait_for_message(topics.DOOR_LED_CMD, lambda order: order == {"color": "green", "mode": "pulse"})
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
    sim.wait_for_status(lambda status: status["state"] == "locked")

    # While locked, even a known card stays outside.
    sim.forget_messages()
    scan(sim, GLORIA)
    sim.assert_nothing_on(topics.DOOR_SPEAKER_SAY)
    assert sim.status()["inside"] is None

    status_code, _body = sim.post("/api/unlock", {"password": WEB_PASSWORD})
    assert status_code == 200
    sim.wait_for_status(lambda status: status["state"] != "locked")

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


def test_fan_from_web_moves_the_fan_and_the_web_shows_it(sim):
    status_code, _body = sim.post("/api/fan", {"speed": 3})
    assert status_code == 200

    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == 3)
    fan_moved(sim, 3)


def test_web_keeps_the_old_speed_until_the_room_pi_confirms(sim):
    simulation.kill("room")  # nobody will confirm the order

    status_code, _body = sim.post("/api/fan", {"speed": 3})
    assert status_code == 200

    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == 3)
    time.sleep(simulation.QUIET_TIME)
    assert sim.status()["fanSpeed"] == 0


def test_every_fan_level_from_web_is_ordered_and_confirmed(sim):
    levels = sorted(messages.FAN_SPEEDS)
    # Off goes last, so every step is a real change from the one before.
    for level in levels[1:] + levels[:1]:
        status_code, _body = sim.post("/api/fan", {"speed": level})
        assert status_code == 200
        sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order, level=level: order["speed"] == level)
        fan_moved(sim, level)


def test_fan_stops_when_person_leaves(sim):
    enter(sim, GLORIA, "Gloria")
    speed = max(messages.FAN_SPEEDS)
    status_code, _body = sim.post("/api/fan", {"speed": speed})
    assert status_code == 200
    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == speed)
    fan_moved(sim, speed)
    sim.forget_messages()

    scan(sim, GLORIA)

    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == FAN_OFF)


def test_web_shows_when_room_pi_goes_offline(sim):
    """T5: the Room Pi's last will says "offline", and the web shows it."""
    sim.wait_for_status(lambda status: status["devices"]["room"] == messages.STATUS_ONLINE)

    simulation.kill("room")

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

    assert speak(sim, "ok computer i'm hot")["command"] == "hot"

    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == FAN_SPEED_ON_HOT)
    fan_moved(sim, FAN_SPEED_ON_HOT)


@pytest.mark.xfail(reason="voice is not in the new brain yet (#67, temp and help)", strict=True)
def test_voice_temperature_is_answered_when_inside(sim):
    enter(sim, GLORIA, "Gloria")

    speak(sim, "ok computer what's the temperature")

    assert str(round(BASE_TEMPERATURE)) in sim.said(containing="degrees")


@pytest.mark.xfail(reason="voice is not in the new brain yet (#67, temp and help)", strict=True)
def test_voice_temperature_uses_the_latest_reading(sim):
    enter(sim, GLORIA, "Gloria")
    sim.publish_sim(SIM_TEMP, temp=WARMER_TEMPERATURE)
    sim.wait_for_message(topics.ROOM_ENV, lambda reading: reading["temp"] == WARMER_TEMPERATURE)

    speak(sim, "ok computer what's the temperature")

    sim.said(containing=f"{round(WARMER_TEMPERATURE)} degrees")


def test_voice_help_calls_the_emergency_centre(sim):
    enter(sim, GLORIA, "Gloria")

    speak(sim, "ok computer help")

    assert sim.wait_for_message(topics.ALERT_CALL)["reason"] == "help"
    sim.said(containing="Emergency services")


# The next two publish the command straight to the brain, to check that the brain
# ignores it. That the Room Pi does not even send it with the microphone off is
# covered by its unit tests.
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
