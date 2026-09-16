# services/companion-server/app/main.py
import sys
import asyncio
import os
from pathlib import Path

# Load .env before any other imports that might use env vars
from dotenv import load_dotenv
if os.getenv("LINGOU_LOAD_DOTENV", "1").lower() not in {"0", "false", "no", "off"}:
    load_dotenv(Path(__file__).parent.parent / ".env")

# Add companion-server root to path for imports
server_root = Path(__file__).parent.parent
sys.path.insert(0, str(server_root))

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import bases, figures, souls, events, hardware, dialogue, brain, sync, voice, character, asr, auth, device, device_auth, memories
from app.core import online_brain

app = FastAPI(
    title="Lingou Companion Server",
    description="Soul Companion base system API",
    version="0.1.0",
)


def _route_path(scope: Scope) -> str:
    """Match Starlette's routing path when an ASGI root_path is configured."""
    path = scope.get("path", "")
    root_path = scope.get("root_path", "")
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path):]
    return path


class ApiAuthenticationBoundaryMiddleware:
    """Reject private HTTP APIs before FastAPI reads or validates the body."""

    PUBLIC_PATHS = {"/api/auth/register", "/api/auth/login"}
    DEVICE_PATHS = {"/api/device/events"}

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        route_path = _route_path(scope)
        if (
            scope["type"] != "http"
            or scope.get("method") == "OPTIONS"
            or not route_path.startswith("/api/")
            or route_path in self.PUBLIC_PATHS
        ):
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("Authorization")
        if route_path in self.DEVICE_PATHS:
            principal = device_auth.device_principal_from_authorization(authorization)
            if not principal:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": device_auth.DEVICE_AUTH_ERROR_DETAIL},
                    headers={"WWW-Authenticate": "Device"},
                )
                await response(scope, receive, send)
                return
            scope["lingou.device_principal"] = principal
            await self.app(scope, receive, send)
            return

        scheme, token = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer" or not token or not auth.authenticate_access_token(token):
            response = JSONResponse(
                status_code=401,
                content={"detail": auth.AUTHENTICATION_ERROR_DETAIL},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# The ASGI boundary runs before route matching and request-body parsing. Router
# dependencies remain in place as defense in depth and provide current_user to
# endpoint code. CORS wraps the boundary so browser-visible 401 responses keep
# the configured development-origin headers.
app.add_middleware(ApiAuthenticationBoundaryMiddleware)

# CORS for H5 dev
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "LINGOU_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Lingou-Audio-Engine",
        "X-Lingou-Audio-Source",
        "X-Lingou-Voice-Speaker",
        "X-Lingou-Audio-Synthesized-At",
    ],
)

# Mount routers. Authentication is a deny-by-default boundary for every
# business HTTP router. ASR is mounted separately because its router also owns
# a WebSocket; /api/asr/status has its own HTTP dependency and /stream decides
# a short-lived ticket before any provider work. Rejected sockets complete only
# the protocol handshake so Uvicorn can deliver the application 440x code.
authenticated = [Depends(auth.require_current_user)]
app.include_router(bases.router, prefix="/api/bases", tags=["bases"], dependencies=authenticated)
app.include_router(figures.router, prefix="/api/figures", tags=["figures"], dependencies=authenticated)
app.include_router(memories.router, prefix="/api/figures", tags=["memories"], dependencies=authenticated)
app.include_router(souls.router, prefix="/api/souls", tags=["souls"], dependencies=authenticated)
app.include_router(events.router, prefix="/api/events", tags=["events"], dependencies=authenticated)
app.include_router(hardware.router, prefix="/api/hardware", tags=["hardware"], dependencies=authenticated)
app.include_router(dialogue.router, prefix="/api/dialogue", tags=["dialogue"], dependencies=authenticated)
app.include_router(brain.router, prefix="/api/brain", tags=["brain"], dependencies=authenticated)
app.include_router(sync.router, prefix="/api/sync", tags=["sync"], dependencies=authenticated)
app.include_router(voice.router, prefix="/api/voice", tags=["voice"], dependencies=authenticated)
app.include_router(character.router, prefix="/api/character", tags=["character"], dependencies=authenticated)
app.include_router(asr.router)
app.include_router(auth.router)
app.include_router(device.router, prefix="/api/device", tags=["device"])


@app.on_event("startup")
async def startup_event():
    """启动时预热在线大脑，避免冷启动超时"""
    auth.validate_auth_configuration()
    if os.getenv("LINGOU_WARMUP_ON_STARTUP", "0").lower() in {"0", "false", "no", "off"}:
        return
    try:
        await asyncio.to_thread(
            online_brain._call_doubao,
            messages=[{"role": "user", "content": "你好"}],
            timeout=15.0
        )
        print("[Startup] Online brain warmed up successfully")
    except Exception as e:
        # 预热失败不影响启动，首轮可能会慢一点
        print(f"[Startup] Online brain warmup failed (will retry on first request): {str(e)}")


@app.get("/")
def root():
    return {"status": "ok", "service": "lingou-companion-server"}


@app.get("/health")
def health():
    return {"status": "healthy"}
