"""Canonical TTS voice catalog — mirrors JD-Dashboard/src/lib/mock-data/providers.ts.

Resolves a stored numeric `voice_id` (persisted on the assistant doc) into the
provider + model + speaker string that voicebot_nodcode_platform's bots need to
build the right TTS service.

IMPORTANT — name collision: "simran" exists as a DISTINCT voice under BOTH
providers (our own fine-tuned IndicF5 vs Sarvam's bulbul:v3 speaker of the same
name). They are never the same audio. Always resolve by voice_id, never by
speaker name alone.

Sarvam speaker roster — CONFIRMED against pipecat.services.sarvam.tts
(SarvamTTSSpeakerV3, pipecat 1.3.0, installed in voicebot_nodcode_platform/.venv):
bulbul:v3 supports EXACTLY this 25-speaker set. Speakers like "anushka",
"manisha", "vidya", "arya", "abhilash", "karun", "hitesh" are bulbul:v2-only —
NOT valid for v3 — and must not be used with model="bulbul:v3" (they were
listed here in an earlier draft before the pipecat SDK was checked; corrected).
The codebase standardizes on bulbul:v3 (bot_pipeline.py, bot_new.py), so this
catalog exposes the full bulbul:v3 roster.

voice_id numbering: 10-19 = "justdial" (own, IndicF5), 20-51 = "sarvam" (bulbul:v3).
"""

from __future__ import annotations

from typing import TypedDict


class VoiceEntry(TypedDict):
    provider: str          # "justdial" | "sarvam" — matches BotConfig.tts_provider
    model: str             # "indic-f5" | "bulbul:v3"
    speaker: str           # speaker string sent to the TTS engine
    verified: bool         # confirmed against the provider's real speaker roster


DEFAULT_VOICE_ID = 12  # Own IndicF5 "simran" — matches today's hardcoded default

VOICE_CATALOG: dict[int, VoiceEntry] = {
    # Own — IndicF5 (fine-tuned)
    10: {"provider": "justdial", "model": "indic-f5", "speaker": "anushka", "verified": True},
    11: {"provider": "justdial", "model": "indic-f5", "speaker": "niharika", "verified": True},
    12: {"provider": "justdial", "model": "indic-f5", "speaker": "simran", "verified": True},
    # Sarvam — bulbul:v3 (full SarvamTTSSpeakerV3 roster; all confirmed valid)
    20: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "simran", "verified": True},
    28: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "aditya", "verified": True},
    29: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "ritu", "verified": True},
    30: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "priya", "verified": True},
    31: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "neha", "verified": True},
    32: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "rahul", "verified": True},
    33: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "pooja", "verified": True},
    34: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "rohan", "verified": True},
    35: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "kavya", "verified": True},
    36: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "amit", "verified": True},
    37: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "dev", "verified": True},
    38: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "ishita", "verified": True},
    39: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "shreya", "verified": True},
    40: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "ratan", "verified": True},
    41: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "varun", "verified": True},
    42: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "manan", "verified": True},
    43: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "sumit", "verified": True},
    44: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "roopa", "verified": True},
    45: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "kabir", "verified": True},
    46: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "aayan", "verified": True},
    47: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "shubh", "verified": True},
    48: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "ashutosh", "verified": True},
    49: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "advait", "verified": True},
    50: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "amelia", "verified": True},
    51: {"provider": "sarvam", "model": "bulbul:v3", "speaker": "sophia", "verified": True},
}


def resolve_voice(voice_id: int | None) -> VoiceEntry:
    """Resolve a stored voice_id to its provider/model/speaker. Falls back to
    DEFAULT_VOICE_ID for None, missing, or unknown ids so callers always get a
    valid TTS configuration."""
    if voice_id is not None and voice_id in VOICE_CATALOG:
        return VOICE_CATALOG[voice_id]
    return VOICE_CATALOG[DEFAULT_VOICE_ID]
