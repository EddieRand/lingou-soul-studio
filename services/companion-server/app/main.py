# services/companion-server/app/main.py
import sys
import asyncio
from pathlib import Path

# Load .env before any other imports that might use env vars
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Add companion-server root to path for imports
server_root = Path(__file__).parent.parent
sys.path.insert(0, str(server_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import bases, figures, souls, events, hardware, dialogue, brain, sync, voice, character, asr, auth
from app.core import online_brain

app = FastAPI(
    title="Lingou Companion Server",
    description="Soul Companion base system API",
    version="0.1.0",
)

# CORS for H5 dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(bases.router, prefix="/api/bases", tags=["bases"])
app.include_router(figures.router, prefix="/api/figures", tags=["figures"])
app.include_router(souls.router, prefix="/api/souls", tags=["souls"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(hardware.router, prefix="/api/hardware", tags=["hardware"])
app.include_router(dialogue.router, prefix="/api/dialogue", tags=["dialogue"])
app.include_router(brain.router, prefix="/api/brain", tags=["brain"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(voice.router, prefix="/api/voice", tags=["voice"])
app.include_router(character.router, prefix="/api/character", tags=["character"])
app.include_router(asr.router)  # ASR WebSocket（已有 prefix）
app.include_router(auth.router)


@app.on_event("startup")
async def startup_event():
    """启动时预热在线大脑，避免冷启动超时"""
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
