# services/companion-server/app/core/dialogue_engine.py
"""
Dialogue engine: orchestrates full wake → reply → speak → emotion → memory chain.
Now uses brain_router for online/offline routing.
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Callable
import threading  # 新增：用于后台线程

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from data.store import get_base, get_figure, save_figure, save_dialogue_log, list_dialogue_logs

from app.core.dialogue_state import get_state, transition, reset
from app.core.wake_engine import detect_wake
from app.core.brain_router import route_reply, route_reply_streaming, should_use_bot_search
from app.core.online_brain import (
    generate_bridging_phrase, 
    _is_bot_configured,
    extract_city,
    is_weather_query,
    process_weather_query,
)
from app.core.voice_player import speak
from app.core.tts_adapter import speak_sentence_streaming, clear_playback_queue
from app.core.emotion_engine import apply_emotion_delta
from app.core.relationship_engine import update_streak


def wake_and_start_listening(base_id: str, trigger: str, text: Optional[str] = None) -> Tuple[Optional[dict], str]:
    """
    wake → listening transition.
    Returns (figure_dict, state) or (None, error_state) on failure.
    """
    success = detect_wake(base_id, trigger, text)
    if not success:
        return None, "idle"

    base = get_base(base_id)
    if not base:
        return None, "idle"
    figure_id = base.get("active_figure_id")
    if not figure_id:
        return None, "idle"

    owner = base.get("bound_user_id")
    figure = get_figure(figure_id, user_id=owner)
    if not figure:
        return None, "idle"

    state = get_state(base_id)
    return figure, state.state


def _load_recent_history(figure_id: str, limit: int = 6) -> list:
    """
    加载该灵偶最近的对话历史（用于在线大脑上下文记忆）。

    Returns:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
        最近 limit 轮对话，按时间正序。
    """
    try:
        logs = list_dialogue_logs(figure_id=figure_id, limit=limit)
        # logs 按时间倒序（最新的在前），需要反转
        logs = list(reversed(logs))
        history = []
        for log in logs:
            user_text = log.get("user_input_text", "")
            reply_text = log.get("reply_text", "")
            if user_text:
                history.append({"role": "user", "content": user_text})
            if reply_text:
                history.append({"role": "assistant", "content": reply_text})
        return history
    except Exception:
        return []


# ============== 上下文压缩摘要（缓存 + 后台线程） ==============

# 上下文压缩阈值：新增超过这个数量的历史才触发压缩
CONTEXT_COMPRESSION_THRESHOLD = 10

# 每次传给 LLM 的最大历史条数
MAX_HISTORY_FOR_LLM = 8

# 摘要缓存：{figure_id: {"summary": "...", "summarized_upto": N}}
_summary_cache: dict = {}

# 缓存锁（保护多线程访问）
_summary_cache_lock = threading.Lock()


def _summarize_conversation(history: list, figure: dict) -> str:
    """
    用 LLM 将长对话历史压缩成一段摘要。

    摘要包含：
    - 用户是谁、有什么特点
    - 聊过的关键事、约定
    - 情绪基调、关系状态

    Returns:
        压缩后的摘要字符串（100-200字）
    """
    from app.core.online_brain import _is_configured, _call_doubao

    if not _is_configured():
        return ""

    # 构造摘要 prompt
    figure_name = figure.get("name", "灵偶")
    soul = figure.get("soul_profile", {})
    archetype = soul.get("archetype", "软萌治愈型")

    # 把历史转成文本
    history_text = "\n".join([
        f"{'用户' if h.get('role') == 'user' else figure_name}: {h.get('content', '')}"
        for h in history
    ])

    summary_prompt = f"""你是{archetype}「{figure_name}」的对话记忆整理助手。

请把下面这段对话压缩成一段简短的摘要（100-150字），包含：
1. 用户的特点、身份（如养猫、喜欢什么）
2. 聊过的关键事情、约定
3. 对话的情绪基调

对话内容：
{history_text}

摘要格式：「用户是...。聊过...。对话氛围...。」"""

    try:
        summary = _call_doubao([{"role": "user", "content": summary_prompt}], timeout=10.0)
        # 确保摘要不太长
        if len(summary) > 200:
            summary = summary[:200] + "…"
        return summary
    except Exception as e:
        print(f"[DEBUG] 上下文压缩失败: {e}")
        return ""


def _get_cached_summary(figure_id: str) -> tuple:
    """
    获取缓存的摘要（线程安全）。

    Returns:
        (cached_summary, summarized_upto)
        - cached_summary: 缓存的摘要字符串
        - summarized_upto: 已压缩到的历史条数
    """
    with _summary_cache_lock:
        cache = _summary_cache.get(figure_id, {})
        return cache.get("summary", ""), cache.get("summarized_upto", 0)


def _update_summary_cache(figure_id: str, summary: str, summarized_upto: int):
    """更新摘要缓存（线程安全）"""
    with _summary_cache_lock:
        _summary_cache[figure_id] = {
            "summary": summary,
            "summarized_upto": summarized_upto,
        }


def _do_compress_sync(figure_id: str, figure: dict, current_count: int):
    """
    同步压缩历史（在后台线程执行，不阻塞事件循环）。
    """
    try:
        logs = list_dialogue_logs(figure_id=figure_id, limit=100)
        logs = list(reversed(logs))
        history = []
        for log in logs:
            user_text = log.get("user_input_text", "")
            reply_text = log.get("reply_text", "")
            if user_text:
                history.append({"role": "user", "content": user_text})
            if reply_text:
                history.append({"role": "assistant", "content": reply_text})

        summary = _summarize_conversation(history, figure)

        if summary:
            _update_summary_cache(figure_id, summary, current_count)
            print(f"[DEBUG] 后台压缩完成：{current_count} 条 → 摘要")
    except Exception as e:
        print(f"[DEBUG] 后台压缩失败: {e}")


def _background_compress_history(figure_id: str, figure: dict):
    """
    后台压缩历史（回复发出之后触发）。

    仅当"自上次压缩新增 ≥ CONTEXT_COMPRESSION_THRESHOLD 条"才触发。
    使用守护线程执行，不阻塞事件循环。
    """
    cached_summary, summarized_upto = _get_cached_summary(figure_id)

    logs = list_dialogue_logs(figure_id=figure_id, limit=100)
    current_count = len(logs)

    new_count = current_count - summarized_upto

    if new_count < CONTEXT_COMPRESSION_THRESHOLD:
        return

    print(f"[DEBUG] 后台压缩触发：新增 {new_count} 条历史")

    threading.Thread(
        target=_do_compress_sync,
        args=(figure_id, figure, current_count),
        daemon=True
    ).start()


def _load_history_fast(figure_id: str) -> tuple:
    """
    快速加载对话历史（不阻塞，用缓存摘要）。

    Returns:
        (history, session_summary)
        - history: 最近 N 轮逐字历史
        - session_summary: 缓存的摘要（如果有）
    """
    # 获取缓存的摘要
    cached_summary, summarized_upto = _get_cached_summary(figure_id)

    # 加载最近的历史（不压缩）
    logs = list_dialogue_logs(figure_id=figure_id, limit=MAX_HISTORY_FOR_LLM)
    logs = list(reversed(logs))

    history = []
    for log in logs:
        user_text = log.get("user_input_text", "")
        reply_text = log.get("reply_text", "")
        if user_text:
            history.append({"role": "user", "content": user_text})
        if reply_text:
            history.append({"role": "assistant", "content": reply_text})

    # 返回缓存摘要 + 最近历史
    return history, cached_summary


def process_text_input(base_id: str, text: str, brain_mode_override: Optional[str] = None, audio_sink: Optional[Callable[[bytes], None]] = None, text_sink: Optional[Callable[[str], None]] = None, cancel_event: Optional[threading.Event] = None) -> dict:
    """
    Full chain: state machine check → transcribing → thinking → brain_router → speaking → emotion update → memory → reset.

    Args:
        base_id: 底座 ID
        text: 用户输入文本
        brain_mode_override: 强制大脑模式，可选 "online" | "offline" | None
            - "online": 强制走在线流式管线（语音通话用）
            - "offline": 强制走离线管线
            - None: 按原有规则自动判断

    Returns dict with: reply, brain_mode, emotion_state, figure_id, base_id
    
    Phase C v2: 边生成边播放管线
      - online brain: LLM 流式产出句子 → 每句立即 TTS 播放（不等整段）
      - offline brain: 保持原有同步方式
    """
    if not text or not text.strip():
        return {"reply": "", "brain_mode": "offline", "emotion_state": {}, "error": "empty text"}

    # 新对话开始时清空播放队列（清理上一轮残留）
    clear_playback_queue()

    # Load figure
    base = get_base(base_id)
    if not base:
        return {"reply": "", "brain_mode": "offline", "emotion_state": {}, "error": "base not found"}

    figure_id = base.get("active_figure_id")
    if not figure_id:
        return {"reply": "", "brain_mode": "offline", "emotion_state": {}, "error": "no active figure"}

    owner = base.get("bound_user_id")
    figure = get_figure(figure_id, user_id=owner)
    if not figure:
        return {"reply": "", "brain_mode": "offline", "emotion_state": {}, "error": "figure not found"}

    state = get_state(base_id)
    if state.state not in ("listening", "wake_detected"):
        detect_wake(base_id, "double_tap")

    # Transition: listening → transcribing → thinking
    transition(base_id, "transcribing")
    transition(base_id, "thinking")

    voice_profile = figure.get("voice_profile", {})
    soul_profile = figure.get("soul_profile", {})
    tts_engine_used = "unknown"
    full_reply = ""
    city_to_save = None  # 城市记忆变量，两条路径都需要用到

    # 【关键修复】快速加载历史（不阻塞，用缓存摘要）
    history, session_summary = _load_history_fast(figure_id)

    # 【关键修复】把 brain_mode_override 透传给 brain_router
    # override 优先于底座设置，确保语音通话强制走在线
    forced_mode_override = brain_mode_override  # None | "online" | "offline"

    # Offline 路径
    if brain_mode_override == "offline" or (not brain_mode_override and forced_mode_override == "offline"):
        # Offline 路径：保持原有同步方式
        reply_text, brain_mode = route_reply(
            figure, text, base_id, history, session_summary,
            forced_mode_override=forced_mode_override
        )
        full_reply = reply_text
        transition(base_id, "speaking")
        speak_result = speak(
            text=reply_text,
            voice_profile=voice_profile,
            figure_id=figure_id,
            async_mode=True,
            soul_profile=soul_profile,
            force_offline=True,
        )
        tts_engine_used = speak_result.get("engine", "system_tts")
    else:
        # Online 流式管线：强制走在线（override="online" 时透传进来）
        brain_mode_holder: dict = {"mode": "online"}

        def track_brain_mode(bm: str) -> None:
            brain_mode_holder["mode"] = bm

        try:
            transition(base_id, "speaking")

            # 【新增】检查是否是天气查询，并处理城市逻辑
            is_weather = is_weather_query(text)
            query_to_use = text  # 默认使用原文本

            if is_weather and _is_bot_configured():
                weather_result = process_weather_query(text, figure)
                if weather_result['should_search']:
                    # 走联网搜索，使用补全后的查询
                    query_to_use = weather_result['query']
                    if weather_result.get('city_to_save'):
                        city_to_save = weather_result['city_to_save']
                else:
                    # 追问城市，不走联网
                    full_reply = weather_result['reply']
                    if text_sink:
                        text_sink(full_reply)
                    speak_sentence_streaming(
                        text=full_reply,
                        voice_profile=voice_profile,
                        figure_id=figure_id,
                        async_mode=True,
                        force_offline=False,
                        soul_profile=soul_profile,
                        audio_sink=audio_sink,
                        cancel_event=cancel_event,
                    )
                    brain_mode = "online"
                    tts_engine_used = "volcano_tts_streaming"
                    # 跳过后续逻辑，直接保存并返回
                    current_emotion = figure.get("soul_profile", {}).get("emotion_state", {
                        "happy": 50, "lonely": 0, "attached": 0, "annoyed": 0, "attention": 0, "sleepy": 0,
                        "last_dialogue_at": None,
                    })
                    if state.wake_source in ("double_tap", "long_press"):
                        current_emotion = apply_emotion_delta(current_emotion, "double_tap")
                    else:
                        current_emotion = apply_emotion_delta(current_emotion, "light_touch")
                    soul = figure.get("soul_profile", {})
                    soul["emotion_state"] = current_emotion
                    figure["soul_profile"] = soul
                    figure["updated_at"] = datetime.utcnow().isoformat()
                    save_figure(figure_id, figure, user_id=owner)
                    now_iso = datetime.utcnow().isoformat()
                    dialogue_log = {
                        "dialogue_id": f"{base_id}-{datetime.utcnow().timestamp()}",
                        "figure_id": figure_id,
                        "base_id": base_id,
                        "wake_source": state.wake_source or "manual_debug",
                        "user_input_text": text,
                        "reply_text": full_reply,
                        "brain_mode": brain_mode,
                        "tts_engine": tts_engine_used,
                        "emotion_at": dict(current_emotion),
                        "memory_candidate": full_reply,
                        "created_at": now_iso,
                    }
                    save_dialogue_log(dialogue_log)
                    reset(base_id)
                    return {
                        "reply": full_reply,
                        "brain_mode": brain_mode,
                        "tts_engine": tts_engine_used,
                        "emotion_state": current_emotion,
                        "figure_id": figure_id,
                        "base_id": base_id,
                    }

            # 【新增】检查非天气对话中是否提到城市，保存到记忆
            if not is_weather:
                mentioned_city = extract_city(text)
                if mentioned_city:
                    city_to_save = mentioned_city

            # 【新增】联网查询时先播放过场语（仅天气或其他联网查询）
            need_bot = should_use_bot_search(text)
            if need_bot and _is_bot_configured():
                bridging = generate_bridging_phrase(figure)
                print(f"[过场语] 检测到联网意图，播放过场语: '{bridging}'")
                speak_sentence_streaming(
                    text=bridging,
                    voice_profile=voice_profile,
                    figure_id=figure_id,
                    async_mode=True,
                    force_offline=False,
                    soul_profile=soul_profile,
                    audio_sink=audio_sink,
                    cancel_event=cancel_event,
                )
                full_reply += bridging
                if text_sink:
                    text_sink(bridging)

            # 流式产出句子，每句立即 TTS 播放
            sentence_idx = 0
            streaming_gen = route_reply_streaming(
                figure, query_to_use, base_id, history, session_summary,
                forced_mode_override=forced_mode_override
            )
            brain_mode = "online"
            # 捕获生成器的真实返回值（实际走的 brain_mode）
            try:
                while True:
                    # 【Barge-in】每次循环检查是否被打断
                    if cancel_event and cancel_event.is_set():
                        print("[Barge-in] 检测到打断，停止生成")
                        break
                    sentence = next(streaming_gen)
                    full_reply += sentence
                    sentence_idx += 1
                    if text_sink:
                        text_sink(sentence)
                    speak_sentence_streaming(
                        text=sentence,
                        voice_profile=voice_profile,
                        figure_id=figure_id,
                        async_mode=True,
                        force_offline=False,
                        soul_profile=soul_profile,
                        audio_sink=audio_sink,
                        cancel_event=cancel_event,
                    )
            except StopIteration as si:
                # generator return 值就是 brain_mode
                brain_mode = si.value if si.value else "online"
            
            tts_engine_used = "volcano_tts_streaming"
        except Exception as e:
            # 流式失败，降级到离线
            print(f"[DEBUG streaming failed] {e}", flush=True)
            reply_text, brain_mode = route_reply(
                figure, text, base_id, history, session_summary,
                forced_mode_override=forced_mode_override
            )
            full_reply = reply_text
            speak_result = speak(
                text=reply_text,
                voice_profile=voice_profile,
                figure_id=figure_id,
                async_mode=True,
                soul_profile=soul_profile,
                force_offline=True,
            )
            tts_engine_used = speak_result.get("engine", "system_tts")

    # Update emotion: attached+1 (普通对话), attention+10 (double_tap/wake)
    current_emotion = figure.get("soul_profile", {}).get("emotion_state", {
        "happy": 50, "lonely": 0, "attached": 0, "annoyed": 0, "attention": 0, "sleepy": 0,
        "last_dialogue_at": None,
    })
    if state.wake_source in ("double_tap", "long_press"):
        current_emotion = apply_emotion_delta(current_emotion, "double_tap")
    else:
        current_emotion = apply_emotion_delta(current_emotion, "light_touch")

    # Persist emotion
    soul = figure.get("soul_profile", {})
    soul["emotion_state"] = current_emotion
    soul["updated_at"] = datetime.utcnow().isoformat()

    # Update memory
    memory = figure.get("memory", {})
    memory["figure_id"] = figure_id
    memory["interaction_count"] = memory.get("interaction_count", 0) + 1
    memory["last_interaction_at"] = datetime.utcnow().isoformat()
    
    # 【新增】保存用户城市到记忆
    if city_to_save:
        memory["user_city"] = city_to_save
        print(f"[城市记忆] 保存城市: {city_to_save}")
    
    memory_candidate = full_reply
    if len(full_reply) < 50 and full_reply not in memory.get("favorite_responses", []):
        favs = memory.get("favorite_responses", [])
        favs.append(full_reply)
        memory["favorite_responses"] = favs[-10:]
    
    # Phase C: 更新 streak_days
    update_streak(figure)
    memory = figure.get("memory", {})  # 重新获取（update_streak 可能修改了 memory）

    # Build emotion snapshot for dialogue log
    emotion_snapshot = dict(current_emotion)

    # Save updated figure
    figure["soul_profile"] = soul
    figure["memory"] = memory
    figure["updated_at"] = datetime.utcnow().isoformat()
    save_figure(figure_id, figure, user_id=owner)

    # Save dialogue log
    now_iso = datetime.utcnow().isoformat()
    dialogue_log = {
        "dialogue_id": f"{base_id}-{datetime.utcnow().timestamp()}",
        "figure_id": figure_id,
        "base_id": base_id,
        "wake_source": state.wake_source or "manual_debug",
        "user_input_text": text,
        "reply_text": full_reply,
        "brain_mode": brain_mode,
        "tts_engine": tts_engine_used,
        "emotion_at": emotion_snapshot,
        "memory_candidate": memory_candidate,
        "created_at": now_iso,
    }
    save_dialogue_log(dialogue_log)

    # 【关键修复】回复发出后触发后台压缩（不阻塞）
    _background_compress_history(figure_id, figure)

    # Reset to idle
    reset(base_id)

    return {
        "reply": full_reply,
        "brain_mode": brain_mode,
        "tts_engine": tts_engine_used,
        "emotion_state": current_emotion,
        "figure_id": figure_id,
        "base_id": base_id,
    }
