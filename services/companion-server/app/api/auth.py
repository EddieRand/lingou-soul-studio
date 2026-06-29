# services/companion-server/app/api/auth.py

from typing import Optional, Union
import uuid
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, field_validator
from data.store import DATA_DIR, _read_json, _write_json, _now_iso

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET_KEY = "lingou_soul_companion_secret_key_2026"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 24 * 60

USERS_FILE = DATA_DIR / "users.json"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator('password')
    def password_length(cls, v):
        if len(v) < 6:
            raise ValueError('密码至少6位')
        return v


class UserLogin(BaseModel):
    username: str
    password: str


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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator('new_password')
    def password_length(cls, v):
        if len(v) < 6:
            raise ValueError('密码至少6位')
        return v


class ResetTokenResponse(BaseModel):
    success: bool
    message: str
    reset_token: str
    expires_in_minutes: int


class SendCodeRequest(BaseModel):
    phone: str


class LoginCodeRequest(BaseModel):
    phone: str
    code: str


class WeChatLoginRequest(BaseModel):
    openid: Optional[str] = None
    nickname: Optional[str] = None
    avatar: Optional[str] = None


class AppleLoginRequest(BaseModel):
    apple_id: Optional[str] = None
    nickname: Optional[str] = None
    email: Optional[str] = None


VERIFICATION_CODES: dict = {}


def _get_users() -> dict:
    return _read_json(USERS_FILE) or {"users": []}


def _save_users(data: dict) -> None:
    _write_json(USERS_FILE, data)


def _hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())


def _verify_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed)


def _create_token(user_id: str, username: str) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> Union[dict, None]:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Union[dict, None]:
    if not token:
        return None
    payload = _decode_token(token)
    if not payload:
        return None
    users_data = _get_users()
    user = next((u for u in users_data["users"] if u["user_id"] == payload["user_id"]), None)
    return user


@router.post("/register", response_model=UserInfo)
def register(user: UserCreate):
    users_data = _get_users()
    
    if any(u["username"] == user.username for u in users_data["users"]):
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    if any(u["email"] == user.email for u in users_data["users"]):
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    new_user = {
        "user_id": str(uuid.uuid4()),
        "username": user.username,
        "email": user.email,
        "password_hash": _hash_password(user.password).decode('utf-8'),
        "created_at": _now_iso(),
        "last_login": None,
        "sync_enabled": True
    }

    users_data["users"].append(new_user)
    _save_users(users_data)
    
    return UserInfo(
        user_id=new_user["user_id"],
        username=new_user["username"],
        email=new_user["email"],
        created_at=new_user["created_at"]
    )


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    users_data = _get_users()
    user = next((
        u for u in users_data["users"] 
        if u["username"] == form_data.username or u["email"] == form_data.username
    ), None)
    
    if not user or not _verify_password(form_data.password, user["password_hash"].encode('utf-8')):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user["last_login"] = _now_iso()
    _save_users(users_data)

    return Token(
        access_token=_create_token(user["user_id"], user["username"]),
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"]
    )


@router.get("/verify", response_model=Union[UserInfo, dict])
def verify(token: str = Depends(oauth2_scheme)):
    if not token:
        return {"valid": False, "detail": "未提供token"}
    
    payload = _decode_token(token)
    if not payload:
        return {"valid": False, "detail": "token无效"}
    
    users_data = _get_users()
    user = next((u for u in users_data["users"] if u["user_id"] == payload["user_id"]), None)
    
    if not user:
        return {"valid": False, "detail": "用户不存在"}
    
    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        email=user["email"],
        created_at=user["created_at"]
    )


@router.post("/logout")
def logout():
    return {"message": "已登出"}


@router.get("/users", response_model=list[UserInfo])
def list_users():
    users_data = _get_users()
    return [
        UserInfo(
            user_id=u["user_id"],
            username=u["username"],
            email=u["email"],
            created_at=u["created_at"]
        )
        for u in users_data["users"]
    ]


@router.post("/forgot-password", response_model=ResetTokenResponse)
def forgot_password(req: ForgotPasswordRequest):
    users_data = _get_users()
    user = next((u for u in users_data["users"] if u["email"] == req.email), None)
    
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")
    
    reset_token = jwt.encode(
        {
            "user_id": user["user_id"],
            "email": user["email"],
            "exp": datetime.utcnow() + timedelta(minutes=15),
            "purpose": "reset_password"
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )
    
    return ResetTokenResponse(
        success=True,
        message="重置链接已生成，请复制下方token到重置页面",
        reset_token=reset_token,
        expires_in_minutes=15
    )


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest):
    try:
        payload = jwt.decode(req.token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="重置链接无效或已过期")
    
    if payload.get("purpose") != "reset_password":
        raise HTTPException(status_code=400, detail="无效的重置链接")
    
    users_data = _get_users()
    user = next((u for u in users_data["users"] if u["user_id"] == payload["user_id"]), None)
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user["password_hash"] = _hash_password(req.new_password).decode('utf-8')
    _save_users(users_data)
    
    return {"success": True, "message": "密码重置成功，请重新登录"}


@router.post("/send-code")
def send_code(req: SendCodeRequest):
    phone = req.phone
    if len(phone) != 11:
        raise HTTPException(status_code=400, detail="请输入正确的手机号")
    
    import random
    code = str(random.randint(100000, 999999))
    VERIFICATION_CODES[phone] = {
        "code": code,
        "expires_at": datetime.utcnow() + timedelta(minutes=5),
        "created_at": datetime.utcnow()
    }
    
    print(f"[DEBUG] 验证码发送: {phone} -> {code}")
    return {"success": True, "message": "验证码已发送", "code": code, "expires_in": 300}


@router.post("/login-code", response_model=Token)
def login_code(req: LoginCodeRequest):
    phone = req.phone
    code = req.code
    
    if len(phone) != 11:
        raise HTTPException(status_code=400, detail="请输入正确的手机号")
    
    if len(code) != 6:
        raise HTTPException(status_code=400, detail="请输入6位验证码")
    
    stored = VERIFICATION_CODES.get(phone)
    if not stored:
        raise HTTPException(status_code=400, detail="验证码不存在，请重新获取")
    
    if datetime.utcnow() > stored["expires_at"]:
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    
    if stored["code"] != code:
        raise HTTPException(status_code=400, detail="验证码错误")
    
    users_data = _get_users()
    user = next((u for u in users_data["users"] if u.get("phone") == phone), None)
    
    if not user:
        user_id = str(uuid.uuid4())
        new_user = {
            "user_id": user_id,
            "username": phone,
            "email": f"{phone}@lingou.local",
            "phone": phone,
            "password_hash": "",
            "created_at": _now_iso(),
            "last_login": None,
            "sync_enabled": True
        }
        users_data["users"].append(new_user)
        _save_users(users_data)
        user = new_user
    
    user["last_login"] = _now_iso()
    _save_users(users_data)
    
    return Token(
        access_token=_create_token(user["user_id"], user["username"]),
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"]
    )


@router.post("/wechat-login", response_model=Token)
def wechat_login(req: WeChatLoginRequest):
    """模拟微信登录：openid 不存在则自动创建用户。"""
    users_data = _get_users()
    openid = req.openid or f"wx_sim_{uuid.uuid4().hex[:8]}"

    user = next((u for u in users_data["users"] if u.get("wechat_openid") == openid), None)

    if not user:
        user_id = str(uuid.uuid4())
        nickname = req.nickname or f"微信用户{uuid.uuid4().hex[:4]}"
        new_user = {
            "user_id": user_id,
            "username": nickname,
            "email": f"{openid}@wechat.lingou.local",
            "password_hash": "",
            "wechat_openid": openid,
            "avatar": req.avatar or "",
            "created_at": _now_iso(),
            "last_login": None,
            "sync_enabled": True
        }
        users_data["users"].append(new_user)
        _save_users(users_data)
        user = new_user

    user["last_login"] = _now_iso()
    _save_users(users_data)

    return Token(
        access_token=_create_token(user["user_id"], user["username"]),
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"]
    )


@router.post("/apple-login", response_model=Token)
def apple_login(req: AppleLoginRequest):
    """模拟 Apple 登录：apple_id 不存在则自动创建用户。"""
    users_data = _get_users()
    apple_id = req.apple_id or f"apple_sim_{uuid.uuid4().hex[:8]}"

    user = next((u for u in users_data["users"] if u.get("apple_id") == apple_id), None)

    if not user:
        user_id = str(uuid.uuid4())
        nickname = req.nickname or f"Apple用户{uuid.uuid4().hex[:4]}"
        new_user = {
            "user_id": user_id,
            "username": nickname,
            "email": req.email or f"{apple_id}@apple.lingou.local",
            "password_hash": "",
            "apple_id": apple_id,
            "created_at": _now_iso(),
            "last_login": None,
            "sync_enabled": True
        }
        users_data["users"].append(new_user)
        _save_users(users_data)
        user = new_user

    user["last_login"] = _now_iso()
    _save_users(users_data)

    return Token(
        access_token=_create_token(user["user_id"], user["username"]),
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"]
    )
