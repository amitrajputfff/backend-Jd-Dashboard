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
    if out is None:
        out = []
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                _flatten_keys(v, path, out)
            else:
                out.append(path)
    elif isinstance(value, list) and value:
        _flatten_keys(value[0], prefix, out)
    return out


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
    full_url = f"{url}?{query_string}" if query_string else url

    status_code: Optional[int] = None
    response_json: Any = None
    try:
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(full_url, headers=data.headers, timeout=_TIMEOUT) as resp:
                    status_code = resp.status
                    response_json = await resp.json(content_type=None)
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
                    response_json = await resp.json(content_type=None)
    except Exception as e:
        log.warning(f"[FunctionTest] {name!r} call to {full_url} failed: {e}")
        errors.append(f"Request failed: {e}")
        return FunctionValidationResponse(
            function_name=name, is_valid=False, errors=errors, warnings=warnings, status_code=status_code,
        )

    if status_code is not None and status_code >= 400:
        errors.append(f"Endpoint returned HTTP {status_code}.")

    keys = _flatten_keys(response_json) if isinstance(response_json, (dict, list)) else []

    return FunctionValidationResponse(
        function_name=name,
        is_valid=not errors,
        errors=errors,
        warnings=warnings,
        status_code=status_code,
        response=response_json,
        keys=keys,
    )
