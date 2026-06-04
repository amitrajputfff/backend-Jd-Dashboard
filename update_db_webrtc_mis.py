"""One-off DB migration script.

Actions:
1. Hard-delete WebRTC agent docs from no_code_platform.assistants.
2. Update the Simran SIP agent's FetchLead URL and mis_api_base to the
   correct production host (192.168.8.67:8000).

Usage:
    python update_db_webrtc_mis.py
"""

import os
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"
SIMRAN_UUID = "e8c0fd31-2d60-4531-a029-2047b17988c4"
NEW_MIS_URL = "http://192.168.8.67:8000/leads/ai-lead-qualify/mis"
NEW_MIS_BASE = "http://192.168.8.67:8000"


def main() -> None:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    col = client[DB_NAME]["assistants"]

    # ------------------------------------------------------------------
    # 1. Hard-delete WebRTC agent docs
    # ------------------------------------------------------------------
    webrtc_filter = {
        "$or": [
            {"tags": {"$in": ["webrtc"]}},
            {"name": {"$regex": "WebRTC", "$options": "i"}},
        ]
    }

    # Preview before deleting
    webrtc_docs = list(col.find(webrtc_filter, {"assistant_id": 1, "name": 1, "_id": 0}))
    if webrtc_docs:
        print(f"[1] Found {len(webrtc_docs)} WebRTC doc(s) to delete:")
        for d in webrtc_docs:
            print(f"    - assistant_id={d.get('assistant_id')} name={d.get('name')!r}")
        result = col.delete_many(webrtc_filter)
        print(f"[1] Deleted {result.deleted_count} WebRTC doc(s).")
    else:
        print("[1] No WebRTC docs found — nothing to delete.")

    # ------------------------------------------------------------------
    # 2. Update FetchLead URL on the Simran SIP agent
    # ------------------------------------------------------------------
    result = col.update_one(
        {
            "assistant_id": SIMRAN_UUID,
            "functions.name": "FetchLead",
        },
        {
            "$set": {
                "functions.$.url": NEW_MIS_URL,
                "api_urls.mis_api_base": NEW_MIS_BASE,
                "mis_api_base": NEW_MIS_BASE,
            }
        },
    )
    print(
        f"[2] FetchLead URL update — matched={result.matched_count}, "
        f"modified={result.modified_count}"
    )
    if result.matched_count == 0:
        print(
            f"    WARNING: assistant_id={SIMRAN_UUID!r} with FetchLead function not found. "
            "Check that the agent exists and has a 'functions' array with name='FetchLead'."
        )
    else:
        # Verify
        doc = col.find_one(
            {"assistant_id": SIMRAN_UUID},
            {"functions": 1, "mis_api_base": 1, "api_urls": 1, "_id": 0},
        )
        fetch_fn = next(
            (f for f in (doc.get("functions") or []) if f.get("name") == "FetchLead"),
            None,
        )
        print(f"    FetchLead.url = {fetch_fn['url'] if fetch_fn else 'NOT FOUND'!r}")
        print(f"    mis_api_base  = {doc.get('mis_api_base')!r}")

    client.close()
    print("[Done]")


if __name__ == "__main__":
    main()
