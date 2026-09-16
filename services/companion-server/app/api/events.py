"""Owner-scoped user event APIs."""

from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from app.api.auth import get_current_user
from app.api.dev_tools import require_dev_tools
from app.api.ownership import current_user_id, owned_base_or_404, owned_figure_or_404
from app.core.response_engine import generate_touch_response
from data.store import list_events, save_event


router = APIRouter()


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_id: str
    event_type: str

    @field_validator("base_id", "event_type")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


@router.post("")
def receive_event(
    request: EventRequest,
    current_user: dict = Depends(get_current_user),
):
    """Receive a user-authenticated simulation event for an owned base."""
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

    save_event(
        {
            "event_id": str(uuid.uuid4()),
            "base_id": response["base_id"],
            "figure_id": response["figure_id"],
            "event_type": response["event"],
            "reply": response["reply"],
            "mood_before": response.get("mood_before", response["mood"]),
            "mood_after": response["mood"],
            "voice_profile_id": response["voice_profile_id"],
            "led_effect": response.get("led_effect"),
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        },
        user_id=owner_user_id,
    )
    return response


@router.get("/logs")
def get_event_logs(
    base_id: Optional[str] = None,
    figure_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    if base_id:
        owned_base_or_404(base_id, owner_user_id)
    if figure_id:
        owned_figure_or_404(figure_id, owner_user_id)
    return list_events(
        user_id=owner_user_id,
        base_id=base_id,
        figure_id=figure_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
