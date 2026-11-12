"""Simulated hardware, so the Door Pi runs without a Raspberry Pi.

`python -m door.main --simulate` (a person at the keyboard):
- KeyboardInput: every line typed is a card scanned, except "m", which is a
  movement in front of the PIR.
- PrintLight: prints the LED changes instead of lighting LEDs.
- PrintSpeaker: prints the text instead of saying it, and finishes at once.

`python -m door.main --sim-topics` (the Docker simulation, driven by the
scenario tests over MQTT):
- TopicInputs: a card published on sim/door/card, or a movement on
  sim/door/motion, goes into the door code as if it came from the hardware.
- TopicLight and TopicSpeaker report what they did on sim/door/led and
  sim/door/speaker/said.

The sim/ topics exist only in the simulation. They are not part of the contract
(common/messages.py): common/sim_link.py is a separate MQTT connection that
carries only them.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Callable, Iterable, Optional

from common.sim_link import SimLink

MOTION_KEY = "m"

SIM_CARD = "sim/door/card"            # {"card_id": "0F00A1B2C3"}
SIM_MOTION = "sim/door/motion"        # {}
SIM_LED = "sim/door/led"              # {"color": "green", "on": true}
SIM_SAID = "sim/door/speaker/said"    # {"text": "Welcome, Gloria."}
SIM_CLIENT_ID = "door-pi-sim"

logger = logging.getLogger(__name__)


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


# --- Driven by sim/ topics ------------------------------------------------------------

class TopicInputs:
    """Cards and movements from sim/ topics instead of the RDM6300 and the PIR."""

    def __init__(self, link: SimLink) -> None:
        self._link = link
        self._stopped = threading.Event()

    def run(self, on_card: Callable[[str], None], on_motion: Callable[[], None]) -> None:
        """Listen until stop(). The messages arrive on the link's own thread."""

        def card(data: dict) -> None:
            card_id = data.get("card_id")
            if isinstance(card_id, str) and card_id.strip():
                on_card(card_id.strip())
            else:
                logger.warning("ignored %s without a card_id: %r", SIM_CARD, data)

        self._link.subscribe(SIM_CARD, card)
        self._link.subscribe(SIM_MOTION, lambda _data: on_motion())
        self._link.start()
        self._stopped.wait()

    def stop(self) -> None:
        self._stopped.set()
        self._link.stop()


class TopicLight:
    def __init__(self, link: SimLink) -> None:
        self._link = link

    def on(self, color: str) -> None:
        self._link.publish(SIM_LED, color=color, on=True)

    def off(self, color: str) -> None:
        self._link.publish(SIM_LED, color=color, on=False)

    def stop(self) -> None:
        pass


class TopicSpeaker:
    """Reports the text instead of saying it, and finishes at once."""

    def __init__(self, link: SimLink) -> None:
        self._link = link

    def play(self, text: str, on_done: Callable[[], None]) -> None:
        self._link.publish(SIM_SAID, text=text)
        on_done()
