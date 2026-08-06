"""Minimal real authentication — email + password, JWT access/refresh tokens
— plus a real two-role RBAC layer (admin / user) on top.

Scope decision (explicit, not an oversight): JD-Dashboard/src/lib/api/auth.ts
is a large (1000+ line) client covering login, register, refresh, logout,
OAuth (Google/GitHub/SSO), email verification, OTP, password reset, and
sessions list/revoke. Building all of that is a separate, much larger
project. This router implements ONLY the four endpoints the actual login
screen (src/components/login-form.tsx) and its auth-guard/refresh-interceptor
plumbing need: login, refresh, me, logout. The remaining authApi methods stay
unused (unreachable — nothing in the UI calls them today) until that's
tackled as its own piece of work.

Response shapes below are reverse-engineered from exactly what the existing
frontend code reads (not guessed):
  - POST /api/auth/login   -> wrapped: {"data": {"token", "refresh_token",
    "user"}, "success": true} (src/lib/api/auth.ts login() reads
    response.data.token/.refresh_token/.user via apiClient, which itself
    unwraps one level — so the FastAPI JSON body must have a top-level
    "data" key).
  - POST /api/auth/refresh -> FLAT, no wrapper: {"access_token",
    "refresh_token", "token_type", "user"} — refreshToken() deliberately
    bypasses apiClient with a raw axios call and reads response.data.
    access_token directly (i.e. axios's response.data IS the flat object).
  - GET  /api/auth/me      -> wrapped: {"data": {...user}} (getCurrentUser()
    handles both wrapped and flat, wrapped matches every other apiClient call).
  - POST /api/auth/logout  -> anything 2xx; frontend clears local storage
    regardless of body content.

No session/refresh-token revocation store — logout is client-side-only
(matches how the frontend already treats it: "Even if logout fails on
server, clear local storage"). Tokens are stateless JWTs; a leaked refresh
token remains valid until it expires. Acceptable for this stopgap; would need
a revocation list before this could be called production-grade multi-tenant
auth.

RBAC (added on top of the above, replacing the old "everyone gets
system.admin" placeholder): every user doc now carries a `role` field, either
"admin" or "user". Permissions are derived from that role on every request
(see `_permissions_for_role`) rather than granted unconditionally, so a role
change takes effect immediately without needing a new token. Two real
FastAPI dependencies — `get_current_user` / `require_admin` — replace the old
pattern of endpoints taking a raw `authorization: Header` and calling a
helper by hand; new endpoints should use these instead.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException

try:
    from ..mongo import get_users_col, next_sequence
except ImportError:
    from mongo import get_users_col, next_sequence

from pydantic import BaseModel

router = APIRouter()

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24h
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

Role = Literal["admin", "user"]

# Permission catalog per role. "system.admin" is the string the frontend's
# authUtils.isSystemAdmin() checks for (JD-Dashboard/src/lib/auth-utils.ts) —
# granting it here is what makes that already-built (previously unused)
# frontend RBAC layer light up for real admins and stay dark for everyone
# else, with no frontend permission-string changes needed.
_ROLE_PERMISSIONS: dict[Role, list[str]] = {
    "admin": [
        "system.admin",
        "system.audit",
        "users.manage",
        "agents.live.manage",
        "phone_numbers.protect",
        "assistants.read",
        "assistants.write",
        "calls.read",
    ],
    "user": [
        "assistants.read",
        "assistants.write",
        "calls.read",
    ],
}


def _permissions_for_role(role: str) -> dict:
    perms = _ROLE_PERMISSIONS.get(role, _ROLE_PERMISSIONS["user"])
    return {
        "user_id": 0,
        "roles": [],
        "role_permissions": list(perms),
        "granted_permissions": list(perms),
        "denied_permissions": [],
        "effective_permissions": list(perms),
        "field_permissions": {},
    }


class LoginBody(BaseModel):
    email: str
    password: str
    recaptcha_token: Optional[str] = None
    remember_me: Optional[str] = None


class RegisterBody(BaseModel):
    email: str
    password: str
    confirm_password: str
    name: str
    recaptcha_token: Optional[str] = None


class RefreshBody(BaseModel):
    refresh_token: str


class LogoutBody(BaseModel):
    refresh_token: Optional[str] = None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_token(user_id: int, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    # Deliberately no `role` claim here — every authorization decision
    # re-reads the role from Mongo (see get_current_user/require_admin
    # below) so a role change takes effect immediately instead of waiting
    # for this token to expire.
    payload = {"sub": str(user_id), "type": token_type, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, "access", timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: int) -> str:
    return _create_token(user_id, "refresh", timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail=f"Expected a {expected_type} token")
    return payload


def _doc_to_user(doc: dict) -> dict:
    role = doc.get("role", "user")
    permissions = _permissions_for_role(role)
    permissions["user_id"] = doc.get("id", 0)
    return {
        "id": doc.get("id", 0),
        "email": doc.get("email", ""),
        "name": doc.get("name", ""),
        "role": role,
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
        "permissions": permissions,
    }


async def get_user_from_bearer(authorization: Optional[str]) -> dict:
    """Shared dependency-style helper: validate a `Bearer <access token>`
    header and return the user doc. Raises 401 on any failure."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token, "access")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    doc = await get_users_col().find_one({"id": user_id})
    if not doc:
        raise HTTPException(status_code=401, detail="User not found")
    return doc


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """Real FastAPI dependency form of get_user_from_bearer — use this via
    `Depends(get_current_user)` on any new endpoint that must require login.
    Raises 401 on any failure (missing/expired/malformed token, unknown
    user). Prefer this over the old pattern (endpoints taking a raw
    `authorization: Header` and calling a helper by hand) going forward."""
    return await get_user_from_bearer(authorization)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency for admin-only endpoints: `Depends(require_admin)`.
    Requires a valid access token AND role == "admin" on the *current*
    Mongo doc (not a token claim), so a demotion takes effect on the very
    next request rather than waiting for token expiry."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


async def get_current_user_optional(authorization: Optional[str] = Header(default=None)) -> Optional[dict]:
    """Best-effort identify the caller for audit-log attribution — NOT an
    access-control gate. Returns None on any failure (missing/expired/
    malformed token, unknown user) instead of raising, so adding this to an
    endpoint that has never required auth (create/update/delete on
    assistants/workflow_bots — see routers/audit_log.py's write_audit_log
    call sites) can never turn a working request into a 401. The dashboard's
    apiClient already attaches a real Bearer token to every request when the
    user is logged in (see JD-Dashboard/src/lib/api/client.ts's request
    interceptor), so in practice this resolves a real user on every normal
    dashboard action.
    """
    try:
        return await get_user_from_bearer(authorization)
    except HTTPException:
        return None


async def verify_live_bot_action(authorization: Optional[str], password: Optional[str]) -> None:
    """Guard for modifying an already-Live-tagged Assistant or Workflow Bot
    (see routers/assistants.py / routers/workflow_bots.py update endpoints).

    Requires ALL THREE: the caller resolves to a real user, that user's role
    is "admin" (non-admins can no longer reach a Live bot's id at all — see
    the ownership checks in assistants.py/workflow_bots.py — but this is
    defense in depth), AND that admin's real password, checked fresh via
    bcrypt — not just "still has a valid session token". Untagging a Live
    bot, or editing it while it stays Live, is meant to be a deliberate,
    re-authenticated action even for an admin.
    """
    user = await get_user_from_bearer(authorization)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can modify a Live agent.")
    if not password:
        raise HTTPException(
            status_code=403,
            detail="This bot is tagged Live — enter your password to make changes.",
        )
    if not verify_password(password, user.get("password_hash", "")):
        raise HTTPException(status_code=403, detail="Incorrect password.")


@router.post("/api/auth/login")
async def login(body: LoginBody):
    doc = await get_users_col().find_one({"email": body.email.strip().lower()})
    if not doc or not verify_password(body.password, doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not doc.get("is_active", True):
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    access = create_access_token(doc["id"])
    refresh = create_refresh_token(doc["id"])
    return {
        "data": {"token": access, "refresh_token": refresh, "user": _doc_to_user(doc)},
        "success": True,
        "message": "Login successful",
    }


@router.post("/api/auth/register")
async def register(body: RegisterBody):
    """Self-service account creation — no email verification (none is wired
    up). No UI in JD-Dashboard's src/app/ links to this today (no /register
    route exists); kept working in case something still posts to it
    directly. Always creates role="user" — this is an internal platform, so
    the only way to become admin is routers/users.py's admin-only role grant
    (see backend/routers/auth.py's module docstring for the RBAC overview).
    Mirrors seed_admin_user.py's user-doc shape exactly, so admin-seeded and
    self-registered users are indistinguishable to the rest of the app.
    """
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")

    users_col = get_users_col()
    if await users_col.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user_id = await next_sequence("user_id")
    now = datetime.now(timezone.utc).isoformat()

    doc = {
        "id": user_id,
        "email": email,
        "password_hash": hash_password(body.password),
        "name": body.name.strip(),
        "role": "user",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await users_col.insert_one(doc)

    return {
        "data": {
            "user": {
                "id": user_id,
                "email": email,
                "name": doc["name"],
                "email_verified": False,
            },
            "verification_sent": False,
        },
        "success": True,
        "message": "Account created successfully. You can now sign in.",
    }


@router.post("/api/auth/refresh")
async def refresh(body: RefreshBody):
    payload = decode_token(body.refresh_token, "refresh")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    doc = await get_users_col().find_one({"id": user_id})
    if not doc or not doc.get("is_active", True):
        raise HTTPException(status_code=401, detail="User no longer active")

    # Flat, unwrapped response — see module docstring; refreshToken() bypasses
    # apiClient and reads this shape directly off the raw axios response.
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "Bearer",
        "user": _doc_to_user(doc),
    }


@router.get("/api/auth/me")
async def me(authorization: Optional[str] = Header(default=None)):
    doc = await get_user_from_bearer(authorization)
    return {"data": _doc_to_user(doc), "success": True}


@router.post("/api/auth/logout")
async def logout(body: LogoutBody | None = None):
    # Stateless JWTs, no revocation store (see module docstring) — logout is
    # effectively client-side. Endpoint exists so the frontend's call succeeds
    # instead of 404ing; nothing to actually invalidate server-side yet.
    return {"data": None, "success": True, "message": "Logged out"}
