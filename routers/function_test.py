"""Function validation / test-invoke — powers the dashboard's per-function
"Validate" button (Advanced Settings > Function Calling).

The frontend (JD-Dashboard/src/lib/api/function-validation.ts) has always
POSTed here, but this endpoint didn't exist yet — the button just showed a
generic network error. This performs the same HTTP call shape the bot
engine's `call_configured_function` (voicebot_nodcode_platform/bot.py) makes
at call time, so "Validate" tells you whether the function will actually
work on a real call, then returns the flattened response field paths (e.g.
"buyer_details.buyer_name") so the dashboard can offer them as draggable
variables in the system-prompt builder.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter()

_TIMEOUT = aiohttp.ClientTimeout(total=8)


class FunctionTestRequest(BaseModel):
    name: str = ""
    description: str = ""
    url: str = ""
    method: str = "POST"
    headers: Dict[str, Any] = Field(default_factory=dict)
    query_params: Dict[str, Any] = Field(default_factory=dict)
    body_format: str = "json"
    custom_body: Any = ""
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    # Optional sample values (e.g. {"lead_id": "123", "mobile": "9999999999"})
    # merged into query_params/body the same way call-time runtime_params are,
    # so the test call can exercise a real record instead of a bare template.
    sample_params: Dict[str, Any] = Field(default_factory=dict)
    # Optional dot path (list indices allowed, e.g. "results.data.0") — see
    # AssistantFunction.response_path in backend/schemas.py. Applied to the
    # response the same way the bot runtime applies it at call time, so
    # Validate discovers fields from the unwrapped record, not the raw
    # envelope, for a function whose response isn't already flat.
    response_path: str = ""

    model_config = {"populate_by_name": True}


class FunctionValidationResponse(BaseModel):
    function_name: str
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    status_code: Optional[int] = None
    response: Any = None
    # Flattened dotted-path field names from `response`, e.g.
    # ["buyer_details.buyer_name", "qualification_schema.catname"] — used to
    # populate the draggable variable chips in the prompt builder.
    keys: List[str] = Field(default_factory=list)


def _flatten_keys(value: Any, prefix: str = "", out: Optional[List[str]] = None) -> List[str]:
    """Matches bot.py's _flatten_dict (the runtime {fn.X.field} resolver)
    exactly, so a chip offered here is guaranteed resolvable at call time.

    A list is only worth recursing into when its first element is itself a
    dict (sampled to discover that shape's fields, same as the runtime
    resolver). A list of scalars — e.g. {"questions_block": ["Q1", "Q2"]} —
    has no further path to expose, so its OWN key must be appended as a leaf
    instead of silently vanishing (the previous unconditional recursion
    tried to flatten value[0] directly, hit a bare string/number, and
    produced nothing at all — the whole field disappeared from the
    draggable-variable list even though the runtime resolver can return it).
    """
    if out is None:
        out = []
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                _flatten_keys(v, path, out)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                _flatten_keys(v[0], path, out)
            else:
                out.append(path)
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        _flatten_keys(value[0], prefix, out)
    return out


def _resolve_response_path(data: Any, path: str) -> Any:
    """Verbatim port of bot.py's _resolve_response_path — duplicated rather
    than imported because backend/ and voicebot_nodcode_platform/ are
    separate processes/environments (see backend/outcomes.py's docstring for
    the same reasoning). Dot-path lookup into a nested dict/list API
    response, e.g. "results.data.0" walks data["results"]["data"][0]. List
    segments must be plain integer indices. Returns None if any segment is
    missing/out of range."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


@router.post("/api/function-validation/validate", response_model=FunctionValidationResponse)
async def validate_function(data: FunctionTestRequest) -> FunctionValidationResponse:
    errors: List[str] = []
    warnings: List[str] = []

    name = (data.name or "").strip()
    url = (data.url or "").strip()
    method = (data.method or "POST").upper()

    if not name:
        errors.append("Function name is required.")
    if not url:
        errors.append("Function URL is required.")
    elif not (url.startswith("http://") or url.startswith("https://")):
        errors.append("Function URL must start with http:// or https://.")
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        errors.append(f"Unsupported HTTP method: {method!r}")
    if not data.description:
        warnings.append("No description set — the LLM uses this to decide when to call the function.")
    if not data.schema_:
        warnings.append("No parameter schema set — this function will be treated as on-start-only, not LLM-callable, unless one is added.")

    if errors:
        return FunctionValidationResponse(function_name=name, is_valid=False, errors=errors, warnings=warnings)

    merged = {**data.query_params, **data.sample_params}
    merged = {k: v for k, v in merged.items() if v not in (None, "")}
    query_string = "&".join(f"{k}={v}" for k, v in merged.items())
    # Mirrors the same fix in bot.py's call_configured_function — a url that
    # already has its own "?..." (e.g. pasted with a query string already in
    # it) must get "&", not a second "?", or the merged params land inside
    # one opaque key instead of becoming real query params.
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}{query_string}" if query_string else url

    status_code: Optional[int] = None
    response_json: Any = None
    response_text: Optional[str] = None
    try:
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(full_url, headers=data.headers, timeout=_TIMEOUT) as resp:
                    status_code = resp.status
                    response_text = await resp.text()
            else:
                body: Any = data.custom_body or {}
                if isinstance(body, str):
                    try:
                        body = json.loads(body) if body.strip() else {}
                    except Exception:
                        body = {}
                if isinstance(body, dict):
                    body = {**body, **data.sample_params}
                kwargs = {"data": body} if data.body_format == "form-data" else {"json": body}
                async with session.request(method, full_url, headers=data.headers, timeout=_TIMEOUT, **kwargs) as resp:
                    status_code = resp.status
                    response_text = await resp.text()
    except Exception as e:
        log.warning(f"[FunctionTest] {name!r} call to {full_url} failed: {e}")
        errors.append(f"Request failed: {e}")
        return FunctionValidationResponse(
            function_name=name, is_valid=False, errors=errors, warnings=warnings, status_code=status_code,
        )

    # The endpoint responded — parse the body separately from the connection
    # attempt above, so a 200 with a non-JSON body (e.g. text/html) is reported
    # distinctly instead of falling into the generic "Request failed" branch.
    if response_text:
        try:
            response_json = json.loads(response_text)
        except Exception:
            if status_code is not None and status_code < 400:
                warnings.append(f"HTTP {status_code} OK, but the response body isn't JSON — no fields could be discovered.")

    if status_code is not None and status_code >= 400:
        errors.append(f"Endpoint returned HTTP {status_code}.")

    # Same unwrapping the bot runtime applies at call time (bot.py's
    # _execute_function_call) — without this, Validate discovered fields
    # from the raw envelope (e.g. "results.data.0.buyer_details.buyer_name")
    # instead of the unwrapped record the prompt builder actually resolves
    # against ("buyer_details.buyer_name"), so every discovered-field chip
    # was wrong for any function configured with a response_path.
    response_path = (data.response_path or "").strip()
    unwrapped = response_json
    if response_path and isinstance(response_json, (dict, list)):
        resolved = _resolve_response_path(response_json, response_path)
        if resolved is not None:
            unwrapped = resolved
        else:
            warnings.append(f"response_path {response_path!r} found nothing in the response.")

    keys = _flatten_keys(unwrapped) if isinstance(unwrapped, (dict, list)) else []

    return FunctionValidationResponse(
        function_name=name,
        is_valid=not errors,
        errors=errors,
        warnings=warnings,
        status_code=status_code,
        response=response_json if response_json is not None else response_text,
        keys=keys,
    )
