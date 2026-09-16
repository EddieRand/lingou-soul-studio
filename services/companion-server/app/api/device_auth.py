"""Independent scoped authentication for provisioned and test devices."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param

from data.store import (
    base_owner_id,
    get_base,
    get_base_for_owner,
    save_base,
    validate_resource_id,
)


DEVICE_AUTH_ERROR_DETAIL = "设备凭据无效或已过期"
TEST_DEVICE_AUTH_ENV = "LINGOU_ENABLE_TEST_DEVICE_AUTH"
TEST_DEVICE_TTL_SECONDS = 24 * 60 * 60
EVENTS_WRITE_SCOPE = "events:write"
VOICE_STREAM_SCOPE = "voice:stream"
DEVICE_SCOPES = (EVENTS_WRITE_SCOPE, VOICE_STREAM_SCOPE)


def test_device_auth_enabled() -> bool:
    return os.getenv(TEST_DEVICE_AUTH_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _credential_hash(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def issue_test_device_credential(
    base: dict,
    owner_user_id: str,
    *,
    ttl_seconds: int = TEST_DEVICE_TTL_SECONDS,
) -> tuple[dict, str]:
    """Rotate the development credential and return its plaintext once."""
    if not test_device_auth_enabled():
        raise RuntimeError("test device authentication is disabled")
    base_id = validate_resource_id(str(base.get("base_id", "")), "base_id")
    if get_base_for_owner(base_id, owner_user_id) is None:
        raise ValueError("base is not owned by this user")
    if ttl_seconds <= 0 or ttl_seconds > TEST_DEVICE_TTL_SECONDS:
        raise ValueError("invalid device credential lifetime")

    credential = f"{base_id}.{secrets.token_urlsafe(32)}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    updated = dict(base)
    updated["device_credential_hash"] = _credential_hash(credential)
    updated["device_credential_kind"] = "test"
    updated["device_credential_status"] = "active"
    updated["device_credential_expires_at"] = expires_at.isoformat()
    updated["device_credential_scope"] = list(DEVICE_SCOPES)
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    return save_base(base_id, updated, owner_user_id=owner_user_id), credential


def authenticate_device_credential(
    credential: str,
    *,
    required_scope: str = EVENTS_WRITE_SCOPE,
) -> Optional[dict]:
    if not credential or "." not in credential:
        return None
    base_id, _secret = credential.split(".", 1)
    try:
        base_id = validate_resource_id(base_id, "base_id")
    except ValueError:
        return None
    base = get_base(base_id)
    if not isinstance(base, dict):
        return None
    owner_user_id = base_owner_id(base)
    if not owner_user_id or get_base_for_owner(base_id, owner_user_id) is None:
        return None
    credential_kind = str(base.get("device_credential_kind", ""))
    if credential_kind == "test":
        if not test_device_auth_enabled():
            return None
    elif credential_kind != "production":
        return None
    if base.get("device_credential_status") != "active":
        return None
    expected_hash = str(base.get("device_credential_hash", ""))
    if not expected_hash or not hmac.compare_digest(
        expected_hash,
        _credential_hash(credential),
    ):
        return None
    if credential_kind == "test":
        try:
            expires_at = datetime.fromisoformat(str(base["device_credential_expires_at"]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            return None
        if expires_at <= datetime.now(timezone.utc):
            return None
    credential_scope = tuple(
        str(scope)
        for scope in base.get("device_credential_scope", [])
        if isinstance(scope, str)
    )
    if required_scope not in credential_scope:
        return None
    return {
        "base_id": base_id,
        "owner_user_id": owner_user_id,
        "scope": credential_scope,
        "credential_kind": credential_kind,
    }


def device_principal_from_authorization(
    authorization: Optional[str],
    *,
    required_scope: str = EVENTS_WRITE_SCOPE,
) -> Optional[dict]:
    scheme, credential = get_authorization_scheme_param(authorization)
    if scheme.lower() != "device" or not credential:
        return None
    return authenticate_device_credential(
        credential,
        required_scope=required_scope,
    )


def _device_authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=DEVICE_AUTH_ERROR_DETAIL,
        headers={"WWW-Authenticate": "Device"},
    )


async def require_current_device(request: Request) -> dict:
    principal = request.scope.get("lingou.device_principal")
    if not principal:
        principal = device_principal_from_authorization(
            request.headers.get("Authorization")
        )
    if not principal:
        raise _device_authentication_error()
    return principal
