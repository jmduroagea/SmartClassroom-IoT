"""The Door Pi's core: it measures and obeys. It never decides.

- A card read is published on glo/door/rfid. The reader repeats the same card
  while it is held, so the same card again within CARD_DEBOUNCE_SECONDS is ignored.
- Movement is published on glo/door/motion only while the brain has the PIR on.
- LEDs: "pulse" lights the LED for PULSE_SECONDS and then switches it off,
  "blink" makes it blink until "off" arrives. The colour always comes in the order.
- Speech is not queued: while the speaker is talking, only the latest text is
  kept, and it is said when the current one ends.
- While the alarm is on, ALARM_TEXT is said every ALARM_INTERVAL_SECONDS. When it
  is switched off, an alarm text still waiting is dropped.

It only knows its ports, the bus and the clock, so tests run it with fakes and a
FakeClock. MQTT messages, timers, the card reader and the speaker can call it from
different threads, so one lock makes them take turns.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from common import messages, topics
from common.bus import MessageBus, Payload
from common.clock import Clock, TimerHandle
from door.core.ports import DoorLight, Speaker

CARD_DEBOUNCE_SECONDS = 2.0
PULSE_SECONDS = 3.0
BLINK_HALF_PERIOD_SECONDS = 0.5
TIMESTAMP_PRECISION = "seconds"

logger = logging.getLogger(__name__)


class DoorCore:
    def __init__(self, bus: MessageBus, clock: Clock, light: DoorLight, speaker: Speaker) -> None:
        self._bus = bus
        self._clock = clock
        self._light = light
        self._speaker = speaker
        self._lock = threading.RLock()
        self._pir_enabled = True  # the brain switches it off while someone is inside
        self._last_card: Optional[str] = None
        self._last_card_seconds = 0.0
        self._led_timers: Dict[str, TimerHandle] = {}
        self._led_lit: Dict[str, bool] = {}
        self._speaking = False
        self._pending_text: Optional[str] = None
        self._alarm_timer: Optional[TimerHandle] = None

    def start(self) -> None:
        self._bus.subscribe(topics.DOOR_PIR_ENABLE, self._on_pir_enable)
        self._bus.subscribe(topics.DOOR_LED_CMD, self._on_led_cmd)
        self._bus.subscribe(topics.DOOR_SPEAKER_SAY, self._on_say)
        self._bus.subscribe(topics.DOOR_ALARM, self._on_alarm)

    # --- Sensors --------------------------------------------------------------------

    def on_card(self, card_id: str) -> None:
        """Called by the card reader with every card it reads."""
        with self._lock:
            seconds = self._clock.now().timestamp()
            repeated = card_id == self._last_card and seconds - self._last_card_seconds < CARD_DEBOUNCE_SECONDS
            self._last_card, self._last_card_seconds = card_id, seconds
            if repeated:
                return
            self._bus.publish(topics.DOOR_RFID, ts=self._timestamp(), card_id=card_id)

    def on_motion(self) -> None:
        """Called by the PIR every time it detects movement."""
        with self._lock:
            if not self._pir_enabled:
                return
            self._bus.publish(topics.DOOR_MOTION, ts=self._timestamp())

    def _on_pir_enable(self, _topic: str, data: Payload) -> None:
        with self._lock:
            self._pir_enabled = data["enabled"]

    # --- LEDs -----------------------------------------------------------------------

    def _on_led_cmd(self, _topic: str, data: Payload) -> None:
        color, mode = data["color"], data["mode"]
        with self._lock:
            self._stop_led_timer(color)
            if mode == "off":
                self._set_led(color, False)
            elif mode == "pulse":
                self._set_led(color, True)
                self._led_timers[color] = self._clock.schedule(PULSE_SECONDS, lambda: self._end_pulse(color))
            else:  # blink
                self._set_led(color, True)
                self._schedule_blink(color)

    def _end_pulse(self, color: str) -> None:
        with self._lock:
            self._led_timers.pop(color, None)
            self._set_led(color, False)

    def _schedule_blink(self, color: str) -> None:
        self._led_timers[color] = self._clock.schedule(BLINK_HALF_PERIOD_SECONDS, lambda: self._blink(color))

    def _blink(self, color: str) -> None:
        with self._lock:
            self._set_led(color, not self._led_lit.get(color, False))
            self._schedule_blink(color)

    def _stop_led_timer(self, color: str) -> None:
        timer = self._led_timers.pop(color, None)
        if timer is not None:
            timer.cancel()

    def _set_led(self, color: str, lit: bool) -> None:
        if lit:
            self._light.on(color)
        else:
            self._light.off(color)
        self._led_lit[color] = lit

    # --- Speech and alarm -----------------------------------------------------------

    def _on_say(self, _topic: str, data: Payload) -> None:
        self._say(data["text"])

    def _say(self, text: str) -> None:
        with self._lock:
            if self._speaking:
                self._pending_text = text  # replaces any older text still waiting
                return
            self._play(text)

    def _play(self, text: str) -> None:
        self._speaking = True
        self._speaker.play(text, self._finished_speaking)

    def _finished_speaking(self) -> None:
        with self._lock:
            self._speaking = False
            if self._pending_text is not None:
                text, self._pending_text = self._pending_text, None
                self._play(text)

    def _on_alarm(self, _topic: str, data: Payload) -> None:
        with self._lock:
            if data["enabled"]:
                if self._alarm_timer is None:
                    self._sound_alarm()
                return
            if self._alarm_timer is not None:
                self._alarm_timer.cancel()
                self._alarm_timer = None
            if self._pending_text == messages.ALARM_TEXT:
                self._pending_text = None

    def _sound_alarm(self) -> None:
        with self._lock:
            self._alarm_timer = self._clock.schedule(messages.ALARM_INTERVAL_SECONDS, self._sound_alarm)
            self._say(messages.ALARM_TEXT)

    # --- Helpers --------------------------------------------------------------------

    def _timestamp(self) -> str:
        """Now, in UTC with its offset, from the clock (never datetime.now())."""
        return self._clock.now().isoformat(timespec=TIMESTAMP_PRECISION)
