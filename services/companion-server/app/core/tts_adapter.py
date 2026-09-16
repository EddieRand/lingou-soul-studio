# services/companion-server/app/core/tts_adapter.py
"""
TTS adapter: unified interface for multiple TTS engines + voice pool.
Engines:
  - volcano_tts  : Volcengine Doubao TTS (online, primary)
  - system_tts   : macOS say (offline fallback)
  - voxcpm2      : placeholder for voice cloning (future)
  - local_tts    : reserved for future local real-time TTS
Selection logic:
  Online + VOLC_TTS_API_KEY configured → volcano_tts
  volcano_tts failure/timeout (8s) → voice_pool (volcano mp3) → system_tts fallback
Voice pool:
  Offline / failed volcano → play pre-cached mp3 from data/voice_pool/{figure_id}/
  Voice pool texts: data/voice_pool_texts/{archetype}.json
  Pre-cached mp3: data/voice_pool/{figure_id}/{text_hash}.mp3
"""

import os
import sys
import subprocess
import threading
import base64
import json
import hashlib
import time
import queue
from pathlib import Path
from typing import Optional, Dict, Callable

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from data.store import DATA_DIR

AUDIO_CACHE_DIR = DATA_DIR / "audio_cache"
VOICE_POOL_DIR = DATA_DIR / "voice_pool"
VOICE_POOL_TEXTS_DIR = DATA_DIR / "voice_pool_texts"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
VOICE_POOL_DIR.mkdir(parents=True, exist_ok=True)
VOICE_POOL_TEXTS_DIR.mkdir(parents=True, exist_ok=True)


# ============== Global Playback Queue with Barge-in ==============
# 全局播放队列：保证同一时刻只有一个音频在播放，避免声音重叠
# 设计：
#   - 线程安全队列：queue.Queue
#   - 单个后台worker线程：持续从队列取任务，用 Popen 播放（可中途终止）
#   - 支持「立即停止」：stop_playback() 终止当前播放进程 + 清空队列
#   - 所有音频播放都走这个队列（流式对话、触摸回应、离线池）

_playback_queue = queue.Queue()
_playback_worker_running = False
_playback_worker_thread = None
_playback_lock = threading.Lock()

# 当前播放进程（用于打断）
_current_process: Optional[subprocess.Popen] = None
_current_scope_id: Optional[str] = None


def _playback_worker():
    """后台播放worker：从队列取音频文件，顺序播放（支持中途停止）"""
    global _playback_worker_running, _current_process, _current_scope_id
    while _playback_worker_running:
        try:
            # 阻塞等待队列任务（带超时，避免退出时卡死）
            item = _playback_queue.get(timeout=1.0)
            if item is None:  # 哨兵值：退出信号
                break
            
            if isinstance(item, tuple):
                filepath, scope_id = item
            else:
                filepath, scope_id = item, None
            if filepath and filepath != "/dev/null":
                try:
                    # 用 Popen 保存进程句柄，便于后续 terminate
                    _current_process = subprocess.Popen(
                        ["afplay", filepath],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    _current_scope_id = scope_id
                    # 阻塞等待播放完成
                    _current_process.wait()
                    _current_process = None
                    _current_scope_id = None
                except Exception:
                    _current_process = None
                    _current_scope_id = None
            _playback_queue.task_done()
        except queue.Empty:
            continue  # 队列为空，继续循环
        except Exception:
            _current_process = None
            _current_scope_id = None
            continue


def _start_playback_worker():
    """启动播放worker线程（懒加载）"""
    global _playback_worker_running, _playback_worker_thread
    with _playback_lock:
        if not _playback_worker_running:
            _playback_worker_running = True
            _playback_worker_thread = threading.Thread(target=_playback_worker, daemon=True)
            _playback_worker_thread.start()


def play_mp3_enqueue(filepath: str, scope_id: Optional[str] = None) -> bool:
    """
    将音频文件加入播放队列（非阻塞）。
    音频会按入队顺序依次播放，保证同一时刻只有一个afplay在运行。
    """
    if not filepath or filepath == "/dev/null":
        return False
    _start_playback_worker()  # 确保worker已启动
    _playback_queue.put((filepath, scope_id))
    return True


def _clear_queued_scope(scope_id: Optional[str]) -> int:
    """Remove queued items for one scope, or every item when scope is None."""
    removed = 0
    retained = []
    while not _playback_queue.empty():
        try:
            item = _playback_queue.get_nowait()
            _playback_queue.task_done()
            item_scope = item[1] if isinstance(item, tuple) else None
            if scope_id is None or item_scope == scope_id:
                removed += 1
            else:
                retained.append(item)
        except queue.Empty:
            break
    for item in retained:
        _playback_queue.put(item)
    return removed


def clear_playback_queue(scope_id: Optional[str] = None):
    """Clear queued playback belonging to the requested conversation scope."""
    with _playback_lock:
        _clear_queued_scope(scope_id)


def stop_playback(scope_id: Optional[str] = None) -> bool:
    """
    立即停止当前播放 + 清空队列（用于打断 barge-in）。
    Returns True if stopped something, False if nothing was playing.
    """
    stopped = False
    
    # 1. 终止当前播放进程
    global _current_process, _current_scope_id
    with _playback_lock:
        if _current_process is not None and (
            scope_id is None or _current_scope_id == scope_id
        ):
            process = _current_process
            try:
                process.terminate()
                process.wait(timeout=1.0)
                stopped = True
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            finally:
                _current_process = None
                _current_scope_id = None
        if _clear_queued_scope(scope_id):
            stopped = True
    
    return stopped


# ============== Engine Registry ==============

class TTSEngineRegistry:
    """
    Centralized TTS engine registry.
    Adding a new engine (e.g. local_tts) only requires:
      1. Implement the engine class
      2. Register it here with register_engine()
    All call sites use get_engine() and never branch on engine names.
    """

    _engines: Dict[str, Callable] = {}

    @classmethod
    def register_engine(cls, name: str, synthesize_fn: Callable):
        """Register a TTS engine by name."""
        cls._engines[name] = synthesize_fn

    @classmethod
    def get_engine(cls, name: str) -> Optional[Callable]:
        """Get synthesize function for engine name. Returns None if not found."""
        return cls._engines.get(name)

    @classmethod
    def list_engines(cls) -> list:
        """List all registered engine names."""
        return list(cls._engines.keys())


# Register built-in engines
def _volcano_synthesize(text: str, speaker: str, figure_id: str, timeout: float = 15.0) -> Optional[str]:
    """Synthesize via Volcengine TTS API. Returns mp3 path or None."""
    return _synthesize_volcano_impl(text, speaker, figure_id, timeout)


def _system_synthesize(text: str, speaker: str, figure_id: str, **kwargs) -> Optional[str]:
    """Synthesize via macOS say. Returns True (plays async) or None."""
    ok = synthesize_system_say(text, speaker, **kwargs)
    return "/dev/null" if ok else None  # path not used for system_say


TTSEngineRegistry.register_engine("volcano_tts", _volcano_synthesize)
TTSEngineRegistry.register_engine("system_tts", _system_synthesize)


# ============== Config ==============

def _volc_config() -> dict:
    return {
        "api_key": os.getenv("VOLC_TTS_API_KEY", "").strip(),
        "resource_id": os.getenv("VOLC_TTS_RESOURCE_ID", "").strip(),
        "endpoint": os.getenv("VOLC_TTS_ENDPOINT", "https://openspeech.bytedance.com/api/v3/tts/unidirectional").strip(),
        "default_speaker": os.getenv("VOLC_TTS_DEFAULT_SPEAKER", "zh_male_beijingxiaoye_emo_v2_mars_bigtts").strip(),
    }


def is_volc_configured() -> bool:
    cfg = _volc_config()
    return bool(cfg["api_key"] and cfg["resource_id"])


# ============== Volcengine TTS Implementation ==============

def _synthesize_volcano_impl(
    text: str,
    speaker: str,
    figure_id: str,
    timeout: float = 15.0,
    *,
    audio_format: str = "mp3",
    sample_rate: int = 24000,
) -> Optional[str]:
    """
    Call Volcengine TTS API.
    The API returns streaming multi-line JSON: each line is a separate JSON object.
    We concatenate all base64 data fields and save the requested audio format.
    
    For uranus series speakers (e.g., zh_female_chunribu_uranus_bigtts), 
    use TTS v2 bidirectional WebSocket protocol.
    """
    if audio_format not in {"mp3", "pcm"}:
        raise ValueError("audio_format must be mp3 or pcm")
    if sample_rate not in {16000, 24000}:
        raise ValueError("sample_rate must be 16000 or 24000")

    # Check if this is a v2 uranus speaker
    if "_uranus_" in speaker:
        return _synthesize_volcano_v2_impl(
            text,
            speaker,
            figure_id,
            timeout,
            audio_format=audio_format,
            sample_rate=sample_rate,
        )
    
    # Fallback to v1 HTTP protocol for other speakers
    cfg = _volc_config()
    headers = {
        "x-api-key": cfg["api_key"],
        "X-Api-Resource-Id": cfg["resource_id"],
        "Content-Type": "application/json",
    }
    payload = {
        "req_params": {
            "text": text,
            "speaker": speaker or cfg["default_speaker"],
            "audio_params": {
                "format": audio_format,
                "sample_rate": sample_rate,
            },
        }
    }
    url = cfg["endpoint"]

    print(f"[DEBUG vol] CALLING API v1: text={text[:10]} speaker={speaker}", flush=True)
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = client.post(url, headers=headers, json=payload)
        print(f"[DEBUG vol] resp.status={resp.status_code}", flush=True)

        if resp.status_code != 200:
            return None

        # Streaming multi-line JSON: each line is a separate JSON object
        audio_chunks = []
        lines = resp.text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            code = obj.get("code", -1)
            if code != 0:
                continue
            data_field = obj.get("data", "")
            if data_field:
                try:
                    decoded = base64.b64decode(data_field)
                    audio_chunks.append(decoded)
                except Exception:
                    pass

        if not audio_chunks:
            return None

        full_audio = b"".join(audio_chunks)
        if len(full_audio) < 100:
            return None

        cache_dir = AUDIO_CACHE_DIR / figure_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}.{audio_format}"
        filepath = cache_dir / filename
        with open(filepath, "wb") as f:
            f.write(full_audio)
        return str(filepath)

    except Exception:
        return None


def _synthesize_volcano_v2_impl(
    text: str,
    speaker: str,
    figure_id: str,
    timeout: float = 15.0,
    *,
    audio_format: str = "mp3",
    sample_rate: int = 24000,
) -> Optional[str]:
    """
    Call Volcengine TTS v2 Bidirectional WebSocket API for uranus speakers.
    
    Returns the requested audio path or None on failure.
    """
    print(f"[DEBUG vol] CALLING API v2 (uranus): text={text[:10]} speaker={speaker}", flush=True)
    
    try:
        from app.core.volc_tts_v2 import synthesize_v2
        
        audio_bytes = synthesize_v2(
            text,
            speaker,
            audio_format=audio_format,
            sample_rate=sample_rate,
        )
        if not audio_bytes or len(audio_bytes) < 100:
            return None

        cache_dir = AUDIO_CACHE_DIR / figure_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}.{audio_format}"
        filepath = cache_dir / filename
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        print(f"[DEBUG vol] v2 success, saved to {filepath}", flush=True)
        return str(filepath)

    except Exception as e:
        print(f"[DEBUG vol] v2 error: {e}", flush=True)
        return None


# ============== System Say ==============

def synthesize_system_say(
    text: str,
    system_voice_name: Optional[str] = None,
    speech_rate: int = 175,
    async_mode: bool = True,
) -> bool:
    """Speak via macOS say. Returns True if launched."""
    if not text:
        return False
    cmd = ["say"]
    if system_voice_name:
        cmd += ["-v", system_voice_name]
    cmd += ["-r", str(speech_rate), "--", text]
    try:
        def _run():
            subprocess.run(cmd, capture_output=True, timeout=30)
        if async_mode:
            t = threading.Thread(target=_run, daemon=True)
            t.start()
        else:
            _run()
        return True
    except Exception:
        return False


# ============== VoxCPM2 stub ==============

def synthesize_voxcpm2(text: str, **kwargs) -> Optional[str]:
    """Placeholder for voice cloning TTS. Not implemented yet."""
    from app.core.voxcpm2_adapter import synthesize_with_cloned
    # Delegates to voxcpm2_adapter when implemented
    try:
        figure_id = kwargs.get("figure_id", "unknown")
        return synthesize_with_cloned(text, figure_id)
    except NotImplementedError:
        raise


# ============== Voice Pool ==============

def get_voice_pool_path(figure_id: str) -> Path:
    """Return voice pool directory for a figure."""
    return VOICE_POOL_DIR / figure_id


def get_pool_index_path(figure_id: str) -> Path:
    """Return voice pool text→mp3 index path for a figure."""
    return get_voice_pool_path(figure_id) / "index.json"


def load_voice_pool_index(figure_id: str) -> Dict[str, str]:
    """Load text→mp3 path index. Returns {} if not precached."""
    idx_path = get_pool_index_path(figure_id)
    if not idx_path.exists():
        return {}
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_voice_pool_index(figure_id: str, index: Dict[str, str]) -> None:
    """Save text→mp3 path index."""
    pool_dir = get_voice_pool_path(figure_id)
    pool_dir.mkdir(parents=True, exist_ok=True)
    idx_path = get_pool_index_path(figure_id)
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def load_archetype_pool_texts(archetype: str) -> list:
    """Load voice pool texts for an archetype from data/voice_pool_texts/{archetype}.json."""
    path = VOICE_POOL_TEXTS_DIR / f"{archetype}.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("texts", [])
    except Exception:
        return []


def is_voice_pool_ready(figure_id: str) -> bool:
    """Returns True if voice pool is precached for this figure."""
    idx = load_voice_pool_index(figure_id)
    return len(idx) > 0


def play_from_voice_pool(text: str, figure_id: str) -> bool:
    """
    Play a pre-cached mp3 from the voice pool.
    Matches text (exact or by hash) against pool index.
    Returns True if played, False if not found.
    """
    index = load_voice_pool_index(figure_id)
    if not index:
        return False

    # Try exact match first
    mp3_path = index.get(text)
    if mp3_path and Path(mp3_path).exists():
        return play_mp3(mp3_path, scope_id=figure_id)

    # Try hash match (for archetypes with many texts)
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    for key, path in index.items():
        if key == text_hash and Path(path).exists():
            return play_mp3(path, scope_id=figure_id)

    return False


def pick_pool_text(archetype: str, intent: str = "default") -> Optional[str]:
    """
    Pick a random text from the archetype voice pool.
    intent currently unused (reserved for future matching).
    """
    texts = load_archetype_pool_texts(archetype)
    if not texts:
        return None
    import random
    return random.choice(texts)


# ============== Precaching ==============

def precache_voice_pool(
    figure_id: str,
    voice_profile: dict,
    archetype: str,
    figure: Optional[dict] = None,
) -> dict:
    """
    Pre-synthesize all voice pool texts for a figure using its volcano speaker.
    Stores mp3s in data/voice_pool/{figure_id}/.
    Saves text→mp3 index.
    Returns {total, success, failed} counts.
    """
    speaker = voice_profile.get("speaker") or _volc_config()["default_speaker"]

    # Load archetype pool texts
    pool_texts = load_archetype_pool_texts(archetype)
    if not pool_texts:
        return {"total": 0, "success": 0, "failed": 0, "error": f"No pool texts for archetype: {archetype}"}

    # Add figure's own touch reaction texts (4 categories) and greeting
    touch_texts = set()
    if figure:
        touch_reactions = figure.get("touch_reactions", {})
        soul_profile = figure.get("soul_profile", {})
        for texts in touch_reactions.values():
            if isinstance(texts, list):
                touch_texts.update(texts)
        greeting = soul_profile.get("persona", {}).get("greeting")
        if greeting:
            touch_texts.add(greeting)
    else:
        # Fallback to voice_profile for backwards compat
        for texts in voice_profile.get("touch_reactions", {}).values():
            if isinstance(texts, list):
                touch_texts.update(texts)

    all_texts = list(set(pool_texts + list(touch_texts)))

    pool_dir = get_voice_pool_path(figure_id)
    pool_dir.mkdir(parents=True, exist_ok=True)

    index = {}
    success = 0
    failed = 0

    for text in all_texts:
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        filepath = pool_dir / f"{text_hash}.mp3"

        if filepath.exists():
            # Already cached
            index[text] = str(filepath)
            success += 1
            continue

        mp3_path = synthesize_volcano_for_pool(text, speaker, figure_id)
        if mp3_path and Path(mp3_path).exists():
            # Move to voice pool dir with hash name
            dest = pool_dir / f"{text_hash}.mp3"
            try:
                Path(mp3_path).rename(dest)
                index[text] = str(dest)
                success += 1
            except Exception:
                failed += 1
        else:
            failed += 1

    # Also save index keyed by hash for flexibility
    hash_index = {hashlib.md5(t.encode("utf-8")).hexdigest(): index.get(t) for t in index}
    index.update(hash_index)

    save_voice_pool_index(figure_id, index)

    return {"total": len(all_texts), "success": success, "failed": failed}


def synthesize_volcano_for_pool(text: str, speaker: str, figure_id: str) -> Optional[str]:
    """Synthesize text and return mp3 path (used for precaching)."""
    return _synthesize_volcano_impl(text, speaker, figure_id, timeout=15.0)


# ============== MP3 Playback ==============

def play_mp3(filepath: str, scope_id: Optional[str] = None) -> bool:
    """Play mp3 via macOS afplay (now uses global playback queue to avoid overlapping)."""
    # 改为使用队列，保证同一时刻只有一个音频在播放
    return play_mp3_enqueue(filepath, scope_id=scope_id)


# ============== Main Speak API ==============

def speak_with_engine(
    text: str,
    voice_profile: dict,
    figure_id: str,
    async_mode: bool = True,
    force_offline: bool = False,
    soul_profile: Optional[dict] = None,
) -> dict:
    """
    Main entry point: speak text using configured TTS engine.
    Priority:
      1. Online + volcano configured → real-time volcano synthesis
      2. Offline / volcano failed + voice_pool ready → play precached pool mp3
      3. Pool not ready / pool miss → system_say fallback (last resort)
    Returns: {engine, audio_path, success}
    """
    if not text:
        return {"engine": "none", "audio_path": None, "success": False}

    tts_engine = voice_profile.get("tts_engine", "volcano_tts")
    speaker = voice_profile.get("speaker") or _volc_config()["default_speaker"]
    system_voice = voice_profile.get("system_voice_name")
    speech_rate = voice_profile.get("speech_rate", 175)
    archetype = (soul_profile or {}).get("archetype", "软萌治愈型") if soul_profile else "软萌治愈型"

    print(f"[DEBUG speak] text={text[:10]} tts_engine={tts_engine} configured={is_volc_configured()} force_offline={force_offline}", flush=True)

    # 【VoxCPM 零样本克隆】优先走克隆音色
    if (voice_profile.get("voice_mode") == "voice_clone"
            and voice_profile.get("clone_engine") == "voxcpm"
            and voice_profile.get("clone_status") == "ready"):
        from app.core import voxcpm_adapter
        ref = voice_profile.get("clone_ref_path")
        ptext = voice_profile.get("clone_prompt_text", "")
        if ref and voxcpm_adapter.is_configured():
            path = voxcpm_adapter.clone_synthesize(text, ref, ptext, figure_id=figure_id)
            if path:
                play_mp3(path, scope_id=figure_id)  # afplay 也能放 wav
                return {"engine": "voxcpm_clone", "audio_path": path, "success": True}
        # VoxCPM 不可用 → 继续往下走火山预设音色(优雅回退)

    # Online path: try volcano TTS
    if not force_offline and tts_engine in ("volcano_tts", "system_tts") and is_volc_configured():
        print("[DEBUG speak] trying volcano_tts (online)", flush=True)
        path = _synthesize_volcano_impl(text, speaker=speaker, figure_id=figure_id, timeout=15.0)
        if path:
            play_mp3(path, scope_id=figure_id)
            return {"engine": "volcano_tts", "audio_path": path, "success": True}

    # VoxCPM2 placeholder
    if tts_engine == "voxcpm2":
        try:
            path = synthesize_voxcpm2(text, speaker=speaker, figure_id=figure_id)
            return {"engine": "voxcpm2", "audio_path": path, "success": path is not None}
        except NotImplementedError:
            pass

    # Voice pool path (offline or volcano failed)
    if not force_offline:
        # First volcano attempt failed - try pool
        print("[DEBUG speak] trying voice_pool (volcano failed)", flush=True)
        if is_voice_pool_ready(figure_id):
            if play_from_voice_pool(text, figure_id):
                # Return pool path in audio_path for tracking
                index = load_voice_pool_index(figure_id)
                pool_path = index.get(text) or ""
                return {"engine": "voice_pool", "audio_path": pool_path, "success": True}

    # Pool path on explicit offline mode
    if force_offline:
        print("[DEBUG speak] trying voice_pool (offline mode)", flush=True)
        if is_voice_pool_ready(figure_id):
            if play_from_voice_pool(text, figure_id):
                index = load_voice_pool_index(figure_id)
                pool_path = index.get(text) or ""
                return {"engine": "voice_pool", "audio_path": pool_path, "success": True}
        # Pick a pool text if none matched
        pool_text = pick_pool_text(archetype)
        if pool_text and is_voice_pool_ready(figure_id):
            if play_from_voice_pool(pool_text, figure_id):
                index = load_voice_pool_index(figure_id)
                pool_path = index.get(pool_text) or ""
                return {"engine": "voice_pool", "audio_path": pool_path, "success": True}

    # Last resort: system say
    print("[DEBUG speak] falling back to system_tts (last resort)", flush=True)
    ok = synthesize_system_say(text, system_voice, speech_rate, async_mode=async_mode)
    return {"engine": "system_tts", "audio_path": None, "success": ok}


# ============== Synthesize + Save (no play) ==============

def synthesize_and_save(
    text: str,
    voice_profile: dict,
    figure_id: str,
    speaker: Optional[str] = None,
) -> Optional[str]:
    """Synthesize and save audio (no auto-play). Returns mp3 path or None."""
    if not text:
        return None
    effective_speaker = speaker or voice_profile.get("speaker") or _volc_config()["default_speaker"]
    if is_volc_configured():
        return _synthesize_volcano_impl(text, speaker=effective_speaker, figure_id=figure_id)
    return None


def synthesize_for_delivery(
    text: str,
    voice_profile: dict,
    figure_id: str,
    *,
    speaker: Optional[str] = None,
) -> dict:
    """Create an audio file without playing it on the server."""
    if not text or not text.strip():
        return {
            "engine": "none",
            "audio_path": None,
            "success": False,
            "error": "empty_text",
        }

    # An explicit speaker means preset-voice preview. It must not accidentally
    # reuse the figure's cloned voice or a pool generated for another speaker.
    if speaker is None and (
        voice_profile.get("voice_mode") == "voice_clone"
        and voice_profile.get("clone_engine") == "voxcpm"
        and voice_profile.get("clone_status") == "ready"
    ):
        from app.core import voxcpm_adapter

        reference = voice_profile.get("clone_ref_path")
        prompt_text = voice_profile.get("clone_prompt_text", "")
        if reference and voxcpm_adapter.is_configured():
            path = voxcpm_adapter.clone_synthesize(
                text,
                reference,
                prompt_text,
                figure_id=figure_id,
            )
            if path:
                return {
                    "engine": "voxcpm_clone",
                    "audio_path": path,
                    "success": True,
                    "error": None,
                }

    effective_speaker = (
        speaker
        or voice_profile.get("speaker")
        or _volc_config()["default_speaker"]
    )
    if is_volc_configured():
        path = _synthesize_volcano_impl(
            text,
            speaker=effective_speaker,
            figure_id=figure_id,
            timeout=15.0,
        )
        if path:
            return {
                "engine": "volcano_tts",
                "audio_path": path,
                "success": True,
                "error": None,
            }

    if speaker is None:
        pool_path = load_voice_pool_index(figure_id).get(text) or ""
        if pool_path and Path(pool_path).is_file():
            return {
                "engine": "voice_pool",
                "audio_path": pool_path,
                "success": True,
                "error": None,
            }

    return {
        "engine": "none",
        "audio_path": None,
        "success": False,
        "error": "no_deliverable_audio",
    }


# ============== Streaming TTS =============

def synthesize_sentence_async(
    text: str,
    voice_profile: dict,
    figure_id: str,
    on_done: Optional[Callable[[str], None]] = None,
) -> None:
    """Synthesize one sentence in a daemon thread (non-blocking)."""
    def _run():
        path = synthesize_and_save(text, voice_profile, figure_id)
        if path and on_done:
            on_done(path)
        elif path:
            play_mp3(path, scope_id=figure_id)
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def speak_sentence_streaming(
    text: str,
    voice_profile: dict,
    figure_id: str,
    async_mode: bool = True,
    force_offline: bool = False,
    soul_profile: Optional[dict] = None,
    audio_sink: Optional[Callable[[bytes], bool]] = None,
    cancel_event: Optional[threading.Event] = None,
    audio_format: str = "mp3",
    sample_rate: int = 24000,
) -> dict:
    """Synthesize one sentence and deliver it to exactly one output target."""
    if audio_format not in {"mp3", "pcm"}:
        raise ValueError("audio_format must be mp3 or pcm")
    if sample_rate not in {16000, 24000}:
        raise ValueError("sample_rate must be 16000 or 24000")
    if not text:
        return {
            "engine": "none",
            "audio_path": None,
            "success": False,
            "synthesized": False,
            "transferred": False,
            "error": "empty_text",
        }
    
    # 【Barge-in】合成前检查是否被打断
    if cancel_event and cancel_event.is_set():
        return {
            "engine": "cancelled",
            "audio_path": None,
            "success": False,
            "synthesized": False,
            "transferred": False,
            "error": "cancelled",
        }
    
    tts_engine = voice_profile.get("tts_engine", "volcano_tts")
    speaker = voice_profile.get("speaker") or _volc_config()["default_speaker"]
    system_voice = voice_profile.get("system_voice_name")
    speech_rate = voice_profile.get("speech_rate", 175)
    archetype = (soul_profile or {}).get("archetype", "软萌治愈型") if soul_profile else "软萌治愈型"

    # 【VoxCPM 零样本克隆】优先走克隆音色
    if (audio_format == "mp3"
            and voice_profile.get("voice_mode") == "voice_clone"
            and voice_profile.get("clone_engine") == "voxcpm"
            and voice_profile.get("clone_status") == "ready"):
        from app.core import voxcpm_adapter
        ref = voice_profile.get("clone_ref_path")
        ptext = voice_profile.get("clone_prompt_text", "")
        if ref and voxcpm_adapter.is_configured():
            path = voxcpm_adapter.clone_synthesize(text, ref, ptext, figure_id=figure_id)
            if path:
                if audio_sink:
                    try:
                        with open(path, "rb") as f:
                            transferred = audio_sink(f.read()) is True
                    except Exception:
                        transferred = False
                    return {
                        "engine": "voxcpm_clone",
                        "audio_path": path,
                        "success": transferred,
                        "synthesized": True,
                        "transferred": transferred,
                        "error": None if transferred else "audio_transfer_failed",
                    }
                else:
                    played = play_mp3(path, scope_id=figure_id)  # afplay 也能放 wav
                    return {
                        "engine": "voxcpm_clone",
                        "audio_path": path,
                        "success": played,
                        "synthesized": True,
                        "transferred": False,
                        "played_locally": played,
                    }
        # VoxCPM 不可用 → 继续往下走火山预设音色(优雅回退)

    if not force_offline and tts_engine in ("volcano_tts", "system_tts") and is_volc_configured():
        path = _synthesize_volcano_impl(
            text,
            speaker=speaker,
            figure_id=figure_id,
            timeout=10.0,
            audio_format=audio_format,
            sample_rate=sample_rate,
        )
        if path:
            # 合成后再次检查是否被打断
            if cancel_event and cancel_event.is_set():
                return {
                    "engine": "cancelled",
                    "audio_path": None,
                    "success": False,
                    "synthesized": True,
                    "transferred": False,
                    "error": "cancelled",
                }
            if audio_sink:
                # 使用 audio_sink 回传音频，不播放本地
                try:
                    with open(path, "rb") as f:
                        audio_bytes = f.read()
                    transferred = audio_sink(audio_bytes) is True
                except Exception:
                    transferred = False
                return {
                    "engine": "volcano_tts",
                    "audio_path": path,
                    "success": transferred,
                    "synthesized": True,
                    "transferred": transferred,
                    "error": None if transferred else "audio_transfer_failed",
                }
            else:
                played = play_mp3(path, scope_id=figure_id)
                return {
                    "engine": "volcano_tts",
                    "audio_path": path,
                    "success": played,
                    "synthesized": True,
                    "transferred": False,
                    "played_locally": played,
                }

    if (
        audio_format == "mp3"
        and not force_offline
        and is_voice_pool_ready(figure_id)
    ):
        index = load_voice_pool_index(figure_id)
        pool_path = index.get(text) or ""
        if pool_path:
            if audio_sink:
                try:
                    with open(pool_path, "rb") as f:
                        mp3_bytes = f.read()
                    transferred = audio_sink(mp3_bytes) is True
                except Exception:
                    transferred = False
                return {
                    "engine": "voice_pool",
                    "audio_path": pool_path,
                    "success": transferred,
                    "synthesized": True,
                    "transferred": transferred,
                    "error": None if transferred else "audio_transfer_failed",
                }
            played = play_mp3(pool_path, scope_id=figure_id)
            return {
                "engine": "voice_pool",
                "audio_path": pool_path,
                "success": played,
                "synthesized": True,
                "transferred": False,
                "played_locally": played,
            }

    if (
        audio_format == "mp3"
        and force_offline
        and is_voice_pool_ready(figure_id)
    ):
        index = load_voice_pool_index(figure_id)
        pool_path = index.get(text) or ""
        if pool_path:
            if audio_sink:
                try:
                    with open(pool_path, "rb") as f:
                        mp3_bytes = f.read()
                    transferred = audio_sink(mp3_bytes) is True
                except Exception:
                    transferred = False
                return {
                    "engine": "voice_pool",
                    "audio_path": pool_path,
                    "success": transferred,
                    "synthesized": True,
                    "transferred": transferred,
                    "error": None if transferred else "audio_transfer_failed",
                }
            played = play_mp3(pool_path, scope_id=figure_id)
            return {
                "engine": "voice_pool",
                "audio_path": pool_path,
                "success": played,
                "synthesized": True,
                "transferred": False,
                "played_locally": played,
            }

    if audio_sink:
        # system_say only reaches the server speaker and cannot satisfy a
        # browser/device delivery request.
        return {
            "engine": "none",
            "audio_path": None,
            "success": False,
            "synthesized": False,
            "transferred": False,
            "error": "no_deliverable_audio",
        }

    played = synthesize_system_say(
        text,
        system_voice,
        speech_rate,
        async_mode=async_mode,
    )
    return {
        "engine": "system_tts",
        "audio_path": None,
        "success": played,
        "synthesized": played,
        "transferred": False,
        "played_locally": played,
        "error": None if played else "system_tts_failed",
    }
