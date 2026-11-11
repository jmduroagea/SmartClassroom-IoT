from typing import Optional, Dict, Any, List


class FakeRepository:
    """In-memory repository test double implementing RepositoryPort."""

    def __init__(self, initial_users: List[Dict[str, Any]] = None):
        self.users = initial_users or [
            {"card_id": "CARD_GLORIA", "name": "Gloria"},
            {"card_id": "CARD_JOSE", "name": "Jose"},
            {"card_id": "CARD_IGNACIO", "name": "Ignacio"}
        ]
        self.access_logs: List[Dict[str, Any]] = []
        self.system_logs: List[Dict[str, Any]] = []
        self.env_logs: List[Dict[str, Any]] = []
        self.fan_logs: List[Dict[str, Any]] = []
        self.motion_logs: List[Dict[str, Any]] = []
        self.emergency_logs: List[Dict[str, Any]] = []

    def find_user_by_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Finds a user by their card ID in memory."""
        for user in self.users:
            if user.get("card_id") == card_id:
                return user
        return None

    def log_access(self, card_id: str, access_type: str, ts: str) -> None:
        """Logs an access event in memory."""
        self.access_logs.append({
            "card_id": card_id,
            "type": access_type,
            "ts": ts
        })

    def log_system(self, event: str, device: str, detail: str, ts: str) -> None:
        """Logs a system event in memory."""
        self.system_logs.append({
            "event": event,
            "device": device,
            "detail": detail,
            "ts": ts
        })

    def log_env(self, temperature: float, ts: str) -> None:
        """Logs an environment reading in memory."""
        self.env_logs.append({
            "temperature": temperature,
            "ts": ts
        })

    def log_fan(self, speed: int, ts: str) -> None:
        """Logs a fan speed change in memory."""
        self.fan_logs.append({
            "speed": speed,
            "ts": ts
        })

    def log_motion(self, detected: bool, ts: str) -> None:
        """Logs a motion sensor event in memory."""
        self.motion_logs.append({
            "detected": detected,
            "ts": ts
        })

    def log_emergency(self, status: str, ts: str) -> None:
        """Logs an emergency event in memory."""
        self.emergency_logs.append({
            "status": status,
            "ts": ts
        })
