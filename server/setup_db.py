#!/usr/bin/env python3
"""
Creates the SmartClassroom database: indexes + test users.
Safe to run several times.

Usage:
    MONGO_URI=mongodb://localhost:27017 python3 setup_db.py
    python3 setup_db.py --user CARD_GLORIA Gloria --user CARD_IGNACIO Ignacio
"""
import argparse
import os
from datetime import datetime

from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "smartroom")

DEFAULT_USERS = [
    ("CARD_GLORIA", "Gloria"),
    ("CARD_IGNACIO", "Ignacio"),
    ("CARD_JOSEMARIA", "Jose Maria"),
]

parser = argparse.ArgumentParser()
parser.add_argument("--user", nargs=2, action="append", metavar=("CARD_ID", "NAME"),
                    help="add a user (repeat for several)")
args = parser.parse_args()

db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)[DB_NAME]

db.users.create_index([("card_id", ASCENDING)], unique=True)
for name in ("access_log", "env", "motion_log", "fan_log", "system_log"):
    db[name].create_index([("ts", ASCENDING)])
db.emergencies.create_index([("started_at", ASCENDING)])

for card_id, name in args.user or DEFAULT_USERS:
    try:
        db.users.insert_one({"card_id": card_id, "name": name, "created_at": datetime.now()})
        print(f"added {card_id} -> {name}")
    except DuplicateKeyError:
        print(f"{card_id} already exists")

print("collections:", sorted(db.list_collection_names()))
