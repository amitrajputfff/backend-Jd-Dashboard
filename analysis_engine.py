"""Lazy, env-safe bridge to voicebot_nodcode_platform's analysis engine.

Used only by POST /api/analysis/test (routers/analysis.py) — the read-only
dry-run endpoint that lets a user test a candidate analysis prompt against a
real call's transcript before saving it. Nothing else in the backend imports
callback_worker.

The import is deferred to first use (mirroring seed_analysis_prompts.py's
sys.path.insert + try/except ImportError pattern) so backend startup never
depends on the voicebot_nodcode_platform package being present. It also
snapshots and restores os.environ around the import: callback_worker/config.py
does `load_dotenv(<repo>/.env, override=True)` at import time against the BOT's
own .env, which would otherwise clobber this process's environment (e.g.
LIVEKIT_*) for the rest of the backend's lifetime. Restoring afterwards is
safe — config.py's constants (GEMINI_API_KEY, etc.) are read once into module
globals at that exact import moment and keep their values regardless of what
os.environ reverts to.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_WORKER_ROOT = str(Path(__file__).resolve().parent.parent / "voicebot_nodcode_platform")

_generate_call_analysis = None
_generate_b2b_score = None
_import_error: str | None = None


def _ensure_imported() -> None:
    global _generate_call_analysis, _generate_b2b_score, _import_error
    if _generate_call_analysis is not None or _import_error is not None:
        return

    if _WORKER_ROOT not in sys.path:
        sys.path.insert(0, _WORKER_ROOT)

    snapshot = dict(os.environ)
    try:
        from callback_worker.analysis import generate_b2b_score, generate_call_analysis

        _generate_call_analysis = generate_call_analysis
        _generate_b2b_score = generate_b2b_score
    except Exception as exc:  # ImportError, or anything raised at module import time
        _import_error = f"{type(exc).__name__}: {exc}"
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


async def run_dry_run_analysis(
    doc: dict,
    *,
    prompt_template: str | None,
    http_session,
    model: str | None = None,
) -> tuple[dict, dict, dict]:
    """Run generate_call_analysis() + generate_b2b_score() against an existing
    call doc's stored transcript, WITHOUT writing anything back — no tagged,
    no analysis field mutation, no callback. Mirrors the argument-building
    callback_worker/processing.py's analyze_and_store() does, but that
    function is deliberately NOT called here (it writes to Mongo and can
    trigger the MIS callback).

    Returns (analysis_dict, b2b_score_dict, debug_dict). Raises RuntimeError
    if the analysis engine couldn't be imported at all.
    """
    _ensure_imported()
    if _import_error:
        raise RuntimeError(f"Could not load analysis engine: {_import_error}")

    schema = (doc.get("lead_record") or {}).get("qualification_schema", {}) or {}
    status = doc.get("status", "completed")
    transcript = doc.get("transcript") or []
    muted_transcript = doc.get("muted_transcript") or []
    gemini_connect_failed = bool(doc.get("gemini_connect_failed"))
    duration_secs = doc.get("call_duration_sec")
    greeting_done = bool(doc.get("greeting_done", True))
    user_speech_ms = int(doc.get("user_speech_ms") or 0)
    wrong_opener_detected = bool(doc.get("wrong_opener_detected", False))

    buyer = ((doc.get("lead_record") or {}).get("buyer_details") or {})
    try:
        is_business_flag = int(buyer.get("is_business_flag")) if buyer.get("is_business_flag") is not None else None
    except (ValueError, TypeError):
        is_business_flag = None

    debug: dict = {}
    kwargs = dict(
        muted_transcript=muted_transcript,
        gemini_connect_failed=gemini_connect_failed,
        duration_secs=duration_secs,
        greeting_done=greeting_done,
        user_speech_ms=user_speech_ms,
        wrong_opener_detected=wrong_opener_detected,
        is_business_flag=is_business_flag,
        prompt_template=prompt_template,
        debug=debug,
    )
    if model:
        kwargs["model"] = model

    analysis = await _generate_call_analysis(transcript, status, schema, http_session, **kwargs)
    b2b_score = await _generate_b2b_score(transcript, http_session)

    return analysis, b2b_score, debug
