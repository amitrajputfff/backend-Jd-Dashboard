"""Pydantic schemas — shapes match exactly what JD-Dashboard frontend expects."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-types
# ---------------------------------------------------------------------------

class AssistantFunction(BaseModel):
    url: str = ""
    name: str = ""
    method: str = "POST"
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    headers: Dict[str, Any] = Field(default_factory=dict)
    body_format: str = "json"
    custom_body: str = ""
    description: str = ""
    query_params: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class CreateAssistantRequest(BaseModel):
    organization_id: str
    name: str
    description: Optional[str] = ""
    category: Optional[str] = "Customer Service"
    tags: Optional[List[str]] = Field(default_factory=list)
    status: Optional[str] = "Draft"
    prompt: Optional[str] = ""
    initial_message: Optional[str] = ""
    call_end_text: Optional[str] = ""
    function_calling: Optional[bool] = False
    functions: Optional[List[Any]] = Field(default_factory=list)

    # Bot API URLs
    mis_api_base: Optional[str] = "http://192.168.14.101:3006"
    callback_api_url: Optional[str] = (
        "http://192.168.14.101:3006/leads/ai-lead-qualify/callback"
    )
    category_change_api: Optional[str] = (
        "http://192.168.20.105:1080/services/abd/abd_beta.php"
    )

    # Prompt config
    script_rule: Optional[str] = ""
    opening_instruction: Optional[str] = ""
    closing_instruction: Optional[str] = ""
    timeout_message: Optional[str] = ""

    # Bot behaviour settings
    language: Optional[str] = "hindi"
    temperature: Optional[float] = 0.4
    gemini_start_sensitivity: Optional[str] = "START_SENSITIVITY_LOW"
    gemini_end_sensitivity: Optional[str] = "END_SENSITIVITY_HIGH"
    gemini_silence_duration_ms: Optional[int] = 800
    gemini_prefix_padding_ms: Optional[int] = 100
    max_call_duration: Optional[int] = 300
    filler_message: Optional[List[str]] = Field(default_factory=list)
    function_filler_message: Optional[List[str]] = Field(default_factory=list)

    # Sarvam STT / VAD tuning
    sarvam_min_rms: Optional[int] = 600
    sarvam_min_speech_ms: Optional[int] = 500
    sarvam_min_speech_ms_singleword: Optional[int] = 800
    sarvam_silero_threshold: Optional[float] = 0.5
    sarvam_silero_min_speech_ms: Optional[int] = 120
    gemini_silero_fallback_speech_ms: Optional[int] = 150
    post_speech_hold_ms: Optional[int] = 300

    # Inactivity timers
    inactivity_first_rescue_secs: Optional[float] = 4.0
    inactivity_first_nudge_gap_secs: Optional[float] = 4.0
    inactivity_nudge_secs: Optional[float] = 10.0
    inactivity_close_secs: Optional[float] = 5.0

    # Analysis prompt
    analysis_prompt: Optional[str] = ""

    # Inactivity phrases
    inactivity_phrase: Optional[str] = "क्या आप अभी line पर हैं?"
    inactivity_end_phrase: Optional[str] = "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."

    # Language notes (appended to system prompt — tone, style, filler rules)
    lang_notes: Optional[str] = ""

    # Accepted but ignored — AI-create flow extras
    language_id: Optional[int] = None
    stt_model_id: Optional[int] = None
    tts_model_id: Optional[int] = None
    llm_model_id: Optional[int] = None
    voice_id: Optional[int] = None
    generate_description: Optional[bool] = None
    generate_tags: Optional[bool] = None
    generate_config: Optional[bool] = None


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class UpdateAssistantRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    prompt: Optional[str] = None
    initial_message: Optional[str] = None
    call_end_text: Optional[str] = None
    function_calling: Optional[bool] = None
    functions: Optional[List[Any]] = None
    mis_api_base: Optional[str] = None
    callback_api_url: Optional[str] = None
    category_change_api: Optional[str] = None
    script_rule: Optional[str] = None
    opening_instruction: Optional[str] = None
    closing_instruction: Optional[str] = None
    timeout_message: Optional[str] = None
    language: Optional[str] = None
    temperature: Optional[float] = None
    gemini_start_sensitivity: Optional[str] = None
    gemini_end_sensitivity: Optional[str] = None
    gemini_silence_duration_ms: Optional[int] = None
    gemini_prefix_padding_ms: Optional[int] = None
    max_call_duration: Optional[int] = None
    filler_message: Optional[List[str]] = None
    function_filler_message: Optional[List[str]] = None

    # Sarvam STT / VAD tuning
    sarvam_min_rms: Optional[int] = None
    sarvam_min_speech_ms: Optional[int] = None
    sarvam_min_speech_ms_singleword: Optional[int] = None
    sarvam_silero_threshold: Optional[float] = None
    sarvam_silero_min_speech_ms: Optional[int] = None
    gemini_silero_fallback_speech_ms: Optional[int] = None
    post_speech_hold_ms: Optional[int] = None

    # Inactivity timers
    inactivity_first_rescue_secs: Optional[float] = None
    inactivity_first_nudge_gap_secs: Optional[float] = None
    inactivity_nudge_secs: Optional[float] = None
    inactivity_close_secs: Optional[float] = None

    # Analysis prompt
    analysis_prompt: Optional[str] = None

    # Inactivity phrases
    inactivity_phrase: Optional[str] = None
    inactivity_end_phrase: Optional[str] = None

    # Language notes
    lang_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Response — matches AssistantDetails TypeScript interface
# ---------------------------------------------------------------------------

class AssistantResponse(BaseModel):
    # Core
    id: int
    assistant_id: str
    organization_id: str
    name: str
    description: str
    category: str
    tags: List[str]
    status: str

    # Prompt / conversation
    prompt: str
    initial_message: str
    call_end_text: str

    # Bot API URLs
    mis_api_base: str
    callback_api_url: str
    category_change_api: str

    # Prompt config
    script_rule: str
    opening_instruction: str
    closing_instruction: str
    timeout_message: str

    # Function calling
    function_calling: bool
    functions: List[Any]

    # Soft delete / active
    is_deleted: bool
    deleted_until: Optional[str]
    is_active: bool

    # Timestamps
    created_at: str
    updated_at: str

    # Metrics
    calls_today: int

    # Bot behaviour settings (stored in DB, used by bots at call start)
    language: str
    temperature: float
    gemini_start_sensitivity: str
    gemini_end_sensitivity: str
    gemini_silence_duration_ms: int
    gemini_prefix_padding_ms: int
    max_call_duration: int
    filler_message: List[str]
    function_filler_message: List[str]

    # Sarvam STT / VAD tuning
    sarvam_min_rms: int
    sarvam_min_speech_ms: int
    sarvam_min_speech_ms_singleword: int
    sarvam_silero_threshold: float
    sarvam_silero_min_speech_ms: int
    gemini_silero_fallback_speech_ms: int
    post_speech_hold_ms: int

    # Inactivity timers
    inactivity_first_rescue_secs: float
    inactivity_first_nudge_gap_secs: float
    inactivity_nudge_secs: float
    inactivity_close_secs: float

    # Analysis prompt
    analysis_prompt: str

    # Inactivity phrases
    inactivity_phrase: str
    inactivity_end_phrase: str

    # Language notes
    lang_notes: str

    # Legacy / frontend-compatibility fields (not stored in DB, provided as defaults)
    language_id: int = 11
    stt_model_id: int = 1
    tts_model_id: int = 1
    llm_model_id: int = 1
    voice_id: int = 1
    speech_speed: float = 1.0
    pitch: str = "0%"
    interruption_level: str = "Low"
    cutoff_seconds: int = 5
    ideal_time_seconds: int = 30
    call_recording: bool = False
    barge_in: bool = True
    voice_activity_detection: bool = True
    noise_suppression: bool = True
    silence_timeout: int = 15
    is_transferable: bool = False
    transfer_number: Optional[str] = None
    max_token: int = 250
    memory_enabled: bool = False
    max_memory_retrieval: int = 5
    logo_file_url: Optional[str] = None
    logo_file_type: Optional[str] = None
    logo_file_size: Optional[int] = None
    training_status: str = "trained"
    avg_duration: str = "0:00"
    last_active: str = ""

    model_config = {"from_attributes": True}


class AssistantsListResponse(BaseModel):
    assistants: List[AssistantResponse]
    total: int


# ---------------------------------------------------------------------------
# Bot config — consumed by server.py / bot.py at call start
# ---------------------------------------------------------------------------

class BotConfig(BaseModel):
    assistant_id: str
    organization_id: str
    system_prompt: str
    initial_message: str
    call_end_text: str
    function_calling: bool
    functions: List[Any]
    api_urls: Dict[str, str]          # mis_api_base, callback_api_url, category_change_api
    prompt_config: Dict[str, str]     # script_rule, opening_instruction, closing_instruction, timeout_message
    # Bot behaviour settings
    language: str
    temperature: float
    gemini_start_sensitivity: str
    gemini_end_sensitivity: str
    gemini_silence_duration_ms: int
    gemini_prefix_padding_ms: int
    max_call_duration: int
    filler_message: List[str]
    function_filler_message: List[str]
    # Sarvam STT / VAD tuning
    sarvam_min_rms: int = 600
    sarvam_min_speech_ms: int = 500
    sarvam_min_speech_ms_singleword: int = 800
    sarvam_silero_threshold: float = 0.5
    sarvam_silero_min_speech_ms: int = 120
    gemini_silero_fallback_speech_ms: int = 150
    post_speech_hold_ms: int = 300
    # Inactivity timers
    inactivity_first_rescue_secs: float = 4.0
    inactivity_first_nudge_gap_secs: float = 4.0
    inactivity_nudge_secs: float = 10.0
    inactivity_close_secs: float = 5.0
    # Analysis prompt
    analysis_prompt: str = ""
    # Inactivity phrases
    inactivity_phrase: str = "क्या आप अभी line पर हैं?"
    inactivity_end_phrase: str = "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."
    # Language notes
    lang_notes: str = ""
