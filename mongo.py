"""Async MongoDB connection using Motor."""

import os

from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")
MONGODB_DB: str = os.getenv("MONGODB_DB", "voicebot_platform")

_client: AsyncIOMotorClient | None = None


def _get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGODB_URL)
    return _client


def get_mongo_db():
    return _get_client()[MONGODB_DB]


def get_call_logs_col():
    return get_mongo_db()["call_logs"]
