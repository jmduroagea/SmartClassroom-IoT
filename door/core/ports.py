"""The Door Pi's ports: what the core needs from the hardware.

The real devices (RFID reader on the UART, PIR, the two LEDs, the USB speaker)
and their fakes are adapters, in door/adapters/ (issue #9).
"""

from __future__ import annotations

from typing import Callable, Protocol


class CardReader(Protocol):
    def read_cards(self, on_card: Callable[[str], None]) -> None:
        """Call on_card(card_id) for every card read. Blocks forever."""
        ...


class MotionSensor(Protocol):
    def watch(self, on_motion: Callable[[], None]) -> None:
        """Call on_motion() every time the PIR detects movement. Returns at once."""
        ...


class DoorLight(Protocol):
    def on(self, color: str) -> None:
        """Switch on the LED of that colour (one of messages.LED_COLORS)."""
        ...

    def off(self, color: str) -> None:
        """Switch off the LED of that colour."""
        ...


class Speaker(Protocol):
    def play(self, text: str, on_done: Callable[[], None]) -> None:
        """Start saying text and return at once. Call on_done() when it has finished."""
        ...
