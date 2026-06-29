# services/companion-server/app/api/events.py
import sys
from pathlib import Path
from datetime import datetime
import uuid
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data.store import save_event, list_events
from app.core.response_engine import generate_touch_response

router = APIRouter()


class EventRequest(BaseModel):
    base_id: str
    event_type: str


@router.post("")
def receive_event(req: EventRequest):
    """Receive a hardware event and generate a short response."""
    response = generate_touch_response(req.base_id, req.event_type)
    if not response:
        raise HTTPException(status_code=404, detail="Base or active figure not found")

    # Basic event log save (full version Day 5)
    event_log = {
        "event_id": str(uuid.uuid4()),
        "base_id": response["base_id"],
        "figure_id": response["figure_id"],
        "event_type": response["event"],
        "reply": response["reply"],
        "mood_before": response.get("mood_before", response["mood"]),
        "mood_after": response["mood"],
        "voice_profile_id": response["voice_profile_id"],
        "led_effect": response.get("led_effect"),
        "triggered_at": datetime.utcnow().isoformat(),
    }
    save_event(event_log)

    return response


@router.get("/logs")
def get_event_logs(
    base_id: Optional[str] = None,
    figure_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
):
    """Query event logs."""
    return list_events(
        base_id=base_id,
        figure_id=figure_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
