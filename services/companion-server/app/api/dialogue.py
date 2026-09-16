"""Owner-scoped dialogue APIs."""

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.auth import get_current_user
from app.api.ownership import (
    current_user_id,
    owned_base_or_404,
    owned_figure_or_404,
)
from app.core.dialogue_engine import process_text_input, wake_and_start_listening
from app.core.dialogue_state import get_state
from data.store import (
    figure_storage_key,
    list_dialogue_logs,
    save_figure,
)


router = APIRouter()


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WakeRequest(_StrictModel):
    base_id: str
    trigger: Literal["voice_wake", "double_tap", "long_press"]
    text: Optional[str] = None


class TextRequest(_StrictModel):
    base_id: str
    text: str
    brain_mode_override: Optional[Literal["online", "offline"]] = None


class MemorySummaryRequest(_StrictModel):
    figure_id: str


class InterruptRequest(_StrictModel):
    base_id: str


class AudioDialogueRequest(_StrictModel):
    base_id: str
    audio_path: str


@router.post("/wake")
def dialogue_wake(
    request: WakeRequest,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    base = owned_base_or_404(request.base_id, owner_user_id)
    figure_id = base.get("active_figure_id")
    if not figure_id:
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")
    figure = owned_figure_or_404(str(figure_id), owner_user_id)

    figure_ret, state = wake_and_start_listening(
        request.base_id,
        request.trigger,
        request.text,
        owner_user_id=owner_user_id,
    )
    if figure_ret is None:
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
def dialogue_text(
    request: TextRequest,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    owned_base_or_404(request.base_id, owner_user_id)
    result = process_text_input(
        request.base_id,
        request.text,
        brain_mode_override=request.brain_mode_override,
        owner_user_id=owner_user_id,
    )
    if "error" in result and not result.get("reply"):
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")

    return {
        "reply": result["reply"],
        "brain_mode": result["brain_mode"],
        "tts_engine": result.get("tts_engine"),
        "emotion_state": result["emotion_state"],
        "figure_id": result.get("figure_id"),
        "session_id": result.get("session_id"),
        "turn_id": result.get("turn_id"),
    }


@router.get("/state")
def get_dialogue_state(
    base_id: str,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    owned_base_or_404(base_id, owner_user_id)
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
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    if figure_id:
        owned_figure_or_404(figure_id, owner_user_id)
    return list_dialogue_logs(
        user_id=owner_user_id,
        figure_id=figure_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.post("/memory-summary")
def generate_memory_summary(
    request: MemorySummaryRequest,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    figure = owned_figure_or_404(request.figure_id, owner_user_id)
    recent_logs = list_dialogue_logs(
        user_id=owner_user_id,
        figure_id=request.figure_id,
        limit=20,
    )
    memory = figure.get("memory", {})
    address_user_as = figure.get("soul_profile", {}).get("address_user_as", "你")
    interaction_count = memory.get("interaction_count", 0)
    last_interaction_at = memory.get("last_interaction_at")
    if not recent_logs:
        summary = f"和{address_user_as}还没有聊天记录~"
    else:
        total = len(recent_logs)
        last_text = recent_logs[0].get("user_input_text", "")
        last_reply = recent_logs[0].get("reply_text", "")[:15]
        if total == 1:
            summary = f"和{address_user_as}聊了1次，话题关于「{last_text[:10]}」"
        else:
            summary = (
                f"和{address_user_as}共聊了{total}次。"
                f"最近：「{last_text[:10]}」→ {last_reply}"
            )
    memory["memory_summary"] = summary
    figure["memory"] = memory
    figure["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_figure(request.figure_id, figure, user_id=owner_user_id)
    return {
        "figure_id": request.figure_id,
        "summary": summary,
        "last_interaction_at": last_interaction_at,
        "interaction_count": interaction_count,
    }


@router.post("/interrupt")
def dialogue_interrupt(
    request: InterruptRequest,
    current_user: dict = Depends(get_current_user),
):
    from app.core.tts_adapter import stop_playback

    owner_user_id = current_user_id(current_user)
    base = owned_base_or_404(request.base_id, owner_user_id)
    figure_id = base.get("active_figure_id")
    stopped = False
    if figure_id:
        stopped = stop_playback(figure_storage_key(owner_user_id, str(figure_id)))
    return {
        "stopped": stopped,
        "message": "已停止播放" if stopped else "没有在播放",
    }


@router.post("/audio")
def dialogue_audio(
    request: AudioDialogueRequest,
    current_user: dict = Depends(get_current_user),
):
    from app.core.asr_adapter import is_asr_available, transcribe

    owner_user_id = current_user_id(current_user)
    owned_base_or_404(request.base_id, owner_user_id)
    if not is_asr_available():
        raise HTTPException(
            status_code=501,
            detail="ASR not yet implemented. Use /api/dialogue/text for text input.",
        )
    try:
        user_text = transcribe(request.audio_path)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="ASR not yet implemented.") from exc
    if not user_text or not user_text.strip():
        raise HTTPException(status_code=400, detail="ASR returned empty text")
    result = process_text_input(
        request.base_id,
        user_text,
        brain_mode_override="online",
        owner_user_id=owner_user_id,
    )
    if "error" in result and not result.get("reply"):
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")
    return {
        "reply": result["reply"],
        "transcribed_text": user_text,
        "brain_mode": result["brain_mode"],
        "emotion_state": result["emotion_state"],
        "figure_id": result.get("figure_id"),
        "session_id": result.get("session_id"),
        "turn_id": result.get("turn_id"),
    }
