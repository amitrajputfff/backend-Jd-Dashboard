"""Async MongoDB connection using Motor.

Three logical databases on the same server (192.168.13.65):
  - voicebot_platform    : call_logs (existing — do not rename)
  - no_code_platform     : assistants + counters (agent config)
  - ai_lead_qualify_dev  : call_transcripts (written by bot + callback worker) —
                           the dev environment's database (was ai_lead_qualify).
                           bot.py, bot_dev.py, and callback_worker/config.py
                           all default to this same name.
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
    return _get_client()["ai_lead_qualify_dev"]["call_transcripts"]


def get_lang_cache_col():
    """Pre-translated fixed strings (greeting/nudge/closing/timeout/fillers) per
    (bot_id, language) — see backend/lang_translate.py. Warmed on save by
    update_assistant/update_workflow_bot; read directly by the bot runtime
    (voicebot_nodcode_platform/bot_dev.py) via its own Mongo client against this
    same server — same cross-service pattern call_transcripts already uses,
    just a different DB/collection name, so no new network hop at call start.
    """
    return _get_client()["no_code_platform"]["lang_string_cache"]


def get_audit_logs_col():
    """Who changed what, on which assistant/workflow bot, and when — see
    backend/audit_log.py's write_audit_log(). Read by routers/audit.py's
    GET /api/audit/logs/all-filters (JD-Dashboard's Audit Logs page)."""
    return _get_client()["no_code_platform"]["audit_logs"]


def get_prompt_versions_col():
    """Saved system-prompt snapshots for assistants — see
    backend/routers/prompt_versions.py. Replaces the old localStorage-only
    version history in JD-Dashboard's llm-config-section.tsx."""
    return _get_client()["no_code_platform"]["prompt_versions"]


# ── no_code_platform — RBAC: protected phone numbers + go-live requests ─────

def get_protected_rules_col():
    """Admin-managed set of "Live"/protected LiveKit SIP dispatch rule IDs —
    see backend/routers/phone_numbers.py. Replaces the old
    PROTECTED_DISPATCH_RULE_IDS env var (still used as this collection's
    one-time migration seed — see backend/migrate_rbac.py). Doc shape:
    {"rule_id": str, "tagged_by": int (user id), "tagged_at": str, "note": str}."""
    return _get_client()["no_code_platform"]["protected_dispatch_rules"]


def get_golive_requests_col():
    """User requests to promote an owned assistant/workflow bot to Live —
    see backend/routers/golive.py. Doc shape: {"id": int, "resource":
    "assistants"|"workflow_bots", "resource_id": str, "requested_by": int,
    "status": "pending"|"approved"|"rejected", "reviewed_by": int|None,
    "created_at": str, "reviewed_at": str|None, "note": str}."""
    return _get_client()["no_code_platform"]["golive_requests"]


async def next_sequence(name: str) -> int:
    """Atomically increment and return the next integer for `name`."""
    doc = await get_counters_col().find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["seq"]
