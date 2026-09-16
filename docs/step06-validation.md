# 第 06 步实施与验证报告

日期：2026-09-15。

结论：第 06 步“前端通话生命周期”在本步约定范围内验证通过。
第 07 步未开始，等待用户单独批准。

## 范围

- 从 `DialogueDebugPage` 抽离麦克风、AudioContext、处理节点、WebSocket、音频队列和重连定时器。
- 建立单一 `VoiceCallController` 管理全部通话资源与状态。
- 修复挂断、页面卸载、底座变化、授权失败、断线重连和连接替换时的清理规则。
- 重连保留页面已有对话记录，并按后端 `turn_id` 合并流式文本。
- 不改变第 07 步的 TTS 合成、传输和“用户实际听到”成功判定。

## 生命周期

前端状态统一为：

`idle -> requesting_permission -> connecting -> listening <-> speaking`

异常分支：

- 意外断线：`reconnecting`，最多自动重试 3 次。
- 权限拒绝：`permission_denied`，释放资源并显示“重新授权麦克风”。
- 身份失效或重试耗尽：`error`，停止自动重连。
- 后端连接替换：`replaced`，不自动抢回底座。

连续点击开始、重连计时器和异步授权结果都通过 attempt 编号失效旧操作，任何时刻最多创建一个
当前 WebSocket。新连接使用新的短票据；页面不保存 access token。

## 资源所有权

控制器独占并统一释放：

- MediaStream 及全部 track。
- AudioContext。
- MediaStreamAudioSourceNode、ScriptProcessorNode 和静音 GainNode。
- WebSocket 及全部事件回调。
- 已排程 AudioBufferSourceNode。
- 重连定时器和正在进行的启动 Promise。

挂断、切换底座、页面卸载、授权中取消、连接替换及失败都会进入同一清理路径。音频解码完成时会
再次检查 attempt；挂断之后才完成的解码结果不会创建或播放音源。

React StrictMode 会模拟一次 effect 卸载。Hook 将最终销毁延迟到微任务，并在 effect 立即重新挂载时
取消销毁语义，避免开发环境中控制器被永久标记为 destroyed。

## 可见历史

- 开始通话和自动重连不再清空 `messages`。
- 只有真实底座切换才清空页面历史。
- 用户与灵偶消息按后端 `turn_id` 去重、追加和完成。
- `turn_cancelled` 会结束对应流式消息，不会让下一轮继续追加到旧气泡。
- `barge_in` 不再额外插入用户消息，避免随后 `final` 再插入一次。

## 验证结果

前端生命周期探针 8/8：

1. 连续两次开始只请求一次权限、票据和 WebSocket。
2. 授权 Promise 未完成时挂断，迟到 MediaStream 立即停止且不继续建连。
3. 权限拒绝进入可重试状态，第二次授权成功后正常连接。
4. 意外断线只安排一个重连，新连接成功后历史仍保留。
5. `4410` 连接替换不自动重连。
6. 重连等待期间挂断，不会再创建连接。
7. 页面销毁释放 track、AudioContext、处理节点、GainNode 和 WebSocket。
8. 挂断后才完成的音频解码不会创建播放源。

其他验证：

| 验证 | 结果 |
|---|---|
| 前端认证/合同探针 | PASS |
| TypeScript | PASS |
| Vite 生产构建 | PASS，60 个模块 |
| 浏览器页面 | PASS |
| Python/硬件既有回归 | 74/74 |
| `git diff --check` | PASS |

浏览器使用独立临时数据完成登录并打开真实绑定底座与角色的对话页。页面在 React StrictMode 下正常，
通话卡片、错误区域、历史区域和开始按钮均可见，控制台无业务错误。测试结束后关闭服务并删除临时数据。

本轮没有点击浏览器麦克风权限弹窗，没有连接真实 ASR、LLM、TTS，也没有验证扬声器实际发声。
权限拒绝、恢复和资源释放由完全注入的假媒体/Socket/计时器自动化验证。

## 下一步边界

第 07 步需要区分“合成成功、传输成功、解码成功、播放开始、播放完成”，并验证声线试听目标及用户终端
实际发声。本步骤只保证资源和状态生命周期正确，不把收到二进制音频等同于用户听到声音。
