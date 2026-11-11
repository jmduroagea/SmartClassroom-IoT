"""The real speaker: espeak-ng says the text on the default sound card (the USB speaker).

espeak-ng runs in the background, so the core is never blocked while it talks,
and on_done is called when it has finished. If espeak-ng is missing or fails, the
error is logged and on_done is still called: the door keeps working without voice.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable, List

VOICE = "en-us"
WORDS_PER_MINUTE = 150   # a little slower than espeak-ng's 175, clearer at the door
COMMAND: List[str] = ["espeak-ng", "-v", VOICE, "-s", str(WORDS_PER_MINUTE)]

logger = logging.getLogger(__name__)


def _in_background(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class EspeakSpeaker:
    def __init__(self, run=subprocess.run, background=_in_background) -> None:
        """`run` and `background` are subprocess.run and a new thread; the tests pass fakes."""
        self._run = run
        self._background = background

    def play(self, text: str, on_done: Callable[[], None]) -> None:
        """Start saying text and return at once. on_done() is called when it ends."""

        def speak() -> None:
            try:
                # The text goes through stdin, so a text starting with "-" is not read as an option.
                self._run(COMMAND, input=text, text=True, check=True, capture_output=True)
            except FileNotFoundError:
                logger.error("espeak-ng is not installed: %r not said", text)
            except subprocess.CalledProcessError as exc:
                logger.error("espeak-ng failed (%s): %r not said", exc.stderr or exc.returncode, text)
            finally:
                on_done()

        self._background(speak)
