# services/companion-server/app/core/response_engine.py
"""
Touch response engine: generates short replies for touch events.
Input: base_id + event_type
1. Resolve active_figure_id from base
2. Load figure's touch_reactions[event_type]
3. Randomly pick one reply (with escalation for repeated touches)
4. Apply emotion delta via emotion_engine
5. Update figure.memory (interaction_count +1, last_interaction_at)
6. Update touch_streak for escalation tracking
7. Return EventResponse

Phase B: figure_placed 重逢反应
- 先 apply_time_decay 计算情绪衰减和 elapsed_hours
- 根据 neglect_tier 选择重逢台词（语气随冷落程度加重）
- 重逢后情绪修复（lonely 大降、happy 提升）

Phase C: 连续陪伴 streak
- 任意互动时调用 update_streak 更新 streak_days

Phase D: 触摸递进反应
- track touch_streak: 同动作且距上次<60秒 → count+1,否则重置为1
- tier = 1(count=1)/2(count=2-3)/3(count≥4)
- 从 touch_escalation 选择对应台词
"""

import random
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from data.store import get_base, get_figure, save_figure

from app.core.emotion_engine import apply_emotion_delta
from app.core.life_engine import (
    apply_time_decay,
    neglect_tier,
    get_reunion_line,
    apply_reunion_boost,
)
from app.core.relationship_engine import update_streak


# LED effect defaults per event type
LED_EFFECTS = {
    "figure_placed": "golden_flash",
    "light_touch":   "soft_glow",
    "heavy_press":   "red_flash",
    "double_tap":    "star_blink",
}

# Touch escalation threshold (seconds)
TOUCH_ESCALATION_WINDOW = 60  # 60秒内同一动作触发递进


def _update_touch_streak(figure: dict, event_type: str) -> int:
    """
    Update touch streak counter for escalation.
    - Same event type and within TOUCH_ESCALATION_WINDOW seconds → count +1
    - Different event type or timeout → reset to 1
    - figure_placed does not participate in escalation
    
    Returns: current streak count
    """
    now = datetime.utcnow()
    touch_streak = figure.get("touch_streak", {})
    
    last_event = touch_streak.get("event")
    last_at = touch_streak.get("last_at")
    current_count = touch_streak.get("count", 0)
    
    # Check if same event and within time window
    if last_event == event_type and last_at:
        try:
            last_time = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            elapsed = (now - last_time).total_seconds()
            if elapsed < TOUCH_ESCALATION_WINDOW:
                current_count += 1
            else:
                current_count = 1
        except Exception:
            current_count = 1
    else:
        current_count = 1
    
    # Update touch_streak
    figure["touch_streak"] = {
        "event": event_type,
        "count": current_count,
        "last_at": now.isoformat(),
    }
    
    return current_count


def _get_touch_tier(count: int) -> int:
    """
    Determine escalation tier based on streak count.
    - tier 1: count == 1
    - tier 2: count == 2-3
    - tier 3: count >= 4
    """
    if count == 1:
        return 1
    elif 2 <= count <= 3:
        return 2
    else:  # count >= 4
        return 3


def _pick_escalation_line(figure: dict, event_type: str, tier: int) -> str:
    """
    Pick a response line based on escalation tier.
    - tier 1: use touch_reactions[event_type]
    - tier 2/3: use touch_escalation[event_type].tierN
    - Falls back to tier 1 if escalation data is missing
    
    Returns: selected response line
    """
    # tier 1: use base touch_reactions
    if tier == 1:
        templates = figure.get("touch_reactions", {}).get(event_type, [])
        if templates:
            return random.choice(templates)
        return "……"
    
    # tier 2/3: use touch_escalation
    escalation = figure.get("touch_escalation", {}).get(event_type, {})
    tier_key = f"tier{tier}"
    tier_lines = escalation.get(tier_key, [])
    
    if tier_lines:
        return random.choice(tier_lines)
    
    # Fallback: use tier 1 if escalation is missing
    templates = figure.get("touch_reactions", {}).get(event_type, [])
    if templates:
        return random.choice(templates)
    
    return "……"


def generate_touch_response(base_id: str, event_type: str) -> Optional[dict]:
    """
    Main entry point for touch event processing.
    Returns an EventResponse dict or None if figure not found.
    
    Phase B: figure_placed 使用重逢反应（情绪衰减 + 重逢台词 + 情绪修复）
    Phase D: 其他触摸事件使用递进反应
    """
    # 1. Get base and resolve active figure
    base = get_base(base_id)
    if not base:
        return None

    figure_id = base.get("active_figure_id")
    if not figure_id:
        return None

    # 2. Load figure
    owner = base.get("bound_user_id")
    figure = get_figure(figure_id, user_id=owner)
    if not figure:
        return None

    # Phase B: figure_placed 重逢反应
    if event_type == "figure_placed":
        return _generate_reunion_response(base_id, figure_id, figure, owner)
    
    # Phase D: 触摸递进反应
    # 3. Update touch streak and get tier
    streak_count = _update_touch_streak(figure, event_type)
    tier = _get_touch_tier(streak_count)
    
    # 4. Pick reply based on tier
    reply = _pick_escalation_line(figure, event_type, tier)

    # 5. Get current emotion state from soul_profile.emotion_state
    current_mood = figure.get("soul_profile", {}).get(
        "emotion_state",
        {
            "happy": 50,
            "lonely": 0,
            "attached": 0,
            "annoyed": 0,
            "attention": 0,
            "sleepy": 0,
            "last_dialogue_at": None,
        },
    )

    # 6. Apply emotion delta
    updated_mood = apply_emotion_delta(current_mood, event_type)

    # 7. Update memory
    now_iso = datetime.utcnow().isoformat()
    memory = figure.get("memory", {})
    memory["figure_id"] = figure_id
    memory["interaction_count"] = memory.get("interaction_count", 0) + 1
    memory["last_interaction_at"] = now_iso
    
    # Phase C: 更新 streak_days
    update_streak(figure)
    
    # Update emotion_state at soul_profile.emotion_state
    soul = figure.get("soul_profile", {})
    soul["emotion_state"] = updated_mood
    soul["updated_at"] = now_iso

    figure["updated_at"] = now_iso

    # 8. Save updated figure
    save_figure(figure_id, figure, user_id=owner)

    # 9. Build response
    voice_id = figure.get("voice_profile", {}).get("voice_id", "")

    return {
        "base_id": base_id,
        "figure_id": figure_id,
        "event": event_type,
        "reply": reply,
        "mood_before": current_mood,
        "mood": updated_mood,
        "voice_profile_id": voice_id,
        "led_effect": LED_EFFECTS.get(event_type),
        "touch_tier": tier,  # Phase D: 递进等级
        "touch_streak": streak_count,  # Phase D: 连续触摸次数
    }


def _generate_reunion_response(base_id: str, figure_id: str, figure: dict, user_id: Optional[str] = None) -> dict:
    """
    Phase B: figure_placed 重逢反应。
    
    1. apply_time_decay 计算情绪衰减和 elapsed_hours
    2. neglect_tier 确定冷落等级
    3. get_reunion_line 选择重逢台词
    4. apply_reunion_boost 情绪修复
    5. 更新 last_interaction_at 并保存
    """
    now_iso = datetime.utcnow().isoformat()
    
    # 1. 计算情绪衰减
    decayed_emotion, elapsed_hours = apply_time_decay(figure)
    tier = neglect_tier(elapsed_hours)
    
    # 2. 获取气质
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    
    # 3. 选择重逢台词
    reply = get_reunion_line(archetype, tier)
    
    # 4. 情绪修复
    reunion_emotion = apply_reunion_boost(decayed_emotion, tier)
    
    # 5. 更新 memory 和 emotion_state
    memory = figure.get("memory", {})
    memory["figure_id"] = figure_id
    memory["interaction_count"] = memory.get("interaction_count", 0) + 1
    memory["last_interaction_at"] = now_iso
    
    # Phase C: 更新 streak_days
    update_streak(figure)
    
    soul = figure.get("soul_profile", {})
    soul["emotion_state"] = reunion_emotion
    soul["updated_at"] = now_iso
    
    figure["updated_at"] = now_iso
    
    # 6. 保存
    save_figure(figure_id, figure, user_id=user_id)
    
    # 7. 构建响应
    voice_id = figure.get("voice_profile", {}).get("voice_id", "")
    
    return {
        "base_id": base_id,
        "figure_id": figure_id,
        "event": "figure_placed",
        "reply": reply,
        "mood_before": decayed_emotion,  # 衰减后的情绪（重逢前）
        "mood": reunion_emotion,  # 重逢修复后的情绪
        "voice_profile_id": voice_id,
        "led_effect": LED_EFFECTS.get("figure_placed"),
        "elapsed_hours": elapsed_hours,  # Phase B: 离开时长
        "neglect_tier": tier,  # Phase B: 冷落等级
    }
