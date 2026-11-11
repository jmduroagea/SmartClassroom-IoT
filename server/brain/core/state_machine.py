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

    def __init__(self, clock=None):
        self.state = State.IDLE
        self.failed_attempts = 0
        self.current_user = None
        self.last_temp_save_time = 0.0
        self.clock = clock

    def handle_pir(self) -> list:
        actions = []
        if self.state == State.IDLE:
            self.state = State.WAITING_CARD
            if self.clock:
                self.clock.schedule(self.TIMER_PROMPT_DELAY, "prompt_card")
                self.clock.schedule(self.TIMER_REMINDER_DELAY, "remind_card")
                self.clock.schedule(self.TIMER_TIMEOUT_DELAY, "timeout_idle")
        return actions

    def handle_timer_event(self, event_name: str) -> list:
        actions = []
        if self.state == State.WAITING_CARD:
            if event_name == "prompt_card":
                actions.append({"type": "say", "text": "Please scan your card"})
            elif event_name == "remind_card":
                actions.append({"type": "say", "text": "Reminder: please scan your card"})
            elif event_name == "timeout_idle":
                self.state = State.IDLE
                actions.append({"type": "set_led", "color": "green", "mode": "off"})
        return actions

    def handle_card(self, card_id: str, is_known: bool, user_name: str = None) -> list:
        actions = []
        if self.state == State.EMERGENCY:
            return actions

        if self.state == State.LOCKED:
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "log_system", "level": "WARN", "msg": f"Access denied (LOCKED) for {card_id}"})
            return actions

        if not is_known:
            self.failed_attempts += 1
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "log_system", "level": "WARN", "msg": f"Access denied (UNKNOWN) for {card_id}"})
            if self.failed_attempts >= self.MAX_FAILED_ATTEMPTS:
                self.state = State.LOCKED
                actions.append({"type": "say", "text": "System locked"})
            return actions

        self.failed_attempts = 0
        if self.state in (State.WAITING_CARD, State.IDLE):
            self.state = State.INSIDE
            self.current_user = user_name or card_id
            if user_name:
                actions.append({"type": "say", "text": f"Welcome, {user_name}"})
            actions.append({"event_type": "in", "card_id": card_id})
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
        elif self.state == State.INSIDE:
            if self.current_user in (card_id, user_name):
                if user_name:
                    actions.append({"type": "say", "text": f"Goodbye, {user_name}"})
                actions.append({"event_type": "out", "card_id": card_id})
                self.state = State.IDLE
                self.current_user = None
                actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
            else:
                actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
                actions.append({"type": "log_system", "level": "WARN", "msg": f"Access denied (OCCUPIED) for {card_id}"})

        return actions

    def unlock(self) -> list:
        actions = []
        if self.state == State.LOCKED:
            self.state = State.IDLE
            self.failed_attempts = 0
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
        return actions

    def handle_emergency(self, event: dict = None) -> list:
        self.state = State.EMERGENCY
        return [
            {"type": "set_fan", "speed": "off", "locked": True},
            {"type": "set_led", "color": "red", "mode": "blink"},
            {"type": "set_alarm", "interval_seconds": self.ALARM_INTERVAL_SECONDS},
            {"type": "set_mic", "status": "on"},
            {"type": "set_pir", "status": "off"},
            {"type": "publish", "topic": "glo/alert/units", "payload": "EMERGENCY_TRIGGERED"}
        ]

    def handle_fan_command(self, command: dict) -> list:
        actions = []
        if self.state == State.EMERGENCY:
            actions.append({"type": "log_system", "level": "WARN", "msg": "Fan command refused: system in EMERGENCY"})
        return actions

    def handle_temperature(self, timestamp: float, temp: float) -> list:
        actions = []
        if self.state == State.EMERGENCY:
            return actions
        if timestamp - self.last_temp_save_time >= self.TEMP_SAVE_INTERVAL_SECONDS:
            self.last_temp_save_time = timestamp
            actions.append({"type": "save_temperature", "value": temp})
        return actions

    def handle_voice_command(self, command: str) -> list:
        actions = []
        if self.state == State.EMERGENCY or self.state != State.INSIDE:
            return actions
        actions.append({"type": "voice_control", "command": command})
        return actions

    def handle_web_fan(self, status: str, speed_level: str = "off") -> list:
        actions = []
        if self.state == State.EMERGENCY:
            return actions
        actions.append({"type": "set_fan", "status": status, "speed": speed_level})
        return actions

    def handle_register_card(self, card_id: str, name: str) -> list:
        return [{"type": "register_card", "card_id": card_id, "name": name}]
