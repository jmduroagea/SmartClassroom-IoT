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
