# services/companion-server/app/core/life_engine.py
"""
Life Engine: 有脉搏的养成（重逢触发型）
- 情绪随时间衰减（懒计算，无后台定时任务）
- 冷落分级（neglect_tier）
- 重逢反应台词池

Phase B: 向后兼容，老 figure 无 last_interaction_at 不报错
"""

from datetime import datetime, timedelta
from typing import Tuple, Dict, Any, Optional


# ============== Neglect Tiers ==============

def neglect_tier(elapsed_hours: float) -> str:
    """
    根据空闲时长返回冷落等级。
    - just_seen: <1小时，刚见过
    - short: 1-12小时，短暂离开
    - half: 12-48小时，半天到两天
    - missed: 48-168小时（2-7天），想念
    - abandoned: >168小时（>7天），以为被抛弃
    """
    if elapsed_hours < 1:
        return "just_seen"
    elif elapsed_hours < 12:
        return "short"
    elif elapsed_hours < 48:
        return "half"
    elif elapsed_hours < 168:
        return "missed"
    else:
        return "abandoned"


# ============== Time Decay ==============

def apply_time_decay(figure: dict) -> Tuple[Dict[str, int], float]:
    """
    计算情绪随时间衰减（懒计算，不写入）。
    
    返回: (updated_emotion, elapsed_hours)
    
    衰减规则：
    - lonely += h*3（上限100）
    - happy -= h*2（下限0）
    - attached -= h*1（下限0）
    - 夜间(23-6点): sleepy = min(100, 40+h)
    - 白天: sleepy 缓降
    
    向后兼容：老 figure 无 last_interaction_at 视为刚创建，不衰减
    """
    now = datetime.utcnow()
    
    # 获取上次交互时间（向后兼容）
    memory = figure.get("memory", {})
    last_interaction = memory.get("last_interaction_at")
    
    if not last_interaction:
        # 老 figure 无该字段，视为刚创建，不衰减
        elapsed_hours = 0.0
    else:
        try:
            last_dt = datetime.fromisoformat(last_interaction.replace("Z", "+00:00").replace("+00:00", ""))
            elapsed_seconds = (now - last_dt).total_seconds()
            elapsed_hours = elapsed_seconds / 3600
        except Exception:
            elapsed_hours = 0.0
    
    # 获取当前情绪（向后兼容）
    soul = figure.get("soul_profile", {})
    emotion = soul.get("emotion_state", {})
    
    # 默认情绪值
    happy = emotion.get("happy", 50)
    lonely = emotion.get("lonely", 0)
    attached = emotion.get("attached", 0)
    annoyed = emotion.get("annoyed", 0)
    attention = emotion.get("attention", 0)
    sleepy = emotion.get("sleepy", 0)
    
    # 应用衰减（只对 elapsed_hours > 0 的情况）
    h = elapsed_hours
    if h > 0:
        # lonely 上升
        lonely = min(100, lonely + int(h * 3))
        
        # happy 下降
        happy = max(0, happy - int(h * 2))
        
        # attached 下降
        attached = max(0, attached - int(h * 1))
        
        # 夜间/白天 sleepy
        current_hour = now.hour
        if current_hour >= 23 or current_hour < 6:
            # 夜间：sleepy 提升
            sleepy = min(100, max(sleepy, int(40 + h)))
        else:
            # 白天：sleepy 缓降
            sleepy = max(0, sleepy - int(h * 0.5))
    
    # Clamp 所有值到 0-100
    updated_emotion = {
        "happy": max(0, min(100, happy)),
        "lonely": max(0, min(100, lonely)),
        "attached": max(0, min(100, attached)),
        "annoyed": max(0, min(100, annoyed)),
        "attention": max(0, min(100, attention)),
        "sleepy": max(0, min(100, sleepy)),
    }
    
    return updated_emotion, elapsed_hours


# ============== Reunion Lines ==============

# 重逢台词池（按气质和冷落等级）
REUNION_LINES = {
    "御姐照顾型": {
        "just_seen": ["回来了？", "嗯，刚见过你。"],
        "short": ["回来了，饭热好了。", "今天辛苦了。"],
        "half": ["两天没见你了，还好吗？", "你终于回来了。"],
        "missed": ["这几天我一直惦记着你。", "你终于回来了，我好想你。"],
        "abandoned": ["你终于回来了……我还以为你不要我了。", "我以为再也见不到你了……"],
    },
    "傲娇吐槽型": {
        "just_seen": ["哼，刚走又回来？", "切，又来了。"],
        "short": ["哼，终于回来了。", "谁稀罕你来。"],
        "half": ["两天没见，想我了吗？哼。", "你终于出现了啊。"],
        "missed": ["这几天……哼，我才没有想你呢！", "你终于回来了，我……算了。"],
        "abandoned": ["你……我还以为你不要我了……哼！", "我以为被抛弃了……笨蛋！"],
    },
    "软萌治愈型": {
        "just_seen": ["嘿嘿，又见面啦~", "呜呜，刚见过~"],
        "short": ["呜呜，你回来啦~抱抱！", "嘿嘿，见到你真开心~"],
        "half": ["呜呜，两天没见你了……", "你终于回来了，我好想你~"],
        "missed": ["呜呜呜……这几天好想你……", "你终于回来了！我好想你~抱抱！"],
        "abandoned": ["呜呜呜……我以为你不要我了……", "你终于回来了……我好怕再也见不到你……"],
    },
    "元气伙伴型": {
        "just_seen": ["耶！又见面啦！", "冲！刚见过！"],
        "short": ["耶！回来了！", "冲！今天也要加油！"],
        "half": ["两天没见，冲！", "终于回来了！"],
        "missed": ["这几天好想你！冲！", "终于回来了！耶！"],
        "abandoned": ["我还以为再也见不到你了……冲！", "你终于回来了……我好怕……"],
    },
    "冷淡守护型": {
        "just_seen": ["……嗯。", "……刚见过。"],
        "short": ["……来了。", "……嗯。"],
        "half": ["……两天。", "……你回来了。"],
        "missed": ["……这几天，一直在等你。", "……你终于回来了。"],
        "abandoned": ["……我以为被遗弃了。", "……你终于回来了……我以为……"],
    },
    "桀骜战神型": {
        "just_seen": ["哼，刚走又回来？", "俺老孙刚见过你。"],
        "short": ["哼，终于回来了。", "俺老孙等你半天了。"],
        "half": ["两天没见，想打架吗？", "终于回来了，俺老孙等你。"],
        "missed": ["这几天俺老孙一直惦记着你。", "终于回来了，俺老孙想你。"],
        "abandoned": ["俺老孙以为你不要俺了……", "你终于回来了……俺老孙好怕……"],
    },
    "搞怪捣蛋型": {
        "just_seen": ["嘿嘿，又见面啦！", "当当！刚见过！"],
        "short": ["当当！回来了！", "嘿嘿，见到你真开心！"],
        "half": ["两天没见，猜猜我是谁？", "嘿嘿，终于回来了！"],
        "missed": ["这几天好想你~嘿嘿！", "当当！终于回来了！我好想你！"],
        "abandoned": ["嘿嘿……我还以为你不要我了……", "当当……我以为再也见不到你了……"],
    },
    "憨憨吃货型": {
        "just_seen": ["嘿嘿，刚见过！", "嗯？刚见过？"],
        "short": ["嘿嘿，回来了！有吃的吗？", "呜呜，终于回来了！"],
        "half": ["两天没见……肚子饿了……", "嘿嘿，终于回来了！"],
        "missed": ["这几天好想你……呜呜……", "终于回来了！我好想你！"],
        "abandoned": ["呜呜……我以为你不要我了……", "嘿嘿……我以为再也见不到你了……"],
    },
    "机械副官型": {
        "just_seen": ["检测到重逢。", "系统：刚见过。"],
        "short": ["检测到重逢。系统正常。", "系统：回来了。"],
        "half": ["系统：两天未检测到用户。", "检测到重逢。系统待机中。"],
        "missed": ["系统：长时间未检测到用户。想念模式激活。", "检测到重逢。系统：想念。"],
        "abandoned": ["系统：长时间未检测到用户。遗弃警告。", "检测到重逢。系统：以为被遗弃。"],
    },
    "萌宠陪伴型": {
        "just_seen": ["汪！刚见过！", "呜~刚见过~"],
        "short": ["汪汪！回来了！", "呜~见到你真开心~"],
        "half": ["呜~两天没见你了……", "汪汪！终于回来了！"],
        "missed": ["呜呜……这几天好想你……", "汪汪汪！终于回来了！我好想你！"],
        "abandoned": ["呜呜呜……我以为你不要我了……", "汪……我以为再也见不到你了……"],
    },
    "潮玩幸运型": {
        "just_seen": ["嘿嘿，刚见过！", "好运~刚见过~"],
        "short": ["嘿嘿，回来了！好运来~", "好运来~见到你真开心！"],
        "half": ["两天没见，好运来~", "嘿嘿，终于回来了！"],
        "missed": ["这几天好想你~好运来~", "好运来~终于回来了！我好想你！"],
        "abandoned": ["嘿嘿……我还以为你不要我了……", "好运……我以为再也见不到你了……"],
    },
}


def get_reunion_line(archetype: str, tier: str) -> str:
    """
    根据气质和冷落等级获取重逢台词。
    默认回退到"软萌治愈型"。
    """
    import random
    
    pool = REUNION_LINES.get(archetype, REUNION_LINES["软萌治愈型"])
    lines = pool.get(tier, pool["short"])
    return random.choice(lines)


# ============== Reunion Emotion Boost ==============

def apply_reunion_boost(emotion: Dict[str, int], tier: str) -> Dict[str, int]:
    """
    重逢后情绪修复。
    
    基础：happy+10, lonely-8
    按 tier 额外：
    - just_seen: 无额外
    - short: lonely-5
    - half: lonely-15, happy+5
    - missed: lonely归0~10, happy+15, attached+5
    - abandoned: lonely归0, happy+20, attached+10
    """
    happy = emotion.get("happy", 50)
    lonely = emotion.get("lonely", 0)
    attached = emotion.get("attached", 0)
    
    # 基础修复
    happy = min(100, happy + 10)
    lonely = max(0, lonely - 8)
    
    # 按 tier 额外修复
    if tier == "short":
        lonely = max(0, lonely - 5)
    elif tier == "half":
        lonely = max(0, lonely - 15)
        happy = min(100, happy + 5)
    elif tier == "missed":
        lonely = min(10, max(0, lonely - 30))  # 归到 0~10
        happy = min(100, happy + 15)
        attached = min(100, attached + 5)
    elif tier == "abandoned":
        lonely = 0  # 归零
        happy = min(100, happy + 20)
        attached = min(100, attached + 10)
    
    return {
        "happy": happy,
        "lonely": lonely,
        "attached": attached,
        "annoyed": emotion.get("annoyed", 0),
        "attention": emotion.get("attention", 0),
        "sleepy": emotion.get("sleepy", 0),
    }


# ============== Status Description ==============

def get_status_description(elapsed_hours: float, emotion: Dict[str, int], archetype: str) -> str:
    """
    生成一句状态提示，用于注入 online_brain system prompt。
    例："你已经3天没被理睬了，TA有点失落/想念"
    """
    tier = neglect_tier(elapsed_hours)
    lonely = emotion.get("lonely", 0)
    
    if tier == "just_seen":
        return "刚见过用户，情绪正常。"
    elif tier == "short":
        return f"离开{int(elapsed_hours)}小时，情绪平稳。"
    elif tier == "half":
        if lonely > 30:
            return f"离开{int(elapsed_hours)}小时，TA有点失落。"
        return f"离开{int(elapsed_hours)}小时，情绪正常。"
    elif tier == "missed":
        return f"已经{int(elapsed_hours/24)}天没被理睬了，TA有点想念/失落。"
    elif tier == "abandoned":
        return f"已经{int(elapsed_hours/24)}天没被理睬了，TA以为被抛弃了，很失落。"
    
    return ""