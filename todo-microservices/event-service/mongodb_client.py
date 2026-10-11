import os
from pymongo import MongoClient

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_USER = os.getenv("MONGO_INITDB_ROOT_USERNAME", "eventuser")
MONGO_PASSWORD = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "eventpass")

MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:27017/?authSource=admin"
client = MongoClient(MONGO_URI)
db = client["eventdb"]
events_collection = db["events"]