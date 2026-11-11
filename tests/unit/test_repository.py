import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from pymongo.errors import PyMongoError
from server.brain.adapters.fake_repository import FakeRepository
from server.brain.adapters.mongo_repository import MongoRepository

class TestFakeRepository(unittest.TestCase):
    def test_user_lookup_and_save(self):
        repo = FakeRepository()
        self.assertIsNone(repo.find_user_by_card("CARD_TEST"))

        repo.save_user("CARD_TEST", "Test User")
        user = repo.find_user_by_card("CARD_TEST")
        self.assertEqual(user["name"], "Test User")

    def test_logging_methods(self):
        repo = FakeRepository()
        now = datetime.now(timezone.utc)

        repo.log_access("CARD_1", "in", "Gloria", now)
        repo.log_env(23.5, now)

        self.assertEqual(len(repo.access_logs), 1)
        self.assertEqual(repo.access_logs[0]["name"], "Gloria")
        self.assertEqual(repo.access_logs[0]["type"], "in")

        self.assertEqual(len(repo.env_logs), 1)
        self.assertEqual(repo.env_logs[0]["temp"], 23.5)

class TestMongoRepositoryMock(unittest.TestCase):
    @patch("server.brain.adapters.mongo_repository.MongoClient")
    def test_mongo_insert_documents_shape(self, mock_client_class):
        mock_db = MagicMock()
        collections = {}
        mock_db.__getitem__.side_effect = lambda name: collections.setdefault(name, MagicMock())
        mock_client_class.return_value.__getitem__.return_value = mock_db

        config = MagicMock()
        config.mongo_uri = "mongodb://localhost:27017"
        config.mongo_db = "smartroom"

        repo = MongoRepository(config)
        now = datetime.now(timezone.utc)

        # Test log_access exact document fields (type, name, ts as datetime)
        repo.log_access("CARD_1", "in", "Gloria", now)
        collections["access_log"].insert_one.assert_called_once_with({
            "card_id": "CARD_1",
            "type": "in",
            "name": "Gloria",
            "ts": now
        })

        # Test log_env exact collection 'env' and field 'temp'
        repo.log_env(21.0, now)
        collections["env"].insert_one.assert_called_once_with({
            "temp": 21.0,
            "ts": now
        })

    @patch("server.brain.adapters.mongo_repository.MongoClient")
    def test_mongo_error_handling_t12(self, mock_client_class):
        mock_db = MagicMock()
        collections = {}
        mock_db.__getitem__.side_effect = lambda name: collections.setdefault(name, MagicMock())
        mock_client_class.return_value.__getitem__.return_value = mock_db

        collections["env"] = MagicMock()
        collections["env"].insert_one.side_effect = PyMongoError("Connection lost")

        config = MagicMock()
        config.mongo_uri = "mongodb://localhost:27017"
        config.mongo_db = "smartroom"

        repo = MongoRepository(config)

        # Should catch PyMongoError, log it, and never crash the brain (T12)
        with self.assertLogs("server.brain.adapters.mongo_repository", level="ERROR") as log:
            repo.log_env(22.0, datetime.now(timezone.utc))
            self.assertTrue(any("MongoDB error in log_env" in message for message in log.output))
