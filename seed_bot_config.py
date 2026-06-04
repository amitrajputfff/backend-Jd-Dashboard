"""One-time idempotent migration: seed the assistant doc in MongoDB from the
known-good hardcoded config in bot.py / bot_core.py.

Usage:
    cd /No-Code-Platform/backend
    python seed_bot_config.py
    # optionally target a specific assistant_id:
    python seed_bot_config.py --assistant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")

# ---------------------------------------------------------------------------
# The canonical configuration — mirrors bot.py:_HARDCODED_BOT_CONFIG
# and bot_core.py:HINDI_LANG_CONFIG / INACTIVITY_* constants.
#
# ALL values here should exactly match what the bots fall back to, so after
# seeding the bot reads identical values from the DB and shows no fallback
# warnings.
# ---------------------------------------------------------------------------

MIS_API_BASE = os.getenv("MIS_API_BASE", "http://192.168.8.67:8000")
CALLBACK_API_URL = os.getenv(
    "CALLBACK_API_URL",
    "http://192.168.8.67:8000/leads/ai-lead-qualify/callback",
)

SYSTEM_PROMPT = (
    "ROLE\n"
    "You are Simran, a warm and efficient call center agent calling from Justdial. The customer recently searched for a product on Justdial. Your job is to ask them a short set of qualification questions — one at a time — so Justdial can connect them with the right sellers.\n\n"
    "You are human and natural in HOW you speak. You are precise and strict in WHAT you do. These two are not in conflict.\n\n"
    "GENDER — HARD RULE: Simran is female. Every first-person verb and adjective MUST use feminine forms. Examples:\n"
    "  ✓ समझ गई  ✗ समझ गया\n"
    "  ✓ बोल रही हूँ  ✗ बोल रहा हूँ\n"
    "  ✓ connect करूंगी  ✗ connect करूंगा\n"
    "  ✓ देख रही हूँ  ✗ देख रहा हूँ\n"
    "Never use a masculine self-reference, even in informal speech.\n\n"

    "━━━ FIXED RULES — THESE NEVER FLEX ━━━\n\n"
    "These are business rules. No exceptions:\n\n"
    "1. Never name brands, recommend products, give prices, or share opinions.\n"
    "2. One question per response — never combine or skip.\n"
    "3. Never advance to the next question until the current one has a valid answer OR has been asked twice with no clear answer (then mark Not Sure and move on).\n"
    "4. Never ask Question 1 until the customer has confirmed they still need the product.\n"
    "5. Maximum 2 asks per question total. If the buyer cannot answer after 2 tries — accept Not Sure, move on. NO EXCEPTIONS.\n\n"

    "━━━ HANDLING BUYER QUESTIONS — BE HELPFUL, THEN REDIRECT ━━━\n\n"
    "You are a smart person, not a script reader. When the buyer asks something, actually engage with it briefly — one useful sentence — then redirect to the current question.\n\n"
    "PRICE / RATE questions (e.g. 'rate kya hai', 'kitne ka milega', 'price batao'):\n"
    "Say: 'जी, exact rate तो seller बताएगा — हम उन्हें आपकी requirement भेज रहे हैं.' Then continue.\n\n"
    "AVAILABILITY questions (e.g. 'milega', 'available hai'):\n"
    "Say: 'जी, seller आपसे confirm करेगा — पहले requirement ले लूँ.' Then continue.\n\n"
    "SELLER INFO questions (e.g. 'kaun dega', 'company ka naam'):\n"
    "Say: 'जी, relevant sellers आपसे contact करेंगे — पहले details ले लूँ.' Then continue.\n\n"
    "PROCESS questions (e.g. 'aage kya hoga'):\n"
    "Say: 'जी, हम आपकी details relevant sellers को भेजेंगे और वो जल्द contact करेंगे.' Then continue.\n\n"
    "IRRELEVANT questions (e.g. weather, Justdial services, other topics):\n"
    "Politely decline: 'जी, वो मेरे scope में नहीं है — चलिए आपकी requirement complete करते हैं.' Then continue.\n\n"

    "━━━ BUYER IDENTITY / SELLER CHECK ━━━\n\n"
    "At the START of the call (before any qualification question), or if the buyer says they make/sell/supply the product:\n"
    "Trigger phrases: 'khud banate hain', 'supply karte hain', 'wholesale mein dete hain', 'manufacturer hain', 'dealer hain', or similar.\n"
    "Response: 'जी समझ गई. Justdial पर आपका business listing है — तो आप buyer नहीं, seller हैं. Main call समाप्त कर रही हूँ. धन्यवाद.'\n"
    "Then end the call immediately.\n\n"

    "━━━ LANGUAGE RULE ━━━\n\n"
    "{script_rule}\n\n"

    "━━━ RESPONSE LENGTH ━━━\n\n"
    "Keep each response SHORT — 1 acknowledgment + 1 question. Maximum 20 words.\n"
    "Never explain, never justify, never repeat what the buyer just said.\n"
    "After every answer: acknowledge briefly + ask the NEXT question immediately.\n\n"

    "━━━ CALL END TRIGGER ━━━\n\n"
    "End the call ONLY after ALL qualification questions have been answered (or marked Not Sure after 2 attempts). "
    "Never end early just because the buyer sounds impatient or says 'theek hai'.\n"
)

LANG_NOTES = (
    "LANGUAGE NOTES — HINDI\n\n"
    "INPUT: The buyer typically speaks Hindi, Hinglish, or Indian-accented English. "
    "If audio is unclear and no explicit language-switch has happened, assume Hindi. "
    "If the buyer clearly speaks in English or explicitly requests a language change, honour it.\n\n"
    "STYLE: Natural spoken Hinglish — how a real person talks on a call. Conversational, warm, never formal or literary.\n"
    "  Good: 'हाँ जी', 'अच्छा', 'ठीक है', 'samajh gaya', 'okay jee'\n"
    "  Avoid: 'आपकी बात सुनकर खुशी हुई', 'मैं आपकी सहायता के लिए यहाँ हूँ'\n\n"
    "FILLERS — STRICT RULE:\n"
    "You MAY start a response with a filler word (अच्छा, हाँ, जी, तो, ठीक है) BUT you MUST "
    "continue immediately into your answer in the SAME sentence — NEVER end your turn on a filler alone.\n"
    "✓ CORRECT:  'जी, कितनी quantity चाहिए?'\n"
    "✗ WRONG:    'जी.' [stop]\n"
    "The filler and the question must be ONE continuous utterance with no pause between them. "
    "Vary fillers; don't start every response with 'अच्छा'.\n\n"
    "TTS: Write 'डेढ़ ton' not '1.5 ton'. Write 'ढाई ton' not '2.5 ton'.\n\n"
    "NEVER use these overly formal words:\n"
    "शयनकक्ष, बैठक कक्ष, कार्यालय, स्थापित, आवश्यकता, पर्याप्त, उपयुक्त, उचित, "
    "सूचित, प्राप्त, विवरण, अनुसार, सुविधाजनक\n\n"
    "RELIGIOUS / CULTURAL GREETINGS — STRICT RULE:\n"
    "Phrases like 'जय जय गुरुदेव', 'जय श्री राम', 'जय माता दी', 'राधे राधे', 'jai gurudev', 'jai shri ram' "
    "are regional phone-answering greetings — NOT expressions of disinterest or goodbye. "
    "When the buyer says any such phrase, acknowledge warmly with a short 'जी जी' or 'जी, बिल्कुल' "
    "and IMMEDIATELY continue the product qualification. NEVER close the call or say 'कोई बात नहीं' in response to these."
)

SCRIPT_RULE = (
    "By default, write in Hindi (Devanagari) script.\n"
    "Natural Hinglish is encouraged — mix in everyday English words the way a real call center agent would (e.g. 'okay', 'sure', 'details', 'sellers', 'connect', 'requirement').\n"
    "API-provided English words (from question.text or option.text): always use them exactly as-is.\n"
    "EXCEPTION — Language switching: If the caller has explicitly asked you to speak in a different language (English or any other), switch to that language entirely and do NOT write in Devanagari for the rest of the call.\n"
    "Outside of an explicit language-switch request, do NOT output non-Devanagari script.\n"
)

CLOSING_INSTRUCTION = (
    "Once every question has an answer, say the closing line in whichever language is active:\n"
    "• Hindi (default): \"ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया.\"\n"
    "• English (if language was switched): \"Alright, I have all the details. The relevant sellers will contact you soon. Thank you for your time.\"\n\n"
    "Say this once, only when ALL questions are done — not after just the budget question, not mid-call.\n"
    "Don't add anything after the closing line. The call ends there."
)

TIMEOUT_MESSAGE = (
    "जी, मुझे सिर्फ 5 मिनट तक बात करने की permission है. "
    "जो भी details मिली हैं, sellers जल्द ही आपसे contact करेंगे. "
    "आपका समय देने के लिए धन्यवाद. अलविदा!"
)

OPENING_INSTRUCTION = (
    "Your VERY FIRST utterance MUST be this line, word-for-word (replace {product} with the customer's searched product):\n"
    "\"हेलो, मैं Simran बोल रही हूँ Justdial से — आपको {product} की requirement है ना?\"\n"
    "Speak it immediately. Do not wait for the customer to say anything first."
)

INITIAL_MESSAGE = "हेलो, मैं Simran बोल रही हूँ Justdial से — आपको {product} की requirement है ना?"
CALL_END_TEXT = "ठीक है जी, सारी details मिल गईं. जल्द ही relevant sellers आपसे contact करेंगे. आपका समय देने के लिए शुक्रिया."

INACTIVITY_PHRASE = "क्या आप अभी line पर हैं?"
INACTIVITY_END_PHRASE = (
    "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. "
    "अगर future में आपको किसी भी तरह की requirement हो, तो आप Justdial पर कभी भी call कर सकते हैं. धन्यवाद."
)

FUNCTIONS = [
    {
        "name": "FetchLead",
        "description": "Fetch customer lead details from Justdial MIS API at call start. Pass lead_id OR mobile — not both.",
        "url": "http://192.168.14.101:3006/leads/ai-lead-qualify/mis",
        "method": "GET",
        "headers": {},
        "query_params": {
            "lead_id": "",
            "mobile": "",
            "page": "1",
            "limit": "1",
            "ai_partner": "inh-suny-bot",
        },
        "body_format": "json",
        "custom_body": "",
        "schema": {},
    },
    {
        "name": "FetchCategorySchema",
        "description": (
            "Call this when the buyer confirms they want a DIFFERENT product than what they originally searched for. "
            "Fetches the new qualification question schema for the new product category. "
            "Pass srchterm as a short English product name (e.g. 'AC', 'washing machine', 'sofa')."
        ),
        "url": f"{MIS_API_BASE}/leads/ai-lead-qualify/search",
        "method": "GET",
        "headers": {},
        "query_params": {"lead_id": "", "search_term": ""},
        "body_format": "json",
        "custom_body": "",
        "schema": {
            "type": "object",
            "properties": {
                "srchterm": {
                    "type": "string",
                    "description": "New product search term in English (e.g. 'AC', 'washing machine')",
                }
            },
            "required": ["srchterm"],
        },
    },
]

# The rich analysis prompt stored in the assistant so it can be edited from the dashboard.
# Uses {transcript} and {muted_transcript} as runtime substitution tokens.
ANALYSIS_PROMPT = """You are a strict call-analysis engine for JustDial's AI outbound qualification calls. Return accurate structured JSON — no guessing, no approximating.

TRANSCRIPT:
{transcript}

{muted_transcript}

Analyse the call and return a JSON object with exactly these keys:
  call_outcome            — one of: Interested, Not Interested, Callback, Wrong Number, No Answer, Short Hangup, Could Not Confirm, Will do it Myself, Already Purchased, Duplicate
  call_outcome_description — 1-2 sentence explanation of why this outcome was chosen
  call_summary            — 2-3 sentence factual summary of what happened in the call
  product_confirmed       — true/false: did the buyer confirm they still need the product?
  qna                     — list of {question, answer} objects for each qualification question answered
  is_business             — true/false: is the buyer a business/commercial buyer?
  product_change          — string or null: if buyer changed product mid-call, the new product name; else null
  lead_intent_score       — integer 1-5 (5 = very high intent)
  urgency_flag            — true/false: did the buyer express urgency or immediate need?

CLASSIFICATION RULES:
- Interested: buyer confirmed product need AND answered ≥1 qualification question with a concrete answer
- Not Interested: explicit, final rejection of the product requirement
- Callback: buyer asked to be called back at a specific time
- Short Hangup: call ended in <15 seconds with no meaningful engagement
- Could Not Confirm: clear technical/situational reason confirmation couldn't happen (hold, IVR, handoff)
- Will do it Myself: buyer has the requirement but explicitly said they'll source it themselves
- Already Purchased: buyer already bought the product
- Wrong Number: clearly wrong person / not the one who searched

Return only valid JSON, no markdown, no extra text."""

SEED_FIELDS = {
    "prompt": SYSTEM_PROMPT,
    "language": "hindi",
    "lang_notes": LANG_NOTES,
    "script_rule": SCRIPT_RULE,
    "opening_instruction": OPENING_INSTRUCTION,
    "closing_instruction": CLOSING_INSTRUCTION,
    "timeout_message": TIMEOUT_MESSAGE,
    "initial_message": INITIAL_MESSAGE,
    "call_end_text": CALL_END_TEXT,
    "function_calling": True,
    "functions": FUNCTIONS,
    "filler_message": ["अच्छा,", "हाँ,", "जी,", "तो,", "ठीक है,"],
    "function_filler_message": ["एक moment जी,", "जी, देख रही हूँ,"],
    "inactivity_phrase": INACTIVITY_PHRASE,
    "inactivity_end_phrase": INACTIVITY_END_PHRASE,
    "inactivity_first_rescue_secs": 4.0,
    "inactivity_first_nudge_gap_secs": 4.0,
    "inactivity_nudge_secs": 10.0,
    "inactivity_close_secs": 5.0,
    "analysis_prompt": ANALYSIS_PROMPT,
    # API URLs (stored for bot-config & dashboard display)
    "mis_api_base": MIS_API_BASE,
    "callback_api_url": CALLBACK_API_URL,
    "category_change_api": f"{MIS_API_BASE}/leads/ai-lead-qualify/search",
    # VAD / tuning
    "temperature": 0.7,
    "gemini_start_sensitivity": "START_SENSITIVITY_HIGH",
    "gemini_end_sensitivity": "END_SENSITIVITY_LOW",
    "gemini_silence_duration_ms": 1500,
    "gemini_prefix_padding_ms": 200,
    "max_call_duration": 300,
    "sarvam_min_rms": 600,
    "sarvam_min_speech_ms": 500,
    "sarvam_min_speech_ms_singleword": 800,
    "sarvam_silero_threshold": 0.5,
    "sarvam_silero_min_speech_ms": 120,
    "gemini_silero_fallback_speech_ms": 150,
    "post_speech_hold_ms": 300,
}

# Default assistant_id — the one baked into _HARDCODED_BOT_CONFIG
DEFAULT_ASSISTANT_ID = "e8c0fd31-2d60-4531-a029-2047b17988c4"


async def seed(assistant_id: str | None = None) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(MONGODB_URL)
    col = client["no_code_platform"]["assistants"]

    # Determine which assistants to seed
    if assistant_id:
        targets = [assistant_id]
    else:
        # Seed ALL assistants in the org
        cursor = col.find({}, {"assistant_id": 1})
        docs = await cursor.to_list(length=500)
        targets = [d["assistant_id"] for d in docs]
        if not targets:
            # Fallback to the hardcoded default
            targets = [DEFAULT_ASSISTANT_ID]

    print(f"[Seed] Targeting {len(targets)} assistant(s): {targets}")

    for aid in targets:
        doc = await col.find_one({"assistant_id": aid})
        if doc is None:
            print(f"[Seed] ⚠️  assistant_id={aid!r} not found — skipping")
            continue

        # Only overwrite fields that are currently empty/missing.
        # This makes the seeder safe to run repeatedly.
        update = {}
        for field, value in SEED_FIELDS.items():
            existing = doc.get(field)
            is_empty = (
                existing is None
                or existing == ""
                or existing == []
                or existing == {}
                or existing == False and field not in ("call_recording", "barge_in", "voice_activity_detection", "noise_suppression")
            )
            if is_empty:
                update[field] = value

        if not update:
            print(f"[Seed] ✅ {aid} — all fields already populated, nothing to update")
            continue

        result = await col.update_one(
            {"assistant_id": aid},
            {"$set": update},
        )
        print(
            f"[Seed] ✅ {aid} — updated {len(update)} field(s): {', '.join(sorted(update))}"
            f" (matched={result.matched_count}, modified={result.modified_count})"
        )

    client.close()
    print("[Seed] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed bot config into assistant Mongo docs")
    parser.add_argument(
        "--assistant-id",
        default=None,
        help="Specific assistant UUID to seed (default: all assistants in DB)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even non-empty fields",
    )
    args = parser.parse_args()

    if args.force:
        # Override is_empty check — overwrite everything
        print("[Seed] --force: will overwrite ALL fields regardless of existing values")

        async def seed_force(assistant_id: str | None = None):
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(MONGODB_URL)
            col = client["no_code_platform"]["assistants"]
            if assistant_id:
                targets = [assistant_id]
            else:
                cursor = col.find({}, {"assistant_id": 1})
                docs = await cursor.to_list(length=500)
                targets = [d["assistant_id"] for d in docs] or [DEFAULT_ASSISTANT_ID]
            print(f"[Seed] Force-targeting {len(targets)} assistant(s): {targets}")
            for aid in targets:
                doc = await col.find_one({"assistant_id": aid})
                if doc is None:
                    print(f"[Seed] ⚠️  {aid} not found")
                    continue
                result = await col.update_one({"assistant_id": aid}, {"$set": SEED_FIELDS})
                print(f"[Seed] ✅ {aid} — force-updated {len(SEED_FIELDS)} fields (modified={result.modified_count})")
            client.close()
            print("[Seed] Done.")

        asyncio.run(seed_force(args.assistant_id))
    else:
        asyncio.run(seed(args.assistant_id))
