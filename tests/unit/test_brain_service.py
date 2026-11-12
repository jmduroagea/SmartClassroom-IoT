"""Unit tests of the brain's application layer (server/brain/service.py): from a
received message to what is published and saved. FakeBus, FakeClock and
FakeRepository, so no broker and no MongoDB."""

import json
import threading
from types import SimpleNamespace

import pytest

from common import topics
from common.messages import ALARM_TEXT
from room.core.voice import WAKE_WORDS
from common.bus import FakeBus
from datetime import timedelta

from common.clock import FAKE_START, FakeClock
from server.brain.adapters.fake_repository import FakeRepository
from server.brain.core.emergency_detector import JUMP_THRESHOLD_DEGREES
from server.brain.service import Brain, LockedClock

GLORIA = {"card_id": "CARD_GLORIA", "name": "Gloria"}
TS = "2026-11-10T09:00:00+00:00"
BASE = 20.0
READING_PERIOD = 2


@pytest.fixture
def brain():
    bus, clock = FakeBus(), FakeClock()
    repo = FakeRepository(initial_users=[dict(GLORIA)])
    service = Brain(bus, clock, repo)
    service.start()
    return SimpleNamespace(service=service, bus=bus, clock=clock, repo=repo)


def send(brain, topic, **fields):
    brain.bus.inject(topic, json.dumps(fields))


def scan(brain, card_id):
    send(brain, topics.DOOR_RFID, ts=TS, card_id=card_id)


def said(brain):
    return [m["text"] for m in brain.bus.published_on(topics.DOOR_SPEAKER_SAY)]


def reading(brain, temp):
    send(brain, topics.ROOM_ENV, ts=TS, temp=temp)
    brain.clock.advance(READING_PERIOD)


# --- Access --------------------------------------------------------------------


def test_known_card_enters(brain):
    scan(brain, "CARD_GLORIA")
    assert said(brain) == ["Welcome, Gloria."]
    assert brain.bus.published_on(topics.DOOR_LED_CMD) == [{"color": "green", "mode": "pulse"}]
    assert brain.bus.published_on(topics.DOOR_PIR_ENABLE) == [{"enabled": False}]
    assert brain.bus.published_on(topics.ROOM_MIC_ENABLE) == [{"enabled": True}]
    assert brain.repo.access_logs == [
        {"card_id": "CARD_GLORIA", "type": "in", "name": "Gloria", "ts": FAKE_START}
    ]


def test_unknown_card_is_logged_without_a_name(brain):
    scan(brain, "UNKNOWN")
    assert said(brain) == ["Card not recognized."]
    assert brain.repo.access_logs[0]["name"] is None
    assert brain.repo.access_logs[0]["type"] == "denied"


def test_lock_and_unlock_are_saved_for_the_web(brain):
    for attempt in range(3):
        scan(brain, f"UNKNOWN{attempt}")
    send(brain, topics.WEB_CMD, action="unlock")
    assert [log["event"] for log in brain.repo.system_logs] == ["locked", "unlocked"]


def test_card_registered_from_the_web_can_enter(brain):
    send(brain, topics.WEB_CMD, action="new_card", card_id="CARD_JOSE", name="Jose")
    scan(brain, "CARD_JOSE")
    assert said(brain) == ["Welcome, Jose."]


def test_forced_exit_from_the_web_empties_the_room(brain):
    scan(brain, "CARD_GLORIA")
    send(brain, topics.WEB_CMD, action="force_exit")
    last = brain.repo.access_logs[-1]
    assert (last["type"], last["card_id"], last["name"]) == ("forced_exit", "CARD_GLORIA", "Gloria")
    assert brain.bus.published_on(topics.ROOM_FAN_CMD)[-1] == {"speed": 0}
    assert brain.bus.published_on(topics.ROOM_MIC_ENABLE)[-1] == {"enabled": False}
    assert brain.bus.published_on(topics.DOOR_PIR_ENABLE)[-1] == {"enabled": True}
    # Nobody is at the door: nothing is said and no LED lights up (only the welcome ones).
    assert said(brain) == ["Welcome, Gloria."]
    assert len(brain.bus.published_on(topics.DOOR_LED_CMD)) == 1


def test_after_a_forced_exit_the_room_is_not_occupied(brain):
    send(brain, topics.WEB_CMD, action="new_card", card_id="CARD_JOSE", name="Jose")
    scan(brain, "CARD_GLORIA")
    send(brain, topics.WEB_CMD, action="force_exit")
    scan(brain, "CARD_JOSE")
    assert said(brain)[-1] == "Welcome, Jose."
    assert brain.repo.access_logs[-1]["type"] == "in"


def test_forced_exit_with_nobody_inside_logs_nothing(brain):
    send(brain, topics.WEB_CMD, action="force_exit")
    assert brain.repo.access_logs == []


def test_motion_is_saved_and_the_prompt_comes_from_a_timer(brain):
    send(brain, topics.DOOR_MOTION, ts=TS)
    assert len(brain.repo.motion_logs) == 1
    brain.clock.advance(3)
    assert said(brain) == ["scan your card"]


# --- Room ----------------------------------------------------------------------


def test_temperature_is_saved_every_10_seconds(brain):
    for _ in range(6):  # 12 s of readings
        reading(brain, BASE)
    assert [log["ts"] for log in brain.repo.env_logs] == [
        FAKE_START, FAKE_START.replace(second=10)
    ]


def test_welcome_says_the_last_temperature(brain):
    reading(brain, 21.5)
    scan(brain, "CARD_GLORIA")
    assert said(brain) == ["Welcome, Gloria. The temperature is 21.5 degrees."]

def test_voice_temp_says_the_latest_reading(brain):
    reading(brain, 21.0)
    scan(brain, "CARD_GLORIA")
    reading(brain, 23.5)
    send(brain, topics.ROOM_VOICE, ts=TS, command="temp")
    assert said(brain)[-1] == "The temperature is 23.5 degrees."


def test_fan_from_the_web_is_ordered_and_its_state_saved(brain):
    send(brain, topics.WEB_CMD, action="fan", speed=2)
    assert brain.bus.published_on(topics.ROOM_FAN_CMD) == [{"speed": 2}]
    send(brain, topics.ROOM_FAN_STATE, ts=TS, speed=2)
    assert brain.repo.fan_logs == [{"speed": 2, "ts": FAKE_START}]


def test_pi_going_offline_is_saved(brain):
    brain.bus.inject(topics.ROOM_STATUS, "offline")
    assert brain.repo.system_logs == [
        {"event": "offline", "device": "room", "detail": "", "ts": FAKE_START}
    ]


# --- Emergency -----------------------------------------------------------------


def test_temperature_jump_declares_the_emergency(brain):
    hot = BASE + JUMP_THRESHOLD_DEGREES + 1
    scan(brain, "CARD_GLORIA")
    reading(brain, BASE)
    reading(brain, hot)  # the jump
    assert brain.bus.published_on(topics.ALERT_UNITS) == []
    reading(brain, hot)  # it stays high: confirmed
    [alert] = brain.bus.published_on(topics.ALERT_UNITS)
    assert alert["temp"] == hot
    assert alert["person"] == "Gloria"
    assert alert["emergency_id"].startswith("em-")
    assert brain.bus.published_on(topics.DOOR_ALARM) == [{"enabled": True}]
    assert brain.bus.published_on(topics.DOOR_LED_CMD)[-1] == {"color": "red", "mode": "blink"}


def test_simulated_emergency_uses_the_last_reading(brain):
    reading(brain, 22.0)
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    [alert] = brain.bus.published_on(topics.ALERT_UNITS)
    assert alert["temp"] == 22.0
    assert alert["person"] is None


def only_record(brain):
    [record] = brain.repo.emergencies.values()
    return record


def test_temperature_rise_creates_the_full_emergency_record(brain):  # Done when of #23
    scan(brain, "CARD_GLORIA")
    for _ in range(16):  # 32 s at room temperature: the 30 s window is full
        reading(brain, BASE)
    reading(brain, BASE + 6)
    send(brain, topics.ROOM_ENV, ts=TS, temp=BASE + 6)  # second in a row: declared now
    declared_at = brain.clock.now()
    record = only_record(brain)
    buffer = record.pop("readings")
    assert record == {
        "_id": "em-20261110T090034",  # FakeClock starts at 09:00:00; 17 readings, 2 s apart
        "started_at": declared_at,
        "ended_at": None,
        "trigger": "rate",
        "trigger_temp": BASE + 6,
        "person": {"card_id": "CARD_GLORIA", "name": "Gloria"},
        "evacuated_at": None,
        "not_evacuated_alert": False,
        "units_notified_at": declared_at,
        "calls": [],
    }
    # The readings of the last 30 s, oldest first, ending with the two that triggered it
    assert [r["temp"] for r in buffer[-2:]] == [BASE + 6, BASE + 6]
    assert all(r["temp"] == BASE for r in buffer[:-2])
    assert buffer[-1]["ts"] == declared_at
    assert declared_at - buffer[0]["ts"] <= timedelta(seconds=30)
    alert = brain.bus.published_on(topics.ALERT_UNITS)[0]
    assert alert["emergency_id"] == record["_id"]


def test_simulated_emergency_record_with_nobody_inside(brain):
    reading(brain, 22.0)
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    record = only_record(brain)
    assert record["trigger"] == "simulated"
    assert record["trigger_temp"] == 22.0
    assert record["person"] is None
    assert [r["temp"] for r in record["readings"]] == [22.0]


def test_simulated_emergency_without_any_reading(brain):
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    record = only_record(brain)
    assert record["trigger_temp"] is None
    assert record["readings"] == []


def test_readings_during_the_emergency_go_to_the_record_and_to_env(brain):
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    env_before = len(brain.repo.env_logs)
    for temp in (30.0, 35.0, 40.0, 45.0, 50.0, 55.0):  # 12 s of readings
        reading(brain, temp)
    assert [r["temp"] for r in only_record(brain)["readings"]] == [30.0, 35.0, 40.0, 45.0, 50.0, 55.0]
    assert len(brain.repo.env_logs) - env_before == 2  # still one every 10 s, for the chart


def test_a_second_emergency_does_not_create_another_record(brain):
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    brain.clock.advance(5)
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    assert len(brain.repo.emergencies) == 1


def test_calls_and_evacuation_are_saved_in_the_record(brain):
    # What the parts of the brain that detect calls and evacuation will emit
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    emergency_id = brain.service.machine.emergency_id
    brain.clock.advance(10)
    brain.service.machine.emit({"type": "emergency_call", "emergency_id": emergency_id, "reason": "help"})
    brain.clock.advance(10)
    brain.service.machine.emit({"type": "emergency_evacuated", "emergency_id": emergency_id})
    brain.service.machine.emit({"type": "emergency_not_evacuated", "emergency_id": emergency_id})
    record = only_record(brain)
    assert record["calls"] == [{"ts": FAKE_START + timedelta(seconds=10), "reason": "help"}]
    assert record["evacuated_at"] == FAKE_START + timedelta(seconds=20)
    assert record["not_evacuated_alert"] is True


def end(brain):
    send(brain, topics.WEB_CMD, action="end_emergency")


def hot_emergency(brain):
    """Room temperature for 32 s, then 2 readings 6 degrees higher: the emergency starts."""
    for _ in range(16):
        reading(brain, BASE)
    reading(brain, BASE + 6)
    reading(brain, BASE + 6)
    assert len(brain.bus.published_on(topics.ALERT_UNITS)) == 1


def test_end_closes_the_record_and_switches_everything_back(brain):
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    brain.clock.advance(30)
    end(brain)
    assert only_record(brain)["ended_at"] == FAKE_START + timedelta(seconds=30)
    assert brain.bus.published_on(topics.DOOR_ALARM)[-1] == {"enabled": False}
    assert brain.bus.published_on(topics.DOOR_LED_CMD)[-1] == {"color": "red", "mode": "off"}
    assert brain.bus.published_on(topics.ROOM_MIC_ENABLE)[-1] == {"enabled": False}
    assert brain.bus.published_on(topics.DOOR_PIR_ENABLE)[-1] == {"enabled": True}
    assert brain.bus.published_on(topics.ROOM_FAN_CMD)[-1] == {"speed": 0}


def test_end_without_evacuation_logs_an_emergency_end_exit(brain):  # T25
    scan(brain, "CARD_GLORIA")
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    end(brain)
    last = brain.repo.access_logs[-1]
    assert (last["type"], last["card_id"], last["name"]) == ("emergency_end", "CARD_GLORIA", "Gloria")
    scan(brain, "CARD_GLORIA")  # to enter again she must scan
    assert brain.repo.access_logs[-1]["type"] == "in"


def test_end_with_the_probe_still_hot_does_not_start_another_emergency(brain):  # T24
    hot_emergency(brain)
    end(brain)
    # The probe is still in the hot water and keeps warming up: 0.5 degrees every
    # reading, so the 30 s window would see a rise of 7 degrees. Detection is paused.
    for step in range(29):  # 58 s
        reading(brain, BASE + 6 + 0.5 * step)
    assert len(brain.bus.published_on(topics.ALERT_UNITS)) == 1
    assert len(brain.repo.emergencies) == 1


def test_after_the_pause_a_new_rise_starts_a_new_emergency(brain):  # T24
    hot_emergency(brain)
    end(brain)
    for _ in range(35):  # pause of 60 s, then the 30 s window fills again, still hot
        reading(brain, BASE + 6)
    reading(brain, BASE + 12)
    reading(brain, BASE + 12)
    assert len(brain.bus.published_on(topics.ALERT_UNITS)) == 2
    assert len(brain.repo.emergencies) == 2


def test_after_an_emergency_that_started_locked_the_web_sees_it_unlocked(brain):
    for attempt in range(3):
        scan(brain, f"UNKNOWN_{attempt}")
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    end(brain)
    lock_events = [log["event"] for log in brain.repo.system_logs if log["event"] in ("locked", "unlocked")]
    assert lock_events[-1] == "unlocked"


def test_end_without_an_emergency_only_logs_a_warning(brain, caplog):
    end(brain)
    assert "no emergency" in caplog.text
    assert brain.bus.published_on(topics.DOOR_ALARM) == []
    scan(brain, "CARD_GLORIA")  # the brain keeps answering
    assert brain.repo.access_logs[-1]["type"] == "in"


# --- Threads -------------------------------------------------------------------


def test_timer_callbacks_run_inside_the_lock():
    lock = threading.Lock()
    clock = FakeClock()
    seen = []
    LockedClock(clock, lock).schedule(1, lambda: seen.append(lock.locked()))
    clock.advance(1)
    assert seen == [True]
    assert not lock.locked()


def test_help_voice_command_publishes_alert_call_in_inside_and_emergency(brain):
    scan(brain, GLORIA["card_id"])
    send(brain, topics.ROOM_VOICE, ts=TS, command="help")

    calls = brain.bus.published_on(topics.ALERT_CALL)
    assert len(calls) == 1
    assert calls[0]["reason"] == "help"
    assert calls[0]["emergency_id"] is None

    send(brain, topics.WEB_CMD, ts=TS, action="simulate_emergency")
    send(brain, topics.ROOM_VOICE, ts=TS, command="help")

    calls = brain.bus.published_on(topics.ALERT_CALL)
    assert len(calls) == 2
    assert calls[1]["reason"] == "help"
    assert calls[1]["emergency_id"] == brain.service.machine.emergency_id

# Every different sentence the flows below make the brain say. Update it when a
# sentence is added, so the test keeps proving it covers all of them.
DISTINCT_SENTENCES_COVERED = 13

def test_no_spoken_sentence_contains_wake_word(brain):
    """Every sentence the brain or alarm can speak must be free of WAKE_WORDS (#68)."""
    # 1. PIR prompt (3 s) + reminder (5 s) + timeout (30 s)
    send(brain, topics.DOOR_MOTION, ts=TS)
    brain.clock.advance(3.0)
    brain.clock.advance(5.0)
    brain.clock.advance(30.0)

    # 2. Entry without temperature reading + "temp" with no reading + occupied room + normal exit
    scan(brain, GLORIA["card_id"])
    send(brain, topics.ROOM_VOICE, ts=TS, command="temp")
    brain.repo.save_user("OTHER_KNOWN_CARD", "Other")
    scan(brain, "OTHER_KNOWN_CARD")
    scan(brain, GLORIA["card_id"])

    # 3. Entry with temperature reading + "temp" + fan limits + "help" inside + emergency + "help"
    send(brain, topics.ROOM_ENV, ts=TS, temp=22.4)
    scan(brain, GLORIA["card_id"])
    send(brain, topics.ROOM_VOICE, ts=TS, command="temp")
    for _ in range(4):
        send(brain, topics.ROOM_VOICE, ts=TS, command="hot")
    for _ in range(4):
        send(brain, topics.ROOM_VOICE, ts=TS, command="cold")
    send(brain, topics.ROOM_VOICE, ts=TS, command="help")
    send(brain, topics.WEB_CMD, ts=TS, action="simulate_emergency")
    send(brain, topics.ROOM_VOICE, ts=TS, command="help")
    send(brain, topics.WEB_CMD, ts=TS, action="end_emergency")

    # 4. Unknown card x3 -> "Card not recognized." + "System locked"
    for idx in range(3):
        scan(brain, f"UNKNOWN_{idx}")

    sentences = [*said(brain), ALARM_TEXT]
    assert len(set(said(brain))) == DISTINCT_SENTENCES_COVERED
    for sentence in sentences:
        lower = sentence.lower()
        for wake in WAKE_WORDS:
            assert wake not in lower, f"Sentence {sentence!r} contains wake word {wake!r}"
