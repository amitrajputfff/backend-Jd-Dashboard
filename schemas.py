"""Pydantic schemas — shapes match exactly what JD-Dashboard frontend expects."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# Env-driven so a fresh assistant's default API URLs match the environment the
# backend is running in (local dev vs a deployed server) without a code change.
_MIS_API_BASE_DEFAULT = os.getenv("MIS_API_BASE", "http://192.168.8.67:8000")
_CALLBACK_API_URL_DEFAULT = os.getenv(
    "CALLBACK_API_URL", "http://192.168.8.67:8000/leads/ai-lead-qualify/callback"
)
_CATEGORY_CHANGE_API_DEFAULT = os.getenv(
    "CATEGORY_CHANGE_API", "http://192.168.20.105:1080/services/abd/abd_beta.php"
)


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
    mis_api_base: Optional[str] = _MIS_API_BASE_DEFAULT
    callback_api_url: Optional[str] = _CALLBACK_API_URL_DEFAULT
    category_change_api: Optional[str] = _CATEGORY_CHANGE_API_DEFAULT

    # Per-assistant MongoDB override — lets one running bot_dev.py worker
    # persist different assistants' call transcripts to different MongoDB
    # deployments and/or database names (e.g. a dev bot -> dev Mongo /
    # ai_lead_qualify_dev, a live bot -> prod Mongo / ai_lead_qualify).
    # None/empty means "use the worker's own MONGO_URI/MONGO_DB env default".
    mongo_uri: Optional[str] = None
    mongo_db: Optional[str] = None

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

    # Lock flag — locked assistants are live in production and cannot be edited
    is_locked: Optional[bool] = False

    # TTS provider/model/voice — persisted, resolved via voice_catalog.resolve_voice()
    # at call start. voice_id 12 = our own IndicF5 "simran" (current default).
    tts_provider_id: Optional[int] = None
    tts_model_id: Optional[int] = None
    voice_id: Optional[int] = 12

    # How easily a caller can interrupt the bot mid-sentence — a simple named
    # preset (see interruption_presets.py) instead of exposing raw seconds/
    # word-count knobs to PMs. "balanced" matches today's behavior.
    interruption_sensitivity: Optional[str] = "balanced"

    # Whether to mute the caller's mic while the bot speaks its greeting / closing
    # lines. Defaults True — matches the previously-unconditional behavior.
    mute_during_greeting: Optional[bool] = True
    mute_during_closing: Optional[bool] = True

    # Accepted but ignored — AI-create flow extras
    language_id: Optional[int] = None
    stt_model_id: Optional[int] = None
    llm_model_id: Optional[int] = None
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
    mongo_uri: Optional[str] = None
    mongo_db: Optional[str] = None
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

    # Lock flag — only admins should flip this
    is_locked: Optional[bool] = None

    # TTS provider/model/voice
    tts_provider_id: Optional[int] = None
    tts_model_id: Optional[int] = None
    voice_id: Optional[int] = None

    # How easily a caller can interrupt the bot mid-sentence
    interruption_sensitivity: Optional[str] = None

    # Whether to mute the caller's mic while the bot speaks its greeting / closing lines.
    mute_during_greeting: Optional[bool] = None
    mute_during_closing: Optional[bool] = None

    # Present only when the existing doc has is_locked=True — required to
    # unlock it or to change ANY other field while it stays locked (see
    # routers/assistants.py's update_assistant). Never persisted.
    password: Optional[str] = None


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

    # Per-assistant MongoDB override (None = worker's own MONGO_URI/MONGO_DB env defaults)
    mongo_uri: Optional[str] = None
    mongo_db: Optional[str] = None

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

    # Lock — True means live in production; edits and deletes are rejected
    is_locked: bool = False

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

    # STT/LLM are fixed (not selectable) — Sarvam saaras:v3 / Gemini 3.1 Flash Lite,
    # the only entries in MOCK_STT_MODELS/MOCK_LLM_MODELS, so these stay hardcoded.
    language_id: int = 11
    stt_model_id: int = 1
    llm_model_id: int = 1

    # TTS provider/model/voice — real, sourced from the stored doc (see voice_catalog.py)
    tts_provider_id: int = 3
    tts_model_id: int = 1
    voice_id: int = 12
    interruption_sensitivity: str = "balanced"
    mute_during_greeting: bool = True
    mute_during_closing: bool = True
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
    # Symmetric with WorkflowBotConfig.bot_type — lets a bot runtime that
    # doesn't already know which kind of bot it's talking to (e.g. a resolver
    # endpoint trying both collections) dispatch on this field.
    bot_type: str = "assistant"
    assistant_id: str
    organization_id: str
    system_prompt: str
    initial_message: str
    call_end_text: str
    function_calling: bool
    functions: List[Any]
    api_urls: Dict[str, str]          # mis_api_base, callback_api_url, category_change_api
    prompt_config: Dict[str, str]     # script_rule, opening_instruction, closing_instruction, timeout_message
    # Per-assistant MongoDB override — see voicebot_nodcode_platform/bot.py's
    # _get_mongo_collection(). None = worker's own MONGO_URI/MONGO_DB env defaults.
    mongo_uri: Optional[str] = None
    mongo_db: Optional[str] = None
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
    # TTS provider/voice — resolved from voice_id via voice_catalog.resolve_voice().
    # tts_provider: "justdial" (own IndicF5) | "sarvam" (bulbul:v3). tts_voice is the
    # speaker string to pass to that engine.
    tts_provider: str = "justdial"
    tts_voice: str = "simran"
    # How easily a caller can interrupt the bot mid-sentence — a named preset
    # ("patient" | "balanced" | "responsive") resolved into concrete
    # LiveKit/Pipecat parameters at call start (see interruption_presets.py).
    interruption_sensitivity: str = "balanced"
    # Whether to mute the caller's mic while the bot speaks its greeting / closing lines.
    mute_during_greeting: bool = True
    mute_during_closing: bool = True
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


# ===========================================================================
# Workflow Bot schemas
# ===========================================================================

# ---------------------------------------------------------------------------
# Workflow graph — node / edge shapes
# ---------------------------------------------------------------------------

class WorkflowVariableSchema(BaseModel):
    """A single variable to collect at a conversation node."""
    name: str
    description: str
    type: Literal["string", "number", "boolean", "enum"] = "string"
    enum_values: Optional[List[str]] = None
    required: bool = True


class WorkflowNodeData(BaseModel):
    """Generic node.data container; extra fields allowed (ReactFlow native)."""
    kind: Literal["start", "conversation", "condition", "function", "end_call", "global"]
    label: str = ""
    # start
    first_message: Optional[str] = None
    # conversation
    prompt: Optional[str] = None
    variables: Optional[List[WorkflowVariableSchema]] = None
    # function/API call
    function: Optional[Dict[str, Any]] = None
    output_key: Optional[str] = None
    # end_call
    closing_message: Optional[str] = None
    # global
    trigger_description: Optional[str] = None
    action: Optional[Literal["end_call", "transfer", "continue"]] = None
    transfer_number: Optional[str] = None
    resume: Optional[bool] = None

    model_config = {"extra": "allow"}


class WorkflowNodePosition(BaseModel):
    x: float
    y: float


class WorkflowNode(BaseModel):
    id: str
    type: str
    position: WorkflowNodePosition
    data: WorkflowNodeData

    model_config = {"extra": "allow"}


class WorkflowRuleCondition(BaseModel):
    path: str               # variable name or dot-path into api response
    op: Literal["eq", "ne", "gt", "lt", "contains", "exists"]
    value: Any = None


class WorkflowEdgeData(BaseModel):
    # kind is optional — new schema uses transition/branch handles; legacy uses llm/rule
    kind: Optional[Literal["llm", "rule", "transition"]] = None
    # LLM / transition edge
    condition: Optional[str] = None
    key: Optional[str] = None
    # Rule edge (condition nodes)
    rule: Optional[WorkflowRuleCondition] = None
    priority: Optional[int] = 0
    is_fallback: Optional[bool] = False
    label: Optional[str] = None

    model_config = {"extra": "allow"}


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    data: Optional[WorkflowEdgeData] = None

    model_config = {"extra": "allow"}


class WorkflowViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1.0


class Workflow(BaseModel):
    """The full graph blob — ReactFlow-native { nodes, edges, viewport }."""
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    viewport: WorkflowViewport = Field(default_factory=WorkflowViewport)

    @model_validator(mode="after")
    def validate_graph(self) -> "Workflow":
        node_ids = {n.id for n in self.nodes}

        # 1. Exactly one start node
        start_nodes = [n for n in self.nodes if n.data.kind == "start"]
        if len(start_nodes) != 1:
            raise ValueError(f"Workflow must have exactly one start node (found {len(start_nodes)})")

        # 2. All edge endpoints must reference existing nodes
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(f"Edge {edge.id!r}: source {edge.source!r} does not exist")
            if edge.target not in node_ids:
                raise ValueError(f"Edge {edge.id!r}: target {edge.target!r} does not exist")

        # 3. Legacy LLM edge key uniqueness (new schema uses node-level transitions; skip those)
        llm_keys_by_source: Dict[str, set] = {}
        for edge in self.edges:
            if edge.data and edge.data.kind == "llm":
                src = edge.source
                key = edge.data.key or ""
                if key:
                    if src not in llm_keys_by_source:
                        llm_keys_by_source[src] = set()
                    if key in llm_keys_by_source[src]:
                        raise ValueError(f"Edge {edge.id!r}: duplicate LLM edge key {key!r} from node {src!r}")
                    llm_keys_by_source[src].add(key)

        # 4. Function nodes must have a URL in their function config
        for node in self.nodes:
            if node.data.kind == "function":
                fn = node.data.function or {}
                if not fn.get("url"):
                    raise ValueError(f"Node {node.id!r}: function node must have a non-empty URL")

        return self


# ---------------------------------------------------------------------------
# Workflow Bot — Create / Update / Response / Config
# ---------------------------------------------------------------------------

class CreateWorkflowBotRequest(BaseModel):
    organization_id: str
    name: str
    description: Optional[str] = ""
    status: Optional[str] = "Draft"
    global_prompt: Optional[str] = ""
    workflow: Workflow

    # Voice / call settings — same field names as CreateAssistantRequest
    language: Optional[str] = "hindi"
    temperature: Optional[float] = 0.7
    gemini_start_sensitivity: Optional[str] = "START_SENSITIVITY_LOW"
    gemini_end_sensitivity: Optional[str] = "END_SENSITIVITY_HIGH"
    gemini_silence_duration_ms: Optional[int] = 800
    gemini_prefix_padding_ms: Optional[int] = 100
    max_call_duration: Optional[int] = 300
    filler_message: Optional[List[str]] = Field(default_factory=list)
    function_filler_message: Optional[List[str]] = Field(default_factory=list)
    sarvam_min_rms: Optional[int] = 600
    sarvam_min_speech_ms: Optional[int] = 500
    sarvam_min_speech_ms_singleword: Optional[int] = 800
    sarvam_silero_threshold: Optional[float] = 0.5
    sarvam_silero_min_speech_ms: Optional[int] = 120
    gemini_silero_fallback_speech_ms: Optional[int] = 150
    post_speech_hold_ms: Optional[int] = 300
    inactivity_first_rescue_secs: Optional[float] = 4.0
    inactivity_first_nudge_gap_secs: Optional[float] = 4.0
    inactivity_nudge_secs: Optional[float] = 10.0
    inactivity_close_secs: Optional[float] = 5.0
    inactivity_phrase: Optional[str] = "क्या आप अभी line पर हैं?"
    inactivity_end_phrase: Optional[str] = "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."
    lang_notes: Optional[str] = ""
    analysis_prompt: Optional[str] = ""

    # TTS provider/model/voice — same field names/defaults as CreateAssistantRequest,
    # persisted and resolved via voice_catalog.resolve_voice() at call start.
    tts_provider_id: Optional[int] = None
    tts_model_id: Optional[int] = None
    voice_id: Optional[int] = 12

    # How easily a caller can interrupt the bot mid-sentence
    interruption_sensitivity: Optional[str] = "balanced"

    # Whether to mute the caller's mic while the bot speaks its closing line.
    # (No greeting-mute equivalent here — a workflow bot's opening line is the
    # start node's PM-authored first_message, not a canned deterministic phrase.)
    mute_during_closing: Optional[bool] = True

    # Lock flag — same meaning/enforcement as Assistant.is_locked
    is_locked: Optional[bool] = False


class UpdateWorkflowBotRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    global_prompt: Optional[str] = None
    workflow: Optional[Workflow] = None
    language: Optional[str] = None
    temperature: Optional[float] = None
    gemini_start_sensitivity: Optional[str] = None
    gemini_end_sensitivity: Optional[str] = None
    gemini_silence_duration_ms: Optional[int] = None
    gemini_prefix_padding_ms: Optional[int] = None
    max_call_duration: Optional[int] = None
    filler_message: Optional[List[str]] = None
    function_filler_message: Optional[List[str]] = None
    sarvam_min_rms: Optional[int] = None
    sarvam_min_speech_ms: Optional[int] = None
    sarvam_min_speech_ms_singleword: Optional[int] = None
    sarvam_silero_threshold: Optional[float] = None
    sarvam_silero_min_speech_ms: Optional[int] = None
    gemini_silero_fallback_speech_ms: Optional[int] = None
    post_speech_hold_ms: Optional[int] = None
    inactivity_first_rescue_secs: Optional[float] = None
    inactivity_first_nudge_gap_secs: Optional[float] = None
    inactivity_nudge_secs: Optional[float] = None
    inactivity_close_secs: Optional[float] = None
    inactivity_phrase: Optional[str] = None
    inactivity_end_phrase: Optional[str] = None
    lang_notes: Optional[str] = None
    analysis_prompt: Optional[str] = None

    # TTS provider/model/voice
    tts_provider_id: Optional[int] = None
    tts_model_id: Optional[int] = None
    voice_id: Optional[int] = None

    # How easily a caller can interrupt the bot mid-sentence
    interruption_sensitivity: Optional[str] = None

    # Whether to mute the caller's mic while the bot speaks its closing line.
    mute_during_closing: Optional[bool] = None

    # Lock flag — only admins should flip this
    is_locked: Optional[bool] = None

    # Present only when the existing doc has is_locked=True — required to
    # unlock it or to change ANY other field while it stays locked (see
    # routers/workflow_bots.py's update_workflow_bot). Never persisted.
    password: Optional[str] = None


class WorkflowBotResponse(BaseModel):
    id: int
    workflow_bot_id: str
    organization_id: str
    name: str
    description: str
    status: str
    global_prompt: str
    workflow: Dict[str, Any]      # raw graph — ReactFlow JSON
    # Voice / call settings
    language: str
    temperature: float
    gemini_start_sensitivity: str
    gemini_end_sensitivity: str
    gemini_silence_duration_ms: int
    gemini_prefix_padding_ms: int
    max_call_duration: int
    filler_message: List[str]
    function_filler_message: List[str]
    sarvam_min_rms: int
    sarvam_min_speech_ms: int
    sarvam_min_speech_ms_singleword: int
    sarvam_silero_threshold: float
    sarvam_silero_min_speech_ms: int
    gemini_silero_fallback_speech_ms: int
    post_speech_hold_ms: int
    inactivity_first_rescue_secs: float
    inactivity_first_nudge_gap_secs: float
    inactivity_nudge_secs: float
    inactivity_close_secs: float
    inactivity_phrase: str
    inactivity_end_phrase: str
    lang_notes: str
    analysis_prompt: str
    # TTS provider/model/voice — real, sourced from the stored doc (see voice_catalog.py)
    tts_provider_id: int = 3
    tts_model_id: int = 1
    voice_id: int = 12
    interruption_sensitivity: str = "balanced"
    mute_during_closing: bool = True
    # Lock — True means live in production; edits and deletes are rejected
    # without the owning user's password (see update_workflow_bot).
    is_locked: bool = False
    # Timestamps / meta
    is_deleted: bool
    deleted_until: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str
    calls_today: int

    model_config = {"from_attributes": True}


class WorkflowBotsListResponse(BaseModel):
    workflow_bots: List[WorkflowBotResponse]
    total: int


class WorkflowBotConfig(BaseModel):
    """Consumed by bot.py / workflow_engine.py at call start."""
    bot_type: str = "workflow"
    workflow_bot_id: str
    organization_id: str
    # Global system prompt (Gemini system_instruction base)
    global_prompt: str = ""
    # The graph
    workflow: Dict[str, Any]
    # Voice / behaviour settings
    language: str
    temperature: float
    gemini_start_sensitivity: str
    gemini_end_sensitivity: str
    gemini_silence_duration_ms: int
    gemini_prefix_padding_ms: int
    max_call_duration: int
    filler_message: List[str]
    function_filler_message: List[str]
    sarvam_min_rms: int = 600
    sarvam_min_speech_ms: int = 500
    sarvam_min_speech_ms_singleword: int = 800
    sarvam_silero_threshold: float = 0.5
    sarvam_silero_min_speech_ms: int = 120
    gemini_silero_fallback_speech_ms: int = 150
    post_speech_hold_ms: int = 300
    inactivity_first_rescue_secs: float = 4.0
    inactivity_first_nudge_gap_secs: float = 4.0
    inactivity_nudge_secs: float = 10.0
    inactivity_close_secs: float = 5.0
    inactivity_phrase: str = "क्या आप अभी line पर हैं?"
    inactivity_end_phrase: str = "जी, कोई response नहीं आया, इसलिए मैं call समाप्त कर रही हूँ. धन्यवाद."
    lang_notes: str = ""
    analysis_prompt: str = ""
    # TTS provider/voice — resolved from voice_id via voice_catalog.resolve_voice(),
    # same semantics as BotConfig.tts_provider/tts_voice above.
    tts_provider: str = "justdial"
    tts_voice: str = "simran"
    # How easily a caller can interrupt the bot mid-sentence — same
    # named-preset semantics as BotConfig.interruption_sensitivity above.
    interruption_sensitivity: str = "balanced"
    # Whether to mute the caller's mic while the bot speaks its closing line.
    mute_during_closing: bool = True
