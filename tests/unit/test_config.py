"""Unit tests of the configuration (common/config.py)."""

from pathlib import Path

import pytest

from common import config
from common.config import ConfigError, load_config

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_defaults_when_nothing_is_set():
    settings = load_config({})
    assert settings.mqtt_host == config.DEFAULT_MQTT_HOST
    assert settings.mqtt_port == config.DEFAULT_MQTT_PORT
    assert settings.mongo_uri == config.DEFAULT_MONGO_URI
    assert settings.mongo_db == config.DEFAULT_MONGO_DB


def test_values_come_from_the_environment():
    settings = load_config(
        {"MQTT_HOST": "10.12.220.20", "MQTT_PORT": "1884", "MONGO_DB": "test_db"}
    )
    assert settings.mqtt_host == "10.12.220.20"
    assert settings.mqtt_port == 1884
    assert settings.mongo_db == "test_db"


def test_spaces_around_values_are_ignored():
    settings = load_config({"MQTT_HOST": "  broker  ", "MQTT_PORT": " 1883 "})
    assert settings.mqtt_host == "broker"
    assert settings.mqtt_port == 1883


def test_port_that_is_not_a_number_stops_the_program():
    with pytest.raises(ConfigError, match="MQTT_PORT"):
        load_config({"MQTT_PORT": "abc"})


@pytest.mark.parametrize("port", ["0", "70000", "-1"])
def test_port_out_of_range_stops_the_program(port):
    with pytest.raises(ConfigError, match="between"):
        load_config({"MQTT_PORT": port})


def test_empty_value_stops_the_program():
    with pytest.raises(ConfigError, match="MQTT_HOST"):
        load_config({"MQTT_HOST": "   "})


def test_reads_the_real_environment_by_default(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "from-the-environment")
    assert load_config().mqtt_host == "from-the-environment"


def test_env_example_documents_every_python_setting():
    documented = {
        line.split("=", 1)[0]
        for line in ENV_EXAMPLE.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    }
    python_settings = {
        config.MQTT_HOST,
        config.MQTT_PORT,
        config.MONGO_URI,
        config.MONGO_DB,
        config.RFID_SERIAL_PORT,
        config.VOSK_MODEL_PATH,
    }
    assert python_settings <= documented
