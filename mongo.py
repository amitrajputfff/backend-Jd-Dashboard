"""Async MongoDB connection using Motor.

Three logical databases on the same server (192.168.13.65):
  - voicebot_platform  : call_logs (existing — do not rename)
  - no_code_platform   : assistants + counters (agent config)
  - ai_lead_qualify    : call_transcripts (written by bot + callback worker)
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


def get_analysis_prompts_col():
    """Standalone analysis prompts — independent of any specific assistant.
    Future: an assistant_prompt_map collection will link assistants → prompt_id.
    """
    return _get_client()["no_code_platform"]["analysis_prompts"]


# ── no_code_platform — workflow bots ────────────────────────────────────────

def get_workflow_bots_col():
    """Visual workflow bot configs — separate from plain assistants."""
    return _get_client()["no_code_platform"]["workflow_bots"]


# ── no_code_platform — dashboard login accounts ─────────────────────────────

def get_users_col():
    """Dashboard login accounts — see backend/routers/auth.py. Minimal real
    auth: email + bcrypt password hash, no OAuth/sessions/email-verification
    (those frontend authApi methods stay unused — see auth.py's module
    docstring for the exact scope decision)."""
    return _get_client()["no_code_platform"]["users"]


# ── ai_lead_qualify — call transcripts + analysis ────────────────────────────

def get_transcripts_col():
    """call_transcripts written by bot.py and tagged by callback_worker."""
    return _get_client()["ai_lead_qualify"]["call_transcripts"]


async def next_sequence(name: str) -> int:
    """Atomically increment and return the next integer for `name`."""
    doc = await get_counters_col().find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["seq"]
