"""The Door Pi program. It wires the core to the real or the simulated hardware.

    python -m door.main              # on the Door Pi
    python -m door.main --simulate   # on a laptop: keyboard for cards and motion
    python -m door.main --sim-topics # in the Docker simulation: cards and motion from sim/ topics

Settings (broker address, RFID serial port) come from the environment: see .env.example.
"""

from __future__ import annotations

import argparse
import logging
from typing import Callable, Optional, Sequence

from common import topics
from common.clock import SystemClock
from common.config import Config, load_config
from common.paho_bus import PahoBus
from door.adapters.leds import GpioDoorLight
from door.adapters.pir import GpioMotionSensor
from door.adapters.rfid import SerialCardReader
from door.adapters.simulated import (
    KeyboardInput,
    PrintLight,
    PrintSpeaker,
    SimLink,
    TopicInputs,
    TopicLight,
    TopicSpeaker,
)
from door.adapters.speaker import EspeakSpeaker
from door.core.door_core import DoorCore

CLIENT_ID = "door-pi"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

class RealInputs:
    """The PIR and the card reader together, so main.py runs both the same way."""

    def __init__(self, motion: GpioMotionSensor, reader: SerialCardReader) -> None:
        self._motion = motion
        self._reader = reader

    def run(self, on_card: Callable[[str], None], on_motion: Callable[[], None]) -> None:
        self._motion.watch(on_motion)
        self._reader.read_cards(on_card)  # blocks forever

    def stop(self) -> None:
        self._motion.stop()


def build_hardware(simulate: bool, config: Config):
    """Inputs (cards and motion), LEDs and speaker: the real ones, or the simulated ones."""
    if simulate:
        return KeyboardInput(), PrintLight(), PrintSpeaker()
    inputs = RealInputs(GpioMotionSensor(), SerialCardReader(config.rfid_serial_port))
    return inputs, GpioDoorLight(), EspeakSpeaker()


def build_sim_topics_hardware(config: Config):
    """Fakes driven by the scenario tests: they share one connection for the sim/ topics."""
    link = SimLink(config.mqtt_host, config.mqtt_port)
    return TopicInputs(link), TopicLight(link), TopicSpeaker(link)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="SmartClassroom Door Pi")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="keyboard for cards and motion, no GPIO")
    mode.add_argument("--sim-topics", action="store_true", help="cards and motion from sim/ topics (Docker simulation)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    config = load_config()
    if args.sim_topics:
        inputs, light, speaker = build_sim_topics_hardware(config)
    else:
        inputs, light, speaker = build_hardware(args.simulate, config)
    bus = PahoBus(config, CLIENT_ID, status_topic=topics.DOOR_STATUS)
    core = DoorCore(bus, SystemClock(), light, speaker)
    core.start()
    bus.start()
    try:
        inputs.run(core.on_card, core.on_motion)  # blocks until Ctrl+C (or end of input)
    except KeyboardInterrupt:
        pass
    finally:
        bus.stop()   # publishes "offline" before leaving
        light.stop()
        inputs.stop()


if __name__ == "__main__":
    main()
