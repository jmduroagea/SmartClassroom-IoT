"""Unit tests of the DS18B20 adapter (room/adapters/ds18b20.py). Temporary
folders play the role of /sys/bus/w1/devices, so no Pi is needed."""

import pytest

from room.adapters.ds18b20 import DS18B20Sensor
from room.core.ports import SensorError

GOOD = (
    "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n"
    "72 01 4b 46 7f ff 0e 10 57 t=23125\n"
)
SERIAL = "28-0316a2794bff"


@pytest.fixture
def sensor(tmp_path):
    return DS18B20Sensor(pattern=str(tmp_path / "28-*" / "w1_slave"))


def plug_in(tmp_path, content=GOOD):
    """Create the folder and the w1_slave file the 1-Wire driver would create."""
    folder = tmp_path / SERIAL
    folder.mkdir()
    (folder / "w1_slave").write_text(content)


def test_reads_the_temperature(tmp_path, sensor):
    plug_in(tmp_path)
    assert sensor.read() == 23.125


def test_no_sensor_raises_sensor_error(sensor):
    with pytest.raises(SensorError, match="no DS18B20"):
        sensor.read()


def test_sensor_plugged_in_later_is_found_without_restarting(tmp_path, sensor):
    with pytest.raises(SensorError):
        sensor.read()
    plug_in(tmp_path)
    assert sensor.read() == 23.125


def test_file_that_cannot_be_read_raises_sensor_error(tmp_path, sensor):
    (tmp_path / SERIAL / "w1_slave").mkdir(parents=True)  # a folder where the file should be
    with pytest.raises(SensorError, match="could not read"):
        sensor.read()


def test_garbage_in_the_file_raises_sensor_error(tmp_path, sensor):
    folder = tmp_path / SERIAL
    folder.mkdir()
    (folder / "w1_slave").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SensorError, match="could not read"):
        sensor.read()


def test_reading_that_cannot_be_trusted_is_rejected(tmp_path, sensor):
    plug_in(tmp_path, GOOD.replace("YES", "NO"))
    with pytest.raises(SensorError, match="CRC"):
        sensor.read()
