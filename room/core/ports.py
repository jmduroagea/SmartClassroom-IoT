"""The Room Pi's ports: what the core needs from the hardware.

The core only knows these three interfaces. The real devices (DS18B20, FS90R
servo, Vosk) and the fakes for tests are adapters in room/adapters/.
"""

from __future__ import annotations

from typing import Callable, Protocol


class SensorError(Exception):
    """The temperature could not be read, or the reading cannot be trusted."""


class TemperatureSensor(Protocol):
    def read(self) -> float:
        """One reading in °C. Raise SensorError if there is none."""
        ...


class Fan(Protocol):
    def set_speed(self, speed: int) -> None:
        """Move the fan to one of messages.FAN_SPEEDS (0 is stopped)."""
        ...


class SpeechRecognizer(Protocol):
    def listen(self, on_phrase: Callable[[str], None]) -> None:
        """Call on_phrase(text) for every phrase heard. Blocks forever."""
        ...
