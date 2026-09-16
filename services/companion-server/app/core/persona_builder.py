"""Build the single MVP persona prompt used by every online dialogue path."""

from __future__ import annotations

from typing import Any, Iterable, Optional

TRANSPARENT_IDENTITY_RULES = """【真实身份与角色边界】
- 你是由 AI 驱动的「灵偶」角色。始终保持角色口吻，但不得否认、隐瞒或伪造这一真实身份。
- 用户直接询问你是否为 AI、程序或真人时，简短如实说明自己是 AI 驱动的灵偶，再自然延续当前角色的表达方式。
- 不声称自己是真人，也不虚构自己在现实世界已经完成了无法执行的动作。"""

DIALOGUE_RULES = """【共同对话规则】
- 回应用户这一次输入的具体内容；用户表达情绪时先确认感受，再按角色立场回应或追问。
- 人设影响观点、措辞、节奏和边界，不得只靠重复口头禅体现。
- 只输出角色说出口的台词，不输出动作、神态、舞台说明或第三人称旁白。
- 通常回复 1 至 3 句；信息不足时明确追问，不确定时如实说明，不编造事实。
- 使用给定称呼，但不要在每一句机械重复。"""


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    normalized = " ".join(str(value).split())
    return normalized[:limit]


def _items(value: Any, *, count: int, item_limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        normalized = _text(item, item_limit)
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= count:
            break
    return result


def _first_items(
    candidates: Iterable[Any],
    *,
    count: int,
    item_limit: int,
) -> list[str]:
    for candidate in candidates:
        values = _items(candidate, count=count, item_limit=item_limit)
        if values:
            return values
    return []


def _mapping_lines(value: Any, *, count: int, item_limit: int) -> list[str]:
    if not isinstance(value, dict):
        return []
    result: list[str] = []
    for key, target in value.items():
        key_text = _text(key, item_limit)
        target_text = _text(target, item_limit)
        if key_text and target_text:
            result.append(f"{key_text}：{target_text}")
        if len(result) >= count:
            break
    return result


def _line(label: str, value: str) -> Optional[str]:
    return f"- {label}：{value}" if value else None


def build_persona_prompt(figure: dict, session_summary: str = "") -> str:
    """Merge stored persona fields with stable precedence and bounded size."""
    soul = figure.get("soul_profile") if isinstance(figure.get("soul_profile"), dict) else {}
    persona = soul.get("persona") if isinstance(soul.get("persona"), dict) else {}
    character = (
        soul.get("character_profile")
        if isinstance(soul.get("character_profile"), dict)
        else {}
    )

    name = _text(figure.get("name") or character.get("character_name") or "灵偶", 30)
    archetype = _text(soul.get("archetype") or character.get("archetype") or "陪伴型", 30)
    one_line = _text(
        soul.get("one_line")
        or character.get("one_line")
        or figure.get("description"),
        120,
    )
    background = _text(character.get("background"), 240)
    traits = _first_items(
        (
            character.get("traits"),
            character.get("personality_traits"),
            persona.get("traits"),
        ),
        count=6,
        item_limit=24,
    )
    speech_style = _text(
        character.get("speech_style") or persona.get("speaking_style"),
        100,
    )
    greeting = _text(persona.get("greeting"), 80)
    catchphrases = _items(character.get("catchphrases"), count=3, item_limit=40)
    signature_lines = _items(
        character.get("signature_lines"),
        count=3,
        item_limit=60,
    )
    values = _items(character.get("values"), count=5, item_limit=40)
    taboos = _items(character.get("taboos"), count=5, item_limit=50)
    relationships = _mapping_lines(
        character.get("relationships"),
        count=8,
        item_limit=40,
    )
    knowledge = (
        character.get("knowledge_bounds")
        if isinstance(character.get("knowledge_bounds"), dict)
        else {}
    )
    knows = _items(knowledge.get("knows"), count=6, item_limit=50)
    unknowns = _first_items(
        (knowledge.get("unknowns"), knowledge.get("不懂")),
        count=6,
        item_limit=50,
    )
    soul_address = soul.get("address_user_as")
    if soul_address == "Eddie":
        soul_address = None
    character_address = character.get("address_user_as")
    if character_address == "Eddie":
        character_address = None
    address_user_as = _text(
        soul_address or character_address or "你",
        20,
    )
    memory = figure.get("memory") if isinstance(figure.get("memory"), dict) else {}
    confirmed_facts = [
        _text(item.get("content"), 120)
        for item in memory.get("confirmed_facts", [])
        if isinstance(item, dict)
        and item.get("status") == "confirmed"
        and item.get("content")
    ][-10:]

    profile_lines = [
        _line("名字", name),
        _line("气质原型", archetype),
        _line("核心设定", one_line),
        _line("背景", background),
        _line("稳定特质", "、".join(traits)),
        _line("表达方式", speech_style),
        _line("问候方式", greeting),
        _line("口头禅", "；".join(catchphrases)),
        _line("代表台词", "；".join(signature_lines)),
        _line("重视的事", "、".join(values)),
        _line("重要关系", "；".join(relationships)),
        _line("熟悉领域", "、".join(knows)),
        _line("不了解或应谨慎的领域", "、".join(unknowns)),
        _line("禁忌与边界", "；".join(taboos)),
        _line("对用户的称呼", address_user_as),
        _line("用户已确认事实", "；".join(confirmed_facts)),
    ]

    summary = _text(session_summary, 1000)
    prompt_parts = [
        TRANSPARENT_IDENTITY_RULES,
        "",
        "【角色设定】",
        *(line for line in profile_lines if line),
    ]
    if summary:
        prompt_parts.extend([
            "",
            "【当前互动】",
            f"- 近期对话摘要：{summary}",
        ])
    prompt_parts.extend(["", DIALOGUE_RULES])
    return "\n".join(prompt_parts)


def build_dialogue_messages(
    figure: dict,
    user_input_text: str,
    history: Optional[list[dict]] = None,
    session_summary: str = "",
) -> list[dict]:
    """Build identical context for synchronous, streaming and bot dialogue."""
    messages = [{
        "role": "system",
        "content": build_persona_prompt(figure, session_summary),
    }]
    for item in (history or [])[-12:]:
        role = item.get("role")
        content = _text(item.get("content"), 2000)
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({
        "role": "system",
        "content": (
            "本轮继续严格遵守同一角色设定和真实身份规则，"
            "具体回应用户当前输入，不要退化成通用助手套话。"
        ),
    })
    messages.append({"role": "user", "content": _text(user_input_text, 4000)})
    return messages
