from common.messages import FAN_SPEEDS
from enum import Enum


class State(Enum):
    IDLE = "IDLE"
    WAITING_CARD = "WAITING_CARD"
    INSIDE = "INSIDE"
    LOCKED = "LOCKED"
    EMERGENCY = "EMERGENCY"


class StateMachine:
    MAX_FAILED_ATTEMPTS = 3
    TEMP_SAVE_INTERVAL_SECONDS = 10.0
    ALARM_INTERVAL_SECONDS = 3

    TIMER_PROMPT_DELAY = 3.0
    TIMER_REMINDER_DELAY = 5.0
    TIMER_TIMEOUT_DELAY = 30.0

    def __init__(self, clock, emit):
        self.clock = clock
        self.emit = emit
        self.state = State.IDLE
        self.failed_attempts = 0
        self.current_user_card = None
        self.last_temp_save_time = 0.0
        self.last_known_temp = None
        self.current_timer = None
        self.fan_speed = 0

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
            actions.append({"type": "denied", "card_id": card_id})
            return actions

        self._cancel_timer()

        if not is_known:
            self.failed_attempts += 1
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "denied", "card_id": card_id})
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
            name_str = user_name or "User"

            if self.last_known_temp is not None:
                rounded_temp = round(self.last_known_temp, 1)
                text = f"Welcome, {name_str}. The temperature is {rounded_temp} degrees."
                actions.append({"type": "say", "text": text})
            else:
                actions.append({"type": "say", "text": f"Welcome, {name_str}."})

            actions.append({"type": "access", "access": "in", "card_id": card_id})
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
            actions.append({"type": "set_pir", "enabled": False})
            actions.append({"type": "set_mic", "enabled": True})

        elif self.state == State.INSIDE:
            if self.current_user_card == card_id:
                self.state = State.IDLE
                self.current_user_card = None
                name_str = user_name or "User"
                actions.append({"type": "say", "text": f"Goodbye, {name_str}."})
                actions.append({"type": "access", "access": "out", "card_id": card_id})
                actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
                self.fan_speed = 0
                actions.append({"type": "set_fan", "speed": 0})
                actions.append({"type": "set_mic", "enabled": False})
                actions.append({"type": "set_pir", "enabled": True})
            else:
                actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
                actions.append({"type": "occupied", "card_id": card_id})
                actions.append({"type": "say", "text": "Room occupied."})

        return actions

    def unlock(self) -> list:
        """Unlocks the system from the web interface."""
        actions = []
        if self.state == State.LOCKED:
            self.state = State.IDLE
            self.failed_attempts = 0
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
        return actions

    def handle_emergency(self, event: dict = None) -> list:
        """Triggers emergency mode."""
        self.state = State.EMERGENCY
        self._cancel_timer()
        self.fan_speed = 0
        return [
            {"type": "set_fan", "speed": 0, "locked": True},
            {"type": "set_led", "color": "red", "mode": "blink"},
            {"type": "set_alarm", "interval_seconds": self.ALARM_INTERVAL_SECONDS},
            {"type": "set_mic", "enabled": True},
            {"type": "set_pir", "enabled": False},
            {
                "type": "publish",
                "topic": "glo/alert/units",
                "payload": {"status": "EMERGENCY_TRIGGERED"}
            }
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
        """Handle voice commands ('hot', 'cold') strictly while INSIDE and not in EMERGENCY."""
        if self.state == State.EMERGENCY or self.state != State.INSIDE:
            return []

        text = command.strip().lower()

        actions = []
        speeds = FAN_SPEEDS

        if text == "hot":
            if self.fan_speed == 0:
                mid_index = len(speeds) // 2
                self.fan_speed = speeds[mid_index]
                actions.append({"type": "set_fan", "speed": self.fan_speed})
            elif self.fan_speed == speeds[-1]:
                actions.append({"type": "say", "text": "The fan is at maximum."})
            else:
                current_index = speeds.index(self.fan_speed)
                self.fan_speed = speeds[current_index + 1]
                actions.append({"type": "set_fan", "speed": self.fan_speed})
                if self.fan_speed == speeds[-1]:
                    actions.append({"type": "say", "text": "The fan is at maximum."})

        elif text == "cold":
            if self.fan_speed == 0:
                actions.append({"type": "say", "text": "The fan is already off."})
            else:
                current_index = speeds.index(self.fan_speed)
                self.fan_speed = speeds[current_index - 1]
                actions.append({"type": "set_fan", "speed": self.fan_speed})

        return actions

    def handle_web_fan(self, speed_level: int = 0) -> list:
        """Handles fan commands exclusively from the web."""
        if self.state == State.EMERGENCY:
            return []
        self.fan_speed = speed_level
        return [{"type": "set_fan", "speed": speed_level}]

    def handle_register_card(self, card_id: str, name: str) -> list:
        """Registers a new card."""
        return [{"type": "register_card", "card_id": card_id, "name": name}]
