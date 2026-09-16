# LINGOU - 灵偶项目计划

## 项目概述

灵偶是一款 AI 灵魂伴侣应用，用户可以创建、培养和与虚拟灵魂角色互动。核心功能包括语音对话、情感系统、关系进度和云同步。

## 技术栈

- **后端**: FastAPI + Python 3.11+（当前基线验证使用 3.12）
- **前端**: React + TypeScript + TailwindCSS
- **数据库**: JSON 文件存储；用户数据按服务端认证身份隔离
- **认证**: JWT + bcrypt
- **语音**: 火山引擎 TTS/ASR

## 目录结构

```
LINGOU/
├── apps/
│   └── soul-studio-h5/          # H5 前端应用
│       ├── src/
│       │   ├── components/      # UI 组件
│       │   ├── context/         # React Context
│       │   ├── pages/           # 页面组件
│       │   ├── services/        # API 服务
│       │   ├── App.tsx          # 路由配置
│       │   ├── main.tsx         # 入口文件
│       │   └── index.css        # 全局样式
│       └── package.json
├── services/
│   └── companion-server/        # 后端服务
│       ├── app/
│       │   ├── api/             # API 路由
│       │   │   ├── auth.py      # 用户认证
│       │   │   ├── figures.py   # 灵偶管理
│       │   │   ├── sync.py      # 云同步
│       │   │   ├── asr.py       # 语音通话
│       │   │   └── ...
│       │   ├── core/            # 核心逻辑
│       │   │   ├── dialogue_engine.py  # 对话引擎
│       │   │   ├── online_brain.py     # 在线大脑
│       │   │   └── ...
│       │   └── main.py          # 应用入口
│       ├── data/
│       │   ├── store.py         # 数据存储
│       │   ├── user_data/       # 用户数据目录
│       │   └── voice_library.json
│       └── requirements.txt
├── data/                        # 共享数据
│   ├── archetypes/              # 气质模板
│   ├── audio_cache/             # 音频缓存
│   └── ...
├── PLAN.md                      # 本文件
├── API.md                       # API 文档
└── README.md
```

## 已完成功能

### 认证系统
- [x] 用户注册/登录/登出
- [x] JWT Token 认证
- [x] 密码加密（bcrypt）
- [x] 登录态恢复（服务端 verify；临时故障可重试）
- [x] 全部业务 HTTP 路由严格认证
- [x] ASR WebSocket 短期一次性票据
- [x] 路由保护（身份确认前不展示或误跳）
- [x] 首次登录新手引导（3 步整屏设计图 + 热区点击）

### 数据归属
- [x] 角色、事件、历史、同步、上传音频从已认证身份推导 owner
- [x] 阻止 A 用户读取、修改、激活或同步 B 用户资源
- [x] 底座与 WebSocket 票据在签发和消费时校验 owner
- [x] 同账号、同角色 ID 的缓存与播放状态使用 owner 隔离键
- [x] 旧数据使用离线清点、显式清单、dry-run、原子写入和迁移账本
- [x] 音色克隆参考音频限制在当前账号与当前角色的上传目录
- [x] 迁移账本阻止同一源或目标通过新清单重复分配
- [x] 第 03 步归属验收：后端及串口桥 60 项测试、前端构建通过
- [x] 真实二维码配对、持久化解绑、凭据吊销与事件防重放（第 04 步）
- [x] 幂等创建与可恢复的创建/激活事务（第 04 步）
- [x] 第 04 步验收：67 项 Python/硬件测试与真实浏览器配对流程通过

### 云同步
- [x] 上传本地数据到云端
- [x] 从云端下载数据
- [x] 全量同步（上传+下载）
- [x] 冲突解决（时间戳比对）

### 灵偶管理
- [x] 创建灵偶（支持头像上传）
- [x] 编辑灵偶（灵魂档案、音色等）
- [x] 删除灵偶（确认弹窗）
- [x] 气质推荐（按性别匹配）
- [x] 音色库浏览（346 个音色，分类筛选）

### 语音通话
- [x] WebSocket 实时通话
- [x] ASR 语音识别
- [x] TTS 语音合成
- [x] 流式回复（逐句显示）
- [x] 打断检测（barge-in）
- [x] 防重复 finalize（echo 抑制）
- [x] 单底座最新连接优先，旧连接使用 4410 退出
- [x] 独立 session/turn、取消传播和迟到结果隔离
- [x] 语音轮次关键时间记录及对话日志追踪 ID
- [x] 前端通话生命周期控制器统一持有媒体、Socket、音频与重连资源
- [x] 挂断/卸载完整释放、权限拒绝可重试、重连保留可见历史
- [x] 通话音频区分合成、传输、解码、播放开始与播放完成
- [x] 客户端播放回执进入同一 session/turn 指标，取消后停止并忽略迟到播放
- [x] 无可交付音频时显式失败，不回退到服务器扬声器伪装成功
- [x] 候选声线在当前终端独立试听，确认保存后服务端回读一致
- [x] 第 07 步验收：81 项 Python/硬件测试、15 项前端音频探针及真实 Chrome 发声通过
- [x] 单一 persona builder 覆盖一期角色设定、表达、关系与知识边界
- [x] 角色口吻下透明说明 AI 身份，不再要求否认 AI
- [x] 文字、语音和上传音频共用 turn ID、关系进度、情绪与日志完成逻辑
- [x] 移除开发期固定称呼 Eddie，角色编辑保存后回读并进入下一轮 prompt
- [x] 第 08 步验收：90 项 Python/硬件测试、真实模型人设对照及浏览器编辑回读通过

### 共同记忆
- [x] 每个灵偶最多保留 10 条用户已确认事实
- [x] 模型在回复完成后异步生成候选，不阻塞首句
- [x] 候选确认、手动新增、修改和二次确认删除
- [x] 纠正/删除墓碑阻止旧事实被自动重新提取
- [x] 原子记忆更新与对话事务合并，避免并发覆盖
- [x] 仅已确认事实进入下一轮 persona prompt
- [x] 固定最近 6 轮历史，停用无持久游标的自动长摘要
- [x] 第 09 步验收：98 项 Python/硬件测试及浏览器记忆 CRUD 通过

### 一期主路径
- [x] 首页只展示一个当前灵偶，并提供继续交流、共同记忆和编辑入口
- [x] 首次流程收敛为绑定底座、名字、一句话设定和默认声线
- [x] 创建草稿及幂等 ID 按账号持久化，刷新或关闭后可恢复
- [x] 创建成功直接进入交流页，次日返回恢复当前角色、记忆和最近对话
- [x] 模拟器、关系快进、脑模式、克隆、多角色切换和触摸台词退出正常路径
- [x] 调试写接口默认返回 404，仅显式开发开关可启用
- [x] 日常对话和触摸不再执行关系、streak、冷落或触摸递进规则
- [x] 第 10 步验收：102 项 Python/硬件测试、23 项前端探针及完整浏览器路径通过

### 替代载体独立设备 MVP（第 11 步，软件修复完成，环境验收待补）
- [x] 设备凭据增加独立 `voice:stream` 权限，不复用用户 Bearer
- [x] 设备直接连接 ASR WebSocket，复用底座当前角色、对话轮次和共同记忆
- [x] 16 kHz `s16le` PCM 上行、24 kHz `s16le` PCM 分帧下行及播放回执
- [x] H5 与设备沿用单底座最新连接优先，显式取消传播到原轮次
- [x] Linux/macOS 通用客户端使用真实系统麦克风和扬声器，不依赖 H5、IDE 或串口桥
- [x] 修复取消后迟到音频、旧控制帧污染、撤权后存量连接继续传输
- [x] 修复正常关闭重连风暴、资源清理、会话健康状态和慢声卡控制阻塞
- [x] 提供 systemd 与 launchd 开机自启动模板，凭据保存在仓库外环境文件
- [x] 自动声学闭环使用真实扬声器/麦克风完成，连接与资源正常退出
- [ ] 真人连续 3 轮及 T3 独立载体环境验收
- [x] 隔离的真实 ASR→确认记忆→Ark→TTS→PCM 回执链路通过
- [x] 13 项缺陷复验：API 19/19、协议 28/28、会话 9/9，已知失败清零
- [ ] 完整 MVP 环境验收：当前 47 条通过、0 条失败、63 条阻塞

### 最终自研硬件（后置，不属于第 11 步通过门槛）
- [x] DNESP32S3 参考固件保持 LED=18、FSR=16、Mic=5/7/4、Speaker=6/15/17
- [x] 参考固件启动红闪 3 次、网络故障本地提示、空闲功放输出归零并编译通过
- [ ] 最终载体确定后验证麦克风阵列、扬声器/腔体、回声消除、底噪和触摸交互
- [ ] 最终载体验证功耗、散热、续航、结构和量产可靠性

### 情感系统
- [x] 情绪衰减（时间流逝影响情绪）
- [x] 冷落等级（neglect tier）
- [x] 关系进度（陌生→熟悉→依赖→羁绊）
- [x] 连续陪伴天数（streak）

## 进行中

- [ ] 头像上传后裁剪优化
- [ ] 云同步增量更新（只同步变更）
- [ ] 比赛 H5 DEMO 线上部署与扫码验收

## 待开发

### 优先级高
- [ ] 多设备同步状态提示
- [ ] 账号安全（密码找回）
- [ ] 数据备份/导出

### 优先级中
- [ ] 社交分享（灵偶展示）
- [ ] 语音克隆优化
- [ ] 离线模式增强

### 优先级低
- [ ] 多语言支持
- [ ] 主题切换
- [ ] 数据统计分析

## API 接口清单

| 模块 | 接口 | 方法 | 说明 |
|------|------|------|------|
| auth | /api/auth/register | POST | 用户注册 |
| auth | /api/auth/login | POST | 用户登录 |
| auth | /api/auth/verify | GET | 验证 Token |
| auth | /api/auth/logout | POST | 客户端退出确认 |
| auth | /api/auth/ws-ticket | POST | 申请一次性 ASR 票据 |
| bases | /api/bases | GET | 列出当前用户底座 |
| bases | /api/bases/pair | POST | 扫码认领预置底座 |
| bases | /api/bases/{id} | GET | 获取当前用户底座 |
| bases | /api/bases/{id}/unbind | POST | 持久化解绑底座 |
| bases | /api/bases/{id}/active-figure | POST | 激活当前用户灵偶 |
| device | /api/device/events | POST | 独立设备凭据上报防重放事件 |
| asr | /api/asr/device-stream | WS | 独立设备载体 PCM 语音通道 |
| figures | /api/figures | GET | 列出灵偶 |
| figures | /api/figures | POST | 创建灵偶 |
| figures | /api/figures/{id} | GET | 获取灵偶详情 |
| figures | /api/figures/{id} | PUT | 更新灵偶 |
| figures | /api/figures/{id} | DELETE | 删除灵偶 |
| sync | /api/sync/upload | POST | 上传到云端 |
| sync | /api/sync/download | POST | 从云端下载 |
| sync | /api/sync/sync | POST | 全量同步 |
| voice | /api/voice/speakers | GET | 获取音色列表 |
| voice | /api/voice/generate | POST | 生成语音 |
| dialogue | /api/dialogue/text | POST | 文本对话 |
| asr | /api/asr/stream?base_id={base_id} | WS | 使用一次性短票据进行语音通话 |

## 启动方式

### 后端
```bash
cd services/companion-server
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 先在 .env 中配置至少 32 字节且跨重启稳定的 LINGOU_JWT_SECRET
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端
```bash
cd apps/soul-studio-h5
npm ci
npm run dev
```

## 环境变量

后端需要在 `services/companion-server/.env` 中配置：
- JWT 签名密钥 `LINGOU_JWT_SECRET`（必填，至少 32 字节，不提交）
- 火山引擎 API Key（ASR/TTS）
- 豆包 API Key（对话）

## 数据存储结构

```
data/
├── users.json                  # 用户列表
├── bases/                      # 带 schema_version 与 owner 的底座索引
├── figures/                    # 旧版全局数据，仅供离线迁移清点
├── user_data/
│   └── {user_id}/              # 用户专属数据
│       ├── figures/            # 灵偶数据
│       ├── dialogue_logs/      # 对话日志
│       ├── events/             # 事件日志
│       ├── sync/               # 同步队列与云端快照
│       └── voice_uploads/      # 用户上传的参考音频
├── archetypes/                 # 气质模板
├── voice_library.json          # 音色库
└── audio_cache/                # 音频缓存
```

## 开发规范

- **代码风格**: Python 使用 PEP8，TypeScript 使用标准格式
- **提交规范**: 每次提交对应一个功能/修复，使用清晰的 commit message
- **测试**: 后端 API 可用 curl 测试，前端页面手动测试
- **文档**: 重要功能变更更新 PLAN.md

## 注意事项

1. 后端服务使用 --reload 模式，代码修改会自动重启
2. 前端使用 Vite，修改会自动热更新
3. 运行时不会读取旧版全局角色、历史和同步数据，也不会按首次访问自动认领
4. 旧数据只能按 docs/data-ownership.md 的离线流程迁移；正式执行前必须在完整副本上验收
5. 前端业务 HTTP 请求通过统一客户端自动带上 Authorization 头
