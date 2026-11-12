"""The MQTT connection of the fake hardware in the Docker simulation.

The simulated Pis (door/adapters/simulated.py, room/adapters/simulated.py) are
driven by the scenario tests on sim/ topics, and report there what they did.
Those topics exist only in the simulation and are not part of the contract
(common/messages.py), so they travel on this separate connection, as plain JSON.
The real Pis never open it.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Dict

SIM_QOS = 1

logger = logging.getLogger(__name__)

SimHandler = Callable[[dict], None]


class SimLink:
    """The MQTT connection of the fakes. It only publishes and listens on sim/ topics,
    with plain JSON, so nothing here goes through the contract of the real system."""

    def __init__(self, host: str, port: int, client_id: str, client=None) -> None:
        """`client` is a paho client; the tests pass a fake one."""
        if client is None:
            import paho.mqtt.client as mqtt

            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._host, self._port = host, port
        self._client = client
        self._handlers: Dict[str, SimHandler] = {}
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self) -> None:
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def subscribe(self, topic: str, handler: SimHandler) -> None:
        """Call handler(data) for every message on the topic. Call it before start()."""
        self._handlers[topic] = handler

    def publish(self, topic: str, **fields) -> None:
        self._client.publish(topic, json.dumps(fields), qos=SIM_QOS)

    def _on_connect(self, client, _userdata, _flags, _reason_code, _properties=None) -> None:
        # Also after a reconnection: the broker forgets the subscriptions.
        for topic in self._handlers:
            client.subscribe(topic, qos=SIM_QOS)

    def _on_message(self, _client, _userdata, message) -> None:
        handler = self._handlers.get(message.topic)
        if handler is None:
            return
        try:
            data = json.loads(message.payload)
        except ValueError:
            logger.warning("ignored %s: not JSON", message.topic)
            return
        if not isinstance(data, dict):
            logger.warning("ignored %s: not a JSON object", message.topic)
            return
        handler(data)
