"""The real door LEDs: one LED per colour, each on its own pin.

The brain names the colour; this table turns it into a pin. The core never
knows about pins.
"""

from __future__ import annotations

GREEN_PIN = 27              # BCM numbering (physical pin 13)
RED_PIN = 22                # BCM numbering (physical pin 15)
PIN_BY_COLOR = {"green": GREEN_PIN, "red": RED_PIN}


def _load_gpio():
    import RPi.GPIO  # only installed on the Raspberry Pi

    return RPi.GPIO


class GpioDoorLight:
    def __init__(self, gpio=None) -> None:
        """`gpio` is the RPi.GPIO module; the tests pass a fake one."""
        self._gpio = gpio if gpio is not None else _load_gpio()
        self._gpio.setmode(self._gpio.BCM)
        for pin in PIN_BY_COLOR.values():
            self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)

    def on(self, color: str) -> None:
        self._gpio.output(PIN_BY_COLOR[color], self._gpio.HIGH)

    def off(self, color: str) -> None:
        self._gpio.output(PIN_BY_COLOR[color], self._gpio.LOW)

    def stop(self) -> None:
        """Switch both LEDs off and free the pins. Called once, when the program ends."""
        for color in PIN_BY_COLOR:
            self.off(color)
        self._gpio.cleanup(list(PIN_BY_COLOR.values()))
