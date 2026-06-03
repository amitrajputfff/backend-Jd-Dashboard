"""Assistants router — MongoDB-backed (no_code_platform.assistants)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query

try:
    from ..mongo import get_assistants_col, next_sequence
    from ..schemas import (
        AssistantResponse,
        AssistantsListResponse,
        BotConfig,
        CreateAssistantRequest,
        UpdateAssistantRequest,
    )
except ImportError:
    from mongo import get_assistants_col, next_sequence
    from schemas import (
        AssistantResponse,
        AssistantsListResponse,
        BotConfig,
        CreateAssistantRequest,
        UpdateAssistantRequest,
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


def _doc_to_response(doc: dict) -> AssistantResponse:
    return AssistantResponse(
        id=doc.get("id", 0),
        assistant_id=doc["assistant_id"],
        organization_id=doc.get("organization_id", ""),
        name=doc.get("name", ""),
        description=doc.get("description", ""),
        category=doc.get("category", "Customer Service"),
        tags=doc.get("tags", []),
        status=doc.get("status", "Draft"),
        prompt=doc.get("prompt", ""),
        initial_message=doc.get("initial_message", ""),
        call_end_text=doc.get("call_end_text", ""),
        mis_api_base=doc.get("mis_api_base", ""),
        callback_api_url=doc.get("callback_api_url", ""),
        category_change_api=doc.get("category_change_api", ""),
        script_rule=doc.get("script_rule", ""),
        opening_instruction=doc.get("opening_instruction", ""),
        closing_instruction=doc.get("closing_instruction", ""),
        timeout_message=doc.get("timeout_message", ""),
        function_calling=bool(doc.get("function_calling", False)),
        functions=doc.get("functions", []),
        is_deleted=bool(doc.get("is_deleted", False)),
        deleted_until=doc.get("deleted_until"),
        is_active=bool(doc.get("is_active", True)),
        created_at=_fmt_dt(doc.get("created_at")),
        updated_at=_fmt_dt(doc.get("updated_at")),
        calls_today=doc.get("calls_today", 0),
        language=doc.get("language", "hindi"),
        temperature=doc.get("temperature", 0.4),
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
        analysis_prompt=doc.get("analysis_prompt", ""),
        inactivity_phrase=doc.get("inactivity_phrase", "क्या आप अभी line पर हैं?"),
        inactivity_end_phrase=doc.get("inactivity_end_phrase", "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."),
        lang_notes=doc.get("lang_notes", ""),
    )


async def _get_or_404(assistant_id: str) -> dict:
    col = get_assistants_col()
    doc = await col.find_one({"assistant_id": assistant_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Assistant {assistant_id!r} not found")
    return doc


def _new_doc(data: CreateAssistantRequest, aid: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": aid,
        "assistant_id": str(uuid.uuid4()),
        "organization_id": data.organization_id,
        "name": data.name,
        "description": data.description or "",
        "category": data.category or "Customer Service",
        "tags": data.tags or [],
        "status": data.status or "Draft",
        "prompt": data.prompt or "",
        "initial_message": data.initial_message or "",
        "call_end_text": data.call_end_text or "",
        "mis_api_base": data.mis_api_base or "http://192.168.14.101:3006",
        "callback_api_url": data.callback_api_url or "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
        "category_change_api": data.category_change_api or "http://192.168.20.105:1080/services/abd/abd_beta.php",
        "script_rule": data.script_rule or "",
        "opening_instruction": data.opening_instruction or "",
        "closing_instruction": data.closing_instruction or "",
        "timeout_message": data.timeout_message or "",
        "function_calling": bool(data.function_calling),
        "functions": data.functions or [],
        "language": data.language or "hindi",
        "temperature": data.temperature if data.temperature is not None else 0.4,
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
        "analysis_prompt": data.analysis_prompt or "",
        "inactivity_phrase": data.inactivity_phrase or "क्या आप अभी line पर हैं?",
        "inactivity_end_phrase": data.inactivity_end_phrase or "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद.",
        "lang_notes": data.lang_notes or "",
        "is_deleted": False,
        "is_active": True,
        "calls_today": 0,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# 1. List assistants
# ---------------------------------------------------------------------------

@router.get("/api/assistants", response_model=AssistantsListResponse)
async def list_assistants(
    organization_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
    is_deleted: bool = Query(False),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("updated_at"),
    sort_order: Optional[str] = Query("desc"),
    status: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
):
    col = get_assistants_col()
    query: dict = {"organization_id": organization_id, "is_deleted": is_deleted}

    if status:
        query["status"] = status
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        query["tags"] = {"$elemMatch": {"$in": tag_list}}

    sort_dir = 1 if sort_order == "asc" else -1
    total = await col.count_documents(query)
    cursor = col.find(query).sort(sort_by or "updated_at", sort_dir).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return AssistantsListResponse(assistants=[_doc_to_response(d) for d in docs], total=total)


# ---------------------------------------------------------------------------
# 2. Create assistant
# ---------------------------------------------------------------------------

@router.post("/api/assistants", response_model=AssistantResponse, status_code=201)
async def create_assistant(data: CreateAssistantRequest):
    col = get_assistants_col()
    aid = await next_sequence("assistant_id")
    doc = _new_doc(data, aid)
    await col.insert_one(doc)
    return _doc_to_response(doc)


# ---------------------------------------------------------------------------
# 3. AI-create (same as create)
# ---------------------------------------------------------------------------

@router.post("/api/assistants/ai-create", response_model=AssistantResponse, status_code=201)
async def ai_create_assistant(data: CreateAssistantRequest):
    return await create_assistant(data)


# ---------------------------------------------------------------------------
# 4. Get assistant by ID
# ---------------------------------------------------------------------------

@router.get("/api/assistants/{assistant_id}", response_model=AssistantResponse)
async def get_assistant(assistant_id: str):
    return _doc_to_response(await _get_or_404(assistant_id))


# ---------------------------------------------------------------------------
# 5. Update assistant
# ---------------------------------------------------------------------------

@router.put("/api/assistants/{assistant_id}", response_model=AssistantResponse)
async def update_assistant(assistant_id: str, data: UpdateAssistantRequest):
    col = get_assistants_col()
    await _get_or_404(assistant_id)
    updates = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    updates["updated_at"] = datetime.now(timezone.utc)
    await col.update_one({"assistant_id": assistant_id}, {"$set": updates})
    doc = await col.find_one({"assistant_id": assistant_id})
    return _doc_to_response(doc)


# ---------------------------------------------------------------------------
# 6. Soft delete
# ---------------------------------------------------------------------------

@router.delete("/api/assistants/{assistant_id}")
async def delete_assistant(assistant_id: str):
    col = get_assistants_col()
    await _get_or_404(assistant_id)
    now = datetime.now(timezone.utc)
    await col.update_one(
        {"assistant_id": assistant_id},
        {"$set": {
            "is_deleted": True,
            "is_active": False,
            "deleted_until": (now + timedelta(days=7)).isoformat(),
            "updated_at": now,
        }},
    )
    return {"message": "Assistant deleted", "assistant_id": assistant_id}


# ---------------------------------------------------------------------------
# 7. Restore
# ---------------------------------------------------------------------------

@router.post("/api/assistants/{assistant_id}/restore", response_model=AssistantResponse)
async def restore_assistant(assistant_id: str):
    col = get_assistants_col()
    doc = await col.find_one({"assistant_id": assistant_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Assistant not found")
    await col.update_one(
        {"assistant_id": assistant_id},
        {"$set": {
            "is_deleted": False,
            "is_active": True,
            "deleted_until": None,
            "status": "Draft",
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    doc = await col.find_one({"assistant_id": assistant_id})
    return _doc_to_response(doc)


# ---------------------------------------------------------------------------
# 8. Clone
# ---------------------------------------------------------------------------

@router.post("/api/assistants/{assistant_id}/clone", response_model=AssistantResponse)
async def clone_assistant(assistant_id: str, body: dict = None):
    col = get_assistants_col()
    original = await _get_or_404(assistant_id)
    new_name = (body or {}).get("new_name") or (body or {}).get("name") or f"{original['name']} (Copy)"
    aid = await next_sequence("assistant_id")
    now = datetime.now(timezone.utc)
    clone = {**original}
    clone.pop("_id", None)
    clone["id"] = aid
    clone["assistant_id"] = str(uuid.uuid4())
    clone["name"] = new_name
    clone["status"] = "Draft"
    clone["is_deleted"] = False
    clone["is_active"] = True
    clone["calls_today"] = 0
    clone["created_at"] = now
    clone["updated_at"] = now
    await col.insert_one(clone)
    return _doc_to_response(clone)


# ---------------------------------------------------------------------------
# 9. Bot config — read by bot.py at call start
# ---------------------------------------------------------------------------

@router.get("/api/assistants/{assistant_id}/bot-config", response_model=BotConfig)
async def get_bot_config(assistant_id: str):
    doc = await _get_or_404(assistant_id)
    return BotConfig(
        assistant_id=doc["assistant_id"],
        organization_id=doc.get("organization_id", ""),
        system_prompt=doc.get("prompt", ""),
        initial_message=doc.get("initial_message", ""),
        call_end_text=doc.get("call_end_text", ""),
        function_calling=bool(doc.get("function_calling", False)),
        functions=doc.get("functions", []),
        api_urls={
            "mis_api_base": doc.get("mis_api_base", "http://192.168.14.101:3006"),
            "callback_api_url": doc.get("callback_api_url", "http://192.168.14.101:3006/leads/ai-lead-qualify/callback"),
            "category_change_api": doc.get("category_change_api", "http://192.168.20.105:1080/services/abd/abd_beta.php"),
        },
        prompt_config={
            "script_rule": doc.get("script_rule", ""),
            "opening_instruction": doc.get("opening_instruction", ""),
            "closing_instruction": doc.get("closing_instruction", ""),
            "timeout_message": doc.get("timeout_message", ""),
        },
        language=doc.get("language", "hindi"),
        temperature=doc.get("temperature", 0.4),
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
        analysis_prompt=doc.get("analysis_prompt", ""),
        inactivity_phrase=doc.get("inactivity_phrase", "क्या आप अभी line पर हैं?"),
        inactivity_end_phrase=doc.get("inactivity_end_phrase", "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."),
        lang_notes=doc.get("lang_notes", ""),
    )
