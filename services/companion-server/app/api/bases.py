"""Owner-scoped base pairing, activation and development APIs."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from urllib.parse import parse_qs, urlparse

from app.api.auth import get_current_user
from app.api.device_auth import (
    TEST_DEVICE_TTL_SECONDS,
    issue_test_device_credential,
    test_device_auth_enabled,
)
from app.api.ownership import (
    current_user_id,
    owned_base_or_404,
    owned_figure_or_404,
    public_base,
    resource_not_found,
)
from data.store import (
    AccountAlreadyHasBaseError,
    BaseAlreadyBoundError,
    DataIntegrityError,
    InvalidPairingTokenError,
    activate_figure,
    claim_base,
    get_base,
    get_figure,
    list_bases_for_owner,
    revoke_device_credential,
    save_base,
    unbind_base,
    validate_resource_id,
)


router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateTestBaseRequest(_StrictModel):
    base_id: str

    @field_validator("base_id")
    @classmethod
    def validate_base_id(cls, value: str) -> str:
        return validate_resource_id(value.strip(), "base_id")


class SetActiveFigureRequest(_StrictModel):
    figure_id: str

    @field_validator("figure_id")
    @classmethod
    def validate_figure_id(cls, value: str) -> str:
        return validate_resource_id(value.strip(), "figure_id")


class PairBaseRequest(_StrictModel):
    qr_token: str

    @field_validator("qr_token")
    @classmethod
    def validate_qr_token(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 512:
            raise ValueError("qr_token must contain 1-512 characters")
        return value


def _extract_pairing_token(qr_payload: str) -> str:
    if not qr_payload.startswith("lingou://"):
        return qr_payload
    parsed = urlparse(qr_payload)
    if parsed.netloc != "pair":
        return ""
    return parse_qs(parsed.query).get("token", [""])[0]


def _base_detail(base: dict, owner_user_id: str) -> dict:
    active_figure = None
    figure_id = base.get("active_figure_id")
    if figure_id:
        active_figure = get_figure(str(figure_id), user_id=owner_user_id)
    return {"base": public_base(base), "figure": active_figure}


def _require_test_device_mode() -> None:
    if not test_device_auth_enabled():
        raise resource_not_found()


@router.get("")
def list_my_bases(current_user: dict = Depends(get_current_user)):
    owner_user_id = current_user_id(current_user)
    return [
        _base_detail(base, owner_user_id)
        for base in list_bases_for_owner(owner_user_id)
    ]


@router.post("/pair")
def pair_base(
    request: PairBaseRequest,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    token = _extract_pairing_token(request.qr_token)
    try:
        base, newly_claimed = claim_base(token, owner_user_id=owner_user_id)
    except InvalidPairingTokenError:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "二维码无效或不是已预置的灵偶底座",
                "error_code": "INVALID_QR_CODE",
            },
        )
    except BaseAlreadyBoundError:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "该底座已绑定其他账号",
                "error_code": "BASE_ALREADY_BOUND",
            },
        )
    except AccountAlreadyHasBaseError:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "当前账号已绑定底座，请先解绑后再配对",
                "error_code": "ACCOUNT_ALREADY_HAS_BASE",
            },
        )
    return {
        "success": True,
        "base_id": base["base_id"],
        "binding_status": "bound_to_current_user",
        "newly_bound": newly_claimed,
        **_base_detail(base, owner_user_id),
    }


@router.post("/test-bases", status_code=status.HTTP_201_CREATED)
def create_test_base(
    request: CreateTestBaseRequest,
    current_user: dict = Depends(get_current_user),
):
    """Register an owned development base when test device auth is enabled."""
    _require_test_device_mode()
    owner_user_id = current_user_id(current_user)
    if get_base(request.base_id) is not None:
        raise HTTPException(status_code=409, detail="测试底座标识已被使用")
    now = _now_iso()
    try:
        base = save_base(
            request.base_id,
            {
                "base_id": request.base_id,
                "active_figure_id": None,
                "status": "bound",
                "created_at": now,
                "updated_at": now,
            },
            owner_user_id=owner_user_id,
        )
    except DataIntegrityError as exc:
        raise HTTPException(status_code=409, detail="测试底座标识已被使用") from exc
    return _base_detail(base, owner_user_id)


@router.get("/{base_id}")
def get_base_detail(base_id: str, current_user: dict = Depends(get_current_user)):
    owner_user_id = current_user_id(current_user)
    return _base_detail(owned_base_or_404(base_id, owner_user_id), owner_user_id)


@router.post("/{base_id}/unbind")
def unbind_owned_base(
    base_id: str,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    owned_base_or_404(base_id, owner_user_id)
    try:
        unbound = unbind_base(base_id, owner_user_id=owner_user_id)
    except DataIntegrityError as exc:
        raise resource_not_found() from exc
    return {
        "success": True,
        "base_id": base_id,
        "binding_status": "unbound",
        "unbound_at": unbound["unbound_at"],
    }


@router.post("/{base_id}/device-credential/revoke")
def revoke_owned_device_credential(
    base_id: str,
    current_user: dict = Depends(get_current_user),
):
    owner_user_id = current_user_id(current_user)
    owned_base_or_404(base_id, owner_user_id)
    try:
        base = revoke_device_credential(base_id, owner_user_id=owner_user_id)
    except DataIntegrityError as exc:
        raise resource_not_found() from exc
    return {"success": True, "base": public_base(base)}


@router.post("/{base_id}/test-device-credential")
def rotate_test_device_credential(
    base_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return a rotated, short-lived development device credential once."""
    _require_test_device_mode()
    owner_user_id = current_user_id(current_user)
    base = owned_base_or_404(base_id, owner_user_id)
    updated, credential = issue_test_device_credential(base, owner_user_id)
    return {
        "base": public_base(updated),
        "device_credential": credential,
        "expires_in": TEST_DEVICE_TTL_SECONDS,
        "scope": ["events:write", "voice:stream"],
    }


@router.post("/{base_id}/active-figure")
def set_active_figure(
    base_id: str,
    request: SetActiveFigureRequest,
    current_user: dict = Depends(get_current_user),
):
    """Activate one of the authenticated user's figures on their own base."""
    owner_user_id = current_user_id(current_user)
    owned_base_or_404(base_id, owner_user_id)
    owned_figure_or_404(request.figure_id, owner_user_id)
    try:
        base, _figure = activate_figure(
            base_id,
            request.figure_id,
            owner_user_id=owner_user_id,
        )
    except DataIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="激活失败，当前数据未完成更新，请重试",
        ) from exc
    return _base_detail(base, owner_user_id)
