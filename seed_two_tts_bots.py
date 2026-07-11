#!/usr/bin/env python3
"""Seed two test bots into MongoDB no_code_platform.assistants:

  1. "Dev — Sarvam TTS"  — Sarvam STT + Sarvam bulbul:v3 "simran" TTS,
     pointed at DEV MIS/callback/category APIs and (optionally) a dev Mongo.
  2. "Live — Own TTS"    — Sarvam STT + our own IndicF5 "simran" TTS,
     pointed at LIVE/prod MIS/callback/category APIs and the prod Mongo.

Both bots get the SAME prompt/behavior settings — cloned from the existing
live LQ bot (assistant_id ...988c4, "Simran") as the base, differing only in:
name, tags, TTS voice_id/tts_provider_id/tts_model_id, mis_api_base/
callback_api_url/category_change_api, mongo_uri, organization_id, is_locked.

Everything environment-specific is env-driven — no hardcoded guessed hosts
for values this script can't know (e.g. a real separate dev Mongo). Where an
env var isn't set, dev values default to the same dev-MIS host already used
elsewhere in this codebase (bot_dev.py/seed_dev_bot.py:
http://192.168.14.101:3006) and live values default to the existing
production MIS host (http://192.168.8.67:8000) / Mongo
(mongodb://192.168.13.65:27017) — override any of these via env if your
actual dev/live infra differs.

Idempotent: re-running updates the existing docs in place (matched by name,
since these are fresh test bots with no fixed UUID like the LQ/dev ones).

Usage:
    python seed_two_tts_bots.py [org_id]

    # override any of these as needed:
    MONGODB_URL=mongodb://<host>:27017 \
    DEV_MIS_API_BASE=http://<dev-mis>:3006 \
    DEV_MONGO_URI=mongodb://<dev-mongo>:27017 \
    LIVE_MIS_API_BASE=http://<live-mis>:8000 \
    LIVE_MONGO_URI=mongodb://<live-mongo>:27017 \
        python seed_two_tts_bots.py my-org
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"
ORG_ID = sys.argv[1] if len(sys.argv) > 1 else "default-org"

LQ_UUID = "e8c0fd31-2d60-4531-a029-2047b17988c4"  # live LQ ("Simran") — prompt/behavior source

# ---------------------------------------------------------------------------
# Dev environment
# ---------------------------------------------------------------------------
DEV_MIS_API_BASE = os.getenv("DEV_MIS_API_BASE", "http://192.168.14.101:3006")
DEV_CALLBACK_API_URL = os.getenv("DEV_CALLBACK_API_URL", f"{DEV_MIS_API_BASE}/leads/ai-lead-qualify/callback")
DEV_CATEGORY_CHANGE_API = os.getenv("DEV_CATEGORY_CHANGE_API", f"{DEV_MIS_API_BASE}/leads/ai-lead-qualify/search")
# No confirmed separate dev Mongo exists yet in this codebase — defaults to
# the same Mongo as MONGODB_URL unless you set DEV_MONGO_URI explicitly.
DEV_MONGO_URI = os.getenv("DEV_MONGO_URI", MONGO_URL)

# ---------------------------------------------------------------------------
# Live/prod environment
# ---------------------------------------------------------------------------
LIVE_MIS_API_BASE = os.getenv("LIVE_MIS_API_BASE", "http://192.168.8.67:8000")
LIVE_CALLBACK_API_URL = os.getenv("LIVE_CALLBACK_API_URL", f"{LIVE_MIS_API_BASE}/leads/ai-lead-qualify/callback")
LIVE_CATEGORY_CHANGE_API = os.getenv("LIVE_CATEGORY_CHANGE_API", "http://192.168.20.105:1080/services/abd/abd_beta.php")
LIVE_MONGO_URI = os.getenv("LIVE_MONGO_URI", "mongodb://192.168.13.65:27017")

# ---------------------------------------------------------------------------
# Voice catalog ids (see backend/voice_catalog.py)
# ---------------------------------------------------------------------------
SARVAM_SIMRAN_VOICE_ID = 20   # sarvam / bulbul:v3 / simran — verified in production use
OWN_SIMRAN_VOICE_ID = 12      # justdial / indic-f5 / simran — current default


def _functions_for(mis_api_base: str) -> list[dict]:
    return [
        {
            "name": "FetchLead",
            "description": "Fetch customer lead details from Justdial MIS API at call start.",
            "url": f"{mis_api_base}/leads/ai-lead-qualify/mis",
            "method": "GET",
            "headers": {},
            "query_params": {"lead_id": "", "mobile": "", "page": "1", "limit": "1", "ai_partner": "inh-suny-bot"},
            "body_format": "json",
            "custom_body": "",
            "schema": {},
        },
        {
            "name": "FetchCategorySchema",
            "description": "Fetches qualification schema when buyer changes product mid-call.",
            "url": f"{mis_api_base}/leads/ai-lead-qualify/search",
            "method": "GET",
            "headers": {},
            "query_params": {"lead_id": "", "search_term": ""},
            "body_format": "json",
            "custom_body": "",
            "schema": {
                "type": "object",
                "properties": {"srchterm": {"type": "string", "description": "New product search term in English"}},
                "required": ["srchterm"],
            },
        },
    ]


BOTS = [
    {
        "name": "Simran — Dev (Sarvam TTS)",
        "description": "Test bot: Sarvam STT + Sarvam bulbul:v3 TTS, dev MIS/callback APIs.",
        "tags": ["hindi", "justdial", "qualification", "dev", "sarvam-tts", "simran"],
        "tts_provider_id": 4, "tts_model_id": 2, "voice_id": SARVAM_SIMRAN_VOICE_ID,
        "mis_api_base": DEV_MIS_API_BASE,
        "callback_api_url": DEV_CALLBACK_API_URL,
        "category_change_api": DEV_CATEGORY_CHANGE_API,
        "mongo_uri": DEV_MONGO_URI,
    },
    {
        "name": "Simran — Live (Own TTS)",
        "description": "Test bot: Sarvam STT + our own fine-tuned IndicF5 TTS, live/prod MIS/callback APIs.",
        "tags": ["hindi", "justdial", "qualification", "live", "own-tts", "simran"],
        "tts_provider_id": 3, "tts_model_id": 1, "voice_id": OWN_SIMRAN_VOICE_ID,
        "mis_api_base": LIVE_MIS_API_BASE,
        "callback_api_url": LIVE_CALLBACK_API_URL,
        "category_change_api": LIVE_CATEGORY_CHANGE_API,
        "mongo_uri": LIVE_MONGO_URI,
    },
]

# Fields cloned verbatim from the LQ bot (same prompt / behavior for both new bots)
_CLONE_FIELDS = [
    "prompt", "initial_message", "call_end_text", "script_rule", "opening_instruction",
    "closing_instruction", "timeout_message", "language", "temperature",
    "gemini_start_sensitivity", "gemini_end_sensitivity", "gemini_silence_duration_ms",
    "gemini_prefix_padding_ms", "max_call_duration", "filler_message", "function_filler_message",
    "sarvam_min_rms", "sarvam_min_speech_ms", "sarvam_min_speech_ms_singleword",
    "sarvam_silero_threshold", "sarvam_silero_min_speech_ms", "gemini_silero_fallback_speech_ms",
    "post_speech_hold_ms", "inactivity_first_rescue_secs", "inactivity_first_nudge_gap_secs",
    "inactivity_nudge_secs", "inactivity_close_secs", "analysis_prompt", "inactivity_phrase",
    "inactivity_end_phrase", "lang_notes",
]


async def main() -> None:
    import uuid

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    col = db["assistants"]
    ctr = db["counters"]
    now = datetime.now(timezone.utc)

    lq_doc = await col.find_one({"assistant_id": LQ_UUID})
    if not lq_doc:
        print(f"[seed] ⚠️  Base LQ bot not found ({LQ_UUID!r}) — bots will be created with empty prompts")
    base = {k: lq_doc.get(k) for k in _CLONE_FIELDS} if lq_doc else {}

    for spec in BOTS:
        existing = await col.find_one({"organization_id": ORG_ID, "name": spec["name"]})
        overrides = {
            **base,
            "organization_id": ORG_ID,
            "name": spec["name"],
            "description": spec["description"],
            "category": "Customer Service",
            "tags": spec["tags"],
            "status": "Active",
            "function_calling": True,
            "functions": _functions_for(spec["mis_api_base"]),
            "mis_api_base": spec["mis_api_base"],
            "callback_api_url": spec["callback_api_url"],
            "category_change_api": spec["category_change_api"],
            "mongo_uri": spec["mongo_uri"],
            "tts_provider_id": spec["tts_provider_id"],
            "tts_model_id": spec["tts_model_id"],
            "voice_id": spec["voice_id"],
            "is_locked": False,
            "is_deleted": False,
            "is_active": True,
            "updated_at": now,
        }

        if existing:
            await col.update_one({"_id": existing["_id"]}, {"$set": overrides})
            print(f"[seed] ✅ Updated: {spec['name']!r} (assistant_id={existing['assistant_id']})")
        else:
            ctr_doc = await ctr.find_one_and_update(
                {"_id": "assistant_id"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True,
            )
            doc = {
                **overrides,
                "id": ctr_doc["seq"],
                "assistant_id": str(uuid.uuid4()),
                "calls_today": 0,
                "created_at": now,
            }
            await col.insert_one(doc)
            print(f"[seed] ✅ Created: {spec['name']!r} (assistant_id={doc['assistant_id']}, id={doc['id']})")

    print()
    print("[seed] Verify:")
    async for doc in col.find(
        {"organization_id": ORG_ID, "name": {"$in": [b["name"] for b in BOTS]}},
        {"name": 1, "assistant_id": 1, "voice_id": 1, "mis_api_base": 1, "mongo_uri": 1, "status": 1},
    ):
        print(f"  {doc}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
