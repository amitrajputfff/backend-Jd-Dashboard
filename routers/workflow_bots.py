"""Workflow Bots router — MongoDB-backed (no_code_platform.workflow_bots).

Visual conversation-flow bots built in the ReactFlow canvas.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

try:
    from ..mongo import get_workflow_bots_col, next_sequence
    from ..schemas import (
        CreateWorkflowBotRequest,
        UpdateWorkflowBotRequest,
        WorkflowBotConfig,
        WorkflowBotResponse,
        WorkflowBotsListResponse,
    )
except ImportError:
    from mongo import get_workflow_bots_col, next_sequence
    from schemas import (
        CreateWorkflowBotRequest,
        UpdateWorkflowBotRequest,
        WorkflowBotConfig,
        WorkflowBotResponse,
        WorkflowBotsListResponse,
    )

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _doc_to_response(doc: dict) -> WorkflowBotResponse:
    return WorkflowBotResponse(
        id=doc.get("id", 0),
        workflow_bot_id=doc["workflow_bot_id"],
        organization_id=doc.get("organization_id", ""),
        name=doc.get("name", ""),
        description=doc.get("description", ""),
        status=doc.get("status", "Draft"),
        global_prompt=doc.get("global_prompt", ""),
        workflow=doc.get("workflow", {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}),
        language=doc.get("language", "hindi"),
        temperature=doc.get("temperature", 0.7),
        gemini_start_sensitivity=doc.get("gemini_start_sensitivity", "START_SENSITIVITY_LOW"),
        gemini_end_sensitivity=doc.get("gemini_end_sensitivity", "END_SENSITIVITY_HIGH"),
        gemini_silence_duration_ms=doc.get("gemini_silence_duration_ms", 800),
        gemini_prefix_padding_ms=doc.get("gemini_prefix_padding_ms", 100),
        max_call_duration=doc.get("max_call_duration", 300),
        filler_message=doc.get("filler_message", []),
        function_filler_message=doc.get("function_filler_message", []),
        sarvam_min_rms=doc.get("sarvam_min_rms", 600),
        sarvam_min_speech_ms=doc.get("sarvam_min_speech_ms", 500),
        sarvam_min_speech_ms_singleword=doc.get("sarvam_min_speech_ms_singleword", 800),
        sarvam_silero_threshold=doc.get("sarvam_silero_threshold", 0.5),
        sarvam_silero_min_speech_ms=doc.get("sarvam_silero_min_speech_ms", 120),
        gemini_silero_fallback_speech_ms=doc.get("gemini_silero_fallback_speech_ms", 150),
        post_speech_hold_ms=doc.get("post_speech_hold_ms", 300),
        inactivity_first_rescue_secs=doc.get("inactivity_first_rescue_secs", 4.0),
        inactivity_first_nudge_gap_secs=doc.get("inactivity_first_nudge_gap_secs", 4.0),
        inactivity_nudge_secs=doc.get("inactivity_nudge_secs", 10.0),
        inactivity_close_secs=doc.get("inactivity_close_secs", 5.0),
        inactivity_phrase=doc.get("inactivity_phrase", "क्या आप अभी line पर हैं?"),
        inactivity_end_phrase=doc.get("inactivity_end_phrase", "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."),
        lang_notes=doc.get("lang_notes", ""),
        analysis_prompt=doc.get("analysis_prompt", ""),
        is_deleted=bool(doc.get("is_deleted", False)),
        deleted_until=doc.get("deleted_until"),
        is_active=bool(doc.get("is_active", True)),
        created_at=_fmt_dt(doc.get("created_at")),
        updated_at=_fmt_dt(doc.get("updated_at")),
        calls_today=doc.get("calls_today", 0),
    )


async def _get_or_404(workflow_bot_id: str) -> dict:
    col = get_workflow_bots_col()
    doc = await col.find_one({"workflow_bot_id": workflow_bot_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Workflow bot {workflow_bot_id!r} not found")
    return doc


def _new_doc(data: CreateWorkflowBotRequest, wid: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": wid,
        "workflow_bot_id": str(uuid.uuid4()),
        "organization_id": data.organization_id,
        "name": data.name,
        "description": data.description or "",
        "status": data.status or "Draft",
        "global_prompt": data.global_prompt or "",
        "workflow": data.workflow.model_dump(),
        "language": data.language or "hindi",
        "temperature": data.temperature if data.temperature is not None else 0.7,
        "gemini_start_sensitivity": data.gemini_start_sensitivity or "START_SENSITIVITY_LOW",
        "gemini_end_sensitivity": data.gemini_end_sensitivity or "END_SENSITIVITY_HIGH",
        "gemini_silence_duration_ms": data.gemini_silence_duration_ms if data.gemini_silence_duration_ms is not None else 800,
        "gemini_prefix_padding_ms": data.gemini_prefix_padding_ms if data.gemini_prefix_padding_ms is not None else 100,
        "max_call_duration": data.max_call_duration if data.max_call_duration is not None else 300,
        "filler_message": data.filler_message or [],
        "function_filler_message": data.function_filler_message or [],
        "sarvam_min_rms": data.sarvam_min_rms if data.sarvam_min_rms is not None else 600,
        "sarvam_min_speech_ms": data.sarvam_min_speech_ms if data.sarvam_min_speech_ms is not None else 500,
        "sarvam_min_speech_ms_singleword": data.sarvam_min_speech_ms_singleword if data.sarvam_min_speech_ms_singleword is not None else 800,
        "sarvam_silero_threshold": data.sarvam_silero_threshold if data.sarvam_silero_threshold is not None else 0.5,
        "sarvam_silero_min_speech_ms": data.sarvam_silero_min_speech_ms if data.sarvam_silero_min_speech_ms is not None else 120,
        "gemini_silero_fallback_speech_ms": data.gemini_silero_fallback_speech_ms if data.gemini_silero_fallback_speech_ms is not None else 150,
        "post_speech_hold_ms": data.post_speech_hold_ms if data.post_speech_hold_ms is not None else 300,
        "inactivity_first_rescue_secs": data.inactivity_first_rescue_secs if data.inactivity_first_rescue_secs is not None else 4.0,
        "inactivity_first_nudge_gap_secs": data.inactivity_first_nudge_gap_secs if data.inactivity_first_nudge_gap_secs is not None else 4.0,
        "inactivity_nudge_secs": data.inactivity_nudge_secs if data.inactivity_nudge_secs is not None else 10.0,
        "inactivity_close_secs": data.inactivity_close_secs if data.inactivity_close_secs is not None else 5.0,
        "inactivity_phrase": data.inactivity_phrase or "क्या आप अभी line पर हैं?",
        "inactivity_end_phrase": data.inactivity_end_phrase or "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद.",
        "lang_notes": data.lang_notes or "",
        "analysis_prompt": data.analysis_prompt or "",
        "is_deleted": False,
        "is_active": True,
        "calls_today": 0,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# 1. List workflow bots
# ---------------------------------------------------------------------------

@router.get("/api/workflow-bots", response_model=WorkflowBotsListResponse)
async def list_workflow_bots(
    organization_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
    is_deleted: bool = Query(False),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("updated_at"),
    sort_order: Optional[str] = Query("desc"),
    status: Optional[str] = Query(None),
):
    col = get_workflow_bots_col()
    query: dict = {"organization_id": organization_id, "is_deleted": is_deleted}

    if status:
        query["status"] = status
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]

    sort_dir = 1 if sort_order == "asc" else -1
    total = await col.count_documents(query)
    cursor = col.find(query).sort(sort_by or "updated_at", sort_dir).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return WorkflowBotsListResponse(workflow_bots=[_doc_to_response(d) for d in docs], total=total)


# ---------------------------------------------------------------------------
# 2. Create workflow bot
# ---------------------------------------------------------------------------

@router.post("/api/workflow-bots", response_model=WorkflowBotResponse, status_code=201)
async def create_workflow_bot(data: CreateWorkflowBotRequest):
    col = get_workflow_bots_col()
    wid = await next_sequence("workflow_bot_id")
    doc = _new_doc(data, wid)
    await col.insert_one(doc)
    return _doc_to_response(doc)


# ---------------------------------------------------------------------------
# 3. Get by ID
# ---------------------------------------------------------------------------

@router.get("/api/workflow-bots/{workflow_bot_id}", response_model=WorkflowBotResponse)
async def get_workflow_bot(workflow_bot_id: str):
    return _doc_to_response(await _get_or_404(workflow_bot_id))


# ---------------------------------------------------------------------------
# 4. Update
# ---------------------------------------------------------------------------

@router.put("/api/workflow-bots/{workflow_bot_id}", response_model=WorkflowBotResponse)
async def update_workflow_bot(workflow_bot_id: str, data: UpdateWorkflowBotRequest):
    col = get_workflow_bots_col()
    await _get_or_404(workflow_bot_id)
    raw = data.model_dump(exclude_none=True)
    # Serialize nested Workflow object to plain dict for Mongo
    if "workflow" in raw and hasattr(data.workflow, "model_dump"):
        raw["workflow"] = data.workflow.model_dump()
    raw["updated_at"] = datetime.now(timezone.utc)
    await col.update_one({"workflow_bot_id": workflow_bot_id}, {"$set": raw})
    doc = await col.find_one({"workflow_bot_id": workflow_bot_id})
    return _doc_to_response(doc)


# ---------------------------------------------------------------------------
# 5. Soft delete
# ---------------------------------------------------------------------------

@router.delete("/api/workflow-bots/{workflow_bot_id}")
async def delete_workflow_bot(workflow_bot_id: str):
    col = get_workflow_bots_col()
    await _get_or_404(workflow_bot_id)
    now = datetime.now(timezone.utc)
    await col.update_one(
        {"workflow_bot_id": workflow_bot_id},
        {"$set": {
            "is_deleted": True,
            "is_active": False,
            "deleted_until": (now + timedelta(days=7)).isoformat(),
            "updated_at": now,
        }},
    )
    return {"message": "Workflow bot deleted", "workflow_bot_id": workflow_bot_id}


# ---------------------------------------------------------------------------
# 6. Restore
# ---------------------------------------------------------------------------

@router.post("/api/workflow-bots/{workflow_bot_id}/restore", response_model=WorkflowBotResponse)
async def restore_workflow_bot(workflow_bot_id: str):
    col = get_workflow_bots_col()
    doc = await col.find_one({"workflow_bot_id": workflow_bot_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Workflow bot not found")
    await col.update_one(
        {"workflow_bot_id": workflow_bot_id},
        {"$set": {
            "is_deleted": False,
            "is_active": True,
            "deleted_until": None,
            "status": "Draft",
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    doc = await col.find_one({"workflow_bot_id": workflow_bot_id})
    return _doc_to_response(doc)


# ---------------------------------------------------------------------------
# 7. Clone
# ---------------------------------------------------------------------------

@router.post("/api/workflow-bots/{workflow_bot_id}/clone", response_model=WorkflowBotResponse)
async def clone_workflow_bot(workflow_bot_id: str, body: dict = None):
    col = get_workflow_bots_col()
    original = await _get_or_404(workflow_bot_id)
    new_name = (body or {}).get("name") or f"{original['name']} (Copy)"
    wid = await next_sequence("workflow_bot_id")
    now = datetime.now(timezone.utc)
    clone = {**original, "_id": None}
    clone.pop("_id", None)
    clone["id"] = wid
    clone["workflow_bot_id"] = str(uuid.uuid4())
    clone["name"] = new_name
    clone["status"] = "Draft"
    clone["is_deleted"] = False
    clone["is_active"] = True
    clone["deleted_until"] = None
    clone["calls_today"] = 0
    clone["created_at"] = now
    clone["updated_at"] = now
    await col.insert_one(clone)
    return _doc_to_response(clone)


# ---------------------------------------------------------------------------
# 8. Bot config endpoint — consumed by bot.py at call start
# ---------------------------------------------------------------------------

@router.get("/api/workflow-bots/{workflow_bot_id}/bot-config", response_model=WorkflowBotConfig)
async def get_workflow_bot_config(workflow_bot_id: str):
    doc = await _get_or_404(workflow_bot_id)
    return WorkflowBotConfig(
        bot_type="workflow",
        workflow_bot_id=doc["workflow_bot_id"],
        organization_id=doc.get("organization_id", ""),
        global_prompt=doc.get("global_prompt", ""),
        workflow=doc.get("workflow", {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}),
        language=doc.get("language", "hindi"),
        temperature=doc.get("temperature", 0.7),
        gemini_start_sensitivity=doc.get("gemini_start_sensitivity", "START_SENSITIVITY_LOW"),
        gemini_end_sensitivity=doc.get("gemini_end_sensitivity", "END_SENSITIVITY_HIGH"),
        gemini_silence_duration_ms=doc.get("gemini_silence_duration_ms", 800),
        gemini_prefix_padding_ms=doc.get("gemini_prefix_padding_ms", 100),
        max_call_duration=doc.get("max_call_duration", 300),
        filler_message=doc.get("filler_message", []),
        function_filler_message=doc.get("function_filler_message", []),
        sarvam_min_rms=doc.get("sarvam_min_rms", 600),
        sarvam_min_speech_ms=doc.get("sarvam_min_speech_ms", 500),
        sarvam_min_speech_ms_singleword=doc.get("sarvam_min_speech_ms_singleword", 800),
        sarvam_silero_threshold=doc.get("sarvam_silero_threshold", 0.5),
        sarvam_silero_min_speech_ms=doc.get("sarvam_silero_min_speech_ms", 120),
        gemini_silero_fallback_speech_ms=doc.get("gemini_silero_fallback_speech_ms", 150),
        post_speech_hold_ms=doc.get("post_speech_hold_ms", 300),
        inactivity_first_rescue_secs=doc.get("inactivity_first_rescue_secs", 4.0),
        inactivity_first_nudge_gap_secs=doc.get("inactivity_first_nudge_gap_secs", 4.0),
        inactivity_nudge_secs=doc.get("inactivity_nudge_secs", 10.0),
        inactivity_close_secs=doc.get("inactivity_close_secs", 5.0),
        inactivity_phrase=doc.get("inactivity_phrase", "क्या आप अभी line पर हैं?"),
        inactivity_end_phrase=doc.get("inactivity_end_phrase", "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."),
        lang_notes=doc.get("lang_notes", ""),
        analysis_prompt=doc.get("analysis_prompt", ""),
    )
