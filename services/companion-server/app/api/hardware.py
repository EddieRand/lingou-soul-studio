# services/companion-server/app/api/hardware.py
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.response_engine import generate_touch_response
from app.core.voice_player import speak
from data.store import get_base, get_figure

router = APIRouter()


class SimulateRequest(BaseModel):
    base_id: str
    event_type: str


@router.post("/simulate")
def simulate_hardware(req: SimulateRequest):
    """
    Simulate a hardware touch event.
    Generates reply + plays audio via tts_adapter (volcano → system_say).
    """
    response = generate_touch_response(req.base_id, req.event_type)
    if not response:
        raise HTTPException(status_code=404, detail="Base or active figure not found")

    # Play audio for the touch response
    figure_id = response.get("figure_id")
    base = get_base(req.base_id)
    if figure_id and base:
        figure = get_figure(figure_id)
        if figure:
            voice_profile = figure.get("voice_profile", {})
            soul_profile = figure.get("soul_profile", {})
            speak(
                text=response.get("reply", ""),
                voice_profile=voice_profile,
                figure_id=figure_id,
                async_mode=True,
                soul_profile=soul_profile,
            )

    return response


@router.get("/system-voices")
def get_system_voices():
    """Return list of macOS say available voice names."""
    try:
        result = subprocess.run(
            ["say", "-v", "?"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().split("\n")
        voices = []
        for line in lines:
            parts = line.split()
            if parts:
                voice_name = parts[0]
                if voice_name not in ("Alex", "Alice", "Alva", "Zarvox", "Victoria", "Agnes", "Kathy"):
                    voices.append(voice_name)
        return voices
    except Exception:
        return ["Tingting", "Mei-Jia", "Yue", "Sin-ji", "Tingting"]
