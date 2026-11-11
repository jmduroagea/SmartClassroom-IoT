"""The Door Pi program. It wires the core to the real or the simulated hardware.

    python -m door.main              # on the Door Pi
    python -m door.main --simulate   # on a laptop: keyboard for cards and motion

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
from door.adapters.simulated import KeyboardInput, PrintLight, PrintSpeaker
from door.core.door_core import DoorCore

CLIENT_ID = "door-pi"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger(__name__)


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
    # The espeak-ng speaker is issue #10; until then the texts are only printed.
    logger.warning("no real speaker yet (#10): texts are printed")
    return inputs, GpioDoorLight(), PrintSpeaker()


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="SmartClassroom Door Pi")
    parser.add_argument("--simulate", action="store_true", help="keyboard for cards and motion, no GPIO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    config = load_config()
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
