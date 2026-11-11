"""The real fan: an FS90R continuous-rotation servo, driven by PWM on GPIO18.

A continuous servo does not turn to an angle: the width of its pulse sets the
speed. At 50 Hz, a 1.5 ms pulse (a duty cycle of 7.5 %) stops it, and wider
pulses turn it faster. The duty cycles below are a first guess; issue #15
calibrates them on the real servo.
"""

from __future__ import annotations

FAN_PIN = 18                # BCM numbering (physical pin 12)
PWM_FREQUENCY_HZ = 50       # servos expect one pulse every 20 ms
STOPPED = 0
# Speed of the contract (messages.FAN_SPEEDS) -> duty cycle in %. Provisional (#15).
DUTY_CYCLE_BY_SPEED = {0: 7.5, 1: 8.5, 2: 9.2, 3: 10.0}


def _load_gpio():
    import RPi.GPIO  # only installed on the Raspberry Pi

    return RPi.GPIO


class ServoFan:
    def __init__(self, gpio=None, pin: int = FAN_PIN) -> None:
        """`gpio` is the RPi.GPIO module; the tests pass a fake one."""
        self._gpio = gpio if gpio is not None else _load_gpio()
        self._pin = pin
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setup(pin, self._gpio.OUT)
        self._pwm = self._gpio.PWM(pin, PWM_FREQUENCY_HZ)
        self._pwm.start(DUTY_CYCLE_BY_SPEED[STOPPED])

    def set_speed(self, speed: int) -> None:
        if speed not in DUTY_CYCLE_BY_SPEED:
            raise ValueError(f"no duty cycle for fan speed {speed!r}")
        self._pwm.ChangeDutyCycle(DUTY_CYCLE_BY_SPEED[speed])

    def stop(self) -> None:
        """Stop the fan and free the pin. Called once, when the program ends."""
        self._pwm.ChangeDutyCycle(DUTY_CYCLE_BY_SPEED[STOPPED])
        self._pwm.stop()
        self._gpio.cleanup(self._pin)
