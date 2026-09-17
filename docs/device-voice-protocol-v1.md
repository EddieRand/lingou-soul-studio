# LINGOU 设备语音协议 v1 能力协商

- 状态：EV-01 设计冻结，运行时协商尚未实现
- 子协议：`lingou.device.voice.v1`
- 端点：`WS(S) /api/asr/device-stream`
机器合同：[`contracts/device-voice-v1.contract.json`](contracts/device-voice-v1.contract.json)

## 1. 目标与范围

本文在不破坏现有设备语音协议的前提下，定义可选的媒体能力协商。它为后续 Opus、
全双工声学前端和 RTC PoC 提供稳定边界，但不表示这些能力当前已经实现或启用。

本次设计不改变：

- 设备使用 `Authorization: Device <credential>` 鉴权；
- 服务端根据凭据确定 owner 和 base，根据 base 确定当前 figure；
- 服务端生成 `session_id`、`turn_id` 和 `audio_id`；
- 当前 16 kHz PCM 上行、24 kHz PCM 下行继续作为兼容基线；
- 取消、迟到隔离、播放回执和最新连接优先规则；
- persona、共同记忆、对话提交和 H5 行为。

## 2. 规范用语

文中的“必须”“不得”是协议约束；“可以”表示可选能力。客户端包括 Linux/macOS
替代载体和最终硬件，服务端指 LINGOU 应用服务端，而不是 RTC 供应商服务。

## 3. 当前兼容基线

旧客户端只需要完成现有握手：

```http
Authorization: Device BASE-DEVICE-001.<secret>
Sec-WebSocket-Protocol: lingou.device.voice.v1
```

服务端认证通过后立即发送：

```json
{
  "type": "status",
  "status": "listening",
  "session_id": "<server-generated>",
  "connection_policy": "newest_connection_wins",
  "client_kind": "device",
  "audio_format": "pcm",
  "audio_sample_rate": 24000
}
```

兼容 profile 固定为 `ws-pcm-s16le-v1`：

| 方向 | 编码 | 采样率 | 声道 | 帧约束 |
|---|---|---:|---:|---|
| 设备上行 | PCM signed 16-bit little-endian | 16000 Hz | 1 | 20 ms，640 字节 |
| 设备下行 | PCM signed 16-bit little-endian | 24000 Hz | 1 | 每帧不超过 4096 字节 |

旧客户端不发送 `device_hello` 时，服务端必须继续使用该 profile。当前运行时代码仍只
支持这个模式。

## 4. 协商时序

### 4.1 兼容顺序

1. 服务端先完成设备鉴权、owner/base 推导和当前 figure 检查。
2. 服务端接受 WebSocket，并立即发送兼容的 `status=listening`。
3. 新客户端在发送第一帧二进制上行音频前，可以发送一次 `device_hello`。
4. 新服务端收到合法 `device_hello` 后返回 `session_config`。
5. 客户端只使用服务端选中的 profile，不能按自己的首选项直接发送。
6. 第一帧二进制音频到达后，本连接的 profile 锁定。

这套顺序保证：

- 旧客户端连接新服务端时无需等待协商；
- 新客户端连接旧服务端时，最多等待 1000 ms 的 `session_config`，随后根据
  `status=listening` 回退到兼容 PCM；
- 新客户端和新服务端可以协商后续编码；
- 每次重连都重新协商，不缓存上一条连接的选择。

### 4.2 `device_hello`

建议结构：

```json
{
  "type": "device_hello",
  "protocol": "lingou.device.voice.v1",
  "capabilities_version": 1,
  "offered_profile_ids": [
    "ws-opus-v1",
    "ws-pcm-s16le-v1"
  ],
  "duplex_modes": [
    "half_duplex",
    "full_duplex"
  ],
  "audio_frontend": {
    "aec": true,
    "agc": true,
    "noise_suppression": true
  },
  "device": {
    "hardware_model": "lingou-esp32s3-rev-a",
    "firmware_version": "0.1.0"
  }
}
```

约束：

- 整条 JSON 编码后不得超过 4096 字节；
- `capabilities_version` 当前只能为整数 `1`；
- `offered_profile_ids` 必须为非空、无重复的字符串数组，最多 8 项；
- LINGOU 自有 v1.1 客户端必须包含 `ws-pcm-s16le-v1` 作为回退；协议仍允许第三方
  客户端只提供其他 profile，并在没有交集时明确拒绝；
- 未知可选字段和未知 profile ID 被忽略；
- 字段类型错误、超长或重复属于无效 hello；
- hello 只能在第一帧二进制上行音频前发送一次。

`audio_frontend` 只用于选择双工模式和记录能力，不是声学质量已经通过的证明。设备
即使声明 `aec=true`，仍必须完成 EV-05 的真实声学验收。

### 4.3 身份字段禁止规则

`device_hello` 的任意层级都不得包含以下字段：

```text
owner
owner_user_id
base_id
figure_id
session_id
turn_id
audio_id
credential
device_credential
access_token
rtc_token
app_key
ak
sk
```

这些字段出现时，服务端必须判定为 `IDENTITY_FIELD_FORBIDDEN`。硬件型号和固件版本
是诊断标签，不参与授权。设备身份只能来自握手时已经验证的设备凭据。

### 4.4 `session_config`

服务端选中 profile 后返回：

```json
{
  "type": "session_config",
  "status": "selected",
  "session_id": "<server-generated>",
  "contract_revision": 1,
  "profile_id": "ws-pcm-s16le-v1",
  "transport": "websocket",
  "uplink": {
    "codec": "pcm_s16le",
    "sample_rate_hz": 16000,
    "channels": 1,
    "frame_duration_ms": 20,
    "frame_bytes": 640
  },
  "downlink": {
    "codec": "pcm_s16le",
    "sample_rate_hz": 24000,
    "channels": 1,
    "max_frame_bytes": 4096
  },
  "duplex_mode": "half_duplex"
}
```

`session_id` 必须与最初 `status=listening` 中的值一致。服务端不得从 hello 回显或
采用客户端传入的身份、session 或 turn。

### 4.5 拒绝与降级

| 条件 | 行为 |
|---|---|
| 不发送 hello | 直接使用 `ws-pcm-s16le-v1` |
| 同时提供未知 profile 和兼容 PCM | 忽略未知项，选择兼容 PCM |
| 提供计划中的 Opus 和兼容 PCM，但服务端尚未启用 Opus | 降级到兼容 PCM |
| 没有共同 profile | 返回 `NO_COMMON_MEDIA_PROFILE`，关闭 `4406` |
| hello 含身份字段 | 返回 `IDENTITY_FIELD_FORBIDDEN`，关闭 `4406` |
| hello 结构或版本无效 | 返回 `INVALID_CAPABILITIES`，关闭 `4406` |
| 第一帧音频后才发送 hello | 保持已锁定的兼容 PCM，返回 `NEGOTIATION_LOCKED` |

拒绝消息：

```json
{
  "type": "protocol_error",
  "session_id": "<server-generated>",
  "code": "NO_COMMON_MEDIA_PROFILE",
  "message": "no enabled media profile matches the device",
  "retryable_on_new_connection": true
}
```

`4406` 仅表示媒体能力不兼容，不得与身份失败 `4401`、无当前角色 `4404` 或连接替换
`4410` 混用。身份检查必须先于能力协商和任何付费 provider 工作。

## 5. Profile 生命周期

机器合同将 profile 分成三种状态：

- `enabled`：当前服务端和客户端可以实际使用；
- `planned`：结构已预留，但不得在运行时选中；
- `experimental`：只允许独立 PoC，不得由生产默认路径选中。

EV-01 完成时只有 `ws-pcm-s16le-v1` 为 `enabled`。`ws-opus-v1` 必须完成 EV-07
后才能启用，`rtc-lite-v1` 必须通过 EV-11 至 EV-13 后才能进入正式决策。

服务端选择规则是：

```text
设备 offered_profile_ids
∩ 服务端 enabled_profile_ids
→ 按服务端 preference 选择第一项
```

客户端数组顺序不决定服务端策略，避免设备强制开启昂贵、实验性或未授权能力。

## 6. 既有轮次和音频不变量

能力协商不改变以下规则：

1. 每条 WebSocket 连接创建新的 `session_id`。
2. 每轮用户输入由服务端创建新的 `turn_id`。
3. 每段可播放输出由服务端创建 `audio_id`。
4. 下行描述符和二进制帧必须属于同一 session/turn/audio。
5. 分片必须从 0 开始、连续、无重复，且 `chunk_count` 稳定。
6. 播放回执顺序必须为
   `decoded -> playback_started -> playback_completed|playback_failed`。
7. 取消后同一 turn 的迟到文本、音频和回执不得恢复业务状态。
8. 重连不沿用旧 session 的缓冲、完成事件或媒体配置。
9. TTS 已合成或音频已传输不代表用户已经听到。

未来 Opus 或 RTC profile 必须提供等价的媒体边界和播放回执，不能以供应商“已发送”
回调替代终端实际播放确认。

## 7. RTC 映射边界

RTC 资源是传输实现细节，LINGOU 标识仍是业务事实源：

| RTC/供应商概念 | LINGOU 映射 |
|---|---|
| `room_id` | 当前连接的传输资源，不作为 owner 或 session |
| `task_id` | 当前智能体传输任务，只保存在服务端映射表 |
| `round_id` | 映射到服务端已创建的 `turn_id`，不能反向覆盖 |
| 中间字幕 | `interim`，不得提交日志或记忆 |
| 最终字幕 | 进入现有 final/turn 流程 |
| 远端音频 | 绑定服务端生成的 `audio_id` |
| 人声打断 | 进入现有 `cancel_turn` |
| 会话阶段 | 映射为 `status` 或 `turn_metrics` |
| Function Call | 服务端白名单工具请求，携带当前 session/turn |

RTC 房间 Token 必须由 LINGOU 服务端短期签发，并绑定已经认证的 base、owner 和用途。
设备不得持有 RTC AppKey、AK 或 SK。

## 8. 测量合同

EV-01 只冻结字段和计算规则；EV-02 才采集可重复基线数据。

### 8.1 关联字段

所有轮次指标必须关联：

- `session_id`
- `turn_id`
- 有音频时关联 `audio_id`
- `transport` 和 `profile_id`
- 设备固件、服务端版本和测试运行 ID

### 8.2 服务端时间点

沿用或补齐以下单调时钟时间点：

```text
speech_finalized
reply_started
first_audio_synthesized
first_audio_transferred
first_audio_decoded
playback_started
playback_completed
playback_failed
reply_completed
cancelled
```

### 8.3 设备本地时间点和计数器

设备本地记录：

```text
socket_connected
session_config_selected
first_audio_received
playback_buffer_started
audio_output_started
audio_output_stopped
cancel_requested
reconnect_started
reconnect_completed
```

以及：

```text
uplink_frames / uplink_bytes
downlink_frames / downlink_bytes
playback_underruns / playback_overflows
dropped_input_frames
reconnect_attempts
```

不同机器的单调时钟不能直接相减。端到端指标优先使用同一侧可闭合的时间段；需要跨端
比较时必须同时记录时钟偏差和不确定度，不能把墙钟时间直接当作精确延迟。

指标和诊断不得包含用户对话正文、Wi-Fi 密码、设备凭据、Access Token 或 RTC Token。

## 9. EV-01 设计合同用例

| 编号 | 场景 | 预期 |
|---|---|---|
| EV01-C01 | 旧客户端不发送 hello | 继续选择兼容 PCM |
| EV01-C02 | 未知 profile + 兼容 PCM | 忽略未知项，选择 PCM |
| EV01-C03 | 计划中的 Opus + 兼容 PCM | 当前服务端降级到 PCM |
| EV01-C04 | 只有未知 profile | `NO_COMMON_MEDIA_PROFILE` / `4406` |
| EV01-C05 | hello 注入 owner/session | `IDENTITY_FIELD_FORBIDDEN` / `4406` |
| EV01-C06 | hello 类型、大小、版本或数组非法 | `INVALID_CAPABILITIES` / `4406` |
| EV01-C07 | 第一帧二进制后发送 hello | 维持 PCM，返回 `NEGOTIATION_LOCKED` |
| EV01-C08 | 连接断开后重连 | 新 session，重新协商，不复用旧配置 |
| EV01-C09 | 新客户端连接旧服务端 | 1000 ms 内无选择消息时回退 PCM |
| EV01-C10 | 新服务端连接旧客户端 | 不等待 hello，不增加旧路径启动时延 |

这些是设计合同，不表示运行时已支持 `device_hello`。后续实现任务必须把相同用例接到
真实服务端和设备客户端，且继续通过现有设备语音回归。

## 10. EV-01 退出条件

- 人可读规范与机器合同一致；
- 当前唯一启用 profile 与现有代码常量一致；
- 旧客户端、未知能力、降级、拒绝和重连规则明确；
- RTC 资源不能覆盖 LINGOU 业务 ID；
- 测量字段和时钟规则已冻结；
- 设计合同测试通过；
- 没有修改对话、记忆、persona、owner 或运行时 session/turn 实现。
