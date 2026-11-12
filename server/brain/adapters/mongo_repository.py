import logging
from typing import Optional, Dict, Any
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from server.brain.ports.repository import RepositoryPort

logger = logging.getLogger(__name__)

class MongoRepository(RepositoryPort):
    """Production MongoDB repository adapter implementing RepositoryPort."""

    def __init__(self, config):
        self.client = MongoClient(config.mongo_uri, serverSelectionTimeoutMS=2000)
        self.db = self.client[config.mongo_db]
        # Exact collection names expected by web and setup_db.py
        self.users_col = self.db["users"]
        self.access_col = self.db["access_log"]
        self.system_col = self.db["system_log"]
        self.env_col = self.db["env"]
        self.fan_col = self.db["fan_log"]
        self.motion_col = self.db["motion_log"]
        self.emergencies_col = self.db["emergencies"]

    def find_user_by_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self.users_col.find_one({"card_id": card_id}, {"_id": 0})
        except PyMongoError as e:
            logger.error(f"MongoDB error in find_user_by_card (T12): {e}")
            return None

    def save_user(self, card_id: str, name: str) -> None:
        try:
            self.users_col.update_one(
                {"card_id": card_id},
                {"$set": {"card_id": card_id, "name": name}},
                upsert=True
            )
        except PyMongoError as e:
            logger.error(f"MongoDB error in save_user (T12): {e}")

    def log_access(self, card_id: str, access_type: str, name: Optional[str], ts: datetime) -> None:
        try:
            self.access_col.insert_one({
                "card_id": card_id,
                "type": access_type,
                "name": name,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_access (T12): {e}")

    def log_system(self, event: str, device: str, detail: str, ts: datetime) -> None:
        try:
            self.system_col.insert_one({
                "event": event,
                "device": device,
                "detail": detail,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_system (T12): {e}")

    def log_env(self, temp: float, ts: datetime) -> None:
        try:
            self.env_col.insert_one({
                "temp": temp,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_env (T12): {e}")

    def log_fan(self, speed: int, ts: datetime) -> None:
        try:
            self.fan_col.insert_one({
                "speed": speed,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_fan (T12): {e}")

    def log_motion(self, detected: bool, ts: datetime) -> None:
        try:
            self.motion_col.insert_one({
                "detected": detected,
                "ts": ts
            })
        except PyMongoError as e:
            logger.error(f"MongoDB error in log_motion (T12): {e}")

    def create_emergency(self, emergency_id: str, record: Dict[str, Any]) -> None:
        try:
            self.emergencies_col.insert_one({"_id": emergency_id, **record})
        except PyMongoError as e:
            logger.error(f"MongoDB error in create_emergency (T12): {e}")

    def add_emergency_reading(self, emergency_id: str, temp: float, ts: datetime) -> None:
        self._update_emergency(emergency_id, {"$push": {"readings": {"ts": ts, "temp": temp}}}, "add_emergency_reading")

    def add_emergency_call(self, emergency_id: str, reason: str, ts: datetime) -> None:
        self._update_emergency(emergency_id, {"$push": {"calls": {"ts": ts, "reason": reason}}}, "add_emergency_call")

    def mark_evacuated(self, emergency_id: str, ts: datetime) -> None:
        self._update_emergency(emergency_id, {"$set": {"evacuated_at": ts}}, "mark_evacuated")

    def mark_not_evacuated(self, emergency_id: str) -> None:
        self._update_emergency(emergency_id, {"$set": {"not_evacuated_alert": True}}, "mark_not_evacuated")

    def close_emergency(self, emergency_id: str, ts: datetime) -> None:
        self._update_emergency(emergency_id, {"$set": {"ended_at": ts}}, "close_emergency")

    def _update_emergency(self, emergency_id: str, update: Dict[str, Any], operation: str) -> None:
        try:
            self.emergencies_col.update_one({"_id": emergency_id}, update)
        except PyMongoError as e:
            logger.error(f"MongoDB error in {operation} (T12): {e}")
