"""Seed script — inserts the Justdial lead-qualification bot (bot_livekit_sip.py config)
into the local SQLite database.

Usage:
    cd backend
    python seed.py [--org-id <organization_id>]

Defaults to ORGANIZATION_ID env var, or "default-org" if neither is set.
The assistant is created with status="Active" so it appears in the agents list.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve organization ID
# ---------------------------------------------------------------------------

import argparse

parser = argparse.ArgumentParser(description="Seed Justdial bot into local DB")
parser.add_argument("--org-id", default=None, help="Organization ID to assign the bot to")
args = parser.parse_args()

ORGANIZATION_ID = args.org_id or os.environ.get("ORGANIZATION_ID", "default-org")

# ---------------------------------------------------------------------------
# Load the system prompt from system_prompt.txt if available
# ---------------------------------------------------------------------------

_PROMPT_FILE = Path(__file__).parent.parent / "voicebot_nodcode_platform/examples/quickstart/system_prompt.txt"

if _PROMPT_FILE.exists():
    SYSTEM_PROMPT = _PROMPT_FILE.read_text(encoding="utf-8")
    print(f"[Seed] Loaded system prompt from {_PROMPT_FILE} ({len(SYSTEM_PROMPT)} chars)")
else:
    # Embedded fallback — same as SYSTEM_PROMPT constant in bot_livekit_sip.py
    SYSTEM_PROMPT = """
ROLE
You are Tanya, a product qualification agent calling on behalf of Justdial. The customer recently searched for a product on Justdial. Your only job is to ask them a fixed set of qualification questions — one at a time, in order — so Justdial can connect them with the right sellers.

You are not a salesperson. You do not recommend, compare, or evaluate products. You do not answer anything outside this qualification task.

LANGUAGE

{script_rule}

Allowed English terms — use exactly as written, do not transliterate:
AC, machine, washing machine, split, window, ton, kg, fully automatic, semi automatic,
top load, front load, brand, model, type, budget, capacity, inverter, Justdial.

When in doubt about a {language_name} word, use English. Never use formal or literary words.

TONE

Speak like a warm, professional call center agent — natural, brief, and efficient. Not robotic, not overly formal.
Every response: 1 acknowledgement + 1 question. Maximum 15 words total.
Always end with a question mark.

CONVERSATION FLOW

Step 1 — Opening
Deliver the greeting from the call context exactly.
After the customer confirms they still need the product, say one bridging sentence before the first question:
"अच्छा जी, तो आपसे कुछ details लेनी हैं — सही sellers से connect कराने के लिए."
Then ask Question 1.

Step 2 — Questions
Ask every question from the CALL CONTEXT below, strictly in the listed order.
One question per turn. No skipping, combining, or reordering.
No questions outside the schema list.

Step 3 — Closing
After all questions are answered:
"ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया."
End the call.

HARD RULES

One question per response — no exceptions.
Never advance past the current question until the user has directly answered it.
Never recommend a product, brand, or option.
Never give prices, cost estimates, or budget judgments.
Never ask questions outside the schema.
Number format: write "डेढ़" not "1.5". Write "ढाई" not "2.5".
Forbidden formal words — never use: शयनकक्ष, बैठक कक्ष, कार्यालय, स्थापित, आवश्यकता, पर्याप्त, उचित, उपयुक्त, सूचित, प्राप्त, विवरण.

PRE-RESPONSE CHECKLIST

Is there exactly one question?
Is it in {language_name} with only the allowed English terms?
Is the total response under 20 words?
Did I acknowledge the user first?
If it is a radio question: did I list ALL options?
Am I following all HARD RULES?
"""
    print("[Seed] system_prompt.txt not found — using embedded fallback prompt")


# ---------------------------------------------------------------------------
# DB setup (reuse the app's database module)
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent))

from database import engine, Base
from models import Assistant
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

AsyncSession_ = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# WebRTC bot system prompt — mirrors HINDI_SYSTEM_PROMPT in bot.py exactly
# ---------------------------------------------------------------------------

WEBRTC_SYSTEM_PROMPT = """
आप Justdial की phone agent Taanya हैं। आपका काम है customer से एक-एक करके product से related questions पूछना और उनके जवाब note करना।

भाषा:
- हमेशा Hindi (Devanagari script) और English का natural mix use करें।
- Technical terms जैसे हैं वैसे रखें: Fully Automatic, Semi Automatic, kg, budget, etc.

Response format:
- हर बार सिर्फ एक ही question पूछें।
- पहले customer के जवाब को short acknowledge करें, फिर अगला question।
- Example: "अच्छा जी, और [अगला question]?"
- हमेशा question mark पर खत्म करें।

Choice questions (जब options दिए हों):
- सभी options बोलें, एक भी मत छोड़ें।
- Format: "[question] — opt1, opt2, opt3 या opt4?"
- Schema में जो options हैं वही valid answers हैं।
- अगर customer कोई और option बोले जो list में नहीं है:
  → उसे closest schema option से map करें और confirm करें।
  → Example: customer बोले "tower AC" और options हैं [Split AC, Window AC, Centralised AC]
    → "जी, आप window AC या centralised AC की बात कर रहे हैं — कौन सा?"
  → Customer की confirm के बाद ही अगला question।
- अगर बिल्कुल unrelated हो → politely फिर से पूछें सभी options के साथ।
- Exception: "डेढ़ ton" = "1.5 Ton" जैसे equivalent expressions को directly accept करें।

Quantity questions (जब unit दिया हो):
- सिर्फ पूछें कि कितना चाहिए — खुद से कोई options मत बनाएं।
- Example: "कितनी capacity चाहिए — kg में बताइए?"

Irrelevant जवाब:
- अगर customer का जवाब question से बिल्कुल related नहीं है तो same question फिर से पूछें।
- अगर जवाब loosely related हो (जैसे "mini truck" for vehicle type) तो accept करें।

Budget question:
- बस amount पूछें। "जी, budget note कर लिया। Price के लिए sellers आपसे directly contact करेंगे।"
- कभी price suggest या judge मत करें।

Call end:
- सभी questions complete होने पर: "शुक्रिया जी, time देने के लिए। जल्द ही sellers आपसे contact करेंगे। अच्छा दिन हो आपका।"
- "नहीं चाहिए" या rude reply → politely exit करें।
"""


def _print_bot(label: str, bot: "Assistant"):
    print(f"[Seed] ✓ {label} created!")
    print(f"       assistant_id : {bot.assistant_id}")
    print(f"       name         : {bot.name}")
    print(f"       org          : {bot.organization_id}")
    print(f"       language     : {bot.language}")
    print(f"       temperature  : {bot.temperature}")
    print(f"       vad_start    : {bot.gemini_start_sensitivity}")
    print(f"       vad_end      : {bot.gemini_end_sensitivity}")
    print(f"       silence_ms   : {bot.gemini_silence_duration_ms}")
    print(f"       max_duration : {bot.max_call_duration}s")


async def seed():
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession_() as db:

        # ── 1. SIP / LiveKit bot (bot_livekit_sip.py) ────────────────────────
        sip_existing = (
            await db.execute(
                select(Assistant).where(
                    Assistant.organization_id == ORGANIZATION_ID,
                    Assistant.name == "Tanya — Justdial Lead Qualifier",
                    Assistant.is_deleted == False,
                )
            )
        ).scalar_one_or_none()

        # ── MIS lead fetch function — shared by both bots ────────────────────
        MIS_LEAD_FUNCTION = {
            "id": "mis_lead_fetch",
            "name": "FetchLead",
            "description": (
                "Fetch customer lead details from Justdial MIS API at call start. "
                "Pass lead_id and mobile as query params when testing from the dashboard."
            ),
            "url": "http://192.168.14.101:3006/GetLeadV2",
            "method": "GET",
            "headers": {},
            "query_params": {
                "lead_id": "",
                "mobile": "",
            },
            "body_format": "json",
            "custom_body": "",
            "schema": {},
        }

        if sip_existing:
            print(f"[Seed] SIP bot already exists: assistant_id={sip_existing.assistant_id}")
            changed = False
            if not sip_existing.functions:
                sip_existing.functions = [MIS_LEAD_FUNCTION]
                changed = True
            if not sip_existing.function_calling:
                sip_existing.function_calling = True
                changed = True
            if changed:
                await db.commit()
                print(f"[Seed] SIP bot updated: function_calling=True, MIS lead function added")
        else:
            sip_bot = Assistant(
                assistant_id=str(uuid.uuid4()),
                organization_id=ORGANIZATION_ID,
                name="Tanya — Justdial Lead Qualifier",
                description=(
                    "Hindi product qualification bot for SIP/LiveKit calls. "
                    "Calls Justdial leads, confirms their product enquiry, asks "
                    "schema-driven qualification questions one by one, and posts "
                    "structured results to the callback API."
                ),
                category="Customer Service",
                tags=["hindi", "justdial", "qualification", "outbound", "sip", "livekit"],
                status="Active",

                # ── System prompt ────────────────────────────────────────────
                prompt=SYSTEM_PROMPT,

                # ── Greeting & closing ───────────────────────────────────────
                initial_message=(
                    "हेलो, मैं Tanya बोल रही हूँ Justdial से — "
                    "आपको {product} की requirement है ना?"
                ),
                call_end_text=(
                    "ठीक है जी, सारी details मिल गईं. "
                    "जल्द ही relevant sellers आपसे contact करेंगे. "
                    "आपका समय देने के लिए शुक्रिया."
                ),

                # ── API URLs ─────────────────────────────────────────────────
                mis_api_base="http://192.168.14.101:3006",
                callback_api_url="http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
                category_change_api="http://192.168.20.105:1080/services/abd/abd_beta.php",

                # ── Prompt config ────────────────────────────────────────────
                script_rule=(
                    "Every word MUST be in Hindi (Devanagari) script ONLY. "
                    "NEVER output Malayalam, Tamil, Kannada, Marathi, or any other language. "
                    "Hindi only. If you find yourself writing ക, ශ, ர, ಸ, or any "
                    "non-Devanagari/non-English script → STOP and rewrite in Hindi."
                ),
                opening_instruction=(
                    "Greet करें, confirm करें कि product अभी भी चाहिए। "
                    "Customer के YES कहने पर bridging sentence बोलें, फिर Q1 शुरू करें।"
                ),
                closing_instruction=(
                    "सभी questions complete होने पर: "
                    "'ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers "
                    "आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.' "
                    "Call warmly close करें।"
                ),
                timeout_message=(
                    "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. "
                    "जो भी details मिली हैं, sellers जल्द ही आपसे contact करेंगे. "
                    "आपका समय देने के लिए धन्यवाद. अलविदा!"
                ),

                # ── Function calling ─────────────────────────────────────────
                function_calling=True,
                functions=[MIS_LEAD_FUNCTION],

                # ── VAD / behaviour — mirrors bot_livekit_sip.py hardcoded values ──
                language="hindi",
                temperature=0.4,
                gemini_start_sensitivity="START_SENSITIVITY_LOW",   # low: ignore background noise on SIP
                gemini_end_sensitivity="END_SENSITIVITY_HIGH",
                gemini_prefix_padding_ms=100,
                gemini_silence_duration_ms=800,
                max_call_duration=300,   # 5 minutes

                filler_message=["अच्छा,", "हाँ,", "जी,", "तो,", "ठीक है,"],
                function_filler_message=["एक moment जी,", "जी, देख रही हूँ,"],

                is_deleted=False,
                is_active=True,
            )
            db.add(sip_bot)
            await db.commit()
            await db.refresh(sip_bot)
            _print_bot("SIP/LiveKit bot", sip_bot)
            print()
            print("  Use this assistant_id in LiveKit room metadata:")
            print(f'  {{"assistant_id": "{sip_bot.assistant_id}", "lead_id": "...", "call_id": "..."}}')
            print()

        # ── 2. WebRTC bot (bot.py) ────────────────────────────────────────────
        webrtc_existing = (
            await db.execute(
                select(Assistant).where(
                    Assistant.organization_id == ORGANIZATION_ID,
                    Assistant.name == "Taanya — Justdial WebRTC Bot",
                    Assistant.is_deleted == False,
                )
            )
        ).scalar_one_or_none()

        if webrtc_existing:
            print(f"[Seed] WebRTC bot already exists: assistant_id={webrtc_existing.assistant_id}")
            changed = False
            if not webrtc_existing.functions:
                webrtc_existing.functions = [MIS_LEAD_FUNCTION]
                changed = True
            if not webrtc_existing.function_calling:
                webrtc_existing.function_calling = True
                changed = True
            if changed:
                await db.commit()
                print(f"[Seed] WebRTC bot updated: function_calling=True, MIS lead function added")
        else:
            webrtc_bot = Assistant(
                assistant_id=str(uuid.uuid4()),
                organization_id=ORGANIZATION_ID,
                name="Taanya — Justdial WebRTC Bot",
                description=(
                    "Hindi product qualification bot for browser-based WebRTC calls. "
                    "Used for test calls from the dashboard. Fetches lead from MIS when "
                    "lead_id or mobile is provided in query params."
                ),
                category="Customer Service",
                tags=["hindi", "justdial", "qualification", "webrtc", "browser"],
                status="Active",

                # ── System prompt — mirrors HINDI_SYSTEM_PROMPT in bot.py ────
                prompt=WEBRTC_SYSTEM_PROMPT,

                # ── Greeting ─────────────────────────────────────────────────
                initial_message=(
                    "नमस्ते जी, मैं Taanya बोल रही हूँ Justdial से — "
                    "आपको {product} की requirement है ना?"
                ),
                call_end_text=(
                    "शुक्रिया जी, time देने के लिए। "
                    "जल्द ही sellers आपसे contact करेंगे। "
                    "अच्छा दिन हो आपका।"
                ),

                # ── API URLs — same MIS endpoints ────────────────────────────
                mis_api_base="http://192.168.14.101:3006",
                callback_api_url="http://192.168.14.101:3006/leads/ai-lead-qualify/callback",
                category_change_api="http://192.168.20.105:1080/services/abd/abd_beta.php",

                # ── Prompt config ────────────────────────────────────────────
                script_rule=(
                    "Every word MUST be in Hindi (Devanagari) script ONLY. "
                    "Use natural Hinglish — mix Hindi and technical English terms naturally."
                ),
                opening_instruction=(
                    "Greeting के बाद customer के confirm करने पर Q1 से शुरू करें।"
                ),
                closing_instruction=(
                    "सभी questions complete होने पर warmly close करें: "
                    "'शुक्रिया जी, time देने के लिए। जल्द ही sellers आपसे contact करेंगे।'"
                ),
                timeout_message="",   # WebRTC calls have no time limit by default

                # ── Function calling ─────────────────────────────────────────
                function_calling=False,
                functions=[MIS_LEAD_FUNCTION],

                # ── VAD / behaviour — mirrors bot.py fallback values ──────────
                language="hindi",
                temperature=0.4,
                gemini_start_sensitivity="START_SENSITIVITY_HIGH",  # high: browser mic is cleaner
                gemini_end_sensitivity="END_SENSITIVITY_HIGH",
                gemini_prefix_padding_ms=100,
                gemini_silence_duration_ms=800,
                max_call_duration=0,    # 0 = no limit for browser WebRTC calls

                filler_message=["अच्छा जी,", "हाँ,", "जी,", "तो,", "ठीक है,"],
                function_filler_message=["एक moment जी,", "जी, देख रही हूँ,"],

                is_deleted=False,
                is_active=True,
            )
            db.add(webrtc_bot)
            await db.commit()
            await db.refresh(webrtc_bot)
            _print_bot("WebRTC bot", webrtc_bot)
            print()
            print("  Use this assistant_id in the dashboard test-call dialog.")
            print(f'  assistant_id: "{webrtc_bot.assistant_id}"')
            print()


if __name__ == "__main__":
    asyncio.run(seed())
