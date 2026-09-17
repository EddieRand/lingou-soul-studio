# 替代载体独立设备 MVP

第 11 步的验收载体改为通用 Linux/macOS 设备，例如树莓派、香橙派、迷你主机或旧电脑，
配合系统可识别的麦克风和扬声器。最终自研硬件不再阻塞一期设备体验验证。

## 本步验证什么

- 不打开 H5、浏览器或 IDE，也不运行串口桥即可完成语音交流。
- 替代载体通过独立设备凭据连接，不保存或使用用户 Bearer。
- 设备和 H5 指向同一底座当前角色、persona、确认记忆及近期历史。
- 用户说话后，载体完成采音、ASR、对话、TTS 和扬声器播放。
- 播放完成结果绑定原 `session_id`、`turn_id`、`audio_id` 回传。
- 中断会取消原服务端轮次，迟到文字和音频不再播放或保存。
- 断网/服务异常会本地提示并退避重连，不播放断线期间积压的回复。
- 进程可通过 systemd 或 launchd 开机自动启动。

这一步不验证最终产品的麦克风阵列、结构腔体、回声消除、底噪、功耗、散热、续航、
触摸传感器或量产可靠性。这些属于最终硬件工程验证。

## 协议

当前运行时协议和未来媒体能力协商的完整规范见
[`device-voice-protocol-v1.md`](device-voice-protocol-v1.md)。EV-01 只冻结设计合同；
当前服务端、替代载体和参考固件仍只启用兼容的 PCM profile。

客户端为：

`hardware_adapter/portable_voice_client.py`

它直接连接：

`WS(S) /api/asr/device-stream`

设备上行是 16 kHz、单声道、16-bit little-endian PCM，每帧 20 ms（640 字节）。
服务端下行是 24 kHz、单声道、16-bit little-endian PCM，每个 WebSocket 二进制帧
不超过 4096 字节。

客户端使用：

```http
Authorization: Device BASE-DEVICE-001.<secret>
Sec-WebSocket-Protocol: lingou.device.voice.v1
```

同一底座只允许一个 H5 或替代载体语音连接。新连接替换旧连接时使用关闭码 `4410`。
替代载体被 H5 替换后暂停自动抢回，需按回车或发送 `SIGUSR1` 才恢复。

握手后的 `status=listening` 确认 PCM 参数，`status=ready` 表示上游 ASR 已可接收音频。
服务端会在每条设备上行前复验原凭据及 base/owner；解绑、撤销或轮换后，存量连接
不能继续传输，并以 `4401` 关闭。

每个 `audio_chunk` 必须携带当前 session/turn/audio 标识、固定格式字段、稳定的
`chunk_count` 和连续 `chunk_index`。播放回执按
`decoded -> playback_started -> playback_completed|playback_failed` 顺序发送。
取消后的迟到描述符和二进制帧只被消费，不再播放或回报完成。

载体在断线和新连接建立时清空尚未发送的麦克风队列，避免把离线期间的旧语音发送到
新 session。可选 `observation_sink` 使用单调时钟记录连接、首音频、播放、重连和
帧计数，不包含凭据或对话正文。EV-02 的基线和修复前后证据见
[`validation/ev02-baseline-20260917/README.md`](validation/ev02-baseline-20260917/README.md)。

## 安装

在替代载体上创建独立环境：

```bash
cd /opt/lingou
python3 -m venv .venv-portable
.venv-portable/bin/python -m pip install \
  -r hardware_adapter/requirements-portable-device.txt
```

Linux 还需要 PortAudio 和 ALSA 运行库。例如 Debian / Raspberry Pi OS：

```bash
sudo apt-get install -y libportaudio2
```

列出可用音频设备：

```bash
.venv-portable/bin/python -B \
  -m hardware_adapter.portable_voice_client \
  --list-audio-devices
```

## 凭据与启动

新底座使用 `scripts.provision_base` 生成二维码和设备凭据。旧底座通过
`scripts.rotate_device_credential` 显式换发具有 `voice:stream` 的凭据。

把真实值保存在仓库外、权限为 `0600` 的环境文件：

```bash
LINGOU_DEVICE_CREDENTIAL=BASE-DEVICE-001.<secret>
LINGOU_DEVICE_VOICE_URL=wss://your-lingou-host/api/asr/device-stream
```

手动运行：

```bash
set -a
source /etc/lingou/device.env
set +a

/opt/lingou/.venv-portable/bin/python -B \
  -m hardware_adapter.portable_voice_client
```

默认使用系统输入/输出设备。可通过 `--input-device` 和 `--output-device` 指定设备索引
或名称。运行中：

- 交互终端按回车：打断当前回复；如被 H5 替换，则恢复设备会话。
- 无终端环境发送 `SIGUSR1`：执行相同操作。
- `SIGINT` / `SIGTERM`：释放麦克风、扬声器和 WebSocket 后退出。
- 下行播放队列固定为 8 帧；慢播放导致队列满时，当前音频明确失败并清空，不阻塞
  `stop_audio` 或其他控制消息。
- 观测快照包含播放溢出、丢帧、最大队列深度和最大排队时长。

## 自动启动

Linux 模板：

`hardware_adapter/service/lingou-portable-device.service.example`

将路径和用户改为实际值，把环境文件写入 `/etc/lingou/device.env` 并限制权限：

```bash
sudo chmod 600 /etc/lingou/device.env
sudo systemctl enable --now lingou-portable-device
```

macOS 模板：

`hardware_adapter/service/com.lingou.portable-device.plist.example`

环境文件放在 `~/.config/lingou/device.env` 并设为 `0600`。生产部署应把日志位置换到
受管理目录，不在环境文件或日志中输出设备凭据。

## 可重复验证

单元与合同验证：

```bash
python -B hardware_adapter/tests/test_portable_voice_client.py
python -B hardware_adapter/tests/test_portable_service_contract.py
```

本机声卡格式检查：

```bash
python -B -m hardware_adapter.portable_voice_client --list-audio-devices
```

真实声学闭环会播放两段声音并调用真实 ASR、Ark 和 TTS，因此要求双重显式确认：

```bash
cd services/companion-server
python -B scripts/verify_portable_carrier_live.py \
  --confirm-live-providers \
  --confirm-audio-io
```

该脚本只使用临时 owner、底座、角色、凭据和数据目录。测试问题先从真实扬声器播放，
再由真实麦克风重新采集；不会把测试输入 PCM 直接注入 WebSocket。

## 第 11 步通过标准

1. 替代载体进程脱离 H5、浏览器、IDE 和串口桥独立启动。
2. 真实麦克风和扬声器完成至少一轮交流，且服务端收到播放完成回执。
3. 该轮使用底座当前角色和确认记忆，日志保存正确的 session/turn ID。
4. 打断后原轮次停止，迟到输出不播放、不落盘。
5. 服务端断开后本地提示并自动恢复；`4410` 替换后不抢回 H5。
6. 自动启动模板和凭据隔离检查通过。

通过这些条件只证明独立设备体验和云链路可行，不证明最终自研硬件已经完成。
