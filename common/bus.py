"""The message bus port: how every program sends and receives MQTT messages.

Programs never talk to paho directly. They use a MessageBus:

    bus.subscribe(topics.DOOR_RFID, on_card)        # on_card(topic, data)
    bus.publish(topics.DOOR_SPEAKER_SAY, text="Welcome, Gloria.")

- publish() builds and checks the message with common.messages, so a wrong
  message can never be sent, and takes the QoS from the contract.
- Handlers receive messages already checked: a dict for JSON messages, or the
  text "online"/"offline" for status topics. Invalid messages never reach them.

This file has no paho import, so cores and tests can use it anywhere.
The real bus is common/paho_bus.py. FakeBus (below) is the bus for tests.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Protocol, Tuple, Union

from common import messages, topics

# A message as handlers receive it: a dict, or "online"/"offline" for status topics
Payload = Union[dict, str]
Handler = Callable[[str, Payload], None]

# Status topics carry plain text, not JSON (see common/messages.py)
STATUS_TOPICS = (topics.DOOR_STATUS, topics.ROOM_STATUS)

logger = logging.getLogger(__name__)


class MessageBus(Protocol):
    """The port: what any message bus must offer."""

    def start(self) -> None:
        """Connect to the broker (the real bus) and start delivering messages."""
        ...

    def stop(self) -> None:
        """Disconnect cleanly."""
        ...

    def publish(self, topic: str, **fields) -> None:
        """Build, check and send a message. Raise InvalidMessage if it is wrong."""
        ...

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """Call handler(topic, data) for every valid message matching the pattern.

        The pattern may use MQTT wildcards: + (one level) and # (everything below).
        """
        ...


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard matching: 'glo/alert/#' matches 'glo/alert/call'."""
    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    for i, part in enumerate(pattern_parts):
        if part == "#":
            return True
        if i >= len(topic_parts):
            return False
        if part != "+" and part != topic_parts[i]:
            return False
    return len(pattern_parts) == len(topic_parts)


def decode(topic: str, payload: Union[bytes, str]) -> Payload:
    """Turn a received payload into what handlers receive, or raise InvalidMessage."""
    if topic in STATUS_TOPICS:
        return messages.parse_status(payload)
    return messages.parse(topic, payload)


def deliver(subscriptions: List[Tuple[str, Handler]], topic: str, payload: Union[bytes, str]) -> None:
    """Check a received message and give it to every matching handler.

    An invalid message is discarded and logged, as the contract says. An error
    inside one handler is logged and does not stop the others.
    """
    try:
        data = decode(topic, payload)
    except messages.InvalidMessage as exc:
        logger.warning("discarded invalid message: %s", exc)
        return
    for pattern, handler in subscriptions:
        if topic_matches(pattern, topic):
            try:
                handler(topic, data)
            except Exception:
                logger.exception("handler for %s failed", topic)


class FakeBus:
    """A bus for tests: no broker. It records what is published and lets the
    test inject received messages, which go through the same checks."""

    def __init__(self) -> None:
        self.published: List[Tuple[str, Dict]] = []
        self.started = False
        self._subscriptions: List[Tuple[str, Handler]] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def publish(self, topic: str, **fields) -> None:
        messages.build(topic, **fields)  # same check as the real bus
        self.published.append((topic, dict(fields)))

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subscriptions.append((pattern, handler))

    def inject(self, topic: str, payload: Union[bytes, str]) -> None:
        """Pretend the broker delivered this payload (JSON text or status text)."""
        deliver(self._subscriptions, topic, payload)

    def published_on(self, topic: str) -> List[Dict]:
        """The messages published on one topic, in order (useful in tests)."""
        return [fields for published_topic, fields in self.published if published_topic == topic]
