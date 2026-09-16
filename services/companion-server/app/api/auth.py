"""Username/password authentication and short-lived WebSocket tickets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
from typing import Optional
import uuid

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from data.store import (
    DATA_DIR,
    _now_iso,
    _read_json,
    get_base_for_owner,
    validate_resource_id,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 24 * 60
WS_TICKET_EXPIRE_SECONDS = 60
ACCESS_TOKEN_TYPE = "access"
WS_TICKET_TYPE = "ws_ticket"
WS_TICKET_PURPOSE = "asr_stream"
MIN_JWT_SECRET_BYTES = 32
AUTHENTICATION_ERROR_DETAIL = "登录凭据无效或已过期"

USERS_FILE = DATA_DIR / "users.json"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

_DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"lingou-invalid-user-timing-placeholder",
    bcrypt.gensalt(),
).decode("utf-8")
_consumed_ws_tickets: dict[str, int] = {}
_ws_ticket_lock = threading.Lock()
_users_lock = threading.RLock()


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 50:
            raise ValueError("用户名长度需为1到50个字符")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("密码至少8位")
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码的 UTF-8 编码不能超过72字节")
        return value


class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    username: str


class UserInfo(BaseModel):
    user_id: str
    username: str
    email: str
    created_at: str


class WebSocketTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_id: str

    @field_validator("base_id")
    @classmethod
    def validate_base_id(cls, value: str) -> str:
        return validate_resource_id(value.strip(), "base_id")


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int


def validate_auth_configuration() -> None:
    """Fail at startup instead of serving an unusable or insecure auth API."""
    _get_jwt_secret()
    _restrict_users_file_permissions()


def _get_jwt_secret() -> str:
    secret = os.getenv("LINGOU_JWT_SECRET", "")
    if len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        raise RuntimeError(
            "LINGOU_JWT_SECRET must be set to at least 32 bytes; "
            "generate a private value before starting the server"
        )
    return secret


def _restrict_users_file_permissions() -> None:
    try:
        USERS_FILE.chmod(0o600)
    except FileNotFoundError:
        pass


def _get_users() -> dict:
    with _users_lock:
        _restrict_users_file_permissions()
        data = _read_json(USERS_FILE) or {"users": []}
    if not isinstance(data.get("users"), list):
        return {"users": []}
    return data


def _save_users(data: dict) -> None:
    with _users_lock:
        temporary = USERS_FILE.with_name(f".{USERS_FILE.name}.{uuid.uuid4().hex}.tmp")
        try:
            # Create with restrictive permissions from the first byte. Writing
            # through the shared helper would briefly honor a permissive umask
            # before chmod, exposing account metadata during that window.
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, USERS_FILE)
            USERS_FILE.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def _create_token(user_id: str, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "typ": ACCESS_TOKEN_TYPE,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def _decode_token(token: str, expected_type: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "typ", "iat", "exp"]},
        )
    except (jwt.InvalidTokenError, RuntimeError):
        return None
    if payload.get("typ") != expected_type:
        return None
    return payload


def _find_user(user_id: str) -> Optional[dict]:
    return next(
        (user for user in _get_users()["users"] if user.get("user_id") == user_id),
        None,
    )


def authenticate_access_token(token: str) -> Optional[dict]:
    payload = _decode_token(token, ACCESS_TOKEN_TYPE)
    if not payload:
        return None
    return _find_user(str(payload["sub"]))


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTHENTICATION_ERROR_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise _authentication_error()
    user = authenticate_access_token(token)
    if not user:
        raise _authentication_error()
    return user


# Existing business routers import this name. It is now deliberately strict.
get_current_user = require_current_user


def _create_ws_ticket(user_id: str, base_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "typ": WS_TICKET_TYPE,
        "purpose": WS_TICKET_PURPOSE,
        "base_id": base_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=WS_TICKET_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def consume_ws_ticket(token: str, base_id: str) -> tuple[Optional[dict], int]:
    """Validate and atomically consume a one-use ASR ticket.

    Returns (user, close_code). close_code is zero on success, 4401 for an
    invalid identity, 4403 for a scope mismatch, and 4409 for a replay.
    """
    payload = _decode_token(token, WS_TICKET_TYPE)
    if not payload:
        return None, 4401
    if payload.get("purpose") != WS_TICKET_PURPOSE or payload.get("base_id") != base_id:
        return None, 4403

    jti = payload.get("jti")
    expires_at = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(expires_at, int):
        return None, 4401

    user = _find_user(str(payload["sub"]))
    if not user:
        return None, 4401
    try:
        owned_base = get_base_for_owner(base_id, str(user["user_id"]))
    except ValueError:
        return None, 4403
    if not owned_base:
        return None, 4403

    now = int(time.time())
    with _ws_ticket_lock:
        expired = [ticket_id for ticket_id, expiry in _consumed_ws_tickets.items() if expiry <= now]
        for ticket_id in expired:
            _consumed_ws_tickets.pop(ticket_id, None)
        if jti in _consumed_ws_tickets:
            return None, 4409
        _consumed_ws_tickets[jti] = expires_at

    return user, 0


def _public_user(user: dict) -> UserInfo:
    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        email=user["email"],
        created_at=user["created_at"],
    )


@router.post("/register", response_model=UserInfo)
def register(user: UserCreate):
    with _users_lock:
        users_data = _get_users()
        username_key = user.username.casefold()
        email = str(user.email).strip().casefold()
        existing_identifiers = {
            identifier
            for existing in users_data["users"]
            for identifier in (
                str(existing.get("username", "")).casefold(),
                str(existing.get("email", "")).casefold(),
            )
            if identifier
        }

        if username_key in existing_identifiers:
            raise HTTPException(status_code=400, detail="用户名已存在")
        if email in existing_identifiers:
            raise HTTPException(status_code=400, detail="邮箱已被注册")

        new_user = {
            "user_id": str(uuid.uuid4()),
            "username": user.username,
            "email": email,
            "password_hash": _hash_password(user.password),
            "created_at": _now_iso(),
            "last_login": None,
            "sync_enabled": True,
        }
        users_data["users"].append(new_user)
        _save_users(users_data)
    return _public_user(new_user)


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    login_key = form_data.username.strip().casefold()
    with _users_lock:
        users_data = _get_users()
        matches = [
            existing
            for existing in users_data["users"]
            if str(existing.get("username", "")).casefold() == login_key
            or str(existing.get("email", "")).casefold() == login_key
        ]
        # Old data may predate the shared username/email uniqueness rule. Never
        # guess which account an ambiguous identifier belongs to.
        user = matches[0] if len(matches) == 1 else None

        password_hash = str(user.get("password_hash", "")) if user else _DUMMY_PASSWORD_HASH
        password_valid = _verify_password(form_data.password, password_hash)
        if not user or not password_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user["last_login"] = _now_iso()
        _save_users(users_data)
    return Token(
        access_token=_create_token(user["user_id"], user["username"]),
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"],
    )


@router.get("/verify", response_model=UserInfo)
def verify(current_user: dict = Depends(require_current_user)):
    return _public_user(current_user)


@router.post("/logout")
def logout(_current_user: dict = Depends(require_current_user)):
    return {"message": "客户端登录状态已清除"}


@router.post("/ws-ticket", response_model=WebSocketTicketResponse)
def issue_ws_ticket(
    request: WebSocketTicketRequest,
    current_user: dict = Depends(require_current_user),
):
    if not get_base_for_owner(request.base_id, str(current_user["user_id"])):
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")
    return WebSocketTicketResponse(
        ticket=_create_ws_ticket(current_user["user_id"], request.base_id),
        expires_in=WS_TICKET_EXPIRE_SECONDS,
    )
