"""Pre-translates a bot's small set of literal, LLM-bypassing strings — the
nudge phrase, closing phrase, timeout message, greeting, and filler lines —
into a non-Hinglish/Hindi language, and caches the result in Mongo.

Why this exists: on the WebRTC test-call runtime (webrtc_bot.py /
pipecat_workflow_engine.py), every fixed line is spoken by having the LLM
"say this, applying the script/pronunciation rules above" — so the TARGET
LANGUAGE directive (see bot.py's build_system_prompt) translates them for
free, no extra latency. But the SIP/LiveKit production runtime
(voicebot_nodcode_platform/bot_dev.py) speaks these same lines via
session.say(literal_string) — completely bypassing the LLM, so there's
nothing to apply a directive to.

Translating on every call would put a Gemini round-trip in front of the
greeting (the only latency-critical one of this set — nudge/closing/timeout
don't fire until well after a call starts). Instead, this module is called
from update_assistant / update_workflow_bot as a background task whenever the
language, multilingual_enabled, or any of the source phrases change — so by
the time a call actually happens, bot_dev.py's read from `lang_string_cache`
is a plain Mongo point read, not a translation call.

The `/api/lang-cache/warm` route below exists purely as a safety net for a
genuine cold miss (brand-new bot, cache row evicted, translation failed
earlier) — bot_dev.py fires it in the background (never awaited) and speaks
the Hinglish source for that one call rather than blocking on it.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks

try:
    from ..mongo import get_assistants_col, get_lang_cache_col, get_workflow_bots_col
    from ..languages import LANG_CONFIGS
except ImportError:
    from mongo import get_assistants_col, get_lang_cache_col, get_workflow_bots_col
    from languages import LANG_CONFIGS

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TRANSLATE_MODEL = os.getenv("LANG_TRANSLATE_MODEL", "gemini-2.0-flash-lite")

router = APIRouter()


def _source_hash(source: Dict[str, Any]) -> str:
    """Changes whenever any source phrase changes — invalidates only the
    affected (bot_id, language) cache row instead of a blanket TTL."""
    return sha256(_json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _call_gemini_sync(prompt: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TRANSLATE_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }
    req = urllib.request.Request(
        url, data=_json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = _json.loads(r.read().decode())
    text_out = raw["candidates"][0]["content"]["parts"][0]["text"]
    return _json.loads(text_out)


async def translate_bot_strings(language_name: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """One Gemini call translating every source string/list at once. Raises on
    failure — the caller (warm_language_cache) treats that as "skip the cache
    write", leaving the previous cached entry (or none) in place."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured on backend")

    prompt = (
        f"Translate the MEANING of each value below from Hindi/Hinglish into natural, "
        f"conversational spoken {language_name} — how a real telecaller would say it on a "
        f"phone call, not a literal word-for-word translation. Keep the same tone (warm, "
        f"brief). Keep any product/brand names and numbers as-is. For list values, translate "
        f"every item and return a list of the same length in the same order.\n\n"
        f"Return ONLY a JSON object with exactly these keys, same shape as the input "
        f"(string in -> string out, list in -> list out):\n\n"
        f"{_json.dumps(source, ensure_ascii=False, indent=2)}"
    )
    result = await asyncio.get_event_loop().run_in_executor(None, _call_gemini_sync, prompt)
    # Defensive shape-check — a malformed Gemini response should never
    # silently write partial/wrong-shaped data into the cache.
    for key, val in source.items():
        if key not in result:
            raise ValueError(f"translation response missing key {key!r}")
        if isinstance(val, list) and not isinstance(result[key], list):
            raise ValueError(f"translation response key {key!r} should be a list")
    return result


def _build_source(bot_doc: Dict[str, Any], *, is_workflow: bool) -> Dict[str, Any]:
    """The exact PM-authored strings this bot would otherwise speak literally.
    Mirrors the fallback defaults bot_dev.py itself uses so a translated cache
    entry is never out of sync with what an untranslated call would say."""
    if is_workflow:
        greeting = ""  # workflow bots have no canned SIP greeting — start node speaks first
        closing = bot_doc.get("inactivity_end_phrase") or "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."
        timeout_message = ""  # no separate hard-timeout message on the workflow runtime today
    else:
        greeting = bot_doc.get("initial_message") or "हेलो मैं सिमरन बोल रही हूँ जस्टडायल से।"
        closing = bot_doc.get("inactivity_end_phrase") or (
            "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. "
            "अगर future में आपको किसी भी तरह की requirement हो, तो आप Justdial पर कभी भी call कर सकते हैं. धन्यवाद."
        )
        timeout_message = bot_doc.get("timeout_message") or (
            "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. जो भी details मिली हैं, "
            "sellers जल्द ही आपसे contact करेंगे. आपका समय देने के लिए धन्यवाद. अलविदा!"
        )
    return {
        "greeting": greeting,
        "nudge_phrase": bot_doc.get("inactivity_phrase") or "क्या आप अभी line पर हैं?",
        "closing_phrase": closing,
        "timeout_message": timeout_message,
        "filler_message": bot_doc.get("filler_message") or [],
        "function_filler_message": bot_doc.get("function_filler_message") or [],
    }


async def warm_language_cache(bot_type: str, bot_id: str, bot_doc: Dict[str, Any]) -> None:
    """Fire-and-forget entrypoint for a background task: translate + cache this
    bot's fixed strings for its currently-configured language, if that language
    needs translating at all. Silently returns/logs on any failure — this must
    never raise into the caller (a settings save should never fail because
    translation did).
    """
    language = bot_doc.get("language") or "hinglish"
    if language in ("hinglish", "hindi") or language not in LANG_CONFIGS:
        return  # nothing to translate — the source strings ARE the target language

    is_workflow = bot_type == "workflow"
    source = _build_source(bot_doc, is_workflow=is_workflow)
    doc_hash = _source_hash(source)

    col = get_lang_cache_col()
    existing = await col.find_one({"bot_id": bot_id, "language": language})
    if existing and existing.get("source_hash") == doc_hash:
        return  # already cached for this exact source text — nothing changed

    try:
        translated = await translate_bot_strings(LANG_CONFIGS[language]["name"], source)
    except Exception as exc:  # noqa: BLE001 — must never propagate out of a background task
        log.warning(f"[lang_cache] warm failed for bot_id={bot_id!r} language={language!r}: {exc}")
        return

    await col.update_one(
        {"bot_id": bot_id, "language": language},
        {"$set": {
            "bot_id": bot_id, "bot_type": bot_type, "language": language,
            "source_hash": doc_hash, "strings": translated,
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Safety-net route — bot_dev.py fires this (never awaited) on a cache miss at
# call start, so the NEXT call for this bot+language has a warm cache even if
# the settings-save background task never ran (e.g. backend restarted before
# it completed, or the bot's language was set before this feature existed).
# ---------------------------------------------------------------------------

@router.post("/api/lang-cache/warm")
async def warm_language_cache_route(bot_type: str, bot_id: str, background_tasks: BackgroundTasks):
    col = get_assistants_col() if bot_type == "assistant" else get_workflow_bots_col()
    id_field = "assistant_id" if bot_type == "assistant" else "workflow_bot_id"
    doc = await col.find_one({id_field: bot_id})
    if not doc:
        return {"warmed": False, "reason": "bot not found"}

    background_tasks.add_task(warm_language_cache, bot_type, bot_id, doc)
    return {"warmed": True}
