# Shared Pydantic models for Lingou Soul Companion
# Must stay consistent with TypeScript types.ts

from datetime import datetime
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ============== Enums ==============

class ArchetypeEnum(str, Enum):
    御姐照顾型 = "御姐照顾型"
    傲娇吐槽型 = "傲娇吐槽型"
    软萌治愈型 = "软萌治愈型"
    元气伙伴型 = "元气伙伴型"
    冷淡守护型 = "冷淡守护型"
    桀骜战神型 = "桀骜战神型"
    搞怪捣蛋型 = "搞怪捣蛋型"
    憨憨吃货型 = "憨憨吃货型"
    机械副官型 = "机械副官型"
    萌宠陪伴型 = "萌宠陪伴型"
    潮玩幸运型 = "潮玩幸运型"


class FigureTypeEnum(str, Enum):
    二次元手办 = "二次元手办"
    机甲模型 = "机甲模型"
    童年角色 = "童年角色"
    宠物公仔 = "宠物公仔"
    潮玩盲盒 = "潮玩盲盒"
    原创角色 = "原创角色"


class TouchType(str, Enum):
    figure_placed = "figure_placed"
    light_touch = "light_touch"
    heavy_press = "heavy_press"
    double_tap = "double_tap"


class VoiceType(str, Enum):
    system = "system"
    custom = "custom"


class VoiceStatus(str, Enum):
    pending = "pending"
    ready = "ready"
    training = "training"
    pending_clone = "pending_clone"


class VoiceMode(str, Enum):
    default = "default"
    voice_design = "voice_design"
    voice_clone = "voice_clone"


class CloneStatus(str, Enum):
    not_started = "not_started"
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class CloneEngine(str, Enum):
    system_tts = "system_tts"
    voxcpm2 = "voxcpm2"
    cloud_tts = "cloud_tts"


class DialogueSource(str, Enum):
    voice_wake = "voice_wake"
    double_tap = "double_tap"
    long_press = "long_press"
    manual_debug = "manual_debug"


class BrainMode(str, Enum):
    online = "online"
    offline = "offline"


class SyncItemType(str, Enum):
    memory = "memory"
    dialogue_log = "dialogue_log"
    emotion_state = "emotion_state"


class SyncItemStatus(str, Enum):
    pending = "pending"
    synced = "synced"
    failed = "failed"


class SyncQueueStatus(str, Enum):
    pending = "pending"
    flushing = "flushing"
    completed = "completed"


class BaseStatus(str, Enum):
    unbound = "unbound"
    bound = "bound"
    waiting = "waiting"


class DialogueStateEnum(str, Enum):
    idle = "idle"
    wake_detected = "wake_detected"
    listening = "listening"
    transcribing = "transcribing"
    thinking = "thinking"
    speaking = "speaking"
    error = "error"
    offline_companion = "offline_companion"


class SpeakingStyle(str, Enum):
    formal = "formal"
    casual = "casual"
    cute = "cute"
    cool = "cool"


# ============== Core Objects ==============

class BaseProfile(BaseModel):
    base_id: str
    bound_user_id: str | None = None
    active_figure_id: str | None = None
    status: BaseStatus
    created_at: str
    updated_at: str


class TouchReactions(BaseModel):
    figure_placed: list[str]
    light_touch: list[str]
    heavy_press: list[str]
    double_tap: list[str]


class PersonaObject(BaseModel):
    traits: list[str]
    greeting: str
    speaking_style: SpeakingStyle
    response_templates: TouchReactions


class KnowledgeBounds(BaseModel):
    knows: list[str] = []
    不懂: list[str] = []


class CharacterProfile(BaseModel):
    """Phase A: 角色还魂深化 - 深度角色档案"""
    character_name: str = ""
    one_line: str = ""  # 用户输入的一句话设定
    background: str = ""  # 背景故事 100-200字
    traits: list[str] = []
    speech_style: str = ""  # 说话癖好/语气/口癖描述
    catchphrases: list[str] = []  # 口头禅 3-5条
    signature_lines: list[str] = []  # 标志性台词 3-5条
    relationships: dict[str, str] = {}  # 关系名→称呼
    taboos: list[str] = []  # 禁忌 3-5条
    knowledge_bounds: KnowledgeBounds = Field(default_factory=KnowledgeBounds)
    values: list[str] = []
    address_user_as: str = ""


class SoulProfile(BaseModel):
    archetype: ArchetypeEnum
    name: str
    avatar_url: str | None = None
    description: str = ""
    address_user_as: str
    persona: PersonaObject
    # Bug 2 fix: emotion_state at soul_profile level (not inside persona)
    emotion_state: EmotionState
    created_at: str
    updated_at: str
    # Phase A: 角色深化层（可选）
    character_profile: CharacterProfile | None = None


class MemoryObject(BaseModel):
    figure_id: str
    interaction_count: int = 0
    last_interaction_at: str | None = None
    favorite_responses: list[str] = []


class EmotionState(BaseModel):
    happy: int = 50
    lonely: int = 0
    attached: int = 0
    annoyed: int = 0
    attention: int = 0
    sleepy: int = 0
    last_dialogue_at: str | None = None


class VoiceProfile(BaseModel):
    voice_id: str
    name: str
    created_at: str
    updated_at: str
    voice_type: VoiceType
    voice_mode: VoiceMode = VoiceMode.default
    system_voice_name: str | None = None
    speech_rate: int = 175
    recording_url: str | None = None
    voice_status: VoiceStatus = VoiceStatus.pending
    clone_status: CloneStatus = CloneStatus.not_started
    clone_engine: CloneEngine | None = None
    cached_audio_path: str | None = None


class FigureProfile(BaseModel):
    figure_id: str
    name: str
    avatar_url: str | None = None
    description: str = ""
    created_at: str
    updated_at: str
    base_id: str | None = None
    figure_type: FigureTypeEnum
    wake_names: list[str]
    soul_profile: SoulProfile
    voice_profile: VoiceProfile
    touch_reactions: TouchReactions
    memory: MemoryObject


class ArchetypeTemplate(BaseModel):
    archetype: ArchetypeEnum
    personality_traits: list[str]
    recommended_voice: str
    greeting: str
    speaking_style: SpeakingStyle
    response_templates: TouchReactions


class EventLog(BaseModel):
    event_id: str
    base_id: str
    figure_id: str
    event_type: TouchType
    reply: str
    mood_before: EmotionState
    mood_after: EmotionState
    voice_profile_id: str
    led_effect: str | None = None
    triggered_at: str


class DialogueLog(BaseModel):
    dialogue_id: str
    figure_id: str
    base_id: str
    wake_source: DialogueSource
    user_input_text: str
    reply_text: str
    brain_mode: BrainMode
    tts_engine: str | None = None
    emotion_at: EmotionState
    memory_candidate: str = ""
    created_at: str


class SyncQueueItem(BaseModel):
    item_id: str
    type: SyncItemType
    data: dict
    status: SyncItemStatus


class SyncQueue(BaseModel):
    queue_id: str
    items: list[SyncQueueItem] = []
    status: SyncQueueStatus = SyncQueueStatus.pending
    created_at: str
    updated_at: str


class DialogueState(BaseModel):
    state: DialogueStateEnum
    figure_id: str | None = None
    base_id: str | None = None
    wake_source: str | None = None
    started_at: str | None = None


class EventResponse(BaseModel):
    base_id: str
    figure_id: str
    event: TouchType
    reply: str
    mood: EmotionState
    voice_profile_id: str
    led_effect: str | None = None


# ============== API Request/Response ==============

class CreateBaseRequest(BaseModel):
    base_id: str
    bound_user_id: str | None = None


class BindBaseRequest(BaseModel):
    bound_user_id: str


class SetActiveFigureRequest(BaseModel):
    figure_id: str


class CreateFigureRequest(BaseModel):
    name: str
    avatar_url: str | None = None
    description: str | None = None
    figure_type: FigureTypeEnum
    wake_names: list[str]
    soul_profile: SoulProfile
    voice_profile: Partial[VoiceProfile] | None = None
    touch_reactions: TouchReactions


class UpdateFigureRequest(BaseModel):
    name: str | None = None
    avatar_url: str | None = None
    description: str | None = None
    wake_names: list[str] | None = None
    soul_profile: Partial[SoulProfile] | None = None
    voice_profile: Partial[VoiceProfile] | None = None
    touch_reactions: Partial[TouchReactions] | None = None


class SimulateHardwareRequest(BaseModel):
    base_id: str
    event_type: TouchType


class DialogueWakeRequest(BaseModel):
    base_id: str
    figure_id: str | None = None
    trigger: DialogueSource


class DialogueTextRequest(BaseModel):
    base_id: str
    figure_id: str
    text: str


class BrainModeRequest(BaseModel):
    mode: BrainMode
