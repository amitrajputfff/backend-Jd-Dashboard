"""Data export — powers the dashboard's Export Data dialog
(JD-Dashboard/src/components/export-data-dialog.tsx via lib/api/export.ts),
which POSTs here and expects a downloadable file blob back. This endpoint
did not exist at all before — every "Export Data" button in the dashboard
(Calls, Agents, Audit Logs, Account) called or wanted to call it and got a
404 or a "coming soon" stub.

CSV only, by design — no PDF-generation library in this backend, and CSV
covers the actual use case (open in Excel/Sheets).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    from ..mongo import get_assistants_col, get_call_logs_col
    from . import phone_numbers as _phone_numbers
except ImportError:
    from mongo import get_assistants_col, get_call_logs_col
    from routers import phone_numbers as _phone_numbers

log = logging.getLogger(__name__)
router = APIRouter()


class ExportDataRequest(BaseModel):
    organization_id: str
    export_type: str  # "assistants" | "call_logs" | "phone_numbers"
    format: str = "csv"
    start_date: str
    end_date: str
    include_relationships: bool = True
    include_metadata: bool = True


def _parse_bound(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value!r}")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return "" if value is None else str(value)


def _rows_to_csv(rows: List[Dict[str, Any]], columns: List[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _fmt(row.get(c)) for c in columns})
    return buf.getvalue().encode("utf-8")


_ASSISTANT_COLUMNS = [
    "assistant_id", "name", "description", "category", "status",
    "language", "tts_provider_id", "voice_id", "temperature",
    "function_calling", "call_recording", "is_active", "is_deleted",
    "is_locked", "calls_today", "created_at", "updated_at",
]

_CALL_LOG_COLUMNS = [
    "id", "call_sid", "from_number", "to_number", "assistant_id",
    "status", "call_type", "outcome", "sentiment", "summary",
    "duration_seconds", "is_transfered", "transfer_number",
    "recording_link", "created_at", "updated_at",
]

_PHONE_NUMBER_COLUMNS = [
    "id", "phone_number", "name", "agent_name", "trunk_id", "type",
    "is_active", "is_protected", "created_at", "updated_at",
]


async def _export_assistants(organization_id: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    col = get_assistants_col()
    query = {
        "organization_id": organization_id,
        "created_at": {"$gte": start, "$lte": end},
    }
    return await col.find(query).sort("created_at", -1).to_list(length=10000)


async def _export_call_logs(organization_id: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    col = get_call_logs_col()
    # created_at is stored as an ISO string here (see routers/call_logs.py's
    # create_call_log), not a datetime — unlike the assistants collection.
    query = {
        "organization_id": organization_id,
        "created_at": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }
    docs = await col.find(query).sort("created_at", -1).to_list(length=10000)
    for d in docs:
        d["id"] = str(d.pop("_id", ""))
    return docs


async def _export_phone_numbers(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    # LiveKit SIP dispatch rules aren't scoped by organization_id at all (see
    # routers/phone_numbers.py's _build_row — that field is always ""), so
    # this can only filter by date, not by org.
    rules, trunks_by_id = await _phone_numbers._fetch_all_rules_and_trunks()
    bots_by_id = await _phone_numbers._fetch_bots_map(_phone_numbers._extract_assistant_ids(rules))
    rows = []
    for rule in rules:
        row = await _phone_numbers._build_row(rule, trunks_by_id, bots_by_id)
        created = _parse_bound(row["created_at"], "created_at") if row.get("created_at") else None
        if created and not (start <= created <= end):
            continue
        rows.append(row)
    return rows


@router.post("/api/export/data")
async def export_data(data: ExportDataRequest):
    if data.format != "csv":
        raise HTTPException(status_code=400, detail="Only CSV export is supported.")

    start = _parse_bound(data.start_date, "start_date")
    end = _parse_bound(data.end_date, "end_date")

    if data.export_type == "assistants":
        rows = await _export_assistants(data.organization_id, start, end)
        columns = _ASSISTANT_COLUMNS
    elif data.export_type == "call_logs":
        rows = await _export_call_logs(data.organization_id, start, end)
        columns = _CALL_LOG_COLUMNS
    elif data.export_type == "phone_numbers":
        rows = await _export_phone_numbers(start, end)
        columns = _PHONE_NUMBER_COLUMNS
    else:
        raise HTTPException(status_code=400, detail=f"Unknown export_type: {data.export_type!r}")

    content = _rows_to_csv(rows, columns)
    filename = f"export_{data.export_type}_{datetime.now(timezone.utc).date().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
