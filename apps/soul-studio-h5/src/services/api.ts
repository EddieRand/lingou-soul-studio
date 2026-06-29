// services/api.ts - Frontend API service

const BASE = '/api';

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = localStorage.getItem('lingou_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const res = await fetch(`${BASE}${path}`, {
    headers: { ...headers, ...(opts?.headers as Record<string, string>) },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ============== Auth ==============

export interface Token {
  access_token: string
  token_type: string
  user_id: string
  username: string
}

export const apiAuth = {
  wechatLogin: () =>
    request<Token>('/auth/wechat-login', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  appleLogin: () =>
    request<Token>('/auth/apple-login', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}

// ============== Bases ==============

export type BindingStatus = 'unbound' | 'bound_to_current_user' | 'bound_to_other_user'

export interface BaseProfile {
  base_id: string;
  bound_user_id: string | null;
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
  error_code?: string;
  message?: string;
}

export interface UnbindResult {
  success: boolean;
  binding_status: 'unbound';
}

// Mock 数据 - 开发期使用
const MOCK_BASE_ID = 'BASE-001'

export const apiBases = {
  create: (base_id: string, bound_user_id?: string) =>
    request<BaseProfile>('/bases', {
      method: 'POST',
      body: JSON.stringify({ base_id, bound_user_id }),
    }),

  get: (base_id: string) =>
    request<{ base: BaseProfile; figure: any }>(`/bases/${base_id}`),

  // 旧版 bind（保留兼容）
  bindLegacy: (base_id: string, bound_user_id: string) =>
    request<BaseProfile>(`/bases/${base_id}/bind`, {
      method: 'POST',
      body: JSON.stringify({ bound_user_id }),
    }),

  // 新版 bind - 扫码绑定（第一版 mock，函数签名预留真实接口）
  bind: async (params: { base_id?: string; qr_token: string; user_id: string }): Promise<BindResult> => {
    // TODO: 接真实后端 POST /api/bases/bind-with-qr
    // Mock 实现
    return new Promise((resolve) => {
      setTimeout(() => {
        // 根据 qr_token 模拟不同结果
        if (params.qr_token === 'VALID_QR_001') {
          resolve({
            success: true,
            base_id: MOCK_BASE_ID,
            binding_status: 'bound_to_current_user',
          })
        } else if (params.qr_token === 'INVALID_QR') {
          resolve({
            success: false,
            error_code: 'INVALID_QR_CODE',
            message: '二维码无效',
          })
        } else if (params.qr_token === 'ALREADY_BOUND_QR') {
          resolve({
            success: false,
            error_code: 'BASE_ALREADY_BOUND',
            message: '该底座已绑定其他账号',
          })
        } else {
          // 默认成功
          resolve({
            success: true,
            base_id: MOCK_BASE_ID,
            binding_status: 'bound_to_current_user',
          })
        }
      }, 500)
    })
  },

  // 解绑底座（第一版 mock，函数签名预留真实接口）
  unbind: async (_params: { base_id: string; user_id: string }): Promise<UnbindResult> => {
    // TODO: 接真实后端 POST /api/bases/unbind
    // Mock 实现
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          success: true,
          binding_status: 'unbound',
        })
      }, 300)
    })
  },

  setActiveFigure: (base_id: string, figure_id: string) =>
    request<BaseProfile>(`/bases/${base_id}/active-figure`, {
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
  name: string;
  archetype: string;
  background: string;
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
    return request<FigureProfile>(`/figures/${figure_id}`)
  },
  create: (data: any) => {
    return request<FigureProfile>('/figures', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
  update: (figure_id: string, data: any) => {
    return request<FigureProfile>(`/figures/${figure_id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
  delete: (figure_id: string) => {
    return request<{ success: boolean }>(`/figures/${figure_id}`, { method: 'DELETE' })
  },
  saveCharacter: (figure_id: string, character_profile: CharacterProfile) => {
    return request<FigureProfile>(`/figures/${figure_id}/character`, {
      method: 'PUT',
      body: JSON.stringify({ character_profile }),
    })
  },
  simulateAbsence: (figure_id: string, hours: number) => {
    return request<FigureProfile>(`/figures/${figure_id}/simulate-absence`, {
      method: 'POST',
      body: JSON.stringify({ hours }),
    })
  },
  boostRelationship: (figure_id: string, params?: { points?: number; level?: string; streak_days?: number }) => {
    return request<FigureProfile>(`/figures/${figure_id}/boost-relationship`, {
      method: 'POST',
      body: JSON.stringify(params || {}),
    })
  },
};

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

// ============== Brain ==============

export const apiBrain = {
  status: (base_id?: string) => {
    const qs = base_id ? `?base_id=${base_id}` : '';
    return request<any>(`/brain/status${qs}`);
  },
  setMode: (mode: string, base_id?: string) => {
    const qs = base_id ? `?base_id=${base_id}` : '';
    return request<any>(`/brain/mode${qs}`, {
      method: 'POST',
      body: JSON.stringify({ mode }),
    });
  },
};

// ============== Voice ==============

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
  listSpeakers: () => request<any>('/voice/speakers'),
  upload: async (figure_id: string, audioFile: File, consentAgreed: boolean) => {
    const form = new FormData();
    form.append('figure_id', figure_id);
    form.append('audio', audioFile);
    form.append('consent_agreed', String(consentAgreed));
    form.append('consent_text_version', 'v1');
    const res = await fetch('/api/voice/upload', { method: 'POST', body: form });
    if (!res.ok) throw new Error('Upload failed');
    return res.json();
  },
  cloneStart: async (figure_id: string, prompt_text?: string) => {
    const res = await fetch('/api/voice/clone/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ figure_id, prompt_text: prompt_text || '' }),
    });
    if (!res.ok) throw new Error('Clone start failed');
    return res.json();
  },
  cloneStatus: async (figure_id: string) => {
    const res = await fetch(`/api/voice/clone/status?figure_id=${figure_id}`);
    if (!res.ok) throw new Error('Get clone status failed');
    return res.json();
  },
};

// ============== Sync ==============

export interface CloudSyncRequest {
  user_id: string
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
  download: (user_id: string, last_sync_at?: string) => {
    const qs = last_sync_at ? `?last_sync_at=${last_sync_at}` : ''
    return request<any>(`/sync/download?user_id=${user_id}${qs}`)
  },
  sync: (data: CloudSyncRequest) =>
    request<any>('/sync/sync', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  migrate: (user_id: string) =>
    request<any>('/sync/migrate', {
      method: 'POST',
      body: JSON.stringify({ user_id }),
    }),
};
