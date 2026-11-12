"""Unit tests of the simulated hardware of the Door Pi (door/adapters/simulated.py)
and of how door/main.py chooses the hardware. The sim/ topic fakes use a fake
paho client, so no broker is needed."""

import json
import threading
from types import SimpleNamespace

from common.config import load_config
from door.adapters.simulated import (
    SIM_CARD,
    SIM_LED,
    SIM_MOTION,
    SIM_SAID,
    KeyboardInput,
    PrintLight,
    PrintSpeaker,
    SimLink,
    TopicInputs,
    TopicLight,
    TopicSpeaker,
)
from door.main import build_hardware, build_sim_topics_hardware


def test_keyboard_lines_are_cards_and_m_is_motion():
    events = []
    lines = ["0F00A1B2C3\n", "m\n", "\n", "M\n", "  0F00C4D5E6  \n"]
    KeyboardInput(lines=lines).run(lambda card: events.append(card), lambda: events.append("motion"))
    assert events == ["0F00A1B2C3", "motion", "motion", "0F00C4D5E6"]


def test_print_light_prints_each_change(capsys):
    light = PrintLight()
    light.on("green")
    light.off("green")
    assert capsys.readouterr().out.splitlines() == ["[led] green on", "[led] green off"]


def test_print_speaker_prints_and_finishes_at_once(capsys):
    done = []
    PrintSpeaker().play("Welcome, Gloria.", lambda: done.append(True))
    assert capsys.readouterr().out.strip() == "[speaker] Welcome, Gloria."
    assert done == [True]


def test_simulate_chooses_the_simulated_hardware():
    inputs, light, speaker = build_hardware(True, load_config({}))
    assert isinstance(inputs, KeyboardInput)
    assert isinstance(light, PrintLight)
    assert isinstance(speaker, PrintSpeaker)


# --- Driven by sim/ topics (Docker simulation) ---------------------------------------

class FakePahoClient:
    """Records what the link does with paho, and lets the test deliver messages."""

    def __init__(self):
        self.subscribed = []
        self.published = []
        self.connected_to = None
        self.on_connect = self.on_message = None

    def connect_async(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.on_connect(self, None, None, 0, None)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def subscribe(self, topic, qos):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos):
        self.published.append((topic, json.loads(payload)))

    def deliver(self, topic, payload):
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload.encode()))


def make_link():
    client = FakePahoClient()
    return SimLink("broker", 1883, client=client), client


def run_inputs(link):
    """Start TopicInputs in a thread, as main.py does, and collect what it reports."""
    events = []
    inputs = TopicInputs(link)
    thread = threading.Thread(
        target=inputs.run, args=(events.append, lambda: events.append("motion")), daemon=True
    )
    thread.start()
    return inputs, thread, events


def wait_until_subscribed(client, count=2):
    for _ in range(100):
        if len(client.subscribed) >= count:
            return
        threading.Event().wait(0.01)
    raise AssertionError(f"not subscribed: {client.subscribed}")


def test_topic_inputs_turn_sim_messages_into_cards_and_motion():
    link, client = make_link()
    inputs, thread, events = run_inputs(link)
    wait_until_subscribed(client)
    assert client.connected_to == ("broker", 1883)
    assert sorted(client.subscribed) == sorted([SIM_CARD, SIM_MOTION])

    client.deliver(SIM_CARD, '{"card_id": " 0F00A1B2C3 "}')
    client.deliver(SIM_MOTION, "{}")
    inputs.stop()
    thread.join(timeout=1)

    assert events == ["0F00A1B2C3", "motion"]
    assert not thread.is_alive()


def test_bad_sim_messages_are_ignored():
    link, client = make_link()
    inputs, thread, events = run_inputs(link)
    wait_until_subscribed(client)
    for payload in ["not json", "[1, 2]", "{}", '{"card_id": ""}', '{"card_id": 7}']:
        client.deliver(SIM_CARD, payload)
    client.deliver("sim/door/other", '{"card_id": "X"}')
    inputs.stop()
    thread.join(timeout=1)
    assert events == []


def test_subscriptions_are_made_again_after_a_reconnection():
    link, client = make_link()
    link.subscribe(SIM_CARD, lambda data: None)
    link.start()
    client.on_connect(client, None, None, 0, None)  # the broker came back
    assert client.subscribed == [SIM_CARD, SIM_CARD]


def test_topic_light_reports_each_change():
    link, client = make_link()
    light = TopicLight(link)
    light.on("green")
    light.off("red")
    assert client.published == [
        (SIM_LED, {"color": "green", "on": True}),
        (SIM_LED, {"color": "red", "on": False}),
    ]


def test_topic_speaker_reports_the_text_and_finishes_at_once():
    link, client = make_link()
    done = []
    TopicSpeaker(link).play("Welcome, Gloria.", lambda: done.append(True))
    assert client.published == [(SIM_SAID, {"text": "Welcome, Gloria."})]
    assert done == [True]


def test_sim_topics_hardware_shares_one_link():
    inputs, light, speaker = build_sim_topics_hardware(load_config({}))
    assert isinstance(inputs, TopicInputs)
    assert isinstance(light, TopicLight)
    assert isinstance(speaker, TopicSpeaker)
    assert inputs._link is light._link is speaker._link
