"""Canonical language table — the `LANG_CONFIGS` that `models.py`'s legacy
`Assistant.language` column comment has promised since day one ("key into
LANG_CONFIGS") but that never actually existed until now.

Single source of truth for every language-aware surface in the dashboard and
at call time: the multilingual toggle's allowed set, the Sarvam TTS/STT
language code, whether the script is Devanagari (gates the IndicF5
transliteration hint), and the style-notes block appended to the system
prompt for that language.

This module is backend-only by design — the bot runtime
(voicebot_nodcode_platform) is a separate deployable with its own venv and
does not import backend code (see how TTS voice resolution works: bot.py
never imports voice_catalog.py either — it receives the already-resolved
tts_provider/tts_voice strings over the wire via BotConfig/WorkflowBotConfig).
Language resolution follows the same pattern: this module resolves everything
server-side, and the *entire* catalog (small — 12 entries) is embedded in
BotConfig/WorkflowBotConfig as `language_catalog` so the bot can pick the
right entry for whatever language a given call actually resolves to
(test-call dropdown / MIS meta.language / bot default — decided bot-side,
after this config has already been fetched).
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# The Hinglish style guide below is unchanged from voicebot_nodcode_platform/
# bot.py's HINDI_LANG_CONFIG["lang_notes"] — it's tuned from real call
# behaviour, not rewritten here. Bot-side, this is what the bot's
# HINDI_LANG_CONFIG constant is being replaced by (see bot.py build_system_prompt).
# ---------------------------------------------------------------------------
_HINGLISH_NOTES = (
    "LANGUAGE NOTES — HINDI\n\n"
    "INPUT: The buyer typically speaks Hindi, Hinglish, or Indian-accented English. If audio is unclear and no explicit language-switch has happened, assume Hindi. If the buyer clearly speaks in English or explicitly requests a language change, honour it — refer to LANGUAGE SWITCHING rules above.\n\n"
    "STYLE: Natural spoken Hinglish — how a real person talks on a call. Conversational, warm, never formal or literary.\n"
    "  Good: 'हाँ जी', 'अच्छा', 'ठीक है', 'samajh gaya', 'okay jee'\n"
    "  Avoid: 'आपकी बात सुनकर खुशी हुई', 'मैं आपकी सहायता के लिए यहाँ हूँ'\n\n"
    "FILLERS — STRICT RULE:\n"
    "You MAY start a response with a filler word (अच्छा, हाँ, जी, तो, ठीक है) BUT you MUST continue immediately into your answer in the SAME sentence — NEVER end your turn on a filler alone.\n"
    "✓ CORRECT:  'जी, कितनी quantity चाहिए?'\n"
    "✗ WRONG:    'जी.' [stop] ... [pause] ... 'कितनी quantity चाहिए?'\n"
    "The filler and the question must be ONE continuous utterance with no pause between them. Vary fillers; don't start every response with 'अच्छा'.\n\n"
    "NUMBERS + UNITS (tonnage, weight, quantity, etc.) — HARD RULE: When a number is followed by a physical unit (ton, kg, litre, HP, etc.), ALWAYS say it as a natural Hindi/Hinglish number word — "
    "NEVER as English digits transliterated into Devanagari (never 'वन टन', 'टू टन', 'वन पॉइंट फाइव टन').\n"
    "  1 ton → 'ek ton'   2 ton → 'do ton'   3 ton → 'teen ton'   4 ton → 'char ton'\n"
    "  1.5 ton → 'dedh ton' (डेढ़ ton)   2.5 ton → 'dhai ton' (ढाई ton)   3.5 ton → 'saade teen ton'   4.5 ton → 'saade char ton'\n"
    "  This pattern (ek/do/teen... and dedh/dhai/saade-X) applies to EVERY quantity+unit pair, not just tonnage.\n\n"
    "NUMBERS — no unit — HARD RULE: Always say a number as a whole number, never digit-by-digit (Hindi 'shunya' for zero sounds broken when repeated). "
    "If a number must be read digit-by-digit (e.g. a code like a grade number), spell the digits out in English words, never in Hindi — "
    "e.g. 1100 → 'one one zero zero', 3003 → 'three zero zero three', 5052 → 'five zero five two'.\n\n"
    "DECIMALS — no unit — HARD RULE: Never say 'दशमलव' (Hindi for decimal point) when reading a plain decimal number aloud (one with no unit attached, e.g. a score or rating). "
    "Always read these the English way instead — e.g. 9.3 → 'nine point three', 3.4 → 'three point four'. "
    "This does NOT apply to quantity+unit numbers (ton, kg, litre, etc.) — those follow the NUMBERS + UNITS rule above instead.\n\n"
    "NEVER use these overly formal words:\n"
    "शयनकक्ष, बैठक कक्ष, कार्यालय, स्थापित, आवश्यकता, पर्याप्त, उपयुक्त, उचित, सूचित, प्राप्त, विवरण, अनुसार, सुविधाजनक\n\n"
    "RELIGIOUS / CULTURAL GREETINGS — STRICT RULE:\n"
    "Phrases like 'जय जय गुरुदेव', 'जय श्री राम', 'जय माता दी', 'राधे राधे', 'jai gurudev', 'jai shri ram' "
    "are regional phone-answering greetings — NOT expressions of disinterest or goodbye. "
    "When the buyer says any such phrase, acknowledge warmly with a short 'जी जी' or 'जी, बिल्कुल' "
    "and IMMEDIATELY continue the product qualification. NEVER close the call or say 'कोई बात नहीं' in response to these."
)

# NOTE: "hindi" intentionally reuses _HINGLISH_NOTES verbatim rather than a
# separate "pure Hindi, no English mixing" style. Before this module existed,
# build_system_prompt() ignored the stored `language` field entirely and
# always applied this exact Hinglish style guide (via the old
# HINDI_LANG_CONFIG constant) — for every bot, regardless of whether its
# stored value was "hindi" or "hinglish" (both exist in the DB; the workflow
# bot Settings dropdown has offered a literal "Hinglish" option since before
# this feature). Giving "hindi" a distinct, stricter no-English-mixing style
# now would silently change every existing bot's speech the moment this ships
# — a real regression, not a language addition. If a genuinely separate
# "pure Hindi" mode is wanted later, give it its own new slug instead of
# repurposing "hindi".


def _generic_notes(name: str) -> str:
    """Short, language-agnostic style block for languages that don't have a
    hand-tuned guide yet. The heavy lifting — actually producing correct,
    idiomatic {name} — is the LLM's job via the TARGET LANGUAGE directive
    (see build_system_prompt); this just covers the handful of rules that
    matter for every Indic language on a phone call.
    """
    return (
        f"LANGUAGE NOTES — {name.upper()}\n\n"
        f"Speak natural, conversational spoken {name} — how a real person talks on a phone call, "
        "never literary, textbook, or overly formal.\n\n"
        "NUMBERS: Say numbers as natural spoken number words in this language, not digit-by-digit, "
        "except for codes/IDs which should be read digit-by-digit using English digit names. Read "
        "plain decimals (no unit attached) the English way — e.g. 9.3 → 'nine point three'.\n\n"
        "CULTURAL GREETINGS: Regional phone-answering greetings and religious phrases are normal "
        "openers, not expressions of disinterest — acknowledge warmly and continue the conversation.\n\n"
        "Product names, brand names, and English loanwords that a caller would naturally say in "
        "English should stay in English/Latin script even mid-sentence, exactly as a bilingual "
        "speaker would say them."
    )


# ---------------------------------------------------------------------------
# LANG_CONFIGS — one entry per selectable language.
#   name        — display name used in the LLM directive and dashboard
#   sarvam      — Sarvam bulbul:v3 / saaras:v3 language code (both TTS + STT
#                 use the same *-IN codes; see pipecat's sarvam service maps)
#   devanagari  — True only for hinglish/hindi. Gates the IndicF5
#                 transliterate-to-Devanagari hint — that hint is wrong (and
#                 harmful) for any other script.
#   notes       — appended to the system prompt as the language's style guide
# ---------------------------------------------------------------------------
LANG_CONFIGS: Dict[str, Dict[str, Any]] = {
    "hinglish": {"name": "Hinglish", "sarvam": "hi-IN", "devanagari": True, "notes": _HINGLISH_NOTES},
    # Same notes as "hinglish" on purpose — see the comment above _HINGLISH_NOTES.
    "hindi": {"name": "Hindi", "sarvam": "hi-IN", "devanagari": True, "notes": _HINGLISH_NOTES},
    "english": {"name": "English", "sarvam": "en-IN", "devanagari": False, "notes": _generic_notes("English")},
    "bengali": {"name": "Bengali", "sarvam": "bn-IN", "devanagari": False, "notes": _generic_notes("Bengali")},
    "gujarati": {"name": "Gujarati", "sarvam": "gu-IN", "devanagari": False, "notes": _generic_notes("Gujarati")},
    "kannada": {"name": "Kannada", "sarvam": "kn-IN", "devanagari": False, "notes": _generic_notes("Kannada")},
    "malayalam": {"name": "Malayalam", "sarvam": "ml-IN", "devanagari": False, "notes": _generic_notes("Malayalam")},
    "marathi": {"name": "Marathi", "sarvam": "mr-IN", "devanagari": False, "notes": _generic_notes("Marathi")},
    "odia": {"name": "Odia", "sarvam": "od-IN", "devanagari": False, "notes": _generic_notes("Odia")},
    "punjabi": {"name": "Punjabi", "sarvam": "pa-IN", "devanagari": False, "notes": _generic_notes("Punjabi")},
    "tamil": {"name": "Tamil", "sarvam": "ta-IN", "devanagari": False, "notes": _generic_notes("Tamil")},
    "telugu": {"name": "Telugu", "sarvam": "te-IN", "devanagari": False, "notes": _generic_notes("Telugu")},
}

# Languages available regardless of the multilingual_enabled toggle — today's
# reality (hi/en/hinglish already worked, just weren't actually honoured by
# the bot runtime — see build_system_prompt). Toggling multilingual_enabled ON
# unlocks the other 9 Sarvam-covered Indic languages.
BASE_LANGUAGES = ("hinglish", "hindi", "english")

# MIS's lead_record.meta.language is a bare ISO-639-1 code (observed: "en").
# Maps that to our internal language slugs; unmapped/unknown codes are
# ignored by resolve_call_language (falls through to the bot's own default).
MIS_LANG_MAP: Dict[str, str] = {
    "hi": "hindi",
    "en": "english",
    "bn": "bengali",
    "gu": "gujarati",
    "kn": "kannada",
    "ml": "malayalam",
    "mr": "marathi",
    "or": "odia",
    "pa": "punjabi",
    "ta": "tamil",
    "te": "telugu",
}

DEFAULT_LANGUAGE = "hinglish"


def is_valid_language(lang: str | None) -> bool:
    return bool(lang) and lang in LANG_CONFIGS


def allowed_languages(multilingual_enabled: bool) -> tuple[str, ...]:
    return tuple(LANG_CONFIGS.keys()) if multilingual_enabled else BASE_LANGUAGES


def language_catalog_for_bot(multilingual_enabled: bool) -> Dict[str, Dict[str, Any]]:
    """The catalog embedded in BotConfig/WorkflowBotConfig — every language the
    bot is allowed to resolve to for this bot, keyed by slug. Kept small
    (12 entries max) since it's fetched at the start of every call.
    """
    keys = allowed_languages(multilingual_enabled)
    return {k: LANG_CONFIGS[k] for k in keys}
