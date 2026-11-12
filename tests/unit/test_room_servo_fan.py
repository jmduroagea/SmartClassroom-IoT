"""Unit tests of the servo fan adapter (room/adapters/servo_fan.py), with a
fake RPi.GPIO module, so no Pi is needed."""

import pytest

from common import messages
from room.adapters.servo_fan import DUTY_CYCLE_BY_SPEED, NO_PULSE, STOPPED, ServoFan


class FakePWM:
    def __init__(self, pin, frequency):
        self.pin = pin
        self.frequency = frequency
        self.duty_cycles = []   # every duty cycle it was given, in order
        self.running = False

    def start(self, duty_cycle):
        self.running = True
        self.duty_cycles.append(duty_cycle)

    def ChangeDutyCycle(self, duty_cycle):
        self.duty_cycles.append(duty_cycle)

    def stop(self):
        self.running = False


class FakeGPIO:
    """Just the part of RPi.GPIO the adapter uses."""

    BCM = "BCM"
    OUT = "OUT"

    def __init__(self):
        self.mode = None
        self.outputs = []
        self.pwm = None
        self.cleaned = []

    def setmode(self, mode):
        self.mode = mode

    def setup(self, pin, direction):
        if direction == self.OUT:
            self.outputs.append(pin)

    def PWM(self, pin, frequency):
        self.pwm = FakePWM(pin, frequency)
        return self.pwm

    def cleanup(self, pin):
        self.cleaned.append(pin)


@pytest.fixture
def gpio():
    return FakeGPIO()


def test_starts_stopped_on_gpio18_at_50_hz(gpio):
    ServoFan(gpio)
    assert gpio.mode == gpio.BCM
    assert gpio.outputs == [18]
    assert (gpio.pwm.pin, gpio.pwm.frequency) == (18, 50)
    assert gpio.pwm.running
    assert gpio.pwm.duty_cycles == [NO_PULSE]   # no pulse: the servo does not move


@pytest.mark.parametrize("speed", [0, 1, 2, 3])
def test_each_speed_sets_its_duty_cycle(gpio, speed):
    ServoFan(gpio).set_speed(speed)
    assert gpio.pwm.duty_cycles[-1] == DUTY_CYCLE_BY_SPEED[speed]


def test_speed_0_sends_no_pulse_so_the_servo_cannot_creep(gpio):
    fan = ServoFan(gpio)
    fan.set_speed(2)
    fan.set_speed(STOPPED)
    assert gpio.pwm.duty_cycles[-1] == NO_PULSE


def test_higher_speed_means_wider_pulse():
    duty_cycles = [DUTY_CYCLE_BY_SPEED[speed] for speed in sorted(DUTY_CYCLE_BY_SPEED)]
    assert duty_cycles == sorted(set(duty_cycles))


def test_there_is_a_duty_cycle_for_every_speed_of_the_contract():
    assert set(DUTY_CYCLE_BY_SPEED) == set(messages.FAN_SPEEDS)


def test_unknown_speed_is_refused_and_the_fan_does_not_change(gpio):
    fan = ServoFan(gpio)
    with pytest.raises(ValueError):
        fan.set_speed(9)
    assert gpio.pwm.duty_cycles == [NO_PULSE]


def test_stop_stops_the_fan_and_frees_the_pin(gpio):
    fan = ServoFan(gpio)
    fan.set_speed(3)
    fan.stop()
    assert gpio.pwm.duty_cycles[-1] == NO_PULSE
    assert not gpio.pwm.running
    assert gpio.cleaned == [18]
