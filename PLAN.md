# LINGOU - 灵偶项目计划

## 项目概述

灵偶是一款 AI 灵魂伴侣应用，用户可以创建、培养和与虚拟灵魂角色互动。核心功能包括语音对话、情感系统、关系进度和云同步。

## 技术栈

- **后端**: FastAPI + Python 3.9
- **前端**: React + TypeScript + TailwindCSS
- **数据库**: JSON 文件存储（用户数据按 user_id 分组）
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
- [x] 登录态持久化（localStorage）
- [x] 路由保护（未登录跳转登录页）
- [x] 首次登录新手引导（3 步整屏设计图 + 热区点击）

### 数据隔离
- [x] 数据按 user_id 分组存储
- [x] 旧数据自动迁移到用户目录
- [x] 向后兼容（不传 user_id 读取旧路径）

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
| auth | /api/auth/users | GET | 列出用户 |
| figures | /api/figures | GET | 列出灵偶 |
| figures | /api/figures | POST | 创建灵偶 |
| figures | /api/figures/{id} | GET | 获取灵偶详情 |
| figures | /api/figures/{id} | PUT | 更新灵偶 |
| figures | /api/figures/{id} | DELETE | 删除灵偶 |
| sync | /api/sync/upload | POST | 上传到云端 |
| sync | /api/sync/download | POST | 从云端下载 |
| sync | /api/sync/sync | POST | 全量同步 |
| sync | /api/sync/migrate | POST | 数据迁移 |
| voice | /api/voice/speakers | GET | 获取音色列表 |
| voice | /api/voice/generate | POST | 生成语音 |
| dialogue | /api/dialogue/text | POST | 文本对话 |
| asr | /api/asr/ws/{base_id} | WS | 语音通话 |

## 启动方式

### 后端
```bash
cd services/companion-server
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端
```bash
cd apps/soul-studio-h5
npm install
npm run dev
```

## 环境变量

后端需要在 `services/companion-server/.env` 中配置：
- 火山引擎 API Key（ASR/TTS）
- 豆包 API Key（对话）

## 数据存储结构

```
data/
├── users.json                  # 用户列表
├── bases/                      # 底座数据
├── figures/                    # 旧版灵偶（未登录用户）
├── user_data/
│   └── {user_id}/              # 用户专属数据
│       ├── figures/            # 灵偶数据
│       ├── dialogue_logs/      # 对话日志
│       ├── events/             # 事件日志
│       └── sync/               # 同步数据
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
3. 用户数据存储在 data/user_data/{user_id}/ 目录下
4. 首次登录会自动迁移旧数据到用户目录
5. 所有 API 请求自动带上 Authorization 头
