# 第 11 步实施与验证报告

日期：2026-09-15。

> **修复后状态（2026-09-16）**
>
> 120 条用例复验发现的 13 项缺陷已修复并通过对应回归。最新统计为当前 MVP
> 47 条通过、0 条失败、63 条环境阻塞；完整 MVP 因 P0 环境阻塞仍未放行。
> 第 11 步现为“软件缺陷修复完成，环境验收待补”，以
> [2026-09-16 MVP 验证报告](mvp-validation-20260916.md) 和
> [逐条执行表](mvp-test-execution.csv) 为准。最终自研硬件仍后置；第 12 步未开始。

以下内容是 2026-09-15 的阶段性记录，保留用于追溯；当前结果以修复后报告为准。

## 范围

- 通用 Linux/macOS 载体不依赖 H5、浏览器、IDE、用户 Bearer 或串口桥，直接连接后端语音服务。
- 设备与 H5 使用同一底座当前角色、persona、最近 6 轮对话和确认记忆。
- 输入为系统麦克风的 16 kHz 单声道 `s16le` PCM。
- 输出为系统扬声器的 24 kHz 单声道 `s16le` PCM。
- 播放结果绑定原 `session_id`、`turn_id`、`audio_id` 回传。
- 回车或 `SIGUSR1` 可中断设备播放及原服务端轮次。
- 断网或服务故障提供本地提示音并退避重连，恢复后建立新会话，不播放积压回复。
- 提供 systemd 和 launchd 模板，使替代载体脱离开发工具自动启动。

## 替代载体

客户端位于：

`hardware_adapter/portable_voice_client.py`

可运行于树莓派、香橙派、迷你主机、旧电脑或其他具备 Linux/macOS、麦克风和扬声器的载体。
可选依赖独立保存在 `hardware_adapter/requirements-portable-device.txt`，不污染后端服务依赖。

运行配置只从 `LINGOU_DEVICE_CREDENTIAL` 和 `LINGOU_DEVICE_VOICE_URL` 读取。
真实凭据保存在仓库外、权限为 `0600` 的环境文件。systemd 与 launchd 模板位于
`hardware_adapter/service`。

## 设备身份

设备凭据拥有两个设备域权限：

- `events:write`
- `voice:stream`

`WS(S) /api/asr/device-stream` 从 `Authorization: Device <credential>` 推导
`base_id` 和 `owner_user_id`，不接受客户端提交 owner 或角色 ID。连接还必须提供
`lingou.device.voice.v1` 子协议，且底座已有当前角色。

旧的 `events:write` 凭据不会在线自动扩权。新增
`scripts.rotate_device_credential`，由操作员在离线数据目录显式轮换生产凭据；
旧凭据立即失效。

## 音频与轮次协议

- 设备每 20 ms 上传 640 字节 16 kHz PCM。
- 火山 TTS 为设备请求 24 kHz 原始 PCM；H5 仍使用原 MP3 路径。
- 服务端把每段 PCM 拆成不超过 4096 字节的二进制帧。
- 每帧前发送 `audio_chunk`，包含格式、采样率、帧序号和原轮次标识。
- 设备回传 `decoded`、`playback_started`、`playback_completed` 或
  `playback_failed`。
- 设备发送 `cancel_turn` 时，服务端取消模型/TTS、停止迟到输出且不提交被取消轮次。

H5 和替代载体共享 `VoiceSessionRegistry`，同一底座仍执行
`newest_connection_wins`。替代载体收到 `session_replaced` 后暂停自动重连，避免抢回 H5；
用户按回车或发送 `SIGUSR1` 后才显式恢复设备会话。

替代载体播放期间麦克风静音，可靠打断方式为回车、系统信号或外接按钮映射到 `SIGUSR1`；
不把未经验证的声学回声消除作为本步承诺。

## 验证结果

新增 10 项设备语音后端测试：

1. 设备凭据推导 owner/base，不信任客户端选择。
2. 缺少 `voice:stream` 时在模型调用前拒绝。
3. 无当前角色时以 `4404` 拒绝。
4. FastAPI 注册路由完成真实 WebSocket 握手。
5. 生产凭据轮换立即撤销旧密钥。
6. 设备 PCM 被拆为 4096 字节上限的有序帧。
7. 显式取消传播到原轮次。
8. 播放回执完成原音频 ID。
9. 设备轮次复用 owner、session、turn 及共同对话入口。
10. TTS 设备路径明确请求 24 kHz PCM。

既有 6 项 DNESP32S3 参考固件合同测试继续保留：

- 固定引脚。
- 启动红闪 3 次。
- 设备鉴权和 PCM 协议。
- 空闲输出归零及播放时麦克风静音。
- 断连本地提示、心跳和重连。
- 密钥文件隔离。

新增 8 项替代载体客户端测试：

- PCM 播放及原始 ID 回执。
- ASR 与回复文本健康状态。
- 打断时先回传播放失败，再取消原轮次。
- `4410` 替换后暂停并显式恢复。
- 麦克风固定发送 20 ms 帧。
- 服务端停止后清理播放并恢复采音。
- 瞬时断连本地提示并退避重连。
- URL 与设备凭据输入校验。

新增 2 项自动启动合同测试，确认 systemd/launchd 脱离 IDE 启动且不内嵌密钥。

完整 Python/设备回归为 `128/128`。其他自动化结果：

- 前端认证、主路径、通话和试听探针 `23/23`。
- TypeScript 与 Vite 生产构建通过，64 个模块。
- Python AST `73/73`。
- `pip check` 与 `git diff --check` 通过。

ESP32 Arduino core `3.3.10` 编译通过：

- Flash：1,110,081 / 1,310,720 字节（84%）。
- RAM：49,596 / 327,680 字节（15%）。

该 ESP32 固件作为最终硬件参考实现保留，但不再是第 11 步验收载体。

替代载体本机音频验证：

- 检测到 MacBook Pro 单声道麦克风和双声道扬声器。
- 默认麦克风支持 16 kHz、单声道、int16。
- 默认扬声器支持 24 kHz、单声道、int16。
- 实际采集 25 个 20 ms 帧，共 16,000 字节，峰值 4,075。
- 实际播放 100 ms、4,800 字节低音量 PCM，音频流正常打开、写入和关闭。

真实火山 PCM 探针：

- 24 kHz、单声道、`s16le`。
- 测试短句返回 49,386 字节。
- 小端解析峰值 24,826，非静音。

隔离的真实云端协议轮次：

- 输入：TTS 合成的 16 kHz PCM“你好，请告诉我你记得我喜欢什么颜色”。
- ASR：`你好，请告诉我，你记得我喜欢什么颜色`。
- 已确认记忆：`用户喜欢蓝色。`
- 回复抽样：`当然记得，你喜欢蓝色呀。`
- 最近一次设备下行：124,916 字节 PCM。
- 播放回执：1 个音频 ID 完成。
- 轮次结果：`completed`，临时 owner 下持久化 1 条带 session/turn ID 的日志。

该流程使用临时底座、角色、凭据和数据目录。服务与临时数据均已删除，没有读取或修改
项目真实运行数据。原数据仍为 646 个文件，元数据摘要保持：

`d0c093a91cecb31dc43b4a3ee5d40bf915742335ba784c5a37f51963604f0959`

复现命令（会调用真实收费 provider，必须显式确认）：

```bash
cd services/companion-server
.venv/bin/python -B scripts/verify_device_voice_live.py \
  --confirm-live-providers
```

真实替代载体声学闭环：

- 测试问题先由真实系统扬声器播放，再由真实系统麦克风重新采集。
- 没有把测试输入 PCM 直接注入 WebSocket。
- ASR：`你好，请告诉我，你记得我喜欢什么颜色`。
- 确认记忆：`用户喜欢蓝色。`
- 回复抽样：`我记得你喜欢蓝色，这个颜色很衬你呢。`
- 回复通过真实系统扬声器播放完成并回传原 `audio_id`。
- 临时 owner 下只持久化 1 条带 session/turn ID 的轮次。

复现命令会真实发声并调用收费 provider，因此要求双重显式确认：

```bash
cd services/companion-server
.venv/bin/python -B scripts/verify_portable_carrier_live.py \
  --confirm-live-providers \
  --confirm-audio-io
```

## 后置边界

以下事项属于最终自研硬件工程，不属于调整后的第 11 步：

1. 最终芯片、麦克风阵列、扬声器和功放选型。
2. 结构腔体、回声消除、底噪、远场拾音及实体按键/触摸。
3. 功耗、散热、续航、跌落、老化和量产可靠性。
4. 最终设备配网、OTA、恢复出厂和售后诊断。

第 11 步软件实现完成只证明“独立设备体验与云链路”可行，不表示最终自研硬件已经完成。
第 12 步仍需用户单独批准。
