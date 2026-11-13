"""The real card reader: an RDM6300-style 125 kHz reader on the UART.

Each card read arrives as a frame of 14 bytes (the same protocol as Tutorial 2):

    0x02 | 10 ASCII hex characters (the card id) | 2 ASCII hex characters (checksum) | 0x03

The checksum is the XOR of the five bytes written by the 10 id characters.
A frame that is cut, has other characters or a wrong checksum is discarded.
"""

from __future__ import annotations

import logging
import string
from typing import Callable, Optional

START = b"\x02"
END = b"\x03"
ID_CHARS = 10
CHECKSUM_CHARS = 2
FRAME_BODY = ID_CHARS + CHECKSUM_CHARS + len(END)  # what follows the start byte
# All zeros passes the checksum (the XOR of zeros is zero), but it is not a card:
# the reader sent it with no card near it on the real Door Pi.
NO_CARD = "0" * ID_CHARS
BAUD_RATE = 9600
READ_TIMEOUT_SECONDS = 1

logger = logging.getLogger(__name__)


def parse_frame(body: bytes) -> Optional[str]:
    """The card id in the bytes that follow 0x02, or None if they are not a valid frame."""
    if len(body) != FRAME_BODY or not body.endswith(END):
        return None
    try:
        text = body[:-1].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not all(char in string.hexdigits for char in text):
        return None
    card_id, checksum = text[:ID_CHARS], text[ID_CHARS:]
    expected = 0
    for i in range(0, ID_CHARS, 2):
        expected ^= int(card_id[i:i + 2], 16)
    if expected != int(checksum, 16) or card_id == NO_CARD:
        return None
    return card_id.upper()


def _open_serial(port: str):
    import serial  # pyserial, installed on the Door Pi (requirements-door.txt)

    return serial.Serial(port, BAUD_RATE, timeout=READ_TIMEOUT_SECONDS)


class SerialCardReader:
    def __init__(self, port: str, serial_port=None) -> None:
        """`serial_port` is an open pyserial port; the tests pass a fake one."""
        self._serial = serial_port if serial_port is not None else _open_serial(port)

    def read_card(self) -> Optional[str]:
        """Wait for one frame. The card id, or None (timeout or a bad frame)."""
        if self._serial.read(1) != START:
            return None
        body = self._serial.read(FRAME_BODY)
        card_id = parse_frame(body)
        if card_id is None:
            logger.warning("RFID frame discarded: %r", body)
        return card_id

    def read_cards(self, on_card: Callable[[str], None]) -> None:
        """Call on_card(card_id) for every valid card read. Blocks forever."""
        while True:
            card_id = self.read_card()
            if card_id is not None:
                on_card(card_id)
