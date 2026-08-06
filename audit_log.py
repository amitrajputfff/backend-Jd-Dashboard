"""Shared audit-log write helper, called from assistants.py/workflow_bots.py
right after a successful create/update/delete/restore.

Never raises: an audit-log write failure must not fail the actual operation
it's describing (same pattern as this codebase's other non-critical
background writes — see warm_language_cache, _bump_calls_today).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from .mongo import get_audit_logs_col
except ImportError:
    from mongo import get_audit_logs_col

log = logging.getLogger(__name__)


async def write_audit_log(
    *,
    user: Optional[dict],
    action: str,
    resource: str,
    resource_id: str = "",
    organization_id: str = "",
    details: str = "",
    status: str = "success",
    severity: str = "low",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Insert one audit_logs doc. `user` is whatever get_current_user_optional()
    (auth.py) resolved from the request's Bearer token — None if it was
    missing/invalid, in which case the entry is still written (an
    unattributed change is still worth recording), just tagged 'unknown'.
    """
    try:
        col = get_audit_logs_col()
        await col.insert_one({
            "organization_id": organization_id,
            "timestamp": datetime.now(timezone.utc),
            "user": {
                "id": str((user or {}).get("id", "")) or "unknown",
                "name": (user or {}).get("name") or "Unknown",
                "email": (user or {}).get("email", ""),
                "role": (user or {}).get("role") or "unknown",
            },
            "action": action,
            "resource": resource,
            "resource_id": resource_id,
            "details": details,
            "ip_address": "",
            "user_agent": "",
            "location": "",
            "device": "",
            "status": status,
            "severity": severity,
            "metadata": metadata,
        })
    except Exception as e:
        log.warning(f"[AuditLog] Failed to write {action!r} on {resource!r}={resource_id!r}: {e}")
