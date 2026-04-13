"""Call logs router — MongoDB-backed.

Endpoints:
  POST /api/call-logs          — bot saves a call log after each call
  GET  /api/call-logs          — dashboard lists call logs with pagination/filters
  GET  /api/call-logs/{log_id} — dashboard fetches a single call log
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from ..mongo import get_call_logs_col
except ImportError:
    from mongo import get_call_logs_col

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schema (sent by the bot after each call)
# ---------------------------------------------------------------------------

class CreateCallLogRequest(BaseModel):
    call_sid: str = ""
    stream_id: str = ""
    from_number: str = ""
    to_number: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    recording_link: Optional[str] = None
    organization_id: str = ""
    assistant_id: str = ""
    is_transfered: bool = False
    transfer_number: Optional[str] = None
    status: str = "completed"
    summary: Optional[str] = None
    meta_data: Dict[str, Any] = Field(default_factory=dict)
    metrics: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    sentiment: str = "neutral"
    outcome: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    call_type: str = "inbound"
    insights: List[Dict[str, Any]] = Field(default_factory=list)
    key_events: List[Dict[str, Any]] = Field(default_factory=list)
    customer_satisfaction: Optional[int] = None
    agent_performance: Optional[int] = None
    transcripts: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_doc(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-serialisable dict.

    • Moves ``_id`` (ObjectId) → ``id`` (string)
    • Converts ``datetime`` values to ISO-8601 strings
    """
    doc = dict(doc)
    oid = doc.pop("_id", None)
    doc["id"] = str(oid) if oid else doc.get("id", "")
    for key, val in list(doc.items()):
        if isinstance(val, datetime):
            doc[key] = val.isoformat()
    return doc


# ---------------------------------------------------------------------------
# POST /api/call-logs  — create
# ---------------------------------------------------------------------------

@router.post("/api/call-logs", status_code=201)
async def create_call_log(data: CreateCallLogRequest):
    col = get_call_logs_col()
    now = datetime.utcnow().isoformat()
    doc = data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    result = await col.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# GET /api/call-logs  — list with pagination + filters
# ---------------------------------------------------------------------------

@router.get("/api/call-logs")
async def list_call_logs(
    organization_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    call_type: Optional[str] = Query(None),
):
    col = get_call_logs_col()

    query: dict = {"organization_id": organization_id}

    if status:
        query["status"] = status
    if call_type:
        query["call_type"] = call_type
    if search:
        pattern = re.escape(search)
        query["$or"] = [
            {"from_number": {"$regex": pattern, "$options": "i"}},
            {"to_number": {"$regex": pattern, "$options": "i"}},
            {"summary": {"$regex": pattern, "$options": "i"}},
        ]

    total = await col.count_documents(query)
    cursor = col.find(query).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)

    return {
        "call_logs": [_serialize_doc(d) for d in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# GET /api/call-logs/{log_id}  — fetch single
# ---------------------------------------------------------------------------

@router.get("/api/call-logs/{log_id}")
async def get_call_log(log_id: str):
    col = get_call_logs_col()

    doc = None
    # Try ObjectId first (24-hex-char string)
    try:
        oid = ObjectId(log_id)
        doc = await col.find_one({"_id": oid})
    except Exception:
        pass

    # Fall back: match by call_sid
    if doc is None:
        doc = await col.find_one({"call_sid": log_id})

    if doc is None:
        raise HTTPException(status_code=404, detail="Call log not found")

    return _serialize_doc(doc)
