#!/usr/bin/env python3
"""Create (or update the password/role of) a real dashboard login account.

The dashboard's login screen used to accept only a hardcoded demo email/
password and never touched the backend at all (see routers/auth.py's module
docstring for the full context). This script creates the first real account
so you can actually log in once login-form.tsx is wired to the real API.

Idempotent: re-running with the same email updates that user's password/role
instead of creating a duplicate.

Usage:
    python seed_admin_user.py <email> <password> [name] [role]

    MONGODB_URL=mongodb://<server>:27017 python seed_admin_user.py \\
        you@justdial.com "a real password" "Your Name" admin
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import bcrypt
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    password = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else email.split("@")[0]
    role = sys.argv[4] if len(sys.argv) > 4 else "user"

    if role not in ("admin", "user"):
        print(f"role must be 'admin' or 'user', got {role!r}.")
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    users_col = db["users"]
    counters_col = db["counters"]

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    now = datetime.now(timezone.utc).isoformat()

    existing = await users_col.find_one({"email": email})
    if existing:
        await users_col.update_one(
            {"email": email},
            {"$set": {"password_hash": password_hash, "name": name, "role": role, "updated_at": now}},
        )
        print(f"Updated user {email!r} (id={existing['id']}, role={role!r}).")
    else:
        counter_doc = await counters_col.find_one_and_update(
            {"_id": "user_id"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True
        )
        user_id = counter_doc["seq"]
        await users_col.insert_one({
            "id": user_id,
            "email": email,
            "password_hash": password_hash,
            "name": name,
            "role": role,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
        print(f"Created user {email!r} (id={user_id}, role={role!r}).")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
