"""Use case 2, end to end: the emergency (T13 to T29, the ones that can be simulated).

The temperature comes from the Room Pi container (sim/room/temp), cards from the
Door Pi container (sim/door/card) or straight on MQTT, and the web is used as a
user would. Only T13, T14, T15 and T24 need the detector; the others start the
emergency with the "Simulate emergency" button.

The detector (#49) declares an emergency when one reading jumps 4 °C or more over
the one before, and the next reading stays that high.
`sim` is a clean system (see conftest.py).
"""

import time

from common import messages, topics
from tests.scenarios.simulation import BASE_TEMPERATURE
from tests.scenarios.test_use_case_1 import (
    GLORIA,
    UNKNOWN_CARD,
    WEB_PASSWORD,
    enter,
    scan,
    speak,
)

SIM_TEMP = "sim/room/temp"
SIM_CARD = "sim/door/card"
SIM_LED = "sim/door/led"
SIM_SAID = "sim/door/speaker/said"

READING_PERIOD = 2
HOT = BASE_TEMPERATURE + 9           # a jump well over the 4 °C of the detector
DETECTION_TIMEOUT = 10               # the jump and the reading that confirms it, and some margin
NOT_EVACUATED_TIMEOUT = 130          # 2 minutes, and some margin (T17)
PAUSE_AFTER_END = 60                 # no new emergency during this time (T24)
ALARM_TIMEOUT = 2 * messages.ALARM_INTERVAL_SECONDS + 2
CARDS_TO_LOCK = 3
PULSE_TIMEOUT = 6                    # an LED pulse lasts 3 s


def set_temperature(sim, temp):
    """Put the Room Pi's sensor at this temperature and wait until it sends it."""
    sim.publish_sim(SIM_TEMP, temp=temp)
    sim.wait_for_message(topics.ROOM_ENV, lambda reading: reading["temp"] == temp)


def simulate(sim, password=WEB_PASSWORD):
    status_code, _body = sim.post("/api/emergency/simulate", {"password": password})
    return status_code


def start_simulated_emergency(sim):
    assert simulate(sim) == 200
    sim.wait_for_status(lambda status: status["state"] == "emergency")


def end_emergency(sim):
    status_code, _body = sim.post("/api/emergency/end", {"password": WEB_PASSWORD})
    assert status_code == 200
    sim.wait_for_status(lambda status: status["state"] != "emergency")


def emergency_count(sim):
    return len(sim.get("/api/emergencies"))


def red_led_changes(sim):
    return [report["on"] for report in sim.messages_on(SIM_LED) if report["color"] == "red"]


# --- Detection -------------------------------------------------------------------


def test_real_emergency_stops_the_fan_and_warns_everyone(sim):  # T13
    enter(sim, GLORIA, "Gloria")

    sim.publish_sim(SIM_TEMP, temp=HOT)

    status = sim.wait_for_status(lambda s: s["state"] == "emergency", DETECTION_TIMEOUT)
    assert status["emergency"]["trigger"] == "rate"
    assert status["emergency"]["person"] == "Gloria"
    # The emergency centre is notified, with the person inside
    alert = sim.wait_for_message(topics.ALERT_UNITS)
    assert alert["person"] == "Gloria"
    # Fan stopped, red LED blinking, alarm on and repeated
    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == 0)
    sim.wait_for_message(topics.DOOR_LED_CMD, lambda order: order == {"color": "red", "mode": "blink"})
    sim.wait_for_message(topics.DOOR_ALARM, lambda order: order["enabled"] is True)
    sim.wait_for(
        lambda: [m["text"] for m in sim.messages_on(SIM_SAID)].count(messages.ALARM_TEXT) >= 2,
        ALARM_TIMEOUT,
    )


def test_slow_rise_does_not_trigger(sim):  # T14
    # 1 °C every 10 s: never a jump between two readings
    for step in range(1, 7):
        set_temperature(sim, BASE_TEMPERATURE + step)
        time.sleep(10 - READING_PERIOD)

    assert sim.status()["state"] != "emergency"
    assert sim.messages_on(topics.ALERT_UNITS) == []


def test_single_spike_does_not_trigger(sim):  # T15
    set_temperature(sim, HOT)                # one reading over the rise...
    sim.publish_sim(SIM_TEMP, temp=BASE_TEMPERATURE)  # ...and back before the next one

    time.sleep(3 * READING_PERIOD)
    assert sim.status()["state"] != "emergency"
    assert sim.messages_on(topics.ALERT_UNITS) == []


# --- During the emergency ------------------------------------------------------------


def test_person_scanning_out_is_marked_evacuated(sim):  # T16
    enter(sim, GLORIA, "Gloria")
    start_simulated_emergency(sim)

    sim.publish_sim(SIM_CARD, card_id=GLORIA)  # through the real door code

    sim.wait_for_status(lambda status: status["emergency"]["evacuated"] is True)
    assert sim.status()["inside"] is None
    assert sim.get("/api/emergencies")[0]["evacuatedAt"] is not None
    assert sim.get("/api/access")[0]["type"] == "evacuated"


def test_nobody_scanning_for_2_minutes_calls_the_centre(sim):  # T17
    enter(sim, GLORIA, "Gloria")
    start_simulated_emergency(sim)

    call = sim.wait_for_message(topics.ALERT_CALL, timeout=NOT_EVACUATED_TIMEOUT)

    assert call["reason"] == "not_evacuated"
    sim.wait_for_status(lambda status: status["emergency"]["notEvacuated"] is True)


def test_help_during_an_emergency_is_shown_on_the_web(sim):  # T18
    enter(sim, GLORIA, "Gloria")
    start_simulated_emergency(sim)
    sim.forget_messages()

    speak(sim, "ok computer help")

    call = sim.wait_for_message(topics.ALERT_CALL)
    assert call["reason"] == "help"
    assert call["emergency_id"] is not None
    sim.wait_for_status(lambda status: status["emergency"]["helpRequested"] is True)


def test_fan_stays_stopped_during_an_emergency(sim):  # T19
    enter(sim, GLORIA, "Gloria")
    start_simulated_emergency(sim)
    sim.wait_for_message(topics.ROOM_FAN_CMD, lambda order: order["speed"] == 0)
    sim.forget_messages()

    speak(sim, "ok computer i'm hot")
    status_code, _body = sim.post("/api/fan", {"speed": 2})
    assert status_code == 200  # the web publishes it; the brain is the one that refuses

    sim.assert_nothing_on(topics.ROOM_FAN_CMD)
    assert sim.status()["fanSpeed"] == 0


def test_wrong_password_publishes_nothing(sim):  # T20
    assert simulate(sim, password="wrong") == 401
    start_simulated_emergency(sim)
    sim.forget_messages()

    status_code, _body = sim.post("/api/emergency/end", {"password": "wrong"})

    assert status_code == 401
    sim.assert_nothing_on(topics.WEB_CMD)
    assert sim.status()["state"] == "emergency"


# --- Nobody inside, and the end ---------------------------------------------------------


def test_emergency_with_nobody_inside(sim):  # T21, from IDLE
    start_simulated_emergency(sim)

    assert sim.wait_for_message(topics.ALERT_UNITS)["person"] is None
    sim.wait_for_message(topics.DOOR_ALARM, lambda order: order["enabled"] is True)
    assert sim.status()["emergency"]["person"] is None

    end_emergency(sim)
    assert sim.status()["state"] == "normal"


def test_emergency_while_locked_ends_unlocked(sim):  # T21, from LOCKED
    for _ in range(CARDS_TO_LOCK):
        scan(sim, UNKNOWN_CARD)
    sim.wait_for_status(lambda status: status["state"] == "locked")

    start_simulated_emergency(sim)
    sim.wait_for_message(topics.DOOR_ALARM, lambda order: order["enabled"] is True)
    end_emergency(sim)

    assert sim.status()["state"] == "normal"


def test_end_with_the_probe_still_hot_does_not_start_another(sim):  # T24
    sim.publish_sim(SIM_TEMP, temp=HOT)
    sim.wait_for_status(lambda status: status["state"] == "emergency", DETECTION_TIMEOUT)

    end_emergency(sim)
    # The probe is still in the hot water and keeps warming up, and it even jumps
    # once: during the pause nothing is decided
    # (the pause counts from the last reading before the end, up to 2 s earlier)
    deadline = time.monotonic() + PAUSE_AFTER_END - 3 * READING_PERIOD
    temp = HOT + 6
    sim.publish_sim(SIM_TEMP, temp=temp)
    while time.monotonic() < deadline:
        temp += 1
        sim.publish_sim(SIM_TEMP, temp=temp)
        time.sleep(2 * READING_PERIOD)
        assert sim.status()["state"] != "emergency"
    assert emergency_count(sim) == 1

    # After the pause, a new rise is detected again
    time.sleep(3 * READING_PERIOD)
    sim.publish_sim(SIM_TEMP, temp=temp + 10)
    sim.wait_for_status(lambda status: status["state"] == "emergency", DETECTION_TIMEOUT)
    assert emergency_count(sim) == 2


def test_end_without_evacuation_closes_the_exit(sim):  # T25
    enter(sim, GLORIA, "Gloria")
    start_simulated_emergency(sim)

    end_emergency(sim)

    sim.wait_for_status(lambda status: status["inside"] is None)
    assert sim.get("/api/access")[0]["type"] == "emergency_end"


# --- LEDs (T29) -------------------------------------------------------------------------


def test_leds_for_each_card(sim):  # T29
    sim.publish_sim(SIM_CARD, card_id=UNKNOWN_CARD)   # unknown: red pulse
    sim.wait_for(lambda: red_led_changes(sim) == [True, False], PULSE_TIMEOUT)
    sim.forget_messages()

    sim.publish_sim(SIM_CARD, card_id=GLORIA)         # known: green pulse
    sim.wait_for_message(SIM_LED, lambda report: report == {"color": "green", "on": True})
    sim.wait_for_message(SIM_LED, lambda report: report == {"color": "green", "on": False}, PULSE_TIMEOUT)
    sim.wait_for_status(lambda status: status["inside"] == "Gloria")
    sim.forget_messages()

    sim.publish_sim(SIM_CARD, card_id="CARD_IGNACIO")  # room occupied: red pulse
    sim.wait_for(lambda: red_led_changes(sim) == [True, False], PULSE_TIMEOUT)


def test_red_led_blinks_until_the_emergency_ends(sim):  # T29
    start_simulated_emergency(sim)

    # Blinking: on and off again and again, every half second
    sim.wait_for(lambda: len(red_led_changes(sim)) >= 4)
    changes = red_led_changes(sim)
    assert all(before != after for before, after in zip(changes, changes[1:]))

    end_emergency(sim)
    sim.wait_for_message(topics.DOOR_LED_CMD, lambda order: order == {"color": "red", "mode": "off"})
    time.sleep(1)  # the last change of the blink, if one was on its way
    sim.forget_messages()
    sim.assert_nothing_on(SIM_LED)
