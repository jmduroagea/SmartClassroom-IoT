"""Simulated hardware, so the Room Pi runs without a Raspberry Pi.

`python -m room.main --simulate` (a person at the keyboard):
- SimulatedSensor: a room at 21 °C with a little noise. heat() warms it up,
  to try the emergency without a glass of hot water.
- PrintFan: prints the speed instead of moving a servo.
- KeyboardMicrophone: every line typed is a phrase heard, e.g.
  "ok computer i'm hot". A line like "+5" or "-2" heats or cools the sensor.

`python -m room.main --sim-topics` (the Docker simulation, driven by the
scenario tests over MQTT, see common/sim_link.py):
- TopicSensor: 21 °C exactly, with no noise, until a test publishes another
  temperature on sim/room/temp. Without noise it never looks like a rise.
- TopicFan: reports every speed on sim/room/fan.
- TopicMicrophone: a phrase published on sim/room/voice is heard as if Vosk
  had recognised it, so it goes through the wake word and the phrase list.
"""

from __future__ import annotations

import logging
import random
import sys
import threading
from typing import Callable, Iterable, Optional

from common.sim_link import SimLink

BASE_TEMPERATURE = 21.0
NOISE_DEGREES = 0.1
DECIMALS = 2
HEAT_SIGNS = ("+", "-")

SIM_TEMP = "sim/room/temp"     # {"temp": 25.0}
SIM_VOICE = "sim/room/voice"   # {"text": "ok computer i'm hot"}
SIM_FAN = "sim/room/fan"       # {"speed": 2}
SIM_CLIENT_ID = "room-pi-sim"

logger = logging.getLogger(__name__)


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


# --- Driven by sim/ topics ------------------------------------------------------------


class TopicSensor:
    def __init__(self, link: SimLink) -> None:
        self._temp = BASE_TEMPERATURE
        link.subscribe(SIM_TEMP, self._on_temp)

    def read(self) -> float:
        return self._temp

    def _on_temp(self, data: dict) -> None:
        temp = data.get("temp")
        if isinstance(temp, (int, float)) and not isinstance(temp, bool):
            self._temp = float(temp)
        else:
            logger.warning("ignored %s without a number in temp: %r", SIM_TEMP, data)


class TopicFan:
    def __init__(self, link: SimLink) -> None:
        self._link = link

    def set_speed(self, speed: int) -> None:
        self._link.publish(SIM_FAN, speed=speed)

    def stop(self) -> None:
        pass


class TopicMicrophone:
    def __init__(self, link: SimLink) -> None:
        self._link = link
        self._stopped = threading.Event()

    def listen(self, on_phrase: Callable[[str], None]) -> None:
        """Listen until stop(). The phrases arrive on the link's own thread."""

        def phrase(data: dict) -> None:
            text = data.get("text")
            if isinstance(text, str):
                on_phrase(text)
            else:
                logger.warning("ignored %s without a text: %r", SIM_VOICE, data)

        self._link.subscribe(SIM_VOICE, phrase)
        self._link.start()
        self._stopped.wait()

    def stop(self) -> None:
        self._stopped.set()
        self._link.stop()
