# EV-02 真实延迟、声学和弱网基线

- 执行日期：2026-09-17
- 任务：`EV-02`
- 传输：WebSocket
- profile：`ws-pcm-s16le-v1`
- 结论：基线采集完成；直接链路与 30 秒恢复通过，当前 Mac 声学回采不合格

## 范围

本次建立后续 Opus、AEC 和 RTC A/B 所需的当前实现基线。所有业务数据使用临时
owner、base、figure、设备凭据和数据目录，任务结束后自动清理。证据只保留随机
session/turn/audio ID、文本长度与摘要、时延和流量计数，不保存实际对话正文或密钥。

本次没有改变对话、记忆、persona、owner 或服务端 session/turn 核心。唯一行为修复
位于 Linux/macOS 替代载体：重连前丢弃断线期间积压的麦克风帧。

## 环境

- macOS 26.6.2，arm64
- Python 3.12.14
- 输入设备：`0 MacBook Pro麦克风`
- 输出设备：`1 MacBook Pro扬声器`
- 输入：16 kHz、mono、s16le、20 ms/640 字节
- 输出：24 kHz、mono、s16le
- 公网基线：`networkQuality -c`
  - 活动接口：`utun4`
  - base RTT：77.2 ms
  - 下载：33.47 Mbit/s
  - 上传：34.97 Mbit/s
  - responsiveness：109.2 RPM

公网基线只描述本次执行环境，不代表到火山服务的专线指标。

## 证据

- [`live-baseline.json`](live-baseline.json)：3 次直接 provider 和 3 次真实声学运行
- [`acoustic-io-baseline.json`](acoustic-io-baseline.json)：3 次低音量 997 Hz
  扬声器到麦克风检测，不保存原始录音
- [`controlled-network-prefit.json`](controlled-network-prefit.json)：修复前 30 秒
  断网失败证据
- [`controlled-network-baseline.json`](controlled-network-baseline.json)：修复后的
  延迟、抖动和 30 秒断网结果
- [`network-quality-summary.json`](network-quality-summary.json)：执行环境公网基线摘要

## 直接 provider 基线

输入 PCM 通过设备 WebSocket 实时发送，真实调用 ASR、Ark 和 TTS；下行 PCM 使用
协议回执完成，不经过扬声器。

| 指标 | 样本 | 最小 | 中位 | 最大 |
|---|---:|---:|---:|---:|
| ASR final → 首文本 | 3 | 1841.7 ms | 2177.0 ms | 2213.3 ms |
| ASR final → 首音频传输 | 3 | 2550.9 ms | 3694.4 ms | 3770.3 ms |
| 客户端收到 final → 首音频 | 3 | 2548.8 ms | 3693.6 ms | 3769.4 ms |
| 客户端收到 final → 轮次完成 | 3 | 2557.8 ms | 3700.0 ms | 3778.7 ms |

结果：

- 3/3 完成；
- 3/3 ASR 命中测试问题；
- 3/3 回复包含已确认事实；
- 每轮均持久化一个带 session/turn ID 的日志；
- 样本仅用于 min/median/max 基线，不能作为 P50/P95 或生产 SLA。

当前主要等待集中在 ASR final 后的 LLM 首文本和首段 TTS，WebSocket 本地传输与回执
不是这三轮的主要耗时。

## 真实声学基线

测试提示先通过真实 Mac 扬声器播放，再由真实 Mac 麦克风采集；未向 WebSocket 直接
注入测试 PCM。

结果：

- 3 次中 2 次最终完成，1 次在 90 秒内没有完成；
- 3 次 ASR 均未命中预期问题；
- 两次完成样本在提示开始后约 49.6–53.4 秒才收到 ASR final；
- 完成样本中，ASR final 到首音频为 3.74–3.97 秒；
- 997 Hz 低音量声学检测 0/3 达到检测门槛；
- 三次声卡采集均无输入溢出或输入队列溢出，但每次首次输出写入都报告 1 次
  PortAudio underflow；
- 没有保存原始录音。

结论：本机输入/输出设备都能打开并传输 PCM，但当前系统音量、麦克风处理、扬声器到
麦克风耦合或环境噪声使自动声学回采不稳定。该结果不能替代真人三轮，也不能证明最终
硬件声学质量。后续 EV-05 必须在目标硬件上使用播放参考通道验证 AEC/AGC/降噪。

## 受控延迟和抖动

该部分使用真实 WebSocket、重连循环、客户端队列和播放状态机，音频与服务端均为隔离
夹具，不调用付费 provider。

| 场景 | 入队到首音频 | 入队到播放完成 | 结果 |
|---|---:|---:|---|
| loopback，无附加延迟 | 0.6 ms | 0.9 ms | 通过 |
| 固定 100 ms 响应延迟 | 101.9 ms | 102.2 ms | 通过 |
| 100 ms 响应延迟 + 120/10/80 ms 分片抖动 | 101.7 ms | 316.2 ms | 通过 |

所有场景的回执顺序均为
`decoded -> playback_started -> playback_completed`。

## 30 秒断网与修复

### 修复前

- 实际中断：30.023 秒；
- 恢复后建立新 session；
- 断线期间缓存的 10 帧音频全部在恢复后上传；
- 判定：失败。

### 根因

音频后端在 WebSocket 断开期间继续采集，输入队列最多保留 100 帧。重新连接时新的发送
任务会先读取旧队列，因此可能把断线期间的语音发送到新 session。

### 修复

- `AudioBackend` 增加 `discard_input_buffer()`；
- WebSocket 结束和新连接成功时清空输入队列；
- 丢弃数量计入 `dropped_input_frames`；
- 记录 `input_buffer_discarded` 观测事件；
- 不改变服务端协议或业务状态机。

### 修复后

- 实际中断：30.026 秒；
- 6 次连接尝试，2 次成功连接，恢复后使用新 session；
- 断线期间 10 帧全部在本地丢弃；
- 恢复前上传旧帧：0；
- 恢复后的新帧正常发送；
- 判定：通过。

## 未覆盖范围

- 没有进行 Wi-Fi 射频衰减、移动网络切换或真实互联网丢包注入；
- WebSocket/TCP 不适合用应用层随机删字节模拟 80% 包丢失；
- 没有把火山产品页的 80% 丢包能力写成 LINGOU 结论；
- 没有最终硬件、AEC、远场、腔体、功耗和温升证据；
- 真实声学语义仍需真人和目标硬件重新验证。

## 验证命令

```bash
services/companion-server/.venv/bin/python -B \
  services/companion-server/scripts/collect_ev02_network_baseline.py \
  --outage-seconds 30

cd services/companion-server
.venv/bin/python -B scripts/collect_ev02_live_baseline.py \
  --confirm-live-providers \
  --confirm-audio-io \
  --direct-runs 3 \
  --acoustic-runs 3 \
  --input-device 0 \
  --output-device 1

.venv/bin/python -B scripts/collect_ev02_acoustic_io.py \
  --confirm-audio-io \
  --input-device 0 \
  --output-device 1 \
  --trials 3
```

## 回归

- 硬件适配器、协议设计和固件合同：`46/46` 通过；
- 后端设备语音定向回归：`13/13` 通过；
- `pip check`：通过；
- Python 编译：通过；
- `git diff --check`：通过。

## EV-02 结论

EV-02 的目标是建立事实基线，不是提前完成最终硬件声学优化。本任务已获得可重复的
直接链路、受控延迟/抖动、30 秒恢复和真实声学失败证据，因此基线采集完成。

下一项 `EV-03` 需要目标硬件并必须在独立硬件适配分支进行。当前仍应先完成
`PLAN.md` 的 `SW-GATE` 真人和 H5 本地放行事项。
