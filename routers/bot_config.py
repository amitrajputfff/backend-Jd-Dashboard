"""Unified bot-config resolver — one endpoint for both assistants and workflow bots.

A bot runtime (LiveKit or WebRTC) that only has an id from room metadata /
the test dialog doesn't otherwise know whether that id names a regular
Assistant or a WorkflowBot — those live in separate Mongo collections with
separate CRUD routers. This tries assistants first, then workflow_bots, and
returns whichever matches. The response's `bot_type` field ("assistant" |
"workflow", see schemas.BotConfig/WorkflowBotConfig) tells the caller which
kind it got so it can dispatch to the right execution path.

Endpoint: GET /api/bot-config/{id}
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

try:
    from . import assistants, workflow_bots
except ImportError:
    from routers import assistants, workflow_bots

router = APIRouter()


@router.get("/api/bot-config/{id}")
async def get_unified_bot_config(id: str):
    """Resolve `id` against assistants first, then workflow_bots.

    Reuses the existing, already-tested per-collection endpoint functions
    rather than duplicating their field-mapping logic.
    """
    try:
        return await assistants.get_bot_config(id)
    except HTTPException as e:
        if e.status_code != 404:
            raise

    try:
        return await workflow_bots.get_workflow_bot_config(id)
    except HTTPException as e:
        if e.status_code != 404:
            raise

    raise HTTPException(
        status_code=404,
        detail=f"No assistant or workflow bot found for id {id!r}",
    )
