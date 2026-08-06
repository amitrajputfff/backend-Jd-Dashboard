"""Audit logs — read-only endpoint for JD-Dashboard's Audit Logs page
(src/lib/api/audit.ts -> GET /api/audit/logs/all-filters).

Logs themselves are written by backend/audit_log.py's write_audit_log(),
called from routers/assistants.py and routers/workflow_bots.py right after
every create/update/delete/restore/clone. This router only reads them back.

Admin-only (RBAC — see routers/auth.py's module docstring): this is a full
cross-user activity trail, and the frontend already gated its page on
system.admin (src/app/audit-logs/page.tsx's withAuditLogsGuard) — that was
previously decorative since every user had system.admin; now it's backed by
a real server-side check.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

try:
    from ..mongo import get_audit_logs_col
    from . import auth
except ImportError:
    from mongo import get_audit_logs_col
    from routers import auth

router = APIRouter()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _serialize(doc: dict) -> Dict[str, Any]:
    ts = doc.get("timestamp")
    return {
        "id": str(doc.get("_id", "")),
        "organizationId": doc.get("organization_id", ""),
        "timestamp": ts.isoformat() if isinstance(ts, datetime) else (ts or ""),
        "user": doc.get("user") or {"id": "unknown", "name": "Unknown", "email": "", "role": "unknown"},
        "action": doc.get("action", ""),
        "resource": doc.get("resource", ""),
        "resourceId": doc.get("resource_id", ""),
        "details": doc.get("details", ""),
        "ipAddress": doc.get("ip_address", ""),
        "userAgent": doc.get("user_agent", ""),
        "location": doc.get("location", ""),
        "device": doc.get("device", ""),
        "status": doc.get("status", "success"),
        "severity": doc.get("severity", "low"),
        "metadata": doc.get("metadata"),
    }


@router.get("/api/audit/logs/all-filters")
async def list_audit_logs(
    organization_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    admin: dict = Depends(auth.require_admin),
) -> List[Dict[str, Any]]:
    col = get_audit_logs_col()
    query: Dict[str, Any] = {}

    if organization_id:
        query["organization_id"] = organization_id
    if user_id:
        query["user.id"] = user_id
    if action:
        query["action"] = action
    if resource:
        query["resource"] = resource
    if resource_id:
        query["resource_id"] = resource_id
    if severity:
        query["severity"] = severity
    if status:
        query["status"] = status
    if user:
        query["$or"] = [
            {"user.name": {"$regex": user, "$options": "i"}},
            {"user.email": {"$regex": user, "$options": "i"}},
        ]
    if search:
        query["$or"] = [
            {"action": {"$regex": search, "$options": "i"}},
            {"details": {"$regex": search, "$options": "i"}},
            {"resource": {"$regex": search, "$options": "i"}},
            {"user.name": {"$regex": search, "$options": "i"}},
            {"user.email": {"$regex": search, "$options": "i"}},
        ]

    time_query: Dict[str, Any] = {}
    if start_date:
        time_query["$gte"] = _parse_dt(start_date)
    if end_date:
        time_query["$lte"] = _parse_dt(end_date)
    if since:
        time_query["$gt"] = _parse_dt(since)
    if time_query:
        query["timestamp"] = time_query

    cursor = col.find(query).sort("timestamp", -1).skip(offset).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [_serialize(d) for d in docs]
