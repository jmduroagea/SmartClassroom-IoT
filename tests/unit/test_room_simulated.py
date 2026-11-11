"""Unit tests of the simulated hardware (room/adapters/simulated.py) and of how
room/main.py chooses the hardware."""

import random

import pytest

from common.config import load_config
from room.adapters.simulated import KeyboardMicrophone, PrintFan, SimulatedSensor, heat_in
from room.main import build_hardware


@pytest.fixture
def sensor():
    return SimulatedSensor(rng=random.Random(0))  # fixed seed: same noise every run


def test_sensor_starts_near_21_degrees(sensor):
    assert 20.9 <= sensor.read() <= 21.1


def test_heat_warms_the_sensor(sensor):
    sensor.heat(5)
    assert 25.9 <= sensor.read() <= 26.1


@pytest.mark.parametrize("line, degrees", [("+5", 5.0), ("-2", -2.0), ("+0.5", 0.5)])
def test_heat_lines_are_understood(line, degrees):
    assert heat_in(line) == degrees


@pytest.mark.parametrize("line", ["ok computer i'm hot", "+", "-abc", ""])
def test_other_lines_are_not_heat(line):
    assert heat_in(line) is None


def test_keyboard_sends_phrases_and_heats_the_sensor(sensor):
    heard = []
    lines = ["ok computer i'm hot\n", "+5\n", "\n", "help\n"]
    KeyboardMicrophone(sensor, lines=lines).listen(heard.append)
    assert heard == ["ok computer i'm hot", "help"]
    assert sensor.read() > 25


def test_simulate_chooses_the_simulated_hardware():
    sensor, fan, microphone = build_hardware(True, load_config({}))
    assert isinstance(sensor, SimulatedSensor)
    assert isinstance(fan, PrintFan)
    assert isinstance(microphone, KeyboardMicrophone)
