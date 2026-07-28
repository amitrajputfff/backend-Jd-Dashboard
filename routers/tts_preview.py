"""TTS voice preview — synthesizes a short real audio sample for the dashboard's
"Test Voice" button, using the SAME providers the live bots use.

Resolves voice_id -> provider/model/speaker via voice_catalog.resolve_voice()
(the identical resolver bot.py's get_bot_config uses), then calls:
 - "sarvam" -> Sarvam's HTTP TTS API directly (POST /text-to-speech), same
   request shape as pipecat.services.sarvam.tts.SarvamHttpTTSService.run_tts.
 - "justdial" -> our self-hosted IndicF5 WebSocket server, same wire protocol
   as voicebot_nodcode_platform/pipecat_indic5_tts.py.

Both paths return a self-contained WAV byte blob so the browser can play it
directly with no client-side decoding.
"""

import base64
import io
import json
import logging
import os
import wave

import aiohttp
import websockets
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

try:
    from ..voice_catalog import resolve_voice
    from ..languages import LANG_CONFIGS
except ImportError:
    from voice_catalog import resolve_voice
    from languages import LANG_CONFIGS

log = logging.getLogger(__name__)
router = APIRouter()

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai")
INDIC_TTS_WS_URL = os.environ.get("INDIC_TTS_WS_URL", "ws://10.10.0.14:8404/ws")

_DEFAULT_PREVIEW_TEXT = "नमस्ते जी, मैं Justdial से बात कर रही हूँ। यह आपकी आवाज़ का एक नमूना है।"

# Per-language fallback sample — feeding the Hindi default text above through
# a non-Hindi target_language_code would have Sarvam try to render Devanagari
# script in another language's phonetics, which comes out garbled. Only
# covers languages without a script overlap with Hindi; English/Hindi/Hinglish
# use _DEFAULT_PREVIEW_TEXT as before.
_PREVIEW_TEXT_BY_LANGUAGE: dict[str, str] = {
    "bengali": "নমস্কার, আমি জাস্টডায়াল থেকে বলছি। এটি আপনার কণ্ঠস্বরের একটি নমুনা।",
    "gujarati": "નમસ્તે, હું જસ્ટડાયલ તરફથી બોલી રહી છું. આ તમારા અવાજનો એક નમૂનો છે.",
    "kannada": "ನಮಸ್ಕಾರ, ನಾನು ಜಸ್ಟ್‌ಡಯಲ್‌ನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ. ಇದು ನಿಮ್ಮ ಧ್ವನಿಯ ಒಂದು ಮಾದರಿ.",
    "malayalam": "നമസ്കാരം, ഞാൻ ജസ്റ്റ്ഡയലിൽ നിന്ന് സംസാരിക്കുന്നു. ഇത് നിങ്ങളുടെ ശബ്ദത്തിന്റെ ഒരു സാമ്പിളാണ്.",
    "marathi": "नमस्कार, मी जस्टडायलकडून बोलत आहे. हा तुमच्या आवाजाचा एक नमुना आहे.",
    "odia": "ନମସ୍କାର, ମୁଁ ଜଷ୍ଟଡାଏଲରୁ କହୁଛି। ଏହା ଆପଣଙ୍କ ସ୍ୱରର ଏକ ନମୁନା।",
    "punjabi": "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਜਸਟਡਾਇਲ ਤੋਂ ਬੋਲ ਰਹੀ ਹਾਂ। ਇਹ ਤੁਹਾਡੀ ਆਵਾਜ਼ ਦਾ ਇੱਕ ਨਮੂਨਾ ਹੈ।",
    "tamil": "வணக்கம், நான் ஜஸ்ட்டையல் இருந்து பேசுகிறேன். இது உங்கள் குரலின் ஒரு மாதிரி.",
    "telugu": "నమస్కారం, నేను జస్ట్‌డయల్ నుండి మాట్లాడుతున్నాను. ఇది మీ వాయిస్ యొక్క నమూనా.",
}


class TTSPreviewRequest(BaseModel):
    voice_id: int
    text: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    # Language slug (e.g. "tamil") — same values as backend/languages.py's
    # LANG_CONFIGS. Only affects the Sarvam path (IndicF5 voices are
    # Devanagari-only regardless, so previewing one always speaks Hindi script).
    # None/unknown falls back to hi-IN, today's only preview language.
    language: str | None = None


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # s16le
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def _synthesize_sarvam(text: str, speaker: str, speed: float, sarvam_lang_code: str = "hi-IN") -> bytes:
    if not SARVAM_API_KEY:
        raise HTTPException(status_code=503, detail="SARVAM_API_KEY is not configured on this server.")

    payload = {
        "text": text,
        "target_language_code": sarvam_lang_code,
        "speaker": speaker,
        "sample_rate": 24000,
        "enable_preprocessing": True,
        "model": "bulbul:v3",
        "pace": max(0.5, min(2.0, speed)),
    }
    headers = {"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{SARVAM_BASE_URL}/text-to-speech", json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                log.warning("Sarvam TTS preview failed (%s): %s", resp.status, error_text)
                raise HTTPException(status_code=502, detail=f"Sarvam TTS error: {error_text}")
            data = await resp.json()

    audios = data.get("audios") or []
    if not audios:
        raise HTTPException(status_code=502, detail="Sarvam TTS returned no audio")

    # Sarvam returns a base64-encoded WAV file already — playable as-is.
    return base64.b64decode(audios[0])


async def _synthesize_indicf5(text: str, speaker: str, speed: float) -> bytes:
    sample_rate = 24000
    request = {
        "text": text,
        "nfe_step": 32,
        "style": "auto",
        "transliterate": True,
        "speed": max(0.5, min(2.0, speed)),
        "sample_rate": sample_rate,
        "speaker": speaker,
    }

    pcm_chunks: list[bytes] = []
    try:
        async with websockets.connect(INDIC_TTS_WS_URL, max_size=None, open_timeout=10) as ws:
            await ws.send(json.dumps(request))
            while True:
                msg = await ws.recv()
                if isinstance(msg, (bytes, bytearray)):
                    pcm_chunks.append(bytes(msg))
                else:
                    event = json.loads(msg).get("event")
                    if event == "end":
                        break
                    if event == "error":
                        detail = json.loads(msg).get("detail") or "IndicF5 TTS server error"
                        raise HTTPException(status_code=502, detail=detail)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("IndicF5 TTS preview failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"IndicF5 TTS server unreachable: {exc}") from exc

    if not pcm_chunks:
        raise HTTPException(status_code=502, detail="IndicF5 TTS returned no audio (voice may be suppressed)")

    return _pcm_to_wav(b"".join(pcm_chunks), sample_rate)


@router.post("/api/tts/preview")
async def preview_voice(body: TTSPreviewRequest):
    """Synthesize a short real audio sample for the given voice_id. Returns raw WAV bytes."""
    voice = resolve_voice(body.voice_id)
    lang_entry = LANG_CONFIGS.get(body.language or "", {})
    sarvam_lang_code = lang_entry.get("sarvam", "hi-IN")
    default_text = _PREVIEW_TEXT_BY_LANGUAGE.get(body.language or "", _DEFAULT_PREVIEW_TEXT)
    text = (body.text or default_text).strip()[:300]

    if voice["provider"] == "sarvam":
        wav_bytes = await _synthesize_sarvam(text, voice["speaker"], body.speed, sarvam_lang_code)
    else:
        # IndicF5 only ever speaks Devanagari script — language selection doesn't apply.
        wav_bytes = await _synthesize_indicf5(text, voice["speaker"], body.speed)

    return Response(content=wav_bytes, media_type="audio/wav")
