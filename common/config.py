"""Settings that change between machines: laptop, simulation and Raspberry Pis.

They come from environment variables, never from the code. Each one has a named
default for development on a laptop. On the Pis, systemd loads them from a .env
file, which git ignores. .env.example lists and explains every variable.

Usage:
    from common.config import load_config

    config = load_config()
    client.connect(config.mqtt_host, config.mqtt_port)

A wrong value (for example MQTT_PORT=abc) raises ConfigError when the program
starts, so the problem is seen at once instead of failing later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

# Names of the environment variables
MQTT_HOST = "MQTT_HOST"
MQTT_PORT = "MQTT_PORT"
MONGO_URI = "MONGO_URI"
MONGO_DB = "MONGO_DB"
RFID_SERIAL_PORT = "RFID_SERIAL_PORT"
VOSK_MODEL_PATH = "VOSK_MODEL_PATH"

# Defaults for development on a laptop (the Pis set their own values in .env)
DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MONGO_URI = "mongodb://localhost:27017"
DEFAULT_MONGO_DB = "smartroom"
DEFAULT_RFID_SERIAL_PORT = "/dev/serial0"
DEFAULT_VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"

# Valid TCP ports
MIN_PORT = 1
MAX_PORT = 65535


class ConfigError(ValueError):
    """A setting with a wrong value. The text says which one and why."""


@dataclass(frozen=True)
class Config:
    mqtt_host: str
    mqtt_port: int
    mongo_uri: str
    mongo_db: str
    rfid_serial_port: str
    vosk_model_path: str


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    """Read every setting. Tests pass their own dict instead of os.environ."""
    if env is None:
        env = os.environ
    return Config(
        mqtt_host=_text(env, MQTT_HOST, DEFAULT_MQTT_HOST),
        mqtt_port=_port(env, MQTT_PORT, DEFAULT_MQTT_PORT),
        mongo_uri=_text(env, MONGO_URI, DEFAULT_MONGO_URI),
        mongo_db=_text(env, MONGO_DB, DEFAULT_MONGO_DB),
        rfid_serial_port=_text(env, RFID_SERIAL_PORT, DEFAULT_RFID_SERIAL_PORT),
        vosk_model_path=_text(env, VOSK_MODEL_PATH, DEFAULT_VOSK_MODEL_PATH),
    )


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, default).strip()
    if not value:
        raise ConfigError(f"{name} must not be empty")
    return value


def _port(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        port = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a number") from None
    if not MIN_PORT <= port <= MAX_PORT:
        raise ConfigError(f"{name}={port} must be between {MIN_PORT} and {MAX_PORT}")
    return port
