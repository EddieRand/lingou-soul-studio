"""Shared authorization helpers for owner-bound resources."""

from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException, status

from data.store import get_base_for_owner, get_figure, validate_resource_id


RESOURCE_NOT_FOUND_DETAIL = "资源不存在或不可访问"


def current_user_id(current_user: dict) -> str:
    """Return the authenticated actor ID, rejecting malformed account data."""
    try:
        return validate_resource_id(str(current_user["user_id"]), "user_id")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭据无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def resource_not_found() -> HTTPException:
    # Cross-owner and missing resources intentionally share one response so an
    # authenticated account cannot enumerate another account's identifiers.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=RESOURCE_NOT_FOUND_DETAIL,
    )


def owned_base_or_404(base_id: str, owner_user_id: str) -> dict:
    try:
        base = get_base_for_owner(base_id, owner_user_id)
    except ValueError as exc:
        raise resource_not_found() from exc
    if not base:
        raise resource_not_found()
    return base


def owned_figure_or_404(figure_id: str, owner_user_id: str) -> dict:
    try:
        figure = get_figure(figure_id, user_id=owner_user_id)
    except ValueError as exc:
        raise resource_not_found() from exc
    if not figure:
        raise resource_not_found()
    return figure


def public_base(base: dict) -> dict:
    """Expose the canonical owner while removing secrets and legacy aliases."""
    result = deepcopy(base)
    for field in (
        "owner_id",
        "bound_user_id",
        "pairing_token_hash",
        "device_credential_hash",
        "device_credential_expires_at",
        "device_credential_scope",
        "device_credential_kind",
        "device_credential_status",
        "device_credential_revoked_at",
        "recent_device_event_ids",
        "recent_device_events",
    ):
        result.pop(field, None)
    return result
