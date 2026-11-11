"""Unit tests of the voice mapping (room/core/voice.py), test T27."""

import pytest

from common import messages
from room.core.voice import ALL_PHRASES, PHRASES, command_for


@pytest.mark.parametrize("wake", ["ok computer", "okay computer"])
@pytest.mark.parametrize(
    "phrase, command",
    [
        ("i'm hot", "hot"),
        ("i'm cold", "cold"),
        ("what's the temperature", "temp"),
        ("help", "help"),
    ],
)
def test_every_phrase_after_the_wake_word_gives_its_command(wake, phrase, command):
    assert command_for(f"{wake} {phrase}") == command


@pytest.mark.parametrize(
    "text",
    [
        "i'm hot",                  # no wake word (T27)
        "help",
        "computer i'm hot",         # half a wake word
        "ok i'm hot",
        "i'm hot ok computer",      # wake word at the end
    ],
)
def test_phrase_without_the_wake_word_is_ignored(text):
    assert command_for(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "ok computer",              # wake word alone
        "ok computer dance",        # not one of our phrases
        "ok computer i'm hot please",
        "[unk]",                    # what Vosk gives for anything else
        "",
    ],
)
def test_unknown_phrase_is_ignored(text):
    assert command_for(text) is None


def test_case_and_extra_spaces_do_not_matter():
    assert command_for("  OK   Computer  I'm HOT ") == "hot"


def test_the_commands_are_the_ones_in_the_contract():
    assert set(PHRASES.values()) == set(messages.VOICE_COMMANDS)


def test_the_grammar_has_every_phrase_with_every_wake_word():
    assert len(ALL_PHRASES) == 8
    assert "okay computer what's the temperature" in ALL_PHRASES
