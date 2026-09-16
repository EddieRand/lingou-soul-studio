// Shared type definitions for Lingou Soul Companion
// Must stay consistent with Python models.py

// ============== Enums ==============

export type ArchetypeEnum =
  | "御姐照顾型"
  | "傲娇吐槽型"
  | "软萌治愈型"
  | "元气伙伴型"
  | "冷淡守护型"
  | "桀骜战神型"
  | "搞怪捣蛋型"
  | "憨憨吃货型"
  | "机械副官型"
  | "萌宠陪伴型"
  | "潮玩幸运型";

export type FigureTypeEnum =
  | "二次元手办"
  | "机甲模型"
  | "童年角色"
  | "宠物公仔"
  | "潮玩盲盒"
  | "原创角色";

export type TouchType = "figure_placed" | "light_touch" | "heavy_press" | "double_tap";

export type VoiceType = "system" | "custom";

export type VoiceStatus = "pending" | "ready" | "training" | "pending_clone";

export type VoiceMode = "default" | "voice_design" | "voice_clone";

export type CloneStatus = "not_started" | "pending" | "processing" | "ready" | "failed";

export type CloneEngine = "system_tts" | "voxcpm2" | "cloud_tts";

export type DialogueSource = "voice_wake" | "double_tap" | "long_press" | "manual_debug";

export type BrainMode = "online" | "offline";

export type SyncItemType = "memory" | "dialogue_log" | "emotion_state";

export type SyncItemStatus = "pending" | "synced" | "failed";

export type SyncQueueStatus = "pending" | "flushing" | "completed";

export type BaseStatus = "unbound" | "bound" | "waiting";

export type DialogueStateEnum =
  | "idle"
  | "wake_detected"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "error"
  | "offline_companion";

export type SpeakingStyle = "formal" | "casual" | "cute" | "cool";

// ============== Core Objects ==============

export interface BaseProfile {
  schema_version: 2;
  owner_user_id: string;
  base_id: string;
  active_figure_id: string | null;
  status: BaseStatus;
  created_at: string;
  updated_at: string;
}

export interface PersonaObject {
  traits: string[];
  greeting: string;
  speaking_style: SpeakingStyle;
  response_templates: TouchReactions;
}

// ============== Character Profile (Phase A: 角色还魂深化) ==============

export interface KnowledgeBounds {
  knows: string[];
 不懂: string[];
}

export interface CharacterProfile {
  character_name: string;
  one_line: string;
  background: string;
  traits: string[];
  speech_style: string;
  catchphrases: string[];
  signature_lines: string[];
  relationships: Record<string, string>;  // key=关系名, value=称呼
  taboos: string[];
  knowledge_bounds: KnowledgeBounds;
  values: string[];
  address_user_as: string;
}

// ============== SoulProfile with optional CharacterProfile ==============

export interface SoulProfile {
  archetype: ArchetypeEnum;
  name: string;
  avatar_url: string | null;
  description: string;
  address_user_as: string;
  persona: PersonaObject;
  // Bug 2 fix: emotion_state at soul_profile level (not inside persona)
  emotion_state: EmotionState;
  created_at: string;
  updated_at: string;
  // Phase A: 角色深化层（可选，没有则只用 archetype 底色）
  character_profile?: CharacterProfile;
}

export interface TouchReactions {
  figure_placed: string[];
  light_touch: string[];
  heavy_press: string[];
  double_tap: string[];
}

export interface MemoryObject {
  figure_id: string;
  interaction_count: number;
  last_interaction_at: string | null;
  favorite_responses: string[];
}

export interface EmotionState {
  happy: number;
  lonely: number;
  attached: number;
  annoyed: number;
  attention: number;
  sleepy: number;
  last_dialogue_at: string | null;
}

export interface VoiceProfile {
  voice_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  voice_type: VoiceType;
  voice_mode: VoiceMode;
  system_voice_name: string | null;
  speech_rate: number;
  recording_url: string | null;
  voice_status: VoiceStatus;
  clone_status: CloneStatus;
  clone_engine: CloneEngine | null;
  cached_audio_path: string | null;
}

export interface FigureProfile {
  schema_version: 2;
  owner_user_id: string;
  figure_id: string;
  name: string;
  avatar_url: string | null;
  description: string;
  created_at: string;
  updated_at: string;
  base_id: string | null;
  figure_type: FigureTypeEnum;
  wake_names: string[];
  soul_profile: SoulProfile;
  voice_profile: VoiceProfile;
  touch_reactions: TouchReactions;
  memory: MemoryObject;
}

export interface ArchetypeTemplate {
  archetype: ArchetypeEnum;
  personality_traits: string[];
  recommended_voice: string;
  greeting: string;
  speaking_style: SpeakingStyle;
  response_templates: TouchReactions;
}

export interface EventLog {
  schema_version: 2;
  owner_user_id: string;
  event_id: string;
  base_id: string;
  figure_id: string;
  event_type: TouchType;
  reply: string;
  mood_before: EmotionState;
  mood_after: EmotionState;
  voice_profile_id: string;
  led_effect: string | null;
  triggered_at: string;
}

export interface DialogueLog {
  schema_version: 2;
  owner_user_id: string;
  dialogue_id: string;
  session_id?: string;
  turn_id?: string;
  figure_id: string;
  base_id: string;
  wake_source: DialogueSource;
  user_input_text: string;
  reply_text: string;
  brain_mode: BrainMode;
  tts_engine: string | null;
  emotion_at: EmotionState;
  memory_candidate: string;
  created_at: string;
}

export interface SyncQueueItem {
  schema_version: 2;
  owner_user_id: string;
  queue_id: string;
  figure_id: string;
  type: SyncItemType;
  data: Record<string, unknown>;
  sync_status: SyncItemStatus;
  created_at: string;
  synced_at?: string;
}

export interface SyncQueue {
  schema_version: 2;
  owner_user_id: string;
  items: SyncQueueItem[];
  created_at: string;
  updated_at?: string;
}

export interface DialogueState {
  state: DialogueStateEnum;
  figure_id: string | null;
  base_id: string | null;
  wake_source: string | null;
  started_at: string | null;
}

export interface EventResponse {
  base_id: string;
  figure_id: string;
  event: TouchType;
  reply: string;
  mood: EmotionState;
  voice_profile_id: string;
  led_effect: string | null;
}

// ============== API Request/Response Types ==============

export interface CreateBaseRequest {
  base_id: string;
}

export interface PairBaseRequest {
  qr_token: string;
}

export interface DeviceEventRequest {
  event_type: string;
  event_id?: string;
  occurred_at?: string;
}

export interface SetActiveFigureRequest {
  figure_id: string;
}

export interface CreateFigureRequest {
  creation_request_id?: string;
  activate_base_id?: string;
  name: string;
  avatar_url?: string;
  description?: string;
  figure_type: string;
  wake_names?: string[];
  soul_profile?: Partial<SoulProfile>;
  voice_profile?: Partial<VoiceProfile>;
  touch_reactions?: Partial<TouchReactions>;
  touch_escalation?: Record<string, unknown>;
}

export interface UpdateFigureRequest {
  name?: string;
  avatar_url?: string;
  description?: string;
  wake_names?: string[];
  soul_profile?: Partial<SoulProfile>;
  voice_profile?: Partial<VoiceProfile>;
  touch_reactions?: Partial<TouchReactions>;
  touch_escalation?: Record<string, unknown>;
}

export interface SimulateHardwareRequest {
  base_id: string;
  event_type: TouchType;
}

export interface DialogueWakeRequest {
  base_id: string;
  trigger: Exclude<DialogueSource, "manual_debug">;
  text?: string;
}

export interface DialogueTextRequest {
  base_id: string;
  text: string;
  brain_mode_override?: BrainMode;
}

export interface BrainModeRequest {
  mode: BrainMode | "auto";
}
