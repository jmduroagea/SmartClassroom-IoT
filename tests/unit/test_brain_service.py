"""Unit tests of the brain's application layer (server/brain/service.py): from a
received message to what is published and saved. FakeBus, FakeClock and
FakeRepository, so no broker and no MongoDB."""

import json
import threading
from types import SimpleNamespace

import pytest

from common import topics
from common.bus import FakeBus
from common.clock import FAKE_START, FakeClock
from server.brain.adapters.fake_repository import FakeRepository
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


def test_temperature_rise_declares_the_emergency(brain):
    scan(brain, "CARD_GLORIA")
    for _ in range(16):  # 32 s at room temperature: the 30 s window is full
        reading(brain, BASE)
    reading(brain, BASE + 6)
    assert brain.bus.published_on(topics.ALERT_UNITS) == []
    reading(brain, BASE + 6)  # second reading in a row
    [alert] = brain.bus.published_on(topics.ALERT_UNITS)
    assert alert["temp"] == BASE + 6
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


def test_end_emergency_does_not_break_anything_yet(brain):
    send(brain, topics.WEB_CMD, action="simulate_emergency")
    send(brain, topics.WEB_CMD, action="end_emergency")
    scan(brain, "CARD_GLORIA")  # the brain keeps answering


# --- Threads -------------------------------------------------------------------


def test_timer_callbacks_run_inside_the_lock():
    lock = threading.Lock()
    clock = FakeClock()
    seen = []
    LockedClock(clock, lock).schedule(1, lambda: seen.append(lock.locked()))
    clock.advance(1)
    assert seen == [True]
    assert not lock.locked()
