# services/companion-server/app/api/sync.py
import sys
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime

from data.store import (
    get_sync_queue, append_sync_item, flush_sync_queue,
    get_cloud_data, save_cloud_data,
    list_figures, get_figure, save_figure,
    list_dialogue_logs, save_dialogue_log,
    list_events, save_event,
)
from app.api.auth import get_current_user

router = APIRouter()


class SyncQueueRequest(BaseModel):
    figure_id: str
    type: str
    data: dict


class CloudSyncRequest(BaseModel):
    user_id: str
    figures: list = []
    dialogue_logs: list = []
    events: list = []
    last_sync_at: Optional[str] = None


class CloudSyncResponse(BaseModel):
    success: bool
    message: str
    synced_at: str
    figures_count: int
    logs_count: int
    events_count: int
    conflicts: list = []


def _resolve_conflict(local, remote, field="updated_at"):
    local_time = datetime.fromisoformat(local.get(field, "")[:-1] if local.get(field) else "2000-01-01T00:00:00")
    remote_time = datetime.fromisoformat(remote.get(field, "")[:-1] if remote.get(field) else "2000-01-01T00:00:00")
    if local_time > remote_time:
        return "local"
    return "remote"


@router.get("")
def get_sync_queue_endpoint(user_id: Optional[str] = None):
    """Return current sync queue."""
    return get_sync_queue(user_id=user_id)


@router.post("")
def queue_sync_item(req: SyncQueueRequest, user_id: Optional[str] = None):
    """
    Append a new item to the sync queue.
    Items are stored locally when offline and flushed when online.
    """
    queue = append_sync_item(req.figure_id, req.type, req.data, user_id=user_id)
    return queue


@router.post("/flush")
def flush_sync_queue_endpoint(queue_id: Optional[str] = None, user_id: Optional[str] = None):
    """
    Mark pending items as synced.
    If queue_id provided, flush that item only; otherwise flush all pending.
    """
    queue = flush_sync_queue(queue_id, user_id=user_id)
    return queue


@router.post("/upload")
def upload_to_cloud(req: CloudSyncRequest):
    """
    Upload local data to cloud.
    Handles conflicts by keeping the newer version.
    """
    user_id = req.user_id
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    cloud_data = get_cloud_data(user_id)
    conflicts = []

    for figure in req.figures:
        figure_id = figure.get("figure_id")
        existing = next((f for f in cloud_data.get("figures", []) if f.get("figure_id") == figure_id), None)
        if existing:
            winner = _resolve_conflict(figure, existing)
            if winner == "local":
                idx = cloud_data["figures"].index(existing)
                cloud_data["figures"][idx] = figure
            else:
                conflicts.append({"type": "figure", "figure_id": figure_id, "resolved_by": "remote"})
        else:
            cloud_data.setdefault("figures", []).append(figure)

    for log in req.dialogue_logs:
        cloud_data.setdefault("dialogue_logs", []).append(log)

    for event in req.events:
        cloud_data.setdefault("events", []).append(event)

    save_cloud_data(user_id, cloud_data)

    return CloudSyncResponse(
        success=True,
        message="Upload completed",
        synced_at=datetime.utcnow().isoformat(),
        figures_count=len(cloud_data.get("figures", [])),
        logs_count=len(cloud_data.get("dialogue_logs", [])),
        events_count=len(cloud_data.get("events", [])),
        conflicts=conflicts,
    )


@router.post("/download")
def download_from_cloud(user_id: str, last_sync_at: Optional[str] = None):
    """
    Download cloud data to local.
    Returns data newer than last_sync_at if provided.
    """
    cloud_data = get_cloud_data(user_id)
    
    result = {
        "user_id": user_id,
        "figures": cloud_data.get("figures", []),
        "dialogue_logs": cloud_data.get("dialogue_logs", []),
        "events": cloud_data.get("events", []),
        "synced_at": cloud_data.get("synced_at"),
        "total_figures": len(cloud_data.get("figures", [])),
        "total_logs": len(cloud_data.get("dialogue_logs", [])),
        "total_events": len(cloud_data.get("events", [])),
    }

    if last_sync_at:
        try:
            sync_time = datetime.fromisoformat(last_sync_at[:-1])
            result["figures"] = [f for f in result["figures"] 
                                if datetime.fromisoformat(f.get("updated_at", "")[:-1]) > sync_time]
            result["dialogue_logs"] = [l for l in result["dialogue_logs"]
                                      if datetime.fromisoformat(l.get("created_at", "")[:-1]) > sync_time]
            result["events"] = [e for e in result["events"]
                                if datetime.fromisoformat(e.get("triggered_at", "")[:-1]) > sync_time]
        except:
            pass

    return result


@router.post("/sync")
def full_sync(req: CloudSyncRequest):
    """
    Full sync: upload local changes, then download cloud changes.
    Returns merged data.
    """
    upload_result = upload_to_cloud(req)
    download_result = download_from_cloud(req.user_id)

    return {
        "upload": upload_result,
        "download": download_result,
        "message": "Full sync completed",
    }


@router.post("/migrate")
def migrate_local_data(user_id: str):
    """
    Migrate existing local data (without user_id) to user-specific storage.
    """
    local_figures = list_figures(user_id=None)
    migrated = 0
    
    for figure in local_figures:
        figure_id = figure.get("figure_id")
        existing = get_figure(figure_id, user_id=user_id)
        if not existing:
            save_figure(figure_id, figure, user_id=user_id)
            migrated += 1

    return {
        "success": True,
        "migrated_count": migrated,
        "total_local": len(local_figures),
        "message": f"Migrated {migrated} figures to user {user_id}",
    }
