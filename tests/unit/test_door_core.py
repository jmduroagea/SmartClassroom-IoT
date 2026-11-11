"""Unit tests of the Door Pi core (door/core/door_core.py), with a FakeBus,
a FakeClock and the two small fakes below."""

import json
from types import SimpleNamespace

import pytest

from common import messages, topics
from common.bus import FakeBus
from common.clock import FakeClock
from door.core.door_core import (
    BLINK_HALF_PERIOD_SECONDS,
    CARD_DEBOUNCE_SECONDS,
    PULSE_SECONDS,
    DoorCore,
)

CARD = "0F00A1B2C3"
OTHER_CARD = "0F00C4D5E6"
ALARM = messages.ALARM_TEXT
INTERVAL = messages.ALARM_INTERVAL_SECONDS


class FakeLight:
    """Remembers which LEDs are on and every change, in order."""

    def __init__(self):
        self.lit = {"green": False, "red": False}
        self.changes = []

    def on(self, color):
        self.lit[color] = True
        self.changes.append((color, "on"))

    def off(self, color):
        self.lit[color] = False
        self.changes.append((color, "off"))


class FakeSpeaker:
    """Records what it was asked to say. A sentence lasts until the test calls finish()."""

    def __init__(self):
        self.said = []
        self._on_done = None

    def play(self, text, on_done):
        self.said.append(text)
        self._on_done = on_done

    @property
    def talking(self):
        return self._on_done is not None

    def finish(self):
        on_done, self._on_done = self._on_done, None
        on_done()


@pytest.fixture
def door():
    """A started core with its fakes, all reachable from the test."""
    bus, clock, light, speaker = FakeBus(), FakeClock(), FakeLight(), FakeSpeaker()
    core = DoorCore(bus, clock, light, speaker)
    core.start()
    return SimpleNamespace(core=core, bus=bus, clock=clock, light=light, speaker=speaker)


def send(door, topic, **fields):
    door.bus.inject(topic, json.dumps(fields))


def cards_published(door):
    return [message["card_id"] for message in door.bus.published_on(topics.DOOR_RFID)]


# --- Cards -------------------------------------------------------------------------


def test_a_card_is_published_with_its_id_and_time(door):
    door.core.on_card(CARD)
    [message] = door.bus.published_on(topics.DOOR_RFID)
    assert message == {"ts": door.clock.now().isoformat(timespec="seconds"), "card_id": CARD}


def test_the_same_card_within_the_debounce_time_is_ignored(door):
    door.core.on_card(CARD)
    door.clock.advance(CARD_DEBOUNCE_SECONDS - 0.5)
    door.core.on_card(CARD)
    assert cards_published(door) == [CARD]


def test_the_same_card_after_the_debounce_time_is_published_again(door):
    door.core.on_card(CARD)
    door.clock.advance(CARD_DEBOUNCE_SECONDS + 0.5)
    door.core.on_card(CARD)
    assert cards_published(door) == [CARD, CARD]


def test_a_card_held_in_front_of_the_reader_counts_once(door):
    # The reader repeats it every half second while it is held.
    for _ in range(6):
        door.core.on_card(CARD)
        door.clock.advance(0.5)
    assert cards_published(door) == [CARD]


def test_a_different_card_is_published_at_once(door):
    door.core.on_card(CARD)
    door.core.on_card(OTHER_CARD)
    assert cards_published(door) == [CARD, OTHER_CARD]


# --- PIR ---------------------------------------------------------------------------


def test_motion_is_published_while_the_pir_is_on(door):
    door.core.on_motion()
    assert len(door.bus.published_on(topics.DOOR_MOTION)) == 1


def test_motion_is_ignored_while_the_pir_is_disabled(door):
    send(door, topics.DOOR_PIR_ENABLE, enabled=False)
    door.core.on_motion()
    assert door.bus.published_on(topics.DOOR_MOTION) == []


def test_motion_is_published_again_after_the_pir_is_enabled(door):
    send(door, topics.DOOR_PIR_ENABLE, enabled=False)
    send(door, topics.DOOR_PIR_ENABLE, enabled=True)
    door.core.on_motion()
    assert len(door.bus.published_on(topics.DOOR_MOTION)) == 1


def test_cards_are_read_even_while_the_pir_is_disabled(door):
    send(door, topics.DOOR_PIR_ENABLE, enabled=False)
    door.core.on_card(CARD)
    assert cards_published(door) == [CARD]


# --- LEDs --------------------------------------------------------------------------


@pytest.mark.parametrize("color", messages.LED_COLORS)
def test_pulse_lights_the_led_and_switches_it_off_after_3_seconds(door, color):
    send(door, topics.DOOR_LED_CMD, color=color, mode="pulse")
    assert door.light.lit[color] is True
    door.clock.advance(PULSE_SECONDS - 0.1)
    assert door.light.lit[color] is True
    door.clock.advance(0.2)
    assert door.light.lit[color] is False


def test_pulse_only_touches_the_colour_in_the_order(door):
    send(door, topics.DOOR_LED_CMD, color="green", mode="pulse")
    assert door.light.lit == {"green": True, "red": False}


def test_a_new_pulse_restarts_the_3_seconds(door):
    send(door, topics.DOOR_LED_CMD, color="red", mode="pulse")
    door.clock.advance(2)
    send(door, topics.DOOR_LED_CMD, color="red", mode="pulse")
    door.clock.advance(2)
    assert door.light.lit["red"] is True
    door.clock.advance(1.1)
    assert door.light.lit["red"] is False


def test_blink_goes_on_and_off_until_off_arrives(door):
    send(door, topics.DOOR_LED_CMD, color="red", mode="blink")
    seen = []
    for _ in range(4):
        seen.append(door.light.lit["red"])
        door.clock.advance(BLINK_HALF_PERIOD_SECONDS)
    assert seen == [True, False, True, False]

    send(door, topics.DOOR_LED_CMD, color="red", mode="off")
    door.clock.advance(10)
    assert door.light.lit["red"] is False
    assert door.clock.pending() == 0


def test_off_cancels_a_pulse(door):
    send(door, topics.DOOR_LED_CMD, color="green", mode="pulse")
    send(door, topics.DOOR_LED_CMD, color="green", mode="off")
    assert door.light.lit["green"] is False
    assert door.clock.pending() == 0


def test_a_pulse_on_one_colour_does_not_stop_the_other_blinking(door):
    send(door, topics.DOOR_LED_CMD, color="red", mode="blink")
    send(door, topics.DOOR_LED_CMD, color="green", mode="pulse")
    door.clock.advance(PULSE_SECONDS + BLINK_HALF_PERIOD_SECONDS)
    assert door.light.lit["green"] is False
    assert ("red", "off") in door.light.changes and door.clock.pending() == 1


def test_an_led_order_with_an_unknown_colour_is_discarded(door):
    door.bus.inject(topics.DOOR_LED_CMD, json.dumps({"color": "blue", "mode": "pulse"}))
    assert door.light.changes == []


# --- Speech ------------------------------------------------------------------------


def test_a_text_is_said_at_once(door):
    send(door, topics.DOOR_SPEAKER_SAY, text="Welcome, Gloria.")
    assert door.speaker.said == ["Welcome, Gloria."]


def test_texts_are_not_queued_only_the_latest_is_said_next(door):
    send(door, topics.DOOR_SPEAKER_SAY, text="first")
    send(door, topics.DOOR_SPEAKER_SAY, text="second")
    send(door, topics.DOOR_SPEAKER_SAY, text="third")
    door.speaker.finish()
    assert door.speaker.said == ["first", "third"]
    door.speaker.finish()
    assert door.speaker.talking is False


def test_after_a_text_ends_the_next_one_is_said_at_once(door):
    send(door, topics.DOOR_SPEAKER_SAY, text="first")
    door.speaker.finish()
    send(door, topics.DOOR_SPEAKER_SAY, text="second")
    assert door.speaker.said == ["first", "second"]


# --- Alarm -------------------------------------------------------------------------


def test_the_alarm_is_said_at_once_and_every_interval(door):
    send(door, topics.DOOR_ALARM, enabled=True)
    for _ in range(2):
        door.speaker.finish()
        door.clock.advance(INTERVAL)
    assert door.speaker.said == [ALARM, ALARM, ALARM]


def test_switching_the_alarm_off_stops_it(door):
    send(door, topics.DOOR_ALARM, enabled=True)
    door.speaker.finish()
    send(door, topics.DOOR_ALARM, enabled=False)
    door.clock.advance(INTERVAL * 5)
    assert door.speaker.said == [ALARM]
    assert door.clock.pending() == 0


def test_an_alarm_text_still_waiting_is_dropped_when_the_alarm_stops(door):
    send(door, topics.DOOR_ALARM, enabled=True)
    door.clock.advance(INTERVAL)  # the first sentence is still playing: the next one waits
    send(door, topics.DOOR_ALARM, enabled=False)
    door.speaker.finish()
    assert door.speaker.said == [ALARM]
    assert door.speaker.talking is False


def test_turning_the_alarm_on_twice_does_not_double_it(door):
    send(door, topics.DOOR_ALARM, enabled=True)
    send(door, topics.DOOR_ALARM, enabled=True)
    door.speaker.finish()
    door.clock.advance(INTERVAL)
    assert door.speaker.said == [ALARM, ALARM]
    assert door.clock.pending() == 1


def test_a_text_from_the_brain_during_the_alarm_is_said_next(door):
    send(door, topics.DOOR_ALARM, enabled=True)
    send(door, topics.DOOR_SPEAKER_SAY, text="Help is coming.")
    door.speaker.finish()
    assert door.speaker.said == [ALARM, "Help is coming."]


# --- Time --------------------------------------------------------------------------


def test_timestamps_are_utc_with_their_offset(door):
    door.core.on_motion()
    [message] = door.bus.published_on(topics.DOOR_MOTION)
    assert message["ts"].endswith("+00:00")
