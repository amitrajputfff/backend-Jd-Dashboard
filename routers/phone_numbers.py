"""Phone numbers router — LiveKit SIP dispatch rules mapped to assistants OR
workflow bots.

LiveKit is the source of truth. This router:
 - Lists SIP dispatch rules with their trunk DIDs and current bot assignment
   (read from rule.room_config.metadata JSON: {"assistant_id": "..."} — the
   JSON key is a legacy name; the value is really just a bot id, and may name
   either an Assistant or a Workflow Bot doc, since bot_dev.py's entrypoint
   resolves it via the unified /backend/api/bot-config/{id} resolver and
   branches on bot_type — confirmed neither collection is assumed before
   that branch runs, see bot_dev.py ~line 307-322).
 - Assigns/unassigns a bot by patching room_config.metadata on the dispatch rule
   using a fetch-then-replace flow (SIPDispatchRuleUpdate has no room_config field).
 - Rejects modifications to protected rule IDs UNLESS the caller is admin
   (RBAC — see routers/auth.py's module docstring). Protected rule IDs are
   now admin-managed in the protected_dispatch_rules Mongo collection
   (mongo.py's get_protected_rules_col()), not a fixed env var — the env var
   (PROTECTED_DISPATCH_RULE_IDS) is only that collection's one-time
   migration seed (see backend/migrate_rbac.py). Non-admins never even see a
   protected rule in the list.
"""

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

try:
    from ..mongo import get_assistants_col, get_protected_rules_col, get_workflow_bots_col
    from ..audit_log import write_audit_log
    from . import auth
except ImportError:
    from mongo import get_assistants_col, get_protected_rules_col, get_workflow_bots_col
    from audit_log import write_audit_log
    from routers import auth

from livekit.api import LiveKitAPI
from livekit.api.sip_service import ListSIPDispatchRuleRequest, ListSIPInboundTrunkRequest

log = logging.getLogger(__name__)
router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

_LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
_LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
_LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")


async def _get_protected_rule_ids() -> set[str]:
    docs = await get_protected_rules_col().find({}, {"rule_id": 1}).to_list(length=None)
    return {d["rule_id"] for d in docs}


# The one active LiveKit worker (bot_dev.py) — per RUNNING_BOTS.md, the only
# worker that understands Workflow Bots and per-bot Mongo dev/live overrides;
# bot.py/bot_new.py/bot_pipeline.py share a different, legacy agent_name and
# are "not part of the current stack." Every dispatch rule a bot gets assigned
# to should route here — see _ensure_agent_name().
TARGET_AGENT_NAME = os.environ.get("TARGET_AGENT_NAME", "voice-bot-justdial-live-2")

# ── Helpers ───────────────────────────────────────────────────────────────────


def _lkapi() -> LiveKitAPI:
    if not _LIVEKIT_URL:
        raise HTTPException(status_code=503, detail="LIVEKIT_URL is not configured on this server.")
    return LiveKitAPI(url=_LIVEKIT_URL, api_key=_LIVEKIT_API_KEY, api_secret=_LIVEKIT_API_SECRET)


def _get_agent_name(rule) -> str:
    """Extract the first dispatched agent name from rule.room_config.agents.

    NOTE: this used to read `ra.dispatches[].agent_name` — but
    RoomConfiguration.agents is a repeated RoomAgentDispatch, which has
    `agent_name` directly (no nested `.dispatches`; that shape belongs to a
    different, unrelated `RoomAgent` message). The old code always raised
    AttributeError internally, silently swallowed by the bare `except`, so
    this always returned "" regardless of what was actually configured.
    """
    try:
        for ra in rule.room_config.agents:
            if ra.agent_name:
                return ra.agent_name
    except Exception:
        pass
    return ""


def _ensure_agent_name(rule, agent_name: str = TARGET_AGENT_NAME) -> None:
    """Set (or add) a RoomAgentDispatch on `rule.room_config.agents` naming
    `agent_name`, so LiveKit actually dispatches calls on this rule to the
    correct worker pool — previously left as whatever the rule was
    pre-provisioned with, completely independent of which bot got assigned.
    Mutates `rule` in place; caller still needs to update_dispatch_rule(...).
    """
    if rule.room_config.agents:
        rule.room_config.agents[0].agent_name = agent_name
    else:
        rule.room_config.agents.add(agent_name=agent_name)


def _ts_to_iso(proto_timestamp) -> str | None:
    """None means "unknown", not "epoch" — LiveKit's ListSIPDispatchRule doesn't
    populate created_at/updated_at for every rule (seen on rules provisioned
    before the server tracked these), and a protobuf Timestamp field is always
    present with seconds=0 as its zero-value default rather than being unset/
    null, so this can't be told apart from a real timestamp except by value.
    Silently converting that default straight to a date rendered as "1 Jan
    1970" on every affected row instead of showing that the value is missing.
    """
    try:
        secs = proto_timestamp.seconds if hasattr(proto_timestamp, "seconds") else float(proto_timestamp)
        if secs <= 0:
            return None
        return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
    except Exception:
        return None


async def _build_row(rule, trunks_by_id: dict, bots_by_id: dict, protected_ids: set[str]) -> dict:
    trunk_id = rule.trunk_ids[0] if rule.trunk_ids else ""
    trunk = trunks_by_id.get(trunk_id)
    numbers: list[str] = list(trunk.numbers) if trunk else []

    try:
        meta: dict = json.loads(rule.room_config.metadata or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}

    mapped_assistant = None
    aid = meta.get("assistant_id", "")
    if aid:
        a = bots_by_id.get(aid)
        if a:
            mapped_assistant = {
                "id": str(a.get("id", 0)),
                "assistant_id": aid,
                "name": a.get("name", "Unknown"),
                "status": a.get("status", "active"),
                "is_active": a.get("is_active", True),
                "bot_type": a.get("_bot_type", "assistant"),
            }
        else:
            # assistant_id set in LiveKit but not found in either collection — show raw UUID
            mapped_assistant = {
                "id": "0",
                "assistant_id": aid,
                "name": aid,
                "status": "unknown",
                "is_active": True,
                "bot_type": "unknown",
            }

    return {
        "id": rule.sip_dispatch_rule_id,
        "phone_number": ", ".join(numbers) if numbers else rule.name,
        "numbers": numbers,
        "trunk_id": trunk_id,
        "name": rule.name,
        "agent_name": _get_agent_name(rule),
        "mapped_assistant": mapped_assistant,
        "is_protected": rule.sip_dispatch_rule_id in protected_ids,
        "is_active": True,
        "provider_id": None,
        "type": "inbound",
        "description": None,
        "organization_id": "",
        "created_at": _ts_to_iso(rule.created_at),
        "updated_at": _ts_to_iso(rule.updated_at),
    }


async def _fetch_all_rules_and_trunks():
    async with _lkapi() as lk:
        rules_resp = await lk.sip.list_dispatch_rule(ListSIPDispatchRuleRequest())
        trunks_resp = await lk.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
    trunks_by_id = {t.sip_trunk_id: t for t in (trunks_resp.items or [])}
    return list(rules_resp.items or []), trunks_by_id


async def _fetch_rule_by_id(rule_id: str, lk: LiveKitAPI):
    """Fetch a single dispatch rule. Returns the rule object or None."""
    resp = await lk.sip.list_dispatch_rule(ListSIPDispatchRuleRequest())
    return next((r for r in (resp.items or []) if r.sip_dispatch_rule_id == rule_id), None)


async def _fetch_bots_map(bot_ids: set[str]) -> dict:
    """Resolve a set of bot ids against BOTH the assistants and workflow_bots
    collections. Each returned doc gets an internal `_bot_type` key
    ("assistant" | "workflow") so _build_row can label the row; assistants
    win on an id collision (shouldn't happen — both use uuid4 — but keeps
    behavior deterministic)."""
    if not bot_ids:
        return {}
    ids = list(bot_ids)

    assistants_col = get_assistants_col()
    assistant_docs = await assistants_col.find({"assistant_id": {"$in": ids}}).to_list(length=200)

    workflow_bots_col = get_workflow_bots_col()
    workflow_docs = await workflow_bots_col.find({"workflow_bot_id": {"$in": ids}}).to_list(length=200)

    merged: dict = {}
    for d in workflow_docs:
        merged[d["workflow_bot_id"]] = {**d, "_bot_type": "workflow"}
    for d in assistant_docs:
        merged[d["assistant_id"]] = {**d, "_bot_type": "assistant"}
    return merged


def _extract_assistant_ids(rules) -> set[str]:
    ids: set[str] = set()
    for rule in rules:
        try:
            meta = json.loads(rule.room_config.metadata or "{}")
            if meta.get("assistant_id"):
                ids.add(meta["assistant_id"])
        except Exception:
            pass
    return ids


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/api/phone-numbers")
async def list_phone_numbers(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    user: dict = Depends(auth.get_current_user),
):
    try:
        rules, trunks_by_id = await _fetch_all_rules_and_trunks()
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("LiveKit list_dispatch_rule failed")
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    bots_by_id = await _fetch_bots_map(_extract_assistant_ids(rules))
    protected_ids = await _get_protected_rule_ids()
    is_admin = user.get("role") == "admin"

    rows = []
    for rule in rules:
        # Non-admins never see a protected/Live number at all — "those won't
        # show on other accounts" (see routers/auth.py's RBAC docstring).
        if not is_admin and rule.sip_dispatch_rule_id in protected_ids:
            continue
        row = await _build_row(rule, trunks_by_id, bots_by_id, protected_ids)
        if search:
            needle = search.lower()
            searchable = f"{row['phone_number']} {row['name']} {row['agent_name']}".lower()
            if needle not in searchable:
                continue
        rows.append(row)

    total = len(rows)
    page = (skip // limit) + 1 if limit else 1
    return {"phone_numbers": rows[skip: skip + limit], "total": total, "page": page, "limit": limit}


@router.get("/api/phone-numbers/{rule_id}")
async def get_phone_number(rule_id: str, user: dict = Depends(auth.get_current_user)):
    try:
        rules, trunks_by_id = await _fetch_all_rules_and_trunks()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    rule = next((r for r in rules if r.sip_dispatch_rule_id == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Dispatch rule {rule_id!r} not found")

    protected_ids = await _get_protected_rule_ids()
    if user.get("role") != "admin" and rule_id in protected_ids:
        # 404, not 403 — a non-admin probing rule ids shouldn't be able to
        # tell "protected" apart from "doesn't exist".
        raise HTTPException(status_code=404, detail=f"Dispatch rule {rule_id!r} not found")

    bots_by_id = await _fetch_bots_map(_extract_assistant_ids([rule]))
    row = await _build_row(rule, trunks_by_id, bots_by_id, protected_ids)
    return {**row, "provider": None}


@router.post("/api/assistants/{assistant_id}/phone-numbers/{rule_id}")
async def assign_assistant(assistant_id: str, rule_id: str, user: dict = Depends(auth.get_current_user)):
    """Assign a bot (Assistant OR Workflow Bot — `assistant_id` here is really
    just a bot id, kept as the URL/param name for backward compat) to a
    dispatch rule. Only an admin may touch a protected rule; only an admin
    or the bot's own owner may assign that bot at all."""
    is_admin = user.get("role") == "admin"
    protected_ids = await _get_protected_rule_ids()
    if rule_id in protected_ids and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="This dispatch rule is live in production and is protected from modifications.",
        )

    assistants_col = get_assistants_col()
    workflow_bots_col = get_workflow_bots_col()
    is_assistant = await assistants_col.find_one({"assistant_id": assistant_id})
    is_workflow_bot = None if is_assistant else await workflow_bots_col.find_one(
        {"workflow_bot_id": assistant_id}
    )
    bot_doc = is_assistant or is_workflow_bot
    if not bot_doc:
        raise HTTPException(status_code=404, detail=f"No assistant or workflow bot found for id {assistant_id!r}")
    if not is_admin and bot_doc.get("created_by") != user.get("id"):
        raise HTTPException(status_code=404, detail=f"No assistant or workflow bot found for id {assistant_id!r}")

    try:
        async with _lkapi() as lk:
            rule = await _fetch_rule_by_id(rule_id, lk)
            if not rule:
                raise HTTPException(status_code=404, detail=f"Dispatch rule {rule_id!r} not found")

            try:
                meta: dict = json.loads(rule.room_config.metadata or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta["assistant_id"] = assistant_id
            rule.room_config.metadata = json.dumps(meta)
            _ensure_agent_name(rule)

            updated = await lk.sip.update_dispatch_rule(rule_id, rule)

            trunks_resp = await lk.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
            trunks_by_id = {t.sip_trunk_id: t for t in (trunks_resp.items or [])}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Failed to assign assistant %s to rule %s", assistant_id, rule_id)
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    bots_by_id = await _fetch_bots_map({assistant_id})
    row = await _build_row(updated, trunks_by_id, bots_by_id, protected_ids)
    return {**row, "provider": None}


@router.delete("/api/assistants/{assistant_id}/phone-numbers/{rule_id}")
async def unassign_assistant(assistant_id: str, rule_id: str, user: dict = Depends(auth.get_current_user)):
    protected_ids = await _get_protected_rule_ids()
    if rule_id in protected_ids and user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="This dispatch rule is live in production and is protected from modifications.",
        )

    try:
        async with _lkapi() as lk:
            rule = await _fetch_rule_by_id(rule_id, lk)
            if not rule:
                raise HTTPException(status_code=404, detail=f"Dispatch rule {rule_id!r} not found")

            try:
                meta: dict = json.loads(rule.room_config.metadata or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta.pop("assistant_id", None)
            rule.room_config.metadata = json.dumps(meta) if meta else ""
            # Keep the rule pointed at the correct worker pool even while
            # unassigned, so the next assignment (or a stray call in the
            # meantime) doesn't fall back to whatever it was before.
            _ensure_agent_name(rule)

            updated = await lk.sip.update_dispatch_rule(rule_id, rule)

            trunks_resp = await lk.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
            trunks_by_id = {t.sip_trunk_id: t for t in (trunks_resp.items or [])}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Failed to unassign assistant from rule %s", rule_id)
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    row = await _build_row(updated, trunks_by_id, {}, protected_ids)
    return {**row, "provider": None}


# ── Admin: manage the protected/Live set itself ────────────────────────────

@router.post("/api/phone-numbers/{rule_id}/protect")
async def protect_phone_number(rule_id: str, body: dict = None, user: dict = Depends(auth.require_admin)):
    """Admin-only: tag a dispatch rule as Live/protected. This is what makes
    it invisible to non-admins and un-assignable by them — see
    list_phone_numbers/assign_assistant/unassign_assistant above."""
    now = datetime.now(timezone.utc).isoformat()
    await get_protected_rules_col().update_one(
        {"rule_id": rule_id},
        {"$set": {
            "rule_id": rule_id,
            "tagged_by": user["id"],
            "tagged_at": now,
            "note": (body or {}).get("note", ""),
        }},
        upsert=True,
    )
    await write_audit_log(
        user=user, action="phone_number.protected", resource="phone_numbers",
        resource_id=rule_id, details=f"Tagged dispatch rule {rule_id!r} as Live/protected",
    )
    return {"rule_id": rule_id, "is_protected": True}


@router.delete("/api/phone-numbers/{rule_id}/protect")
async def unprotect_phone_number(rule_id: str, user: dict = Depends(auth.require_admin)):
    """Admin-only: remove the Live/protected tag from a dispatch rule."""
    await get_protected_rules_col().delete_one({"rule_id": rule_id})
    await write_audit_log(
        user=user, action="phone_number.unprotected", resource="phone_numbers",
        resource_id=rule_id, details=f"Removed Live/protected tag from dispatch rule {rule_id!r}",
    )
    return {"rule_id": rule_id, "is_protected": False}
