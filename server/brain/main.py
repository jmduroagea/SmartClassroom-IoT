"""The brain program, on the Server Pi. It only wires the parts together.

    python -m server.brain.main

Settings (broker, MongoDB) come from the environment: see .env.example.
"""

from __future__ import annotations

import logging
import threading

from common.clock import SystemClock
from common.config import load_config
from common.paho_bus import PahoBus
from server.brain.adapters.mongo_repository import MongoRepository
from server.brain.service import Brain

CLIENT_ID = "brain"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    config = load_config()
    bus = PahoBus(config, CLIENT_ID)
    brain = Brain(bus, SystemClock(), MongoRepository(config))
    brain.start()
    bus.start()
    try:
        threading.Event().wait()  # MQTT and the timers run in their own threads
    except KeyboardInterrupt:
        pass
    finally:
        bus.stop()


if __name__ == "__main__":
    main()
