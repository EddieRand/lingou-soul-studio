# 灵偶 Soul Companion

**AI 硬件伴侣软件核心 + H5 灵魂设计工作室**

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                      H5 Frontend (Soul Studio)                   │
│                   React + Tailwind CSS + Vite                    │
│  • 登录/注册 • 灵偶管理 • 灵魂档案编辑 • 语音通话 • 共同记忆     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (:8000)                      │
│  • 用户认证(JWT) • 灵偶引擎 • 轮次管理 • 记忆系统 • 同步契约     │
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
| 后端 | FastAPI + Python 3.11+（基线验证使用 3.12）+ Pydantic + JWT + bcrypt |
| 在线大脑 | 豆包 Doubao Ark API |
| 语音合成 | 火山引擎 Volcengine TTS API |
| 语音识别 | 火山引擎 Volcengine ASR API |
| 离线语音 | 本地预合成音频池 |
| 存储 | JSON 文件存储；用户数据按服务端认证身份隔离 |
| 认证 | 用户 JWT Bearer + 独立设备凭据 |

---

## 本地启动

### 后端

```bash
cd services/companion-server
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 生成一个私有 JWT 密钥，把输出填入 .env 的 LINGOU_JWT_SECRET
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
# 编辑 .env，填入：
#   LINGOU_JWT_SECRET（必填，至少 32 字节）
#   ARK_API_KEY
#   ARK_ENDPOINT_ID
#   VOLC_TTS_API_KEY
#   VOLC_TTS_APP_ID
#   VOLC_TTS_ACCESS_TOKEN

.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd apps/soul-studio-h5
npm ci
npm run dev
```

前端默认运行在 `http://localhost:3000`。

本轮可重复验证环境使用 Python 3.12.14、Node 22.23.2、npm 10.9.8。
无需真实账号、数据或模型密钥的检查方法见 [开发基线与隔离验证](docs/development-baseline.md)。

### 预置、配对与替代载体

底座在交付前离线生成二维码认领凭据和独立设备凭据：

```bash
cd services/companion-server
.venv/bin/python -B -m scripts.provision_base \
  --base-id BASE-DEVICE-001 \
  --data-dir /absolute/path/to/runtime-data
```

输出只显示一次。`qr_payload` 用于底座标签，`device_credential` 写入设备受保护配置。
两者不可互换，也不要写入仓库。用户登录 H5 后扫描二维码即可完成真实认领；
解绑会保留灵偶档案并切断设备事件及语音权限。第 11 步前已预置的底座需使用
`scripts.rotate_device_credential` 显式换发语音凭据。

最终自研硬件完成前，可用树莓派、迷你主机或旧电脑作为独立设备 MVP。它使用系统
麦克风和扬声器，不依赖 H5、浏览器、IDE 或串口桥。安装及自启动方式见
[替代载体独立设备 MVP](docs/portable-device-mvp.md)。

### 环境变量说明

| 变量名 | 说明 | 来源 |
|--------|------|------|
| `LINGOU_JWT_SECRET` | JWT 签名密钥，至少 32 字节且必须跨重启保持一致 | 本机随机生成，不提交 |
| `LINGOU_CORS_ORIGINS` | 允许跨域访问的前端来源，逗号分隔 | 默认只允许 localhost:3000 |
| `LINGOU_WARMUP_ON_STARTUP` | 是否在启动时调用模型预热 | 默认 `0`，显式设为 `1` 才启用 |
| `LINGOU_ENABLE_TEST_DEVICE_AUTH` | 是否开放测试底座及测试设备凭据入口 | 默认 `0`；只能用于开发验证 |
| `ARK_API_KEY` | 豆包 Ark API 密钥 | 火山引擎控制台 |
| `ARK_ENDPOINT_ID` | Ark 推理端点 ID | 火山引擎控制台 |
| `VOLC_TTS_API_KEY` | 火山 TTS API Key | 火山引擎控制台 |
| `VOLC_TTS_APP_ID` | 火山 TTS App ID | 火山引擎控制台 |
| `VOLC_TTS_ACCESS_TOKEN` | 火山 TTS Access Token | 火山引擎控制台 |

---

## 核心功能

### 认证与数据
- **用户账号系统**：用户名/密码注册与登录，刷新后向服务端恢复身份
- **统一身份边界**：除注册、登录和健康检查外，全部业务 HTTP 接口要求 JWT Bearer
- **语音连接认证**：H5 使用 60 秒单次票据，物理设备使用独立 `voice:stream` 凭据
- **统一数据归属**：角色、历史、同步和音频均从已认证身份推导 owner；跨账号访问统一拒绝
- **真实底座配对**：预置二维码认领、持久化解绑、设备凭据撤销与事件防重放
- **可靠创建激活**：创建请求幂等，角色保存和底座激活由可恢复事务一次完成
- **旧数据迁移**：运行时不自动认领旧版全局数据，只允许离线清点和人工确认的显式迁移
- **服务端同步契约**：按 owner 隔离的上传、下载和时间过滤；当前落在同一后端的
  `cloud_data.json`，尚未接入生产云存储

### 灵偶管理
- **创建灵偶**：名字和一句话设定即可完成；编辑页支持头像自动裁剪和气质推荐
- **灵魂档案编辑**：背景、性格特质、价值观、关系网、口头禅、禁忌等
- **音色库**：346 个音色，支持分类筛选和试听
- **删除灵偶**：确认弹窗

### 对话系统
- **双大脑引擎**：豆包 Ark 在线大脑 + 离线语音池
- **语音通话**：WebSocket 实时通话，ASR 语音识别，TTS 语音合成
- **流式回复**：逐句显示，逐句播放
- **打断检测**：barge-in 实时打断，防重复 finalize
- **轮次隔离**：每轮独立 ID 与取消令牌，旧回复不能污染新轮次
- **连接仲裁**：同一底座最新连接优先，旧连接明确退出且不抢回
- **前端通话生命周期**：统一释放媒体资源，权限失败可恢复，重连不清空历史
- **真实音频交付**：合成、传输、解码和终端播放分别确认；无音频时显示失败
- **声线试听**：候选声线在当前终端播放，确认后保存并回读校验
- **统一角色人设**：普通、流式和联网对话使用同一 persona prompt
- **统一轮次完成**：文字与语音共享交互计数、追踪 ID 和日志提交
- **可纠正共同记忆**：模型提出候选，用户确认后才进入对话；支持新增、修改和删除
- **稳定上下文**：最近 6 轮对话加最多 10 条确认事实，不使用易失的自动长摘要
- **一期单角色路径**：绑定后只需名字与一句话设定，创建完成直接开始交流
- **次日继续**：主页恢复当前角色、最近确认记忆，对话页恢复最近 6 轮
- **开发功能隔离**：模拟器、关系快进、脑模式和音色克隆默认关闭
- **独立设备协议**：替代载体直接上传 16 kHz PCM、播放 24 kHz PCM 并确认播放结果

### 后置养成能力
- 情绪衰减、冷落等级、关系进度和 streak 的历史实现仍保留
- 一期普通创建、对话和触摸默认不初始化或推进这些字段
- 相关调试入口默认关闭；只有重新确认产品目标后才作为独立版本启用

---

## 文档

- **项目计划**: [PLAN.md](PLAN.md) - 功能清单、开发进度、待办事项
- **嵌入式语音路线**: [docs/embedded-voice-best-practice-roadmap.md](docs/embedded-voice-best-practice-roadmap.md) - 火山方案借鉴任务、依赖和验收门槛
- **设备语音协议**: [docs/device-voice-protocol-v1.md](docs/device-voice-protocol-v1.md) - EV-01 能力协商、兼容规则和测量字段
- **语音基线证据**: [docs/validation/ev02-baseline-20260917/README.md](docs/validation/ev02-baseline-20260917/README.md) - EV-02 真实延迟、声学和 30 秒恢复结果
- **硬件 HAL**: [docs/hardware-hal.md](docs/hardware-hal.md) - EV-03 端口、生命周期、任务模型和板级隔离
- **非阻塞音频流水线**: [docs/validation/ev04-audio-pipeline-20260917/README.md](docs/validation/ev04-audio-pipeline-20260917/README.md) - EV-04 有界采播、取消隔离和待补实物证据
- **API 文档**: [API.md](API.md) - 完整接口说明
- **身份边界**: [docs/authentication.md](docs/authentication.md) - Bearer、WebSocket 票据与测试设备身份
- **数据归属**: [docs/data-ownership.md](docs/data-ownership.md) - owner 规则与离线迁移流程
- **第 04 步验收**: [docs/step04-validation.md](docs/step04-validation.md) - 配对、创建激活及验证证据
- **第 05 步验收**: [docs/step05-validation.md](docs/step05-validation.md) - 语音轮次、取消与并发验证
- **第 06 步验收**: [docs/step06-validation.md](docs/step06-validation.md) - 前端通话资源、权限与重连验证
- **独立设备固件**: [firmware/lingou_device_v1/README.md](firmware/lingou_device_v1/README.md) - 接线、配置、构建与协议
- **替代载体 MVP**: [docs/portable-device-mvp.md](docs/portable-device-mvp.md) - Linux/macOS 客户端与验收
- **最新 MVP 验证**: [docs/mvp-validation-20260916.md](docs/mvp-validation-20260916.md) - 13 项缺陷已关闭，当前仍有环境阻塞项
- **第 11 步阶段记录**: [docs/step11-validation.md](docs/step11-validation.md) - 旧阶段证据，已由最新复验更新结论
- **MVP 测试用例**: [docs/mvp-test-cases.md](docs/mvp-test-cases.md) - 120 条详细场景与[执行记录表](docs/mvp-test-execution.csv)

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
│       │   │   ├── sync.py      # 服务端同步快照接口
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
2. 启动前端（端口 3000）
3. 访问 `http://localhost:3000`，先注册账号或登录
4. 认领测试底座，创建第一个灵偶并体验对话功能
