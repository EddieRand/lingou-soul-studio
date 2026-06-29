# services/companion-server/app/api/asr.py
"""
ASR WebSocket 端点（服务端编排版本）。

架构：
  - H5 麦克风 → PCM 流式上传 → /api/asr/stream WebSocket
  - 后端转发给火山 ASR
  - 火山返回整段累积识别文本（result.text）
  - 后端自动编排：ASR → 大脑 → TTS → 播放

说完判定（基于整段文本稳定超时）：
  - 用 result.text（火山返回的整段累积文本）
  - 1.5s 稳定超时：result.text 1.5s 没变 → 用户停下来了 → 触发一轮对话

每轮一条火山连接方案：
  - 每条火山连接只处理一句话
  - finalize 后主动重连火山，迎接下一轮
  - 回复期间暂停向火山转发音频（避免错误帧）
  - epoch 机制：旧连接自动退出，不阻塞新连接

性能优化：
  - 音频缓冲：火山未就绪时缓冲 PCM，连好后补发
  - 后台连接：客户端连上后立即进入聆听，火山连接后台建立
  - 快速失败：火山连接超时 4s，重试之间 0.3s 退避
  - fire-and-forget：旧连接后台关闭，不阻塞新连接
"""

import asyncio
import json
import re
import threading
import time
from collections import deque
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.asr_adapter import is_asr_available, _build_full_client_request, _build_audio_frame, _parse_server_response
from app.core.tts_adapter import stop_playback
from app.core.dialogue_engine import process_text_input

router = APIRouter(prefix="/api/asr", tags=["asr"])

# 文本稳定超时时间（秒）
STABILITY_TIMEOUT = 1.5

# 火山连接超时和重试配置
VOLC_OPEN_TIMEOUT = 4.0   # 火山连接超时（秒）
VOLC_MAX_RETRIES = 2     # 最大重试次数
VOLC_RETRY_DELAY = 0.3   # 重试之间退避（秒）
VOLC_CLOSE_TIMEOUT = 2.0  # 旧连接关闭超时（秒）


class VoiceCallSession:
    """
    语音通话会话：管理单个 WebSocket 连接的 ASR → 对话编排。

    每轮一条火山连接：
      - 每条火山连接只处理一句话
      - finalize 后主动重连火山，迎接下一轮
      - 回复期间暂停向火山转发音频
      - epoch 机制：旧连接自动退出，不阻塞新连接
    """

    def __init__(self, websocket: WebSocket, base_id: str):
        self.ws = websocket
        self.base_id = base_id
        self.volc_ws = None  # 火山 ASR WebSocket
        self._connected = False  # 火山是否已连接并就绪
        self._replying = False  # 是否正在等待/播放灵偶回复
        self._reply_lock = asyncio.Lock()
        self._request_id = str(id(self))  # 用于日志标识

        # ========== 连接代号（epoch）机制 ==========
        self._conn_epoch = 0  # 当前连接代号，每次新建连接 +1
        self._epoch_lock = asyncio.Lock()

        # ========== 音频缓冲队列 ==========
        self._audio_buffer: deque = deque()  # 缓冲的 PCM 音频块
        self._buffer_lock = asyncio.Lock()
        self._connecting = False  # 是否正在连接火山

        # ========== 整段文本稳定超时机制 ==========
        self._current_text = ""           # 当前正在计时的 result.text
        self._current_text_lock = asyncio.Lock()
        self._stability_timer: Optional[asyncio.Task] = None  # 稳定性定时器

        # ========== 重连锁 ==========
        self._reconnecting = False  # 防止并发重连

        # ========== Barge-in 取消事件 ==========
        self._cancel_event: Optional[threading.Event] = None

    # ============== epoch 机制 ==============

    async def _next_epoch(self) -> int:
        """获取下一个 epoch，并更新"""
        async with self._epoch_lock:
            self._conn_epoch += 1
            return self._conn_epoch

    async def _get_epoch(self) -> int:
        """获取当前 epoch"""
        async with self._epoch_lock:
            return self._conn_epoch

    # ============== 音频缓冲 ==============

    async def _buffer_audio(self, audio_chunk: bytes):
        """缓冲音频到队列"""
        async with self._buffer_lock:
            self._audio_buffer.append(audio_chunk)

    async def _flush_buffer(self):
        """补发缓冲的音频给火山（火山就绪后调用）"""
        async with self._buffer_lock:
            if not self._audio_buffer:
                return

            count = len(self._audio_buffer)
            print(f"[VoiceCall {self._request_id}] 补发 {count} 块缓冲音频...")

            while self._audio_buffer:
                chunk = self._audio_buffer.popleft()
                if self._connected and self.volc_ws:
                    try:
                        frame = _build_audio_frame(chunk)
                        await self.volc_ws.send(frame)
                    except Exception as e:
                        print(f"[VoiceCall {self._request_id}] 补发音频失败: {e}")
                        self._audio_buffer.appendleft(chunk)
                        break

    async def send_audio(self, audio_chunk: bytes):
        """
        发送音频到火山 ASR（全双工：Barge-in 期间也正常转发）。
        因为 AEC 已把灵偶声音消掉，转发不会导致自问自答。
        """
        if self._connected and self.volc_ws:
            try:
                frame = _build_audio_frame(audio_chunk)
                await self.volc_ws.send(frame)
            except Exception as e:
                print(f"[VoiceCall {self._request_id}] 发送音频失败: {e}")
                self._connected = False
                await self._buffer_audio(audio_chunk)
        else:
            await self._buffer_audio(audio_chunk)

    # ============== 后台关闭旧连接（fire-and-forget） ==============

    async def _safe_close_volc_ws(self, ws, epoch: int):
        """后台安全关闭旧火山连接（不阻塞）"""
        try:
            await asyncio.wait_for(ws.close(), timeout=VOLC_CLOSE_TIMEOUT)
            print(f"[VoiceCall {self._request_id}] 旧连接 epoch={epoch} 已关闭")
        except asyncio.TimeoutError:
            print(f"[VoiceCall {self._request_id}] 旧连接 epoch={epoch} 关闭超时，强制终止")
        except Exception as e:
            print(f"[VoiceCall {self._request_id}] 旧连接 epoch={epoch} 关闭异常: {e}")

    def _fire_and_forget_close(self, ws, epoch: int):
        """Fire-and-forget：后台关闭旧连接，不阻塞"""
        if ws:
            asyncio.create_task(self._safe_close_volc_ws(ws, epoch))

    # ============== 火山连接（带重试） ==============

    async def connect_volc_with_retry(self, max_retries: int = VOLC_MAX_RETRIES, reset_baseline: bool = True) -> bool:
        """
        连接火山 ASR WebSocket，带重试机制。

        Args:
            max_retries: 最大重试次数
            reset_baseline: 是否重置基线（每条新连接都需要）
        """
        import uuid
        from app.core.asr_adapter import _get_asr_config, VOLC_ASR_URL
        import websockets

        cfg = _get_asr_config()
        headers = {
            "X-Api-Key": cfg["api_key"],
            "X-Api-Resource-Id": cfg["resource_id"],
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        for attempt in range(max_retries + 1):
            try:
                print(f"[VoiceCall {self._request_id}] 连接火山 ASR (尝试 {attempt + 1}/{max_retries + 1})...")

                try:
                    self.volc_ws = await asyncio.wait_for(
                        websockets.connect(
                            VOLC_ASR_URL,
                            additional_headers=headers,
                            ping_interval=None,
                            ping_timeout=None,
                            open_timeout=VOLC_OPEN_TIMEOUT,
                        ),
                        timeout=VOLC_OPEN_TIMEOUT + 1
                    )
                except TypeError:
                    self.volc_ws = await asyncio.wait_for(
                        websockets.connect(
                            VOLC_ASR_URL,
                            extra_headers=headers,
                            ping_interval=None,
                            ping_timeout=None,
                        ),
                        timeout=VOLC_OPEN_TIMEOUT + 1
                    )

                init_frame = _build_full_client_request()
                await asyncio.wait_for(self.volc_ws.send(init_frame), timeout=5.0)

                self._connected = True
                print(f"[VoiceCall {self._request_id}] 火山 ASR 连接成功")

                # 【关键】重置基线：每条新连接文本从 0 开始
                if reset_baseline:
                    await self._cancel_timer()
                    async with self._current_text_lock:
                        self._current_text = ""

                await self._flush_buffer()

                # 启动新接收循环（带 epoch）
                my_epoch = await self._get_epoch()
                asyncio.create_task(self.recv_loop(my_epoch))

                return True

            except asyncio.TimeoutError:
                print(f"[VoiceCall {self._request_id}] 火山 ASR 连接超时 (尝试 {attempt + 1}/{max_retries + 1})")
                if self.volc_ws:
                    self._fire_and_forget_close(self.volc_ws, await self._get_epoch())
                    self.volc_ws = None

            except Exception as e:
                print(f"[VoiceCall {self._request_id}] 火山 ASR 连接失败: {e} (尝试 {attempt + 1}/{max_retries + 1})")
                if self.volc_ws:
                    self._fire_and_forget_close(self.volc_ws, await self._get_epoch())
                    self.volc_ws = None

            if attempt < max_retries:
                await asyncio.sleep(VOLC_RETRY_DELAY)

        print(f"[VoiceCall {self._request_id}] 火山 ASR 连接失败，已重试 {max_retries} 次")
        await self._send_ws({
            "type": "error",
            "message": "语音连接繁忙，正在重试..."
        })
        return False

    # ============== 后台连接 ==============

    async def _start_volc_connection_background(self):
        """后台异步连接火山 ASR"""
        if self._connecting:
            return
        self._connecting = True

        try:
            # 首次连接需要重置基线
            success = await self.connect_volc_with_retry(max_retries=VOLC_MAX_RETRIES, reset_baseline=True)
            if not success:
                print(f"[VoiceCall {self._request_id}] 后台连接火山失败，音频将继续缓冲")
        finally:
            self._connecting = False

    # ============== 主动重连（每轮结束后） ==============

    async def _reconnect_for_next_turn(self):
        """
        回复结束后主动重连火山，迎接下一轮。
        使用 epoch 机制：旧连接自动退出，不阻塞新连接。
        """
        if self._reconnecting:
            print(f"[VoiceCall {self._request_id}] 已有重连在进行，跳过")
            return
        self._reconnecting = True

        print(f"[VoiceCall {self._request_id}] 回复完成，迎接下一轮...")

        try:
            # 1. epoch+1，标记旧连接失效
            new_epoch = await self._next_epoch()
            print(f"[VoiceCall {self._request_id}] 新 epoch={new_epoch}")

            # 2. Fire-and-forget：后台关闭旧连接，不阻塞
            old_ws = self.volc_ws
            old_epoch = new_epoch - 1
            self.volc_ws = None
            self._connected = False
            self._fire_and_forget_close(old_ws, old_epoch)

            # 3. 清本地状态
            await self._cancel_timer()
            async with self._current_text_lock:
                self._current_text = ""

            # 4. 立刻建新连接（不等待旧连接关闭）
            print(f"[VoiceCall {self._request_id}] 开始建立新连接...")
            success = await self.connect_volc_with_retry(max_retries=VOLC_MAX_RETRIES, reset_baseline=True)
            if success:
                print(f"[VoiceCall {self._request_id}] 下一轮火山连接就绪")
            else:
                print(f"[VoiceCall {self._request_id}] 下一轮火山连接失败")

        finally:
            self._reconnecting = False

    # ============== 自愈重连（兜底） ==============

    async def _self_heal_connection(self, error_epoch: int):
        """自愈重连：火山 error 帧时尝试重建连接一次"""
        # 检查 epoch：旧 epoch 的 error 直接忽略
        current_epoch = await self._get_epoch()
        if error_epoch < current_epoch:
            print(f"[VoiceCall {self._request_id}] 旧连接 epoch={error_epoch} 的 error，忽略")
            return

        if self._reconnecting:
            print(f"[VoiceCall {self._request_id}] 已有重连在进行，跳过自愈")
            return
        self._reconnecting = True

        print(f"[VoiceCall {self._request_id}] 火山连接异常，尝试自愈...")

        try:
            # epoch+1
            new_epoch = await self._next_epoch()

            # Fire-and-forget：后台关闭旧连接
            old_ws = self.volc_ws
            self.volc_ws = None
            self._connected = False
            self._fire_and_forget_close(old_ws, error_epoch)

            # 清本地状态
            await self._cancel_timer()
            async with self._current_text_lock:
                self._current_text = ""

            # 重连一次
            success = await self.connect_volc_with_retry(max_retries=1, reset_baseline=True)
            if success:
                print(f"[VoiceCall {self._request_id}] 自愈重连成功")
                await self._send_ws({"type": "status", "status": "reconnected"})
            else:
                print(f"[VoiceCall {self._request_id}] 自愈重连失败")

        finally:
            self._reconnecting = False

    # ============== 整段文本变化处理 ==============

    async def _on_result_text_changed(self, text: str, my_epoch: int):
        """result.text 发生变化时的处理"""
        # 检查 epoch：旧连接的文本忽略
        current_epoch = await self._get_epoch()
        if my_epoch < current_epoch:
            return

        if not text.strip():
            return

        async with self._current_text_lock:
            self._current_text = text

        await self._reset_stability_timer()

        # 打断检测：回复中检测到新内容
        if self._replying:
            if self._is_echo_of_last_final(text):
                # 只是刚说那句的尾巴/重复，不算打断
                return
            print(f"[VoiceCall {self._request_id}] 打断检测（新内容）: '{text}'")
            asyncio.create_task(self._handle_barge_in(text))

    async def _reset_stability_timer(self):
        """重置稳定定时器"""
        if self._stability_timer and not self._stability_timer.done():
            self._stability_timer.cancel()
            try:
                await self._stability_timer
            except asyncio.CancelledError:
                pass

        self._stability_timer = asyncio.create_task(self._stability_timeout())

    async def _stability_timeout(self):
        """稳定超时回调：1.5s 内 result.text 无变化，判定说完"""
        try:
            await asyncio.sleep(STABILITY_TIMEOUT)
        except asyncio.CancelledError:
            return

        async with self._current_text_lock:
            text = self._current_text
            self._current_text = ""

        if text.strip():
            print(f"[VoiceCall {self._request_id}] 稳定超时触发: '{text}'")
            asyncio.create_task(self._finalize_text(text))

    async def _cancel_timer(self):
        """取消稳定定时器"""
        if self._stability_timer and not self._stability_timer.done():
            self._stability_timer.cancel()
            try:
                await self._stability_timer
            except asyncio.CancelledError:
                pass
        self._stability_timer = None

    # ============== finalize 整段文本 ==============

    async def _finalize_text(self, text: str):
        """finalize 整段文本（触发一轮对话）"""
        text = text.strip()
        if not text:
            return

        # 【防重复 finalize】同一句的重复/延续（差个标点，4s 窗内）直接跳过，不触发第二轮
        if self._is_echo_of_last_final(text):
            print(f"[VoiceCall {self._request_id}] 忽略重复 finalize: '{text}'")
            return

        print(f"[VoiceCall {self._request_id}] finalize: '{text}'")
        self._last_finalized_text = text
        self._last_finalize_at = time.monotonic()

        # 推送 final
        await self._send_ws({"type": "final", "text": text})

        # 触发对话（后台异步）
        asyncio.create_task(self._get_figure_reply(text))

        # 重置本地状态（不重连火山，等回复结束后再重连）
        await self._cancel_timer()
        async with self._current_text_lock:
            self._current_text = ""

    # ============== 接收循环（带 epoch） ==============

    async def recv_loop(self, my_epoch: int):
        """接收火山 ASR 结果循环（带 epoch 检查）"""
        if not self.volc_ws:
            return

        print(f"[VoiceCall {self._request_id}] recv_loop 启动，epoch={my_epoch}")

        try:
            while self._connected:
                # 【关键】检查 epoch：旧连接自动退出
                current_epoch = await self._get_epoch()
                if my_epoch < current_epoch:
                    print(f"[VoiceCall {self._request_id}] recv_loop epoch={my_epoch} < current={current_epoch}，退出")
                    return

                try:
                    msg = await asyncio.wait_for(self.volc_ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    # 连接已关闭或异常，退出
                    print(f"[VoiceCall {self._request_id}] recv_loop 接收异常: {e}")
                    return

                if isinstance(msg, bytes):
                    result = _parse_server_response(msg)
                else:
                    try:
                        result = json.loads(msg)
                    except:
                        result = {"error": msg}

                if result.get("error"):
                    print(f"[VoiceCall {self._request_id}] 火山 error: {result['error']}")
                    # 自愈重连（检查 epoch）
                    asyncio.create_task(self._self_heal_connection(my_epoch))
                    return

                text = result.get("text", "") or ""

                if not text:
                    await self._cancel_timer()
                    continue

                async with self._current_text_lock:
                    last_text = self._current_text

                if text != last_text:
                    async with self._current_text_lock:
                        self._current_text = text
                    await self._send_ws({"type": "interim", "text": text})
                    await self._on_result_text_changed(text, my_epoch)

        except Exception as e:
            print(f"[VoiceCall {self._request_id}] recv_loop 异常: {e}")
        finally:
            print(f"[VoiceCall {self._request_id}] recv_loop epoch={my_epoch} 结束")

    # ============== 处理对话 ==============

    async def _get_figure_reply(self, user_text: str):
        """获取灵偶回复并播放（后台运行）"""
        async with self._reply_lock:
            self._replying = True

        # 【Barge-in】创建新的取消事件
        self._cancel_event = threading.Event()

        try:
            # 立即通知前端开始说话
            await self._send_ws({"type": "speaking", "status": "start"})

            # 【关键】回复一开始就重连火山，换一条干净连接：
            #  ① 上一句的尾巴落在已失效的旧连接上被忽略（彻底解决重复 finalize）
            #  ② 回复期间是干净基线，用户说新话就是新话，不带上一句前缀 → 打断能正常触发
            await self._reconnect_for_next_turn()

            # 获取事件循环，用于 audio_sink
            loop = asyncio.get_running_loop()
            
            # 构造 audio_sink：将音频字节通过 WebSocket 回传前端
            audio_sink = lambda b: asyncio.run_coroutine_threadsafe(self.ws.send_bytes(b), loop)

            # 构造 text_sink：将每句文字通过 WebSocket 回传前端
            text_sink = lambda s: asyncio.run_coroutine_threadsafe(
                self._send_ws({"type": "reply_chunk", "text": s}), loop
            )

            # 【关键修复】把阻塞的对话处理放到线程池，不阻塞事件循环
            result = await asyncio.to_thread(
                process_text_input,
                self.base_id,
                user_text,
                brain_mode_override="online",
                audio_sink=audio_sink,
                text_sink=text_sink,
                cancel_event=self._cancel_event,
            )
            reply = result.get("reply", "")
            brain_mode = result.get("brain_mode", "")
            tts_engine = result.get("tts_engine", "")

            await self._send_ws({
                "type": "reply",
                "reply": reply,
                "brain_mode": brain_mode,
                "tts_engine": tts_engine,
            })

            print(f"[VoiceCall {self._request_id}] 灵偶回复完成: '{reply[:30]}...'")

        except Exception as e:
            print(f"[VoiceCall {self._request_id}] 获取灵偶回复失败: {e}")
            await self._send_ws({"type": "error", "message": f"获取回复失败: {e}"})
            await self._send_ws({"type": "reply", "reply": "", "brain_mode": "offline", "tts_engine": ""})
        finally:
            await self._send_ws({"type": "speaking", "status": "end"})
            async with self._reply_lock:
                self._replying = False

            # 重置本地状态
            await self._cancel_timer()
            async with self._current_text_lock:
                self._current_text = ""

    # ============== 打断 ==============

    def _is_echo_of_last_final(self, text: str) -> bool:
        """判断 text 是否只是刚 finalize 那句的延续/重复（差个标点），避免同一句尾巴造成假打断。"""
        last = getattr(self, "_last_finalized_text", "")
        if not last:
            return False
        norm = lambda s: re.sub(r'[，。！？、,.!?\s]', '', s)
        nt, nl = norm(text), norm(last)
        if not nt:
            return False
        same_or_grow = (nt == nl)
        recent = (time.monotonic() - getattr(self, "_last_finalize_at", 0)) < 4.0
        return same_or_grow and recent

    async def _handle_barge_in(self, user_text: str):
        """打断：灵偶播放期间用户开口"""
        if not user_text.strip():
            return

        print(f"[VoiceCall {self._request_id}] 打断: '{user_text}'")

        # 【Barge-in】触发取消信号
        if self._cancel_event:
            self._cancel_event.set()
            print(f"[VoiceCall {self._request_id}] 已触发取消事件")

        # 通知前端立即停止播放音频
        await self._send_ws({"type": "stop_audio"})
        print(f"[VoiceCall {self._request_id}] 已发送 stop_audio 到前端")

        try:
            stop_playback()
            print(f"[VoiceCall {self._request_id}] 已停止当前播放")
        except Exception as e:
            print(f"[VoiceCall {self._request_id}] 停止播放失败: {e}")

        async with self._reply_lock:
            self._replying = False

        await self._cancel_timer()

        async with self._current_text_lock:
            self._current_text = ""

        await self._send_ws({"type": "barge_in", "text": user_text})

        # 打断后直接 finalize 这句话
        asyncio.create_task(self._finalize_text(user_text))

    # ============== WebSocket 发送 ==============

    async def _send_ws(self, data: dict):
        """发送消息给前端 WebSocket（静默处理断开）"""
        try:
            await self.ws.send_json(data)
        except Exception:
            pass

    # ============== 关闭 ==============

    async def close_volc(self):
        """关闭火山 ASR 连接"""
        self._connected = False
        self._replying = False

        # epoch+1，让所有旧循环退出
        await self._next_epoch()

        if self.volc_ws:
            self._fire_and_forget_close(self.volc_ws, await self._get_epoch())
            self.volc_ws = None

        await self._cancel_timer()


# ============== WebSocket 端点 ==============

@router.websocket("/stream")
async def asr_stream_ws(websocket: WebSocket, base_id: str = "BASE-001"):
    """语音通话 WebSocket"""
    await websocket.accept()

    ws_closed = False

    if not is_asr_available():
        await websocket.send_json({
            "type": "error",
            "message": "语音服务未配置（缺少 VOLC_ASR_API_KEY 或 VOLC_ASR_RESOURCE_ID）"
        })
        await websocket.close()
        return

    session = VoiceCallSession(websocket, base_id)

    # 立即推送聆听状态
    await session._send_ws({"type": "status", "status": "listening"})
    print(f"[VoiceCall {session._request_id}] 前端已连接，立即进入聆听中...")

    # 火山连接后台建立
    asyncio.create_task(session._start_volc_connection_background())

    try:
        while True:
            data = await websocket.receive_bytes()
            await session.send_audio(data)

    except WebSocketDisconnect:
        print(f"[VoiceCall {session._request_id}] 前端断开连接")
    except Exception as e:
        print(f"[VoiceCall {session._request_id}] WebSocket 异常: {e}")
        if not ws_closed:
            ws_closed = True
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
    finally:
        await session.close_volc()

        if not ws_closed:
            ws_closed = True
            try:
                await websocket.close()
            except Exception:
                pass


@router.get("/status")
def asr_status():
    """检查 ASR 服务状态"""
    return {
        "available": is_asr_available(),
        "message": "语音服务已配置" if is_asr_available() else "语音服务未配置",
    }