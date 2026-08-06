"""Admin-only user administration — the internal-platform replacement for
self-service org/account management. Every route requires role=="admin"
(see routers/auth.py's require_admin). An admin can create accounts,
activate/deactivate them, reset a password, and grant/revoke the admin role
itself — with guard rails so the platform can never lock itself out of
being administered (the last admin can't be demoted, deactivated, or
self-demoted).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from ..mongo import get_users_col, next_sequence
    from ..audit_log import write_audit_log
    from . import auth
except ImportError:
    from mongo import get_users_col, next_sequence
    from audit_log import write_audit_log
    from routers import auth

router = APIRouter()

Role = Literal["admin", "user"]


class CreateUserBody(BaseModel):
    email: str
    password: str
    name: str
    role: Role = "user"


class UpdateUserBody(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class SetPasswordBody(BaseModel):
    password: str


class SetRoleBody(BaseModel):
    role: Role


def _doc_out(doc: dict) -> dict:
    return {
        "id": doc.get("id", 0),
        "email": doc.get("email", ""),
        "name": doc.get("name", ""),
        "role": doc.get("role", "user"),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
    }


async def _admin_count(exclude_id: Optional[int] = None) -> int:
    query: dict = {"role": "admin", "is_active": True}
    if exclude_id is not None:
        query["id"] = {"$ne": exclude_id}
    return await get_users_col().count_documents(query)


@router.get("/api/users")
async def list_users(skip: int = 0, limit: int = 100, admin: dict = Depends(auth.require_admin)):
    col = get_users_col()
    total = await col.count_documents({})
    docs = await col.find({}).sort("id", 1).skip(skip).limit(limit).to_list(length=limit)
    return {"users": [_doc_out(d) for d in docs], "total": total}


@router.post("/api/users", status_code=201)
async def create_user(body: CreateUserBody, admin: dict = Depends(auth.require_admin)):
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")

    col = get_users_col()
    if await col.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user_id = await next_sequence("user_id")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": user_id,
        "email": email,
        "password_hash": auth.hash_password(body.password),
        "name": body.name.strip(),
        "role": body.role,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await col.insert_one(doc)
    await write_audit_log(
        user=admin, action="user.created", resource="users",
        resource_id=str(user_id), details=f"Created account {email!r} (role={body.role})",
    )
    return _doc_out(doc)


@router.patch("/api/users/{user_id}")
async def update_user(user_id: int, body: UpdateUserBody, admin: dict = Depends(auth.require_admin)):
    col = get_users_col()
    doc = await col.find_one({"id": user_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    updates: dict = {}
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Name cannot be empty.")
        updates["name"] = body.name.strip()
    if body.is_active is not None:
        if not body.is_active and doc.get("role") == "admin" and await _admin_count(exclude_id=user_id) == 0:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last remaining admin.")
        updates["is_active"] = body.is_active

    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await col.update_one({"id": user_id}, {"$set": updates})
        await write_audit_log(
            user=admin, action="user.updated", resource="users",
            resource_id=str(user_id), details=f"Updated user {doc.get('email', '')!r}: {', '.join(updates)}",
        )
    doc = await col.find_one({"id": user_id})
    return _doc_out(doc)


@router.patch("/api/users/{user_id}/password")
async def set_user_password(user_id: int, body: SetPasswordBody, admin: dict = Depends(auth.require_admin)):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    col = get_users_col()
    doc = await col.find_one({"id": user_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    await col.update_one(
        {"id": user_id},
        {"$set": {
            "password_hash": auth.hash_password(body.password),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    await write_audit_log(
        user=admin, action="user.password_reset", resource="users",
        resource_id=str(user_id), details=f"Reset password for {doc.get('email', '')!r}", severity="medium",
    )
    return {"id": user_id, "message": "Password updated."}


@router.patch("/api/users/{user_id}/role")
async def set_user_role(user_id: int, body: SetRoleBody, admin: dict = Depends(auth.require_admin)):
    col = get_users_col()
    doc = await col.find_one({"id": user_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if doc.get("role") == body.role:
        return _doc_out(doc)

    if doc.get("role") == "admin" and body.role != "admin":
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="You cannot demote your own account.")
        if await _admin_count(exclude_id=user_id) == 0:
            raise HTTPException(status_code=400, detail="Cannot demote the last remaining admin.")

    await col.update_one(
        {"id": user_id},
        {"$set": {"role": body.role, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await write_audit_log(
        user=admin, action="user.role_changed", resource="users",
        resource_id=str(user_id),
        details=f"Changed {doc.get('email', '')!r} role: {doc.get('role')} -> {body.role}",
        severity="medium",
    )
    doc = await col.find_one({"id": user_id})
    return _doc_out(doc)
