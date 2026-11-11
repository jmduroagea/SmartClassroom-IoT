"""Unit tests of the RFID frame parsing and the serial card reader (door/adapters/rfid.py)."""

import pytest

from door.adapters.rfid import FRAME_BODY, SerialCardReader, parse_frame

CARD = "0F00A1B2C3"
CHECKSUM = "DF"  # 0x0F ^ 0x00 ^ 0xA1 ^ 0xB2 ^ 0xC3


def body(card=CARD, checksum=CHECKSUM, end=b"\x03"):
    """What the reader sends after the start byte 0x02."""
    return (card + checksum).encode("ascii") + end


def test_a_valid_frame_gives_the_card_id():
    assert parse_frame(body()) == CARD


def test_lower_case_hex_is_accepted_and_given_in_upper_case():
    assert parse_frame(body(card=CARD.lower(), checksum=CHECKSUM.lower())) == CARD


@pytest.mark.parametrize(
    "frame",
    [
        body(checksum="00"),                 # wrong checksum
        body(end=b"\x00"),                   # no end byte
        body()[:-2],                         # cut
        body() + b"\x03",                    # too long
        body(card="0F00A1B2CZ"),             # not hex
        "0F00A1B2C3DÉ".encode("utf-8")[:12] + b"\x03",  # not ASCII
        b"",
    ],
)
def test_an_invalid_frame_gives_none(frame):
    assert parse_frame(frame) is None


class FakeSerial:
    """Gives the bytes of `data` as a serial port would, then b"" (a timeout)."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self, size=1):
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk


def test_the_reader_reads_one_card():
    reader = SerialCardReader("unused", serial_port=FakeSerial(b"\x02" + body()))
    assert reader.read_card() == CARD


def test_the_reader_skips_noise_before_the_start_byte():
    reader = SerialCardReader("unused", serial_port=FakeSerial(b"\xff" + b"\x02" + body()))
    assert reader.read_card() is None   # the noise byte
    assert reader.read_card() == CARD


def test_the_reader_discards_a_bad_frame_and_logs_it(caplog):
    reader = SerialCardReader("unused", serial_port=FakeSerial(b"\x02" + body(checksum="00")))
    assert reader.read_card() is None
    assert "discarded" in caplog.text


def test_a_timeout_gives_none():
    reader = SerialCardReader("unused", serial_port=FakeSerial(b""))
    assert reader.read_card() is None


def test_read_cards_calls_back_for_every_valid_card():
    data = b"\x02" + body() + b"\x02" + body(checksum="00") + b"\x02" + body()
    reader = SerialCardReader("unused", serial_port=FakeSerial(data))
    cards = []

    class Done(Exception):
        pass

    def on_card(card_id):
        cards.append(card_id)
        if len(cards) == 2:
            raise Done

    with pytest.raises(Done):
        reader.read_cards(on_card)
    assert cards == [CARD, CARD]


def test_the_frame_body_is_14_bytes_minus_the_start_byte():
    assert FRAME_BODY == 13
