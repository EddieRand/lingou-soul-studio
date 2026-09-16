"""Authenticated browser-side hardware simulation endpoints."""

import subprocess

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.auth import get_current_user
from app.api.dev_tools import require_dev_tools
from app.api.ownership import current_user_id, owned_base_or_404
from app.core.response_engine import generate_touch_response
from app.core.voice_player import speak
from data.store import figure_storage_key, get_figure


router = APIRouter()


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_id: str
    event_type: str


@router.post("/simulate")
def simulate_hardware(
    request: SimulateRequest,
    current_user: dict = Depends(get_current_user),
):
    require_dev_tools()
    owner_user_id = current_user_id(current_user)
    owned_base_or_404(request.base_id, owner_user_id)
    response = generate_touch_response(
        request.base_id,
        request.event_type,
        owner_user_id=owner_user_id,
    )
    if not response:
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")

    figure_id = response.get("figure_id")
    if figure_id:
        figure = get_figure(str(figure_id), user_id=owner_user_id)
        if figure:
            speak(
                text=response.get("reply", ""),
                voice_profile=figure.get("voice_profile", {}),
                figure_id=figure_storage_key(owner_user_id, str(figure_id)),
                async_mode=True,
                soul_profile=figure.get("soul_profile", {}),
            )
    return response


@router.get("/system-voices")
def get_system_voices():
    require_dev_tools()
    try:
        result = subprocess.run(
            ["say", "-v", "?"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        voices = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if parts and parts[0] not in (
                "Alex", "Alice", "Alva", "Zarvox", "Victoria", "Agnes", "Kathy"
            ):
                voices.append(parts[0])
        return voices
    except Exception:
        return ["Tingting", "Mei-Jia", "Yue", "Sin-ji", "Tingting"]
