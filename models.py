import uuid
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.sql import func

try:
    from .database import Base
except ImportError:
    from database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Assistant(Base):
    __tablename__ = "assistants"

    # Primary key — integer for internal use
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Public identifier exposed to the frontend and bot
    assistant_id = Column(String(36), unique=True, nullable=False, default=_new_uuid, index=True)

    # Org
    organization_id = Column(String(100), nullable=False, index=True)

    # Basic info
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    category = Column(String(100), default="Customer Service")
    tags = Column(JSON, default=list)           # list[str]
    status = Column(String(50), default="Draft")  # "Active" | "Draft"

    # Prompt & conversation flow
    prompt = Column(Text, default="")           # system prompt
    initial_message = Column(Text, default="")  # greeting
    call_end_text = Column(Text, default="")

    # API URLs used by the bot (editable per-agent)
    mis_api_base = Column(String(500), default="http://192.168.8.67:8000")
    callback_api_url = Column(
        String(500),
        default="http://192.168.8.67:8000/leads/ai-lead-qualify/callback",
    )
    category_change_api = Column(
        String(500),
        default="http://192.168.20.105:1080/services/abd/abd_beta.php",
    )

    # Prompt config (replaces prompt_config.json)
    script_rule = Column(Text, default="")
    opening_instruction = Column(Text, default="")
    closing_instruction = Column(Text, default="")
    timeout_message = Column(Text, default="")

    # Function calling
    function_calling = Column(Boolean, default=False)
    functions = Column(JSON, default=list)      # list[AssistantFunction]

    # Soft delete
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_until = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Bot behaviour settings (persisted, used at call start via /bot-config)
    language = Column(String(50), default="hindi")       # key into LANG_CONFIGS
    temperature = Column(Float, default=0.4)
    gemini_start_sensitivity = Column(String(50), default="START_SENSITIVITY_LOW")
    gemini_end_sensitivity = Column(String(50), default="END_SENSITIVITY_HIGH")
    gemini_silence_duration_ms = Column(Integer, default=800)
    gemini_prefix_padding_ms = Column(Integer, default=100)
    max_call_duration = Column(Integer, default=300)     # seconds (5 min default)
    filler_message = Column(JSON, default=list)
    function_filler_message = Column(JSON, default=list)

    # Sarvam STT / VAD tuning
    sarvam_min_rms = Column(Integer, default=600)
    sarvam_min_speech_ms = Column(Integer, default=500)
    sarvam_min_speech_ms_singleword = Column(Integer, default=800)
    sarvam_silero_threshold = Column(Float, default=0.5)
    sarvam_silero_min_speech_ms = Column(Integer, default=120)
    gemini_silero_fallback_speech_ms = Column(Integer, default=150)
    post_speech_hold_ms = Column(Integer, default=300)

    # Inactivity / silence-handling timers (seconds)
    inactivity_first_rescue_secs = Column(Float, default=4.0)
    inactivity_first_nudge_gap_secs = Column(Float, default=4.0)
    inactivity_nudge_secs = Column(Float, default=10.0)
    inactivity_close_secs = Column(Float, default=5.0)

    # Analysis prompt — used by callback_worker to analyse call transcripts
    analysis_prompt = Column(Text, default="")

    # Lightweight metrics (incremented by the bot on callback)
    calls_today = Column(Integer, default=0)
