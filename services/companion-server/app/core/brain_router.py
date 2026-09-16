# services/companion-server/app/core/brain_router.py
"""
Brain router: routes to online_brain or offline_brain based on content/network.
Routing rules (plan.md §4.1):
  1. no ARK_API_KEY / network unreachable → offline_brain
  2. text ≤30 chars AND no real-time keywords → offline_brain
  3. otherwise → online_brain; on exception → fallback to offline_brain
"""

import os
import re
import threading
from typing import Dict, Tuple, Optional, List

from app.core.online_brain import (
    generate_online_reply,
    generate_online_reply_streaming,
    generate_online_reply_streaming_with_bot,
    should_use_bot_search,
    OnlineBrainError,
    _is_configured,
    _is_bot_configured,
)
from app.core.offline_brain import generate_offline_reply


# Real-time / factual keywords → route to online_brain
_REALTIME_PATTERNS = [
    r"今天天气",
    r"明天天气",
    r"现在几",
    r"时间",
    r"新闻",
    r"热搜",
    r"股价",
    r"股票",
    r"多少",
    r"who is",
    r"what is",
    r"how to",
    r"怎么做",
    r"是什么",
    r"哪个",
    r"哪里",
    r"什么电影",
    r"推荐",
]


def _is_short_offline_candidate(text: str) -> bool:
    """Return True if text is short AND no real-time keywords."""
    if len(text.strip()) > 30:
        return False
    for pat in _REALTIME_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return False
    return True


# In-memory forced-mode store (per-base override)
_forced_mode: Dict[str, str] = {}
_lock = threading.Lock()


def get_forced_mode(base_id: str) -> Optional[str]:
    with _lock:
        return _forced_mode.get(base_id)


def set_forced_mode(base_id: str, mode: str) -> None:
    """Set forced brain mode for a base: 'online' | 'offline' | 'auto'."""
    with _lock:
        if mode == "auto":
            _forced_mode.pop(base_id, None)
        else:
            _forced_mode[base_id] = mode


# Fallback reason tracking
_fallback_reasons: Dict[str, str] = {}


def get_fallback_reason(base_id: str) -> Optional[str]:
    return _fallback_reasons.get(base_id)


def _clear_fallback_reason(base_id: str) -> None:
    _fallback_reasons.pop(base_id, None)


def route_reply(
    figure: dict,
    user_input_text: str,
    base_id: str,
    history: Optional[List[dict]] = None,
    session_summary: str = "",
    forced_mode_override: Optional[str] = None,
    voice_pool_key: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Route to online_brain or offline_brain.
    Returns (reply_text, brain_mode).

    Args:
        session_summary: 上下文压缩摘要（长对话时注入 system prompt）
        forced_mode_override: 强制模式，可选 "online" | "offline" | None
            - 优先于底座的 get_forced_mode 设置
            - 语音通话时传 "online" 强制走在线
    """
    # 【关键修复】override 优先于底座设置
    mode = forced_mode_override or get_forced_mode(base_id)

    if mode == "offline":
        reply = generate_offline_reply(
            figure, user_input_text, voice_pool_key=voice_pool_key
        )
        return reply, "offline"

    if mode == "online":
        if not _is_configured():
            _fallback_reasons[base_id] = "forced_online_but_no_api_key"
            reply = generate_offline_reply(
                figure, user_input_text, voice_pool_key=voice_pool_key
            )
            return reply, "offline"
        try:
            reply = generate_online_reply(figure, user_input_text, history, session_summary)
            _clear_fallback_reason(base_id)
            return reply, "online"
        except OnlineBrainError as e:
            _fallback_reasons[base_id] = f"online_error:{str(e)[:50]}"
            reply = generate_offline_reply(
                figure, user_input_text, voice_pool_key=voice_pool_key
            )
            return reply, "offline"

    # Auto mode（mode is None）：API 已配置则直接尝试在线，离线只作兜底
    # Rule 1: no API key → offline
    if not _is_configured():
        _fallback_reasons[base_id] = "no_api_key"
        reply = generate_offline_reply(
            figure, user_input_text, voice_pool_key=voice_pool_key
        )
        return reply, "offline"

    # Rule 2: try online (auto 模式优先在线，删除短句判断)
    try:
        reply = generate_online_reply(figure, user_input_text, history, session_summary)
        _clear_fallback_reason(base_id)
        return reply, "online"
    except OnlineBrainError as e:
        _fallback_reasons[base_id] = f"online_error:{str(e)[:50]}"
        reply = generate_offline_reply(
            figure, user_input_text, voice_pool_key=voice_pool_key
        )
        return reply, "offline"


# ============== Streaming Route ==============

from typing import Generator


def route_reply_streaming(
    figure: dict,
    user_input_text: str,
    base_id: str,
    history: Optional[List[dict]] = None,
    session_summary: str = "",
    forced_mode_override: Optional[str] = None,
    voice_pool_key: Optional[str] = None,
    cancel_event=None,
) -> Generator[str, None, str]:
    """
    Streaming version of route_reply.
    Yields complete sentences as they are generated.
    Returns brain_mode when done.

    Args:
        session_summary: 上下文压缩摘要（长对话时注入 system prompt）
        forced_mode_override: 强制模式，可选 "online" | "offline" | None
            - 优先于底座的 get_forced_mode 设置
            - 语音通话时传 "online" 强制走在线
    """
    # 【关键修复】override 优先于底座设置
    mode = forced_mode_override or get_forced_mode(base_id)
    if cancel_event and cancel_event.is_set():
        return "cancelled"

    if mode == "offline":
        reply = generate_offline_reply(
            figure, user_input_text, voice_pool_key=voice_pool_key
        )
        yield reply
        return "offline"

    if mode == "online":
        if not _is_configured():
            _fallback_reasons[base_id] = "forced_online_but_no_api_key"
            reply = generate_offline_reply(
                figure, user_input_text, voice_pool_key=voice_pool_key
            )
            yield reply
            return "offline"
        try:
            # 【关键】判断是否需要 Bot 联网搜索
            need_bot = should_use_bot_search(user_input_text)
            if need_bot and _is_bot_configured():
                print(f"[路由] 检测到联网意图: '{user_input_text}' → Bot联网")
                # Bot 联网路径：generate_online_reply_streaming_with_bot 内部会走 Bot 搜索
                for sentence in generate_online_reply_streaming_with_bot(
                    figure,
                    user_input_text,
                    history,
                    session_summary,
                    cancel_event=cancel_event,
                ):
                    if cancel_event and cancel_event.is_set():
                        return "cancelled"
                    yield sentence
            else:
                # 普通在线路径
                for sentence in generate_online_reply_streaming(
                    figure,
                    user_input_text,
                    history,
                    session_summary,
                    cancel_event=cancel_event,
                ):
                    if cancel_event and cancel_event.is_set():
                        return "cancelled"
                    yield sentence
            _clear_fallback_reason(base_id)
            return "online"
        except OnlineBrainError as e:
            _fallback_reasons[base_id] = f"online_error:{str(e)[:50]}"
            reply = generate_offline_reply(
                figure, user_input_text, voice_pool_key=voice_pool_key
            )
            yield reply
            return "offline"

    # Auto mode（mode is None）：API 已配置则直接尝试在线，离线只作兜底
    if not _is_configured():
        _fallback_reasons[base_id] = "no_api_key"
        reply = generate_offline_reply(
            figure, user_input_text, voice_pool_key=voice_pool_key
        )
        yield reply
        return "offline"

    # Auto 模式优先在线（删除短句判断）
    try:
        for sentence in generate_online_reply_streaming(
            figure,
            user_input_text,
            history,
            session_summary,
            cancel_event=cancel_event,
        ):
            if cancel_event and cancel_event.is_set():
                return "cancelled"
            yield sentence
        _clear_fallback_reason(base_id)
        return "online"
    except OnlineBrainError as e:
        _fallback_reasons[base_id] = f"online_error:{str(e)[:50]}"
        reply = generate_offline_reply(
            figure, user_input_text, voice_pool_key=voice_pool_key
        )
        yield reply
        return "offline"
