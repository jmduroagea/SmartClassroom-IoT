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


# --- Emergency records (#23) -----------------------------------------------------

EMERGENCY_ID = "em-20261112T131500"
RECORD = {
    "started_at": datetime(2026, 11, 12, 13, 15, tzinfo=timezone.utc),
    "ended_at": None,
    "trigger": "rate",
    "trigger_temp": 41.5,
    "person": {"card_id": "CARD_1", "name": "Gloria"},
    "evacuated_at": None,
    "not_evacuated_alert": False,
    "units_notified_at": datetime(2026, 11, 12, 13, 15, tzinfo=timezone.utc),
    "calls": [],
    "readings": [],
}


class TestFakeRepositoryEmergencies(unittest.TestCase):
    def test_the_record_grows_with_readings_calls_and_evacuation(self):
        repo = FakeRepository()
        now = datetime.now(timezone.utc)
        repo.create_emergency(EMERGENCY_ID, {**RECORD, "calls": [], "readings": []})
        repo.add_emergency_reading(EMERGENCY_ID, 42.0, now)
        repo.add_emergency_call(EMERGENCY_ID, "help", now)
        repo.mark_evacuated(EMERGENCY_ID, now)
        repo.mark_not_evacuated(EMERGENCY_ID)

        record = repo.emergencies[EMERGENCY_ID]
        self.assertEqual(record["_id"], EMERGENCY_ID)
        self.assertEqual(record["readings"], [{"ts": now, "temp": 42.0}])
        self.assertEqual(record["calls"], [{"ts": now, "reason": "help"}])
        self.assertEqual(record["evacuated_at"], now)
        self.assertTrue(record["not_evacuated_alert"])


class TestMongoRepositoryEmergencies(unittest.TestCase):
    def setUp(self):
        patcher = patch("server.brain.adapters.mongo_repository.MongoClient")
        mock_client_class = patcher.start()
        self.addCleanup(patcher.stop)
        mock_db = MagicMock()
        self.collections = {}
        mock_db.__getitem__.side_effect = lambda name: self.collections.setdefault(name, MagicMock())
        mock_client_class.return_value.__getitem__.return_value = mock_db
        config = MagicMock()
        config.mongo_uri = "mongodb://localhost:27017"
        config.mongo_db = "smartroom"
        self.repo = MongoRepository(config)
        self.emergencies = self.collections["emergencies"]

    def test_create_uses_the_emergency_id_as_the_document_id(self):
        self.repo.create_emergency(EMERGENCY_ID, RECORD)
        self.emergencies.insert_one.assert_called_once_with({"_id": EMERGENCY_ID, **RECORD})

    def test_a_reading_is_pushed_into_the_record(self):
        now = datetime.now(timezone.utc)
        self.repo.add_emergency_reading(EMERGENCY_ID, 42.0, now)
        self.emergencies.update_one.assert_called_once_with(
            {"_id": EMERGENCY_ID}, {"$push": {"readings": {"ts": now, "temp": 42.0}}}
        )

    def test_a_call_is_pushed_into_the_record(self):
        now = datetime.now(timezone.utc)
        self.repo.add_emergency_call(EMERGENCY_ID, "not_evacuated", now)
        self.emergencies.update_one.assert_called_once_with(
            {"_id": EMERGENCY_ID}, {"$push": {"calls": {"ts": now, "reason": "not_evacuated"}}}
        )

    def test_evacuation_and_not_evacuated_are_set(self):
        now = datetime.now(timezone.utc)
        self.repo.mark_evacuated(EMERGENCY_ID, now)
        self.repo.mark_not_evacuated(EMERGENCY_ID)
        self.emergencies.update_one.assert_any_call({"_id": EMERGENCY_ID}, {"$set": {"evacuated_at": now}})
        self.emergencies.update_one.assert_any_call({"_id": EMERGENCY_ID}, {"$set": {"not_evacuated_alert": True}})

    def test_a_database_error_is_logged_and_does_not_stop_the_brain(self):  # T12
        self.emergencies.update_one.side_effect = PyMongoError("Connection lost")
        with self.assertLogs("server.brain.adapters.mongo_repository", level="ERROR") as log:
            self.repo.add_emergency_reading(EMERGENCY_ID, 42.0, datetime.now(timezone.utc))
        self.assertTrue(any("add_emergency_reading" in message for message in log.output))
