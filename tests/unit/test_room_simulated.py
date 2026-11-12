"""Unit tests of the simulated hardware (room/adapters/simulated.py) and of how
room/main.py chooses the hardware."""

import random
import threading

import pytest

from common.config import load_config
from common.sim_link import SimLink
from room.adapters.simulated import (
    BASE_TEMPERATURE,
    SIM_FAN,
    SIM_TEMP,
    SIM_VOICE,
    KeyboardMicrophone,
    PrintFan,
    SimulatedSensor,
    TopicFan,
    TopicMicrophone,
    TopicSensor,
    heat_in,
)
from room.main import build_hardware, build_sim_topics_hardware
from tests.unit.fake_paho import FakePahoClient


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


# --- Driven by sim/ topics (Docker simulation) ---------------------------------------


def make_link():
    client = FakePahoClient()
    return SimLink("broker", 1883, "room-pi-sim", client=client), client


def start_listening(link):
    """Start TopicMicrophone in a thread, as main.py does, and collect the phrases."""
    heard = []
    microphone = TopicMicrophone(link)
    thread = threading.Thread(target=microphone.listen, args=(heard.append,), daemon=True)
    thread.start()
    return microphone, thread, heard


def wait_until_subscribed(client, topic):
    for _ in range(100):
        if topic in client.subscribed:
            return
        threading.Event().wait(0.01)
    raise AssertionError(f"not subscribed to {topic}: {client.subscribed}")


def test_topic_sensor_gives_21_degrees_without_noise():
    link, _client = make_link()
    sensor = TopicSensor(link)
    assert [sensor.read() for _ in range(5)] == [BASE_TEMPERATURE] * 5


def test_topic_sensor_takes_the_temperature_published_on_sim():
    link, client = make_link()
    sensor = TopicSensor(link)
    microphone, thread, _heard = start_listening(link)  # starts the link
    wait_until_subscribed(client, SIM_TEMP)

    client.deliver(SIM_TEMP, '{"temp": 26.5}')
    assert sensor.read() == 26.5
    for bad in ['{"temp": "hot"}', '{"temp": true}', "{}", "not json"]:
        client.deliver(SIM_TEMP, bad)
    assert sensor.read() == 26.5

    microphone.stop()
    thread.join(timeout=1)


def test_topic_microphone_hears_the_phrases_published_on_sim():
    link, client = make_link()
    microphone, thread, heard = start_listening(link)
    wait_until_subscribed(client, SIM_VOICE)

    client.deliver(SIM_VOICE, '{"text": "ok computer i\'m hot"}')
    client.deliver(SIM_VOICE, '{"text": 7}')
    microphone.stop()
    thread.join(timeout=1)

    assert heard == ["ok computer i'm hot"]
    assert not thread.is_alive()


def test_topic_fan_reports_each_speed():
    link, client = make_link()
    fan = TopicFan(link)
    fan.set_speed(2)
    fan.set_speed(0)
    assert client.published == [(SIM_FAN, {"speed": 2}), (SIM_FAN, {"speed": 0})]


def test_sim_topics_hardware_shares_one_link():
    sensor, fan, microphone = build_sim_topics_hardware(load_config({}))
    assert isinstance(sensor, TopicSensor)
    assert isinstance(fan, TopicFan)
    assert isinstance(microphone, TopicMicrophone)
    assert fan._link is microphone._link
