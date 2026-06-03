"""Seed script — upserts the Justdial lead-qualification bots into MongoDB.

Usage:
    cd backend
    uv run python seed.py [--org-id <organization_id>]
"""

import argparse
import ast
import asyncio
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--org-id", default=None)
args = parser.parse_args()
ORGANIZATION_ID = args.org_id or os.environ.get("ORGANIZATION_ID", "default-org")

sys.path.insert(0, str(Path(__file__).parent))
from mongo import get_assistants_col, get_counters_col, next_sequence


# ---------------------------------------------------------------------------
# Extract system prompt from bot.py
# ---------------------------------------------------------------------------

def _load_simran_prompt() -> str:
    bot_file = Path(__file__).parent.parent / "voicebot_nodcode_platform" / "bot.py"
    if not bot_file.exists():
        print("[Seed] bot.py not found — using placeholder prompt")
        return "Update this system prompt from the dashboard."
    src = bot_file.read_text(encoding="utf-8")
    # Match the parenthesised string expression after "system_prompt":
    m = re.search(
        r'"system_prompt":\s*(\((?:[^()]*|\([^()]*\))*\))\s*,\s*"initial_message"',
        src,
        re.DOTALL,
    )
    if m:
        try:
            prompt = ast.literal_eval(m.group(1).strip())
            print(f"[Seed] Loaded Simran system_prompt from bot.py ({len(prompt)} chars)")
            return prompt
        except Exception as e:
            print(f"[Seed] ast.literal_eval failed: {e} — using placeholder")
    else:
        print("[Seed] Could not find system_prompt in bot.py — using placeholder")
    return "Update this system prompt from the dashboard."


# ---------------------------------------------------------------------------
# Bot documents
# ---------------------------------------------------------------------------

SIMRAN_UUID = "e8c0fd31-2d60-4531-a029-2047b17988c4"

SIMRAN_FUNCTIONS = [
    {
        "name": "FetchLead",
        "description": "Fetch customer lead details from Justdial MIS API at call start.",
        "url": "http://192.168.14.101:3006/leads/ai-lead-qualify/mis",
        "method": "GET",
        "headers": {},
        "query_params": {"lead_id": "", "mobile": "", "page": "1", "limit": "1", "ai_partner": "inh-suny-bot"},
        "body_format": "json",
        "custom_body": "",
        "schema": {},
    },
    {
        "name": "FetchCategorySchema",
        "description": "Fetches the new qualification schema when the buyer changes their product mid-call.",
        "url": "http://192.168.8.67:8000/leads/ai-lead-qualify/search",
        "method": "GET",
        "headers": {},
        "query_params": {"lead_id": "", "search_term": ""},
        "body_format": "json",
        "custom_body": "",
        "schema": {
            "type": "object",
            "properties": {"srchterm": {"type": "string", "description": "New product search term in English"}},
            "required": ["srchterm"],
        },
    },
]


def _simran_doc(aid: int, prompt: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": aid,
        "assistant_id": SIMRAN_UUID,
        "organization_id": ORGANIZATION_ID,
        "name": "Simran — Justdial Lead Qualifier (SIP)",
        "description": "Active SIP/LiveKit voice bot for Justdial lead qualification. Female persona 'Simran'. Hindi/Hinglish with full conversation rules.",
        "category": "Customer Service",
        "tags": ["hindi", "justdial", "qualification", "outbound", "sip", "livekit", "simran"],
        "status": "Active",
        "prompt": prompt,
        "initial_message": "हेलो, मैं Simran बोल रही हूँ Justdial से — आपको {product} की requirement है ना?",
        "call_end_text": "ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.",
        "mis_api_base": "http://192.168.8.67:8000",
        "callback_api_url": "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
        "category_change_api": "http://192.168.8.67:8000/leads/ai-lead-qualify/search",
        "script_rule": (
            "By default, write in Hindi (Devanagari) script.\n"
            "Natural Hinglish is encouraged — mix in everyday English words the way a real call center agent would.\n"
            "API-provided English words (from question.text or option.text): always use them exactly as-is.\n"
            "EXCEPTION — Language switching: If the caller has explicitly asked you to speak in a different language, switch entirely."
        ),
        "opening_instruction": "",
        "closing_instruction": (
            "Once every question has an answer, say the closing line in whichever language is active:\n"
            "• Hindi (default): \"ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.\"\n"
            "• English (if language was switched): \"Alright, I have all the details. The relevant sellers will contact you soon. Thank you for your time.\"\n"
            "Say this once, only when ALL questions are done."
        ),
        "timeout_message": (
            "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. "
            "जो भी details मिली हैं, sellers जल्द ही आपसे contact करेंगे. "
            "आपका समय देने के लिए धन्यवाद. अलविदा!"
        ),
        "function_calling": True,
        "functions": SIMRAN_FUNCTIONS,
        "language": "hindi",
        "temperature": 0.7,
        "gemini_start_sensitivity": "START_SENSITIVITY_HIGH",
        "gemini_end_sensitivity": "END_SENSITIVITY_LOW",
        "gemini_silence_duration_ms": 1500,
        "gemini_prefix_padding_ms": 200,
        "max_call_duration": 300,
        "filler_message": ["अच्छा,", "हाँ,", "जी,", "तो,", "ठीक है,"],
        "function_filler_message": ["एक moment जी,", "जी, देख रही हूँ,"],
        "sarvam_min_rms": 600,
        "sarvam_min_speech_ms": 500,
        "sarvam_min_speech_ms_singleword": 800,
        "sarvam_silero_threshold": 0.5,
        "sarvam_silero_min_speech_ms": 120,
        "gemini_silero_fallback_speech_ms": 150,
        "post_speech_hold_ms": 300,
        "inactivity_first_rescue_secs": 4.0,
        "inactivity_first_nudge_gap_secs": 4.0,
        "inactivity_nudge_secs": 10.0,
        "inactivity_close_secs": 5.0,
        "analysis_prompt": "",
        "is_deleted": False,
        "is_active": True,
        "calls_today": 0,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

async def seed():
    col = get_assistants_col()
    await col.create_index("assistant_id", unique=True)

    prompt = _load_simran_prompt()

    # Upsert Simran bot
    existing = await col.find_one({"assistant_id": SIMRAN_UUID})
    if existing:
        # Update all config fields (keep id/created_at intact)
        update_fields = _simran_doc(existing["id"], prompt)
        update_fields.pop("id", None)
        update_fields.pop("created_at", None)
        update_fields["updated_at"] = datetime.now(timezone.utc)
        await col.update_one({"assistant_id": SIMRAN_UUID}, {"$set": update_fields})
        print(f"[Seed] Simran bot updated in MongoDB: assistant_id={SIMRAN_UUID}")
    else:
        aid = await next_sequence("assistant_id")
        doc = _simran_doc(aid, prompt)
        await col.insert_one(doc)
        print(f"[Seed] Simran bot created in MongoDB: assistant_id={SIMRAN_UUID}, id={aid}")

    print(f"[Seed] Done. prompt_len={len(prompt)}")
    print()
    print("  Set this in LiveKit room metadata:")
    print(f'  {{"assistant_id": "{SIMRAN_UUID}", "lead_id": "...", "call_id": "..."}}')


if __name__ == "__main__":
    asyncio.run(seed())
