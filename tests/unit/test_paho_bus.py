"""Unit tests of the paho adapter (common/paho_bus.py) with a mocked paho client.

No broker is needed: the paho client is replaced by a MagicMock, and the tests
check how the adapter uses it (topic, payload, QoS, last will, reconnection).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import paho.mqtt.client as mqtt
import pytest

from common import messages, topics
from common.config import load_config
from common.messages import InvalidMessage
from common.paho_bus import (
    KEEPALIVE_SECONDS,
    RECONNECT_MAX_DELAY_SECONDS,
    RECONNECT_MIN_DELAY_SECONDS,
    PahoBus,
)

CONFIG = load_config({"MQTT_HOST": "broker.test", "MQTT_PORT": "1884"})
TS = "2026-11-10T11:00:00"
CONNECTED = SimpleNamespace(is_failure=False)
REFUSED = SimpleNamespace(is_failure=True)


def make_bus(status_topic=None):
    client = MagicMock()
    client.is_connected.return_value = False
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    bus = PahoBus(CONFIG, "test-client", status_topic, client_factory=lambda client_id: client)
    return bus, client


# --- Publishing: topic, payload and QoS from the contract --------------------


def test_publish_uses_the_topic_payload_and_qos_of_the_contract():
    bus, client = make_bus()
    bus.publish(topics.DOOR_RFID, ts=TS, card_id="0F00A1B2C3")
    client.publish.assert_called_once()
    topic, payload = client.publish.call_args.args
    assert topic == topics.DOOR_RFID
    assert json.loads(payload) == {"ts": TS, "card_id": "0F00A1B2C3"}
    assert client.publish.call_args.kwargs["qos"] == 1


def test_alerts_are_published_with_qos_2():
    bus, client = make_bus()
    bus.publish(topics.ALERT_CALL, ts=TS, reason="help", emergency_id=None)
    assert client.publish.call_args.kwargs["qos"] == 2


def test_wrong_message_never_reaches_paho():
    bus, client = make_bus()
    with pytest.raises(InvalidMessage):
        bus.publish(topics.ROOM_FAN_CMD, speed=9)
    client.publish.assert_not_called()


def test_failed_publish_is_logged(caplog):
    bus, client = make_bus()
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_NO_CONN)
    bus.publish(topics.DOOR_MOTION, ts=TS)
    assert "could not publish" in caplog.text


# --- Last will and online status --------------------------------------------


def test_last_will_says_offline_retained():
    _bus, client = make_bus(status_topic=topics.DOOR_STATUS)
    client.will_set.assert_called_once_with(
        topics.DOOR_STATUS, messages.STATUS_OFFLINE, qos=1, retain=True
    )


def test_no_last_will_without_status_topic():
    _bus, client = make_bus()
    client.will_set.assert_not_called()


def test_on_connect_publishes_online_retained():
    bus, client = make_bus(status_topic=topics.DOOR_STATUS)
    bus._on_connect(client, None, None, CONNECTED, None)
    client.publish.assert_called_once_with(
        topics.DOOR_STATUS, messages.STATUS_ONLINE, qos=1, retain=True
    )


def test_stop_publishes_offline_and_disconnects():
    bus, client = make_bus(status_topic=topics.DOOR_STATUS)
    bus.stop()
    client.publish.assert_called_once_with(
        topics.DOOR_STATUS, messages.STATUS_OFFLINE, qos=1, retain=True
    )
    client.disconnect.assert_called_once()
    client.loop_stop.assert_called_once()


# --- Connection and automatic reconnection ----------------------------------


def test_start_connects_to_the_configured_broker_without_blocking():
    bus, client = make_bus()
    bus.start()
    client.connect_async.assert_called_once_with("broker.test", 1884, keepalive=KEEPALIVE_SECONDS)
    client.loop_start.assert_called_once()


def test_reconnection_delay_is_set():
    _bus, client = make_bus()
    client.reconnect_delay_set.assert_called_once_with(
        min_delay=RECONNECT_MIN_DELAY_SECONDS, max_delay=RECONNECT_MAX_DELAY_SECONDS
    )


def test_every_connection_subscribes_again():
    bus, client = make_bus()
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: None)
    bus.subscribe(topics.ALERT_ALL, lambda topic, data: None)
    client.subscribe.assert_not_called()  # not connected yet
    for _ in range(2):  # first connection, then a reconnection
        bus._on_connect(client, None, None, CONNECTED, None)
    assert client.subscribe.call_count == 4
    client.subscribe.assert_any_call(topics.DOOR_RFID, qos=1)
    client.subscribe.assert_any_call(topics.ALERT_ALL, qos=2)  # alerts keep QoS 2


def test_subscribing_while_connected_subscribes_at_once():
    bus, client = make_bus()
    client.is_connected.return_value = True
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: None)
    client.subscribe.assert_called_once_with(topics.DOOR_RFID, qos=1)


def test_refused_connection_does_nothing(caplog):
    bus, client = make_bus(status_topic=topics.DOOR_STATUS)
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: None)
    bus._on_connect(client, None, None, REFUSED, None)
    client.subscribe.assert_not_called()
    client.publish.assert_not_called()
    assert "connection refused" in caplog.text


# --- Receiving --------------------------------------------------------------


def test_received_message_reaches_the_handler_checked():
    bus, client = make_bus()
    received = []
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: received.append(data))
    message = SimpleNamespace(
        topic=topics.DOOR_RFID, payload=b'{"ts": "2026-11-10T11:00:00", "card_id": "0F00A1B2C3"}'
    )
    bus._on_message(client, None, message)
    assert received == [{"ts": TS, "card_id": "0F00A1B2C3"}]


def test_received_invalid_message_is_discarded():
    bus, client = make_bus()
    received = []
    bus.subscribe(topics.DOOR_RFID, lambda topic, data: received.append(data))
    bus._on_message(client, None, SimpleNamespace(topic=topics.DOOR_RFID, payload=b"not json"))
    assert received == []
