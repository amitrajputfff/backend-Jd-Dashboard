"""Async MongoDB connection using Motor.

Two logical databases on the same server (192.168.13.65):
  - voicebot_platform  : call_logs (existing — do not rename)
  - no_code_platform   : assistants + counters (agent config, NEW)
"""

import os

from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")

_client: AsyncIOMotorClient | None = None


def _get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGODB_URL)
    return _client


# ── voicebot_platform — call logs ────────────────────────────────────────────

def get_call_logs_col():
    return _get_client()["voicebot_platform"]["call_logs"]


# ── no_code_platform — agent config ─────────────────────────────────────────

def get_assistants_col():
    return _get_client()["no_code_platform"]["assistants"]


def get_counters_col():
    """Auto-increment counters (used for integer `id` field on assistants)."""
    return _get_client()["no_code_platform"]["counters"]


async def next_sequence(name: str) -> int:
    """Atomically increment and return the next integer for `name`."""
    doc = await get_counters_col().find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["seq"]
