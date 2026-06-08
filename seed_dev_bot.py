#!/usr/bin/env python3
"""Seed the Dev bot (assistant_id ...987c4) into MongoDB no_code_platform.assistants.

Idempotent: if the dev bot doc already exists it is updated in-place.
Also sets is_locked=True on the live LQ bot (...988c4) and is_locked=False
on the dev bot.

Usage:
    python seed_dev_bot.py [org_id]
"""
import asyncio
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL    = "mongodb://192.168.13.65:27017"
DB_NAME      = "no_code_platform"
ORG_ID       = sys.argv[1] if len(sys.argv) > 1 else "default-org"

LQ_UUID  = "e8c0fd31-2d60-4531-a029-2047b17988c4"   # live LQ (Simran SIP) — must be locked
DEV_UUID = "e8c0fd31-2d60-4531-a029-2047b17987c4"   # dev bot (WebRTC + SIP) — unlocked

DEV_FUNCTIONS = [
    {
        "name": "FetchLead",
        "description": "Fetch customer lead details from Justdial MIS API at call start.",
        "url": "http://192.168.14.101:3006/leads/ai-lead-qualify/mis",
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
        "url": "http://192.168.14.101:3006/leads/ai-lead-qualify/search",
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


async def main() -> None:
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    col = db["assistants"]
    ctr = db["counters"]
    now = datetime.now(timezone.utc)

    # 1. Lock the live LQ bot
    lq_doc = await col.find_one({"assistant_id": LQ_UUID})
    if lq_doc:
        await col.update_one(
            {"assistant_id": LQ_UUID},
            {"$set": {"is_locked": True, "updated_at": now}},
        )
        print(f"[seed] ✅ Locked live LQ bot: assistant_id={LQ_UUID}")
    else:
        print(f"[seed] ⚠️  Live LQ bot not found: {LQ_UUID!r} — skipping lock")

    # 2. Upsert the dev bot
    existing = await col.find_one({"assistant_id": DEV_UUID})
    if existing:
        # Clone any missing fields from LQ doc as fallback, but keep dev-specific ones
        updates = {
            "is_locked": False,
            "status": existing.get("status", "Active"),
            "mis_api_base": "http://192.168.14.101:3006",
            "callback_api_url": "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
            "functions": DEV_FUNCTIONS,
            "updated_at": now,
        }
        await col.update_one({"assistant_id": DEV_UUID}, {"$set": updates})
        print(f"[seed] ✅ Updated existing dev bot: assistant_id={DEV_UUID}")
    else:
        # Clone the full LQ doc config as the base for the dev bot
        base = lq_doc or {}
        ctr_doc = await ctr.find_one_and_update(
            {"_id": "assistant_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        new_id = ctr_doc["seq"]
        dev_doc = {
            **{k: v for k, v in base.items() if k not in ("_id", "id", "assistant_id")},
            "id": new_id,
            "assistant_id": DEV_UUID,
            "organization_id": ORG_ID,
            "name": "Simran — Dev (WebRTC + SIP)",
            "description": "Dev/test bot. Same config as live LQ bot but points at dev MIS (192.168.14.101:3006) and dev MongoDB. Unlocked — editable from dashboard.",
            "category": "Customer Service",
            "tags": ["hindi", "justdial", "qualification", "dev", "webrtc", "simran"],
            "status": "Active",
            "mis_api_base": "http://192.168.14.101:3006",
            "callback_api_url": "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
            "functions": DEV_FUNCTIONS,
            "function_calling": True,
            "is_locked": False,
            "is_deleted": False,
            "is_active": True,
            "calls_today": 0,
            "created_at": now,
            "updated_at": now,
        }
        await col.insert_one(dev_doc)
        print(f"[seed] ✅ Created dev bot: assistant_id={DEV_UUID}  id={new_id}")

    # 3. Verify
    for uid, label in [(LQ_UUID, "LQ (live)"), (DEV_UUID, "Dev")]:
        doc = await col.find_one({"assistant_id": uid}, {"name": 1, "is_locked": 1, "status": 1})
        print(f"[seed] Verify {label}: {doc}")

    client.close()


asyncio.run(main())
