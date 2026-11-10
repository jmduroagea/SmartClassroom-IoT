"""The real message bus, on top of paho-mqtt. Used on the Raspberry Pis.

What it adds to the MessageBus port:
- Last will: if the program dies, the broker publishes "offline" on its status
  topic (retained), so the web app knows. On every connection it publishes "online".
- Automatic reconnection, with a growing delay, and it subscribes again.
- QoS from the contract (common.messages.qos), never written by hand.

Only main.py files import this module: cores use common.bus.MessageBus.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

import paho.mqtt.client as mqtt

from common import messages
from common.bus import Handler, deliver
from common.config import Config

KEEPALIVE_SECONDS = 30
RECONNECT_MIN_DELAY_SECONDS = 1
RECONNECT_MAX_DELAY_SECONDS = 30
STATUS_QOS = 1

logger = logging.getLogger(__name__)


def _default_client_factory(client_id: str) -> mqtt.Client:
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


class PahoBus:
    def __init__(
        self,
        config: Config,
        client_id: str,
        status_topic: Optional[str] = None,
        client_factory: Callable[[str], mqtt.Client] = _default_client_factory,
    ) -> None:
        """client_factory lets tests replace the paho client with a mock."""
        self._config = config
        self._status_topic = status_topic
        self._subscriptions: List[Tuple[str, Handler]] = []
        self._client = client_factory(client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(
            min_delay=RECONNECT_MIN_DELAY_SECONDS, max_delay=RECONNECT_MAX_DELAY_SECONDS
        )
        if status_topic:
            # Must be set before connecting: the broker keeps it for us.
            self._client.will_set(
                status_topic, messages.STATUS_OFFLINE, qos=STATUS_QOS, retain=True
            )

    def start(self) -> None:
        # connect_async + loop_start: does not block, and keeps retrying if the
        # broker is not there yet.
        self._client.connect_async(
            self._config.mqtt_host, self._config.mqtt_port, keepalive=KEEPALIVE_SECONDS
        )
        self._client.loop_start()

    def stop(self) -> None:
        if self._status_topic:
            self._client.publish(
                self._status_topic, messages.STATUS_OFFLINE, qos=STATUS_QOS, retain=True
            )
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, topic: str, **fields) -> None:
        payload = messages.build(topic, **fields)  # raises InvalidMessage if wrong
        info = self._client.publish(topic, payload, qos=messages.qos(topic))
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("could not publish on %s (rc=%s)", topic, info.rc)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subscriptions.append((pattern, handler))
        # If already connected, subscribe now; otherwise _on_connect will do it.
        if self._client.is_connected():
            self._client.subscribe(pattern, qos=messages.qos(pattern))

    # --- paho callbacks (they run in paho's network thread) ---------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            logger.warning("connection refused by the broker: %s", reason_code)
            return
        logger.info("connected to %s:%s", self._config.mqtt_host, self._config.mqtt_port)
        # After a reconnection the broker has forgotten us: subscribe again.
        for pattern, _handler in self._subscriptions:
            client.subscribe(pattern, qos=messages.qos(pattern))
        if self._status_topic:
            client.publish(self._status_topic, messages.STATUS_ONLINE, qos=STATUS_QOS, retain=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        logger.warning("disconnected (%s), paho will reconnect", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        deliver(self._subscriptions, message.topic, message.payload)
