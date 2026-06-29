# services/companion-server/app/api/bases.py
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from data.store import save_base, get_base, list_bases, get_figure
from app.api.auth import get_current_user

router = APIRouter()


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ============== Request/Response Models ==============

class CreateBaseRequest(BaseModel):
    base_id: str
    bound_user_id: Optional[str] = None


class BindBaseRequest(BaseModel):
    bound_user_id: str


class SetActiveFigureRequest(BaseModel):
    figure_id: str


# ============== API Endpoints ==============

@router.get("")
def list_my_bases(current_user: Optional[dict] = Depends(get_current_user)):
    """List bases belonging to the current user."""
    user_id = current_user["user_id"] if current_user else "user_default"
    all_bases = list_bases()
    user_bases = [b for b in all_bases if b.get("bound_user_id") == user_id]
    result = []
    for base in user_bases:
        active_figure = None
        if base.get("active_figure_id"):
            active_figure = get_figure(base["active_figure_id"])
        result.append({
            "base": base,
            "figure": active_figure,
        })
    return result


@router.post("", response_model=dict)
def create_base(req: CreateBaseRequest):
    """Register a new base."""
    existing = get_base(req.base_id)
    if existing:
        raise HTTPException(status_code=409, detail="Base already exists")

    base = {
        "base_id": req.base_id,
        "bound_user_id": req.bound_user_id,
        "active_figure_id": None,
        "status": "unbound",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    return save_base(req.base_id, base)


@router.get("/{base_id}")
def get_base_detail(base_id: str):
    """Get base detail with current active figure."""
    base = get_base(base_id)
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    # Load active figure if any
    active_figure = None
    if base.get("active_figure_id"):
        from data.store import get_figure
        active_figure = get_figure(base["active_figure_id"])

    return {"base": base, "figure": active_figure}


@router.post("/{base_id}/bind")
def bind_base(base_id: str, req: BindBaseRequest, current_user: Optional[dict] = Depends(get_current_user)):
    """Bind/activate a base."""
    base = get_base(base_id)
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    if req.bound_user_id:
        user_id = req.bound_user_id
    elif current_user:
        user_id = current_user["user_id"]
    else:
        user_id = "user_default"

    base["bound_user_id"] = user_id
    base["status"] = "bound"
    base["updated_at"] = _now_iso()
    return save_base(base_id, base)


@router.post("/{base_id}/active-figure")
def set_active_figure(base_id: str, req: SetActiveFigureRequest):
    """Set the active figure on this base.
    Ensures one figure can only be active on one base at a time (per user)."""
    base = get_base(base_id)
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    figure = get_figure(req.figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    owner = base.get("bound_user_id")
    if owner:
        for other in list_bases():
            if other.get("base_id") != base_id and other.get("bound_user_id") == owner \
               and other.get("active_figure_id") == req.figure_id:
                other["active_figure_id"] = None
                other["status"] = "bound"
                other["updated_at"] = _now_iso()
                save_base(other["base_id"], other)

    base["active_figure_id"] = req.figure_id
    base["status"] = "waiting"
    base["updated_at"] = _now_iso()
    return save_base(base_id, base)
