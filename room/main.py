"""The Room Pi program. It wires the core to the real or the simulated hardware.

    python -m room.main              # on the Room Pi
    python -m room.main --simulate   # on a laptop: fake sensor, keyboard as microphone

Settings (broker address, Vosk model) come from the environment: see .env.example.
"""

from __future__ import annotations

import argparse
import logging
from typing import Optional, Sequence

from common import topics
from common.clock import SystemClock
from common.config import Config, load_config
from common.paho_bus import PahoBus
from room.adapters.ds18b20 import DS18B20Sensor
from room.adapters.servo_fan import ServoFan
from room.adapters.simulated import KeyboardMicrophone, PrintFan, SimulatedSensor
from room.adapters.vosk_mic import VoskMicrophone
from room.core.room_core import RoomCore

CLIENT_ID = "room-pi"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def build_hardware(simulate: bool, config: Config):
    """Sensor, fan and microphone: the real ones, or the simulated ones."""
    if simulate:
        sensor = SimulatedSensor()
        return sensor, PrintFan(), KeyboardMicrophone(sensor)
    return DS18B20Sensor(), ServoFan(), VoskMicrophone(config.vosk_model_path)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="SmartClassroom Room Pi")
    parser.add_argument("--simulate", action="store_true", help="fake sensor, keyboard as microphone")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    config = load_config()
    sensor, fan, microphone = build_hardware(args.simulate, config)
    bus = PahoBus(config, CLIENT_ID, status_topic=topics.ROOM_STATUS)
    core = RoomCore(bus, SystemClock(), sensor, fan)
    core.start()
    bus.start()
    try:
        microphone.listen(core.on_phrase)  # blocks until Ctrl+C (or end of input)
    except KeyboardInterrupt:
        pass
    finally:
        bus.stop()   # publishes "offline" before leaving
        fan.stop()


if __name__ == "__main__":
    main()
