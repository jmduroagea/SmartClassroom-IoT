"""Unit tests of the clock port (common/clock.py)."""

import threading
from datetime import timedelta, timezone

import pytest

from common.clock import FAKE_START, FakeClock, SystemClock

# --- FakeClock: time --------------------------------------------------------


def test_fake_clock_starts_at_a_fixed_utc_time():
    clock = FakeClock()
    assert clock.now() == FAKE_START
    assert clock.now().tzinfo == timezone.utc


def test_advance_moves_the_time():
    clock = FakeClock()
    clock.advance(90)
    assert clock.now() == FAKE_START + timedelta(seconds=90)


# --- Callbacks fire at the right time ---------------------------------------


def test_callback_does_not_fire_before_its_time():
    clock = FakeClock()
    fired = []
    clock.schedule(3, lambda: fired.append("prompt"))
    clock.advance(2.9)
    assert fired == []


def test_callback_fires_exactly_at_its_time():
    clock = FakeClock()
    fired = []
    clock.schedule(3, lambda: fired.append("prompt"))
    clock.advance(3)
    assert fired == ["prompt"]


def test_inside_the_callback_now_is_the_alarm_time():
    clock = FakeClock()
    seen = []
    clock.schedule(3, lambda: seen.append(clock.now()))
    clock.advance(10)
    assert seen == [FAKE_START + timedelta(seconds=3)]


def test_callback_fires_only_once():
    clock = FakeClock()
    fired = []
    clock.schedule(1, lambda: fired.append("x"))
    clock.advance(5)
    clock.advance(5)
    assert fired == ["x"]


def test_small_steps_work_like_one_big_step():
    clock = FakeClock()
    fired = []
    clock.schedule(120, lambda: fired.append("not evacuated"))
    for _ in range(119):
        clock.advance(1)
    assert fired == []
    clock.advance(1)
    assert fired == ["not evacuated"]


# --- Callbacks fire in order ------------------------------------------------


def test_callbacks_fire_in_time_order():
    clock = FakeClock()
    fired = []
    clock.schedule(30, lambda: fired.append("back to idle"))
    clock.schedule(3, lambda: fired.append("prompt"))
    clock.schedule(8, lambda: fired.append("reminder"))
    clock.advance(60)
    assert fired == ["prompt", "reminder", "back to idle"]


def test_callbacks_due_at_the_same_time_fire_in_scheduling_order():
    clock = FakeClock()
    fired = []
    clock.schedule(5, lambda: fired.append("first"))
    clock.schedule(5, lambda: fired.append("second"))
    clock.advance(5)
    assert fired == ["first", "second"]


def test_alarm_set_by_another_alarm_fires_in_the_same_advance():
    # The brain's real case: the prompt at 3 s sets the reminder 5 s later.
    clock = FakeClock()
    fired = []

    def prompt():
        fired.append(("prompt", clock.now()))
        clock.schedule(5, lambda: fired.append(("reminder", clock.now())))

    clock.schedule(3, prompt)
    clock.advance(8)
    assert fired == [
        ("prompt", FAKE_START + timedelta(seconds=3)),
        ("reminder", FAKE_START + timedelta(seconds=8)),
    ]


# --- Cancelling works -------------------------------------------------------


def test_cancelled_callback_never_fires():
    clock = FakeClock()
    fired = []
    alarm = clock.schedule(3, lambda: fired.append("prompt"))
    alarm.cancel()
    clock.advance(10)
    assert fired == []
    assert clock.pending() == 0


def test_cancelling_one_alarm_keeps_the_others():
    clock = FakeClock()
    fired = []
    clock.schedule(3, lambda: fired.append("prompt"))
    reminder = clock.schedule(8, lambda: fired.append("reminder"))
    reminder.cancel()
    clock.advance(10)
    assert fired == ["prompt"]


def test_an_alarm_can_cancel_a_later_one():
    # The card arrives at 2 s: its handler cancels the prompt due at 3 s.
    clock = FakeClock()
    fired = []
    prompt = clock.schedule(3, lambda: fired.append("prompt"))
    clock.schedule(2, prompt.cancel)
    clock.advance(10)
    assert fired == []


def test_cancelling_twice_or_after_firing_is_harmless():
    clock = FakeClock()
    alarm = clock.schedule(1, lambda: None)
    clock.advance(1)
    alarm.cancel()
    alarm.cancel()


# --- Invalid durations ------------------------------------------------------


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), "3", True])
def test_invalid_delay_is_rejected(seconds):
    with pytest.raises(ValueError):
        FakeClock().schedule(seconds, lambda: None)


def test_going_back_in_time_is_rejected():
    with pytest.raises(ValueError):
        FakeClock().advance(-1)


# --- SystemClock (real time, very short delays) ------------------------------


def test_system_clock_gives_utc_time():
    assert SystemClock().now().tzinfo == timezone.utc


def test_system_clock_fires_the_callback():
    done = threading.Event()
    SystemClock().schedule(0.01, done.set)
    assert done.wait(timeout=2)


def test_system_clock_alarm_can_be_cancelled():
    done = threading.Event()
    alarm = SystemClock().schedule(0.2, done.set)
    alarm.cancel()
    assert not done.wait(timeout=0.4)
