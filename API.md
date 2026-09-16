# 灵偶 API

本地 Base URL：`http://localhost:8000/api`

交互式接口定义以服务运行时的 `http://localhost:8000/docs` 为准。本文记录当前认证边界、数据归属规则和主要接口，避免客户端依赖已经删除的兼容入口。

## 认证与数据归属

- `POST /auth/register` 和 `POST /auth/login` 允许匿名访问；其余用户 HTTP 接口要求 `Authorization: Bearer <access_token>`。
- `POST /device/events` 和设备语音 WebSocket 只接受
  `Authorization: Device <credential>`，不能使用用户 Bearer。
- 业务数据的 owner 只取自服务端验证后的 JWT `sub` 或设备凭据。请求不得传入 `user_id`、`owner_id`、`owner_user_id` 或 `bound_user_id`。
- 资源不存在和资源属于其他账号都返回 `404`，客户端不能据此探测其他账号的数据。
- 旧版数据（包括已分入用户目录但没有规范 owner 的记录）不会在登录或访问时自动认领；只能使用离线迁移工具和人工确认的清单处理。详见 [统一数据归属](docs/data-ownership.md)。

资源 ID 只允许 1 至 128 个 ASCII 字母、数字、下划线或连字符，首字符必须是字母或数字。

## 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/auth/register` | 注册；JSON 包含 `username`、`email`、`password` |
| `POST` | `/auth/login` | OAuth2 form 登录；返回 24 小时 access token |
| `GET` | `/auth/verify` | 返回当前服务端用户 |
| `POST` | `/auth/logout` | 确认客户端退出；客户端负责删除 token |
| `POST` | `/auth/ws-ticket` | 为当前用户拥有的 `base_id` 签发 60 秒、单次 ASR 票据 |

## 底座

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/bases` | 列出当前用户拥有的底座及其当前灵偶 |
| `POST` | `/bases/pair` | 使用预置二维码认领底座；JSON：`{"qr_token":"lingou://pair?token=..."}` |
| `GET` | `/bases/{base_id}` | 获取当前用户拥有的底座 |
| `POST` | `/bases/{base_id}/unbind` | 持久化解绑；保留灵偶档案，清除底座与当前灵偶关联 |
| `POST` | `/bases/{base_id}/active-figure` | 激活当前用户的灵偶；JSON：`{"figure_id":"..."}` |
| `POST` | `/bases/{base_id}/device-credential/revoke` | 撤销物理设备事件及语音凭据 |
| `POST` | `/bases/test-bases` | 仅开发验证；创建测试底座 |
| `POST` | `/bases/{base_id}/test-device-credential` | 仅开发验证；轮换事件及语音凭据 |

两个测试入口只有在 `LINGOU_ENABLE_TEST_DEVICE_AUTH=1` 时可用。真实底座必须先用
`scripts/provision_base.py` 离线预置；二维码认领凭据和设备凭据彼此独立，明文只在预置时返回一次。
第 11 步前已预置的底座需要通过 `scripts/rotate_device_credential.py` 显式换发
`events:write`、`voice:stream` 凭据，旧凭据随即失效。
一期每个账号只允许绑定一个底座；重复扫描自己的二维码幂等成功，其他账号不能抢占。

## 灵偶

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/figures` | 列出当前用户的灵偶 |
| `POST` | `/figures` | 创建灵偶 |
| `GET` | `/figures/{figure_id}` | 获取当前用户的灵偶 |
| `PUT` | `/figures/{figure_id}` | 更新当前用户的灵偶 |
| `DELETE` | `/figures/{figure_id}` | 删除灵偶，并清理当前用户底座上的激活引用 |
| `PUT` | `/figures/{figure_id}/character` | 保存角色档案 |
| `GET` | `/figures/{figure_id}/memories` | 查看已确认事实与待确认候选 |
| `POST` | `/figures/{figure_id}/memories` | 手动新增一条已确认事实 |
| `POST` | `/figures/{figure_id}/memories/{memory_id}/confirm` | 确认模型候选 |
| `PUT` | `/figures/{figure_id}/memories/{memory_id}` | 修改记忆内容 |
| `DELETE` | `/figures/{figure_id}/memories/{memory_id}` | 删除记忆并阻止旧内容自动复活 |
| `POST` | `/figures/{figure_id}/simulate-absence` | 开发工具：模拟离开 |
| `POST` | `/figures/{figure_id}/boost-relationship` | 开发工具：快进关系 |

创建请求必须包含 `name` 和 `figure_type`，可选字段包括 `avatar_url`、`description`、`wake_names`、
`soul_profile`、`voice_profile` 和触摸反应配置。普通创建流程还应携带：

- `creation_request_id`：同一创建意图在网络重试时保持不变，服务端只创建一个灵偶。
- `activate_base_id`：由当前已绑定底座显式传入；创建与激活使用同一可恢复事务。

每个灵偶最多保留 10 条已确认事实。模型提取只生成待确认候选，候选不会进入对话 prompt；
确认或手动新增后才会在下一轮使用。修改和删除按稳定 `memory_id` 执行，旧内容会记录不可见
指纹，避免后续自动提取再次写回。所有操作只接受当前 Bearer 用户拥有的灵偶。

## 对话、事件与硬件

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/dialogue/wake` | 在自有底座上触发唤醒 |
| `POST` | `/dialogue/text` | 在自有底座上进行文本对话 |
| `GET` | `/dialogue/state?base_id=...` | 查询自有底座的对话状态 |
| `GET` | `/dialogue/logs` | 查询当前用户的对话记录，可按自有灵偶过滤 |
| `POST` | `/dialogue/memory-summary` | 生成自有灵偶的记忆摘要 |
| `POST` | `/dialogue/interrupt` | 停止自有底座当前灵偶的播放 |
| `POST` | `/dialogue/audio` | 非流式 ASR 占位接口；当前返回 `501` |
| `POST` | `/events` | 开发工具：浏览器模拟事件 |
| `GET` | `/events/logs` | 查询当前用户事件，可按自有底座或灵偶过滤 |
| `POST` | `/hardware/simulate` | 开发工具：浏览器硬件模拟 |
| `POST` | `/device/events` | 设备上报；生产凭据要求 `event_type`、唯一 `event_id` 和带时区的 `occurred_at` |

生产设备事件使用预置的 `Authorization: Device <credential>`。同一 `event_id` 只接受一次，
服务器时间前后超过 5 分钟的事件会按重放或过期请求拒绝。开发测试凭据仍可省略事件身份字段。

## 语音与大脑

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/voice/upload` | 为自有灵偶上传参考音频 |
| `POST` | `/voice/generate` | 兼容接口：为自有灵偶生成音频文件，不在服务器播放 |
| `POST` | `/voice/preview` | 返回认证音频字节，供当前终端试听指定候选或角色声线 |
| `POST` | `/voice/precache` | 为自有灵偶预生成语音池 |
| `GET` | `/voice/pool-status/{figure_id}` | 查询自有灵偶语音池 |
| `POST` | `/voice/design` | 为自有灵偶设计音色 |
| `GET` | `/voice/speakers` | 列出音色 |
| `POST` | `/voice/clone/start` | 为自有灵偶启动声音克隆 |
| `GET` | `/voice/clone/status?figure_id=...` | 查询自有灵偶克隆状态 |
| `GET` | `/brain/status?base_id=...` | 查询大脑状态；传底座时校验归属 |
| `POST` | `/brain/mode?base_id=...` | 设置自有底座的大脑模式 |
| `GET` | `/asr/status` | 查询 ASR 配置状态 |

`/voice/preview` 使用 `speaker` 明确指定候选声线；试听角色当前声线时传 `figure_id`。
响应头返回实际 speaker、引擎、来源和合成时间。没有可播放字节时返回
`VOICE_AUDIO_UNAVAILABLE`，不会调用服务器本地扬声器。

ASR WebSocket 在二进制音频前发送 `audio_output/synthesized` 元数据，传输完成后发送
`audio_output/transferred`。客户端以 `audio_playback` 回传 `decoded`、
`playback_started`、`playback_completed` 或 `playback_failed`，均绑定原
`session_id`、`turn_id` 和 `audio_id`。

独立设备载体连接 `/asr/device-stream`，上行 16 kHz 单声道 `s16le` PCM；下行使用
24 kHz 单声道 `s16le` PCM，每个二进制帧不超过 4096 字节。每个二进制帧前都有
`audio_chunk` 描述。设备可发送 `cancel_turn` 中断当前轮，仍需对已开始的音频回传
`playback_failed`。回执只接受
`decoded -> playback_started -> playback_completed|playback_failed` 的顺序，
重复阶段幂等，乱序或矛盾终态不改变轮次结果。

文字、实时语音和上传音频最终都进入同一个对话核心。成功响应与对话日志包含
`session_id` 和 `turn_id`；关系进度、交互次数、情绪和日志只在核心完成一次，
传输层不得重复更新。

在线普通回复、流式回复和联网搜索共用同一 persona prompt。角色保持设定口吻，
但在被询问时必须如实说明其为 AI 驱动的灵偶，不能伪装真人或否认 AI 身份。

当前上下文使用最近 6 个完整对话轮次及最多 10 条已确认事实。没有持久 turn 游标的旧自动
长摘要已停用，避免日志超过 100 条后停更，也避免纠正或删除的旧事实从摘要重新进入 prompt。

模拟离开、关系快进、浏览器事件、硬件模拟、脑模式写入、音色上传/克隆和系统声线枚举默认
返回 `404`。仅本地开发环境同时显式设置 `LINGOU_ENABLE_DEV_TOOLS=1` 时开放。
关系等级、streak、冷落和触摸递进默认不运行；若需复现旧演示行为，额外设置
`LINGOU_ENABLE_DEFERRED_GAMEPLAY=1`。

## 同步

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/sync` | 获取当前用户的同步队列 |
| `POST` | `/sync` | 为当前用户的灵偶加入同步项 |
| `POST` | `/sync/flush` | 刷新当前用户的同步队列 |
| `POST` | `/sync/upload` | 上传当前用户的数据快照 |
| `POST` | `/sync/download?last_sync_at=...` | 下载当前用户的数据快照 |
| `POST` | `/sync/sync` | 上传后下载 |

同步请求不接受任何 owner 字段。在线 `/sync/migrate` 已删除，避免登录用户自动认领来源不明的旧数据。

## ASR WebSocket

先用 Bearer 调用 `/auth/ws-ticket` 并传入自有 `base_id`，再连接：

```text
ws://localhost:8000/api/asr/stream?base_id=<base_id>
```

`Sec-WebSocket-Protocol` 同时提供 `lingou.asr.v1` 和 `lingou.ticket.<ticket>`。票据只可使用一次；归属或底座不匹配关闭码为 `4403`，重放为 `4409`，其他认证错误为 `4401`。

同一底座只允许一个活动语音连接，策略为 `newest_connection_wins`。新连接建立后，
旧连接先收到 `session_replaced`，随后以 `4410` 关闭。旧连接不得自动重连。

独立设备载体不使用用户票据，连接：

```text
ws://localhost:8000/api/asr/device-stream
```

请求头为 `Authorization: Device <credential>`，子协议为
`lingou.device.voice.v1`。设备凭据必须具有 `voice:stream`，且底座已有 owner 和
当前角色；否则分别以 `4401` 或 `4404` 关闭。生产环境必须使用带 CA 校验的 WSS。
存量连接的每条上行也会重新校验凭据及 base/owner；解绑、撤销或轮换后以 `4401`
关闭，不能继续向 ASR 发送。`status=listening` 完成 PCM 协商，
`status=ready` 表示上游 ASR 已连接。一期替代载体客户端为
`hardware_adapter.portable_voice_client`。

每个服务端消息包含 `session_id`；从识别完成开始的轮次消息还包含 `turn_id` 和
`turn_sequence`。主要消息如下：

| 类型 | 说明 |
|---|---|
| `final` | 本轮识别文本已确定 |
| `reply_chunk` | 当前轮次的一段回复文本 |
| 二进制帧 | 当前轮次的一段音频 |
| `reply` | 当前轮次完整回复 |
| `stop_audio` / `turn_cancelled` | 当前轮次被新输入、挂断或连接替换取消 |
| `turn_metrics` | 识别完成、回复启动、首段文本、首段音频、完成或取消的相对毫秒时间 |

服务端只允许当前 `turn_id` 发送文本、音频和最终回复。被取消的模型线程即使晚到，也不能再发送、
写入角色状态或追加对话记录。语音产生的对话日志保存对应 `session_id` 和 `turn_id`。

## 常见错误

| 状态码 | 含义 |
|---|---|
| `400` | 业务输入无效 |
| `401` | 用户或设备凭据缺失、无效或过期 |
| `404` | 资源不存在或当前身份不可访问 |
| `409` | 底座已被占用、账号已有底座、创建/激活事务失败或设备事件重放 |
| `422` | 请求结构、资源 ID 或同步归属字段不合法 |
| `501` | 本地能力尚未配置或实现 |
