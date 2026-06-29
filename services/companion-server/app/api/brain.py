# services/companion-server/app/api/brain.py
import sys
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.online_brain import _get_config
from app.core.brain_router import get_forced_mode, set_forced_mode, get_fallback_reason

router = APIRouter()


class BrainModeRequest(BaseModel):
    mode: str  # "online" | "offline" | "auto"


@router.get("/status")
def brain_status(base_id: Optional[str] = None):
    """Return brain status: mode, network_ok, has_api_key, voice_pool_ready."""
    cfg = _get_config()
    has_key = bool(cfg["api_key"] and cfg["endpoint_id"])
    forced_mode = get_forced_mode(base_id) if base_id else None

    # voice_pool_ready per base (based on active figure)
    voice_pool_ready = False
    if base_id:
        from data.store import get_base, get_figure
        from app.core.tts_adapter import is_voice_pool_ready
        base = get_base(base_id)
        if base:
            figure_id = base.get("active_figure_id")
            if figure_id:
                voice_pool_ready = is_voice_pool_ready(figure_id)

    return {
        "has_api_key": has_key,
        "api_key_set": bool(cfg["api_key"]),
        "endpoint_id_set": bool(cfg["endpoint_id"]),
        "base_url": cfg["base_url"],
        "forced_mode": forced_mode or "auto",
        "network_ok": None,  # Not actively checked in MVP
        "fallback_reason": get_fallback_reason(base_id) if base_id else None,
        "voice_pool_ready": voice_pool_ready,
    }


@router.post("/mode")
def set_brain_mode(req: BrainModeRequest, base_id: Optional[str] = None):
    """Force brain mode for a base (for demo purposes)."""
    if req.mode not in ("online", "offline", "auto"):
        return {"error": "mode must be online/offline/auto"}

    if base_id:
        set_forced_mode(base_id, req.mode)
    return {"mode": req.mode, "base_id": base_id}
