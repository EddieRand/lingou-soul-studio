# services/companion-server/app/core/online_brain.py
"""
Online brain: Doubao Ark (Volcengine Ark) OpenAI-compatible API.
Uses environment variables:
  ARK_API_KEY      - API key
  ARK_ENDPOINT_ID - Chat endpoint ID (model identifier)
  ARK_BASE_URL    - Base URL (default: https://ark.cn-beijing.volces.com/api/v3)

Phase A (角色还魂深化):
  - 所有角色使用同一个 persona builder
  - 保持角色表达，同时如实说明 AI 驱动身份

Phase B (有脉搏的养成):
  - 注入"当前状态"块：距上次互动时长、当前情绪、状态提示
  - 让所有在线回复都带当前情绪底色

Phase C (羁绊层):
  - 注入【关系】块：关系等级、称呼方式、记忆胶囊
  - 按关系等级决定语气亲密度
"""

import os
import httpx
import json
import re
import time
from typing import Optional, List, Dict, Any, Generator

from app.core.persona_builder import build_dialogue_messages, build_persona_prompt


class OnlineBrainError(Exception):
    """Raised when online brain call fails."""
    pass


def _get_config() -> Dict[str, str]:
    return {
        "api_key": os.getenv("ARK_API_KEY", "").strip(),
        "endpoint_id": os.getenv("ARK_ENDPOINT_ID", "").strip(),
        "base_url": os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip(),
        "bot_id": os.getenv("ARK_BOT_ID", "").strip(),
    }


def _get_bot_config() -> Dict[str, str]:
    """获取 Bot 联网配置（联网搜索用）"""
    cfg = _get_config()
    bot_id = cfg.get("bot_id", "").strip()
    if not bot_id:
        return {}
    return {
        "api_key": cfg["api_key"],
        "bot_id": bot_id,
        "base_url": cfg["base_url"],
    }


def _is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["api_key"] and cfg["endpoint_id"])


def _is_bot_configured() -> bool:
    """检查 Bot 联网是否配置"""
    bot_cfg = _get_bot_config()
    return bool(bot_cfg.get("bot_id"))


# ============== Stage Directions Stripper ==============

def _strip_stage_directions(text: str) -> str:
    """去除动作/神态旁白与书名号包裹，只留口语台词。"""
    text = re.sub(r'（[^）]*）', '', text)
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'【[^】]*】', '', text)
    text = text.replace('「', '').replace('」', '').replace('『', '').replace('』', '')
    return text.strip()


def _build_system_prompt(figure: dict, recent_events: List[dict], session_summary: str = "") -> str:
    """Compatibility wrapper around the single persona builder."""
    return build_persona_prompt(figure, session_summary)


# ============== Breaking Detection ==============

# Generic-assistant phrases that lose the configured role. Truthful disclosure
# such as "我是 AI 驱动的灵偶" is intentionally not treated as a failure.
BREAKING_PATTERNS = [
    r"我是\s*(OpenAI|Anthropic|Claude|ChatGPT|文心一言|通义千问|豆包)",
    r"我是由\s*(.*)训练",
    r"我的底层是\s*(.*模型)",
    r"作为一个\s*(语言模型|聊天机器人)",
    r"从技术角度",
    r"我的训练数据",
    r"我可以帮助您",
    r"请问有什么可以帮您",
    r"抱歉，我无法",
    r"对不起，我不能",
    r"我不能满足",
    r"很抱歉，我不能",
    r"这超出我的能力范围",
]


def _detect_breaking_out(reply: str) -> bool:
    """Detect generic assistant boilerplate without suppressing AI disclosure."""
    reply_lower = reply.lower()
    for pattern in BREAKING_PATTERNS:
        if re.search(pattern, reply_lower):
            return True
    return False


# ============== Ark API Call ==============

def _call_doubao(messages: List[dict], timeout: float = 25.0) -> str:
    """Call Doubao Ark API, return assistant reply text."""
    cfg = _get_config()

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": cfg["endpoint_id"],
        "messages": messages,
        "max_tokens": 800,  # 放宽长度，允许完整回复不被截断
        "temperature": 0.9,
        "thinking": {"type": "disabled"},
    }

    url = f"{cfg['base_url']}/chat/completions"

    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise OnlineBrainError(f"Ark API error: {resp.status_code} {resp.text[:200]}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise OnlineBrainError("No choices in Ark response")
        reply = choices[0].get("message", {}).get("content", "").strip()
        return _strip_stage_directions(reply)


# ============== Main Generate Reply ==============

def generate_online_reply(
    figure: dict,
    user_input_text: str,
    history: Optional[List[dict]] = None,
    session_summary: str = "",
) -> str:
    """
    Generate reply via Doubao Ark online brain.

    所有人设字段由统一 builder 注入。
    若回复退化为通用助手套话，重生成一次；真实 AI 身份说明不会触发重试。

    Args:
        session_summary: 会话摘要（长对话压缩后的上下文）
    """
    if not _is_configured():
        raise OnlineBrainError("ARK_API_KEY or ARK_ENDPOINT_ID not set")

    messages = build_dialogue_messages(
        figure,
        user_input_text,
        history,
        session_summary,
    )

    # 第一次生成
    try:
        reply = _call_doubao(messages)
    except Exception as e:
        raise OnlineBrainError(f"Ark call failed: {e}")

    # 通用助手话术检测
    if _detect_breaking_out(reply):
        # 兜底重生成一次
        try:
            reply = _call_doubao(messages)
        except Exception:
            pass

        # 再次检测仍不符合角色表达时，用 signature_lines 兜底
        if _detect_breaking_out(reply):
            cp = figure.get("soul_profile", {}).get("character_profile") or {}
            signature_lines = cp.get("signature_lines") or []
            if signature_lines:
                import random
                reply = random.choice(signature_lines)
            else:
                # 没有 signature_lines，用 archetype 风格的默认回复
                archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
                defaults = {
                    "桀骜战神型": "俺老孙去也！",
                    "软萌治愈型": "嗯...人家不太懂呢~",
                    "傲娇吐槽型": "哈？问这种奇怪的问题...",
                }
                reply = defaults.get(archetype, "这个嘛...人家不太清楚呢~")

    return reply


# ============== Streaming LLM Call ==============

def _call_doubao_streaming(
    messages: List[dict],
    timeout: float = 25.0,
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    Call Doubao Ark API with stream=True, yielding delta chunks as they arrive.
    
    方案A（推荐）: 使用 urllib.request 做 SSE 流式，避免 httpx 的响应缓冲问题。
    urllib 已验证同 prompt 首 token 3.4s（httpx 要 12.8s）。
    """
    import urllib.request
    import urllib.error

    cfg = _get_config()

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        # Bug2 Fix: 禁用压缩，避免缓冲延迟
        "Accept-Encoding": "identity",
    }

    payload = {
        "model": cfg["endpoint_id"],
        "messages": messages,
        "max_tokens": 800,  # 放宽长度，允许完整回复不被截断
        "temperature": 0.9,
        "stream": True,
        "thinking": {"type": "disabled"},
    }

    url = f"{cfg['base_url']}/chat/completions"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        if cancel_event and cancel_event.is_set():
            return
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            add_callback = getattr(cancel_event, "add_callback", None)
            remove_callback = getattr(cancel_event, "remove_callback", None)
            if callable(add_callback):
                add_callback(resp.close)
            try:
                # SSE streaming: each line is "data: {...}" or "[DONE]"
                for line in resp:
                    if cancel_event and cancel_event.is_set():
                        return
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].lstrip()
                    if line == "[DONE]":
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    choices = obj.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
            finally:
                if callable(remove_callback):
                    remove_callback(resp.close)
    except urllib.error.HTTPError as e:
        raise OnlineBrainError(f"Ark HTTP error: {e.code} {e.reason}")
    except Exception as e:
        if cancel_event and cancel_event.is_set():
            return
        raise OnlineBrainError(f"Ark streaming error: {e}")


# ============== Sentence Streaming Generator ==============

# 断句只在句末标点切（去掉逗号、顿号，让 TTS 拿到完整自然句、韵律连贯）
_SENTENCE_ENDINGS = re.compile(r'[。！？…\n]+')
# 兜底：句子过长（>40字）时在最近的逗号处切一次
_SENTENCE_FALLBACK = re.compile(r'[，、]')


def _generate_sentence_stream(
    messages: List[dict],
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    Generator: calls LLM streaming, accumulates text, yields complete sentences.
    
    Yields each complete sentence as it is formed (on sentence-ending punctuation).
    The final sentence (without ending punctuation) is also yielded at the end.
    
    断句规则：
    1. 优先在句末标点（。！？…）切分，让 TTS 拿到完整自然句
    2. 若句子过长（>40字）仍无句末标点，在最近的逗号处兜底切一次
    """
    buffer = ""

    for chunk in _call_doubao_streaming(messages, cancel_event=cancel_event):
        if cancel_event and cancel_event.is_set():
            return
        buffer += chunk

        # 提取所有完整的句子
        while True:
            # 优先找句末标点
            match = _SENTENCE_ENDINGS.search(buffer)
            if match:
                sentence = buffer[:match.end()]
                buffer = buffer[match.end():]
                sentence = _strip_stage_directions(sentence)
                if sentence:
                    yield sentence
                continue
            
            # 兜底：句子过长时在逗号处切
            if len(buffer) > 40:
                fallback_match = _SENTENCE_FALLBACK.search(buffer)
                if fallback_match:
                    sentence = buffer[:fallback_match.end()]
                    buffer = buffer[fallback_match.end():]
                    sentence = _strip_stage_directions(sentence)
                    if sentence:
                        yield sentence
                    continue
            
            # 没找到断句点，继续累积
            break

    # 最后一段（可能没有标点）
    buffer = _strip_stage_directions(buffer)
    if buffer and not (cancel_event and cancel_event.is_set()):
        yield buffer


# ============== Streaming Reply Generator ==============

def generate_online_reply_streaming(
    figure: dict,
    user_input_text: str,
    history: Optional[List[dict]] = None,
    session_summary: str = "",
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    Streaming version: yields complete sentences as they are generated.
    
    LLM starts generating immediately; first sentence is yielded as soon as
    the model outputs sentence-ending punctuation.
    This enables the TTS pipeline to start speaking while LLM continues.
    """
    if not _is_configured():
        raise OnlineBrainError("ARK_API_KEY or ARK_ENDPOINT_ID not set")

    messages = build_dialogue_messages(
        figure,
        user_input_text,
        history,
        session_summary,
    )

    # 出错检测用完整文本
    full_text_chunks: List[str] = []

    for sentence in _generate_sentence_stream(messages, cancel_event=cancel_event):
        if cancel_event and cancel_event.is_set():
            return
        full_text_chunks.append(sentence)

        # 通用助手话术检测（检查到目前为止的完整句子）
        full_so_far = "".join(full_text_chunks)
        if _detect_breaking_out(sentence):
            # 跳过通用助手套话，流结束后按同一角色上下文重试。
            continue

        yield sentence

    # 出错检测（最后完整文本）
    full_text = "".join(full_text_chunks)
    if _detect_breaking_out(full_text):
        # 尝试重生成
        try:
            retry_messages = list(messages[:-1])  # 去掉 user input
            retry_messages.append({"role": "user", "content": user_input_text + "（请简短回复，1-2句）"})
            retry_buffer = ""
            retry_chunks: List[str] = []

            for chunk in _call_doubao_streaming(
                retry_messages,
                cancel_event=cancel_event,
            ):
                if cancel_event and cancel_event.is_set():
                    return
                retry_buffer += chunk
                retry_chunks.append(chunk)

                while True:
                    match = _SENTENCE_ENDINGS.search(retry_buffer)
                    if not match:
                        break
                    sentence = retry_buffer[:match.end()]
                    retry_buffer = retry_buffer[match.end():]
                    sentence = _strip_stage_directions(sentence)
                    if sentence:
                        yield sentence

            retry_text = "".join(retry_chunks)
            if _detect_breaking_out(retry_text):
                # 仍是通用助手套话 → 用 signature_lines 兜底
                cp = figure.get("soul_profile", {}).get("character_profile") or {}
                signature_lines = cp.get("signature_lines") or []
                if signature_lines:
                    import random
                    fallback = random.choice(signature_lines)
                else:
                    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
                    defaults = {
                        "桀骜战神型": "俺老孙去也！",
                        "软萌治愈型": "嗯...人家不太懂呢~",
                        "傲娇吐槽型": "哈？问这种奇怪的问题...",
                    }
                    fallback = defaults.get(archetype, "这个嘛...人家不太清楚呢~")
                # 清空之前的内容，只返回兜底
                yield fallback
        except Exception:
            pass  # 重生成失败，保持原内容


# ============== Bot 联网搜索 ==============

def _call_doubao_bot_streaming(
    messages: List[dict],
    timeout: float = 20.0,
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    Call Doubao Ark Bot API with stream=True, yielding delta chunks as they arrive.

    联网搜索端点：/bots/chat/completions, model = ARK_BOT_ID
    响应格式同 OpenAI (choices[0].delta.content stream)

    无 ARK_BOT_ID 或调用失败时返回空 Generator（优雅回退）
    """
    import urllib.request
    import urllib.error

    bot_cfg = _get_bot_config()
    if not bot_cfg.get("bot_id"):
        return  # 无 Bot ID，优雅回退

    headers = {
        "Authorization": f"Bearer {bot_cfg['api_key']}",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
    }

    payload = {
        "model": bot_cfg["bot_id"],
        "messages": messages,
        "max_tokens": 800,
        "temperature": 0.9,
        "stream": True,
    }

    url = f"{bot_cfg['base_url']}/bots/chat/completions"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        if cancel_event and cancel_event.is_set():
            return
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            add_callback = getattr(cancel_event, "add_callback", None)
            remove_callback = getattr(cancel_event, "remove_callback", None)
            if callable(add_callback):
                add_callback(resp.close)
            try:
                for line in resp:
                    if cancel_event and cancel_event.is_set():
                        return
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    # 兼容两种 SSE 格式：data:{...} 和 data: {...}
                    if line.startswith("data:"):
                        line = line[5:].lstrip()
                    if line == "[DONE]":
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    choices = obj.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
            finally:
                if callable(remove_callback):
                    remove_callback(resp.close)
    except urllib.error.HTTPError as e:
        print(f"[Bot联网] HTTP error: {e.code} {e.reason}")
        return
    except Exception as e:
        if cancel_event and cancel_event.is_set():
            return
        print(f"[Bot联网] 错误: {e}")
        return


def _generate_bot_sentence_stream(
    messages: List[dict],
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    Generator: calls Bot streaming, accumulates text, yields complete sentences.

    沿用现有的句子切分逻辑（句末标点 + 40字兜底）
    """
    buffer = ""

    for chunk in _call_doubao_bot_streaming(
        messages,
        cancel_event=cancel_event,
    ):
        if cancel_event and cancel_event.is_set():
            return
        buffer += chunk

        while True:
            match = _SENTENCE_ENDINGS.search(buffer)
            if match:
                sentence = buffer[:match.end()]
                buffer = buffer[match.end():]
                sentence = _strip_stage_directions(sentence)
                if sentence:
                    yield sentence
                continue

            if len(buffer) > 40:
                fallback_match = _SENTENCE_FALLBACK.search(buffer)
                if fallback_match:
                    sentence = buffer[:fallback_match.end()]
                    buffer = buffer[fallback_match.end():]
                    sentence = _strip_stage_directions(sentence)
                    if sentence:
                        yield sentence
                    continue

            break

    buffer = _strip_stage_directions(buffer)
    if buffer and not (cancel_event and cancel_event.is_set()):
        yield buffer


def generate_online_reply_streaming_with_bot(
    figure: dict,
    user_input_text: str,
    history: Optional[List[dict]] = None,
    session_summary: str = "",
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    联网搜索流式回复：先说过场语，再联网查资料。

    - 若 Bot 可用：用 Bot 联网搜索
    - 若 Bot 不可用：优雅回退到普通在线大脑
    """
    messages = build_dialogue_messages(
        figure,
        user_input_text,
        history,
        session_summary,
    )

    # 检查 Bot 是否可用
    if _is_bot_configured():
        # Bot 联网路径
        full_text_chunks: List[str] = []
        has_content = False

        for sentence in _generate_bot_sentence_stream(
            messages,
            cancel_event=cancel_event,
        ):
            if cancel_event and cancel_event.is_set():
                return
            full_text_chunks.append(sentence)
            has_content = True
            yield sentence

        # Bot 返回空 → 回退到普通在线大脑
        if not has_content:
            print("[Bot联网] Bot 无返回，回退到普通在线大脑")
            for sentence in _generate_sentence_stream(
                messages,
                cancel_event=cancel_event,
            ):
                yield sentence
    else:
        # 无 Bot 配置，直接用普通在线大脑
        for sentence in _generate_sentence_stream(
            messages,
            cancel_event=cancel_event,
        ):
            yield sentence


# 常见城市名列表（用于提取用户提到的城市）
_COMMON_CITIES = [
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 省会城市
    "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州", "郑州", "长沙",
    "沈阳", "青岛", "济南", "哈尔滨", "合肥", "大连", "厦门", "佛山", "东莞", "无锡",
    "昆明", "宁波", "福州", "长春", "石家庄", "南宁", "温州", "太原", "徐州", "泉州",
    "惠州", "绍兴", "嘉兴", "台州", "烟台", "潍坊", "常州", "南通", "金华", "珠海",
    "中山", "兰州", "贵阳", "保定", "临沂", "唐山", "呼和浩特", "温州", "绍兴", "嘉兴",
    # 其他热门城市
    "三亚", "丽江", "桂林", "黄山", "张家界",
]


def extract_city(text: str) -> Optional[str]:
    """
    从文本中提取城市名。
    
    返回：城市名（如"北京"）或 None（未找到）
    """
    text = text.replace("市", "").replace("省", "")
    for city in _COMMON_CITIES:
        if city in text:
            return city
    return None


def is_weather_query(text: str) -> bool:
    """
    判断是否是天气查询。
    """
    text_lower = text.lower()
    weather_keywords = ["天气", "气温", "温度", "下雨", "PM2.5", "空气质量"]
    return any(kw in text_lower for kw in weather_keywords)


def process_weather_query(text: str, figure: dict) -> dict:
    """
    处理天气查询：解析城市，决定走联网还是追问。
    
    Returns:
        {
            'should_search': bool,      # 是否应该走联网搜索
            'query': str,               # 传给 Bot 的查询（可能已补全城市）
            'need_retry': bool,         # 是否需要重新处理（追问后用户再问）
            'reply': str,               # 若不走联网，返回追问话术
        }
    """
    # 提取句中的城市
    city_in_text = extract_city(text)
    # 获取记忆中的城市
    memory = figure.get("memory", {})
    remembered_city = memory.get("user_city")
    
    if city_in_text:
        # 句中显式带城市 → 用该城市联网查，并更新记忆
        return {
            'should_search': True,
            'query': f"{city_in_text}今天天气",
            'need_retry': False,
            'reply': "",
            'city_to_save': city_in_text,
        }
    elif remembered_city:
        # 句中没带城市但有记忆 → 用记忆里的城市
        return {
            'should_search': True,
            'query': f"{remembered_city}今天天气",
            'need_retry': False,
            'reply': "",
            'city_to_save': None,
        }
    else:
        # 句中没带城市且无记忆 → 角色化追问
        reply = generate_weather_city_prompt(figure)
        return {
            'should_search': False,
            'query': "",
            'need_retry': True,
            'reply': reply,
            'city_to_save': None,
        }


def generate_weather_city_prompt(figure: dict) -> str:
    """
    生成角色化追问城市的话术。
    """
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    address_user_as = figure.get("soul_profile", {}).get("address_user_as", "你")

    prompts = {
        "桀骜战神型": f"嘿！{address_user_as}想查哪个城市的天气？快告诉俺老孙！",
        "软萌治愈型": f"嗯嗯~{address_user_as}想查哪个城市的天气呀~人家好去帮你看看~",
        "傲娇吐槽型": f"哈？{address_user_as}问天气却不说哪个城市？本小姐怎么查嘛~",
        "默认": f"嗯~{address_user_as}想查哪个城市的天气呀~",
    }

    return prompts.get(archetype, prompts["默认"])


# ============== 角色化过场语 ==============

# 过场语模板（按 archetype）
_BRIDGING_PHRASE_TEMPLATES = {
    "桀骜战神型": [
        "且慢！{user}问的这个问题，俺老孙得去查查！",
        "嘿！{user}问的这个...等俺老孙打听打听！",
    ],
    "软萌治愈型": [
        "稍等哦~{user}这个问题，人家去帮你查一下~",
        "嗯嗯~{user}想知道这个呀，人家马上帮你看看~",
    ],
    "傲娇吐槽型": [
        "哈？{user}问这个...行吧，本小姐去查查~",
        "哼~{user}问的这个问题...等着！",
    ],
    "默认": [
        "稍等哦~{user}这个问题，人家去帮你查一下~",
    ],
}

# 没网话术模板
_NO_NETWORK_PHRASES = {
    "桀骜战神型": "哼！俺老孙现在没网，等你联网了再来问我！",
    "软萌治愈型": "哎呀~{user}，我现在没网哦，等联网了再帮你查~",
    "傲娇吐槽型": "哈？没网？本小姐现在查不了，等你连上网再说！",
    "默认": "嗯...我现在没网哦，等你联网了我再帮你查~",
}


def generate_bridging_phrase(figure: dict) -> str:
    """
    生成角色化过场语（快路径，模板，不等大模型）。

    联网查询前播放一句过场语，让用户知道灵偶正在去查资料。
    """
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    address_user_as = figure.get("soul_profile", {}).get("address_user_as", "你")

    templates = _BRIDGING_PHRASE_TEMPLATES.get(archetype, _BRIDGING_PHRASE_TEMPLATES["默认"])

    import random
    template = random.choice(templates)
    return template.format(user=address_user_as)


def generate_no_network_phrase(figure: dict) -> str:
    """
    生成角色化"没网"话术。

    联网查询失败时播放，告诉用户当前没网。
    """
    archetype = figure.get("soul_profile", {}).get("archetype", "软萌治愈型")
    address_user_as = figure.get("soul_profile", {}).get("address_user_as", "你")

    phrases = _NO_NETWORK_PHRASES.get(archetype, _NO_NETWORK_PHRASES["默认"])
    return phrases.format(user=address_user_as)


def should_use_bot_search(text: str) -> bool:
    """
    判定用户问题是否需要联网搜索。

    用单关键词子串命中（只要句子里出现关键词就算），更宽松。
    目标："今天北京天气""上海天气如何""现在几点""茅台股价"都能命中。

    返回 True 表示需要联网，返回 False 表示普通闲聊。
    """
    import re

    # 单关键词：只要句子里出现就算（不用连续匹配）
    single_keywords = [
        "天气", "气温", "温度", "下雨", "PM2.5", "空气质量",
        "新闻", "热搜",
        "股价", "股票", "涨跌", "指数",
        "现在几点", "现在时间", "几点",
        "多少钱", "价格", "汇率",
        "比赛结果", "比分",
        "最新",
    ]
    # 多词组合：需要连续匹配
    multi_patterns = [
        r"who is",
        r"what is",
        r"how to",
        r"怎么做",
        r"是什么",
        r"哪个",
        r"哪里",
        r"什么电影",
        r"推荐",
    ]

    text_lower = text.lower()

    # 先检查单关键词（子串匹配）
    for kw in single_keywords:
        if kw in text_lower:
            return True

    # 再检查多词组合
    for pat in multi_patterns:
        if re.search(pat, text_lower):
            return True

    return False
