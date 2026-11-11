"""Unit tests of the Vosk adapter (room/adapters/vosk_mic.py): the grammar and
the confidence rule, with results in Vosk's JSON format. The audio loop needs
the real microphone, so it is checked on the Pi (#70)."""

import json

import pytest

from room.adapters.vosk_mic import VoskMicrophone, accepted_text, grammar
from room.core import voice

PHRASE = "ok computer i'm hot"
# The rule under test, written here so recalibrating the constants (#70)
# does not change what these tests mean.
WORD_MIN = 0.4
AVERAGE_MIN = 0.7


def vosk_result(*confidences, text=PHRASE):
    """What KaldiRecognizer.Result() returns with SetWords(True)."""
    words = [{"word": word, "conf": conf} for word, conf in zip(text.split(), confidences)]
    return json.dumps({"result": words, "text": text})


def accepted(result_json):
    return accepted_text(result_json, word_min=WORD_MIN, average_min=AVERAGE_MIN)


def test_grammar_has_every_phrase_and_unk():
    assert json.loads(grammar()) == list(voice.ALL_PHRASES) + ["[unk]"]


def test_clear_phrase_is_accepted():
    assert accepted(vosk_result(1.0, 1.0, 1.0, 1.0)) == PHRASE


def test_one_word_a_bit_worse_is_tolerated():
    assert accepted(vosk_result(1.0, 1.0, 0.5, 1.0)) == PHRASE      # lowest 0.5, average 0.88


def test_one_very_doubtful_word_rejects_the_phrase():
    assert accepted(vosk_result(1.0, 1.0, 0.3, 1.0)) is None        # average still 0.83


def test_every_word_mediocre_rejects_the_phrase():
    assert accepted(vosk_result(0.6, 0.65, 0.6, 0.7)) is None       # none below 0.4, average 0.64


def test_values_exactly_on_the_thresholds_are_accepted():
    assert accepted(vosk_result(0.4, 1.0, 0.7, 0.7)) == PHRASE      # lowest 0.4, average 0.7


@pytest.mark.parametrize("result", ['{"text": ""}', '{"result": [], "text": ""}'])
def test_silence_gives_nothing(result):
    assert accepted(result) is None


def test_rejection_is_logged_with_the_confidences(caplog):
    caplog.set_level("INFO")
    accepted(vosk_result(1.0, 1.0, 0.3, 1.0))
    assert "lowest 0.30" in caplog.text


def test_missing_model_fails_at_start(tmp_path):
    with pytest.raises(FileNotFoundError, match="VOSK_MODEL_PATH"):
        VoskMicrophone(str(tmp_path / "no-model-here"))
