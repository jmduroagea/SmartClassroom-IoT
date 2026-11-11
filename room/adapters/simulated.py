"""Simulated hardware for `python -m room.main --simulate`, so the Room Pi runs
on any laptop:

- SimulatedSensor: a room at 21 °C with a little noise. heat() warms it up,
  to try the emergency without a glass of hot water.
- PrintFan: prints the speed instead of moving a servo.
- KeyboardMicrophone: every line typed is a phrase heard, e.g.
  "ok computer i'm hot". A line like "+5" or "-2" heats or cools the sensor.
"""

from __future__ import annotations

import random
import sys
from typing import Callable, Iterable, Optional

BASE_TEMPERATURE = 21.0
NOISE_DEGREES = 0.1
DECIMALS = 2
HEAT_SIGNS = ("+", "-")


class SimulatedSensor:
    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng or random.Random()
        self._offset = 0.0

    def heat(self, degrees: float) -> None:
        self._offset += degrees

    def read(self) -> float:
        noise = self._rng.uniform(-NOISE_DEGREES, NOISE_DEGREES)
        return round(BASE_TEMPERATURE + self._offset + noise, DECIMALS)


class PrintFan:
    def set_speed(self, speed: int) -> None:
        print(f"[fan] speed {speed}")

    def stop(self) -> None:
        print("[fan] stopped")


def heat_in(line: str) -> Optional[float]:
    """The degrees in a line like "+5" or "-2", or None if it is a phrase."""
    if not line.startswith(HEAT_SIGNS):
        return None
    try:
        return float(line)
    except ValueError:
        return None


class KeyboardMicrophone:
    def __init__(self, sensor: SimulatedSensor, lines: Optional[Iterable[str]] = None) -> None:
        """`lines` is the keyboard (stdin); tests pass a list instead."""
        self._sensor = sensor
        self._lines = lines

    def listen(self, on_phrase: Callable[[str], None]) -> None:
        print('Type a phrase ("ok computer i\'m hot") or "+5" to heat the sensor.')
        for line in self._lines if self._lines is not None else sys.stdin:
            line = line.strip()
            degrees = heat_in(line)
            if degrees is not None:
                self._sensor.heat(degrees)
                print(f"[sim] sensor {degrees:+g} °C")
            elif line:
                on_phrase(line)
