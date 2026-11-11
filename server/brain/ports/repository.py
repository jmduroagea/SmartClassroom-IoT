from typing import Protocol, Optional, Dict, Any

class RepositoryPort(Protocol):
    def find_user_by_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Finds a user by their RFID card ID."""
        ...

    def log_access(self, card_id: str, access_type: str, ts: str) -> None:
        """Logs access events (in/out/denied/occupied) for the web interface."""
        ...

    def log_system(self, event: str, device: str, detail: str, ts: str) -> None:
        """Logs general system events."""
        ...

    def log_env(self, temperature: float, ts: str) -> None:
        """Logs environment temperature readings."""
        ...

    def log_fan(self, speed: int, ts: str) -> None:
        """Logs fan state changes."""
        ...

    def log_motion(self, detected: bool, ts: str) -> None:
        """Logs PIR motion sensor events."""
        ...

    def log_emergency(self, status: str, ts: str) -> None:
        """Logs emergency events."""
        ...
