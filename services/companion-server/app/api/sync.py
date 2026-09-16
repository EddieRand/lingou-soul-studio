"""Owner-derived sync APIs.

The authenticated Bearer subject is the only namespace selector. Client
payloads cannot select or inject an owner, and legacy migration is unavailable
through the online API.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import get_current_user
from app.api.ownership import current_user_id, owned_base_or_404, owned_figure_or_404
from data.store import (
    append_sync_item,
    flush_sync_queue,
    get_cloud_data,
    get_sync_queue,
    save_cloud_data,
)


router = APIRouter()
_OWNER_FIELDS = {"user_id", "owner_id", "owner_user_id", "bound_user_id"}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncQueueRequest(_StrictModel):
    figure_id: str
    type: str
    data: dict


class CloudSyncRequest(_StrictModel):
    figures: list[dict] = Field(default_factory=list)
    dialogue_logs: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    last_sync_at: Optional[str] = None


class CloudSyncResponse(_StrictModel):
    success: bool
    message: str
    synced_at: str
    figures_count: int
    logs_count: int
    events_count: int
    conflicts: list[dict] = Field(default_factory=list)


def _validate_record(
    raw: dict,
    owner_user_id: str,
    *,
    require_figure: bool = False,
    require_base: bool = False,
) -> dict:
    if any(field in raw for field in _OWNER_FIELDS):
        raise HTTPException(status_code=422, detail="同步记录不能包含归属字段")
    record = deepcopy(raw)
    figure_id = record.get("figure_id")
    base_id = record.get("base_id")
    if require_figure and not figure_id:
        raise HTTPException(status_code=422, detail="同步记录缺少 figure_id")
    if require_base and not base_id:
        raise HTTPException(status_code=422, detail="同步记录缺少 base_id")
    if figure_id:
        owned_figure_or_404(str(figure_id), owner_user_id)
    if base_id:
        owned_base_or_404(str(base_id), owner_user_id)
    record["schema_version"] = 2
    record["owner_user_id"] = owner_user_id
    return record


def _replace_or_append(records: list[dict], incoming: dict, key: str) -> None:
    incoming_id = incoming.get(key)
    if not incoming_id:
        raise HTTPException(status_code=422, detail=f"同步记录缺少 {key}")
    for index, existing in enumerate(records):
        if existing.get(key) == incoming_id:
            records[index] = incoming
            return
    records.append(incoming)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="last_sync_at 不是合法时间") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _newer_than(record: dict, field: str, threshold: Optional[datetime]) -> bool:
    if threshold is None:
        return True
    raw = record.get(field)
    if not raw:
        return False
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return value.astimezone(timezone.utc) > threshold


def _upload(request: CloudSyncRequest, owner_user_id: str) -> CloudSyncResponse:
    cloud = get_cloud_data(owner_user_id)
    figures = list(cloud.get("figures", []))
    logs = list(cloud.get("dialogue_logs", []))
    events = list(cloud.get("events", []))

    for raw in request.figures:
        _replace_or_append(
            figures,
            _validate_record(raw, owner_user_id, require_figure=True),
            "figure_id",
        )
    for raw in request.dialogue_logs:
        _replace_or_append(
            logs,
            _validate_record(raw, owner_user_id, require_figure=True),
            "dialogue_id",
        )
    for raw in request.events:
        _replace_or_append(
            events,
            _validate_record(
                raw,
                owner_user_id,
                require_figure=True,
                require_base=True,
            ),
            "event_id",
        )

    saved = save_cloud_data(
        owner_user_id,
        {
            "schema_version": 2,
            "owner_user_id": owner_user_id,
            "figures": figures,
            "dialogue_logs": logs,
            "events": events,
        },
    )
    return CloudSyncResponse(
        success=True,
        message="Upload completed",
        synced_at=str(saved["synced_at"]),
        figures_count=len(figures),
        logs_count=len(logs),
        events_count=len(events),
        conflicts=[],
    )


def _download(owner_user_id: str, last_sync_at: Optional[str]) -> dict[str, Any]:
    threshold = _parse_timestamp(last_sync_at)
    cloud = get_cloud_data(owner_user_id)
    figures = [
        item for item in cloud.get("figures", [])
        if _newer_than(item, "updated_at", threshold)
    ]
    logs = [
        item for item in cloud.get("dialogue_logs", [])
        if _newer_than(item, "created_at", threshold)
    ]
    events = [
        item for item in cloud.get("events", [])
        if _newer_than(item, "triggered_at", threshold)
    ]
    return {
        "figures": figures,
        "dialogue_logs": logs,
        "events": events,
        "synced_at": cloud.get("synced_at"),
        "total_figures": len(cloud.get("figures", [])),
        "total_logs": len(cloud.get("dialogue_logs", [])),
        "total_events": len(cloud.get("events", [])),
    }


@router.get("")
def get_sync_queue_endpoint(current_user: dict = Depends(get_current_user)):
    return get_sync_queue(user_id=current_user_id(current_user))


@router.post("")
def queue_sync_item(
    request: SyncQueueRequest,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    owned_figure_or_404(request.figure_id, owner_user_id)
    if any(field in request.data for field in _OWNER_FIELDS):
        raise HTTPException(status_code=422, detail="同步记录不能包含归属字段")
    return append_sync_item(
        request.figure_id,
        request.type,
        request.data,
        user_id=owner_user_id,
    )


@router.post("/flush")
def flush_sync_queue_endpoint(
    queue_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    return flush_sync_queue(queue_id, user_id=current_user_id(current_user))


@router.post("/upload", response_model=CloudSyncResponse)
def upload_to_cloud(
    request: CloudSyncRequest,
    current_user: dict = Depends(get_current_user),
):
    return _upload(request, current_user_id(current_user))


@router.post("/download")
def download_from_cloud(
    last_sync_at: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    return _download(current_user_id(current_user), last_sync_at)


@router.post("/sync")
def full_sync(
    request: CloudSyncRequest,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    upload = _upload(request, owner_user_id)
    return {
        "upload": upload,
        "download": _download(owner_user_id, request.last_sync_at),
        "message": "Full sync completed",
    }
