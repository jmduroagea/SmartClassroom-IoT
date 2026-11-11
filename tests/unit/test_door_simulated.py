"""Unit tests of the simulated hardware of the Door Pi (door/adapters/simulated.py)
and of how door/main.py chooses the hardware."""

from common.config import load_config
from door.adapters.simulated import KeyboardInput, PrintLight, PrintSpeaker
from door.main import build_hardware


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
