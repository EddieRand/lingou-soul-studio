// services/api.ts - Frontend API service

import { getStoredToken, invalidateStoredSession } from './authSession'

const BASE = '/api'

type RequestOptions = RequestInit & { authenticated?: boolean }

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { authenticated = true, ...fetchOptions } = opts
  const requestToken = authenticated ? getStoredToken() : null
  const headers = new Headers(fetchOptions.headers)
  const body = fetchOptions.body

  if (requestToken) {
    headers.set('Authorization', `Bearer ${requestToken}`)
  }
  if (
    body !== undefined
    && !(body instanceof FormData)
    && !(body instanceof URLSearchParams)
    && !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${BASE}${path}`, { ...fetchOptions, headers })
  if (!res.ok) {
    if (res.status === 401 && authenticated) {
      invalidateStoredSession(requestToken)
    }
    const errorBody = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    const detail = typeof errorBody.detail === 'string'
      ? errorBody.detail
      : errorBody.detail?.message
    throw new ApiError(
      detail || `HTTP ${res.status}`,
      res.status,
      errorBody.error_code || errorBody.detail?.code,
    )
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json()
}

async function requestAudio(
  path: string,
  opts: RequestOptions = {},
): Promise<VoicePreviewAudio> {
  const { authenticated = true, ...fetchOptions } = opts
  const requestToken = authenticated ? getStoredToken() : null
  const headers = new Headers(fetchOptions.headers)
  if (requestToken) {
    headers.set('Authorization', `Bearer ${requestToken}`)
  }
  if (fetchOptions.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${BASE}${path}`, { ...fetchOptions, headers })
  if (!response.ok) {
    if (response.status === 401 && authenticated) {
      invalidateStoredSession(requestToken)
    }
    const body = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
    const detail = typeof body.detail === 'string'
      ? body.detail
      : body.detail?.message
    throw new ApiError(
      detail || `HTTP ${response.status}`,
      response.status,
      body.error_code || body.detail?.code,
    )
  }

  return {
    blob: await response.blob(),
    engine: response.headers.get('X-Lingou-Audio-Engine') || 'unknown',
    source: response.headers.get('X-Lingou-Audio-Source') || 'synthesized',
    speaker: response.headers.get('X-Lingou-Voice-Speaker') || '',
    synthesizedAt: response.headers.get('X-Lingou-Audio-Synthesized-At') || '',
    transferredAt: new Date().toISOString(),
  }
}

// ============== Auth ==============

export interface Token {
  access_token: string
  token_type: string
  user_id: string
  username: string
}

export interface AuthUser {
  user_id: string
  username: string
  email: string
  created_at: string
}

export interface WebSocketTicket {
  ticket: string
  expires_in: number
}

export const apiAuth = {
  login: (username: string, password: string) =>
    request<Token>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username, password }),
      authenticated: false,
    }),
  register: (username: string, email: string, password: string) =>
    request<AuthUser>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
      authenticated: false,
    }),
  verify: () => request<AuthUser>('/auth/verify'),
  logout: () => request<{ message: string }>('/auth/logout', { method: 'POST' }),
  createWebSocketTicket: (base_id: string) =>
    request<WebSocketTicket>('/auth/ws-ticket', {
      method: 'POST',
      body: JSON.stringify({ base_id }),
    }),
}

// ============== Bases ==============

export type BindingStatus = 'unbound' | 'bound_to_current_user' | 'bound_to_other_user'

export interface BaseProfile {
  base_id: string;
  active_figure_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  binding_status?: BindingStatus;
}

export interface BindResult {
  success: boolean;
  base_id?: string;
  binding_status?: BindingStatus;
  newly_bound?: boolean;
  base?: BaseProfile;
  figure?: FigureProfile | null;
}

export interface UnbindResult {
  success: boolean;
  binding_status: 'unbound';
}

export interface BaseDetail {
  base: BaseProfile;
  figure: FigureProfile | null;
}

export const apiBases = {
  list: () => request<BaseDetail[]>('/bases'),

  createTestBase: (base_id: string) =>
    request<BaseDetail>('/bases/test-bases', {
      method: 'POST',
      body: JSON.stringify({ base_id }),
    }),

  get: (base_id: string) =>
    request<BaseDetail>(`/bases/${encodeURIComponent(base_id)}`),

  bind: (params: { qr_token: string }) =>
    request<BindResult>('/bases/pair', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  unbind: (params: { base_id: string }) =>
    request<UnbindResult>(`/bases/${encodeURIComponent(params.base_id)}/unbind`, {
      method: 'POST',
    }),

  setActiveFigure: (base_id: string, figure_id: string) =>
    request<BaseDetail>(`/bases/${encodeURIComponent(base_id)}/active-figure`, {
      method: 'POST',
      body: JSON.stringify({ figure_id }),
    }),
};

// ============== Character ==============

export interface Recommendation {
  recommended_archetype: string;
  personality_traits: string[];
  speech_style: string;
  recommended_voice: string;
  wake_reply: string;
  recommended_touch_reactions: {
    figure_placed: string;
    light_touch: string;
    heavy_press: string;
    double_tap: string;
    long_press: string;
  };
  recommended_touch_escalation?: {
    light_touch?: { tier2: string[]; tier3: string[] };
    heavy_press?: { tier2: string[]; tier3: string[] };
    double_tap?: { tier2: string[]; tier3: string[] };
  };
}

export interface CharacterProfile {
  name?: string;
  character_name?: string;
  archetype?: string;
  one_line?: string;
  background: string;
  speech_style?: string;
  address_user_as?: string;
  catchphrases: string[];
  signature_lines: string[];
  taboos: string[];
  personality_traits: string[];
  relationships: Record<string, string>;
  values: string[];
  traits: string[];
  knowledge_bounds: {
    knows: string[];
    unknowns: string[];
  };
}

export const apiCharacter = {
  generate: (payload: { name: string; figure_type: string; archetype: string; one_line: string }, timeoutMs = 70000) =>
    request<{ recommendation: Recommendation; character_profile: CharacterProfile }>('/character/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal: timeoutMs ? AbortSignal.timeout(timeoutMs) : undefined,
    }),
};

// ============== Figures ==============

export interface FigureProfile {
  figure_id: string;
  name: string;
  avatar_url: string | null;
  description: string;
  created_at: string;
  updated_at: string;
  base_id: string | null;
  figure_type: string;
  wake_names: string[];
  soul_profile: any;
  voice_profile: any;
  touch_reactions: any;
  touch_escalation?: {
    light_touch?: { tier2: string[]; tier3: string[] };
    heavy_press?: { tier2: string[]; tier3: string[] };
    double_tap?: { tier2: string[]; tier3: string[] };
  };
  memory: any;
  // Phase B: 生命状态（情绪衰减后）
  life_status?: {
    elapsed_hours: number;
    neglect_tier: string;
    status_description: string;
    simulated?: boolean;
  };
}

export const apiFigures = {
  list: () => {
    return request<FigureProfile[]>('/figures')
  },
  get: (figure_id: string) => {
    return request<FigureProfile>(`/figures/${encodeURIComponent(figure_id)}`)
  },
  create: (data: any) => {
    return request<FigureProfile>('/figures', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
  update: (figure_id: string, data: any) => {
    return request<FigureProfile>(`/figures/${encodeURIComponent(figure_id)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
  delete: (figure_id: string) => {
    return request<{ success: boolean }>(`/figures/${encodeURIComponent(figure_id)}`, { method: 'DELETE' })
  },
  saveCharacter: (figure_id: string, character_profile: CharacterProfile) => {
    return request<FigureProfile>(`/figures/${encodeURIComponent(figure_id)}/character`, {
      method: 'PUT',
      body: JSON.stringify({ character_profile }),
    })
  },
  simulateAbsence: (figure_id: string, hours: number) => {
    return request<FigureProfile>(`/figures/${encodeURIComponent(figure_id)}/simulate-absence`, {
      method: 'POST',
      body: JSON.stringify({ hours }),
    })
  },
  boostRelationship: (figure_id: string, params?: { points?: number; level?: string; streak_days?: number }) => {
    return request<FigureProfile>(`/figures/${encodeURIComponent(figure_id)}/boost-relationship`, {
      method: 'POST',
      body: JSON.stringify(params || {}),
    })
  },
};

export interface MemoryRecord {
  memory_id: string
  content: string
  status: 'pending' | 'confirmed'
  source: 'model' | 'user'
  source_turn_id: string | null
  created_at: string
  updated_at: string
  confirmed_at?: string
}

export interface MemoryCollection {
  figure_id: string
  confirmed_facts: MemoryRecord[]
  candidates: MemoryRecord[]
  confirmed_limit: number
  revision: number
  updated_at: string | null
}

export const apiMemories = {
  list: (figure_id: string) =>
    request<MemoryCollection>(`/figures/${encodeURIComponent(figure_id)}/memories`),
  create: (figure_id: string, content: string) =>
    request<{ memory: MemoryRecord; created: boolean }>(
      `/figures/${encodeURIComponent(figure_id)}/memories`,
      {
        method: 'POST',
        body: JSON.stringify({ content }),
      },
    ),
  confirm: (figure_id: string, memory_id: string) =>
    request<{ memory: MemoryRecord }>(
      `/figures/${encodeURIComponent(figure_id)}/memories/${encodeURIComponent(memory_id)}/confirm`,
      { method: 'POST' },
    ),
  update: (figure_id: string, memory_id: string, content: string) =>
    request<{ memory: MemoryRecord }>(
      `/figures/${encodeURIComponent(figure_id)}/memories/${encodeURIComponent(memory_id)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content }),
      },
    ),
  delete: (figure_id: string, memory_id: string) =>
    request<void>(
      `/figures/${encodeURIComponent(figure_id)}/memories/${encodeURIComponent(memory_id)}`,
      { method: 'DELETE' },
    ),
}

// ============== Souls/Archetypes ==============

export interface Archetype {
  archetype: string;
  personality_traits: string[];
  recommended_voice: string;
  volcano_speaker: string;
  greeting: string;
  speaking_style: string;
  response_templates: {
    figure_placed: string[];
    light_touch: string[];
    heavy_press: string[];
    double_tap: string[];
  };
}

export const apiSouls = {
  getArchetypes: () => request<Archetype[]>('/souls/archetypes'),
};

// ============== Events ==============

export interface EventResponse {
  base_id: string;
  figure_id: string;
  event: string;
  reply: string;
  mood: {
    happy: number;
    lonely: number;
    attached: number;
    annoyed: number;
    attention: number;
    sleepy: number;
    last_dialogue_at: string | null;
  };
  voice_profile_id: string;
  led_effect: string | null;
}

export const apiEvents = {
  send: (base_id: string, event_type: string) =>
    request<EventResponse>('/events', {
      method: 'POST',
      body: JSON.stringify({ base_id, event_type }),
    }),
  getLogs: (params?: { base_id?: string; figure_id?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.base_id) qs.set('base_id', params.base_id);
    if (params?.figure_id) qs.set('figure_id', params.figure_id);
    if (params?.limit) qs.set('limit', String(params.limit));
    return request<any[]>(`/events/logs?${qs}`);
  },
};

// ============== Hardware ==============

export const apiHardware = {
  simulate: (base_id: string, event_type: string) =>
    request<EventResponse>('/hardware/simulate', {
      method: 'POST',
      body: JSON.stringify({ base_id, event_type }),
    }),
  getSystemVoices: () => request<string[]>('/hardware/system-voices'),
};

// ============== Dialogue / ASR ==============

export const apiDialogue = {
  getState: (base_id: string) =>
    request<any>(`/dialogue/state?base_id=${encodeURIComponent(base_id)}`),
  sendText: (base_id: string, text: string) =>
    request<any>('/dialogue/text', {
      method: 'POST',
      body: JSON.stringify({ base_id, text }),
    }),
  getLogs: (figure_id: string, limit = 10) =>
    request<any[]>(
      `/dialogue/logs?figure_id=${encodeURIComponent(figure_id)}&limit=${encodeURIComponent(String(limit))}`,
    ),
  getAsrStatus: () => request<{ available: boolean; message: string }>('/asr/status'),
}

// ============== Brain ==============

export const apiBrain = {
  status: (base_id?: string) => {
    const qs = base_id ? `?base_id=${encodeURIComponent(base_id)}` : '';
    return request<any>(`/brain/status${qs}`);
  },
  setMode: (mode: string, base_id?: string) => {
    const qs = base_id ? `?base_id=${encodeURIComponent(base_id)}` : '';
    return request<any>(`/brain/mode${qs}`, {
      method: 'POST',
      body: JSON.stringify({ mode }),
    });
  },
};

// ============== Voice ==============

export interface VoicePreviewRequest {
  text: string
  speaker?: string
  figure_id?: string
}

export interface VoicePreviewAudio {
  blob: Blob
  engine: string
  source: string
  speaker: string
  synthesizedAt: string
  transferredAt: string
}

export const apiVoice = {
  generate: (figure_id: string, text: string, speaker?: string) =>
    request<any>('/voice/generate', {
      method: 'POST',
      body: JSON.stringify({ figure_id, text, speaker }),
    }),
  design: (figure_id: string, speaker: string, tts_engine?: string) =>
    request<any>('/voice/design', {
      method: 'POST',
      body: JSON.stringify({ figure_id, speaker, tts_engine }),
    }),
  preview: (payload: VoicePreviewRequest, signal?: AbortSignal) =>
    requestAudio('/voice/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    }),
  listSpeakers: () => request<any>('/voice/speakers'),
  upload: async (figure_id: string, audioFile: File, consentAgreed: boolean) => {
    const form = new FormData();
    form.append('figure_id', figure_id);
    form.append('audio', audioFile);
    form.append('consent_agreed', String(consentAgreed));
    form.append('consent_text_version', 'v1');
    return request<any>('/voice/upload', { method: 'POST', body: form })
  },
  cloneStart: (figure_id: string, prompt_text?: string) =>
    request<any>('/voice/clone/start', {
      method: 'POST',
      body: JSON.stringify({ figure_id, prompt_text: prompt_text || '' }),
    }),
  cloneStatus: (figure_id: string) =>
    request<any>(`/voice/clone/status?figure_id=${encodeURIComponent(figure_id)}`),
};

// ============== Sync ==============

export interface CloudSyncRequest {
  figures: any[]
  dialogue_logs: any[]
  events: any[]
  last_sync_at?: string
}

export interface CloudSyncResponse {
  success: boolean
  message: string
  synced_at: string
  figures_count: number
  logs_count: number
  events_count: number
  conflicts: any[]
}

export const apiSync = {
  upload: (data: CloudSyncRequest) =>
    request<CloudSyncResponse>('/sync/upload', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  download: (last_sync_at?: string) => {
    const qs = new URLSearchParams()
    if (last_sync_at) qs.set('last_sync_at', last_sync_at)
    const suffix = qs.size > 0 ? `?${qs.toString()}` : ''
    return request<any>(`/sync/download${suffix}`, { method: 'POST' })
  },
  sync: (data: CloudSyncRequest) =>
    request<any>('/sync/sync', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};
