#!/usr/bin/env python3
"""One-shot: seed Simran bot into MongoDB no_code_platform.assistants"""
import ast, asyncio, re, sys
from datetime import datetime, timezone
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://192.168.13.65:27017"
DB_NAME   = "no_code_platform"
ORG_ID    = sys.argv[1] if len(sys.argv) > 1 else "default-org"
SIMRAN_UUID = "e8c0fd31-2d60-4531-a029-2047b17988c4"


def load_prompt():
    f = Path(__file__).parent.parent / "voicebot_nodcode_platform" / "bot.py"
    if not f.exists():
        return "Edit this prompt from the dashboard."
    src = f.read_text(encoding="utf-8")
    m = re.search(
        r'"system_prompt":\s*(\((?:[^()]*|\([^()]*\))*\))\s*,\s*"initial_message"',
        src, re.DOTALL)
    if m:
        try:
            p = ast.literal_eval(m.group(1).strip())
            print(f"[seed] prompt extracted: {len(p)} chars")
            return p
        except Exception as e:
            print(f"[seed] ast failed: {e}")
    return "Edit this prompt from the dashboard."


SIMRAN_FUNCTIONS = [
    {"name": "FetchLead",
     "description": "Fetch customer lead details from Justdial MIS API at call start.",
     "url": "http://192.168.8.67:8000/leads/ai-lead-qualify/mis",
     "method": "GET", "headers": {},
     "query_params": {"lead_id": "", "mobile": "", "page": "1", "limit": "1", "ai_partner": "inh-suny-bot"},
     "body_format": "json", "custom_body": "", "schema": {}},
    {"name": "FetchCategorySchema",
     "description": "Fetches qualification schema when buyer changes product mid-call.",
     "url": "http://192.168.8.67:8000/leads/ai-lead-qualify/search",
     "method": "GET", "headers": {},
     "query_params": {"lead_id": "", "search_term": ""},
     "body_format": "json", "custom_body": "",
     "schema": {"type": "object",
                "properties": {"srchterm": {"type": "string", "description": "New product search term in English"}},
                "required": ["srchterm"]}},
]


async def main():
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db  = client[DB_NAME]
    col = db["assistants"]
    ctr = db["counters"]

    await col.create_index("assistant_id", unique=True)
    prompt = load_prompt()
    now = datetime.now(timezone.utc)

    existing = await col.find_one({"assistant_id": SIMRAN_UUID})
    if existing:
        updates = {
            "prompt": prompt,
            "initial_message": "हेलो, मैं Simran बोल रही हूँ Justdial से — आपको {product} की requirement है ना?",
            "call_end_text": "ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.",
            "mis_api_base": "http://192.168.8.67:8000",
            "callback_api_url": "http://192.168.8.67:8000/leads/ai-lead-qualify/callback",
            "category_change_api": "http://192.168.8.67:8000/leads/ai-lead-qualify/search",
            "script_rule": "By default, write in Hindi (Devanagari) script. Natural Hinglish is encouraged.",
            "closing_instruction": "Once every question has an answer say the Hindi closing line. Say it once, only when ALL questions are done.",
            "timeout_message": "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. जो भी details मिली हैं, sellers जल्द ही आपसे contact करेंगे. आपका समय देने के लिए धन्यवाद. अलविदा!",
            "function_calling": True, "functions": SIMRAN_FUNCTIONS,
            "language": "hindi", "temperature": 0.7,
            "gemini_start_sensitivity": "START_SENSITIVITY_HIGH",
            "gemini_end_sensitivity": "END_SENSITIVITY_LOW",
            "gemini_silence_duration_ms": 1500, "gemini_prefix_padding_ms": 200,
            "max_call_duration": 300,
            "filler_message": ["अच्छा,", "हाँ,", "जी,", "तो,", "ठीक है,"],
            "function_filler_message": ["एक moment जी,", "जी, देख रही हूँ,"],
            "sarvam_min_rms": 600, "sarvam_min_speech_ms": 500,
            "sarvam_min_speech_ms_singleword": 800, "sarvam_silero_threshold": 0.5,
            "sarvam_silero_min_speech_ms": 120, "gemini_silero_fallback_speech_ms": 150,
            "post_speech_hold_ms": 300,
            "inactivity_first_rescue_secs": 4.0, "inactivity_first_nudge_gap_secs": 4.0,
            "inactivity_nudge_secs": 10.0, "inactivity_close_secs": 5.0,
            "analysis_prompt": "", "updated_at": now,
        }
        await col.update_one({"assistant_id": SIMRAN_UUID}, {"$set": updates})
        print(f"[seed] Updated Simran in MongoDB (id={existing['id']})")
    else:
        ctr_doc = await ctr.find_one_and_update(
            {"_id": "assistant_id"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
        aid = ctr_doc["seq"]
        doc = {
            "id": aid, "assistant_id": SIMRAN_UUID, "organization_id": ORG_ID,
            "name": "Simran — Justdial Lead Qualifier (SIP)",
            "description": "Active SIP/LiveKit voice bot. Female persona Simran. Hindi/Hinglish.",
            "category": "Customer Service",
            "tags": ["hindi", "justdial", "qualification", "sip", "livekit", "simran"],
            "status": "Active",
            "prompt": prompt,
            "initial_message": "हेलो, मैं Simran बोल रही हूँ Justdial से — आपको {product} की requirement है ना?",
            "call_end_text": "ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.",
            "mis_api_base": "http://192.168.8.67:8000",
            "callback_api_url": "http://192.168.8.67:8000/leads/ai-lead-qualify/callback",
            "category_change_api": "http://192.168.8.67:8000/leads/ai-lead-qualify/search",
            "script_rule": "By default, write in Hindi (Devanagari) script. Natural Hinglish is encouraged.",
            "opening_instruction": "",
            "closing_instruction": "Once every question has an answer say the Hindi closing line. Say it once, only when ALL questions are done.",
            "timeout_message": "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. जो भी details मिली हैं, sellers जल्द ही आपसे contact करेंगे. आपका समय देने के लिए धन्यवाद. अलविदा!",
            "function_calling": True, "functions": SIMRAN_FUNCTIONS,
            "language": "hindi", "temperature": 0.7,
            "gemini_start_sensitivity": "START_SENSITIVITY_HIGH",
            "gemini_end_sensitivity": "END_SENSITIVITY_LOW",
            "gemini_silence_duration_ms": 1500, "gemini_prefix_padding_ms": 200,
            "max_call_duration": 300,
            "filler_message": ["अच्छा,", "हाँ,", "जी,", "तो,", "ठीक है,"],
            "function_filler_message": ["एक moment जी,", "जी, देख रही हूँ,"],
            "sarvam_min_rms": 600, "sarvam_min_speech_ms": 500,
            "sarvam_min_speech_ms_singleword": 800, "sarvam_silero_threshold": 0.5,
            "sarvam_silero_min_speech_ms": 120, "gemini_silero_fallback_speech_ms": 150,
            "post_speech_hold_ms": 300,
            "inactivity_first_rescue_secs": 4.0, "inactivity_first_nudge_gap_secs": 4.0,
            "inactivity_nudge_secs": 10.0, "inactivity_close_secs": 5.0,
            "analysis_prompt": "", "is_deleted": False, "is_active": True,
            "calls_today": 0, "created_at": now, "updated_at": now,
        }
        await col.insert_one(doc)
        print(f"[seed] Created Simran in MongoDB: assistant_id={SIMRAN_UUID} id={aid}")

    # Verify
    check = await col.find_one({"assistant_id": SIMRAN_UUID}, {"prompt": 0})
    print(f"[seed] Verify: {check}")
    client.close()


asyncio.run(main())
