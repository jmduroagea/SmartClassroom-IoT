"""The brain's application layer: it connects the bus, the core and the repository.

Every message received goes to the state machine or the detector, and every
action they return is carried out here: a message published on the bus or a
document written to the database. The core never knows about MQTT or MongoDB.

Three threads can reach the brain at once: MQTT messages, the clock's timers
and the microphone/alarm timers. One lock makes them take turns, and the timers
of the state machine run inside the same lock (LockedClock).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, List

from common import topics
from common.bus import MessageBus, Payload
from common.clock import Clock, TimerHandle
from server.brain.core.emergency_detector import EmergencyDetector
from server.brain.core.state_machine import StateMachine
from server.brain.ports.repository import RepositoryPort

TIMESTAMP_PRECISION = "seconds"
DEVICE_BY_STATUS_TOPIC = {topics.DOOR_STATUS: "door", topics.ROOM_STATUS: "room"}

logger = logging.getLogger(__name__)


class LockedClock:
    """A clock whose timer callbacks run while holding the brain's lock."""

    def __init__(self, clock: Clock, lock: threading.Lock) -> None:
        self._clock = clock
        self._lock = lock

    def now(self):
        return self._clock.now()

    def schedule(self, delay: float, callback: Callable[[], None]) -> TimerHandle:
        def locked_callback() -> None:
            with self._lock:
                callback()

        return self._clock.schedule(delay, locked_callback)


class Brain:
    def __init__(self, bus: MessageBus, clock: Clock, repo: RepositoryPort) -> None:
        self._bus = bus
        self._clock = clock
        self._repo = repo
        self._lock = threading.Lock()
        self.machine = StateMachine(LockedClock(clock, self._lock), emit=self._execute_one)
        self.detector = EmergencyDetector()
        # action type -> what carries it out
        self._executors: Dict[str, Callable[[dict], None]] = {
            "say": lambda a: self._bus.publish(topics.DOOR_SPEAKER_SAY, text=a["text"]),
            "set_led": lambda a: self._bus.publish(topics.DOOR_LED_CMD, color=a["color"], mode=a["mode"]),
            "set_pir": lambda a: self._bus.publish(topics.DOOR_PIR_ENABLE, enabled=a["enabled"]),
            "set_mic": lambda a: self._bus.publish(topics.ROOM_MIC_ENABLE, enabled=a["enabled"]),
            "set_fan": lambda a: self._bus.publish(topics.ROOM_FAN_CMD, speed=a["speed"]),
            "set_alarm": lambda a: self._bus.publish(topics.DOOR_ALARM, enabled=a["enabled"]),
            "alert_units": self._alert_units,
            "alert_call": self._alert_call,
            "access": lambda a: self._repo.log_access(a["card_id"], a["access"], a["name"], self._now()),
            "system_event": lambda a: self._repo.log_system(a["event"], a["device"], a["detail"], self._now()),
            "save_temperature": lambda a: self._repo.log_env(a["value"], self._now()),
            "register_card": lambda a: self._repo.save_user(a["card_id"], a["name"]),
            "open_emergency_record": self._open_emergency_record,
            "emergency_reading": lambda a: self._repo.add_emergency_reading(a["emergency_id"], a["value"], self._now()),
            "emergency_call": lambda a: self._repo.add_emergency_call(a["emergency_id"], a["reason"], self._now()),
            "emergency_evacuated": lambda a: self._repo.mark_evacuated(a["emergency_id"], self._now()),
            "emergency_not_evacuated": lambda a: self._repo.mark_not_evacuated(a["emergency_id"]),
            "close_emergency_record": lambda a: self._repo.close_emergency(a["emergency_id"], self._now()),
            "reset_detector": lambda a: self.detector.reset(),
        }

    def start(self) -> None:
        handlers = {
            topics.DOOR_MOTION: self._on_motion,
            topics.DOOR_RFID: self._on_card,
            topics.ROOM_ENV: self._on_env,
            topics.ROOM_VOICE: self._on_voice,
            topics.ROOM_FAN_STATE: self._on_fan_state,
            topics.WEB_CMD: self._on_web,
            topics.DOOR_STATUS: self._on_status,
            topics.ROOM_STATUS: self._on_status,
        }
        for topic, handler in handlers.items():
            self._bus.subscribe(topic, self._locked(handler))

    # --- Messages received ----------------------------------------------------------

    def _on_motion(self, _topic: str, _data: Payload) -> None:
        self._repo.log_motion(True, self._now())
        self._execute(self.machine.handle_pir())

    def _on_card(self, _topic: str, data: Payload) -> None:
        card_id = data["card_id"]
        user = self._repo.find_user_by_card(card_id)
        name = user["name"] if user else None
        self._execute(self.machine.handle_card(card_id, is_known=user is not None, user_name=name))

    def _on_env(self, _topic: str, data: Payload) -> None:
        temp = float(data["temp"])
        # The brain's own time (decision 3A): one clock for everything, in UTC
        seconds = self._now().timestamp()
        self._execute(self.machine.handle_temperature(seconds, temp))
        if self.detector.process_temperature(seconds, temp):
            self._execute(self.machine.handle_emergency("rate", temp))

    def _on_voice(self, _topic: str, data: Payload) -> None:
        self._execute(self.machine.handle_voice_command(data["command"]))

    def _on_fan_state(self, _topic: str, data: Payload) -> None:
        self._repo.log_fan(data["speed"], self._now())

    def _on_web(self, _topic: str, data: Payload) -> None:
        action = data["action"]
        if action == "fan":
            actions = self.machine.handle_web_fan(data["speed"])
        elif action == "unlock":
            actions = self.machine.unlock()
        elif action == "new_card":
            actions = self.machine.handle_register_card(data["card_id"], data["name"])
        elif action == "simulate_emergency":
            actions = self.machine.handle_emergency("simulated", self.machine.last_known_temp)
        elif action == "force_exit":
            actions = self.machine.force_exit()
            if not actions:
                logger.warning("force_exit received, but nobody is inside")
        else:  # end_emergency
            actions = self.machine.end_emergency()
            if not actions:
                logger.warning("end_emergency received, but there is no emergency")
        self._execute(actions)

    def _on_status(self, topic: str, status: Payload) -> None:
        self._repo.log_system(status, DEVICE_BY_STATUS_TOPIC[topic], "", self._now())

    # --- Actions carried out --------------------------------------------------------

    def _execute(self, actions: List[dict]) -> None:
        for action in actions:
            self._execute_one(action)

    def _execute_one(self, action: dict) -> None:
        executor = self._executors.get(action["type"])
        if executor is None:
            logger.error("no executor for action %r", action)
            return
        executor(action)

    def _open_emergency_record(self, action: dict) -> None:
        """One document per emergency, with the readings of the last 30 s already in it.
        The notification to the units is sent at the same moment (the next action)."""
        now = self._now()
        buffer = [
            {"ts": datetime.fromtimestamp(seconds, timezone.utc), "temp": temp}
            for seconds, temp in self.detector.readings
        ]
        self._repo.create_emergency(action["emergency_id"], {
            "started_at": now,
            "ended_at": None,
            "trigger": action["trigger"],
            "trigger_temp": action["trigger_temp"],
            "person": action["person"],
            "evacuated_at": None,
            "not_evacuated_alert": False,
            "units_notified_at": now,
            "calls": [],
            "readings": buffer,
        })

    def _alert_units(self, action: dict) -> None:
        self._bus.publish(
            topics.ALERT_UNITS,
            ts=self._timestamp(),
            emergency_id=action["emergency_id"],
            temp=action["temp"],
            person=action["person"],
        )

    def _alert_call(self, action: dict) -> None:
        self._bus.publish(
            topics.ALERT_CALL,
            ts=self._timestamp(),
            reason=action["reason"],
            emergency_id=action["emergency_id"],
        )

    # --- Helpers --------------------------------------------------------------------

    def _locked(self, handler: Callable[[str, Payload], None]) -> Callable[[str, Payload], None]:
        def locked_handler(topic: str, data: Payload) -> None:
            with self._lock:
                handler(topic, data)

        return locked_handler

    def _now(self):
        return self._clock.now()

    def _timestamp(self) -> str:
        return self._clock.now().isoformat(timespec=TIMESTAMP_PRECISION)
