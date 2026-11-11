"""Unit tests of the DS18B20 reading parser (room/core/reading.py), test T23."""

import pytest

from room.core.ports import SensorError
from room.core.reading import parse_reading

# Content of w1_slave, in the format the 1-Wire driver writes.
# Replace them with real captures from the Room Pi on Thursday.
GOOD = (
    "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n"
    "72 01 4b 46 7f ff 0e 10 57 t=23125\n"
)
CRC_FAILED = (
    "72 01 4b 46 7f ff 0e 10 57 : crc=a3 NO\n"
    "72 01 4b 46 7f ff 0e 10 57 t=23125\n"
)
POWER_ON_RESET = (
    "50 05 4b 46 7f ff 0c 10 1c : crc=1c YES\n"
    "50 05 4b 46 7f ff 0c 10 1c t=85000\n"
)
BELOW_ZERO = (
    "5e ff 4b 46 7f ff 02 10 7b : crc=7b YES\n"
    "5e ff 4b 46 7f ff 02 10 7b t=-10125\n"
)


def test_good_reading_gives_degrees():
    assert parse_reading(GOOD) == 23.125


def test_temperature_below_zero():
    assert parse_reading(BELOW_ZERO) == -10.125


def test_failed_crc_is_rejected():
    with pytest.raises(SensorError, match="CRC"):
        parse_reading(CRC_FAILED)


def test_power_on_value_is_rejected():
    with pytest.raises(SensorError, match="85"):
        parse_reading(POWER_ON_RESET)


def test_just_above_85_is_a_real_reading():
    assert parse_reading(POWER_ON_RESET.replace("t=85000", "t=85062")) == pytest.approx(85.062)


@pytest.mark.parametrize(
    "text",
    [
        "",                                       # empty file
        "only one line YES",                      # cut short
        GOOD.replace("t=23125", "t=abc"),         # not a number
        GOOD.replace("t=", "x="),                 # no temperature mark
    ],
)
def test_broken_content_is_rejected(text):
    with pytest.raises(SensorError):
        parse_reading(text)
