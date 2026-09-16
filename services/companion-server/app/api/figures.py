# services/companion-server/app/api/figures.py
import sys
from pathlib import Path
from datetime import datetime, timedelta
import uuid
from typing import Optional, List, Dict, Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import get_current_user
from app.api.dev_tools import require_dev_tools
from app.api.ownership import current_user_id
from data.store import (
    DataIntegrityError,
    create_figure_idempotent,
    delete_figure,
    get_archetypes,
    get_figure,
    list_bases_for_owner,
    list_figures,
    save_base,
    save_figure,
)

from app.core.life_engine import apply_time_decay, neglect_tier, get_status_description
from app.core.relationship_engine import boost_relationship, set_streak, RELATIONSHIP_LEVELS, LEVEL_THRESHOLDS

router = APIRouter()


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _synchronize_persona_address(
    soul_profile: dict,
    *,
    preferred: Optional[str] = None,
) -> None:
    character_profile = soul_profile.get("character_profile")
    character_address = (
        character_profile.get("address_user_as")
        if isinstance(character_profile, dict)
        else None
    )
    candidates = (
        preferred,
        soul_profile.get("address_user_as"),
        character_address,
        "你",
    )
    address = "你"
    for candidate in candidates:
        normalized = str(candidate or "").strip()[:20]
        if normalized and normalized != "Eddie":
            address = normalized
            break
    soul_profile["address_user_as"] = address
    if isinstance(character_profile, dict):
        character_profile["address_user_as"] = address


# ============== Archetype Template Loader ==============

_ARCHETYPE_CACHE: Optional[List[Dict]] = None


def _load_archetype_template(archetype: str) -> Dict:
    """
    Load archetype template from archetypes.json.
    Returns the matched template dict, or a minimal default if not found.
    """
    global _ARCHETYPE_CACHE
    if _ARCHETYPE_CACHE is None:
        _ARCHETYPE_CACHE = get_archetypes()

    for tmpl in _ARCHETYPE_CACHE:
        if tmpl.get("archetype") == archetype:
            return tmpl

    # Fallback minimal template
    return {
        "archetype": archetype,
        "personality_traits": ["热情"],
        "recommended_voice": "Tingting",
        "greeting": "你好呀！",
        "speaking_style": "cute",
        "response_templates": {
            "figure_placed": ["你好呀！"],
            "light_touch": ["嘿嘿~"],
            "heavy_press": ["轻点啦！"],
            "double_tap": ["有什么事呀？"],
        },
    }


# ============== Default factories ==============

def _default_emotion_state() -> dict:
    return {
        "happy": 50,
        "lonely": 0,
        "attached": 0,
        "annoyed": 0,
        "attention": 0,
        "sleepy": 0,
        "last_dialogue_at": None,
    }


# ============== Request Models ==============

class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateFigureRequest(_StrictModel):
    name: str
    avatar_url: Optional[str] = None
    description: Optional[str] = None
    figure_type: str
    wake_names: List[str] = Field(default_factory=list)
    soul_profile: Optional[dict] = None
    voice_profile: Optional[dict] = None
    touch_reactions: Optional[dict] = None
    touch_escalation: Optional[dict] = None  # 触摸递进台词
    creation_request_id: Optional[str] = None
    activate_base_id: Optional[str] = None


class UpdateFigureRequest(_StrictModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    description: Optional[str] = None
    wake_names: Optional[List[str]] = None
    soul_profile: Optional[dict] = None
    voice_profile: Optional[dict] = None
    touch_reactions: Optional[dict] = None
    touch_escalation: Optional[dict] = None  # 触摸递进台词


# ============== API Endpoints ==============

@router.get("")
def get_figures(current_user: dict = Depends(get_current_user)):
    """List all figures."""
    user_id = current_user_id(current_user)
    return list_figures(user_id=user_id)


@router.post("")
def create_figure(req: CreateFigureRequest, current_user: dict = Depends(get_current_user)):
    """
    Create a new figure.
    Bug 1 fix: archetype template drives default touch_reactions / persona / voice.
    Bug 2 fix: emotion_state lives at soul_profile.emotion_state (not persona.emotion_state).
    Priority: explicit request field > archetype template > hard-coded default.
    """
    user_id = current_user_id(current_user)
    figure_id = _new_uuid()
    voice_id = _new_uuid()
    now = _now_iso()

    # Resolve archetype (explicit or default)
    explicit_archetype = req.soul_profile.get("archetype") if req.soul_profile else None
    archetype = explicit_archetype or "软萌治愈型"

    # Load archetype template
    tmpl = _load_archetype_template(archetype)

    # Build soul_profile with correct priority
    if req.soul_profile:
        # Start from archetype template, overlay explicit fields
        soul_profile = dict(req.soul_profile)
        # Ensure archetype field
        soul_profile["archetype"] = archetype

        # persona: template → explicit, then fill any missing keys
        explicit_persona = soul_profile.get("persona", {})
        tmpl_persona = {
            "traits": tmpl.get("personality_traits", []),
            "greeting": tmpl.get("greeting", "你好呀！"),
            "speaking_style": tmpl.get("speaking_style", "cute"),
            "response_templates": dict(tmpl.get("response_templates", {})),
        }
        # Deep merge: explicit persona keys override template
        merged_persona = dict(tmpl_persona)
        for k, v in explicit_persona.items():
            if k == "response_templates":
                # Merge each event type: explicit list overrides template list
                merged_rt = dict(tmpl_persona.get("response_templates", {}))
                for evt, lines in v.items():
                    if isinstance(lines, list) and lines:
                        merged_rt[evt] = lines
                merged_persona["response_templates"] = merged_rt
            elif v is not None:
                merged_persona[k] = v

        soul_profile["persona"] = merged_persona

        soul_profile.setdefault("name", req.name)
        soul_profile.setdefault("avatar_url", req.avatar_url)
        soul_profile.setdefault("description", req.description or "")
        soul_profile.setdefault("created_at", now)
        soul_profile.setdefault("updated_at", now)
        # emotion_state at soul_profile.emotion_state (Bug 2 fix)
        soul_profile.setdefault("emotion_state", _default_emotion_state())
    else:
        # No soul_profile in request → full archetype template
        tmpl_persona = {
            "traits": tmpl.get("personality_traits", []),
            "greeting": tmpl.get("greeting", "你好呀！"),
            "speaking_style": tmpl.get("speaking_style", "cute"),
            "response_templates": dict(tmpl.get("response_templates", {})),
        }
        soul_profile = {
            "archetype": archetype,
            "name": req.name,
            "avatar_url": req.avatar_url,
            "description": req.description or "",
            "address_user_as": "你",
            "persona": tmpl_persona,
            "emotion_state": _default_emotion_state(),  # Bug 2: at soul_profile level
            "created_at": now,
            "updated_at": now,
        }
    _synchronize_persona_address(soul_profile)

    # Build voice_profile: explicit > archetype recommended_voice > default
    # Day 6: add tts_engine + speaker fields
    if req.voice_profile:
        voice_profile = dict(req.voice_profile)
        voice_profile.setdefault("voice_id", voice_id)
        voice_profile.setdefault("name", "默认音色")
        voice_profile.setdefault("created_at", now)
        voice_profile.setdefault("updated_at", now)
        voice_profile.setdefault("voice_type", "system")
        voice_profile.setdefault("voice_mode", "default")
        voice_profile.setdefault("tts_engine", "volcano_tts")   # Day 6: default to volcano
        voice_profile.setdefault("speaker", tmpl.get("volcano_speaker", "zh_male_beijingxiaoye_emo_v2_mars_bigtts"))  # Day 6
        voice_profile.setdefault("speech_rate", 175)
        voice_profile.setdefault("recording_url", None)
        voice_profile.setdefault("voice_status", "ready")
        voice_profile.setdefault("clone_status", "not_started")
        voice_profile.setdefault("clone_engine", None)
        voice_profile.setdefault("cached_audio_path", None)
        # Use archetype recommended voice if not specified
        if not voice_profile.get("system_voice_name"):
            voice_profile["system_voice_name"] = tmpl.get("recommended_voice", "Tingting")
    else:
        voice_profile = {
            "voice_id": voice_id,
            "name": "默认音色",
            "created_at": now,
            "updated_at": now,
            "voice_type": "system",
            "voice_mode": "default",
            "tts_engine": "volcano_tts",                                   # Day 6
            "speaker": tmpl.get("volcano_speaker", "zh_male_beijingxiaoye_emo_v2_mars_bigtts"),  # Day 6
            "system_voice_name": tmpl.get("recommended_voice", "Tingting"),
            "speech_rate": 175,
            "recording_url": None,
            "voice_status": "ready",
            "clone_status": "not_started",
            "clone_engine": None,
            "cached_audio_path": None,
        }

    # Build touch_reactions: explicit > archetype template > hard-coded default
    if req.touch_reactions:
        # Start from archetype template, overlay explicit
        touch_reactions = dict(tmpl.get("response_templates", {
            "figure_placed": ["你好呀！"],
            "light_touch": ["嘿嘿~"],
            "heavy_press": ["轻点啦！"],
            "double_tap": ["有什么事呀？"],
        }))
        for evt, lines in req.touch_reactions.items():
            if isinstance(lines, list) and lines:
                touch_reactions[evt] = lines
    else:
        # Full archetype template
        touch_reactions = dict(tmpl.get("response_templates", {
            "figure_placed": ["你好呀！"],
            "light_touch": ["嘿嘿~"],
            "heavy_press": ["轻点啦！"],
            "double_tap": ["有什么事呀？"],
        }))

    # Memory
    memory = {
        "figure_id": figure_id,
        "interaction_count": 0,
        "last_interaction_at": None,
        "confirmed_facts": [],
        "memory_candidates": [],
        "memory_tombstones": [],
        "memory_revision": 0,
    }

    # Assemble figure
    figure = {
        "figure_id": figure_id,
        "name": req.name,
        "avatar_url": req.avatar_url,
        "description": req.description or "",
        "created_at": now,
        "updated_at": now,
        "base_id": None,
        "figure_type": req.figure_type,
        "wake_names": req.wake_names,
        "soul_profile": soul_profile,
        "voice_profile": voice_profile,
        "touch_reactions": touch_reactions,
        "touch_escalation": req.touch_escalation or {},  # 触摸递进台词，没传则留空
        "memory": memory,
    }

    try:
        saved, _created = create_figure_idempotent(
            figure_id,
            figure,
            user_id=user_id,
            creation_request_id=req.creation_request_id,
            activate_base_id=req.activate_base_id,
        )
    except (DataIntegrityError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="创建或激活失败，未完成写入，请检查底座后重试",
        ) from exc
    return saved


@router.get("/{figure_id}")
def get_figure_detail(figure_id: str, current_user: dict = Depends(get_current_user)):
    """Get a single figure.
    
    Phase B: 应用情绪衰减（懒计算），返回"现在"的情绪状态。
    """
    user_id = current_user_id(current_user)
    figure = get_figure(figure_id, user_id=user_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")
    
    # Phase B: 计算情绪衰减
    decayed_emotion, elapsed_hours = apply_time_decay(figure)
    tier = neglect_tier(elapsed_hours)
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    status_desc = get_status_description(elapsed_hours, decayed_emotion, archetype)
    
    # 更新 soul_profile.emotion_state 为衰减后的情绪（懒计算写回）
    soul = figure.get("soul_profile", {})
    soul["emotion_state"] = decayed_emotion
    figure["soul_profile"] = soul
    
    # 添加 Phase B 状态信息
    figure["life_status"] = {
        "elapsed_hours": elapsed_hours,
        "neglect_tier": tier,
        "status_description": status_desc,
    }
    
    return figure


@router.put("/{figure_id}")
def update_figure(figure_id: str, req: UpdateFigureRequest, current_user: dict = Depends(get_current_user)):
    """Update a figure."""
    user_id = current_user_id(current_user)
    figure = get_figure(figure_id, user_id=user_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    if req.name is not None:
        figure["name"] = req.name
    if req.avatar_url is not None:
        figure["avatar_url"] = req.avatar_url
    if req.description is not None:
        figure["description"] = req.description
    if req.wake_names is not None:
        figure["wake_names"] = req.wake_names
    if req.soul_profile is not None:
        figure["soul_profile"].update(req.soul_profile)
        incoming_character = req.soul_profile.get("character_profile")
        preferred_address = req.soul_profile.get("address_user_as")
        if not preferred_address and isinstance(incoming_character, dict):
            preferred_address = incoming_character.get("address_user_as")
        _synchronize_persona_address(
            figure["soul_profile"],
            preferred=preferred_address,
        )
    if req.voice_profile is not None:
        figure["voice_profile"].update(req.voice_profile)
    if req.touch_reactions is not None:
        figure["touch_reactions"].update(req.touch_reactions)
    if req.touch_escalation is not None:
        # 支持整体覆盖或部分更新
        if "light_touch" in req.touch_escalation or "heavy_press" in req.touch_escalation or "double_tap" in req.touch_escalation:
            figure["touch_escalation"] = figure.get("touch_escalation", {})
            figure["touch_escalation"].update(req.touch_escalation)
        else:
            figure["touch_escalation"] = req.touch_escalation

    figure["updated_at"] = _now_iso()
    return save_figure(figure_id, figure, user_id=user_id)


@router.delete("/{figure_id}")
def delete_figure_endpoint(figure_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a figure."""
    user_id = current_user_id(current_user)
    if not get_figure(figure_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="找不到这个灵偶")
    now = _now_iso()
    for base in list_bases_for_owner(user_id):
        if base.get("active_figure_id") == figure_id:
            base["active_figure_id"] = None
            base["status"] = "bound"
            base["updated_at"] = now
            save_base(str(base["base_id"]), base, owner_user_id=user_id)
    deleted = delete_figure(figure_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")
    return {"success": True}


class SaveCharacterRequest(_StrictModel):
    character_profile: dict


@router.put("/{figure_id}/character")
def save_figure_character(figure_id: str, req: SaveCharacterRequest, current_user: dict = Depends(get_current_user)):
    """Save character profile to figure's soul_profile.character_profile."""
    user_id = current_user_id(current_user)
    figure = get_figure(figure_id, user_id=user_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")

    soul_profile = figure.get("soul_profile", {})
    character_profile = dict(req.character_profile)
    soul_profile["character_profile"] = character_profile
    _synchronize_persona_address(
        soul_profile,
        preferred=character_profile.get("address_user_as"),
    )
    figure["soul_profile"] = soul_profile
    figure["updated_at"] = _now_iso()

    save_figure(figure_id, figure, user_id=user_id)

    return {
        "figure_id": figure_id,
        "character_profile": soul_profile["character_profile"],
        "saved": True,
    }


# ============== Debug Endpoints (Phase B) ==============

class SimulateAbsenceRequest(_StrictModel):
    hours: float = Field(..., description="模拟离开的小时数")


@router.post("/{figure_id}/simulate-absence")
def simulate_absence(figure_id: str, req: SimulateAbsenceRequest, current_user: dict = Depends(get_current_user)):
    """
    Phase B: 调试接口 - 模拟离开。
    
    把该 figure 的 last_interaction_at 回拨 hours 小时，
    用于演示冷落效果。
    
    返回更新后的 figure 和 life_status。
    """
    require_dev_tools()
    user_id = current_user_id(current_user)
    figure = get_figure(figure_id, user_id=user_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")
    
    # 回拨 last_interaction_at
    now = datetime.utcnow()
    simulated_last = now - timedelta(hours=req.hours)
    simulated_last_iso = simulated_last.isoformat()
    
    memory = figure.get("memory", {})
    memory["last_interaction_at"] = simulated_last_iso
    figure["memory"] = memory
    figure["updated_at"] = _now_iso()
    
    # 保存
    save_figure(figure_id, figure, user_id=user_id)
    
    # 计算衰减后的情绪和状态
    decayed_emotion, elapsed_hours = apply_time_decay(figure)
    tier = neglect_tier(elapsed_hours)
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    status_desc = get_status_description(elapsed_hours, decayed_emotion, archetype)
    
    # 更新 soul_profile.emotion_state
    soul = figure.get("soul_profile", {})
    soul["emotion_state"] = decayed_emotion
    figure["soul_profile"] = soul
    
    figure["life_status"] = {
        "elapsed_hours": elapsed_hours,
        "neglect_tier": tier,
        "status_description": status_desc,
        "simulated": True,
    }
    
    return figure


# ============== Debug Endpoints (Phase C: Relationship) ==============

class BoostRelationshipRequest(_StrictModel):
    points: Optional[int] = Field(None, description="直接设置的点数")
    level: Optional[str] = Field(None, description="直接设置的等级（陌生/熟悉/依赖/羁绊）")
    streak_days: Optional[int] = Field(None, description="直接设置的连续陪伴天数")


@router.post("/{figure_id}/boost-relationship")
def boost_relationship_endpoint(figure_id: str, req: BoostRelationshipRequest, current_user: dict = Depends(get_current_user)):
    """
    Phase C: 调试接口 - 快进关系。
    
    - points: 直接设置关系点数
    - level: 直接设置关系等级（会回填 first_met_at 以满足天数门槛）
    - streak_days: 直接设置连续陪伴天数
    
    返回更新后的 figure。
    """
    require_dev_tools()
    user_id = current_user_id(current_user)
    figure = get_figure(figure_id, user_id=user_id)
    if not figure:
        raise HTTPException(status_code=404, detail="找不到这个灵偶")
    
    # Phase C: 调用 boost_relationship
    figure = boost_relationship(figure, points=req.points, level=req.level)
    
    # Phase C Streak: 设置 streak_days
    if req.streak_days is not None:
        figure = set_streak(figure, req.streak_days)
    
    figure["updated_at"] = _now_iso()
    
    # 保存
    save_figure(figure_id, figure, user_id=user_id)
    
    return figure
