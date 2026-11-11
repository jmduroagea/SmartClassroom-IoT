"""Helpers for scenario tests: start the Docker simulation and talk to it.

Scenario tests are black box. They only use what exists on the real network:
- MQTT, where the test plays the role of the Pis (it publishes what a Pi would
  publish and listens to what the brain orders), and
- the web API, to see what a user would see and what was saved in the database.

They never read MongoDB directly and never look inside a program.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import paho.mqtt.client as mqtt

from common import messages, topics

REPO_ROOT = Path(__file__).resolve().parents[2]

# Where the simulation is published on the laptop (see compose.yaml)
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
WEB_URL = "http://127.0.0.1:3001"

ALL_TOPICS = f"{topics.PREFIX}/#"
LISTEN_QOS = 2  # receive every message with the QoS it was published with

# Timeouts, in seconds
DOCKER_TIMEOUT = 600        # first build downloads the images
CONTAINER_STOP_TIMEOUT = 1  # containers hold no state worth a clean stop
READY_TIMEOUT = 90          # the whole system answering after a restart
REACTION_TIMEOUT = 5        # the brain reacting to one message
HTTP_TIMEOUT = 5
POLL_INTERVAL = 0.2
QUIET_TIME = 1.5            # how long we wait to say "nothing happened"
LOG_LINES = 40

# The readiness check sends this temperature; tests can rely on it afterwards.
BASE_TEMPERATURE = 21.0

# Voice commands start with "Ok Computer". The speaker must never say this word,
# or the microphone could hear the system's own voice as a command.
WAKE_WORD = "computer"


def docker_compose(*args: str) -> str:
    """Run `docker compose ...` at the repository root and return its output."""
    try:
        result = subprocess.run(
            ["docker", "compose", *args],
            cwd=REPO_ROOT, capture_output=True, timeout=DOCKER_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        raise RuntimeError("Docker is not installed: scenario tests need it") from None
    if result.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(args)} failed. Is Docker running?\n{result.stderr}"
        )
    return (result.stdout or "") + (result.stderr or "")


def build_images() -> None:
    docker_compose("build")


def restart_clean() -> None:
    """Recreate every container: empty database, brain back in its first state."""
    docker_compose("up", "-d", "--force-recreate", "--timeout", str(CONTAINER_STOP_TIMEOUT))


def stop() -> None:
    docker_compose("down", "--timeout", str(CONTAINER_STOP_TIMEOUT))


def logs() -> str:
    return docker_compose("logs", "--no-color", "--tail", str(LOG_LINES), "brain", "web")


def now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Simulation:
    """One connection to the running system, as the Pis and a web user see it."""

    def __init__(self) -> None:
        self._received: List[Tuple[str, str]] = []
        self._sentences: List[str] = []  # everything sent to the speaker, never forgotten
        self._lock = threading.Lock()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="scenario-test")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._subscribed = threading.Event()
        self._client.on_subscribe = lambda *_args: self._subscribed.set()

    # --- connection -------------------------------------------------------------

    def connect(self) -> None:
        """Wait until the broker, the web and the brain all answer."""
        deadline = time.monotonic() + READY_TIMEOUT
        self._connect_to_broker(deadline)
        self._wait_for_web(deadline)
        self._wait_for_brain(deadline)
        self.forget_messages()

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _connect_to_broker(self, deadline: float) -> None:
        while True:
            try:
                self._client.connect(BROKER_HOST, BROKER_PORT)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise AssertionError("the broker did not start") from None
                time.sleep(POLL_INTERVAL)
        self._client.loop_start()
        if not self._subscribed.wait(READY_TIMEOUT):
            raise AssertionError("could not subscribe to the broker")

    def _wait_for_web(self, deadline: float) -> None:
        while True:
            try:
                self.status()
                return
            except (OSError, AssertionError):
                if time.monotonic() > deadline:
                    raise AssertionError("the web did not start") from None
                time.sleep(POLL_INTERVAL)

    def _wait_for_brain(self, deadline: float) -> None:
        # The brain saves the first temperature it receives, and the web shows
        # it. When that works, the whole chain is up: broker, brain, MongoDB, web.
        while self.status()["temperature"] != BASE_TEMPERATURE:
            if time.monotonic() > deadline:
                raise AssertionError("the brain did not start (no temperature saved)")
            self.publish(topics.ROOM_ENV, ts=now_ts(), temp=BASE_TEMPERATURE)
            time.sleep(POLL_INTERVAL)

    def _on_connect(self, client, _userdata, _flags, _reason_code, _properties) -> None:
        client.subscribe(ALL_TOPICS, qos=LISTEN_QOS)

    def _on_message(self, _client, _userdata, message) -> None:
        payload = message.payload.decode("utf-8", "replace")
        with self._lock:
            self._received.append((message.topic, payload))
            if message.topic == topics.DOOR_SPEAKER_SAY:
                self._sentences.append(payload)

    # --- playing the Pis: MQTT ----------------------------------------------------

    def publish(self, topic: str, **fields) -> None:
        """Publish what a Pi would publish. The contract checks it first."""
        self.publish_raw(topic, messages.build(topic, **fields))

    def publish_raw(self, topic: str, payload: str) -> None:
        """Publish any text, even an invalid message (robustness tests only)."""
        self._client.publish(topic, payload, qos=messages.qos(topic)).wait_for_publish(HTTP_TIMEOUT)

    def messages_on(self, topic: str) -> List[dict]:
        """Every message received on a topic since the last forget_messages()."""
        with self._lock:
            return [json.loads(payload) for received, payload in self._received if received == topic]

    def forget_messages(self) -> None:
        with self._lock:
            self._received.clear()

    def wait_for_message(
        self, topic: str, where: Optional[Callable[[dict], bool]] = None,
        timeout: float = REACTION_TIMEOUT,
    ) -> dict:
        """Return the first message on the topic that fulfils `where`, or fail."""
        deadline = time.monotonic() + timeout
        while True:
            for message in self.messages_on(topic):
                if where is None or where(message):
                    return message
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"no expected message on {topic} after {timeout} s. "
                    f"Received there: {self.messages_on(topic)}"
                )
            time.sleep(POLL_INTERVAL)

    def said(self, timeout: float = REACTION_TIMEOUT, containing: str = "") -> str:
        """Wait for the next sentence sent to the speaker that contains a text."""
        message = self.wait_for_message(
            topics.DOOR_SPEAKER_SAY, lambda m: containing in m["text"], timeout
        )
        return message["text"]

    def assert_wake_word_never_said(self) -> None:
        """Fail if any sentence sent to the speaker in this test had the wake word."""
        with self._lock:
            guilty = [sentence for sentence in self._sentences if WAKE_WORD in sentence.lower()]
        assert guilty == [], f"the speaker was told to say the wake word: {guilty}"

    def assert_nothing_on(self, topic: str) -> None:
        """Fail if a message arrives on the topic during the quiet time."""
        time.sleep(QUIET_TIME)
        assert self.messages_on(topic) == [], f"unexpected message on {topic}"

    # --- being a web user: HTTP -----------------------------------------------------

    def get(self, path: str):
        status, body = self._request("GET", path)
        assert status == 200, f"GET {path} answered {status}: {body}"
        return body

    def post(self, path: str, body: Optional[dict] = None) -> Tuple[int, dict]:
        return self._request("POST", path, body or {})

    def status(self) -> dict:
        return self.get("/api/status")

    def wait_for_status(self, where: Callable[[dict], bool], timeout: float = REACTION_TIMEOUT) -> dict:
        """Wait until what the web shows fulfils `where`, or fail."""
        deadline = time.monotonic() + timeout
        while True:
            status = self.status()
            if where(status):
                return status
            if time.monotonic() > deadline:
                raise AssertionError(f"the web never showed what was expected. Last status: {status}")
            time.sleep(POLL_INTERVAL)

    def wait_for(self, condition: Callable[[], bool], timeout: float = REACTION_TIMEOUT) -> None:
        """Wait until any condition about the system becomes true, or fail."""
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError(f"the condition was still false after {timeout} s")
            time.sleep(POLL_INTERVAL)

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            WEB_URL + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")
