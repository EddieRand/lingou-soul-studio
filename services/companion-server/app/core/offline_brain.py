# services/companion-server/app/core/offline_brain.py
"""
Offline brain: rule-based short replies (≤30 chars).
No real AI - only companionship / comfort / character-driven responses.
When voice pool is precached, prefers pool texts over hardcoded replies.
"""

import random
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


# Keyword → reply templates by sentiment
_COMFORT_KEYWORDS = ["累", "难过", "伤心", "哭", "困", "不爽", "烦", "累死了", "好累"]
_GREETING_KEYWORDS = ["你好", "在吗", "在不在", "嗨", "哈喽", "嘿", "早上好", "晚上好"]
_CUTE_KEYWORDS = ["可爱", "漂亮", "好看", "萌", "喜欢你", "爱"]
_BORED_KEYWORDS = ["无聊", "没事干", "干嘛", "干什么", "干嘛呢"]
_INTEREST_KEYWORDS = ["喜欢", "爱", "想你", "想念"]


# Archetype-specific reply banks (fallback when voice pool not available)
_ARCHETYPE_REPLIES = {
    "傲娇吐槽型": {
        "default": ["哼~", "干嘛啦~", "有什么事快说~", "切~"],
        "greeting": ["哼，来了？", "切，你来啦~", "干嘛~"],
        "comfort": ["哎呀，知道了啦！", "行了行了，别矫情了~", "哼，想开点嘛~"],
        "interest": ["谁、谁喜欢你了！", "才没有！", "哼~"],
    },
    "御姐照顾型": {
        "default": ["乖~", "嗯？怎么了？", "说吧~", "我在听~"],
        "greeting": ["回来了~欢迎~", "来了呀~", "嗯~我在~"],
        "comfort": ["辛苦了~抱抱~", "没事的~我在这里~", "乖，不哭不哭~"],
        "interest": ["乖~姐姐也喜欢你~", "嗯~知道了~"],
    },
    "软萌治愈型": {
        "default": ["嘿嘿~", "嗯嗯~", "呜~什么事~", "抱抱~"],
        "greeting": ["呜呜~你来啦~", "嘿嘿~抱抱~", "呀~你好~"],
        "comfort": ["呜呜~不哭不哭~", "抱抱~会好起来的~", "乖~没事的~"],
        "interest": ["嘿嘿~我也喜欢你~", "呜~真的吗~"],
    },
    "元气伙伴型": {
        "default": ["冲！", "耶！", "好呀好呀！", "走起！"],
        "greeting": ["耶！来了来了！", "冲鸭！", "嗨嗨嗨~"],
        "comfort": ["没事没事！振作起来！", "加油！冲！", "嘿嘿，别灰心！"],
        "interest": ["耶！我也喜欢你！", "真的吗！嘿嘿~"],
    },
    "冷淡守护型": {
        "default": ["……嗯。", "……说。", "……我在。"],
        "greeting": ["……来了。", "……嗯。"],
        "comfort": ["……会好的。", "……没事。"],
        "interest": ["……知道了。"],
    },
    "桀骜战神型": {
        "default": ["哼。", "有话就说。", "别磨蹭。"],
        "greeting": ["哼，来就来。", "切。"],
        "comfort": ["切，这点事算什么。", "振作点。"],
        "interest": ["哼。", "少废话。"],
    },
    "搞怪捣蛋型": {
        "default": ["嘿嘿嘿~", "哈哈！", "猜猜我是谁~"],
        "greeting": ["当当！猜猜我是谁~", "哈哈！来啦来啦~"],
        "comfort": ["哈哈哈！别这样嘛~", "嘿嘿，笑一笑嘛~"],
        "interest": ["嘿嘿嘿~真的吗~"],
    },
    "憨憨吃货型": {
        "default": ["嗯？", "有吃的吗？", "饿~"],
        "greeting": ["有吃的吗！", "肚子饿了~"],
        "comfort": ["呜呜~抱抱~", "乖~吃点东西就好了~"],
        "interest": ["嗯嗯~我也喜欢你~", "嘿嘿~"],
    },
    "机械副官型": {
        "default": ["指令接收。", "系统正常运作。", "等待指示。"],
        "greeting": ["启动完成。", "检测到用户。"],
        "comfort": ["分析中……建议休息。", "情绪数据异常，建议调整。"],
        "interest": ["指令确认。"],
    },
    "萌宠陪伴型": {
        "default": ["汪！", "呜~", "汪汪~"],
        "greeting": ["汪汪！主人！", "呜~你来啦~"],
        "comfort": ["呜呜~抱抱~", "汪！没事的~"],
        "interest": ["汪汪！我也喜欢你！", "呜~真的吗~"],
    },
    "潮玩幸运型": {
        "default": ["好运来~", "嘿嘿~", "今天运气不错！"],
        "greeting": ["好运来~喜洋洋~", "嘿嘿~来了~"],
        "comfort": ["嘿嘿，笑一笑嘛~", "好运马上来！"],
        "interest": ["嘿嘿~真的吗！", "我也喜欢你~嘿嘿~"],
    },
}

_FALLBACK_REPLIES = ["嗯~", "嘿嘿~", "好~", "知道了~", "呜~"]


def _get_archetype_replies(archetype: str, category: str) -> list:
    """Get reply list for archetype + category."""
    banks = _ARCHETYPE_REPLIES.get(archetype, {})
    return banks.get(category, banks.get("default", _FALLBACK_REPLIES))


def _detect_intent(text: str) -> str:
    """Detect intent category from user text."""
    t = text.lower()
    for kw in _INTEREST_KEYWORDS:
        if kw in t:
            return "interest"
    for kw in _CUTE_KEYWORDS:
        if kw in t:
            return "interest"
    for kw in _COMFORT_KEYWORDS:
        if kw in t:
            return "comfort"
    for kw in _GREETING_KEYWORDS:
        if kw in t:
            return "greeting"
    for kw in _BORED_KEYWORDS:
        if kw in t:
            return "bored"
    return "default"


def generate_offline_reply(figure: dict, user_input_text: str) -> str:
    """
    Generate a short offline reply (≤30 chars).
    Input: figure dict (needs archetype, speaking_style, address_user_as, soul_profile)
    If voice pool is precached for the figure, picks from pool texts instead of hardcoded banks.
    """
    figure_id = figure.get("figure_id", "")
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    speaking_style = figure.get("soul_profile", {}).get("persona", {}).get("speaking_style", "cute")
    address_user_as = figure.get("soul_profile", {}).get("address_user_as", "主人")
    intent = _detect_intent(user_input_text)

    # Try voice pool first if precached
    if figure_id and _pool_is_ready_cached(figure_id):
        pool_text = _pick_pool_for_intent(archetype, intent)
        if pool_text:
            # Enforce ≤30 chars
            if len(pool_text) > 30:
                pool_text = pool_text[:29] + "…"
            return pool_text

    # Fallback to hardcoded archetype banks
    reply_pool = _get_archetype_replies(archetype, intent)
    raw_reply = random.choice(reply_pool)

    # Add address_user_as prefix sometimes
    if intent == "comfort" and speaking_style in ("cute", "casual"):
        if random.random() > 0.5:
            prefix = random.choice([
                f"给{address_user_as}一个抱抱~",
                f"乖~{address_user_as}",
                f"不哭不哭~",
            ])
            reply = prefix + raw_reply
        else:
            reply = raw_reply
    else:
        reply = raw_reply

    # Enforce ≤30 chars
    if len(reply) > 30:
        reply = reply[:29] + "…"

    return reply


# --- Voice pool helpers (lazy import to avoid circular deps) ---

_pool_ready_cache: dict = {}


def _pool_is_ready_cached(figure_id: str) -> bool:
    """Check if voice pool is ready (cached)."""
    if figure_id in _pool_ready_cache:
        return _pool_ready_cache[figure_id]
    from app.core.tts_adapter import is_voice_pool_ready
    ready = is_voice_pool_ready(figure_id)
    _pool_ready_cache[figure_id] = ready
    return ready


def _pick_pool_for_intent(archetype: str, intent: str) -> str:
    """Pick a random pool text for archetype + intent category."""
    from app.core.tts_adapter import load_archetype_pool_texts, pick_pool_text
    texts = load_archetype_pool_texts(archetype)
    if not texts:
        return ""
    return random.choice(texts)
