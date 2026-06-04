"""One-off migration: seed CANONICAL_ANALYSIS_PROMPT into all assistant documents
that have an empty, missing, or outdated (pre-GP-rules) analysis_prompt field.

Usage (from repo root or backend/ directory):
    python backend/migrate_analysis_prompt.py

    # Dry-run — show what would be updated without writing:
    python backend/migrate_analysis_prompt.py --dry-run

    # Force-overwrite ALL documents regardless of current content:
    python backend/migrate_analysis_prompt.py --force

Environment variables:
    MONGO_URI   — MongoDB connection string (default: mongodb://192.168.13.65:27017)
"""

from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Path setup — allow importing from the worker package which lives one level
# up from this script (../voicebot_nodcode_platform/callback_worker/).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER_ROOT = os.path.join(_HERE, "..", "voicebot_nodcode_platform")
sys.path.insert(0, _WORKER_ROOT)

try:
    from callback_worker.canonical_prompt import CANONICAL_ANALYSIS_PROMPT
except ImportError as exc:
    print(
        f"[migrate] ERROR: Could not import CANONICAL_ANALYSIS_PROMPT — {exc}\n"
        "Run this script from the repo root or make sure the voicebot_nodcode_platform "
        "package is on PYTHONPATH.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# MongoDB connection
# ---------------------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"
COLLECTION_NAME = "assistants"

# A doc needs updating if its analysis_prompt is empty/missing/short
# OR if it doesn't contain "GP-1" (the old short prompt lacks all the rules).
_MIN_LENGTH = 500
_MARKER = "GP-1"


def _needs_update(doc: dict) -> bool:
    """Return True if this document's analysis_prompt should be replaced."""
    ap = doc.get("analysis_prompt") or ""
    if not ap or len(ap) < _MIN_LENGTH:
        return True
    if _MARKER not in ap:
        return True
    return False


def run(dry_run: bool = False, force: bool = False) -> None:
    try:
        import pymongo
    except ImportError:
        print(
            "[migrate] ERROR: pymongo is not installed. Run: pip install pymongo",
            file=sys.stderr,
        )
        sys.exit(1)

    client = pymongo.MongoClient(MONGO_URI)
    col = client[DB_NAME][COLLECTION_NAME]

    docs = list(col.find({}, {"_id": 1, "assistant_id": 1, "analysis_prompt": 1}))
    if not docs:
        print("[migrate] No assistant documents found — nothing to do.")
        client.close()
        return

    to_update = [d for d in docs if force or _needs_update(d)]
    skipped = len(docs) - len(to_update)

    print(
        f"[migrate] Found {len(docs)} assistant doc(s). "
        f"{len(to_update)} need updating, {skipped} already up-to-date."
    )

    if not to_update:
        print("[migrate] Nothing to update.")
        client.close()
        return

    updated = 0
    for doc in to_update:
        aid = doc.get("assistant_id") or str(doc["_id"])
        if dry_run:
            print(f"[migrate] DRY-RUN — would update assistant_id={aid!r}")
            updated += 1
            continue

        result = col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"analysis_prompt": CANONICAL_ANALYSIS_PROMPT}},
        )
        if result.modified_count:
            print(f"[migrate] Updated  assistant_id={aid!r}")
            updated += 1
        else:
            print(f"[migrate] No change for assistant_id={aid!r} (already up-to-date?)")

    client.close()

    action = "Would update" if dry_run else "Updated"
    print(f"[migrate] Done. {action} {updated} of {len(to_update)} document(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed CANONICAL_ANALYSIS_PROMPT into MongoDB assistant documents"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing to MongoDB",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite analysis_prompt on ALL assistant documents, even up-to-date ones",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force)
