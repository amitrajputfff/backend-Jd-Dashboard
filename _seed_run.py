"""Run once to seed Simran bot into MongoDB."""
import ast, re, sys
from datetime import datetime, timezone
from pathlib import Path
from pymongo import MongoClient

ORG = sys.argv[1] if len(sys.argv) > 1 else "default-org"
UUID = "e8c0fd31-2d60-4531-a029-2047b17988c4"

src = (Path(__file__).parent.parent / "voicebot_nodcode_platform" / "bot.py").read_text()
m = re.search(r'"system_prompt":\s*(\((?:[^()]*|\([^()]*\))*\))\s*,\s*"initial_message"', src, re.DOTALL)
prompt = ast.literal_eval(m.group(1).strip()) if m else "Edit from dashboard"
print(f"prompt: {len(prompt)} chars")

c   = MongoClient("mongodb://192.168.13.65:27017")
col = c["no_code_platform"]["assistants"]
ctr = c["no_code_platform"]["counters"]
col.create_index("assistant_id", unique=True)

now = datetime.now(timezone.utc)
FUNCS = [
    {"name":"FetchLead","description":"Fetch lead from MIS","url":"http://192.168.14.101:3006/leads/ai-lead-qualify/mis","method":"GET","headers":{},"query_params":{"lead_id":"","mobile":"","page":"1","limit":"1","ai_partner":"inh-suny-bot"},"body_format":"json","custom_body":"","schema":{}},
    {"name":"FetchCategorySchema","description":"Fetch schema for product change","url":"http://192.168.8.67:8000/leads/ai-lead-qualify/search","method":"GET","headers":{},"query_params":{"lead_id":"","search_term":""},"body_format":"json","custom_body":"","schema":{"type":"object","properties":{"srchterm":{"type":"string"}},"required":["srchterm"]}},
]
fields = {
    "prompt": prompt,
    "initial_message": "हेलो, मैं Simran बोल रही हूँ Justdial से — आपको {product} की requirement है ना?",
    "call_end_text": "ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.",
    "mis_api_base": "http://192.168.8.67:8000",
    "callback_api_url": "http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
    "category_change_api": "http://192.168.8.67:8000/leads/ai-lead-qualify/search",
    "script_rule": "By default write in Hindi Devanagari. Natural Hinglish encouraged.",
    "opening_instruction": "",
    "closing_instruction": "Say closing line once ALL questions are answered.",
    "timeout_message": "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. अलविदा!",
    "function_calling": True, "functions": FUNCS,
    "language": "hindi", "temperature": 0.7,
    "gemini_start_sensitivity": "START_SENSITIVITY_HIGH",
    "gemini_end_sensitivity": "END_SENSITIVITY_LOW",
    "gemini_silence_duration_ms": 1500, "gemini_prefix_padding_ms": 200,
    "max_call_duration": 300,
    "filler_message": ["अच्छा,","हाँ,","जी,","तो,","ठीक है,"],
    "function_filler_message": ["एक moment जी,","जी, देख रही हूँ,"],
    "sarvam_min_rms": 600, "sarvam_min_speech_ms": 500,
    "sarvam_min_speech_ms_singleword": 800, "sarvam_silero_threshold": 0.5,
    "sarvam_silero_min_speech_ms": 120, "gemini_silero_fallback_speech_ms": 150,
    "post_speech_hold_ms": 300,
    "inactivity_first_rescue_secs": 4.0, "inactivity_first_nudge_gap_secs": 4.0,
    "inactivity_nudge_secs": 10.0, "inactivity_close_secs": 5.0,
    "analysis_prompt": "", "updated_at": now,
}

ex = col.find_one({"assistant_id": UUID})
if ex:
    col.update_one({"assistant_id": UUID}, {"$set": fields})
    print(f"UPDATED id={ex['id']}")
else:
    r = ctr.find_one_and_update({"_id":"assistant_id"},{"$inc":{"seq":1}},upsert=True,return_document=True)
    doc = {"id": r["seq"], "assistant_id": UUID, "organization_id": ORG,
           "name": "Simran — Justdial Lead Qualifier", "description": "SIP LiveKit bot",
           "category": "Customer Service", "tags": ["hindi","sip","simran"],
           "status": "Active", "is_deleted": False, "is_active": True,
           "calls_today": 0, "created_at": now, **fields}
    col.insert_one(doc)
    print(f"CREATED id={r['seq']}")

v = col.find_one({"assistant_id": UUID}, {"prompt": 0, "_id": 0})
print("OK:", v)
c.close()
