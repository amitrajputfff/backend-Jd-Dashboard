"""Analysis router — reads ai_lead_qualify.call_transcripts.

Endpoints:
  GET  /api/analysis/calls                    — paginated list of call transcripts + outcomes
  GET  /api/analysis/calls/{call_id}          — full transcript + analysis sub-doc
  POST /api/analysis/calls/{call_id}/rerun    — re-run analysis with assistant's analysis_prompt
  GET  /api/analysis/prompt/{assistant_id}    — read assistant's analysis_prompt
  PUT  /api/analysis/prompt/{assistant_id}    — update assistant's analysis_prompt
  GET  /api/metrics/{assistant_id}            — real aggregated metrics from call_transcripts
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

try:
    from ..mongo import get_transcripts_col, get_assistants_col, get_analysis_prompts_col
except ImportError:
    from mongo import get_transcripts_col, get_assistants_col, get_analysis_prompts_col

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


# ---------------------------------------------------------------------------
# 1. List call transcripts
# ---------------------------------------------------------------------------

@router.get("/api/analysis/calls")
async def list_analysis_calls(
    assistant_id: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    tagged: Optional[bool] = Query(None),
    date_from: Optional[str] = Query(None, description="ISO date e.g. 2026-01-01"),
    date_to: Optional[str] = Query(None, description="ISO date e.g. 2026-12-31"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    col = get_transcripts_col()
    query: dict = {}

    if assistant_id:
        query["assistant_id"] = assistant_id
    if tagged is not None:
        query["tagged"] = tagged
    if outcome:
        query["analysis.call_outcome"] = outcome
    if date_from or date_to:
        dt_filter: dict = {}
        if date_from:
            try:
                dt_filter["$gte"] = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        if date_to:
            try:
                dt_filter["$lte"] = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        if dt_filter:
            query["call_start_time"] = dt_filter

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
# 4. Analysis Prompts — standalone collection, not tied to any assistant
#    Future: a separate mapping table will link assistant_id → prompt_id.
# ---------------------------------------------------------------------------

import uuid as _uuid


def _prompt_doc_out(doc: dict) -> dict:
    """Shape a prompt document for API responses."""
    return {
        "prompt_id": doc.get("prompt_id", str(doc["_id"])),
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "analysis_prompt": doc.get("analysis_prompt", ""),
        "is_default": doc.get("is_default", False),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
    }


async def _get_default_prompt_doc() -> Optional[dict]:
    """Return the default prompt doc, falling back to the first one."""
    col = get_analysis_prompts_col()
    doc = await col.find_one({"is_default": True})
    if doc is None:
        doc = await col.find_one({}, sort=[("created_at", 1)])
    return doc


# --- List all prompts ---

@router.get("/api/analysis/prompts")
async def list_analysis_prompts():
    col = get_analysis_prompts_col()
    cursor = col.find({}, {"analysis_prompt": 0}).sort("created_at", 1)
    docs = await cursor.to_list(length=100)
    return [_prompt_doc_out({**d, "analysis_prompt": ""}) for d in docs]


# --- Get default prompt (must be registered before /{prompt_id}) ---

@router.get("/api/analysis/prompts/default")
async def get_default_analysis_prompt():
    doc = await _get_default_prompt_doc()
    if doc is None:
        raise HTTPException(status_code=404, detail="No analysis prompts found — run the seeder")
    return _prompt_doc_out(doc)


# --- Get specific prompt ---

@router.get("/api/analysis/prompts/{prompt_id}")
async def get_analysis_prompt_by_id(prompt_id: str):
    col = get_analysis_prompts_col()
    doc = await col.find_one({"prompt_id": prompt_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")
    return _prompt_doc_out(doc)


# --- Create prompt ---

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
    return _prompt_doc_out(doc)


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
    return _prompt_doc_out(doc)


# --- Delete prompt ---

@router.delete("/api/analysis/prompts/{prompt_id}", status_code=204)
async def delete_analysis_prompt(prompt_id: str):
    col = get_analysis_prompts_col()
    result = await col.delete_one({"prompt_id": prompt_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id!r} not found")


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

OUTCOME_SUCCESS = {
    "Interested", "Callback", "Will do it Myself", "Already Purchased",
}


@router.get("/api/metrics/{assistant_id}")
async def get_metrics(
    assistant_id: str,
    range: str = Query("7d", description="Time range: 1d, 7d, 30d, 90d"),
):
    col = get_transcripts_col()

    # Resolve date range
    now = datetime.now(timezone.utc)
    range_days = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}.get(range, 7)
    since = now - timedelta(days=range_days)
    prev_since = since - timedelta(days=range_days)

    def _date_query(start: datetime, end: datetime) -> dict:
        base: dict = {}
        if assistant_id and assistant_id != "all":
            base["assistant_id"] = assistant_id
        # call_start_time may be a datetime or ISO string
        base["$or"] = [
            {"call_start_time": {"$gte": start, "$lt": end}},
            {"call_start_time": {"$gte": start.isoformat(), "$lt": end.isoformat()}},
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
        base: dict = {}
        if assistant_id and assistant_id != "all":
            base["assistant_id"] = assistant_id
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
