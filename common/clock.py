"""Time as a port: every program asks this clock for the time and for timers.

The brain waits 3 s, 5 s, 30 s, 60 s and 2 min. Tests cannot wait for real,
so the code never calls time.time(), time.sleep() or threading.Timer itself:
it receives a Clock.

- SystemClock is the real clock, used on the Raspberry Pis.
- FakeClock is a clock for tests: time only moves when the test calls
  advance(seconds), and it moves instantly, firing every alarm on the way.

Usage:
    alarm = clock.schedule(3, ask_for_card)   # in 3 seconds, call ask_for_card()
    alarm.cancel()                            # the card arrived: no need to ask
"""

from __future__ import annotations

import itertools
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Protocol

# FakeClock starts at a fixed moment, so tests always give the same result.
FAKE_START = datetime(2026, 11, 10, 9, 0, 0, tzinfo=timezone.utc)


class TimerHandle(Protocol):
    """What schedule() returns: something you can cancel."""

    def cancel(self) -> None: ...


class Clock(Protocol):
    """The port: what any clock must offer."""

    def now(self) -> datetime:
        """Current time, in UTC (MongoDB stores UTC)."""
        ...

    def schedule(self, delay: float, callback: Callable[[], None]) -> TimerHandle:
        """Call callback() in `delay` seconds. Return a handle to cancel it."""
        ...


def _check_seconds(seconds: float) -> None:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError(f"seconds must be a number, got {seconds!r}")
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"seconds must be a finite number >= 0, got {seconds!r}")


class SystemClock:
    """The real clock. Each alarm is a threading.Timer (it already has cancel())."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def schedule(self, delay: float, callback: Callable[[], None]) -> TimerHandle:
        _check_seconds(delay)
        timer = threading.Timer(delay, callback)
        timer.daemon = True  # an alarm never keeps the program alive at exit
        timer.start()
        return timer


@dataclass(eq=False)
class FakeAlarm:
    """An alarm of the FakeClock. It is also the handle returned to the caller."""

    due: datetime
    order: int  # alarms due at the same time fire in the order they were set
    callback: Callable[[], None]
    cancelled: bool = field(default=False)

    def cancel(self) -> None:
        self.cancelled = True


class FakeClock:
    """A clock for tests. Time only moves with advance(), and instantly."""

    def __init__(self, start: datetime = FAKE_START) -> None:
        self._now = start
        self._alarms: List[FakeAlarm] = []
        self._counter = itertools.count()

    def now(self) -> datetime:
        return self._now

    def schedule(self, delay: float, callback: Callable[[], None]) -> TimerHandle:
        _check_seconds(delay)
        alarm = FakeAlarm(self._now + timedelta(seconds=delay), next(self._counter), callback)
        self._alarms.append(alarm)
        return alarm

    def advance(self, seconds: float) -> None:
        """Move time forward, firing every alarm that falls due, in order.

        An alarm set by another alarm also fires if it falls inside the same
        advance: advance(8) fires a 3 s prompt and the 5 s reminder it sets.
        """
        _check_seconds(seconds)
        target = self._now + timedelta(seconds=seconds)
        while True:
            due = [a for a in self._alarms if a.due <= target and not a.cancelled]
            if not due:
                break
            alarm = min(due, key=lambda a: (a.due, a.order))
            self._alarms.remove(alarm)
            self._now = alarm.due  # inside the callback, now() is the alarm time
            alarm.callback()
        self._alarms = [a for a in self._alarms if not a.cancelled]
        self._now = target

    def pending(self) -> int:
        """Number of alarms waiting (useful in tests)."""
        return sum(1 for a in self._alarms if not a.cancelled)
