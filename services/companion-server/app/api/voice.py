# services/companion-server/app/api/voice.py
"""
Voice API: TTS synthesis, voice design, speaker list.
Day 6: Volcano TTS integration with system_say fallback.
"""
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional
from pydantic import BaseModel

from data.store import save_voice_upload, get_figure, save_figure
from app.core.tts_adapter import (
    synthesize_and_save,
    speak_with_engine,
    is_volc_configured,
    is_voice_pool_ready,
    precache_voice_pool,
    _volc_config,
)

router = APIRouter()


# ============== Voice Upload (Day 5) =============

@router.post("/upload")
async def voice_upload(
    figure_id: str = Form(...),
    audio: UploadFile = File(...),
    consent_agreed: bool = Form(...),
    consent_text_version: str = Form("v1"),
):
    """Upload reference audio for voice cloning (MVP: saves file + updates status only)."""
    figure = get_figure(figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    # 【合规检查】必须同意授权声明
    if not consent_agreed:
        raise HTTPException(status_code=400, detail="需先确认音色授权声明")

    contents = await audio.read()
    saved_path = save_voice_upload(figure_id, audio.filename or "recording.wav", contents)

    voice_profile = figure.get("voice_profile", {})
    voice_profile["voice_mode"] = "voice_clone"
    voice_profile["voice_status"] = "pending_clone"
    voice_profile["clone_status"] = "pending"
    voice_profile["recording_url"] = str(saved_path)
    
    # 【审计记录】保存授权信息
    voice_profile["consent"] = {
        "agreed": True,
        "text_version": consent_text_version,
        "agreed_at": datetime.utcnow().isoformat(),
        "source_filename": audio.filename or "",
    }

    figure["voice_profile"] = voice_profile
    figure["updated_at"] = datetime.utcnow().isoformat()
    save_figure(figure_id, figure)

    return {
        "voice_profile": voice_profile,
        "saved_path": str(saved_path),
    }


# ============== Voice Generate =============

class VoiceGenerateRequest(BaseModel):
    figure_id: str
    text: str
    speaker: Optional[str] = None   # override figure's default speaker


@router.post("/generate")
def voice_generate(req: VoiceGenerateRequest):
    """
    Synthesize audio for given text using the figure's TTS engine.
    Plays audio via afplay (volcano) or say (system), and returns audio_path.
    """
    figure = get_figure(req.figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    voice_profile = figure.get("voice_profile", {})
    soul_profile = figure.get("soul_profile", {})

    # Debug
    import app.core.tts_adapter as tts_adapter
    cfg = tts_adapter._volc_config()
    print(f"[DEBUG voice/generate] tts_engine={voice_profile.get('tts_engine')} configured={tts_adapter.is_volc_configured()} api_key={cfg.get('api_key','?')[:8]} speaker={cfg.get('default_speaker')}", flush=True)

    # synthesize + play
    result = speak_with_engine(
        text=req.text,
        voice_profile=voice_profile,
        figure_id=req.figure_id,
        async_mode=True,
        soul_profile=soul_profile,
    )

    return {
        "text": req.text,
        "engine": result["engine"],
        "audio_path": result.get("audio_path"),
        "success": result["success"],
        "speaker": voice_profile.get("speaker") or req.speaker,
        "figure_id": req.figure_id,
        "voice_profile": voice_profile,
    }


# ============== Voice Pool Precache =============

class VoicePrecacheRequest(BaseModel):
    figure_id: str


@router.post("/precache")
def voice_precache(req: VoicePrecacheRequest):
    """
    Pre-synthesize all voice pool texts for a figure using its volcano speaker.
    Stores mp3s in data/voice_pool/{figure_id}/.
    Returns {total, success, failed, voice_pool_ready}.
    """
    figure = get_figure(req.figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    voice_profile = figure.get("voice_profile", {})
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")

    result = precache_voice_pool(
        figure_id=req.figure_id,
        voice_profile=voice_profile,
        archetype=archetype,
        figure=figure,
    )
    result["voice_pool_ready"] = is_voice_pool_ready(req.figure_id)

    return result


@router.get("/pool-status/{figure_id}")
def voice_pool_status(figure_id: str):
    """Return voice pool status for a figure."""
    figure = get_figure(figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    ready = is_voice_pool_ready(figure_id)
    index = {}
    if ready:
        from app.core.tts_adapter import load_voice_pool_index
        index = load_voice_pool_index(figure_id)

    return {
        "figure_id": figure_id,
        "voice_pool_ready": ready,
        "cached_count": len(index),
    }


# ============== Voice Design =============

class VoiceDesignRequest(BaseModel):
    figure_id: str
    speaker: str                      # volcano speaker ID to set
    tts_engine: Optional[str] = None  # optional: change engine too


@router.post("/design")
def voice_design(req: VoiceDesignRequest):
    """
    Set / switch the figure's volcano speaker.
    Updates voice_profile.speaker + tts_engine=volcano_tts.
    """
    figure = get_figure(req.figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    voice_profile = figure.get("voice_profile", {})
    voice_profile["speaker"] = req.speaker
    if req.tts_engine:
        voice_profile["tts_engine"] = req.tts_engine
    else:
        voice_profile["tts_engine"] = "volcano_tts"

    figure["voice_profile"] = voice_profile
    figure["updated_at"] = datetime.utcnow().isoformat()
    save_figure(req.figure_id, figure)

    return {
        "voice_profile": voice_profile,
        "message": f"Speaker set to {req.speaker}",
    }


# ============== Speaker List =============

@router.get("/speakers")
def list_speakers(include_ip: bool = False):
    """
    Return available TTS speakers, grouped by gender + category.
    Reads from voice_library.json, falls back to hardcoded list if file not found.

    Query params:
        include_ip: 是否包含 IP 仿音/真人模仿音色（默认 false，合规不上架）
    """
    cfg = _volc_config()
    default = cfg["default_speaker"]
    volc_available = is_volc_configured()

    all_speakers = _load_voice_library()

    # 默认过滤 IP 仿音
    if not include_ip:
        all_speakers = [s for s in all_speakers if not s.get("ip_risk", False)]

    # 按 gender + category 分组
    category_groups: dict[tuple, list] = {}
    for s in all_speakers:
        key = (s.get("gender", "unknown"), s.get("category", "其他"))
        if key not in category_groups:
            category_groups[key] = []
        category_groups[key].append(s)

    categories = []
    for (gender, category), spks in category_groups.items():
        cat_key = f"{gender}_{category}"
        categories.append({
            "key": cat_key,
            "gender": gender,
            "category": category,
            "speakers": spks,
        })

    # 按性别排序：女声在前，男声在后
    categories.sort(key=lambda c: (0 if c["gender"] == "female" else 1, c["category"]))

    return {
        "available": volc_available,
        "configured_speaker": default,
        "total": len(all_speakers),
        "categories": categories,
        "speakers": all_speakers,
    }


def _load_voice_library() -> list:
    """Load voice library from JSON file, fallback to hardcoded list."""
    import json
    import os

    lib_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "voice_library.json")
    lib_path = os.path.abspath(lib_path)

    try:
        with open(lib_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Voice Library] Failed to load {lib_path}: {e}, using fallback")
        return _fallback_speakers()


def _fallback_speakers() -> list:
    """Hardcoded fallback speaker list."""
    return [
        {"speaker_id": "zh_female_roumeinvyou_emo_v2_mars_bigtts", "name": "柔美女性", "gender": "female", "age_group": "青年", "category": "多情感", "styles": ["温柔", "治愈"], "emotions": [], "description": "温柔治愈,适合软萌陪伴", "demo_url": "", "recommended_archetypes": ["软萌治愈型"]},
        {"speaker_id": "zh_female_meilinvyou_emo_v2_mars_bigtts", "name": "魅力女友", "gender": "female", "age_group": "青年", "category": "多情感", "styles": ["御姐", "魅惑"], "emotions": [], "description": "成熟魅惑御姐音", "demo_url": "", "recommended_archetypes": ["御姐照顾型"]},
        {"speaker_id": "zh_female_gaolengyujie_emo_v2_mars_bigtts", "name": "高冷御姐", "gender": "female", "age_group": "青年", "category": "多情感", "styles": ["高冷", "清冷"], "emotions": [], "description": "清冷疏离,适合守护型", "demo_url": "", "recommended_archetypes": ["冷淡守护型"]},
        {"speaker_id": "zh_female_tianmeitaozi_mars_bigtts", "name": "甜妹桃子", "gender": "female", "age_group": "少女", "category": "通用场景", "styles": ["甜美", "元气"], "emotions": [], "description": "甜美少女音", "demo_url": "", "recommended_archetypes": ["傲娇吐槽型", "潮玩幸运型"]},
        {"speaker_id": "zh_female_shuangkuaisisi_moon_bigtts", "name": "爽快思思", "gender": "female", "age_group": "青年", "category": "通用场景", "styles": ["元气", "爽快"], "emotions": [], "description": "活泼爽快,元气满满", "demo_url": "", "recommended_archetypes": ["元气伙伴型"]},
        {"speaker_id": "zh_female_kailangjiejie_moon_bigtts", "name": "开朗姐姐", "gender": "female", "age_group": "青年", "category": "通用场景", "styles": ["开朗", "亲和"], "emotions": [], "description": "开朗亲和大姐姐", "demo_url": "", "recommended_archetypes": ["萌宠陪伴型"]},
        {"speaker_id": "zh_female_chunribu_uranus_bigtts", "name": "春日部姐姐", "gender": "female", "age_group": "青年", "category": "多情感", "styles": ["温柔", "知性"], "emotions": [], "description": "温柔知性情感音(v2)", "demo_url": "", "recommended_archetypes": ["软萌治愈型"]},
        {"speaker_id": "zh_male_yangguangqingnian_emo_v2_mars_bigtts", "name": "阳光青年", "gender": "male", "age_group": "青年", "category": "多情感", "styles": ["阳光", "清爽"], "emotions": [], "description": "阳光清爽青年音", "demo_url": "", "recommended_archetypes": ["机械副官型"]},
        {"speaker_id": "zh_male_beijingxiaoye_emo_v2_mars_bigtts", "name": "北京小哥", "gender": "male", "age_group": "青年", "category": "趣味口音", "styles": ["憨厚", "京味"], "emotions": [], "description": "憨厚京味,亲切接地气", "demo_url": "", "recommended_archetypes": ["憨憨吃货型"]},
        {"speaker_id": "zh_male_jingqiangkanye_moon_bigtts", "name": "京腔侃爷", "gender": "male", "age_group": "中年", "category": "趣味口音", "styles": ["京味", "幽默"], "emotions": [], "description": "京腔幽默,贫嘴有趣", "demo_url": "", "recommended_archetypes": ["搞怪捣蛋型"]},
        {"speaker_id": "zh_male_sunwukong_mars_bigtts", "name": "孙悟空", "gender": "male", "age_group": "特色", "category": "角色扮演", "styles": ["桀骜", "戏曲"], "emotions": [], "description": "齐天大圣特色音", "demo_url": "", "recommended_archetypes": ["桀骜战神型"], "ip_risk": True},
    ]


# ============== Voice Clone (VoxCPM) =============

class VoiceCloneStartRequest(BaseModel):
    figure_id: str
    prompt_text: Optional[str] = ""


@router.post("/clone/start")
async def voice_clone_start(req: VoiceCloneStartRequest):
    """开始声音克隆（VoxCPM 零样本克隆，无需训练）。"""
    figure = get_figure(req.figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    voice_profile = figure.get("voice_profile", {})
    
    # 校验授权同意
    consent = voice_profile.get("consent", {})
    if not consent.get("agreed"):
        raise HTTPException(status_code=400, detail="需先确认音色授权声明")
    
    # 校验参考音频
    recording_url = voice_profile.get("recording_url")
    if not recording_url:
        raise HTTPException(status_code=400, detail="请先上传参考音频")

    # VoxCPM 零样本克隆：无需训练，直接就绪
    voice_profile["clone_engine"] = "voxcpm"
    voice_profile["clone_ref_path"] = recording_url
    voice_profile["clone_prompt_text"] = req.prompt_text or ""
    voice_profile["voice_mode"] = "voice_clone"
    voice_profile["clone_status"] = "ready"
    
    figure["voice_profile"] = voice_profile
    figure["updated_at"] = datetime.utcnow().isoformat()
    save_figure(req.figure_id, figure)

    return {
        "clone_status": "ready",
        "clone_engine": "voxcpm",
        "message": "VoxCPM 克隆已就绪",
    }


@router.get("/clone/status")
def voice_clone_status(figure_id: str):
    """查询克隆状态（VoxCPM 直接返回已就绪）。"""
    figure = get_figure(figure_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    voice_profile = figure.get("voice_profile", {})
    clone_status = voice_profile.get("clone_status", "not_started")
    
    return {
        "clone_status": clone_status,
        "clone_engine": voice_profile.get("clone_engine"),
    }
