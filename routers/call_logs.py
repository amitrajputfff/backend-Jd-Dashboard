"""Call logs router — MongoDB-backed.

Endpoints:
  POST /api/call-logs          — bot saves a call log after each call
  GET  /api/call-logs          — dashboard lists call logs with pagination/filters
  GET  /api/call-logs/{log_id} — dashboard fetches a single call log
"""

from __future__ import annotations

import json as _json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from ..mongo import get_call_logs_col, get_assistants_col
except ImportError:
    from mongo import get_call_logs_col, get_assistants_col

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "gemini-2.0-flash-lite")

_log = logging.getLogger(__name__)

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


async def _bump_calls_today(assistant_id: str) -> None:
    """Increment the assistant's calls_today counter, resetting it to 1 on a
    new UTC day. Best-effort — a failure here must never fail call-log
    creation (the bot depends on that succeeding to record the call).
    """
    if not assistant_id:
        return
    try:
        col = get_assistants_col()
        today = datetime.now(timezone.utc).date().isoformat()
        doc = await col.find_one({"assistant_id": assistant_id}, {"calls_today_date": 1})
        if doc is None:
            return  # unknown assistant_id — nothing to bump
        if doc.get("calls_today_date") == today:
            await col.update_one({"assistant_id": assistant_id}, {"$inc": {"calls_today": 1}})
        else:
            await col.update_one(
                {"assistant_id": assistant_id},
                {"$set": {"calls_today": 1, "calls_today_date": today}},
            )
    except Exception as e:
        _log.warning(f"[calls_today] Failed to bump for assistant_id={assistant_id!r}: {e}")


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
    await _bump_calls_today(data.assistant_id)
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


# ---------------------------------------------------------------------------
# Reanalyze — re-run LLM analysis on stored transcript
# ---------------------------------------------------------------------------

@router.post("/api/call-logs/{log_id}/reanalyze")
async def reanalyze_call_log(log_id: str):
    col = get_call_logs_col()

    doc = None
    try:
        doc = await col.find_one({"_id": ObjectId(log_id)})
    except Exception:
        pass
    if doc is None:
        doc = await col.find_one({"call_sid": log_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Call log not found")

    # Get analysis_prompt from the assistant's config
    analysis_prompt_override = ""
    assistant_id = doc.get("assistant_id") or doc.get("meta_data", {}).get("assistant_id")
    if assistant_id:
        a_col = get_assistants_col()
        agent_doc = await a_col.find_one({"assistant_id": assistant_id})
        if agent_doc:
            analysis_prompt_override = agent_doc.get("analysis_prompt") or ""

    transcripts = doc.get("transcripts") or []
    muted_transcripts = doc.get("muted_transcript") or doc.get("muted_transcripts") or []
    qual_schema = (doc.get("lead_record") or {}).get("qualification_schema") or {}

    # Build transcript text
    lines = "\n".join(f"{t.get('speaker','?').upper()}: {t.get('text','')}" for t in transcripts if t.get("text"))
    muted_lines = "\n".join(f"[MUTED USER]: {m}" for m in (muted_transcripts if isinstance(muted_transcripts, list) else []) if isinstance(m, str) and m.strip())

    if not lines:
        raise HTTPException(status_code=422, detail="No transcript to analyse")

    # Use custom analysis_prompt if set, otherwise a compact default
    if analysis_prompt_override.strip():
        prompt = analysis_prompt_override.replace("{transcript}", lines).replace("{muted_transcript}", muted_lines)
    else:
        prompt = f"""You are a call-analysis engine for Justdial AI outbound qualification calls.
Analyse the transcript and return a JSON object with keys:
  call_outcome (string), call_outcome_description (string), call_summary (string).

TRANSCRIPT:
{lines}
{muted_lines}

Return only valid JSON, no markdown."""

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured on backend")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{ANALYSIS_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }

    import asyncio
    def _call_gemini():
        req = urllib.request.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return _json.loads(r.read().decode())

    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, _call_gemini)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {e}")

    try:
        text_out = raw["candidates"][0]["content"]["parts"][0]["text"]
        result = _json.loads(text_out)
    except Exception:
        raise HTTPException(status_code=502, detail="Could not parse Gemini response")

    update_fields: dict = {"updated_at": datetime.utcnow()}
    if "call_outcome" in result:
        update_fields["outcome"] = result["call_outcome"]
    if "call_summary" in result:
        update_fields["summary"] = result["call_summary"]
    if "call_outcome_description" in result:
        update_fields.setdefault("meta_data", {})
        update_fields["meta_data.call_outcome_desc"] = result["call_outcome_description"]

    await col.update_one({"_id": doc["_id"]}, {"$set": update_fields})

    return {
        "outcome": update_fields.get("outcome"),
        "summary": update_fields.get("summary"),
        "meta_data": {"call_outcome_desc": result.get("call_outcome_description")},
        "raw": result,
    }
