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
except ImportError:
    from voice_catalog import resolve_voice

log = logging.getLogger(__name__)
router = APIRouter()

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai")
INDIC_TTS_WS_URL = os.environ.get("INDIC_TTS_WS_URL", "ws://10.10.0.14:8404/ws")

_DEFAULT_PREVIEW_TEXT = "नमस्ते जी, मैं Justdial से बात कर रही हूँ। यह आपकी आवाज़ का एक नमूना है।"


class TTSPreviewRequest(BaseModel):
    voice_id: int
    text: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # s16le
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def _synthesize_sarvam(text: str, speaker: str, speed: float) -> bytes:
    if not SARVAM_API_KEY:
        raise HTTPException(status_code=503, detail="SARVAM_API_KEY is not configured on this server.")

    payload = {
        "text": text,
        "target_language_code": "hi-IN",
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
        "nfe_step": 16,
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
    text = (body.text or _DEFAULT_PREVIEW_TEXT).strip()[:300]

    if voice["provider"] == "sarvam":
        wav_bytes = await _synthesize_sarvam(text, voice["speaker"], body.speed)
    else:
        wav_bytes = await _synthesize_indicf5(text, voice["speaker"], body.speed)

    return Response(content=wav_bytes, media_type="audio/wav")
