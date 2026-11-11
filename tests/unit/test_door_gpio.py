"""Unit tests of the GPIO adapters of the Door Pi (door/adapters/leds.py and pir.py),
with a fake RPi.GPIO module."""

import pytest

from door.adapters.leds import GREEN_PIN, RED_PIN, GpioDoorLight
from door.adapters.pir import BOUNCE_MILLISECONDS, PIR_PIN, GpioMotionSensor


class FakeGPIO:
    """Just the part of RPi.GPIO the adapters use. It remembers pin levels and callbacks."""

    BCM, IN, OUT, HIGH, LOW, RISING = "BCM", "IN", "OUT", 1, 0, "RISING"

    def __init__(self):
        self.mode = None
        self.setups = {}
        self.levels = {}
        self.callbacks = {}
        self.cleaned = []

    def setmode(self, mode):
        self.mode = mode

    def setup(self, pin, direction, initial=None):
        self.setups[pin] = direction
        if initial is not None:
            self.levels[pin] = initial

    def output(self, pin, level):
        self.levels[pin] = level

    def add_event_detect(self, pin, edge, callback, bouncetime):
        self.callbacks[pin] = (edge, callback, bouncetime)

    def remove_event_detect(self, pin):
        self.callbacks.pop(pin, None)

    def cleanup(self, pins):
        self.cleaned.append(pins)


@pytest.fixture
def gpio():
    return FakeGPIO()


# --- LEDs ----------------------------------------------------------------------------


def test_both_leds_start_as_outputs_and_off(gpio):
    GpioDoorLight(gpio)
    assert gpio.mode == "BCM"
    assert gpio.setups == {GREEN_PIN: "OUT", RED_PIN: "OUT"}
    assert gpio.levels == {GREEN_PIN: 0, RED_PIN: 0}


@pytest.mark.parametrize("color, pin", [("green", 27), ("red", 22)])
def test_each_colour_drives_its_own_pin(gpio, color, pin):
    light = GpioDoorLight(gpio)
    light.on(color)
    assert gpio.levels[pin] == 1
    light.off(color)
    assert gpio.levels[pin] == 0


def test_one_colour_does_not_touch_the_other(gpio):
    light = GpioDoorLight(gpio)
    light.on("green")
    assert gpio.levels[RED_PIN] == 0


def test_an_unknown_colour_is_an_error(gpio):
    with pytest.raises(KeyError):
        GpioDoorLight(gpio).on("blue")


def test_stop_switches_both_off_and_frees_the_pins(gpio):
    light = GpioDoorLight(gpio)
    light.on("green")
    light.on("red")
    light.stop()
    assert gpio.levels == {GREEN_PIN: 0, RED_PIN: 0}
    assert gpio.cleaned == [[GREEN_PIN, RED_PIN]]


# --- PIR -----------------------------------------------------------------------------


def test_the_pir_pin_is_an_input(gpio):
    GpioMotionSensor(gpio)
    assert gpio.setups == {PIR_PIN: "IN"}


def test_a_rising_edge_calls_on_motion(gpio):
    seen = []
    GpioMotionSensor(gpio).watch(lambda: seen.append("motion"))
    edge, callback, bouncetime = gpio.callbacks[PIR_PIN]
    assert (edge, bouncetime) == ("RISING", BOUNCE_MILLISECONDS)
    callback(PIR_PIN)  # what RPi.GPIO does on the edge
    assert seen == ["motion"]


def test_stop_removes_the_detection_and_frees_the_pin(gpio):
    sensor = GpioMotionSensor(gpio)
    sensor.watch(lambda: None)
    sensor.stop()
    assert gpio.callbacks == {}
    assert gpio.cleaned == [PIR_PIN]
