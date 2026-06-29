import os
import base64
import uuid
import httpx
from pathlib import Path

TRAIN_URL = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"
STATUS_URL = "https://openspeech.bytedance.com/api/v3/tts/get_voice"
FIXED_SPEAKER_ID = "custom_speaker_id"


def _api_key() -> str:
    return os.getenv("VOLC_TTS_API_KEY", "").strip()


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-Api-Key": _api_key(),
        "X-Api-Request-Id": str(uuid.uuid4()),
    }


def make_custom_speaker_id(figure_id: str) -> str:
    """每个灵偶生成合规 custom_speaker_id：custom_zh_lingou_<figureid前8位>"""
    short = figure_id.split("-")[0][:8]
    return f"custom_zh_lingou_{short}"


def _fmt_from_path(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return ext if ext in ("wav", "mp3", "ogg", "m4a", "aac", "pcm") else "mp3"


def start_clone(custom_speaker_id: str, audio_path: str, demo_text: str = "你好呀，我是你的专属灵偶。") -> dict:
    """上传音频发起训练。返回 {code,status,message}。"""
    with open(audio_path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode()
    body = {
        "speaker_id": FIXED_SPEAKER_ID,
        "custom_speaker_id": custom_speaker_id,
        "audio": {"data": data_b64, "format": _fmt_from_path(audio_path)},
        "extra_params": {"demo_text": demo_text, "enable_audio_denoise": False},
    }
    r = httpx.post(TRAIN_URL, headers=_headers(), json=body, timeout=60.0)
    j = r.json()
    return {"http": r.status_code, "code": j.get("code"), "status": j.get("status"),
            "message": j.get("message", ""), "raw": j}


def query_status(custom_speaker_id: str) -> dict:
    """查训练状态。火山 status: 0未找到/1训练中/2成功/3失败/4激活(2或4可合成)。"""
    body = {"speaker_id": FIXED_SPEAKER_ID, "custom_speaker_id": custom_speaker_id}
    r = httpx.post(STATUS_URL, headers=_headers(), json=body, timeout=30.0)
    j = r.json()
    return {"http": r.status_code, "volc_status": j.get("status"),
            "demo_audio": j.get("demo_audio"), "message": j.get("message", ""), "raw": j}


def map_status(volc_status) -> str:
    """火山状态码 → 我们的5态。"""
    return {0: "not_started", 1: "processing", 2: "ready", 3: "failed", 4: "ready"}.get(volc_status, "not_started")
