"""Go-Live requests — the non-admin side of the Transfer-to-Live flow (see
routers/admin.py's module docstring). A user who owns a draft/active
assistant or workflow bot can ask an admin to promote it to Live instead of
being able to flip is_locked themselves (that flag is admin-only now — see
routers/assistants.py's update_assistant). An admin approves (which calls
straight into admin.transfer_to_live so the two "become Live" paths never
drift) or rejects with an optional note.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from ..mongo import get_golive_requests_col, next_sequence
    from ..audit_log import write_audit_log
    from . import auth
    from .admin import Resource, resource_col, resource_id_field, transfer_to_live
except ImportError:
    from mongo import get_golive_requests_col, next_sequence
    from audit_log import write_audit_log
    from routers import auth
    from routers.admin import Resource, resource_col, resource_id_field, transfer_to_live

router = APIRouter()

Status = Literal["pending", "approved", "rejected"]


class CreateGoLiveRequestBody(BaseModel):
    resource: Resource
    resource_id: str
    note: Optional[str] = ""


class ReviewGoLiveRequestBody(BaseModel):
    note: Optional[str] = ""


def _doc_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "resource": doc["resource"],
        "resource_id": doc["resource_id"],
        "resource_name": doc.get("resource_name", ""),
        "requested_by": doc.get("requested_by"),
        "status": doc.get("status", "pending"),
        "reviewed_by": doc.get("reviewed_by"),
        "created_at": doc.get("created_at", ""),
        "reviewed_at": doc.get("reviewed_at"),
        "note": doc.get("note", ""),
    }


@router.post("/api/golive-requests")
async def create_golive_request(body: CreateGoLiveRequestBody, user: dict = Depends(auth.get_current_user)):
    doc = await resource_col(body.resource).find_one({resource_id_field(body.resource): body.resource_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"{body.resource} {body.resource_id!r} not found")
    if doc.get("is_locked"):
        raise HTTPException(status_code=400, detail="This agent is already Live.")
    if user.get("role") != "admin" and doc.get("created_by") != user.get("id"):
        raise HTTPException(status_code=404, detail=f"{body.resource} {body.resource_id!r} not found")

    requests_col = get_golive_requests_col()
    existing = await requests_col.find_one({
        "resource": body.resource, "resource_id": body.resource_id, "status": "pending",
    })
    if existing:
        raise HTTPException(status_code=409, detail="A Go-Live request for this agent is already pending.")

    req_id = await next_sequence("golive_request_id")
    now = datetime.now(timezone.utc).isoformat()
    new_doc = {
        "id": req_id,
        "resource": body.resource,
        "resource_id": body.resource_id,
        "resource_name": doc.get("name", ""),
        "requested_by": user["id"],
        "status": "pending",
        "reviewed_by": None,
        "created_at": now,
        "reviewed_at": None,
        "note": body.note or "",
    }
    await requests_col.insert_one(new_doc)
    await write_audit_log(
        user=user, action="golive_request.created", resource=body.resource,
        resource_id=body.resource_id, details=f"Requested Go-Live for {doc.get('name', '')!r}",
    )
    return _doc_out(new_doc)


@router.get("/api/golive-requests")
async def list_golive_requests(status: Optional[Status] = None, user: dict = Depends(auth.get_current_user)):
    query: dict = {} if user.get("role") == "admin" else {"requested_by": user["id"]}
    if status:
        query["status"] = status
    docs = await get_golive_requests_col().find(query).sort("created_at", -1).to_list(length=500)
    return {"requests": [_doc_out(d) for d in docs], "total": len(docs)}


@router.post("/api/golive-requests/{request_id}/approve")
async def approve_golive_request(request_id: int, body: ReviewGoLiveRequestBody = None, admin: dict = Depends(auth.require_admin)):
    requests_col = get_golive_requests_col()
    req = await requests_col.find_one({"id": request_id})
    if req is None:
        raise HTTPException(status_code=404, detail=f"Go-Live request {request_id} not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {req.get('status')}.")

    await transfer_to_live(req["resource"], req["resource_id"], admin)

    now = datetime.now(timezone.utc).isoformat()
    await requests_col.update_one(
        {"id": request_id},
        {"$set": {
            "status": "approved", "reviewed_by": admin["id"], "reviewed_at": now,
            "note": (body or ReviewGoLiveRequestBody()).note or req.get("note", ""),
        }},
    )
    req = await requests_col.find_one({"id": request_id})
    return _doc_out(req)


@router.post("/api/golive-requests/{request_id}/reject")
async def reject_golive_request(request_id: int, body: ReviewGoLiveRequestBody = None, admin: dict = Depends(auth.require_admin)):
    requests_col = get_golive_requests_col()
    req = await requests_col.find_one({"id": request_id})
    if req is None:
        raise HTTPException(status_code=404, detail=f"Go-Live request {request_id} not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {req.get('status')}.")

    now = datetime.now(timezone.utc).isoformat()
    note = (body or ReviewGoLiveRequestBody()).note or ""
    await requests_col.update_one(
        {"id": request_id},
        {"$set": {"status": "rejected", "reviewed_by": admin["id"], "reviewed_at": now, "note": note}},
    )
    await write_audit_log(
        user=admin, action="golive_request.rejected", resource=req["resource"],
        resource_id=req["resource_id"], details=f"Rejected Go-Live request for {req.get('resource_name', '')!r}"
        + (f": {note}" if note else ""),
    )
    req = await requests_col.find_one({"id": request_id})
    return _doc_out(req)
