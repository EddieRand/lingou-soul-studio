import os
import base64
import json
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

from data.store import DATA_DIR


def _url() -> str:
    return os.getenv("VOXCPM_URL", "http://localhost:9000").rstrip("/")


def is_configured() -> bool:
    """检查 VoxCPM 服务是否可用。"""
    try:
        r = urllib.request.urlopen(_url() + "/health", timeout=3)
        return json.loads(r.read()).get("ok", False)
    except Exception:
        return False


def clone_synthesize(text: str, ref_audio_path: str, prompt_text: str = "",
                     figure_id: str = "") -> Optional[str]:
    """零样本克隆合成：返回保存的 wav 路径，失败返回 None。"""
    try:
        ref_b64 = base64.b64encode(open(ref_audio_path, "rb").read()).decode()
        fmt = Path(ref_audio_path).suffix.lower().lstrip(".") or "wav"
        body = json.dumps({
            "text": text, "prompt_audio_b64": ref_b64, "prompt_audio_format": fmt,
            "prompt_text": prompt_text or "",
            "cfg_value": 2.0, "inference_timesteps": 40, "denoise": True,
        }).encode()
        req = urllib.request.Request(_url() + "/clone_tts", data=body,
                                     headers={"Content-Type": "application/json"})
        j = json.loads(urllib.request.urlopen(req, timeout=120).read())
        if not j.get("ok"):
            return None
        out_dir = DATA_DIR / "audio_cache" / (figure_id or "clone")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"clone_{uuid.uuid4().hex}.wav"
        out.write_bytes(base64.b64decode(j["audio_b64"]))
        return str(out)
    except Exception as e:
        print(f"[VoxCPM] clone_synthesize 失败: {e}")
        return None
