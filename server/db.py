import os
from datetime import datetime, timezone

import gridfs
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10000, tz_aware=True)
db = client[os.environ.get("MONGODB_DB", "accident_detection")]

users = db["users"]
downloads = db["downloads"]  # one document per click on the website's download button
attempts = db["auth_attempts"]  # failed logins / sign-ups, to slow down password guessing (auto-deleted)
# Images and videos live in GridFS (bucket "media"): the bytes in media.chunks,
# the owner / kind / capture time in media.files.metadata
media = gridfs.GridFSBucket(db, bucket_name="media")
media_files = db["media.files"]


def now():
    return datetime.now(timezone.utc)


def init_db(hash_password):
    users.create_index([("username_lower", ASCENDING)], unique=True)
    media_files.create_index([("metadata.owner_id", ASCENDING), ("metadata.kind", ASCENDING), ("uploadDate", DESCENDING)])
    media_files.create_index([("metadata.captured_at", DESCENDING)])
    downloads.create_index([("at", DESCENDING)])
    downloads.create_index([("visitor", ASCENDING), ("at", DESCENDING)])
    attempts.create_index([("key", ASCENDING), ("at", DESCENDING)])
    attempts.create_index([("at", ASCENDING)], expireAfterSeconds=24 * 3600)  # MongoDB deletes them after a day

    # First start: create the admin account from .env so someone can manage the others
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if username and password and users.count_documents({"role": "admin"}) == 0:
        users.update_one(
            {"username_lower": username.lower()},
            {"$set": {"role": "admin"},
             "$setOnInsert": {"username": username, "username_lower": username.lower(),
                              "password_hash": hash_password(password), "created_at": now(), "last_login": None}},
            upsert=True,
        )
