# services/companion-server/app/core/relationship_engine.py
"""
Relationship Engine: 羁绊层（关系生长 + 解锁专属 + 记忆胶囊 + 只认你）

Phase C: 向后兼容，老 figure 无相关字段不报错

核心概念：
- relationship_points: 关系点数（对话+3，触摸+1）
- relationship_level: 关系等级（陌生/熟悉/依赖/羁绊）
- memory_capsule: 记忆胶囊数组（first_meet/milestone/user_said）
"""

from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List


# ============== Relationship Levels ==============

RELATIONSHIP_LEVELS = ["陌生", "熟悉", "依赖", "羁绊"]

# 等级门槛（points, min_days）
LEVEL_THRESHOLDS = {
    "陌生": (0, 0),
    "熟悉": (21, 1),
    "依赖": (61, 3),
    "羁绊": (151, 7),
}

# 等级解锁配置
LEVEL_UNLOCKS = {
    "陌生": {
        "address_style": "客气称呼",
        "tone": "保持礼貌距离",
        "unlocked": {
            "intimate_address": False,
            "personal_topics": False,
            "remembered_things": False,
        }
    },
    "熟悉": {
        "address_style": "正常称呼",
        "tone": "轻松自然",
        "unlocked": {
            "intimate_address": False,
            "personal_topics": True,
            "remembered_things": False,
        }
    },
    "依赖": {
        "address_style": "亲密称呼",
        "tone": "关心体贴",
        "unlocked": {
            "intimate_address": True,
            "personal_topics": True,
            "remembered_things": True,
        }
    },
    "羁绊": {
        "address_style": "专属昵称/最亲密",
        "tone": "非常亲密黏人",
        "unlocked": {
            "intimate_address": True,
            "personal_topics": True,
            "remembered_things": True,
        }
    },
}


def get_days_known(first_met_at: str) -> int:
    """根据 first_met_at 计算认识天数。"""
    try:
        first_dt = datetime.fromisoformat(first_met_at.replace("Z", "+00:00").replace("+00:00", ""))
        now = datetime.utcnow()
        delta = now - first_dt
        return max(0, delta.days)
    except Exception:
        return 0


def compute_level(points: int, days_known: int) -> str:
    """
    根据关系点数和认识天数计算关系等级。
    
    规则：
    - 羁绊：points >= 151 且 days >= 7
    - 依赖：points >= 61 且 days >= 3
    - 熟悉：points >= 21 且 days >= 1
    - 陌生：默认
    """
    if points >= 151 and days_known >= 7:
        return "羁绊"
    elif points >= 61 and days_known >= 3:
        return "依赖"
    elif points >= 21 and days_known >= 1:
        return "熟悉"
    else:
        return "陌生"


def level_unlocks(level: str) -> Dict[str, Any]:
    """返回指定等级的配置。"""
    return LEVEL_UNLOCKS.get(level, LEVEL_UNLOCKS["陌生"])


def add_points(figure: dict, event_type: str = "touch") -> Tuple[int, str, bool]:
    """
    增加关系点数。
    
    Args:
        figure: figure 对象
        event_type: "touch" 或 "dialogue"
    
    Returns:
        (old_points, new_level, level_up)
    """
    memory = figure.get("memory", {})
    
    # 获取当前值
    old_points = memory.get("relationship_points", 0)
    old_level = memory.get("relationship_level", "陌生")
    
    # 计算新增点数
    if event_type == "dialogue":
        add = 3
    else:  # touch
        add = 1
    
    new_points = old_points + add
    
    # 计算认识天数
    first_met_at = memory.get("first_met_at", figure.get("created_at", datetime.utcnow().isoformat()))
    days_known = get_days_known(first_met_at)
    
    # 计算新等级
    new_level = compute_level(new_points, days_known)
    
    # 检查是否升级
    old_idx = RELATIONSHIP_LEVELS.index(old_level) if old_level in RELATIONSHIP_LEVELS else 0
    new_idx = RELATIONSHIP_LEVELS.index(new_level) if new_level in RELATIONSHIP_LEVELS else 0
    level_up = new_idx > old_idx
    
    # 更新 memory
    memory["relationship_points"] = new_points
    memory["relationship_level"] = new_level
    
    # 如果升级，添加 milestone 胶囊
    if level_up:
        capsule = {
            "type": "milestone",
            "content": f"关系升级到{new_level}",
            "created_at": datetime.utcnow().isoformat(),
        }
        add_memory_capsule(memory, capsule)
    
    figure["memory"] = memory
    return old_points, new_level, level_up


def check_milestone_triggers(figure: dict) -> Optional[Dict[str, Any]]:
    """
    检查是否触发自动里程碑。
    
    interaction_count 到达 10/50/100 时触发。
    """
    memory = figure.get("memory", {})
    interaction_count = memory.get("interaction_count", 0)
    existing_milestones = memory.get("memory_capsule", [])
    
    milestone_counts = {}
    for cap in existing_milestones:
        if cap.get("type") == "milestone" and "interaction_count" in cap.get("content", ""):
            # 解析 milestone 内容中的数字
            import re
            match = re.search(r"(\d+)", cap.get("content", ""))
            if match:
                milestone_counts[int(match.group(1))] = True
    
    trigger = None
    for threshold in [10, 50, 100]:
        if interaction_count >= threshold and threshold not in milestone_counts:
            capsule = {
                "type": "milestone",
                "content": f"交互次数达到{threshold}次",
                "created_at": datetime.utcnow().isoformat(),
            }
            add_memory_capsule(memory, capsule)
            trigger = capsule
            break
    
    if trigger:
        figure["memory"] = memory
    return trigger


def init_memory_capsule(memory: dict) -> dict:
    """
    初始化记忆胶囊。
    
    在 figure 创建时调用，添加 first_meet 胶囊。
    
    Returns:
        更新后的 memory dict
    """
    # 如果已有胶囊，不重复初始化
    if memory.get("memory_capsule"):
        return memory
    
    memory["memory_capsule"] = memory.get("memory_capsule", [])
    memory["relationship_points"] = 0
    memory["relationship_level"] = "陌生"
    memory["streak_days"] = 0
    memory["first_met_at"] = memory.get("first_met_at", datetime.utcnow().isoformat())
    
    figure_name = memory.get("figure_name", "灵偶")
    first_meet = {
        "type": "first_meet",
        "content": f"第一次见到{figure_name}",
        "created_at": memory.get("first_met_at", datetime.utcnow().isoformat()),
    }
    memory["memory_capsule"] = [first_meet]
    
    return memory


def add_memory_capsule(memory: dict, capsule: Dict[str, Any]) -> None:
    """
    添加记忆胶囊。
    
    - 避免重复 content
    - 限制 user_said 类型最多保留 10 条
    - 限制总胶囊数量最多 50 条
    """
    capsules = memory.get("memory_capsule", [])
    
    # 避免完全重复
    for existing in capsules:
        if existing.get("content") == capsule.get("content"):
            return
    
    capsules.append(capsule)
    
    # 裁剪：user_said 最多 10 条
    user_said_capsules = [c for c in capsules if c.get("type") == "user_said"]
    other_capsules = [c for c in capsules if c.get("type") != "user_said"]
    if len(user_said_capsules) > 10:
        user_said_capsules = user_said_capsules[-10:]
    
    # 总数最多 50 条
    capsules = other_capsules + user_said_capsules
    if len(capsules) > 50:
        capsules = capsules[-50:]
    
    memory["memory_capsule"] = capsules


def get_recent_capsules(memory: dict, limit: int = 5) -> List[Dict[str, Any]]:
    """获取最近的记忆胶囊。"""
    capsules = memory.get("memory_capsule", [])
    return capsules[-limit:] if capsules else []


def build_relationship_block(figure: dict) -> str:
    """
    构建关系块（精简版），用于注入 online_brain system prompt。
    
    Phase C v2: 极度精简，一行说完。
    """
    memory = figure.get("memory", {})
    
    # 获取关系信息
    level = memory.get("relationship_level", "陌生")
    points = memory.get("relationship_points", 0)
    days_known = get_days_known(memory.get("first_met_at", figure.get("created_at", "")))
    
    # 获取等级解锁配置
    unlocks = level_unlocks(level)
    tone = unlocks.get("tone", "轻松自然")
    
    # 获取称呼用户的方式
    soul = figure.get("soul_profile", {})
    base_address = soul.get("address_user_as", "主人")
    
    # 根据等级调整称呼
    if level == "羁绊":
        user_address = f"用专属亲密昵称（如：小可爱、亲爱的）"
    elif level == "依赖":
        user_address = f"用亲密称呼「{base_address}」"
    elif level == "熟悉":
        user_address = f"正常称呼「{base_address}」"
    else:
        user_address = f"客气礼貌地称呼「{base_address}」"
    
    return f"""【关系】{level} | {points}点 | {days_known}天 | {tone} | {user_address}"""


def boost_relationship(figure: dict, points: Optional[int] = None, level: Optional[str] = None) -> dict:
    """
    调试接口：直接加分或直接设等级。
    
    Returns:
        更新后的 figure
    """
    memory = figure.get("memory", {})
    
    if level:
        # 直接设等级
        if level not in RELATIONSHIP_LEVELS:
            level = "陌生"
        
        memory["relationship_level"] = level
        
        # 根据等级反推需要的点数
        target_points = {
            "陌生": 0,
            "熟悉": 25,
            "依赖": 65,
            "羁绊": 155,
        }
        memory["relationship_points"] = target_points.get(level, 0)
        
        # 为了满足天数门槛，回拨 first_met_at
        import datetime as dt
        days_needed = LEVEL_THRESHOLDS.get(level, (0, 0))[1]
        if days_needed > 0:
            new_first_met = dt.datetime.utcnow() - dt.timedelta(days=days_needed + 1)
            memory["first_met_at"] = new_first_met.isoformat()
        
        # 添加 milestone
        capsule = {
            "type": "milestone",
            "content": f"关系跳级到{level}",
            "created_at": datetime.utcnow().isoformat(),
        }
        add_memory_capsule(memory, capsule)
        
    elif points is not None:
        # 加分
        old_level = memory.get("relationship_level", "陌生")
        memory["relationship_points"] = points
        days_known = get_days_known(memory.get("first_met_at", figure.get("created_at", "")))
        new_level = compute_level(points, days_known)
        memory["relationship_level"] = new_level
        
        # 检查是否升级
        if RELATIONSHIP_LEVELS.index(new_level) > RELATIONSHIP_LEVELS.index(old_level):
            capsule = {
                "type": "milestone",
                "content": f"关系升级到{new_level}",
                "created_at": datetime.utcnow().isoformat(),
            }
            add_memory_capsule(memory, capsule)
    
    figure["memory"] = memory
    return figure


# ============== Streak (Phase C Companion) ==============

def get_today_date() -> str:
    """获取今天的日期字符串 YYYY-MM-DD。"""
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_yesterday_date() -> str:
    """获取昨天的日期字符串 YYYY-MM-DD。"""
    from datetime import timedelta
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")


def update_streak(figure: dict) -> Tuple[int, bool]:
    """
    更新连续陪伴天数 streak_days。
    
    任意互动时调用：
    - 今天 = last_active_date → 不变
    - 今天 = 昨天 → streak_days + 1
    - 断档（>1天或为空）→ 重置为 1
    - 更新 last_active_date = 今天
    
    Returns:
        (streak_days, is_new_streak)
    """
    memory = figure.get("memory", {})
    today = get_today_date()
    yesterday = get_yesterday_date()
    
    last_active = memory.get("last_active_date", "")
    streak_days = memory.get("streak_days", 0)
    
    is_new_streak = False
    
    if last_active == today:
        # 今天已经互动过，不变
        pass
    elif last_active == yesterday:
        # 昨天互动过，streak + 1
        streak_days += 1
        memory["streak_days"] = streak_days
        memory["last_active_date"] = today
        is_new_streak = streak_days > 1  # 只有不是第一天时才算是新 streak
    else:
        # 断档或首次，重置为 1
        streak_days = 1
        memory["streak_days"] = streak_days
        memory["last_active_date"] = today
    
    figure["memory"] = memory
    return streak_days, is_new_streak


def set_streak(figure: dict, days: int) -> dict:
    """
    调试接口：直接设置 streak_days。
    
    Returns:
        更新后的 figure
    """
    memory = figure.get("memory", {})
    memory["streak_days"] = max(0, days)
    memory["last_active_date"] = get_today_date()
    figure["memory"] = memory
    return figure


def build_streak_block(figure: dict) -> str:
    """
    构建 streak 块，用于注入 system prompt。
    """
    memory = figure.get("memory", {})
    streak_days = memory.get("streak_days", 0)
    
    if streak_days == 0:
        return ""
    
    if streak_days == 1:
        streak_desc = "今天刚刚开始连续陪伴"
    elif streak_days < 7:
        streak_desc = f"已经连续陪伴 {streak_days} 天了"
    elif streak_days < 30:
        streak_desc = f"已经连续陪伴 {streak_days} 天，继续加油"
    else:
        streak_desc = f"已经连续陪伴 {streak_days} 天，真爱无疑"
    
    return f"""
【连续陪伴】
{streak_desc}
连续陪伴 {streak_days} 天的关系应该更加稳定和信任。"""