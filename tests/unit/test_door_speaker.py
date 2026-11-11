"""Unit tests of the espeak-ng speaker (door/adapters/speaker.py), with a fake
subprocess.run, so no sound and no espeak-ng are needed."""

import subprocess

from door.adapters.speaker import COMMAND, EspeakSpeaker


def at_once(work):
    """Runs the background work straight away, so the test can check the result."""
    work()


class FakeRun:
    """Records each call to subprocess.run; it can fail like a missing or broken espeak-ng."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, command, **options):
        self.calls.append((command, options))
        if self.error:
            raise self.error


def test_the_text_is_said_with_espeak_ng_in_american_english_at_150_words_per_minute():
    run = FakeRun()
    done = []
    EspeakSpeaker(run=run, background=at_once).play("Welcome, Gloria.", lambda: done.append(True))
    [(command, options)] = run.calls
    assert command == ["espeak-ng", "-v", "en-us", "-s", "150"] == COMMAND
    assert options["input"] == "Welcome, Gloria."
    assert done == [True]


def test_a_text_starting_with_a_dash_is_not_taken_as_an_option():
    run = FakeRun()
    EspeakSpeaker(run=run, background=at_once).play("-5 degrees", lambda: None)
    [(command, options)] = run.calls
    assert "-5 degrees" not in command
    assert options["input"] == "-5 degrees"


def test_play_returns_before_the_speech_ends():
    run = FakeRun()
    waiting = []
    speaker = EspeakSpeaker(run=run, background=waiting.append)
    done = []
    speaker.play("Room occupied.", lambda: done.append(True))
    assert run.calls == [] and done == []   # still in the background
    waiting[0]()
    assert done == [True]


def test_without_espeak_ng_the_error_is_logged_and_on_done_still_called(caplog):
    done = []
    speaker = EspeakSpeaker(run=FakeRun(error=FileNotFoundError("espeak-ng")), background=at_once)
    speaker.play("Card not recognized.", lambda: done.append(True))
    assert "not installed" in caplog.text
    assert done == [True]


def test_when_espeak_ng_fails_the_error_is_logged_and_on_done_still_called(caplog):
    done = []
    error = subprocess.CalledProcessError(1, COMMAND, stderr="no audio device")
    EspeakSpeaker(run=FakeRun(error=error), background=at_once).play("Goodbye.", lambda: done.append(True))
    assert "no audio device" in caplog.text
    assert done == [True]


def test_the_real_default_runs_in_another_thread():
    import threading

    finished = threading.Event()
    EspeakSpeaker(run=FakeRun()).play("Hello.", finished.set)
    assert finished.wait(timeout=2)
