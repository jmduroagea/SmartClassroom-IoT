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

    def handle_emergency(self, event: dict) -> list:
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
