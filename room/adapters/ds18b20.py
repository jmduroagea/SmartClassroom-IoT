"""The real temperature sensor: a DS18B20 on the 1-Wire bus (GPIO4).

Linux shows each DS18B20 as a folder named 28-<serial number> with a file
w1_slave holding its last reading. This adapter only finds and reads that file;
deciding whether the reading can be trusted is parse_reading()'s job.
"""

from __future__ import annotations

import glob

from room.core.ports import SensorError
from room.core.reading import parse_reading

# 28 is the family code of every DS18B20 (1-Wire must be enabled on the Pi)
W1_SLAVE_PATTERN = "/sys/bus/w1/devices/28-*/w1_slave"


class DS18B20Sensor:
    def __init__(self, pattern: str = W1_SLAVE_PATTERN) -> None:
        """`pattern` lets the tests point the sensor at temporary files."""
        self._pattern = pattern

    def read(self) -> float:
        # Looked for on every reading, so a sensor plugged back in works again
        # without restarting the program (test T6). With several, the first wins.
        paths = sorted(glob.glob(self._pattern))
        if not paths:
            raise SensorError("no DS18B20 found: is it wired and is 1-Wire enabled?")
        try:
            with open(paths[0], encoding="ascii") as file:
                text = file.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise SensorError(f"could not read {paths[0]}: {exc}") from exc
        return parse_reading(text)
