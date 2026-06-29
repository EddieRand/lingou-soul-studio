# LINGOU API 文档

## 基础信息

- **Base URL**: http://localhost:8000/api
- **认证方式**: JWT Bearer Token
- **格式**: JSON

## 认证接口

### 1. 用户注册

**POST** `/auth/register`

请求体:
```json
{
  "username": "string",    // 必填，用户名
  "email": "string",       // 必填，邮箱
  "password": "string"     // 必填，密码
}
```

响应:
```json
{
  "user_id": "uuid-string",
  "username": "string",
  "email": "string",
  "created_at": "datetime-string"
}
```

### 2. 用户登录

**POST** `/auth/login`

请求体 (application/x-www-form-urlencoded):
```
username=xxx&password=xxx
```

响应:
```json
{
  "access_token": "jwt-token-string",
  "token_type": "bearer",
  "user_id": "uuid-string",
  "username": "string"
}
```

### 3. 验证 Token

**GET** `/auth/verify`

请求头:
```
Authorization: Bearer <token>
```

响应:
```json
{
  "user_id": "uuid-string",
  "username": "string",
  "email": "string",
  "created_at": "datetime-string"
}
```

### 4. 列出用户

**GET** `/auth/users`

响应:
```json
{
  "users": [
    {
      "user_id": "uuid-string",
      "username": "string",
      "email": "string",
      "created_at": "datetime-string"
    }
  ]
}
```

---

## 灵偶管理接口

### 1. 列出灵偶

**GET** `/figures?user_id=<uuid>`

响应:
```json
[
  {
    "figure_id": "uuid-string",
    "name": "string",
    "avatar": "string",
    "archetype": "string",
    "relationship_level": "stranger|acquaintance|familiar|dependent|bonded",
    "mood": 0.0,
    "neglect_tier": 0,
    "streak": 0,
    "last_interaction_at": "datetime-string"
  }
]
```

### 2. 创建灵偶

**POST** `/figures`

请求体:
```json
{
  "figure_id": "uuid-string",
  "name": "string",
  "avatar": "string",
  "gender": "male|female|neutral",
  "archetype": "string",
  "user_id": "uuid-string"
}
```

### 3. 获取灵偶详情

**GET** `/figures/{figure_id}?user_id=<uuid>`

### 4. 更新灵偶

**PUT** `/figures/{figure_id}`

请求体:
```json
{
  "name": "string",
  "avatar": "string",
  "archetype": "string",
  "user_id": "uuid-string",
  "voice_profile": {...},
  "personality_profile": {...},
  "emotional_profile": {...}
}
```

### 5. 删除灵偶

**DELETE** `/figures/{figure_id}?user_id=<uuid>`

---

## 云同步接口

### 1. 上传数据

**POST** `/sync/upload`

请求体:
```json
{
  "user_id": "uuid-string",
  "figures": [],
  "dialogue_logs": [],
  "events": [],
  "last_sync_at": "datetime-string"
}
```

响应:
```json
{
  "success": true,
  "message": "Uploaded",
  "synced_at": "datetime-string",
  "figures_count": 0,
  "logs_count": 0,
  "events_count": 0,
  "conflicts": []
}
```

### 2. 下载数据

**POST** `/sync/download`

请求体:
```json
{
  "user_id": "uuid-string",
  "last_sync_at": "datetime-string"
}
```

响应:
```json
{
  "success": true,
  "figures": [],
  "dialogue_logs": [],
  "events": [],
  "server_time": "datetime-string"
}
```

### 3. 全量同步

**POST** `/sync/sync`

请求体: 同上传

响应:
```json
{
  "upload": {...},
  "download": {...},
  "message": "Full sync completed"
}
```

### 4. 数据迁移

**POST** `/sync/migrate`

请求体:
```json
{
  "user_id": "uuid-string"
}
```

响应:
```json
{
  "success": true,
  "message": "Migrated X figures",
  "migrated_count": 0
}
```

---

## 语音接口

### 1. 获取音色列表

**GET** `/voice/speakers`

查询参数:
- `include_ip`: boolean (default: false) - 是否包含 IP 仿音

响应:
```json
{
  "available": true,
  "configured_speaker": "string",
  "total": 330,
  "categories": [
    {
      "key": "female_角色扮演",
      "gender": "female",
      "category": "角色扮演",
      "speakers": [
        {
          "speaker_id": "string",
          "name": "string",
          "age_group": "string",
          "emotions": [],
          "demo_url": "string"
        }
      ]
    }
  ],
  "speakers": []
}
```

### 2. 生成语音

**POST** `/voice/generate`

请求体:
```json
{
  "text": "string",
  "speaker": "string",
  "figure_id": "string",
  "cache": true
}
```

响应:
```json
{
  "success": true,
  "audio_url": "string",
  "duration": 0.0
}
```

---

## 对话接口

### 1. 文本对话

**POST** `/dialogue/text`

请求体:
```json
{
  "figure_id": "string",
  "user_input": "string",
  "user_id": "uuid-string"
}
```

响应:
```json
{
  "reply": "string",
  "figure_id": "string",
  "brain_mode": "online|local",
  "tokens_used": 0
}
```

---

## 事件接口

### 1. 获取事件日志

**GET** `/events/{figure_id}?user_id=<uuid>&limit=10`

响应:
```json
[
  {
    "event_id": "uuid-string",
    "figure_id": "uuid-string",
    "type": "string",
    "description": "string",
    "timestamp": "datetime-string",
    "metadata": {}
  }
]
```

### 2. 创建事件

**POST** `/events`

请求体:
```json
{
  "figure_id": "string",
  "type": "string",
  "description": "string",
  "metadata": {},
  "user_id": "uuid-string"
}
```

---

## 语音通话接口

### WebSocket 语音通话

**WS** `/asr/ws/{base_id}`

消息格式:
```json
{
  "type": "start_recording" | "stop_recording" | "speaking",
  "data": {...}
}
```

---

## 请求头规范

所有需要认证的接口需携带:
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

## 错误响应格式

```json
{
  "detail": "错误描述"
}
```

常见错误码:
- 401: 未授权（Token 无效或过期）
- 404: 资源不存在
- 400: 请求参数错误
- 500: 服务器内部错误
