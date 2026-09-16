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

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import threading
import time
from collections import deque
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.security.utils import get_authorization_scheme_param

from app.api.auth import consume_ws_ticket, require_current_user
from app.api.device_auth import (
    VOICE_STREAM_SCOPE,
    authenticate_device_credential,
    device_principal_from_authorization,
)
from app.core.asr_adapter import is_asr_available, _build_full_client_request, _build_audio_frame, _parse_server_response
from app.core.dialogue_state import reset
from app.core.tts_adapter import stop_playback
from app.core.dialogue_engine import process_text_input
from data.store import figure_storage_key, get_base_for_owner

router = APIRouter(prefix="/api/asr", tags=["asr"])

# 文本稳定超时时间（秒）
STABILITY_TIMEOUT = 1.5

# 火山连接超时和重试配置
VOLC_OPEN_TIMEOUT = 4.0   # 火山连接超时（秒）
VOLC_MAX_RETRIES = 2     # 最大重试次数
VOLC_RETRY_DELAY = 0.3   # 重试之间退避（秒）
VOLC_CLOSE_TIMEOUT = 2.0  # 旧连接关闭超时（秒）
WS_PROTOCOL = "lingou.asr.v1"
WS_TICKET_PROTOCOL_PREFIX = "lingou.ticket."
DEVICE_WS_PROTOCOL = "lingou.device.voice.v1"
DEVICE_AUDIO_FORMAT = "pcm"
DEVICE_AUDIO_SAMPLE_RATE = 24000
DEVICE_AUDIO_FRAME_BYTES = 4096
SESSION_REPLACED_CLOSE_CODE = 4410
DEVICE_AUTH_CLOSE_CODE = 4401
DEVICE_NOT_READY_CLOSE_CODE = 4404


class TurnCancellation:
    """Cancellation token that can serialize final persistence with cancel."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._callbacks: set = set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        with self._lock:
            self._event.set()
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def add_callback(self, callback) -> None:
        with self._lock:
            if self._event.is_set():
                run_now = True
            else:
                self._callbacks.add(callback)
                run_now = False
        if run_now:
            callback()

    def remove_callback(self, callback) -> None:
        with self._lock:
            self._callbacks.discard(callback)

    def run_if_active(self, callback) -> bool:
        with self._lock:
            if self._event.is_set():
                return False
            callback()
            return True


@dataclass
class VoiceTurn:
    turn_id: str
    sequence: int
    user_text: str
    cancel_event: TurnCancellation = field(default_factory=TurnCancellation)
    task: Optional[asyncio.Task] = None
    cancel_reason: Optional[str] = None
    timestamps: dict[str, float] = field(default_factory=dict)
    audio_sequence: int = 0
    audio_ids: set[str] = field(default_factory=set)
    audio_terminal_ids: set[str] = field(default_factory=set)
    audio_playback_stages: dict[str, str] = field(default_factory=dict)
    audio_stream_complete: bool = False
    audio_failed: bool = False
    playback_done: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def mark(self, name: str) -> None:
        self.timestamps.setdefault(name, time.monotonic())

    def metrics(self) -> dict[str, float]:
        origin = self.timestamps.get("speech_finalized", min(self.timestamps.values()))
        return {
            f"{name}_ms": round((value - origin) * 1000, 1)
            for name, value in self.timestamps.items()
        }


class VoiceSessionRegistry:
    """Single active voice connection per physical base, regardless of client."""

    def __init__(self):
        self._sessions: dict[str, VoiceCallSession] = {}
        self._lock = threading.RLock()

    def replace(self, session: "VoiceCallSession") -> Optional["VoiceCallSession"]:
        with self._lock:
            previous = self._sessions.get(session.base_id)
            self._sessions[session.base_id] = session
            return previous if previous is not session else None

    def discard(self, session: "VoiceCallSession") -> bool:
        with self._lock:
            if self._sessions.get(session.base_id) is session:
                self._sessions.pop(session.base_id, None)
                return True
            return False

    def is_current(self, session: "VoiceCallSession") -> bool:
        with self._lock:
            return self._sessions.get(session.base_id) is session


voice_session_registry = VoiceSessionRegistry()


class VoiceCallSession:
    """
    语音通话会话：管理单个 WebSocket 连接的 ASR → 对话编排。

    每轮一条火山连接：
      - 每条火山连接只处理一句话
      - finalize 后主动重连火山，迎接下一轮
      - 回复期间暂停向火山转发音频
      - epoch 机制：旧连接自动退出，不阻塞新连接
    """

    def __init__(
        self,
        websocket: WebSocket,
        base_id: str,
        owner_user_id: str,
        *,
        client_kind: str = "browser",
        output_audio_format: str = "mp3",
        output_sample_rate: int = 24000,
        max_audio_frame_bytes: Optional[int] = None,
    ):
        if output_audio_format not in {"mp3", "pcm"}:
            raise ValueError("output_audio_format must be mp3 or pcm")
        if output_sample_rate not in {16000, 24000}:
            raise ValueError("output_sample_rate must be 16000 or 24000")
        if max_audio_frame_bytes is not None and max_audio_frame_bytes <= 0:
            raise ValueError("max_audio_frame_bytes must be positive")
        self.ws = websocket
        self.base_id = base_id
        self.owner_user_id = owner_user_id
        self.client_kind = client_kind
        self.output_audio_format = output_audio_format
        self.output_sample_rate = output_sample_rate
        self.max_audio_frame_bytes = max_audio_frame_bytes
        self.session_id = str(uuid.uuid4())
        self._closed = False
        self._send_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._turn_sequence = 0
        self._active_turn: Optional[VoiceTurn] = None
        self._background_tasks: set[asyncio.Task] = set()
        base = get_base_for_owner(base_id, owner_user_id)
        active_figure_id = base.get("active_figure_id") if base else None
        self._playback_scope = (
            figure_storage_key(owner_user_id, str(active_figure_id))
            if active_figure_id
            else None
        )
        self.volc_ws = None  # 火山 ASR WebSocket
        self._connected = False  # 火山是否已连接并就绪
        self._replying = False  # 是否正在等待/播放灵偶回复
        self._request_id = self.session_id[:8]  # 用于日志标识

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
        self._barge_in_pending = False

        self._last_finalized_text = ""
        self._last_finalize_at = 0.0

    def _spawn_task(self, coroutine, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)

        def discard(completed: asyncio.Task) -> None:
            self._background_tasks.discard(completed)
            if not completed.cancelled():
                try:
                    completed.exception()
                except Exception:
                    pass

        task.add_done_callback(discard)
        return task

    def _turn_is_current(self, turn: VoiceTurn) -> bool:
        return (
            not self._closed
            and voice_session_registry.is_current(self)
            and self._active_turn is turn
            and not turn.cancel_event.is_set()
        )

    async def _emit_turn_metrics(
        self,
        turn: VoiceTurn,
        status: str,
        *,
        require_current: bool,
    ) -> None:
        payload = {
            "type": "turn_metrics",
            "turn_id": turn.turn_id,
            "turn_sequence": turn.sequence,
            "status": status,
            "started_at": turn.started_at,
            "timings": turn.metrics(),
        }
        print(
            "[VoiceTurnMetrics] "
            + json.dumps(
                {
                    **payload,
                    "session_id": self.session_id,
                    "base_id": self.base_id,
                    "owner_user_id": self.owner_user_id,
                    "client_kind": self.client_kind,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        await self._send_ws(
            payload,
            turn=turn if require_current else None,
        )

    async def _cancel_active_turn(
        self,
        reason: str,
        *,
        notify: bool = True,
    ) -> Optional[VoiceTurn]:
        task_to_wait: Optional[asyncio.Task] = None
        async with self._turn_lock:
            turn = self._active_turn
            if turn is None:
                return None
            self._active_turn = None
            self._replying = False
            turn.cancel_reason = reason
            turn.cancel_event.set()
            turn.mark("cancelled")
            task = turn.task
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
                task_to_wait = task

        if task_to_wait:
            await asyncio.gather(task_to_wait, return_exceptions=True)

        if self._playback_scope:
            try:
                stop_playback(self._playback_scope)
            except Exception:
                pass
        if notify and not self._closed:
            await self._send_ws(
                {
                    "type": "stop_audio",
                    "turn_id": turn.turn_id,
                    "reason": reason,
                }
            )
            await self._send_ws(
                {
                    "type": "turn_cancelled",
                    "turn_id": turn.turn_id,
                    "reason": reason,
                }
            )
        await self._emit_turn_metrics(
            turn,
            "cancelled",
            require_current=False,
        )
        return turn

    async def _begin_turn(self, user_text: str) -> VoiceTurn:
        if self._closed or not voice_session_registry.is_current(self):
            raise asyncio.CancelledError
        await self._cancel_active_turn("superseded")
        async with self._turn_lock:
            self._turn_sequence += 1
            turn = VoiceTurn(
                turn_id=str(uuid.uuid4()),
                sequence=self._turn_sequence,
                user_text=user_text,
            )
            turn.mark("speech_finalized")
            self._active_turn = turn
            self._replying = True
            return turn

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
        if self._closed:
            return
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
            self._spawn_task(
                self._safe_close_volc_ws(ws, epoch),
                name=f"voice-volc-close-{self.session_id}-{epoch}",
            )

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

        if self._closed:
            return False
        cfg = _get_asr_config()
        headers = {
            "X-Api-Key": cfg["api_key"],
            "X-Api-Resource-Id": cfg["resource_id"],
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        for attempt in range(max_retries + 1):
            if self._closed:
                return False
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
                self._spawn_task(
                    self.recv_loop(my_epoch),
                    name=f"voice-asr-recv-{self.session_id}-{my_epoch}",
                )

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
        if self._closed or self._connecting:
            return
        self._connecting = True

        try:
            # 首次连接需要重置基线
            success = await self.connect_volc_with_retry(max_retries=VOLC_MAX_RETRIES, reset_baseline=True)
            if success:
                await self._send_ws({"type": "status", "status": "ready"})
            else:
                print(f"[VoiceCall {self._request_id}] 后台连接火山失败，音频将继续缓冲")
        finally:
            self._connecting = False

    # ============== 主动重连（每轮结束后） ==============

    async def _reconnect_for_next_turn(self):
        """
        回复结束后主动重连火山，迎接下一轮。
        使用 epoch 机制：旧连接自动退出，不阻塞新连接。
        """
        if self._closed or self._reconnecting:
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
        if self._closed:
            return
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
        if self._closed or not voice_session_registry.is_current(self):
            return
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
        if self._replying and not self._barge_in_pending:
            if self._is_echo_of_last_final(text):
                # 只是刚说那句的尾巴/重复，不算打断
                return
            print(f"[VoiceCall {self._request_id}] 打断检测（新内容）: '{text}'")
            self._barge_in_pending = True
            self._spawn_task(
                self._handle_barge_in(text),
                name=f"voice-barge-in-{self.session_id}",
            )

    async def _reset_stability_timer(self):
        """重置稳定定时器"""
        if self._closed:
            return
        if self._stability_timer and not self._stability_timer.done():
            self._stability_timer.cancel()
            try:
                await self._stability_timer
            except asyncio.CancelledError:
                pass

        self._stability_timer = asyncio.create_task(
            self._stability_timeout(),
            name=f"voice-stability-{self.session_id}",
        )

    async def _stability_timeout(self):
        """稳定超时回调：1.5s 内 result.text 无变化，判定说完"""
        try:
            await asyncio.sleep(STABILITY_TIMEOUT)
        except asyncio.CancelledError:
            return
        if self._closed or not voice_session_registry.is_current(self):
            return

        async with self._current_text_lock:
            text = self._current_text
            self._current_text = ""

        if text.strip():
            print(f"[VoiceCall {self._request_id}] 稳定超时触发: '{text}'")
            self._spawn_task(
                self._finalize_text(text),
                name=f"voice-finalize-{self.session_id}",
            )

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
        if self._closed or not voice_session_registry.is_current(self):
            return
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
        turn = await self._begin_turn(text)

        # 推送 final
        await self._send_ws(
            {
                "type": "final",
                "turn_id": turn.turn_id,
                "turn_sequence": turn.sequence,
                "text": text,
            },
            turn=turn,
        )

        # 触发对话（后台异步）
        turn.task = self._spawn_task(
            self._get_figure_reply(turn),
            name=f"voice-reply-{self.session_id}-{turn.sequence}",
        )

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
            while self._connected and not self._closed:
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
                    self._spawn_task(
                        self._self_heal_connection(my_epoch),
                        name=f"voice-self-heal-{self.session_id}-{my_epoch}",
                    )
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

    async def _send_turn_audio(self, turn: VoiceTurn, payload: bytes) -> bool:
        if not payload or not self._turn_is_current(turn):
            return False
        async with self._send_lock:
            if not self._turn_is_current(turn):
                return False
            turn.audio_sequence += 1
            audio_id = f"{turn.turn_id}:{turn.audio_sequence}"
            turn.audio_ids.add(audio_id)
            envelope = {
                "type": "audio_output",
                "stage": "synthesized",
                "audio_id": audio_id,
                "content_type": (
                    "audio/mpeg"
                    if self.output_audio_format == "mp3"
                    else (
                        "audio/pcm;rate="
                        f"{self.output_sample_rate};channels=1;format=s16le"
                    )
                ),
                "audio_format": self.output_audio_format,
                "sample_rate": self.output_sample_rate,
                "channels": 1,
                "sample_format": (
                    "encoded" if self.output_audio_format == "mp3" else "s16le"
                ),
                "byte_length": len(payload),
                "session_id": self.session_id,
                "turn_id": turn.turn_id,
                "turn_sequence": turn.sequence,
            }
            try:
                turn.mark("first_audio_synthesized")
                await self.ws.send_json(envelope)
                if self.max_audio_frame_bytes:
                    chunks = [
                        payload[offset:offset + self.max_audio_frame_bytes]
                        for offset in range(0, len(payload), self.max_audio_frame_bytes)
                    ]
                    for index, chunk in enumerate(chunks):
                        if not self._turn_is_current(turn):
                            return False
                        await self.ws.send_json({
                            **envelope,
                            "type": "audio_chunk",
                            "stage": "transferring",
                            "chunk_index": index,
                            "chunk_count": len(chunks),
                            "chunk_byte_length": len(chunk),
                        })
                        await self.ws.send_bytes(chunk)
                else:
                    await self.ws.send_bytes(payload)
                turn.mark("first_audio")
                turn.mark("first_audio_transferred")
                await self.ws.send_json({
                    **envelope,
                    "stage": "transferred",
                })
                return True
            except Exception:
                turn.audio_failed = True
                return False

    async def handle_client_message(self, payload: dict) -> None:
        """Accept playback receipts and explicit device interruption."""
        if payload.get("type") == "cancel_turn":
            requested_session_id = payload.get("session_id")
            if requested_session_id and requested_session_id != self.session_id:
                return
            interrupted = await self._cancel_active_turn("client_cancel")
            await self._send_ws({
                "type": "cancel_ack",
                "interrupted_turn_id": interrupted.turn_id if interrupted else None,
            })
            return
        if payload.get("type") != "audio_playback":
            return
        turn = self._active_turn
        if (
            turn is None
            or payload.get("session_id") != self.session_id
            or payload.get("turn_id") != turn.turn_id
        ):
            return
        audio_id = str(payload.get("audio_id") or "")
        if audio_id not in turn.audio_ids:
            return

        stage = payload.get("stage")
        marks = {
            "decoded": "first_audio_decoded",
            "playback_started": "playback_started",
            "playback_completed": "playback_completed",
            "playback_failed": "playback_failed",
        }
        mark = marks.get(str(stage))
        if mark is None:
            return
        current_stage = turn.audio_playback_stages.get(audio_id)
        if current_stage is None:
            if stage != "decoded":
                return
        elif current_stage == "decoded":
            if stage == "decoded":
                return
            if stage != "playback_started":
                return
        elif current_stage == "playback_started":
            if stage == "playback_started":
                return
            if stage not in {"playback_completed", "playback_failed"}:
                return
        else:
            return
        turn.audio_playback_stages[audio_id] = str(stage)
        turn.mark(mark)
        if stage in {"playback_completed", "playback_failed"}:
            turn.audio_terminal_ids.add(audio_id)
            if stage == "playback_failed":
                turn.audio_failed = True
            if (
                turn.audio_stream_complete
                and turn.audio_terminal_ids.issuperset(turn.audio_ids)
            ):
                turn.playback_done.set()

    async def _send_turn_text(self, turn: VoiceTurn, text: str) -> bool:
        if not text or not self._turn_is_current(turn):
            return False
        sent = await self._send_ws(
            {"type": "reply_chunk", "text": text},
            turn=turn,
        )
        if sent:
            turn.mark("first_text")
        return sent

    async def _get_figure_reply(self, turn: VoiceTurn):
        """获取灵偶回复并播放（后台运行）"""
        try:
            if not self._turn_is_current(turn):
                return
            turn.mark("reply_started")
            # 立即通知前端开始说话
            await self._send_ws(
                {"type": "speaking", "status": "start"},
                turn=turn,
            )

            # 【关键】回复一开始就重连火山，换一条干净连接：
            #  ① 上一句的尾巴落在已失效的旧连接上被忽略（彻底解决重复 finalize）
            #  ② 回复期间是干净基线，用户说新话就是新话，不带上一句前缀 → 打断能正常触发
            await self._reconnect_for_next_turn()
            if not self._turn_is_current(turn):
                return

            # 获取事件循环，用于 audio_sink
            loop = asyncio.get_running_loop()

            def audio_sink(payload: bytes):
                if turn.cancel_event.is_set():
                    return False
                future = asyncio.run_coroutine_threadsafe(
                    self._send_turn_audio(turn, payload),
                    loop,
                )
                try:
                    return future.result(timeout=5)
                except Exception:
                    return False

            def text_sink(text: str):
                if turn.cancel_event.is_set():
                    return None
                future = asyncio.run_coroutine_threadsafe(
                    self._send_turn_text(turn, text),
                    loop,
                )
                try:
                    return future.result(timeout=5)
                except Exception:
                    return False

            # 【关键修复】把阻塞的对话处理放到线程池，不阻塞事件循环
            result = await asyncio.to_thread(
                process_text_input,
                self.base_id,
                turn.user_text,
                brain_mode_override="online",
                audio_sink=audio_sink,
                text_sink=text_sink,
                cancel_event=turn.cancel_event,
                audio_format=self.output_audio_format,
                audio_sample_rate=self.output_sample_rate,
                owner_user_id=self.owner_user_id,
                session_id=self.session_id,
                turn_id=turn.turn_id,
            )
            if not self._turn_is_current(turn) or result.get("cancelled"):
                return
            reply = result.get("reply", "")
            brain_mode = result.get("brain_mode", "")
            tts_engine = result.get("tts_engine", "")
            turn.mark("reply_completed")
            turn.audio_stream_complete = True

            await self._send_ws(
                {
                    "type": "reply",
                    "reply": reply,
                    "brain_mode": brain_mode,
                    "tts_engine": tts_engine,
                    "audio_status": (
                        "awaiting_playback" if turn.audio_ids else "failed"
                    ),
                },
                turn=turn,
            )

            if turn.audio_ids:
                if turn.audio_terminal_ids.issuperset(turn.audio_ids):
                    turn.playback_done.set()
                await self._send_ws(
                    {
                        "type": "audio_output",
                        "stage": "stream_complete",
                        "chunk_count": len(turn.audio_ids),
                    },
                    turn=turn,
                )
                try:
                    await asyncio.wait_for(turn.playback_done.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    turn.audio_failed = True
                    turn.mark("playback_timeout")
                    await self._send_ws(
                        {
                            "type": "audio_output",
                            "stage": "failed",
                            "error_code": "PLAYBACK_CONFIRMATION_TIMEOUT",
                            "message": "未收到终端播放完成确认",
                        },
                        turn=turn,
                    )
            else:
                turn.audio_failed = True
                turn.mark("audio_unavailable")
                await self._send_ws(
                    {
                        "type": "audio_output",
                        "stage": "failed",
                        "error_code": "NO_AUDIO_GENERATED",
                        "message": "回复文字已生成，但没有可播放音频",
                    },
                    turn=turn,
                )

            print(f"[VoiceCall {self._request_id}] 灵偶回复完成: '{reply[:30]}...'")

        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[VoiceCall {self._request_id}] 获取灵偶回复失败: {e}")
            if self._turn_is_current(turn):
                turn.mark("failed")
                await self._send_ws(
                    {"type": "error", "message": f"获取回复失败: {e}"},
                    turn=turn,
                )
                await self._send_ws(
                    {
                        "type": "reply",
                        "reply": "",
                        "brain_mode": "offline",
                        "tts_engine": "",
                    },
                    turn=turn,
                )
        finally:
            if self._turn_is_current(turn):
                await self._send_ws(
                    {"type": "speaking", "status": "end"},
                    turn=turn,
                )
                await self._emit_turn_metrics(
                    turn,
                    (
                        "completed"
                        if (
                            "reply_completed" in turn.timestamps
                            and not turn.audio_failed
                        )
                        else "audio_failed"
                        if "reply_completed" in turn.timestamps
                        else "failed"
                    ),
                    require_current=True,
                )
                async with self._turn_lock:
                    if self._active_turn is turn:
                        self._active_turn = None
                        self._replying = False
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
        try:
            if not user_text.strip() or self._closed:
                return
            print(f"[VoiceCall {self._request_id}] 打断: '{user_text}'")
            interrupted = await self._cancel_active_turn("barge_in")
            await self._cancel_timer()
            async with self._current_text_lock:
                self._current_text = ""
            await self._send_ws(
                {
                    "type": "barge_in",
                    "text": user_text,
                    "interrupted_turn_id": (
                        interrupted.turn_id if interrupted else None
                    ),
                }
            )
            await self._finalize_text(user_text)
        finally:
            self._barge_in_pending = False

    # ============== WebSocket 发送 ==============

    async def _send_ws(
        self,
        data: dict,
        *,
        turn: Optional[VoiceTurn] = None,
    ) -> bool:
        """发送消息给前端 WebSocket（静默处理断开）"""
        if self._closed or (turn is not None and not self._turn_is_current(turn)):
            return False
        payload = dict(data)
        payload.setdefault("session_id", self.session_id)
        if turn is not None:
            payload.setdefault("turn_id", turn.turn_id)
            payload.setdefault("turn_sequence", turn.sequence)
        async with self._send_lock:
            if self._closed or (
                turn is not None and not self._turn_is_current(turn)
            ):
                return False
            try:
                await self.ws.send_json(payload)
                return True
            except Exception:
                return False

    # ============== 关闭 ==============

    async def close_volc(self):
        """Cancel all session work and close the provider connection."""
        if self._closed:
            return
        self._closed = True
        self._connected = False
        await self._cancel_active_turn("session_closed", notify=False)

        # epoch+1，让所有旧循环退出
        await self._next_epoch()

        provider_ws = self.volc_ws
        self.volc_ws = None
        if provider_ws:
            await self._safe_close_volc_ws(provider_ws, await self._get_epoch())

        await self._cancel_timer()
        current_task = asyncio.current_task()
        tasks = [
            task for task in self._background_tasks
            if task is not current_task and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._buffer_lock:
            self._audio_buffer.clear()

    async def supersede(self, replacement_session_id: str) -> None:
        """Notify and close this connection when a newer base session wins."""
        if self._closed:
            return
        await self._send_ws(
            {
                "type": "session_replaced",
                "replacement_session_id": replacement_session_id,
            }
        )
        await self.close_volc()
        try:
            await self.ws.close(
                code=SESSION_REPLACED_CLOSE_CODE,
                reason="newer voice session connected",
            )
        except Exception:
            pass


# ============== WebSocket 端点 ==============

def _ticket_from_subprotocol_header(websocket: WebSocket) -> Optional[str]:
    """Read the one-use ticket without putting credentials in the URL."""
    raw_protocols = websocket.headers.get("sec-websocket-protocol", "")
    protocols = [value.strip() for value in raw_protocols.split(",") if value.strip()]
    if WS_PROTOCOL not in protocols:
        return None
    for protocol in protocols:
        if protocol.startswith(WS_TICKET_PROTOCOL_PREFIX):
            return protocol.removeprefix(WS_TICKET_PROTOCOL_PREFIX)
    return None

def _offered_protocols(websocket: WebSocket) -> set[str]:
    return {
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    }


async def _reject_voice_socket(
    websocket: WebSocket,
    *,
    protocol: str,
    code: int,
    reason: str,
) -> None:
    selected_protocol = protocol if protocol in _offered_protocols(websocket) else None
    await websocket.accept(subprotocol=selected_protocol)
    await websocket.close(code=code, reason=reason)


async def _serve_voice_socket(
    websocket: WebSocket,
    *,
    base_id: str,
    owner_user_id: str,
    client_kind: str,
    output_audio_format: str = "mp3",
    output_sample_rate: int = 24000,
    max_audio_frame_bytes: Optional[int] = None,
    device_credential: Optional[str] = None,
) -> None:
    ws_closed = False

    if not is_asr_available():
        await websocket.send_json({
            "type": "error",
            "message": "语音服务未配置（缺少 VOLC_ASR_API_KEY 或 VOLC_ASR_RESOURCE_ID）"
        })
        await websocket.close()
        return

    session = VoiceCallSession(
        websocket,
        base_id,
        owner_user_id,
        client_kind=client_kind,
        output_audio_format=output_audio_format,
        output_sample_rate=output_sample_rate,
        max_audio_frame_bytes=max_audio_frame_bytes,
    )
    previous = voice_session_registry.replace(session)
    if previous:
        await previous.supersede(session.session_id)

    # 立即推送聆听状态
    await session._send_ws({
        "type": "status",
        "status": "listening",
        "connection_policy": "newest_connection_wins",
        "client_kind": client_kind,
        "audio_format": output_audio_format,
        "audio_sample_rate": output_sample_rate,
    })
    print(
        f"[VoiceCall {session._request_id}] {client_kind} 已连接，立即进入聆听中..."
    )

    # 火山连接后台建立
    session._spawn_task(
        session._start_volc_connection_background(),
        name=f"voice-asr-connect-{session.session_id}",
    )

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if device_credential is not None:
                current_principal = authenticate_device_credential(
                    device_credential,
                    required_scope=VOICE_STREAM_SCOPE,
                )
                if (
                    current_principal is None
                    or str(current_principal.get("base_id")) != base_id
                    or str(current_principal.get("owner_user_id"))
                    != owner_user_id
                ):
                    ws_closed = True
                    await session.close_volc()
                    await websocket.close(
                        code=DEVICE_AUTH_CLOSE_CODE,
                        reason="device credential is no longer authorized",
                    )
                    return
            audio_data = message.get("bytes")
            if audio_data is not None:
                await session.send_audio(audio_data)
                continue
            text_data = message.get("text")
            if text_data is None:
                continue
            try:
                payload = json.loads(text_data)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                await session.handle_client_message(payload)

    except WebSocketDisconnect:
        print(f"[VoiceCall {session._request_id}] {client_kind} 断开连接")
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
        if voice_session_registry.discard(session):
            reset(base_id)

        if not ws_closed:
            ws_closed = True
            try:
                await websocket.close()
            except Exception:
                pass


@router.websocket("/stream")
async def asr_stream_ws(websocket: WebSocket, base_id: str):
    """Authenticated H5 voice-call WebSocket."""
    ticket = _ticket_from_subprotocol_header(websocket)
    current_user, close_code = consume_ws_ticket(ticket or "", base_id)
    if close_code:
        # Complete the handshake before closing so clients receive the 440x
        # application code. Authentication still precedes provider work.
        await _reject_voice_socket(
            websocket,
            protocol=WS_PROTOCOL,
            code=close_code,
            reason="authentication rejected",
        )
        return

    await websocket.accept(subprotocol=WS_PROTOCOL)
    await _serve_voice_socket(
        websocket,
        base_id=base_id,
        owner_user_id=str(current_user["user_id"]),
        client_kind="browser",
    )


@router.websocket("/device-stream")
async def asr_device_stream_ws(websocket: WebSocket):
    """Provisioned DNESP32S3 voice connection using its device credential."""
    authorization = websocket.headers.get("authorization")
    principal = device_principal_from_authorization(
        authorization,
        required_scope=VOICE_STREAM_SCOPE,
    )
    if principal is None or DEVICE_WS_PROTOCOL not in _offered_protocols(websocket):
        await _reject_voice_socket(
            websocket,
            protocol=DEVICE_WS_PROTOCOL,
            code=DEVICE_AUTH_CLOSE_CODE,
            reason="device authentication rejected",
        )
        return

    base_id = str(principal["base_id"])
    owner_user_id = str(principal["owner_user_id"])
    _scheme, device_credential = get_authorization_scheme_param(authorization)
    base = get_base_for_owner(base_id, owner_user_id)
    if not base or not base.get("active_figure_id"):
        await _reject_voice_socket(
            websocket,
            protocol=DEVICE_WS_PROTOCOL,
            code=DEVICE_NOT_READY_CLOSE_CODE,
            reason="base has no active figure",
        )
        return

    await websocket.accept(subprotocol=DEVICE_WS_PROTOCOL)
    await _serve_voice_socket(
        websocket,
        base_id=base_id,
        owner_user_id=owner_user_id,
        client_kind="device",
        output_audio_format=DEVICE_AUDIO_FORMAT,
        output_sample_rate=DEVICE_AUDIO_SAMPLE_RATE,
        max_audio_frame_bytes=DEVICE_AUDIO_FRAME_BYTES,
        device_credential=device_credential,
    )


@router.get("/status")
def asr_status(_current_user: dict = Depends(require_current_user)):
    """检查 ASR 服务状态"""
    available = is_asr_available()
    return {
        "available": available,
        "message": "语音服务已配置" if available else "语音服务未配置",
    }
