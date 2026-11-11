import unittest
from unittest.mock import MagicMock, patch
from pymongo.errors import PyMongoError
from server.brain.adapters.fake_repository import FakeRepository
from server.brain.adapters.mongo_repository import MongoRepository


class TestFakeRepository(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()

    def test_find_user_by_card(self):
        user = self.repo.find_user_by_card("CARD_GLORIA")
        self.assertIsNotNone(user)
        self.assertEqual(user["name"], "Gloria")

        unknown = self.repo.find_user_by_card("UNKNOWN")
        self.assertIsNone(unknown)

    def test_log_access(self):
        self.repo.log_access("CARD_GLORIA", "in", "2026-11-11T12:00:00")
        self.assertEqual(len(self.repo.access_logs), 1)
        self.assertEqual(self.repo.access_logs[0]["type"], "in")
        self.assertEqual(self.repo.access_logs[0]["card_id"], "CARD_GLORIA")

    def test_log_system(self):
        self.repo.log_system("EVENT", "device", "detail", "2026-11-11T12:00:00")
        self.assertEqual(len(self.repo.system_logs), 1)
        self.assertEqual(self.repo.system_logs[0]["event"], "EVENT")

    def test_log_env(self):
        self.repo.log_env(22.5, "2026-11-11T12:00:00")
        self.assertEqual(len(self.repo.env_logs), 1)
        self.assertEqual(self.repo.env_logs[0]["temperature"], 22.5)

    def test_log_fan(self):
        self.repo.log_fan(2, "2026-11-11T12:00:00")
        self.assertEqual(len(self.repo.fan_logs), 1)
        self.assertEqual(self.repo.fan_logs[0]["speed"], 2)

    def test_log_motion(self):
        self.repo.log_motion(True, "2026-11-11T12:00:00")
        self.assertEqual(len(self.repo.motion_logs), 1)
        self.assertTrue(self.repo.motion_logs[0]["detected"])

    def test_log_emergency(self):
        self.repo.log_emergency("TRIGGERED", "2026-11-11T12:00:00")
        self.assertEqual(len(self.repo.emergency_logs), 1)
        self.assertEqual(self.repo.emergency_logs[0]["status"], "TRIGGERED")


class TestMongoRepositoryT12ErrorHandling(unittest.TestCase):
    @patch("server.brain.adapters.mongo_repository.MongoClient")
    @patch("server.brain.adapters.mongo_repository.load_config")
    def test_mongo_error_handling_t12(self, mock_load_config, mock_client_class):
        """Verifies requirement T12: MongoDB failures are caught and never crash the brain."""
        mock_config = MagicMock()
        mock_config.mongo_uri = "mongodb://localhost:27017"
        mock_config.mongo_db = "smartroom"
        mock_load_config.return_value = mock_config

        # Force a PyMongoError on database operations
        mock_db = mock_client_class.return_value.__getitem__.return_value
        mock_collection = mock_db.__getitem__.return_value
        mock_collection.insert_one.side_effect = PyMongoError("Simulated DB Crash")
        mock_collection.find_one.side_effect = PyMongoError("Simulated DB Crash")

        repo = MongoRepository()

        # None of these calls should raise an exception, fulfilling T12
        try:
            repo.log_access("CARD_GLORIA", "in", "2026-11-11T12:00:00")
            repo.log_system("TEST", "dev", "det", "2026-11-11T12:00:00")
            repo.log_env(21.0, "2026-11-11T12:00:00")
            repo.log_fan(1, "2026-11-11T12:00:00")
            repo.log_motion(False, "2026-11-11T12:00:00")
            repo.log_emergency("ACTIVE", "2026-11-11T12:00:00")

            user = repo.find_user_by_card("CARD_GLORIA")
            self.assertIsNone(user)
        except Exception as e:
            self.fail(f"MongoRepository raised an exception on database failure, violating T12: {e}")
