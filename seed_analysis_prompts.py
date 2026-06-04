"""Seed the canonical analysis prompt into the new `analysis_prompts` collection.

This collection lives in the `no_code_platform` MongoDB database and is
independent of any specific assistant.  In future a separate mapping table
will link assistant_id → prompt_id.

Usage (from repo root or backend/ directory):
    python backend/seed_analysis_prompts.py

    # Dry-run — show what would happen without writing:
    python backend/seed_analysis_prompts.py --dry-run

    # Force-overwrite the existing default prompt even if it's already seeded:
    python backend/seed_analysis_prompts.py --force

Environment variables:
    MONGO_URI   — MongoDB connection string (default: mongodb://192.168.13.65:27017)
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER_ROOT = os.path.join(_HERE, "..", "voicebot_nodcode_platform")
sys.path.insert(0, _WORKER_ROOT)

try:
    from callback_worker.canonical_prompt import CANONICAL_ANALYSIS_PROMPT
except ImportError as exc:
    print(
        f"[seed] ERROR: Could not import CANONICAL_ANALYSIS_PROMPT — {exc}\n"
        "Run this script from the repo root or make sure "
        "voicebot_nodcode_platform is on PYTHONPATH.",
        file=sys.stderr,
    )
    sys.exit(1)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"
COLLECTION = "analysis_prompts"

DEFAULT_PROMPT_NAME = "JustDial Default Analysis Prompt"
_MIN_LENGTH = 500
_MARKER = "GP-1"


def _prompt_is_current(doc: dict) -> bool:
    ap = doc.get("analysis_prompt") or ""
    return bool(ap) and len(ap) >= _MIN_LENGTH and _MARKER in ap


def run(dry_run: bool = False, force: bool = False) -> None:
    try:
        import pymongo
    except ImportError:
        print("[seed] ERROR: pymongo is not installed. Run: pip install pymongo", file=sys.stderr)
        sys.exit(1)

    client = pymongo.MongoClient(MONGO_URI)
    col = client[DB_NAME][COLLECTION]

    now = datetime.now(timezone.utc)

    # Check if a default prompt already exists
    existing_default = col.find_one({"is_default": True})
    if existing_default is None:
        existing_default = col.find_one({}, sort=[("created_at", pymongo.ASCENDING)])

    if existing_default and not force:
        if _prompt_is_current(existing_default):
            pid = existing_default.get("prompt_id", str(existing_default["_id"]))
            print(f"[seed] Default prompt already seeded (prompt_id={pid!r}). Use --force to overwrite.")
            client.close()
            return
        else:
            print("[seed] Existing default prompt is outdated — will update.")

    if existing_default and (force or not _prompt_is_current(existing_default)):
        pid = existing_default.get("prompt_id", str(existing_default["_id"]))
        if dry_run:
            print(f"[seed] DRY-RUN — would update existing prompt prompt_id={pid!r}")
        else:
            col.update_one(
                {"_id": existing_default["_id"]},
                {"$set": {
                    "analysis_prompt": CANONICAL_ANALYSIS_PROMPT,
                    "name": DEFAULT_PROMPT_NAME,
                    "is_default": True,
                    "updated_at": now,
                }},
            )
            print(f"[seed] Updated existing prompt prompt_id={pid!r}")
    else:
        # No existing prompt — create fresh
        new_id = str(uuid.uuid4())
        doc = {
            "prompt_id": new_id,
            "name": DEFAULT_PROMPT_NAME,
            "description": "Full GP-1 through GP-8 JustDial outbound qualification analysis rules.",
            "analysis_prompt": CANONICAL_ANALYSIS_PROMPT,
            "is_default": True,
            "created_at": now,
            "updated_at": now,
        }
        if dry_run:
            print(f"[seed] DRY-RUN — would insert new prompt prompt_id={new_id!r}")
        else:
            col.insert_one(doc)
            print(f"[seed] Inserted new default prompt prompt_id={new_id!r}")

    client.close()
    print("[seed] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed CANONICAL_ANALYSIS_PROMPT into the analysis_prompts collection"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite even if already up-to-date")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force)
