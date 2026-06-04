"""FastAPI backend for the No-Code Platform agents dashboard.

Run:
    cd /No-Code-Platform/backend
    uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from .routers import assistants, call_logs, analysis
    from .mongo import get_assistants_col
except ImportError:
    from routers import assistants, call_logs, analysis
    from mongo import get_assistants_col


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure indexes exist on startup
    col = get_assistants_col()
    await col.create_index("assistant_id", unique=True)
    await col.create_index("organization_id")
    await col.create_index([("organization_id", 1), ("is_deleted", 1)])
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


@app.get("/health")
async def health():
    return {"status": "ok"}
