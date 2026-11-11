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

    def __init__(self, clock):
        self.clock = clock
        self.state = State.IDLE
        self.failed_attempts = 0
        self.current_user_card = None
        self.last_temp_save_time = 0.0
        self.last_known_temp = 0.0
        self.current_timer = None

    def _cancel_timer(self):
        if self.current_timer:
            self.current_timer.cancel()
            self.current_timer = None

    def handle_pir(self) -> list:
        actions = []
        if self.state == State.IDLE:
            self.state = State.WAITING_CARD
            self._cancel_timer()
            # 1. Se programa el primer timer pasando la función (callback), no un string
            self.current_timer = self.clock.schedule(self.TIMER_PROMPT_DELAY, self._prompt)
        return actions

    def _prompt(self) -> list:
        if self.state != State.WAITING_CARD:
            return []
        # 2. El aviso programa el recordatorio
        self.current_timer = self.clock.schedule(self.TIMER_REMINDER_DELAY, self._reminder)
        return [{"type": "say", "text": "scan your card"}]

    def _reminder(self) -> list:
        if self.state != State.WAITING_CARD:
            return []
        # 3. El recordatorio programa el timeout
        self.current_timer = self.clock.schedule(self.TIMER_TIMEOUT_DELAY, self._timeout)
        return [{"type": "say", "text": "Reminder: scan your card"}]

    def _timeout(self) -> list:
        if self.state != State.WAITING_CARD:
            return []
        self.state = State.IDLE
        self.current_timer = None
        return [{"type": "set_led", "color": "green", "mode": "off"}]

    def handle_card(self, card_id: str, is_known: bool, user_name: str = None) -> list:
        actions = []
        if self.state == State.EMERGENCY:
            return actions

        if self.state == State.LOCKED:
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "denied", "card_id": card_id})
            return actions

        # Si llega una tarjeta, se cancelan los timers de espera pendientes
        self._cancel_timer()

        if not is_known:
            self.failed_attempts += 1
            actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
            actions.append({"type": "denied", "card_id": card_id})
            actions.append({"type": "say", "text": "Card not recognized."})

            if self.failed_attempts >= self.MAX_FAILED_ATTEMPTS:
                self.state = State.LOCKED
                actions.append({"type": "say", "text": "System locked"})
            else:
                self.state = State.IDLE
            return actions

        self.failed_attempts = 0
        if self.state in (State.WAITING_CARD, State.IDLE):
            self.state = State.INSIDE
            self.current_user_card = card_id  # Guardamos y comparamos IDs, no nombres
            name_str = user_name or "User"

            actions.append({"type": "say", "text": f"Welcome, {name_str}. The temperature is {self.last_known_temp} degrees."})
            actions.append({"event_type": "in", "card_id": card_id})
            actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
            # Entry actions: PIR off, Mic on (con booleanos)
            actions.append({"type": "set_pir", "enabled": False})
            actions.append({"type": "set_mic", "enabled": True})

        elif self.state == State.INSIDE:
            if self.current_user_card == card_id:
                self.state = State.IDLE
                self.current_user_card = None
                actions.append({"event_type": "out", "card_id": card_id})
                actions.append({"type": "set_led", "color": "green", "mode": "pulse"})
                # Exit actions: Fan a 0, Mic off, PIR on
                actions.append({"type": "set_fan", "speed": 0})
                actions.append({"type": "set_mic", "enabled": False})
                actions.append({"type": "set_pir", "enabled": True})
            else:
                actions.append({"type": "set_led", "color": "red", "mode": "pulse"})
                actions.append({"type": "occupied", "card_id": card_id})
                actions.append({"type": "say", "text": "Room occupied."})

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
        self._cancel_timer()
        return [
            {"type": "set_fan", "speed": 0, "locked": True},
            {"type": "set_led", "color": "red", "mode": "blink"},
            {"type": "set_alarm", "interval_seconds": self.ALARM_INTERVAL_SECONDS},
            {"type": "set_mic", "enabled": True},
            {"type": "set_pir", "enabled": False},
            {"type": "publish", "topic": "glo/alert/units", "payload": {"status": "EMERGENCY_TRIGGERED"}}
        ]

    def handle_fan_command(self, command: dict) -> list:
        if self.state == State.EMERGENCY:
            return []
        return []

    def handle_temperature(self, timestamp: float, temp: float) -> list:
        actions = []
        self.last_known_temp = temp
        if self.state == State.EMERGENCY:
            return actions
        if timestamp - self.last_temp_save_time >= self.TEMP_SAVE_INTERVAL_SECONDS:
            self.last_temp_save_time = timestamp
            actions.append({"type": "save_temperature", "value": temp})
        return actions

    def handle_voice_command(self, command: str) -> list:
        if self.state == State.EMERGENCY or self.state != State.INSIDE:
            return []
        return [{"type": "voice_control", "command": command}]

    def handle_web_fan(self, speed_level: int = 0) -> list:
        if self.state == State.EMERGENCY:
            return []
        return [{"type": "set_fan", "speed": speed_level}]

    def handle_register_card(self, card_id: str, name: str) -> list:
        return [{"type": "register_card", "card_id": card_id, "name": name}]
