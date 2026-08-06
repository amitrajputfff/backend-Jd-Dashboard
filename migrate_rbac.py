#!/usr/bin/env python3
"""One-time migration: bolt real RBAC onto the existing Mongo data.

Before this script: every user was implicitly a superuser (see
routers/auth.py's old _FULL_PERMISSIONS), and "which agents can I see" was
answered by a client-supplied `organization_id` query param that any caller
could set to anything. After this script: users carry a real `role`
("admin" | "user"), and assistants/workflow_bots carry `created_by` (the
Mongo `id` of the user who made them) instead of `organization_id`.

Idempotent — re-running it is safe and prints the same end-state summary
each time. Steps:
  1. Users: ADMIN_EMAIL becomes role="admin", everyone else role="user".
     Drops organization_id / organization_name / phone_number (this is an
     internal platform — those fields don't mean anything here).
  2. Assistants + workflow_bots: backfill created_by from the old
     organization_id using _ORG_TO_USER below, then drop organization_id.
     Anything with an unmapped organization_id falls back to
     _DEFAULT_CREATED_BY and gets logged loudly, since a silent wrong owner
     would just make an agent vanish from everyone's list.
  3. Seeds the protected_dispatch_rules collection from today's
     PROTECTED_DISPATCH_RULE_IDS env var, so the phone numbers already
     marked Live in production stay Live after routers/phone_numbers.py
     switches from that env var to this collection.

Run with the project's venv (system python has no `motor`):
    .venv/bin/python backend/migrate_rbac.py [--yes]

Without --yes it prints the plan and exits without writing anything.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"

ADMIN_EMAIL = "sreeram.chengaloor@justdial.com"

# organization_id -> user id to attribute existing assistants/workflow_bots
# to. Values taken from the live users collection at migration-authoring
# time (demo@justdial.com=3, nikitapatel=5, pranav.garg=6, rohan.bisht=8).
# default-org is a seed-script artifact, not a real user's org — attributed
# to demo (3) rather than the admin, since admin's list is Live-only and an
# unmapped agent landing there would silently disappear from every list.
_ORG_TO_USER: dict[str, int] = {
    "org-demo-123": 3,
    "org-justdial-5": 5,
    "org-justdial-6": 6,
    "org-just-dial-8": 8,
    "default-org": 3,
}
_DEFAULT_CREATED_BY = 3

_PROTECTED_RULE_IDS_ENV = os.environ.get("PROTECTED_DISPATCH_RULE_IDS", "SDR_CSA2NurhzDxz")


async def main():
    dry_run = "--yes" not in sys.argv
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    now = datetime.now(timezone.utc).isoformat()

    print(f"{'DRY RUN — ' if dry_run else ''}Migrating {MONGO_URL}/{DB_NAME}")
    print("=" * 70)

    # ── 1. Users ──────────────────────────────────────────────────────────
    users_col = db["users"]
    users = await users_col.find({}).to_list(length=None)
    print(f"\n[users] {len(users)} account(s):")
    for u in users:
        role = "admin" if u.get("email", "").strip().lower() == ADMIN_EMAIL else "user"
        print(f"    {u.get('email'):40} id={u.get('id'):<4} -> role={role}")
        if not dry_run:
            await users_col.update_one(
                {"_id": u["_id"]},
                {
                    "$set": {"role": role, "updated_at": now},
                    "$unset": {"organization_id": "", "organization_name": "", "phone_number": ""},
                },
            )

    admin_count = sum(1 for u in users if u.get("email", "").strip().lower() == ADMIN_EMAIL)
    if admin_count == 0:
        print(f"\n  !! WARNING: no user with email {ADMIN_EMAIL!r} exists yet — "
              f"create one (seed_admin_user.py) before or after running this.")

    # ── 2. Assistants + workflow_bots: organization_id -> created_by ──────
    # Only docs that STILL HAVE organization_id are touched — once step 1's
    # $unset runs on a doc, organization_id is gone and this must leave
    # created_by alone. Without this filter a second run would see every
    # doc's organization_id as "" (unmapped) and clobber every previously
    # correct created_by back to _DEFAULT_CREATED_BY — a real bug this
    # comment is here to keep from regressing.
    for collection_name in ("assistants", "workflow_bots"):
        col = db[collection_name]
        docs = await col.find({"organization_id": {"$exists": True}}).to_list(length=None)
        already_migrated = await col.count_documents({"organization_id": {"$exists": False}})
        print(f"\n[{collection_name}] {len(docs)} doc(s) to migrate "
              f"({already_migrated} already migrated, skipped):")
        for d in docs:
            org = d.get("organization_id", "")
            created_by = _ORG_TO_USER.get(org)
            if created_by is None:
                created_by = _DEFAULT_CREATED_BY
                print(f"    !! unmapped organization_id={org!r} on "
                      f"{d.get('name', d.get('assistant_id') or d.get('workflow_bot_id'))!r} "
                      f"-> defaulting created_by={created_by}")
            else:
                print(f"    {org!r:22} -> created_by={created_by}  "
                      f"({d.get('name', '')!r})")
            if not dry_run:
                await col.update_one(
                    {"_id": d["_id"]},
                    {"$set": {"created_by": created_by, "updated_at": now}, "$unset": {"organization_id": ""}},
                )

    # ── 3. Seed protected_dispatch_rules from the env var ──────────────────
    protected_col = db["protected_dispatch_rules"]
    rule_ids = {r.strip() for r in _PROTECTED_RULE_IDS_ENV.split(",") if r.strip()}
    print(f"\n[protected_dispatch_rules] seeding from PROTECTED_DISPATCH_RULE_IDS={_PROTECTED_RULE_IDS_ENV!r}:")
    admin_doc = next((u for u in users if u.get("email", "").strip().lower() == ADMIN_EMAIL), None)
    tagged_by = admin_doc.get("id") if admin_doc else 0
    for rule_id in rule_ids:
        print(f"    {rule_id}")
        if not dry_run:
            await protected_col.update_one(
                {"rule_id": rule_id},
                {"$setOnInsert": {
                    "rule_id": rule_id,
                    "tagged_by": tagged_by,
                    "tagged_at": now,
                    "note": "migrated from PROTECTED_DISPATCH_RULE_IDS env var",
                }},
                upsert=True,
            )

    print("\n" + "=" * 70)
    if dry_run:
        print("Dry run only — nothing was written. Re-run with --yes to apply.")
    else:
        print("Migration applied.")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
