import logging
from typing import Optional, Dict, Any
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from common.config import load_config

logger = logging.getLogger(__name__)


class MongoRepository:
    """Production MongoDB implementation of RepositoryPort."""

    def __init__(self):
        try:
            config = load_config()
            # Support both object attributes and dictionary-like config access
            uri = getattr(config, "mongo_uri", None) or config.get("MONGO_URI")
            db_name = getattr(config, "mongo_db", None) or config.get("MONGO_DB", "smartroom")

            self.client = MongoClient(uri)
            self.db = self.client[db_name]

            self.users_col = self.db["users"]
            self.access_log_col = self.db["access_log"]
            self.system_log_col = self.db["system_log"]
            self.env_log_col = self.db["env_log"]
            self.fan_log_col = self.db["fan_log"]
            self.motion_log_col = self.db["motion_log"]
            self.emergency_log_col = self.db["emergency_log"]
        except Exception as e:
            logger.error(f"Failed to initialize MongoRepository: {e}")
            self.client = None
            self.db = None

    def find_user_by_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Finds a user by card ID from MongoDB."""
        try:
            if self.db is None:
                return None
            return self.users_col.find_one({"card_id": card_id}, {"_id": 0})
        except PyMongoError as e:
            logger.error(f"MongoDB error in find_user_by_card: {e}")
            return None

    def log_access(self, card_id: str, access_type: str, ts: str) -> None:
        """Logs access event with 'type' field required by the web interface."""
        try:
            if self.db is None:
                return
            self.access_log_col.insert_one({
                "card_id": card_id,
                "type": access_type,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_access (T12 handled): {e}")

    def log_system(self, event: str, device: str, detail: str, ts: str) -> None:
        """Logs system event with exact fields required by the web interface."""
        try:
            if self.db is None:
                return
            self.system_log_col.insert_one({
                "event": event,
                "device": device,
                "detail": detail,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_system (T12 handled): {e}")

    def log_env(self, temperature: float, ts: str) -> None:
        """Logs environmental temperature readings."""
        try:
            if self.db is None:
                return
            self.env_log_col.insert_one({
                "temperature": temperature,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_env (T12 handled): {e}")

    def log_fan(self, speed: int, ts: str) -> None:
        """Logs fan speed changes."""
        try:
            if self.db is None:
                return
            self.fan_log_col.insert_one({
                "speed": speed,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_fan (T12 handled): {e}")

    def log_motion(self, detected: bool, ts: str) -> None:
        """Logs PIR motion sensor events."""
        try:
            if self.db is None:
                return
            self.motion_log_col.insert_one({
                "detected": detected,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_motion (T12 handled): {e}")

    def log_emergency(self, status: str, ts: str) -> None:
        """Logs emergency state events."""
        try:
            if self.db is None:
                return
            self.emergency_log_col.insert_one({
                "status": status,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_emergency (T12 handled): {e}")
