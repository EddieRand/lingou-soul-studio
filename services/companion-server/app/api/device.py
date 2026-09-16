"""Narrow HTTP surface used by development hardware bridges."""

from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.api.device_auth import require_current_device
from app.core.response_engine import generate_touch_response
from data.store import (
    DataIntegrityError,
    DeviceEventReplayError,
    register_device_event,
    save_event,
    validate_resource_id,
)


router = APIRouter()


class DeviceEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    event_id: Optional[str] = None
    occurred_at: Optional[datetime] = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 64:
            raise ValueError("event_type must be 1-64 characters")
        return value

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return validate_resource_id(value.strip(), "event_id")

    @model_validator(mode="after")
    def validate_event_identity(self):
        if (self.event_id is None) != (self.occurred_at is None):
            raise ValueError("event_id and occurred_at must be provided together")
        return self


@router.post("/events")
def receive_device_event(
    request: DeviceEventRequest,
    device: dict = Depends(require_current_device),
):
    """Accept one event for the base encoded in the device credential."""
    if device.get("credential_kind") == "production":
        if not request.event_id or request.occurred_at is None:
            raise HTTPException(
                status_code=422,
                detail="生产设备事件必须包含 event_id 和 occurred_at",
            )
        try:
            register_device_event(
                device["base_id"],
                request.event_id,
                request.occurred_at,
                owner_user_id=device["owner_user_id"],
            )
        except DeviceEventReplayError as exc:
            raise HTTPException(status_code=409, detail="设备事件重复或已过期") from exc
        except DataIntegrityError as exc:
            raise HTTPException(status_code=404, detail="资源不存在或不可访问") from exc
    event_id = request.event_id or str(uuid.uuid4())
    triggered_at = (
        request.occurred_at.astimezone(timezone.utc).isoformat()
        if request.occurred_at
        else datetime.now(timezone.utc).isoformat()
    )
    response = generate_touch_response(
        device["base_id"],
        request.event_type,
        owner_user_id=device["owner_user_id"],
    )
    if not response:
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")
    save_event(
        {
            "event_id": event_id,
            "base_id": response["base_id"],
            "figure_id": response["figure_id"],
            "event_type": response["event"],
            "reply": response["reply"],
            "mood_before": response.get("mood_before", response["mood"]),
            "mood_after": response["mood"],
            "voice_profile_id": response["voice_profile_id"],
            "led_effect": response.get("led_effect"),
            "triggered_at": triggered_at,
        },
        user_id=device["owner_user_id"],
    )
    return response
