# 灵偶 API 文档

Base URL: `http://localhost:8000/api`

---

## 基础（Bases）

### POST /bases
创建设备底座

**Request Body**
```json
{
  "name": "我的灵偶底座",
  "model": "BV700_V2"
}
```

**Response**
```json
{
  "id": "base_001",
  "name": "我的灵偶底座",
  "model": "BV700_V2",
  "bound_figure_id": null,
  "is_active": false,
  "created_at": "2026-06-18T10:00:00Z"
}
```

---

### GET /bases/{base_id}
获取底座详情

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `base_id` | string | 底座 ID |

**Response**
```json
{
  "id": "base_001",
  "name": "我的灵偶底座",
  "model": "BV700_V2",
  "bound_figure_id": "figure_001",
  "is_active": true,
  "created_at": "2026-06-18T10:00:00Z"
}
```

---

### POST /bases/{base_id}/bind
绑定灵偶到指定底座

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `base_id` | string | 底座 ID |

**Request Body**
```json
{
  "figure_id": "figure_001"
}
```

**Response**
```json
{
  "success": true,
  "base_id": "base_001",
  "figure_id": "figure_001"
}
```

---

### POST /bases/{base_id}/active-figure
激活当前底座的灵偶

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `base_id` | string | 底座 ID |

**Response**
```json
{
  "success": true,
  "active_figure_id": "figure_001"
}
```

---

## 灵偶（Figures）

### GET /figures
获取所有灵偶列表

**Response**
```json
{
  "figures": [
    {
      "id": "figure_001",
      "name": "小慧",
      "wake_name": "姐姐",
      "archetype": "yujie_care",
      "voice_profile": {
        "speaker": "zh_female_meilinvyou_emo",
        "speed": 1.0,
        "pitch": 1.0,
        "emotion_intensity": 0.8
      },
      "soul_profile": { ... },
      "emotion_state": { ... },
      "created_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

---

### POST /figures
创建新灵偶

**Request Body**
```json
{
  "name": "小慧",
  "wake_name": "姐姐",
  "archetype": "yujie_care",
  "voice_profile": {
    "speaker": "zh_female_meilinvyou_emo",
    "speed": 1.0,
    "pitch": 1.0,
    "emotion_intensity": 0.8
  }
}
```

**Response**
```json
{
  "id": "figure_001",
  "name": "小慧",
  "wake_name": "姐姐",
  "archetype": "yujie_care",
  "voice_profile": { ... },
  "soul_profile": { ... },
  "emotion_state": { ... },
  "created_at": "2026-06-18T10:00:00Z"
}
```

---

### GET /figures/{figure_id}
获取灵偶详情

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `figure_id` | string | 灵偶 ID |

**Response**
```json
{
  "id": "figure_001",
  "name": "小慧",
  "wake_name": "姐姐",
  "archetype": "yujie_care",
  "voice_profile": { ... },
  "soul_profile": { ... },
  "emotion_state": { ... },
  "voice_pool": [ ... ],
  "created_at": "2026-06-18T10:00:00Z"
}
```

---

### PUT /figures/{figure_id}
更新灵偶信息

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `figure_id` | string | 灵偶 ID |

**Request Body**
```json
{
  "name": "新名字",
  "voice_profile": {
    "speaker": "zh_female_tianmei_emo"
  }
}
```

**Response**
```json
{
  "id": "figure_001",
  "name": "新名字",
  ...
}
```

---

### DELETE /figures/{figure_id}
删除灵偶

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `figure_id` | string | 灵偶 ID |

**Response**
```json
{
  "success": true,
  "deleted_id": "figure_001"
}
```

---

## 灵魂原型（Souls）

### GET /souls/archetypes
获取所有灵魂原型模板

**Response**
```json
{
  "archetypes": [
    {
      "id": "yujie_care",
      "name": "御姐照顾型",
      "description": "成熟稳重，善于照顾人的御姐型灵魂",
      "default_emotion_state": { ... },
      "compatible_voices": [ ... ]
    },
    {
      "id": "shoushi_heart",
      "name": "手饰心类型",
      "description": "温柔细腻，富有同理心的灵魂",
      "default_emotion_state": { ... },
      "compatible_voices": [ ... ]
    }
  ]
}
```

---

## 事件（Events）

### POST /events
记录设备事件

**Request Body**
```json
{
  "base_id": "base_001",
  "figure_id": "figure_001",
  "event_type": "touch",
  "touch_position": "head",
  "duration_ms": 1500
}
```

**Response**
```json
{
  "event_id": "evt_001",
  "created_at": "2026-06-18T10:00:00Z"
}
```

---

### GET /events/logs
获取事件日志

**Query Parameters**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `figure_id` | string | null | 按灵偶 ID 过滤 |
| `event_type` | string | null | 按事件类型过滤 |
| `limit` | int | 50 | 返回条数 |

**Response**
```json
{
  "events": [
    {
      "event_id": "evt_001",
      "figure_id": "figure_001",
      "event_type": "touch",
      "touch_position": "head",
      "duration_ms": 1500,
      "created_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

---

## 对话（Dialogue）

### POST /dialogue/wake
唤醒灵偶

**Request Body**
```json
{
  "figure_id": "figure_001",
  "wake_word": "姐姐"
}
```

**Response**
```json
{
  "awakened": true,
  "emotion_state": { ... }
}
```

---

### POST /dialogue/text
发送文本对话

**Request Body**
```json
{
  "figure_id": "figure_001",
  "text": "你好呀"
}
```

**Response**
```json
{
  "response_text": "你好呀，我是小慧～",
  "response_audio_url": "/audio/response_001.mp3",
  "tts_engine": "volcano_tts",
  "emotion_state": { ... }
}
```

---

### GET /dialogue/state
获取当前对话状态

**Query Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `figure_id` | string | 灵偶 ID |

**Response**
```json
{
  "figure_id": "figure_001",
  "conversation_active": true,
  "last_interaction": "2026-06-18T10:00:00Z",
  "emotion_state": {
    "joy": 0.8,
    "anger": 0.1,
    "sadness": 0.1,
    "fear": 0.0,
    "surprise": 0.3,
    "disgust": 0.0
  }
}
```

---

### POST /dialogue/audio
上传音频并获取对话响应

**Request Body** (multipart/form-data)
| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | file | WAV/MP3 音频文件 |
| `figure_id` | string | 灵偶 ID |

**Response**
```json
{
  "response_text": "听到了～",
  "response_audio_url": "/audio/response_002.mp3"
}
```

---

### GET /dialogue/logs
获取对话历史

**Query Parameters**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `figure_id` | string | null | 按灵偶 ID 过滤 |
| `limit` | int | 50 | 返回条数 |

**Response**
```json
{
  "logs": [
    {
      "id": "log_001",
      "figure_id": "figure_001",
      "role": "user",
      "content": "你好",
      "created_at": "2026-06-18T10:00:00Z"
    },
    {
      "id": "log_002",
      "figure_id": "figure_001",
      "role": "assistant",
      "content": "你好呀～",
      "tts_engine": "volcano_tts",
      "created_at": "2026-06-18T10:00:01Z"
    }
  ]
}
```

---

## 大脑（Brain）

### GET /brain/status
获取大脑状态

**Query Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `figure_id` | string | 灵偶 ID |

**Response**
```json
{
  "figure_id": "figure_001",
  "online_brain": "ark",
  "offline_brain": "voice_pool",
  "current_mode": "auto",
  "voice_pool_ready": true,
  "ark_connected": true
}
```

---

### POST /brain/mode
设置大脑模式

**Request Body**
```json
{
  "figure_id": "figure_001",
  "mode": "force_online"
}
```

**Mode 取值**：
| 值 | 说明 |
|----|------|
| `auto` | 自动（短文本/关键词走离线） |
| `force_online` | 强制使用豆包 Ark |
| `force_offline` | 强制使用离线语音池 |

**Response**
```json
{
  "success": true,
  "current_mode": "force_online"
}
```

---

## 语音（Voice）

### POST /voice/generate
生成语音

**Request Body**
```json
{
  "figure_id": "figure_001",
  "text": "今天天气真好呀～",
  "speaker": "zh_female_meilinvyou_emo",
  "speed": 1.0,
  "pitch": 1.0,
  "emotion_intensity": 0.8
}
```

**Response**
```json
{
  "audio_url": "/audio/generated_001.mp3",
  "duration_ms": 2500,
  "tts_engine": "volcano_tts"
}
```

---

### POST /voice/design
设计音色参数

**Request Body**
```json
{
  "figure_id": "figure_001",
  "speaker": "zh_female_tianmei_emo",
  "speed": 1.1,
  "pitch": 0.95,
  "emotion_intensity": 0.9
}
```

**Response**
```json
{
  "success": true,
  "voice_profile": {
    "speaker": "zh_female_tianmei_emo",
    "speed": 1.1,
    "pitch": 0.95,
    "emotion_intensity": 0.9
  }
}
```

---

### GET /voice/speakers
获取可用音色列表

**Response**
```json
{
  "speakers": [
    {
      "id": "zh_female_meilinvyou_emo",
      "name": "魅力女友",
      "gender": "female",
      "emotion_support": ["joy", "sadness", "love"]
    },
    {
      "id": "zh_female_tianmei_emo",
      "name": "甜美女神",
      "gender": "female",
      "emotion_support": ["joy", "love", "surprise"]
    }
  ]
}
```

---

### POST /voice/upload
上传自定义音色

**Request Body** (multipart/form-data)
| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | file | 音频文件 |
| `speaker_id` | string | 音色 ID |
| `figure_id` | string | 灵偶 ID（可选） |

**Response**
```json
{
  "success": true,
  "speaker_id": "custom_voice_001"
}
```

---

### POST /voice/precache
预缓存语音池

**Request Body**
```json
{
  "figure_id": "figure_001"
}
```

**Response**
```json
{
  "success": true,
  "precached_count": 58,
  "total_count": 58
}
```

---

### GET /voice/pool-status/{figure_id}
获取语音池状态

**Path Parameters**
| 参数 | 类型 | 说明 |
|------|------|------|
| `figure_id` | string | 灵偶 ID |

**Response**
```json
{
  "figure_id": "figure_001",
  "total": 58,
  "precached": 58,
  "ready": true
}
```

---

## 硬件（Hardware）

### POST /hardware/simulate
模拟硬件交互

**Request Body**
```json
{
  "figure_id": "figure_001",
  "action": "touch",
  "position": "head",
  "duration_ms": 1500
}
```

**Response**
```json
{
  "success": true,
  "led_effect": "pulse_pink",
  "response_text": "（轻抚）好舒服呀～",
  "response_audio_url": "/audio/precache_001.mp3"
}
```

---

### GET /hardware/system-voices
获取系统预置音效

**Response**
```json
{
  "sounds": [
    {
      "id": "power_on",
      "name": "开机音效",
      "url": "/audio/system/power_on.mp3"
    },
    {
      "id": "touch_head",
      "name": "摸头音效",
      "url": "/audio/system/touch_head.mp3"
    }
  ]
}
```

---

## 同步（Sync）

### GET /sync/status
获取同步状态

**Response**
```json
{
  "last_sync": "2026-06-18T10:00:00Z",
  "pending_events": 0,
  "sync_enabled": true
}
```

---

### POST /sync/push
推送同步数据

**Request Body**
```json
{
  "figure_id": "figure_001",
  "data": {
    "emotion_state": { ... },
    "interaction_count": 42
  }
}
```

**Response**
```json
{
  "success": true,
  "synced_at": "2026-06-18T10:00:00Z"
}
```
