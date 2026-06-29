# 灵偶 Soul Companion

**情感 AI 硬件伴侣 + H5 灵魂设计工作室**

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                      H5 Frontend (Soul Studio)                   │
│                   React + Tailwind CSS + Vite                    │
│  • 登录/注册 • 灵偶管理 • 灵魂档案编辑 • 语音通话 • 云同步       │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (:8000)                      │
│  • 用户认证(JWT) • 灵偶引擎 • 情绪系统 • 双脑路由 • 云同步       │
└───────┬─────────────────┬──────────────┬────────────────────────┘
        │                 │              │
        ▼                 ▼              ▼
┌───────────────┐ ┌───────────────┐ ┌─────────────────┐
│  豆包 Ark     │ │  火山 TTS     │ │   离线语音池     │
│  (在线大脑)   │ │ (情感音色)    │ │  (Precache)     │
│               │ │               │ │                 │
│  • 实时对话   │ │  • 流式合成   │ │  • 58句/灵偶   │
│  • 复杂推理   │ │  • 346种音色  │ │  • 即时播放     │
│  • 知识问答   │ │  • 11种气质   │ │  • 情绪匹配     │
└───────────────┘ └───────────────┘ └─────────────────┘
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + Tailwind CSS + Vite + React Router + Context API |
| 后端 | FastAPI + Python 3.10+ + Pydantic + JWT + bcrypt |
| 在线大脑 | 豆包 Doubao Ark API |
| 语音合成 | 火山引擎 Volcengine TTS API |
| 语音识别 | 火山引擎 Volcengine ASR API |
| 离线语音 | 本地预合成音频池 |
| 存储 | JSON 文件存储（用户数据按 user_id 隔离） |
| 认证 | JWT Bearer Token |

---

## 本地启动

### 后端

```bash
cd services/companion-server
cp .env.example .env
# 编辑 .env，填入：
#   ARK_API_KEY
#   ARK_ENDPOINT_ID
#   VOLC_TTS_API_KEY
#   VOLC_TTS_APP_ID
#   VOLC_TTS_ACCESS_TOKEN

python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd apps/soul-studio-h5
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`

### 环境变量说明

| 变量名 | 说明 | 来源 |
|--------|------|------|
| `ARK_API_KEY` | 豆包 Ark API 密钥 | 火山引擎控制台 |
| `ARK_ENDPOINT_ID` | Ark 推理端点 ID | 火山引擎控制台 |
| `VOLC_TTS_API_KEY` | 火山 TTS API Key | 火山引擎控制台 |
| `VOLC_TTS_APP_ID` | 火山 TTS App ID | 火山引擎控制台 |
| `VOLC_TTS_ACCESS_TOKEN` | 火山 TTS Access Token | 火山引擎控制台 |

---

## 核心功能

### 认证与数据
- **用户账号系统**：注册/登录/登出，JWT Token 认证
- **数据隔离**：用户数据按 user_id 分组存储，多用户互不干扰
- **云同步**：数据上传/下载/全量同步，冲突解决
- **数据迁移**：首次登录自动迁移旧数据到用户目录

### 灵偶管理
- **创建灵偶**：支持头像上传、气质推荐（按性别匹配）
- **灵魂档案编辑**：背景、性格特质、价值观、关系网、口头禅、禁忌等
- **音色库**：346 个音色，支持分类筛选和试听
- **删除灵偶**：确认弹窗

### 对话系统
- **双大脑引擎**：豆包 Ark 在线大脑 + 离线语音池
- **语音通话**：WebSocket 实时通话，ASR 语音识别，TTS 语音合成
- **流式回复**：逐句显示，逐句播放
- **打断检测**：barge-in 实时打断，防重复 finalize

### 情感系统
- **情绪衰减**：时间流逝影响情绪值
- **冷落等级**：neglect tier 系统
- **关系进度**：陌生 → 熟悉 → 依赖 → 羁绊
- **连续陪伴天数**：streak 记录

---

## 文档

- **项目计划**: [PLAN.md](PLAN.md) - 功能清单、开发进度、待办事项
- **API 文档**: [API.md](API.md) - 完整接口说明

---

## 目录结构

```
LINGOU/
├── apps/
│   └── soul-studio-h5/          # H5 前端应用
│       ├── src/
│       │   ├── components/      # UI 组件
│       │   ├── context/         # React Context (AuthContext)
│       │   ├── pages/           # 页面组件
│       │   ├── services/        # API 服务
│       │   └── App.tsx          # 路由配置（含路由保护）
│       └── package.json
├── services/
│   └── companion-server/        # 后端服务
│       ├── app/
│       │   ├── api/             # API 路由
│       │   │   ├── auth.py      # 用户认证
│       │   │   ├── figures.py   # 灵偶管理
│       │   │   ├── sync.py      # 云同步
│       │   │   ├── asr.py       # 语音通话
│       │   │   └── voice.py     # 语音合成
│       │   ├── core/            # 核心逻辑
│       │   └── main.py          # 应用入口
│       └── data/
│           ├── store.py         # 数据存储
│           ├── user_data/       # 用户数据目录
│           └── voice_library.json
├── data/                        # 共享数据
│   ├── archetypes/              # 气质模板
│   └── audio_cache/             # 音频缓存
├── PLAN.md                      # 项目计划
├── API.md                       # API 文档
└── README.md                    # 本文件
```

---

## 快速体验

1. 启动后端服务（端口 8000）
2. 启动前端（端口 5173）
3. 访问 `http://localhost:5173`，先注册账号或登录
4. 创建第一个灵偶，体验对话功能
