"""Admin-only agent lifecycle actions — promoting/demoting Live status by id.

This is the "Transfer to Live" flow from routers/auth.py's RBAC docstring:
once an assistant or workflow bot is Live (is_locked=True), it leaves its
owner's list entirely and becomes visible only to admins (see
routers/assistants.py / routers/workflow_bots.py's list_* visibility split).
Getting an agent OUT of that state (demoting it) is the same admin action in
reverse — remove-from-live. The other way an agent goes Live is an approved
request — see routers/golive.py, which calls back into
transfer_to_live()/remove_from_live() below so the two paths can't drift.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from ..mongo import get_assistants_col, get_workflow_bots_col
    from ..audit_log import write_audit_log
    from . import auth
except ImportError:
    from mongo import get_assistants_col, get_workflow_bots_col
    from audit_log import write_audit_log
    from routers import auth

router = APIRouter()

Resource = Literal["assistants", "workflow_bots"]


class TransferToLiveBody(BaseModel):
    resource: Resource
    resource_id: str


def resource_col(resource: Resource):
    return get_assistants_col() if resource == "assistants" else get_workflow_bots_col()


def resource_id_field(resource: Resource) -> str:
    return "assistant_id" if resource == "assistants" else "workflow_bot_id"


async def _get_or_404(resource: Resource, resource_id: str) -> dict:
    doc = await resource_col(resource).find_one({resource_id_field(resource): resource_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"{resource} {resource_id!r} not found")
    return doc


async def transfer_to_live(resource: Resource, resource_id: str, admin: dict) -> dict:
    """Shared by this router's endpoint and an approved routers/golive.py
    request — sets is_locked=True and audit-logs it. Leaves `created_by`
    untouched so provenance survives the move to the admin-only Live pool."""
    doc = await _get_or_404(resource, resource_id)
    now = datetime.now(timezone.utc)
    await resource_col(resource).update_one(
        {resource_id_field(resource): resource_id},
        {"$set": {"is_locked": True, "updated_at": now}},
    )
    await write_audit_log(
        user=admin, action="agent.transferred_to_live", resource=resource,
        resource_id=resource_id, details=f"Transferred {doc.get('name', '')!r} to Live",
        severity="medium",
    )
    return {**doc, "is_locked": True}


async def remove_from_live(resource: Resource, resource_id: str, admin: dict) -> dict:
    doc = await _get_or_404(resource, resource_id)
    now = datetime.now(timezone.utc)
    await resource_col(resource).update_one(
        {resource_id_field(resource): resource_id},
        {"$set": {"is_locked": False, "updated_at": now}},
    )
    await write_audit_log(
        user=admin, action="agent.removed_from_live", resource=resource,
        resource_id=resource_id, details=f"Removed {doc.get('name', '')!r} from Live",
        severity="medium",
    )
    return {**doc, "is_locked": False}


@router.post("/api/admin/agents/transfer-to-live")
async def transfer_to_live_endpoint(body: TransferToLiveBody, admin: dict = Depends(auth.require_admin)):
    doc = await transfer_to_live(body.resource, body.resource_id, admin)
    return {"resource": body.resource, "resource_id": body.resource_id, "name": doc.get("name", ""), "is_locked": True}


@router.post("/api/admin/agents/remove-from-live")
async def remove_from_live_endpoint(body: TransferToLiveBody, admin: dict = Depends(auth.require_admin)):
    doc = await remove_from_live(body.resource, body.resource_id, admin)
    return {"resource": body.resource, "resource_id": body.resource_id, "name": doc.get("name", ""), "is_locked": False}
