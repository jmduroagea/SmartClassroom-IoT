from typing import Protocol, Optional, Dict, Any
from datetime import datetime

class RepositoryPort(Protocol):
    def find_user_by_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Finds a user by their RFID card ID."""
        ...

    def save_user(self, card_id: str, name: str) -> None:
        """Saves or registers a new user card."""
        ...

    def log_access(self, card_id: str, access_type: str, name: Optional[str], ts: datetime) -> None:
        """Logs access events with name and datetime timestamp."""
        ...

    def log_system(self, event: str, device: str, detail: str, ts: datetime) -> None:
        """Logs general system events."""
        ...

    def log_env(self, temp: float, ts: datetime) -> None:
        """Logs environment temperature readings in the 'env' collection."""
        ...

    def log_fan(self, speed: int, ts: datetime) -> None:
        """Logs fan state changes."""
        ...

    def log_motion(self, detected: bool, ts: datetime) -> None:
        """Logs PIR motion sensor events."""
        ...
