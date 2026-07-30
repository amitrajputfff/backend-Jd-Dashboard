"""Server-side prompt version history for assistants — replaces the old
localStorage-only version history in JD-Dashboard's llm-config-section.tsx
(loadVersions/saveVersion, keyed by `pv_<assistantId>` in the browser, capped
at 3, invisible to anyone but the browser that saved them, with no "who
saved this" attribution at all).

Diffing and "restore" (setting the form field to an old version's text) stay
entirely client-side — see computeLineDiff/DiffViewer/handleRestore in
llm-config-section.tsx. This module only persists and lists snapshots; the
actual assistant.prompt field is written through the normal
PUT /api/assistants/{id} save flow when the user next saves the form.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

try:
    from ..mongo import get_prompt_versions_col
    from . import auth
except ImportError:
    from mongo import get_prompt_versions_col
    from routers import auth

router = APIRouter()

# Unbounded growth otherwise — one doc per save, forever. The old
# localStorage version capped at 3; this keeps more since Mongo storage
# isn't as scarce as a browser's localStorage quota.
MAX_VERSIONS_PER_ASSISTANT = 20


class SavePromptVersionRequest(BaseModel):
    prompt_text: str
    label: str = "Manual save"


def _serialize(doc: dict) -> Dict[str, Any]:
    created_at = doc.get("created_at")
    return {
        "id": str(doc.get("_id", "")),
        "assistant_id": doc.get("assistant_id", ""),
        "prompt_text": doc.get("prompt_text", ""),
        "label": doc.get("label", ""),
        "created_by": doc.get("created_by") or {"id": "unknown", "name": "Unknown", "email": ""},
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else (created_at or ""),
    }


@router.post("/api/assistants/{assistant_id}/prompt-versions", status_code=201)
async def save_prompt_version(
    assistant_id: str,
    data: SavePromptVersionRequest,
    authorization: Optional[str] = Header(default=None),
):
    if not data.prompt_text.strip():
        raise HTTPException(status_code=400, detail="Nothing to save — prompt is empty.")

    col = get_prompt_versions_col()

    # Skip saving an exact duplicate of the most recent version — same
    # de-dup rule the old localStorage saveVersion() had.
    last = await col.find_one({"assistant_id": assistant_id}, sort=[("created_at", -1)])
    if last and last.get("prompt_text") == data.prompt_text:
        return _serialize(last)

    user = await auth.get_current_user_optional(authorization)
    doc = {
        "assistant_id": assistant_id,
        "prompt_text": data.prompt_text,
        "label": data.label,
        "created_by": {
            "id": str((user or {}).get("id", "")) or "unknown",
            "name": (user or {}).get("name") or "Unknown",
            "email": (user or {}).get("email", ""),
        },
        "created_at": datetime.now(timezone.utc),
    }
    result = await col.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Trim to the most recent MAX_VERSIONS_PER_ASSISTANT.
    existing = await col.find({"assistant_id": assistant_id}).sort("created_at", -1).to_list(length=1000)
    if len(existing) > MAX_VERSIONS_PER_ASSISTANT:
        stale_ids = [d["_id"] for d in existing[MAX_VERSIONS_PER_ASSISTANT:]]
        await col.delete_many({"_id": {"$in": stale_ids}})

    return _serialize(doc)


@router.get("/api/assistants/{assistant_id}/prompt-versions")
async def list_prompt_versions(assistant_id: str) -> List[Dict[str, Any]]:
    col = get_prompt_versions_col()
    docs = (
        await col.find({"assistant_id": assistant_id})
        .sort("created_at", -1)
        .to_list(length=MAX_VERSIONS_PER_ASSISTANT)
    )
    return [_serialize(d) for d in docs]
