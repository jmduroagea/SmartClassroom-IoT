import logging
from common.messages import FAN_SPEEDS

logger = logging.getLogger(__name__)

class State:
    IDLE = "IDLE"
    WAITING_CARD = "WAITING_CARD"
    INSIDE = "INSIDE"
    LOCKED = "LOCKED"
    OFF = "OFF"
    OCCUPIED = "OCCUPIED"
    EMERGENCY = "EMERGENCY"

class StateMachine:
    """Pure domain state machine supporting Use Case 1, Emergency, and Fan Control (#67)."""

    def __init__(self, clock=None, emit=None):
        self.clock = clock
        self.emit = emit
        self.state = State.OFF
        self.occupied_user = None
        self.fan_speed = 0

    def process_card_scan(self, card_id: str, user_name: str | None = None) -> list[dict]:
        actions = []

        if self.state in (State.OFF, State.IDLE):
            if user_name:
                self.state = State.OCCUPIED if self.state == State.OFF else State.INSIDE
                self.occupied_user = user_name
                actions.append({"type": "say", "text": f"Welcome, {user_name}!"})
                actions.append({
                    "type": "log_access",
                    "event_type": "entry",
                    "card_id": card_id,
                    "name": user_name
                })
            else:
                actions.append({"type": "say", "text": "Access denied"})
                actions.append({
                    "type": "log_system",
                    "level": "WARNING",
                    "msg": f"Access denied for card: {card_id}"
                })

        elif self.state in (State.OCCUPIED, State.INSIDE):
            if user_name and user_name == self.occupied_user:
                self.state = State.OFF
                self.occupied_user = None
                self.fan_speed = 0
                actions.append({"type": "say", "text": f"Goodbye, {user_name}!"})
                actions.append({
                    "type": "log_access",
                    "event_type": "exit",
                    "card_id": card_id,
                    "name": user_name
                })
            else:
                actions.append({"type": "say", "text": "Access denied"})
                actions.append({
                    "type": "log_system",
                    "level": "WARNING",
                    "msg": f"Access denied for card: {card_id}"
                })

        elif self.state == State.EMERGENCY:
            actions.append({"type": "say", "text": "Emergency in progress"})

        return actions

    def handle_emergency(self, payload: dict | None = None) -> list[dict]:
        """Trigger emergency transition from any state."""
        self.state = State.EMERGENCY
        return [
            {"type": "emergency", "active": True},
            {"type": "set_fan", "locked": True}
        ]

    def handle_fan_command(self, payload: dict | None = None) -> list[dict]:
        """Handle legacy/direct fan commands, strictly refused during EMERGENCY."""
        if self.state == State.EMERGENCY:
            return []
        return []

    def process_voice_command(self, command: str) -> list[dict]:
        actions = []
        cmd = command.strip().lower()

        if self.state == State.EMERGENCY:
            return actions

        speeds = list(FAN_SPEEDS) if not isinstance(FAN_SPEEDS, dict) else list(FAN_SPEEDS.values())

        if cmd == "hot":
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

        elif cmd == "cold":
            if self.fan_speed == 0:
                actions.append({"type": "say", "text": "The fan is already off."})
            else:
                current_index = speeds.index(self.fan_speed)
                self.fan_speed = speeds[current_index - 1]
                actions.append({"type": "set_fan", "speed": self.fan_speed})

        return actions
