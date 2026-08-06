"""FastAPI backend for the No-Code Platform agents dashboard.

Run:
    cd /No-Code-Platform/backend
    uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # load backend/.env before any module reads os.environ

try:
    from .routers import assistants, auth, bot_config, call_logs, analysis, phone_numbers, workflow_bots, tts_preview, function_test, mock_vendor, lang_cache, export, audit, prompt_versions, admin, golive, users
    from .mongo import get_assistants_col, get_users_col, get_workflow_bots_col, get_audit_logs_col, get_protected_rules_col, get_golive_requests_col
except ImportError:
    from routers import assistants, auth, bot_config, call_logs, analysis, phone_numbers, workflow_bots, tts_preview, function_test, mock_vendor, lang_cache, export, audit, prompt_versions, admin, golive, users
    from mongo import get_assistants_col, get_users_col, get_workflow_bots_col, get_audit_logs_col, get_protected_rules_col, get_golive_requests_col


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure indexes exist on startup
    col = get_assistants_col()
    await col.create_index("assistant_id", unique=True)
    await col.create_index("created_by")
    await col.create_index([("created_by", 1), ("is_deleted", 1)])
    await col.create_index("is_locked")

    # Workflow bots indexes
    wb_col = get_workflow_bots_col()
    await wb_col.create_index("workflow_bot_id", unique=True)
    await wb_col.create_index("created_by")
    await wb_col.create_index([("created_by", 1), ("is_deleted", 1)])
    await wb_col.create_index("is_locked")

    # Users (login accounts) indexes
    users_col = get_users_col()
    await users_col.create_index("email", unique=True)
    await users_col.create_index("id", unique=True)

    # Audit logs indexes — newest-first is the default sort on every query.
    audit_col = get_audit_logs_col()
    await audit_col.create_index([("timestamp", -1)])
    await audit_col.create_index([("organization_id", 1), ("timestamp", -1)])
    await audit_col.create_index("resource_id")

    # RBAC: protected phone numbers + go-live request queue.
    protected_col = get_protected_rules_col()
    await protected_col.create_index("rule_id", unique=True)

    golive_col = get_golive_requests_col()
    await golive_col.create_index("id", unique=True)
    await golive_col.create_index([("status", 1), ("created_at", -1)])
    await golive_col.create_index("requested_by")
    yield


app = FastAPI(
    title="No-Code Platform API",
    description="Backend for the JD-Dashboard agents management",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes — prefix /backend so paths match what the frontend hardcodes:
#   GET http://localhost:8000/backend/api/assistants
app.include_router(assistants.router, prefix="/backend")
app.include_router(call_logs.router, prefix="/backend")
app.include_router(analysis.router, prefix="/backend")
app.include_router(phone_numbers.router, prefix="/backend")
app.include_router(workflow_bots.router, prefix="/backend")
app.include_router(bot_config.router, prefix="/backend")
app.include_router(tts_preview.router, prefix="/backend")
app.include_router(function_test.router, prefix="/backend")
app.include_router(mock_vendor.router, prefix="/backend")
app.include_router(auth.router, prefix="/backend")
app.include_router(lang_cache.router, prefix="/backend")
app.include_router(export.router, prefix="/backend")
app.include_router(audit.router, prefix="/backend")
app.include_router(prompt_versions.router, prefix="/backend")
app.include_router(admin.router, prefix="/backend")
app.include_router(golive.router, prefix="/backend")
app.include_router(users.router, prefix="/backend")


@app.get("/health")
async def health():
    return {"status": "ok"}
