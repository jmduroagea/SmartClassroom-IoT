"""A fake paho client for the unit tests of common/sim_link.py and the fakes that use it."""

import json
from types import SimpleNamespace


class FakePahoClient:
    """Records what the link does with paho, and lets the test deliver messages."""

    def __init__(self):
        self.subscribed = []
        self.published = []
        self.connected_to = None
        self.on_connect = self.on_message = None

    def connect_async(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.on_connect(self, None, None, 0, None)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def subscribe(self, topic, qos):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos):
        self.published.append((topic, json.loads(payload)))

    def deliver(self, topic, payload):
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload.encode()))
