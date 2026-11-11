"""Turning the content of the DS18B20's w1_slave file into a temperature.

The Linux 1-Wire driver writes two lines, for example:

    72 01 4b 46 7f ff 0e 10 57 : crc=57 YES
    72 01 4b 46 7f ff 0e 10 57 t=23125

The first line ends in YES when the CRC check passed. The second gives the
temperature in thousandths of a degree (23125 = 23.125 °C).

This is pure logic, with no file access, so it is tested with recorded text
(test T23). The adapter only reads the file and calls parse_reading().
"""

from __future__ import annotations

from room.core.ports import SensorError

CRC_OK = "YES"
TEMPERATURE_MARK = "t="
MILLIDEGREES_PER_DEGREE = 1000
# The DS18B20 answers exactly 85.000 °C after a power-on reset, before its first
# real measurement. Compared as an integer, so no float rounding is involved.
POWER_ON_RESET_MILLIDEGREES = 85000


def parse_reading(text: str) -> float:
    """Return the temperature in °C, or raise SensorError if it cannot be trusted."""
    lines = text.strip().splitlines()
    if len(lines) != 2:
        raise SensorError(f"expected 2 lines from the sensor, got {len(lines)}")
    crc_line, data_line = lines
    if not crc_line.endswith(CRC_OK):
        raise SensorError("CRC check failed")
    _, mark, value = data_line.partition(TEMPERATURE_MARK)
    if not mark:
        raise SensorError("no temperature in the sensor data")
    try:
        millidegrees = int(value)
    except ValueError:
        raise SensorError(f"temperature {value!r} is not a number") from None
    if millidegrees == POWER_ON_RESET_MILLIDEGREES:
        raise SensorError("85.0 °C is the power-on value, not a measurement")
    return millidegrees / MILLIDEGREES_PER_DEGREE
