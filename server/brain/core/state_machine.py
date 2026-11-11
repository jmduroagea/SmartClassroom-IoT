from enum import Enum

class State(Enum):
    IDLE = "IDLE"
    WAITING_CARD = "WAITING_CARD"
    INSIDE = "INSIDE"
    LOCKED = "LOCKED"
    EMERGENCY = "EMERGENCY"

class StateMachine:
    def __init__(self):
        self.state = State.IDLE
        self.failed_attempts = 0
        self.current_user = None
        self.last_temp_save_time = 0.0

    def handle_card(self, card_id: str, is_known: bool) -> list:
        if self.state == State.EMERGENCY:
            return []
            
        if self.state == State.LOCKED:
            return [
                {"type": "set_led", "color": "red", "mode": "pulse"},
                {"type": "log_system", "level": "WARN", "msg": f"Access denied (LOCKED) for {card_id}"}
            ]
            
        if not is_known:
            self.failed_attempts += 1
            actions = [
                {"type": "set_led", "color": "red", "mode": "pulse"},
                {"type": "log_system", "level": "WARN", "msg": f"Access denied (UNKNOWN) for {card_id}"}
            ]
            if self.failed_attempts >= 3:
                self.state = State.LOCKED
                actions.append({"type": "say", "text": "System locked"})
            return actions

        if self.state == State.IDLE:
            self.state = State.INSIDE
            self.current_user = card_id
            self.failed_attempts = 0
            return [{"type": "set_led", "color": "green", "mode": "pulse"}]
            
        if self.state == State.INSIDE:
            if self.current_user == card_id:
                self.state = State.IDLE
                self.current_user = None
                return [{"type": "set_led", "color": "green", "mode": "pulse"}]
            else:
                return [
                    {"type": "set_led", "color": "red", "mode": "pulse"},
                    {"type": "log_system", "level": "WARN", "msg": f"Access denied (OCCUPIED) for {card_id}"}
                ]
        return []

    def process_card_scan(self, card_id: str, user_name: str = None) -> list:
        is_known = user_name is not None or card_id in ["CARD_GLORIA", "CARD_JOSE", "CARD_IGNACIO"]
        actions = []
        if is_known and self.state == State.IDLE and user_name:
            actions.append({"type": "say", "text": f"Welcome, {user_name}"})
            actions.append({"event_type": "in", "card_id": card_id})
        elif is_known and self.state == State.INSIDE and self.current_user == card_id:
            if user_name:
                actions.append({"type": "say", "text": f"Goodbye, {user_name}"})
            actions.append({"event_type": "out", "card_id": card_id})
            
        actions.extend(self.handle_card(card_id, is_known))
        return actions

    def unlock(self) -> list:
        if self.state == State.LOCKED:
            self.state = State.IDLE
            self.failed_attempts = 0
            return [
                {"type": "set_led", "color": "green", "mode": "solid"}
            ]
        return []

    def handle_temperature(self, timestamp: float, temp: float) -> list:
        if self.state == State.EMERGENCY:
            return []
        if timestamp - self.last_temp_save_time >= 10.0:
            self.last_temp_save_time = timestamp
            return [{"type": "save_temperature", "value": temp}]
        return []

    def handle_voice_command(self, command: str) -> list:
        if self.state == State.EMERGENCY or self.state != State.INSIDE:
            return []
        return [{"type": "voice_control", "command": command}]

    def handle_web_fan(self, status: str, level: int = 0) -> list:
        if self.state == State.EMERGENCY:
            return []
        return [{"type": "set_fan", "status": status, "level": level}]

    def handle_register_card(self, card_id: str) -> list:
        return [{"type": "register_card", "card_id": card_id}]

    def handle_emergency(self, event: dict = None) -> list:
        self.state = State.EMERGENCY
        return [
            {"type": "set_fan", "status": "stopped", "locked": True},
            {"type": "set_led", "mode": "blinking"},
            {"type": "set_alarm", "interval_seconds": 3},
            {"type": "set_mic", "status": "on"},
            {"type": "set_pir", "status": "off"},
            {"type": "publish", "topic": "glo/alert/units", "payload": "EMERGENCY_TRIGGERED"}
        ]
        
    def handle_fan_command(self, command: dict) -> list:
        if self.state == State.EMERGENCY:
            return [{"type": "log_system", "level": "WARN", "msg": "Fan command refused: system in EMERGENCY"}]
        return []
