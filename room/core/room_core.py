"""The Room Pi's core: it measures, listens and obeys. It never decides.

- Every ENV_PERIOD_SECONDS it reads the temperature and publishes it. A reading
  that fails or cannot be trusted is logged and skipped (tests T6 and T23).
- It publishes a voice command only while the brain has the microphone on.
- It moves the fan when the brain orders it, then confirms the new speed.

It only knows its ports, the bus and the clock, so tests run it with fakes
and a FakeClock.
"""

from __future__ import annotations

import logging

from common import topics
from common.bus import MessageBus, Payload
from common.clock import Clock
from room.core import voice
from room.core.ports import Fan, SensorError, TemperatureSensor

ENV_PERIOD_SECONDS = 2
TIMESTAMP_PRECISION = "seconds"

logger = logging.getLogger(__name__)


class RoomCore:
    def __init__(self, bus: MessageBus, clock: Clock, sensor: TemperatureSensor, fan: Fan) -> None:
        self._bus = bus
        self._clock = clock
        self._sensor = sensor
        self._fan = fan
        self._mic_enabled = False  # the brain switches it on when someone enters

    def start(self) -> None:
        self._bus.subscribe(topics.ROOM_MIC_ENABLE, self._on_mic_enable)
        self._bus.subscribe(topics.ROOM_FAN_CMD, self._on_fan_cmd)
        self._clock.schedule(ENV_PERIOD_SECONDS, self._measure)

    def on_phrase(self, text: str) -> None:
        """Called by the speech recogniser with every phrase it heard."""
        command = voice.command_for(text)
        if command is None:
            return
        if not self._mic_enabled:
            logger.info("voice command %r ignored: microphone off", command)
            return
        self._bus.publish(topics.ROOM_VOICE, ts=self._timestamp(), command=command)

    def _measure(self) -> None:
        # The next reading is scheduled first, so the period stays exact.
        self._clock.schedule(ENV_PERIOD_SECONDS, self._measure)
        try:
            temp = self._sensor.read()
        except SensorError as exc:
            logger.warning("temperature reading discarded: %s", exc)
            return
        self._bus.publish(topics.ROOM_ENV, ts=self._timestamp(), temp=temp)

    def _on_mic_enable(self, _topic: str, data: Payload) -> None:
        self._mic_enabled = data["enabled"]

    def _on_fan_cmd(self, _topic: str, data: Payload) -> None:
        speed = data["speed"]
        self._fan.set_speed(speed)
        # Confirmed only once the fan really moved. If set_speed fails, the bus
        # logs the error and nothing is confirmed.
        self._bus.publish(topics.ROOM_FAN_STATE, ts=self._timestamp(), speed=speed)

    def _timestamp(self) -> str:
        """Now, in UTC with its offset, from the clock (never datetime.now())."""
        return self._clock.now().isoformat(timespec=TIMESTAMP_PRECISION)
