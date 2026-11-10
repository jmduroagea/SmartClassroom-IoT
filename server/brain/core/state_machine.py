from enum import Enum
from typing import Optional, Dict, Any, List

class State(Enum):
    IDLE = "IDLE"
    WAITING_CARD = "WAITING_CARD"
    INSIDE = "INSIDE"
    LOCKED = "LOCKED"
    EMERGENCY = "EMERGENCY"

class StateMachine:
    def __init__(self):
        self.state = State.IDLE
        self.inside_card_id: Optional[str] = None
        self.inside_user_name: Optional[str] = None
        self.failed_attempts = 0

    def process_card_scan(self, card_id: str, user_name: Optional[str]) -> List[Dict[str, Any]]:
        actions = []

        if self.state == State.LOCKED:
            actions.append({"type": "say", "text": "System locked"})
            return actions

        if self.state == State.EMERGENCY:
            actions.append({"type": "say", "text": "Emergency in progress"})
            return actions

        if user_name is None:
            self.failed_attempts += 1
            actions.append({"type": "say", "text": "Card not recognized"})
            actions.append({"type": "log_system", "level": "WARN", "msg": f"Unrecognized card: {card_id}"})
            
            if self.failed_attempts >= 3:
                self.state = State.LOCKED
                actions.append({"type": "say", "text": "System locked"})
                actions.append({"type": "log_system", "level": "ERROR", "msg": "System locked after 3 failed attempts"})
            return actions

        self.failed_attempts = 0

        if self.state in (State.IDLE, State.WAITING_CARD):
            self.state = State.INSIDE
            self.inside_card_id = card_id
            self.inside_user_name = user_name
            actions.append({"type": "say", "text": f"Welcome, {user_name}"})
            actions.append({"type": "log_access", "event_type": "in", "card_id": card_id, "name": user_name})

        elif self.state == State.INSIDE:
            if self.inside_card_id == card_id:
                self.state = State.IDLE
                actions.append({"type": "say", "text": f"Goodbye, {user_name}"})
                actions.append({"type": "log_access", "event_type": "out", "card_id": card_id, "name": user_name})
                self.inside_card_id = None
                self.inside_user_name = None
            else:
                actions.append({"type": "say", "text": "Room occupied"})

        return actions

    def unlock(self) -> List[Dict[str, Any]]:
        actions = []
        if self.state == State.LOCKED:
            self.state = State.IDLE
            self.failed_attempts = 0
            actions.append({"type": "log_system", "level": "INFO", "msg": "System unlocked from web"})
        return actions
