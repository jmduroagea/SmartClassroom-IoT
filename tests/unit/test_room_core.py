"""Unit tests of the Room Pi core (room/core/room_core.py), with a FakeBus,
a FakeClock and the two small fakes below."""

import json
from types import SimpleNamespace

import pytest

from common import topics
from common.bus import FakeBus
from common.clock import FakeClock
from room.core.ports import SensorError
from room.core.room_core import RoomCore

TEMP = 21.5


class FakeSensor:
    """Gives `temp`, or raises `error` when the test sets one."""

    def __init__(self):
        self.temp = TEMP
        self.error = None

    def read(self):
        if self.error:
            raise self.error
        return self.temp


class FakeFan:
    """Records every speed. When `broken`, it fails like a servo that does not answer."""

    def __init__(self):
        self.speeds = []
        self.broken = False

    def set_speed(self, speed):
        if self.broken:
            raise RuntimeError("servo not answering")
        self.speeds.append(speed)


@pytest.fixture
def room():
    """A started core with its fakes, all reachable from the test."""
    bus, clock, sensor, fan = FakeBus(), FakeClock(), FakeSensor(), FakeFan()
    core = RoomCore(bus, clock, sensor, fan)
    core.start()
    return SimpleNamespace(core=core, bus=bus, clock=clock, sensor=sensor, fan=fan)


def send(room, topic, **fields):
    room.bus.inject(topic, json.dumps(fields))


# --- Temperature ------------------------------------------------------------


def test_nothing_is_published_before_the_first_2_seconds(room):
    room.clock.advance(1.9)
    assert room.bus.published_on(topics.ROOM_ENV) == []


def test_one_reading_every_2_seconds(room):
    room.clock.advance(6)
    assert [m["temp"] for m in room.bus.published_on(topics.ROOM_ENV)] == [TEMP, TEMP, TEMP]


def test_reading_time_is_utc(room):
    room.clock.advance(2)
    assert room.bus.published_on(topics.ROOM_ENV)[0]["ts"] == "2026-11-10T09:00:02+00:00"


def test_bad_reading_is_skipped_and_the_loop_carries_on(room, caplog):
    room.sensor.error = SensorError("CRC check failed")
    room.clock.advance(2)
    assert room.bus.published_on(topics.ROOM_ENV) == []
    assert "CRC check failed" in caplog.text

    room.sensor.error = None
    room.clock.advance(2)
    assert len(room.bus.published_on(topics.ROOM_ENV)) == 1


# --- Voice ------------------------------------------------------------------


def test_voice_is_ignored_while_the_mic_is_off(room):
    room.core.on_phrase("ok computer i'm hot")
    assert room.bus.published_on(topics.ROOM_VOICE) == []


def test_voice_is_published_when_the_mic_is_on(room):
    send(room, topics.ROOM_MIC_ENABLE, enabled=True)
    room.core.on_phrase("ok computer i'm hot")
    assert room.bus.published_on(topics.ROOM_VOICE) == [
        {"ts": "2026-11-10T09:00:00+00:00", "command": "hot"}
    ]


def test_voice_is_ignored_again_when_the_mic_goes_off(room):
    send(room, topics.ROOM_MIC_ENABLE, enabled=True)
    send(room, topics.ROOM_MIC_ENABLE, enabled=False)
    room.core.on_phrase("ok computer i'm hot")
    assert room.bus.published_on(topics.ROOM_VOICE) == []


def test_phrase_without_the_wake_word_is_ignored_with_the_mic_on(room):
    send(room, topics.ROOM_MIC_ENABLE, enabled=True)
    room.core.on_phrase("i'm hot")
    assert room.bus.published_on(topics.ROOM_VOICE) == []


# --- Fan --------------------------------------------------------------------


def test_fan_order_moves_the_fan_and_is_confirmed(room):
    send(room, topics.ROOM_FAN_CMD, speed=2)
    assert room.fan.speeds == [2]
    assert room.bus.published_on(topics.ROOM_FAN_STATE) == [
        {"ts": "2026-11-10T09:00:00+00:00", "speed": 2}
    ]


def test_fan_that_fails_is_not_confirmed(room):
    room.fan.broken = True
    send(room, topics.ROOM_FAN_CMD, speed=2)
    assert room.bus.published_on(topics.ROOM_FAN_STATE) == []


def test_fan_order_outside_the_contract_never_reaches_the_fan(room):
    send(room, topics.ROOM_FAN_CMD, speed=9)
    assert room.fan.speeds == []
    assert room.bus.published_on(topics.ROOM_FAN_STATE) == []
