"""Analysis router — reads ai_lead_qualify.call_transcripts.

Endpoints:
  GET  /api/analysis/calls                    — paginated list of call transcripts + outcomes
  GET  /api/analysis/calls/{call_id}          — full transcript + analysis sub-doc
  POST /api/analysis/calls/{call_id}/rerun    — re-run analysis with assistant's analysis_prompt
  GET  /api/analysis/prompt/{assistant_id}    — read assistant's analysis_prompt
  PUT  /api/analysis/prompt/{assistant_id}    — update assistant's analysis_prompt
  GET  /api/metrics/{assistant_id}            — real aggregated metrics from call_transcripts
                                                 (assistant_id="all" — no assistant scoping)
  GET  /api/dashboard/stats                   — org-wide rollup of the same metrics,
                                                 scoped by organization_id, + activeAgents
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

try:
    from ..mongo import get_transcripts_col, get_assistants_col, get_analysis_prompts_col, get_workflow_bots_col
    from ..outcomes import DISPOSITION_MAP, OUTCOME_SUCCESS, UNANALYSED_SENTINEL
except ImportError:
    from mongo import get_transcripts_col, get_assistants_col, get_analysis_prompts_col, get_workflow_bots_col
    from outcomes import DISPOSITION_MAP, OUTCOME_SUCCESS, UNANALYSED_SENTINEL

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str_id(doc: dict) -> dict:
    """Convert _id to string for JSON serialisation."""
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _date_range_clause(date_from: Optional[str], date_to: Optional[str]) -> dict:
    """`call_start_time` is stored inconsistently across call records — as a
    BSON datetime, an ISO string, AND a raw Unix-epoch float (the format
    bot.py itself writes: `call_start_time: 1784884680.29`). Comparing only
    against a datetime (the old behavior) silently matched zero documents
    whenever the stored value was a float, since BSON treats numbers and
    dates as different types. This covers all three representations via $or.
    `date_to` is treated as inclusive of the whole day (exclusive upper bound
    at the next day's midnight) — comparing against literal 00:00:00 excluded
    every record from that day.
    """
    start_dt = end_dt = None
    if date_from:
        try:
            start_dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if date_to:
        try:
            end_dt = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            pass
    if start_dt is None and end_dt is None:
        return {}

    def _bounds(gte, lt) -> dict:
        b: dict = {}
        if gte is not None:
            b["$gte"] = gte
        if lt is not None:
            b["$lt"] = lt
        return b

    return {"$or": [
        {"call_start_time": _bounds(start_dt, end_dt)},
        {"call_start_time": _bounds(start_dt.isoformat() if start_dt else None, end_dt.isoformat() if end_dt else None)},
        {"call_start_time": _bounds(start_dt.timestamp() if start_dt else None, end_dt.timestamp() if end_dt else None)},
    ]}


def _normalized_phone_variants(digits: str) -> set[str]:
    """Mirrors voicebot_nodcode_platform/bot.py's normalize_mobile so a search
    for any variant of a number matches all the ways it's actually stored:
    lead_record.buyer_details.buyer_number (bare 10 digits), sip_info.caller_number
    (leading zero), or a +91-prefixed form."""
    n = digits
    if n.startswith("91") and len(n) == 12:
        n = n[2:]
    if n.startswith("0") and len(n) == 11:
        n = n[1:]
    if len(n) != 10:
        return {digits}
    return {n, f"0{n}", f"91{n}", f"+91{n}"}


def _search_clause(search: str) -> dict:
    """Matches a lead ID or phone number across every field/representation the
    verified document shape actually uses — see the module docstring for
    which fields exist and why phone numbers need normalization."""
    search = search.strip()
    pattern = re.escape(search)
    or_clauses: list[dict] = [
        {"lead_id": {"$regex": pattern, "$options": "i"}},
        {"call_id": {"$regex": pattern, "$options": "i"}},
        {"lead_record.buyer_details.buyer_number": {"$regex": pattern}},
        {"lead_record.mobile": {"$regex": pattern}},
        {"sip_info.caller_number": {"$regex": pattern}},
    ]

    digits = re.sub(r"\D", "", search)
    if digits:
        for variant in _normalized_phone_variants(digits):
            vp = re.escape(variant)
            or_clauses.append({"lead_record.buyer_details.buyer_number": {"$regex": vp}})
            or_clauses.append({"lead_record.mobile": {"$regex": vp}})
            or_clauses.append({"sip_info.caller_number": {"$regex": vp}})
            or_clauses.append({"call_id": {"$regex": vp}})

    # lead_id is sometimes stored as an ObjectId rather than a string — see
    # voicebot_nodcode_platform/fetch_lead_debug.py's identical fallback.
    if re.fullmatch(r"[0-9a-fA-F]{24}", search):
        try:
            or_clauses.append({"lead_id": ObjectId(search)})
        except InvalidId:
            pass

    return {"$or": or_clauses}


# ---------------------------------------------------------------------------
# 1. List call transcripts
# ---------------------------------------------------------------------------

@router.get("/api/analysis/calls")
async def list_analysis_calls(
    assistant_id: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None, description=f"An outcome value, or {UNANALYSED_SENTINEL!r} for no analysis yet"),
    tagged: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Lead ID or phone number (any format)"),
    date_from: Optional[str] = Query(None, description="ISO date e.g. 2026-01-01"),
    date_to: Optional[str] = Query(None, description="ISO date e.g. 2026-12-31 (inclusive)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    col = get_transcripts_col()

    # Every filter is its own clause, combined with $and — search and the date
    # range both need their own top-level $or, and assigning `query["$or"]`
    # twice would silently clobber the first one.
    clauses: list[dict] = []
    if assistant_id:
        clauses.append({"assistant_id": assistant_id})
    if tagged is not None:
        clauses.append({"tagged": tagged})
    if outcome:
        if outcome == UNANALYSED_SENTINEL:
            clauses.append({"$or": [
                {"analysis.call_outcome": {"$in": [None, ""]}},
                {"analysis.call_outcome": {"$exists": False}},
            ]})
        else:
            clauses.append({"analysis.call_outcome": outcome})
    date_clause = _date_range_clause(date_from, date_to)
    if date_clause:
        clauses.append(date_clause)
    if search and search.strip():
        clauses.append(_search_clause(search))

    query: dict = {"$and": clauses} if clauses else {}

    # Project: omit heavy fields for listing
    projection = {
        "_id": 1,
        "call_id": 1,
        "lead_id": 1,
        "assistant_id": 1,
        "call_start_time": 1,
        "call_end_time": 1,
        "call_duration_sec": 1,
        "status": 1,
        "tagged": 1,
        "tagged_at": 1,
        "analysis.call_outcome": 1,
        "analysis.call_summary": 1,
        "analysis.call_outcome_description": 1,
        "analysis.lead_intent_score": 1,
        "lead_record.buyer_details.buyer_name": 1,
        "lead_record.buyer_details.buyer_number": 1,
        "lead_record.search_context.searched_keyword": 1,
    }

    total = await col.count_documents(query)
    cursor = col.find(query, projection).sort("call_start_time", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)

    return {
        "calls": [_str_id(d) for d in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 1b. Canonical outcome list — see backend/outcomes.py
# ---------------------------------------------------------------------------

@router.get("/api/analysis/outcomes")
async def list_outcomes():
    return {
        "outcomes": [{"value": k, "description": v} for k, v in DISPOSITION_MAP.items()],
        "unanalysed_value": UNANALYSED_SENTINEL,
    }


# ---------------------------------------------------------------------------
# 2. Get single call transcript + analysis
# ---------------------------------------------------------------------------

@router.get("/api/analysis/calls/{call_id}")
async def get_analysis_call(call_id: str):
    col = get_transcripts_col()

    # Try ObjectId first, then call_id string
    doc = None
    if len(call_id) == 24:
        try:
            doc = await col.find_one({"_id": ObjectId(call_id)})
        except Exception:
            pass
    if doc is None:
        doc = await col.find_one({"call_id": call_id})

    if doc is None:
        raise HTTPException(status_code=404, detail=f"Call {call_id!r} not found")

    return _str_id(doc)


# ---------------------------------------------------------------------------
# 3. Rerun analysis
# ---------------------------------------------------------------------------

class RerunRequest(BaseModel):
    analysis_prompt_override: Optional[str] = None  # If None, uses assistant's stored prompt


@router.post("/api/analysis/calls/{call_id}/rerun")
async def rerun_analysis(call_id: str, body: RerunRequest = RerunRequest()):
    col = get_transcripts_col()

    # Find the doc
    doc = None
    if len(call_id) == 24:
        try:
            doc = await col.find_one({"_id": ObjectId(call_id)})
        except Exception:
            pass
    if doc is None:
        doc = await col.find_one({"call_id": call_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Call {call_id!r} not found")

    now = datetime.now(timezone.utc)
    await col.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "tagged": False,
                "rerun": True,
                "rerun_requested_at": now.isoformat(),
            },
            "$unset": {"tagged_at": ""},
        },
    )

    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=202, content={"status": "queued", "call_id": call_id})


# ---------------------------------------------------------------------------
# 3b. Dry-run test — try a candidate prompt against a real call's transcript
#     WITHOUT writing anything back (no tagged, no analysis mutation, no
#     callback). Lets a user iterate on a prompt before saving/assigning it.
#     Never calls analyze_and_store() — that writes to Mongo and can fire the
#     MIS callback; this endpoint only ever reads.
# ---------------------------------------------------------------------------

class TestAnalysisRequest(BaseModel):
    call_id: Optional[str] = None
    lead_id: Optional[str] = None
    prompt_id: Optional[str] = None
    # Raw, possibly-unsaved prompt text — wins over prompt_id. An explicit ""
    # is a deliberate request to test the canonical fallback, so it's
    # distinguished from "not provided" via `analysis_prompt is not None`.
    analysis_prompt: Optional[str] = None
    model: Optional[str] = None


@router.post("/api/analysis/test")
async def test_analysis_prompt(body: TestAnalysisRequest):
    if not body.call_id and not body.lead_id:
        raise HTTPException(status_code=400, detail="Provide call_id or lead_id")

    col = get_transcripts_col()

    doc = None
    if body.call_id:
        if len(body.call_id) == 24:
            try:
                doc = await col.find_one({"_id": ObjectId(body.call_id)})
            except Exception:
                pass
        if doc is None:
            doc = await col.find_one({"call_id": body.call_id})
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Call {body.call_id!r} not found")
    else:
        doc = await col.find_one(_search_clause(body.lead_id), sort=[("call_start_time", -1)])
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No call found for lead_id/phone {body.lead_id!r}")

    # Resolve which prompt text to test — inline text (even "") > prompt_id >
    # this org's default prompt > canonical (render_analysis_prompt's own
    # fallback when prompt_template is None). Per-agent assignment
    # (analysis_prompt_id on the doc's assistant) is layered in once that
    # exists — until then, every call tests against the same default/canonical
    # chain a real analysis would use for an unassigned agent.
    prompt_template: Optional[str] = None
    prompt_source = "canonical"
    if body.analysis_prompt is not None:
        prompt_template = body.analysis_prompt
        prompt_source = "inline"
    elif body.prompt_id:
        prompts_col = get_analysis_prompts_col()
        prompt_doc = await prompts_col.find_one({"prompt_id": body.prompt_id})
        if prompt_doc is None:
            raise HTTPException(status_code=404, detail=f"Prompt {body.prompt_id!r} not found")
        prompt_template = prompt_doc.get("analysis_prompt", "")
        prompt_source = f"prompt_id:{body.prompt_id}"
    else:
        default_doc = await _get_default_prompt_doc()
        if default_doc is not None:
            prompt_template = default_doc.get("analysis_prompt", "")
            prompt_source = f"default:{default_doc.get('prompt_id', str(default_doc.get('_id', '')))}"

    from analysis_engine import run_dry_run_analysis

    started = datetime.now(timezone.utc)
    async with aiohttp.ClientSession() as http_session:
        try:
            analysis, b2b_score, debug = await run_dry_run_analysis(
                doc, prompt_template=prompt_template, http_session=http_session, model=body.model,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    reached_llm = debug.get("reached_llm", False)
    guard = None if reached_llm else analysis.get("call_outcome")
    if reached_llm and "llm_raw_outcome" not in debug:
        # The Gemini call itself raised inside generate_call_analysis()'s own
        # try/except, which caught it and silently returned fallback_analysis()
        # — surfacing that as if it were a real classification would be
        # misleading (it would look like "your prompt produced this outcome").
        raise HTTPException(
            status_code=502,
            detail="Gemini call failed while testing this prompt — see server logs for the underlying error.",
        )

    return {
        "doc_id": str(doc.get("_id", "")),
        "call_id": doc.get("call_id"),
        "lead_id": doc.get("lead_id"),
        "assistant_id": doc.get("assistant_id"),
        "transcript_turns": len(doc.get("transcript") or []),
        "muted_turns": len(doc.get("muted_transcript") or []),
        "call_duration_sec": doc.get("call_duration_sec"),
        "status": doc.get("status"),
        "prompt_source": prompt_source,
        "missing_placeholders": debug.get("missing_placeholders", []),
        "auto_repaired": debug.get("auto_repaired", False),
        "guard": guard,
        "llm_raw_outcome": debug.get("llm_raw_outcome"),
        "post_processing": debug.get("post_processing", []),
        "rendered_prompt": debug.get("rendered_prompt"),
        "analysis": {**analysis, **{k: b2b_score.get(k) for k in ("deal_value", "lead_intent_score", "urgency_flag")}},
        "stored_analysis": doc.get("analysis"),
        "elapsed_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# 4. Analysis Prompts — standalone collection, not tied to any assistant
#    Future: a separate mapping table will link assistant_id → prompt_id.
# ---------------------------------------------------------------------------

import uuid as _uuid


def _prompt_doc_out(doc: dict, assignments: Optional[dict] = None) -> dict:
    """Shape a prompt document for API responses.

    assignments, when given, is the {prompt_id: [{"assistant_id"/"workflow_bot_id",
    "name", "bot_type"}]} map built by _assignments_by_prompt_id() — batched
    across all prompts to avoid an N+1 query per prompt in list_analysis_prompts.
    """
    pid = doc.get("prompt_id", str(doc["_id"]))
    assigned = (assignments or {}).get(pid, [])
    return {
        "prompt_id": pid,
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "analysis_prompt": doc.get("analysis_prompt", ""),
        "is_default": doc.get("is_default", False),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
        "assistant_ids": [a["id"] for a in assigned],
        "assistant_count": len(assigned),
    }


async def _get_default_prompt_doc() -> Optional[dict]:
    """Return the default prompt doc, falling back to the first one."""
    col = get_analysis_prompts_col()
    doc = await col.find_one({"is_default": True})
    if doc is None:
        doc = await col.find_one({}, sort=[("created_at", 1)])
    return doc


async def _assignments_by_prompt_id(prompt_ids: Optional[list[str]] = None) -> dict[str, list[dict]]:
    """Batched lookup of every agent (assistant or workflow bot) currently
    assigned to each prompt_id — one query per collection, not one per prompt.
    `prompt_ids`, when given, restricts the result to just those ids (still a
    single query); omit to fetch every assignment that exists.
    """
    match: dict = {"analysis_prompt_id": {"$ne": None}}
    if prompt_ids is not None:
        match = {"analysis_prompt_id": {"$in": prompt_ids}}

    result: dict[str, list[dict]] = {}

    assistants_col = get_assistants_col()
    async for a in assistants_col.find(match, {"assistant_id": 1, "name": 1, "analysis_prompt_id": 1}):
        pid = a.get("analysis_prompt_id")
        if pid:
            result.setdefault(pid, []).append({"id": a.get("assistant_id"), "name": a.get("name", ""), "bot_type": "assistant"})

    workflow_bots_col = get_workflow_bots_col()
    async for w in workflow_bots_col.find(match, {"workflow_bot_id": 1, "name": 1, "analysis_prompt_id": 1}):
        pid = w.get("analysis_prompt_id")
        if pid:
            result.setdefault(pid, []).append({"id": w.get("workflow_bot_id"), "name": w.get("name", ""), "bot_type": "workflow"})

    return result


# --- List all prompts ---

@router.get("/api/analysis/prompts")
async def list_analysis_prompts():
    col = get_analysis_prompts_col()
    cursor = col.find({}, {"analysis_prompt": 0}).sort("created_at", 1)
    docs = await cursor.to_list(length=100)
    assignments = await _assignments_by_prompt_id()
    return [_prompt_doc_out({**d, "analysis_prompt": ""}, assignments) for d in docs]


# --- Get default prompt (must be registered before /{prompt_id}) ---

@router.get("/api/analysis/prompts/default")
async def get_default_analysis_prompt():
    doc = await _get_default_prompt_doc()
    if doc is None:
        raise HTTPException(status_code=404, detail="No analysis prompts found — run the seeder")
    assignments = await _assignments_by_prompt_id([doc.get("prompt_id", str(doc["_id"]))])
    return _prompt_doc_out(doc, assignments)


# --- Get specific prompt ---

@router.get("/api/analysis/prompts/{prompt_id}")
async def get_analysis_prompt_by_id(prompt_id: str):
    col = get_analysis_prompts_col()
    doc = await col.find_one({"prompt_id": prompt_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")
    assignments = await _assignments_by_prompt_id([prompt_id])
    return _prompt_doc_out(doc, assignments)


# --- Create prompt ---

_FALLBACK_REQUIRED_PLACEHOLDERS = ("transcript", "qualification_questions", "disposition_options", "dynamic_notes")


def _validate_prompt_placeholders(text: str) -> list[str]:
    """Non-blocking check — a blank/missing placeholder is never a hard error
    (an empty prompt legitimately means "use the canonical fallback", and a
    saved prompt missing a required placeholder gets auto-repaired at render
    time, see prompt_render.py) — just a warning surfaced to the editor UI.
    """
    if not text.strip():
        return []
    try:
        _WORKER_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "voicebot_nodcode_platform")
        import sys
        if _WORKER_ROOT not in sys.path:
            sys.path.insert(0, _WORKER_ROOT)
        from callback_worker.canonical_prompt import REQUIRED_PLACEHOLDERS
    except Exception:
        REQUIRED_PLACEHOLDERS = _FALLBACK_REQUIRED_PLACEHOLDERS
    return [name for name in REQUIRED_PLACEHOLDERS if "{" + name + "}" not in text]


class CreatePromptRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    analysis_prompt: str
    is_default: bool = False


@router.post("/api/analysis/prompts", status_code=201)
async def create_analysis_prompt(body: CreatePromptRequest):
    col = get_analysis_prompts_col()
    now = datetime.now(timezone.utc)
    # If marked as default, unset other defaults
    if body.is_default:
        await col.update_many({"is_default": True}, {"$set": {"is_default": False}})
    new_id = str(_uuid.uuid4())
    doc = {
        "prompt_id": new_id,
        "name": body.name,
        "description": body.description or "",
        "analysis_prompt": body.analysis_prompt,
        "is_default": body.is_default,
        "created_at": now,
        "updated_at": now,
    }
    await col.insert_one(doc)
    return {**_prompt_doc_out(doc), "warnings": _validate_prompt_placeholders(body.analysis_prompt)}


# --- Update prompt ---

class UpdatePromptRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    analysis_prompt: Optional[str] = None
    is_default: Optional[bool] = None


@router.put("/api/analysis/prompts/{prompt_id}")
async def update_analysis_prompt_by_id(prompt_id: str, body: UpdatePromptRequest):
    col = get_analysis_prompts_col()
    update: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.name is not None:
        update["name"] = body.name
    if body.description is not None:
        update["description"] = body.description
    if body.analysis_prompt is not None:
        update["analysis_prompt"] = body.analysis_prompt
    if body.is_default is True:
        # Unset other defaults first
        await col.update_many({"is_default": True}, {"$set": {"is_default": False}})
        update["is_default"] = True
    elif body.is_default is False:
        update["is_default"] = False

    result = await col.update_one({"prompt_id": prompt_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")
    doc = await col.find_one({"prompt_id": prompt_id})
    warnings = _validate_prompt_placeholders(doc.get("analysis_prompt", ""))
    return {**_prompt_doc_out(doc), "warnings": warnings}


# --- Delete prompt ---

@router.delete("/api/analysis/prompts/{prompt_id}")
async def delete_analysis_prompt(prompt_id: str):
    col = get_analysis_prompts_col()
    doc = await col.find_one({"prompt_id": prompt_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")
    if doc.get("is_default"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the default prompt — set another prompt as default first.",
        )

    # Unassign every agent pointing at this prompt BEFORE deleting it, so no
    # assistant/workflow-bot is left with a dangling analysis_prompt_id.
    # (resolve_prompt_template degrades gracefully to the default prompt on a
    # dangling id, but leaving one around is still a hygiene bug worth avoiding.)
    unassign_filter = {"analysis_prompt_id": prompt_id}
    assistants_result = await get_assistants_col().update_many(unassign_filter, {"$unset": {"analysis_prompt_id": ""}})
    workflow_result = await get_workflow_bots_col().update_many(unassign_filter, {"$unset": {"analysis_prompt_id": ""}})
    unassigned = assistants_result.modified_count + workflow_result.modified_count

    await col.delete_one({"prompt_id": prompt_id})
    return {"deleted": True, "prompt_id": prompt_id, "unassigned": unassigned}


# ---------------------------------------------------------------------------
# 4a. Prompt <-> agent assignment — one prompt per agent (analysis_prompt_id
#     lives on the assistant/workflow_bot doc; None = use the default prompt).
#     Deliberately NOT routed through PUT /api/assistants/{id} or
#     PUT /api/workflow-bots/{id} — both do
#     data.model_dump(exclude_none=True), which silently drops an attempt to
#     clear analysis_prompt_id back to None.
# ---------------------------------------------------------------------------

async def _validate_agent_ids(ids: list[str]) -> None:
    """404 listing any id that isn't a real assistant or workflow bot."""
    if not ids:
        return
    assistants_col = get_assistants_col()
    workflow_bots_col = get_workflow_bots_col()
    found_assistants = {
        a["assistant_id"] async for a in assistants_col.find({"assistant_id": {"$in": ids}}, {"assistant_id": 1})
    }
    found_workflow = {
        w["workflow_bot_id"] async for w in workflow_bots_col.find({"workflow_bot_id": {"$in": ids}}, {"workflow_bot_id": 1})
    }
    unknown = set(ids) - found_assistants - found_workflow
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown agent id(s): {sorted(unknown)}")


@router.get("/api/analysis/prompts/{prompt_id}/assistants")
async def get_prompt_assistants(prompt_id: str):
    col = get_analysis_prompts_col()
    if await col.find_one({"prompt_id": prompt_id}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")
    assignments = await _assignments_by_prompt_id([prompt_id])
    return {"prompt_id": prompt_id, "assistants": assignments.get(prompt_id, [])}


class SetPromptAssistantsRequest(BaseModel):
    assistant_ids: list[str] = []


@router.put("/api/analysis/prompts/{prompt_id}/assistants")
async def set_prompt_assistants(prompt_id: str, body: SetPromptAssistantsRequest):
    col = get_analysis_prompts_col()
    if await col.find_one({"prompt_id": prompt_id}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")

    await _validate_agent_ids(body.assistant_ids)

    assistants_col = get_assistants_col()
    workflow_bots_col = get_workflow_bots_col()
    now = datetime.now(timezone.utc)

    # One-prompt-per-agent falls out naturally: $set overwrites whatever this
    # agent was previously assigned to. Unassign every agent CURRENTLY on this
    # prompt but not in the new list, then assign everyone in the new list.
    unassign_filter = {"analysis_prompt_id": prompt_id, "assistant_id": {"$nin": body.assistant_ids}}
    await assistants_col.update_many(unassign_filter, {"$unset": {"analysis_prompt_id": ""}})
    unassign_filter_wf = {"analysis_prompt_id": prompt_id, "workflow_bot_id": {"$nin": body.assistant_ids}}
    await workflow_bots_col.update_many(unassign_filter_wf, {"$unset": {"analysis_prompt_id": ""}})

    if body.assistant_ids:
        await assistants_col.update_many(
            {"assistant_id": {"$in": body.assistant_ids}},
            {"$set": {"analysis_prompt_id": prompt_id, "updated_at": now}},
        )
        await workflow_bots_col.update_many(
            {"workflow_bot_id": {"$in": body.assistant_ids}},
            {"$set": {"analysis_prompt_id": prompt_id, "updated_at": now}},
        )

    assignments = await _assignments_by_prompt_id([prompt_id])
    return {"prompt_id": prompt_id, "assistants": assignments.get(prompt_id, [])}


@router.get("/api/analysis/prompt-assignments")
async def list_prompt_assignments(organization_id: str = Query(...)):
    """Every agent in this org, with whichever prompt currently analyzes its
    calls (None = falls back to the org default) — powers the assignment UI's
    "assigned elsewhere" warning and "N unassigned -> Default" summary."""
    prompts_col = get_analysis_prompts_col()
    prompt_names = {
        p["prompt_id"]: p.get("name", "")
        async for p in prompts_col.find({}, {"prompt_id": 1, "name": 1})
    }

    result: list[dict] = []
    assistants_col = get_assistants_col()
    async for a in assistants_col.find(
        {"organization_id": organization_id, "is_deleted": {"$ne": True}},
        {"assistant_id": 1, "name": 1, "analysis_prompt_id": 1},
    ):
        pid = a.get("analysis_prompt_id")
        result.append({
            "assistant_id": a.get("assistant_id"),
            "name": a.get("name", ""),
            "bot_type": "assistant",
            "analysis_prompt_id": pid,
            "prompt_name": prompt_names.get(pid) if pid else None,
        })

    workflow_bots_col = get_workflow_bots_col()
    async for w in workflow_bots_col.find(
        {"organization_id": organization_id, "is_deleted": {"$ne": True}},
        {"workflow_bot_id": 1, "name": 1, "analysis_prompt_id": 1},
    ):
        pid = w.get("analysis_prompt_id")
        result.append({
            "assistant_id": w.get("workflow_bot_id"),
            "name": w.get("name", ""),
            "bot_type": "workflow",
            "analysis_prompt_id": pid,
            "prompt_name": prompt_names.get(pid) if pid else None,
        })

    return {"assignments": result}


# ---------------------------------------------------------------------------
# 4b. Legacy compat shims — /api/analysis/prompt/{assistant_id}
#     These keep old callers working by reading/writing the default prompt.
#     Once the frontend is fully migrated they can be removed.
# ---------------------------------------------------------------------------

@router.get("/api/analysis/prompt/{assistant_id}")
async def get_analysis_prompt_compat(assistant_id: str):
    """Compat: returns the default analysis prompt (assistant_id ignored)."""
    doc = await _get_default_prompt_doc()
    if doc is None:
        raise HTTPException(status_code=404, detail="No analysis prompts found — run the seeder")
    return {
        "assistant_id": assistant_id,
        "prompt_id": doc.get("prompt_id"),
        "name": doc.get("name", ""),
        "analysis_prompt": doc.get("analysis_prompt", ""),
    }


class _LegacyUpdatePromptRequest(BaseModel):
    analysis_prompt: str


@router.put("/api/analysis/prompt/{assistant_id}")
async def update_analysis_prompt_compat(assistant_id: str, body: _LegacyUpdatePromptRequest):
    """Compat: updates the default analysis prompt (assistant_id ignored)."""
    doc = await _get_default_prompt_doc()
    if doc is None:
        raise HTTPException(status_code=404, detail="No analysis prompts found — run the seeder")
    col = get_analysis_prompts_col()
    await col.update_one(
        {"prompt_id": doc["prompt_id"]},
        {"$set": {"analysis_prompt": body.analysis_prompt, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"assistant_id": assistant_id, "analysis_prompt": body.analysis_prompt}


# ---------------------------------------------------------------------------
# 5. Real metrics aggregation
# ---------------------------------------------------------------------------
# OUTCOME_SUCCESS now imported from backend/outcomes.py — the previous local
# set here used non-existent values ("Callback", "Already Purchased") and
# omitted real ones ("Approved", "Enriched"); see that module's docstring.


async def _compute_call_metrics(assistant_filter: dict, range: str) -> dict:
    """Core metrics aggregation over ai_lead_qualify.call_transcripts.

    assistant_filter is merged into every query — pass {} for no assistant
    scoping (org-wide), {"assistant_id": "x"} for a single assistant, or
    {"assistant_id": {"$in": [...]}} for a set of assistants (an org's agents).
    Shared by GET /api/metrics/{assistant_id} (single) and
    GET /api/dashboard/stats (org-wide).
    """
    col = get_transcripts_col()

    # Resolve date range
    now = datetime.now(timezone.utc)
    range_days = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}.get(range, 7)
    since = now - timedelta(days=range_days)
    prev_since = since - timedelta(days=range_days)

    def _date_query(start: datetime, end: datetime) -> dict:
        base: dict = dict(assistant_filter)
        # call_start_time may be a datetime, an ISO string, OR a raw Unix-epoch
        # float (the format bot.py itself writes) — the float case used to be
        # missing here, silently excluding every record stored that way from
        # both current- and previous-period metrics.
        base["$or"] = [
            {"call_start_time": {"$gte": start, "$lt": end}},
            {"call_start_time": {"$gte": start.isoformat(), "$lt": end.isoformat()}},
            {"call_start_time": {"$gte": start.timestamp(), "$lt": end.timestamp()}},
        ]
        return base

    # Current period stats
    q_curr = _date_query(since, now)
    total = await col.count_documents(q_curr)

    # Aggregate outcomes
    pipeline_outcomes = [
        {"$match": q_curr},
        {"$group": {
            "_id": "$analysis.call_outcome",
            "count": {"$sum": 1},
            "avg_duration": {"$avg": "$call_duration_sec"},
        }},
    ]
    outcome_docs = await col.aggregate(pipeline_outcomes).to_list(length=100)

    successful = sum(
        d["count"] for d in outcome_docs
        if d.get("_id") in OUTCOME_SUCCESS
    )
    failed = total - successful
    success_rate = round((successful / total * 100) if total else 0, 2)

    # Average duration across all calls
    all_durations = [d.get("avg_duration") or 0 for d in outcome_docs]
    avg_duration = round(sum(all_durations) / len(all_durations)) if all_durations else 0

    # Today / this week / this month
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    def _period_query(start: datetime) -> dict:
        base: dict = dict(assistant_filter)
        base["$or"] = [
            {"call_start_time": {"$gte": start}},
            {"call_start_time": {"$gte": start.isoformat()}},
        ]
        return base

    calls_today = await col.count_documents(_period_query(today_start))
    calls_week = await col.count_documents(_period_query(week_start))
    calls_month = await col.count_documents(_period_query(month_start))

    # Previous period for comparison
    q_prev = _date_query(prev_since, since)
    prev_total = await col.count_documents(q_prev)
    prev_outcomes = await col.aggregate([
        {"$match": q_prev},
        {"$group": {"_id": "$analysis.call_outcome", "count": {"$sum": 1}}},
    ]).to_list(length=100)
    prev_successful = sum(d["count"] for d in prev_outcomes if d.get("_id") in OUTCOME_SUCCESS)
    prev_success_rate = round((prev_successful / prev_total * 100) if prev_total else 0, 2)
    total_change = round(((total - prev_total) / prev_total * 100) if prev_total else 0, 1)
    sr_change = round(success_rate - prev_success_rate, 2)

    # Daily trends for the range
    trend_pipeline = [
        {"$match": q_curr},
        {"$addFields": {
            "call_start_dt": {
                "$cond": {
                    "if": {"$type": "$call_start_time"},  # always true — just convert
                    "then": {
                        "$dateFromString": {
                            "dateString": {"$toString": "$call_start_time"},
                            "onError": None,
                        }
                    },
                    "else": None,
                }
            }
        }},
        {"$group": {
            "_id": {
                "$dateToString": {
                    "format": "%Y-%m-%d",
                    "date": {
                        "$cond": {
                            "if": {"$eq": [{"$type": "$call_start_time"}, "date"]},
                            "then": "$call_start_time",
                            "else": {
                                "$dateFromString": {
                                    "dateString": "$call_start_time",
                                    "onError": now,
                                }
                            },
                        }
                    },
                }
            },
            "totalCalls": {"$sum": 1},
            "avgDuration": {"$avg": "$call_duration_sec"},
            "outcomes": {"$push": "$analysis.call_outcome"},
        }},
        {"$sort": {"_id": 1}},
    ]

    try:
        trend_docs = await col.aggregate(trend_pipeline).to_list(length=200)
    except Exception:
        trend_docs = []

    call_trends = []
    for td in trend_docs:
        day_outcomes = td.get("outcomes", [])
        day_total = td.get("totalCalls", 0)
        day_success = sum(1 for o in day_outcomes if o in OUTCOME_SUCCESS)
        call_trends.append({
            "timestamp": f"{td['_id']}T00:00:00Z",
            "totalCalls": day_total,
            "successfulCalls": day_success,
            "failedCalls": day_total - day_success,
            "avgDuration": round(td.get("avgDuration") or 0),
        })

    # Outcome breakdown
    outcome_breakdown = {d["_id"]: d["count"] for d in outcome_docs if d.get("_id")}

    return {
        "data": {
            "overview": {
                "totalCalls": total,
                "successfulCalls": successful,
                "failedCalls": failed,
                "successRate": success_rate,
                "avgCallDuration": avg_duration,
                "callsToday": calls_today,
                "callsThisWeek": calls_week,
                "callsThisMonth": calls_month,
            },
            "comparison": {
                "totalCallsChange": total_change,
                "successRateChange": sr_change,
                "avgDurationChange": 0,
                "periodLabel": f"vs previous {range}",
            },
            "callTrends": call_trends,
            "outcomeBreakdown": outcome_breakdown,
        }
    }


@router.get("/api/metrics/{assistant_id}")
async def get_metrics(
    assistant_id: str,
    range: str = Query("7d", description="Time range: 1d, 7d, 30d, 90d"),
):
    assistant_filter = {} if (not assistant_id or assistant_id == "all") else {"assistant_id": assistant_id}
    return await _compute_call_metrics(assistant_filter, range)


# ---------------------------------------------------------------------------
# 6. Org-wide dashboard stats — powers /dashboard/analytics + /dashboard/realtime
# ---------------------------------------------------------------------------

@router.get("/api/dashboard/stats")
async def get_dashboard_stats(
    organization_id: str = Query(...),
    range: str = Query("7d", description="Time range: 1d, 7d, 30d, 90d"),
):
    """Org-wide rollup of the same call_transcripts metrics as /api/metrics/{id},
    scoped to every assistant belonging to organization_id (instead of one
    assistant), plus an activeAgents count. Powers the dashboard's top-level
    analytics/realtime views.
    """
    a_col = get_assistants_col()
    assistant_docs = await a_col.find(
        {"organization_id": organization_id, "is_deleted": False},
        {"assistant_id": 1, "status": 1},
    ).to_list(length=10000)
    assistant_ids = [d["assistant_id"] for d in assistant_docs if d.get("assistant_id")]
    active_agents = sum(1 for d in assistant_docs if d.get("status") == "Active")

    if not assistant_ids:
        # No agents yet for this org — return an all-zero shape rather than
        # querying call_transcripts unscoped (which would leak other orgs' data).
        return {
            "data": {
                "overview": {
                    "totalCalls": 0, "successfulCalls": 0, "failedCalls": 0,
                    "successRate": 0, "avgCallDuration": 0,
                    "callsToday": 0, "callsThisWeek": 0, "callsThisMonth": 0,
                    "activeAgents": 0,
                },
                "comparison": {"totalCallsChange": 0, "successRateChange": 0, "avgDurationChange": 0, "periodLabel": f"vs previous {range}"},
                "callTrends": [],
                "outcomeBreakdown": {},
            }
        }

    result = await _compute_call_metrics({"assistant_id": {"$in": assistant_ids}}, range)
    result["data"]["overview"]["activeAgents"] = active_agents
    return result
