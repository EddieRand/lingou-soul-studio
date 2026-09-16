"""Owner-checked brain mode diagnostics."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.auth import get_current_user
from app.api.dev_tools import require_dev_tools
from app.api.ownership import current_user_id, owned_base_or_404
from app.core.brain_router import get_fallback_reason, get_forced_mode, set_forced_mode
from app.core.online_brain import _get_config
from app.core.tts_adapter import is_voice_pool_ready
from data.store import figure_storage_key


router = APIRouter()


class BrainModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["online", "offline", "auto"]


@router.get("/status")
def brain_status(
    base_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    cfg = _get_config()
    has_key = bool(cfg["api_key"] and cfg["endpoint_id"])
    base = owned_base_or_404(base_id, owner_user_id) if base_id else None
    forced_mode = get_forced_mode(base_id) if base_id else None

    voice_pool_ready = False
    if base and base.get("active_figure_id"):
        voice_pool_ready = is_voice_pool_ready(
            figure_storage_key(owner_user_id, str(base["active_figure_id"]))
        )

    return {
        "has_api_key": has_key,
        "api_key_set": bool(cfg["api_key"]),
        "endpoint_id_set": bool(cfg["endpoint_id"]),
        "base_url": cfg["base_url"],
        "forced_mode": forced_mode or "auto",
        "network_ok": None,
        "fallback_reason": get_fallback_reason(base_id) if base_id else None,
        "voice_pool_ready": voice_pool_ready,
    }


@router.post("/mode")
def set_brain_mode(
    request: BrainModeRequest,
    base_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    require_dev_tools()
    owner_user_id = current_user_id(current_user)
    if base_id:
        owned_base_or_404(base_id, owner_user_id)
        set_forced_mode(base_id, request.mode)
    return {"mode": request.mode, "base_id": base_id}
