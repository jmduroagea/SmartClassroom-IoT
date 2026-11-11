"""Simulated hardware for `python -m door.main --simulate`, so the Door Pi runs
on any laptop:

- KeyboardInput: every line typed is a card scanned, except "m", which is a
  movement in front of the PIR.
- PrintLight: prints the LED changes instead of lighting LEDs.
- PrintSpeaker: prints the text instead of saying it, and finishes at once.
"""

from __future__ import annotations

import sys
from typing import Callable, Iterable, Optional

MOTION_KEY = "m"


class KeyboardInput:
    def __init__(self, lines: Optional[Iterable[str]] = None) -> None:
        """`lines` is the keyboard (stdin); tests pass a list instead."""
        self._lines = lines

    def run(self, on_card: Callable[[str], None], on_motion: Callable[[], None]) -> None:
        """Read lines until the end of the input."""
        print(f"Type a card id + Enter to scan a card, '{MOTION_KEY}' + Enter for motion.")
        for raw in self._lines if self._lines is not None else sys.stdin:
            line = raw.strip()
            if not line:
                continue
            if line.lower() == MOTION_KEY:
                on_motion()
            else:
                on_card(line)

    def stop(self) -> None:
        pass


class PrintLight:
    def on(self, color: str) -> None:
        print(f"[led] {color} on")

    def off(self, color: str) -> None:
        print(f"[led] {color} off")

    def stop(self) -> None:
        print("[led] all off")


class PrintSpeaker:
    def play(self, text: str, on_done: Callable[[], None]) -> None:
        print(f"[speaker] {text}")
        on_done()
