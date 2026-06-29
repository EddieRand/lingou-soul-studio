# services/companion-server/app/api/dialogue.py
import sys
import threading
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dialogue_state import get_state, transition
from app.core.dialogue_engine import wake_and_start_listening, process_text_input
from app.core.memory_engine import extract_memory_async
from app.core.relationship_engine import add_points
from data.store import get_base, get_figure, list_dialogue_logs, save_figure

router = APIRouter()


class WakeRequest(BaseModel):
    base_id: str
    trigger: str  # "voice_wake" | "double_tap" | "long_press"
    text: Optional[str] = None


class TextRequest(BaseModel):
    base_id: str
    text: str
    brain_mode_override: Optional[str] = None  # 可选：强制 "online" | "offline"


class MemorySummaryRequest(BaseModel):
    figure_id: str


@router.post("/wake")
def dialogue_wake(req: WakeRequest):
    """
    Wake dialogue: detect wake and enter listening state.
    Bug fix: if base/figure exists but wake name doesn't match, return 200 {woken:false}.
    Only raise 404 if base or active figure truly doesn't exist.
    """
    # First check: base must exist
    base = get_base(req.base_id)
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    # Figure must exist
    figure_id = base.get("active_figure_id")
    if not figure_id:
        raise HTTPException(status_code=404, detail="No active figure on this base")

    figure = get_figure(figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="Active figure not found")

    # Now try wake detection
    figure_ret, state = wake_and_start_listening(req.base_id, req.trigger, req.text)
    if figure_ret is None:
        # Wake name didn't match (for voice_wake) - not a 404, return 200 with woken=false
        return {
            "woken": False,
            "state": "idle",
            "figure": {
                "figure_id": figure_id,
                "name": figure.get("name"),
                "archetype": figure.get("soul_profile", {}).get("archetype"),
            },
        }

    return {
        "woken": True,
        "state": state,
        "figure": {
            "figure_id": figure_ret.get("figure_id"),
            "name": figure_ret.get("name"),
            "archetype": figure_ret.get("soul_profile", {}).get("archetype"),
        },
    }


@router.post("/text")
def dialogue_text(req: TextRequest):
    """Process text input through dialogue engine (now uses brain_router)."""
    result = process_text_input(req.base_id, req.text, brain_mode_override=req.brain_mode_override)
    if "error" in result and not result.get("reply"):
        raise HTTPException(status_code=404, detail=result.get("error", "Processing failed"))
    
    # Phase C: 异步提取记忆 + 增加羁绊点（不阻塞对话）
    figure_id = result.get("figure_id")
    if figure_id:
        try:
            base = get_base(req.base_id)
            owner = base.get("bound_user_id") if base else None
            figure = get_figure(figure_id, user_id=owner)
            if figure:
                extract_memory_async(figure, req.text, user_id=owner)
                add_points(figure, "dialogue")
                save_figure(figure_id, figure, user_id=owner)
        except Exception:
            pass  # 提取失败不影响对话
    
    return {
        "reply": result["reply"],
        "brain_mode": result["brain_mode"],
        "tts_engine": result.get("tts_engine"),
        "emotion_state": result["emotion_state"],
        "figure_id": figure_id,
    }


@router.get("/state")
def get_dialogue_state(base_id: str):
    """Get current dialogue state for a base."""
    state = get_state(base_id)
    return {
        "state": state.state,
        "figure_id": state.figure_id,
        "base_id": state.base_id,
        "wake_source": state.wake_source,
        "started_at": state.started_at,
    }


@router.get("/logs")
def get_dialogue_log_list(
    figure_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
):
    """Query dialogue logs."""
    return list_dialogue_logs(
        figure_id=figure_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.post("/memory-summary")
def generate_memory_summary(req: MemorySummaryRequest):
    """
    Generate a memory summary from recent dialogue logs.
    MVP: rule-based summary from recent logs.
    Writes summary back to figure.memory.
    """
    figure = get_figure(req.figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    # Read recent dialogue logs
    recent_logs = list_dialogue_logs(figure_id=req.figure_id, limit=20)
    memory = figure.get("memory", {})
    address_user_as = figure.get("soul_profile", {}).get("address_user_as", "主人")

    # Rule-based summary generation
    interaction_count = memory.get("interaction_count", 0)
    last_interaction_at = memory.get("last_interaction_at", None)

    if not recent_logs:
        summary = f"和{address_user_as}还没有聊天记录~"
    else:
        total = len(recent_logs)
        last_text = recent_logs[0].get("user_input_text", "") if recent_logs else ""
        last_reply_snippet = recent_logs[0].get("reply_text", "")[:15] if recent_logs else ""

        if total == 1:
            summary = f"和{address_user_as}聊了1次，话题关于「{last_text[:10]}」"
        else:
            summary = f"和{address_user_as}共聊了{total}次。最近：「{last_text[:10]}」→ {last_reply_snippet}"

    # Write back to figure.memory
    memory["memory_summary"] = summary
    memory["last_interaction_at"] = last_interaction_at
    memory["interaction_count"] = interaction_count
    figure["memory"] = memory
    from datetime import datetime
    figure["updated_at"] = datetime.utcnow().isoformat()
    save_figure(req.figure_id, figure)

    return {
        "figure_id": req.figure_id,
        "summary": summary,
        "last_interaction_at": last_interaction_at,
        "interaction_count": interaction_count,
    }


# ============== Audio Dialogue (ASR Skeleton) =============

class InterruptRequest(BaseModel):
    base_id: str


class AudioDialogueRequest(BaseModel):
    base_id: str
    audio_path: str  # path to uploaded audio file on server


@router.post("/interrupt")
def dialogue_interrupt(req: InterruptRequest):
    """
    打断当前灵偶语音播放（barge-in）。
    调用 stop_playback() 立即停止当前音频 + 清空队列。
    """
    from app.core.tts_adapter import stop_playback

    stopped = stop_playback()
    return {
        "stopped": stopped,
        "message": "已停止播放" if stopped else "没有在播放",
    }


@router.post("/audio")
def dialogue_audio(req: AudioDialogueRequest):
    """
    Process audio input: ASR → dialogue_engine.
    MVP: ASR stub - raises NotImplementedError.
    Future: audio_path → asr_adapter.transcribe → process_text_input
    """
    from app.core.asr_adapter import transcribe, is_asr_available

    if not is_asr_available():
        raise HTTPException(
            status_code=501,
            detail="ASR not yet implemented. Use /api/dialogue/text for text input.",
        )

    try:
        user_text = transcribe(req.audio_path)
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="ASR not yet implemented.",
        )

    if not user_text or not user_text.strip():
        raise HTTPException(status_code=400, detail="ASR returned empty text")

    # Delegate to text dialogue
    result = process_text_input(req.base_id, user_text, brain_mode_override="online")
    if "error" in result and not result.get("reply"):
        raise HTTPException(status_code=404, detail=result.get("error", "Processing failed"))

    return {
        "reply": result["reply"],
        "transcribed_text": user_text,
        "brain_mode": result["brain_mode"],
        "emotion_state": result["emotion_state"],
        "figure_id": result.get("figure_id"),
    }
