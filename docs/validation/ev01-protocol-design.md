# EV-01 设备语音协议能力协商设计验收

- 执行日期：2026-09-17
- 任务：`EV-01`
- 结论：设计合同通过；运行时协商未实现，仍只启用 PCM

## 范围

本任务只冻结 `lingou.device.voice.v1` 的向后兼容能力协商、RTC 映射和测量字段。
没有修改服务端、替代载体或 ESP32 固件的运行逻辑，也没有进入 Opus、RTC、AEC、
VAD、对话、记忆或 persona 实现。

实际延迟、声学和弱网数据采集属于 `EV-02`，本任务只确定字段、关联 ID 和时钟规则。

## 产物

- 人可读规范：
  [`../device-voice-protocol-v1.md`](../device-voice-protocol-v1.md)
- 机器合同：
  [`../contracts/device-voice-v1.contract.json`](../contracts/device-voice-v1.contract.json)
- 设计合同测试：
  [`../../hardware_adapter/tests/test_device_voice_protocol_design.py`](../../hardware_adapter/tests/test_device_voice_protocol_design.py)

## 冻结结论

1. `device_hello` 是可选首个控制帧，只能在第一帧二进制上行音频前发送。
2. 旧客户端不发送 hello 时继续使用 `ws-pcm-s16le-v1`。
3. 新客户端连接旧服务端时，等待选择消息最多 1000 ms，随后按现有
   `status=listening` 回退 PCM。
4. 当前唯一启用 profile 仍为 16 kHz PCM 上行、24 kHz PCM 下行。
5. Opus 为 `planned`，RTC Lite 为 `experimental`，运行时不得选中。
6. 服务端按自身启用列表和优先级选择 profile，设备不能强制开启实验能力。
7. owner/base/figure/session/turn/audio 均为服务端事实，hello 中出现这些身份字段即拒绝。
8. 能力不兼容使用 `4406`，不与身份 `4401`、未激活 `4404` 或替换 `4410` 混用。
9. 每次新 WebSocket 都生成新 session 并重新协商，不复用旧配置和旧播放状态。
10. RTC room/task/round 只是传输资源，不能覆盖 LINGOU 的 session/turn/audio。

## 测量合同

服务端继续以 `session_id`、`turn_id` 和 `audio_id` 关联：

- 语音判停；
- 回复开始；
- 首音频合成和传输；
- 终端解码、播放开始和播放完成/失败；
- 回复完成和取消。

设备侧后续补充连接、配置选择、首音频接收、缓冲开始、实际输出停止、重连及
欠载/溢出计数。跨设备的单调时钟不能直接相减；EV-02 必须按同一时钟域计算持续时间，
或记录时钟偏差和不确定度。

指标不得包含对话正文、Wi-Fi 密码、设备凭据、Access Token 或 RTC Token。

## 自动验证

### 设计合同

命令：

```bash
python3 -B hardware_adapter/tests/test_device_voice_protocol_design.py
```

结果：`11/11` 通过。

覆盖：

- 当前三个运行端的子协议、端点和 PCM 常量一致；
- 旧客户端无 hello 的兼容行为；
- 未知 profile 忽略；
- Opus 未启用时降级 PCM；
- 无共同 profile 拒绝；
- 任意层级身份字段注入拒绝；
- hello 结构边界；
- 第一帧音频后 profile 锁定；
- 重连重新协商；
- RTC 映射和测量字段边界；
- 新关闭码不与既有应用关闭码重叠。

### 硬件适配器回归

命令：

```bash
python3 -B -m unittest discover -s hardware_adapter/tests -v
```

结果：`44/44` 通过，其中既有测试 `33` 项，EV-01 新增 `11` 项。

### 静态检查

```bash
python3 -m json.tool docs/contracts/device-voice-v1.contract.json
git diff --check
```

结果：通过。

## 后续补跑

EV-01 初次执行时系统 `python3` 为 3.9.6，低于仓库要求。EV-02 已使用独立
Python 3.12.14 环境补跑：

```bash
cd services/companion-server
.venv/bin/python -B tests/test_device_voice.py
```

结果：`13/13` 通过。本任务仍未修改服务端运行代码。

## 验收映射

| EV-01 条件 | 证据 | 结果 |
|---|---|---|
| 旧客户端继续走 PCM | 机器合同 legacy 样例及设计测试 | 通过 |
| 设备不能声明 owner/figure/session | 递归身份字段拒绝测试 | 通过 |
| 未知、降级和拒绝规则 | 三组 profile 选择样例及测试 | 通过 |
| 重连使用新配置 | 每连接重新协商合同测试 | 通过 |
| RTC 不替换业务 ID | RTC 映射合同测试 | 通过 |
| 测量字段和时钟规则明确 | 规范第 8 节及机器合同 | 通过 |
| 不修改业务核心 | Git 变更仅含文档、JSON 合同和测试 | 通过 |

## 后续边界

- `EV-02` 才建立故障注入工具并采集当前 WebSocket + PCM 的真实基线。
- `EV-07` 才实现 Opus 和真实运行时协商。
- `EV-11` 至 `EV-13` 才允许 RTC Lite 进入独立 PoC 和 A/B 决策。
- 在这些任务完成前，运行时仍只允许 `ws-pcm-s16le-v1`。
