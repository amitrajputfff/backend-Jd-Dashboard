"""Assistants router — all 8 endpoints the JD-Dashboard frontend calls."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..database import get_db
    from ..models import Assistant
    from ..schemas import (
        AssistantResponse,
        AssistantsListResponse,
        BotConfig,
        CreateAssistantRequest,
        UpdateAssistantRequest,
    )
except ImportError:
    from database import get_db
    from models import Assistant
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

def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.isoformat()


def _to_response(a: Assistant) -> AssistantResponse:
    return AssistantResponse(
        id=a.id,
        assistant_id=a.assistant_id,
        organization_id=a.organization_id,
        name=a.name,
        description=a.description or "",
        category=a.category or "Customer Service",
        tags=a.tags or [],
        status=a.status or "Draft",
        prompt=a.prompt or "",
        initial_message=a.initial_message or "",
        call_end_text=a.call_end_text or "",
        mis_api_base=a.mis_api_base or "",
        callback_api_url=a.callback_api_url or "",
        category_change_api=a.category_change_api or "",
        script_rule=a.script_rule or "",
        opening_instruction=a.opening_instruction or "",
        closing_instruction=a.closing_instruction or "",
        timeout_message=a.timeout_message or "",
        function_calling=bool(a.function_calling),
        functions=a.functions or [],
        is_deleted=bool(a.is_deleted),
        deleted_until=_fmt_dt(a.deleted_until) if a.deleted_until else None,
        is_active=bool(a.is_active),
        created_at=_fmt_dt(a.created_at),
        updated_at=_fmt_dt(a.updated_at),
        calls_today=a.calls_today or 0,
        language=a.language or "hindi",
        temperature=a.temperature if a.temperature is not None else 0.4,
        gemini_start_sensitivity=a.gemini_start_sensitivity or "START_SENSITIVITY_LOW",
        gemini_end_sensitivity=a.gemini_end_sensitivity or "END_SENSITIVITY_HIGH",
        gemini_silence_duration_ms=a.gemini_silence_duration_ms if a.gemini_silence_duration_ms is not None else 800,
        gemini_prefix_padding_ms=a.gemini_prefix_padding_ms if a.gemini_prefix_padding_ms is not None else 100,
        max_call_duration=a.max_call_duration if a.max_call_duration is not None else 300,
        filler_message=a.filler_message or [],
        function_filler_message=a.function_filler_message or [],
    )


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
    tags: Optional[str] = Query(None),   # comma-separated
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Assistant).where(
        Assistant.organization_id == organization_id,
        Assistant.is_deleted == is_deleted,
    )

    if status:
        stmt = stmt.where(Assistant.status == status)

    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Assistant.name.ilike(like),
                Assistant.description.ilike(like),
            )
        )

    if tags:
        # SQLite stores tags as JSON — filter client-side after fetch for simplicity
        pass

    # Sort
    sort_col = getattr(Assistant, sort_by, Assistant.updated_at)
    if sort_order == "asc":
        stmt = stmt.order_by(sort_col.asc())
    else:
        stmt = stmt.order_by(sort_col.desc())

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Page
    stmt = stmt.offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Apply tag filter client-side
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        rows = [r for r in rows if any(t in (r.tags or []) for t in tag_list)]
        total = len(rows)  # recount after filter

    return AssistantsListResponse(assistants=[_to_response(r) for r in rows], total=total)


# ---------------------------------------------------------------------------
# 2. Create assistant
# ---------------------------------------------------------------------------

@router.post("/api/assistants", response_model=AssistantResponse, status_code=201)
async def create_assistant(
    data: CreateAssistantRequest,
    db: AsyncSession = Depends(get_db),
):
    assistant = Assistant(
        assistant_id=str(uuid.uuid4()),
        organization_id=data.organization_id,
        name=data.name,
        description=data.description or "",
        category=data.category or "Customer Service",
        tags=data.tags or [],
        status=data.status or "Draft",
        prompt=data.prompt or "",
        initial_message=data.initial_message or "",
        call_end_text=data.call_end_text or "",
        mis_api_base=data.mis_api_base or "http://192.168.14.101:3006",
        callback_api_url=data.callback_api_url
        or "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
        category_change_api=data.category_change_api
        or "http://192.168.20.105:1080/services/abd/abd_beta.php",
        script_rule=data.script_rule or "",
        opening_instruction=data.opening_instruction or "",
        closing_instruction=data.closing_instruction or "",
        timeout_message=data.timeout_message or "",
        function_calling=bool(data.function_calling),
        functions=data.functions or [],
        language=data.language or "hindi",
        temperature=data.temperature if data.temperature is not None else 0.4,
        gemini_start_sensitivity=data.gemini_start_sensitivity or "START_SENSITIVITY_LOW",
        gemini_end_sensitivity=data.gemini_end_sensitivity or "END_SENSITIVITY_HIGH",
        gemini_silence_duration_ms=data.gemini_silence_duration_ms if data.gemini_silence_duration_ms is not None else 800,
        gemini_prefix_padding_ms=data.gemini_prefix_padding_ms if data.gemini_prefix_padding_ms is not None else 100,
        max_call_duration=data.max_call_duration if data.max_call_duration is not None else 300,
        filler_message=data.filler_message or [],
        function_filler_message=data.function_filler_message or [],
        is_deleted=False,
        is_active=True,
    )
    db.add(assistant)
    await db.commit()
    await db.refresh(assistant)
    return _to_response(assistant)


# ---------------------------------------------------------------------------
# 3. AI-create (simplified — same as create, ignores AI generation flags)
# ---------------------------------------------------------------------------

@router.post("/api/assistants/ai-create", response_model=AssistantResponse, status_code=201)
async def ai_create_assistant(
    data: CreateAssistantRequest,
    db: AsyncSession = Depends(get_db),
):
    return await create_assistant(data, db)


# ---------------------------------------------------------------------------
# 4. Get assistant by ID
# ---------------------------------------------------------------------------

@router.get("/api/assistants/{assistant_id}", response_model=AssistantResponse)
async def get_assistant(
    assistant_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_404(db, assistant_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# 5. Update assistant
# ---------------------------------------------------------------------------

@router.put("/api/assistants/{assistant_id}", response_model=AssistantResponse)
async def update_assistant(
    assistant_id: str,
    data: UpdateAssistantRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_404(db, assistant_id)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(row, field, value)

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# 6. Soft delete
# ---------------------------------------------------------------------------

@router.delete("/api/assistants/{assistant_id}")
async def delete_assistant(
    assistant_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_404(db, assistant_id)
    row.is_deleted = True
    row.is_active = False
    row.deleted_until = datetime.now(timezone.utc) + timedelta(days=7)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Assistant deleted", "assistant_id": assistant_id}


# ---------------------------------------------------------------------------
# 7. Restore
# ---------------------------------------------------------------------------

@router.post("/api/assistants/{assistant_id}/restore", response_model=AssistantResponse)
async def restore_assistant(
    assistant_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Assistant).where(Assistant.assistant_id == assistant_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Assistant not found")

    row.is_deleted = False
    row.is_active = True
    row.deleted_until = None
    row.status = "Draft"
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# 8. Clone
# ---------------------------------------------------------------------------

@router.post("/api/assistants/{assistant_id}/clone", response_model=AssistantResponse)
async def clone_assistant(
    assistant_id: str,
    body: dict = None,
    db: AsyncSession = Depends(get_db),
):
    original = await _get_or_404(db, assistant_id)
    new_name = (body or {}).get("new_name") or (body or {}).get("name") or f"{original.name} (Copy)"

    clone = Assistant(
        assistant_id=str(uuid.uuid4()),
        organization_id=original.organization_id,
        name=new_name,
        description=original.description,
        category=original.category,
        tags=list(original.tags or []),
        status="Draft",
        prompt=original.prompt,
        initial_message=original.initial_message,
        call_end_text=original.call_end_text,
        mis_api_base=original.mis_api_base,
        callback_api_url=original.callback_api_url,
        category_change_api=original.category_change_api,
        script_rule=original.script_rule,
        opening_instruction=original.opening_instruction,
        closing_instruction=original.closing_instruction,
        timeout_message=original.timeout_message,
        function_calling=original.function_calling,
        functions=list(original.functions or []),
        language=original.language or "hindi",
        temperature=original.temperature if original.temperature is not None else 0.4,
        gemini_start_sensitivity=original.gemini_start_sensitivity or "START_SENSITIVITY_LOW",
        gemini_end_sensitivity=original.gemini_end_sensitivity or "END_SENSITIVITY_HIGH",
        gemini_silence_duration_ms=original.gemini_silence_duration_ms if original.gemini_silence_duration_ms is not None else 800,
        gemini_prefix_padding_ms=original.gemini_prefix_padding_ms if original.gemini_prefix_padding_ms is not None else 100,
        max_call_duration=original.max_call_duration if original.max_call_duration is not None else 300,
        filler_message=list(original.filler_message or []),
        function_filler_message=list(original.function_filler_message or []),
        is_deleted=False,
        is_active=True,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    return _to_response(clone)


# ---------------------------------------------------------------------------
# 9. Bot config — read by server.py / bot.py at call start
# ---------------------------------------------------------------------------

@router.get("/api/assistants/{assistant_id}/bot-config", response_model=BotConfig)
async def get_bot_config(
    assistant_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_404(db, assistant_id)
    return BotConfig(
        assistant_id=row.assistant_id,
        organization_id=row.organization_id or "",
        system_prompt=row.prompt or "",
        initial_message=row.initial_message or "",
        call_end_text=row.call_end_text or "",
        function_calling=bool(row.function_calling),
        functions=row.functions or [],
        api_urls={
            "mis_api_base": row.mis_api_base or "http://192.168.14.101:3006",
            "callback_api_url": row.callback_api_url or "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
            "category_change_api": row.category_change_api or "http://192.168.20.105:1080/services/abd/abd_beta.php",
        },
        prompt_config={
            "script_rule": row.script_rule or "",
            "opening_instruction": row.opening_instruction or "",
            "closing_instruction": row.closing_instruction or "",
            "timeout_message": row.timeout_message or "",
        },
        language=row.language or "hindi",
        temperature=row.temperature if row.temperature is not None else 0.4,
        gemini_start_sensitivity=row.gemini_start_sensitivity or "START_SENSITIVITY_LOW",
        gemini_end_sensitivity=row.gemini_end_sensitivity or "END_SENSITIVITY_HIGH",
        gemini_silence_duration_ms=row.gemini_silence_duration_ms if row.gemini_silence_duration_ms is not None else 800,
        gemini_prefix_padding_ms=row.gemini_prefix_padding_ms if row.gemini_prefix_padding_ms is not None else 100,
        max_call_duration=row.max_call_duration if row.max_call_duration is not None else 300,
        filler_message=row.filler_message or [],
        function_filler_message=row.function_filler_message or [],
    )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _get_or_404(db: AsyncSession, assistant_id: str) -> Assistant:
    stmt = select(Assistant).where(
        Assistant.assistant_id == assistant_id,
        Assistant.is_deleted == False,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return row
