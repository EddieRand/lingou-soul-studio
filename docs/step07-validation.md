# 第 07 步实施与验证报告

日期：2026-09-15。

结论：第 07 步“真实音频与声线试听”在本步约定范围内验证通过。
第 08 步未开始，等待用户单独批准。

## 范围

- 区分语音合成、WebSocket 传输、客户端解码、播放开始和播放完成。
- 无可交付音频时返回真实失败，不把服务器本地 `say/afplay` 当作用户端成功。
- 由前端统一管理通话播放回执及候选声线试听资源。
- 候选声线先独立试听，再明确确认保存；保存后从服务端回读验证。
- 不修改第 08 步的人设字段、prompt 或文字/语音共同对话规则。

## 通话音频协议

每段服务端音频具有独立 `audio_id`，并绑定原有 `session_id`、`turn_id` 和
`turn_sequence`。服务端依次发送：

1. `audio_output / synthesized` 元数据。
2. 二进制音频。
3. `audio_output / transferred`。
4. 全部分段发送后发送 `audio_output / stream_complete`。

客户端只有在实际完成对应操作后才回传：

- `decoded`
- `playback_started`
- `playback_completed`
- `playback_failed`

服务端在本轮指标中记录：

- `first_audio_synthesized_ms`
- `first_audio_transferred_ms`
- `first_audio_decoded_ms`
- `playback_started_ms`
- `playback_completed_ms`

没有音频时，本轮状态为 `audio_failed` 并发送 `NO_AUDIO_GENERATED`。播放确认超时也不记为成功。
barge-in、挂断、连接替换和服务端失败都会停止已排程音源、清空音频元数据及定时器；迟到解码结果
仍受 attempt 校验约束。

## 输出语义

`speak_sentence_streaming` 现在分别返回 `synthesized` 和 `transferred`。浏览器请求存在
`audio_sink` 时：

- TTS 生成文件但发送失败：`synthesized=true`、`transferred=false`、`success=false`。
- 没有云端或语音池音频：返回 `no_deliverable_audio`。
- 不调用服务器本地 `system_say` 或播放器作为降级。
- 语音池向浏览器发送文件字节时，不再同时从服务器扬声器播放。

文字回复仍可见，但页面会明确提示音频失败，避免把文字成功误报成用户已经听到。

## 声线试听

新增认证接口 `POST /api/voice/preview`，直接返回音频字节和以下响应头：

- `X-Lingou-Audio-Engine`
- `X-Lingou-Audio-Source`
- `X-Lingou-Voice-Speaker`
- `X-Lingou-Audio-Synthesized-At`

传 `speaker` 时只试听该候选声线，不会复用角色当前克隆声线或其他 speaker 的语音池。
传 `figure_id` 且不传 speaker 时试听角色当前配置。实时合成不可用时，预置声线可回退到该
speaker 在受控音色目录中的官方样本，并通过 `source=catalog_demo` 明确标识。

前端新增 `VoicePreviewController/useVoicePreview`，统一管理请求取消、Object URL、
`HTMLAudioElement` 和播放阶段。创建页、编辑页和音色实验室使用同一控制器：

- 不再为试听创建临时角色。
- 不再依赖空 `demo_url` 或不存在的 `/voice/play`。
- 点声线卡只选择候选，不立即保存。
- 确认选用后调用保存接口，再读取角色并校验 speaker 一致。
- 页面卸载、切换试听或再次点击当前声线都会停止并释放旧音频。

## 验证结果

| 验证 | 结果 |
|---|---|
| 第 01 步隔离基线 | 8/8 |
| 第 02 步身份安全 | 18/18 |
| 第 03 步数据归属 | 10/10 |
| 离线迁移 | 19/19 |
| 第 04 步配对、创建与激活 | 6/6 |
| 第 05–07 步语音轮次与播放指标 | 8/8 |
| 第 07 步音频交付接口 | 6/6 |
| 串口桥协议 | 6/6 |
| Python/硬件合计 | 81/81 |
| 前端通话生命周期探针 | 11/11 |
| 前端声线试听探针 | 4/4 |
| 前端认证合同探针 | PASS |
| TypeScript + Vite 生产构建 | PASS，62 个模块 |
| `pip check` | PASS |
| `git diff --check` | PASS |

定向自动化覆盖无音频失败、合成成功但传输失败、候选 speaker 精确传递、跨账号拒绝、保存回读、
客户端完整播放回执、解码失败、挂断取消和迟到音频隔离。

## 真实浏览器验证

使用独立临时数据启动真实 Uvicorn 与 Vite，并调用已配置的火山 TTS：

- 试听第二条候选声线返回 HTTP 200，`source=synthesized`。
- 响应 speaker 为 `ICL_zh_male_wenrouxuezhang_tob`，音频为 13,869 字节。
- Chrome 中依次出现传输、解码、播放和播放完成状态。
- 确认保存后，服务端回读 speaker 与试听目标完全一致。
- 前台 Chrome 再执行一轮实际终端播放，音频为 15,213 字节并触发 `onplaying/onended`。
- 390x844 与 1280x900 均无水平溢出，浏览器控制台无错误。

该验证证明音频由用户终端浏览器输出，而不是服务器播放器。未进行人工声学质量、音量或扬声器
硬件评分；这些属于后续设备及综合验收。

测试结束后已关闭临时服务。原运行数据仍为 646 个文件，元数据摘要保持：

`d0c093a91cecb31dc43b4a3ee5d40bf915742335ba784c5a37f51963604f0959`

## 边界与下一步

- 本步没有连接真实 ASR、LLM、麦克风或实体灵偶硬件。
- 浏览器播放成功不能替代第 11 步的独立设备扬声器验收。
- 当前音频按句生成完整文件后发送，不是 provider 级音频帧流；延迟分位数留到第 12 步测量。
- 第 08 步范围是统一人设与共同对话入口。本报告不授予下一步执行许可。
