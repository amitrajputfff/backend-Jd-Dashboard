"""Phone numbers router — LiveKit SIP dispatch rules mapped to assistants.

LiveKit is the source of truth. This router:
 - Lists SIP dispatch rules with their trunk DIDs and current assistant assignment
   (read from rule.room_config.metadata JSON: {"assistant_id": "..."}).
 - Assigns/unassigns an assistant by patching room_config.metadata on the dispatch rule
   using a fetch-then-replace flow (SIPDispatchRuleUpdate has no room_config field).
 - Rejects modifications to protected rule IDs (PROTECTED_DISPATCH_RULE_IDS env var).
"""

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

try:
    from ..mongo import get_assistants_col
except ImportError:
    from mongo import get_assistants_col

from livekit.api import LiveKitAPI
from livekit.api.sip_service import ListSIPDispatchRuleRequest, ListSIPInboundTrunkRequest

log = logging.getLogger(__name__)
router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

_LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
_LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
_LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")

_protected_env = os.environ.get("PROTECTED_DISPATCH_RULE_IDS", "SDR_CSA2NurhzDxz")
PROTECTED_RULE_IDS: set[str] = {r.strip() for r in _protected_env.split(",") if r.strip()}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _lkapi() -> LiveKitAPI:
    if not _LIVEKIT_URL:
        raise HTTPException(status_code=503, detail="LIVEKIT_URL is not configured on this server.")
    return LiveKitAPI(url=_LIVEKIT_URL, api_key=_LIVEKIT_API_KEY, api_secret=_LIVEKIT_API_SECRET)


def _get_agent_name(rule) -> str:
    """Extract the first dispatched agent name from rule.room_config.agents."""
    try:
        for ra in rule.room_config.agents:
            for dispatch in ra.dispatches:
                if dispatch.agent_name:
                    return dispatch.agent_name
    except Exception:
        pass
    return ""


def _ts_to_iso(proto_timestamp) -> str:
    try:
        secs = proto_timestamp.seconds if hasattr(proto_timestamp, "seconds") else float(proto_timestamp)
        return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat()


async def _build_row(rule, trunks_by_id: dict, assistants_by_id: dict) -> dict:
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
        a = assistants_by_id.get(aid)
        if a:
            mapped_assistant = {
                "id": str(a.get("id", 0)),
                "assistant_id": aid,
                "name": a.get("name", "Unknown"),
                "status": a.get("status", "active"),
                "is_active": a.get("is_active", True),
            }
        else:
            # assistant_id set in LiveKit but not found in Mongo — show raw UUID
            mapped_assistant = {
                "id": "0",
                "assistant_id": aid,
                "name": aid,
                "status": "unknown",
                "is_active": True,
            }

    return {
        "id": rule.sip_dispatch_rule_id,
        "phone_number": ", ".join(numbers) if numbers else rule.name,
        "numbers": numbers,
        "trunk_id": trunk_id,
        "name": rule.name,
        "agent_name": _get_agent_name(rule),
        "mapped_assistant": mapped_assistant,
        "is_protected": rule.sip_dispatch_rule_id in PROTECTED_RULE_IDS,
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


async def _fetch_assistants_map(assistant_ids: set[str]) -> dict:
    if not assistant_ids:
        return {}
    col = get_assistants_col()
    docs = await col.find({"assistant_id": {"$in": list(assistant_ids)}}).to_list(length=200)
    return {d["assistant_id"]: d for d in docs}


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
    organization_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
):
    try:
        rules, trunks_by_id = await _fetch_all_rules_and_trunks()
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("LiveKit list_dispatch_rule failed")
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    assistants_by_id = await _fetch_assistants_map(_extract_assistant_ids(rules))

    rows = []
    for rule in rules:
        row = await _build_row(rule, trunks_by_id, assistants_by_id)
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
async def get_phone_number(rule_id: str):
    try:
        rules, trunks_by_id = await _fetch_all_rules_and_trunks()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    rule = next((r for r in rules if r.sip_dispatch_rule_id == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Dispatch rule {rule_id!r} not found")

    assistants_by_id = await _fetch_assistants_map(_extract_assistant_ids([rule]))
    row = await _build_row(rule, trunks_by_id, assistants_by_id)
    return {**row, "provider": None}


@router.post("/api/assistants/{assistant_id}/phone-numbers/{rule_id}")
async def assign_assistant(assistant_id: str, rule_id: str):
    if rule_id in PROTECTED_RULE_IDS:
        raise HTTPException(
            status_code=403,
            detail="This dispatch rule is live in production and is protected from modifications.",
        )

    col = get_assistants_col()
    if not await col.find_one({"assistant_id": assistant_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"Assistant {assistant_id!r} not found")

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

            updated = await lk.sip.update_dispatch_rule(rule_id, rule)

            trunks_resp = await lk.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
            trunks_by_id = {t.sip_trunk_id: t for t in (trunks_resp.items or [])}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Failed to assign assistant %s to rule %s", assistant_id, rule_id)
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    assistants_by_id = await _fetch_assistants_map({assistant_id})
    row = await _build_row(updated, trunks_by_id, assistants_by_id)
    return {**row, "provider": None}


@router.delete("/api/assistants/{assistant_id}/phone-numbers/{rule_id}")
async def unassign_assistant(assistant_id: str, rule_id: str):
    if rule_id in PROTECTED_RULE_IDS:
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

            updated = await lk.sip.update_dispatch_rule(rule_id, rule)

            trunks_resp = await lk.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
            trunks_by_id = {t.sip_trunk_id: t for t in (trunks_resp.items or [])}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Failed to unassign assistant from rule %s", rule_id)
        raise HTTPException(status_code=502, detail=f"LiveKit error: {exc}") from exc

    row = await _build_row(updated, trunks_by_id, {})
    return {**row, "provider": None}
