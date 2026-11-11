from typing import Optional, Dict, Any, List
from datetime import datetime
from server.brain.ports.repository import RepositoryPort

class FakeRepository(RepositoryPort):
    """In-memory repository test double implementing RepositoryPort without hardcoded users."""

    def __init__(self, initial_users: List[Dict[str, Any]] = None):
        self.users: List[Dict[str, Any]] = initial_users or []
        self.access_logs: List[Dict[str, Any]] = []
        self.system_logs: List[Dict[str, Any]] = []
        self.env_logs: List[Dict[str, Any]] = []
        self.fan_logs: List[Dict[str, Any]] = []
        self.motion_logs: List[Dict[str, Any]] = []

    def find_user_by_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        for user in self.users:
            if user.get("card_id") == card_id:
                return user
        return None

    def save_user(self, card_id: str, name: str) -> None:
        for user in self.users:
            if user.get("card_id") == card_id:
                user["name"] = name
                return
        self.users.append({"card_id": card_id, "name": name})

    def log_access(self, card_id: str, access_type: str, name: Optional[str], ts: datetime) -> None:
        self.access_logs.append({
            "card_id": card_id,
            "type": access_type,
            "name": name,
            "ts": ts
        })

    def log_system(self, event: str, device: str, detail: str, ts: datetime) -> None:
        self.system_logs.append({
            "event": event,
            "device": device,
            "detail": detail,
            "ts": ts
        })

    def log_env(self, temp: float, ts: datetime) -> None:
        self.env_logs.append({
            "temp": temp,
            "ts": ts
        })

    def log_fan(self, speed: int, ts: datetime) -> None:
        self.fan_logs.append({
            "speed": speed,
            "ts": ts
        })

    def log_motion(self, detected: bool, ts: datetime) -> None:
        self.motion_logs.append({
            "detected": detected,
            "ts": ts
        })
