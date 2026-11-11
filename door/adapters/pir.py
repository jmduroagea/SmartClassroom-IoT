"""The real motion sensor: a PIR on GPIO17.

The PIR raises its output when it sees movement and keeps it high for a while,
so only the rising edge counts, with a bounce time so one movement is one event.
"""

from __future__ import annotations

from typing import Callable

PIR_PIN = 17                # BCM numbering (physical pin 11)
BOUNCE_MILLISECONDS = 2000


def _load_gpio():
    import RPi.GPIO  # only installed on the Raspberry Pi

    return RPi.GPIO


class GpioMotionSensor:
    def __init__(self, gpio=None, pin: int = PIR_PIN) -> None:
        """`gpio` is the RPi.GPIO module; the tests pass a fake one."""
        self._gpio = gpio if gpio is not None else _load_gpio()
        self._pin = pin
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setup(pin, self._gpio.IN)

    def watch(self, on_motion: Callable[[], None]) -> None:
        """Call on_motion() on every movement. Returns at once (GPIO calls back)."""
        self._gpio.add_event_detect(
            self._pin, self._gpio.RISING, callback=lambda _channel: on_motion(), bouncetime=BOUNCE_MILLISECONDS
        )

    def stop(self) -> None:
        self._gpio.remove_event_detect(self._pin)
        self._gpio.cleanup(self._pin)
