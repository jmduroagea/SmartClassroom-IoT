from enum import Enum
from typing import Optional


class State(Enum):
    IDLE = "IDLE"
    WAITING_CARD = "WAITING_CARD"
    INSIDE = "INSIDE"
    LOCKED = "LOCKED"
    EMERGENCY = "EMERGENCY"


class StateMachine:
    MAX_FAILED_ATTEMPTS = 3
    TEMP_SAVE_INTERVAL_SECONDS = 10.0
    # How the emergency started: the detector ("rate") or the web button ("simulated")
    EMERGENCY_TRIGGERS = ("rate", "simulated")
    # emergency_id, from the clock: one emergency at a time, so seconds are enough
    EMERGENCY_ID_FORMAT = "em-%Y%m%dT%H%M%S"

    TIMER_PROMPT_DELAY = 3.0
    TIMER_REMINDER_DELAY = 5.0
    TIMER_TIMEOUT_DELAY = 30.0

    def __init__(self, clock, emit):
        self.clock = clock
        self.emit = emit
        self.state = State.IDLE
        self.failed_attempts = 0
        self.current_user_card = None
        self.current_user_name = None
        self.emergency_id = None
        self.emergency_trigger = None
        self.last_temp_save_time = 0.0
        self.last_known_temp = None
        self.current_timer = None

    def _cancel_timer(self):
        """Cancels any pending timer."""
        if self.current_timer:
            self.current_timer.cancel()
            self.current_timer = None

    def handle_pir(self) -> list:
        """Handles the PIR motion sensor."""
        actions = []
        if self.state == State.IDLE:
            self.state = State.WAITING_CARD
            self._cancel_timer()
            self.current_timer = self.clock.schedule(
                self.TIMER_PROMPT_DELAY, self._prompt
            )
        return actions

    def _prompt(self):
        """Callback for the 3s prompt."""
        if self.state != State.WAITING_CARD:
            return
        self.current_timer = self.clock.schedule(
            self.TIMER_REMINDER_DELAY, self._reminder
        )
        self.emit({"type": "say", "text": "scan your card"})

    def _reminder(self):
        """Callback for the 5s reminder."""
        if self.state != State.WAITING_CARD:
            return
        self.current_timer = self.clock.schedule(
            self.TIMER_TIMEOUT_DELAY, self._timeout
        )
        self.emit({"type": "say", "text": "Reminder: scan your card"})

    def _timeout(self):
        """Callback for the 30s timeout."""
        if self.state != State.WAITING_CARD:
            return
        self.state = State.IDLE
        self.current_timer = None

    def handle_card(self, card_id: str, is_known: bool, user_name: str = None) -> list:
        """Handles card scans."""
        actions = []
        if self.state == State.EMERGENCY:
            return actions

        if self.state == State.LOCKED:
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "access", "access": "denied", "card_id": card_id, "name": user_name})
            return actions

        self._cancel_timer()

        if not is_known:
            self.failed_attempts += 1
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "access", "access": "denied", "card_id": card_id, "name": None})
            actions.append({
                    "type": "system_event", "event": "locked", "device": "door",
                    "detail": f"{self.failed_attempts} unknown cards",
                })
            actions.append({"type": "say", "text": "Card not recognized."})

            if self.failed_attempts >= self.MAX_FAILED_ATTEMPTS:
                self.state = State.LOCKED
                actions.append({"type": "say", "text": "System locked"})
            elif self.state == State.WAITING_CARD:
                self.state = State.IDLE

            return actions

        self.failed_attempts = 0
        if self.state in (State.WAITING_CARD, State.IDLE):
            self.state = State.INSIDE
            self.current_user_card = card_id
            self.current_user_name = user_name
            name_str = user_name or "User"

            if self.last_known_temp is not None:
                rounded_temp = round(self.last_known_temp, 1)
                text = f"Welcome, {name_str}. The temperature is {rounded_temp} degrees."
                actions.append({"type": "say", "text": text})
            else:
                actions.append({"type": "say", "text": f"Welcome, {name_str}."})

            actions.append({"type": "access", "access": "in", "card_id": card_id, "name": user_name})
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
            actions.append({"type": "set_pir", "enabled": False})
            actions.append({"type": "set_mic", "enabled": True})

        elif self.state == State.INSIDE:
            if self.current_user_card == card_id:
                self.state = State.IDLE
                self.current_user_card = None
                self.current_user_name = None
                name_str = user_name or "User"
                actions.append({"type": "say", "text": f"Goodbye, {name_str}."})
                actions.append({"type": "access", "access": "out", "card_id": card_id, "name": user_name})
                actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
                actions.append({"type": "set_fan", "speed": 0})
                actions.append({"type": "set_mic", "enabled": False})
                actions.append({"type": "set_pir", "enabled": True})
            else:
                actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
                actions.append({"type": "access", "access": "occupied", "card_id": card_id, "name": user_name})
                actions.append({"type": "say", "text": "Room occupied."})

        return actions

    def unlock(self) -> list:
        """Unlocks the system from the web interface."""
        actions = []
        if self.state == State.LOCKED:
            self.state = State.IDLE
            self.failed_attempts = 0
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
            actions.append({"type": "system_event", "event": "unlocked", "device": "web", "detail": ""})
        return actions

    def handle_emergency(self, trigger: str, temp: Optional[float] = None) -> list:
        """Declares the emergency from any state. A second one while active is ignored."""
        if trigger not in self.EMERGENCY_TRIGGERS:
            raise ValueError(f"unknown emergency trigger {trigger!r}")
        if self.state == State.EMERGENCY:
            return []
        self._cancel_timer()
        person = self.current_user_name if self.state == State.INSIDE else None
        self.state = State.EMERGENCY
        self.emergency_id = self.clock.now().strftime(self.EMERGENCY_ID_FORMAT)
        self.emergency_trigger = trigger
        return [
            {"type": "set_fan", "speed": 0},
            {"type": "set_led", "color": "red", "mode": "blink"},
            {"type": "set_alarm", "enabled": True},
            {"type": "set_mic", "enabled": True},
            {"type": "set_pir", "enabled": False},
            {"type": "alert_units", "emergency_id": self.emergency_id, "temp": temp, "person": person},
        ]

    def handle_fan_command(self, command: dict) -> list:
        """Handles external fan commands."""
        if self.state == State.EMERGENCY:
            return []
        speed = command.get("speed", 0)
        return [{"type": "set_fan", "speed": speed}]

    def handle_temperature(self, timestamp: float, temp: float) -> list:
        """Saves temperature readings periodically."""
        actions = []
        self.last_known_temp = temp
        if self.state == State.EMERGENCY:
            return actions

        time_diff = timestamp - self.last_temp_save_time
        if time_diff >= self.TEMP_SAVE_INTERVAL_SECONDS:
            self.last_temp_save_time = timestamp
            actions.append({"type": "save_temperature", "value": temp})
        return actions

    def handle_voice_command(self, command: str) -> list:
        """Handles incoming voice commands."""
        if self.state == State.EMERGENCY or self.state != State.INSIDE:
            return []
        return [{"type": "voice_control", "command": command}]

    def handle_web_fan(self, speed_level: int = 0) -> list:
        """Handles fan commands exclusively from the web."""
        if self.state == State.EMERGENCY:
            return []
        return [{"type": "set_fan", "speed": speed_level}]

    def handle_register_card(self, card_id: str, name: str) -> list:
        """Registers a new card."""
        return [{"type": "register_card", "card_id": card_id, "name": name}]
