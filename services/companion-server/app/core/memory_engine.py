# services/companion-server/app/core/memory_engine.py
"""
Memory Engine: 记忆胶囊提取

Phase C: 对话后异步从 user_input_text 提取值得记住的事

核心逻辑：
- 使用豆包 API 提取"值得记住的事"
- 提取结果存入 memory_capsule（user_said 类型）
- 不阻塞对话主流程（异步/顺带执行）
- 提取失败不影响对话结果
"""

import os
import httpx
import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime


# ============== Config ==============

def _get_ark_config() -> Dict[str, str]:
    return {
        "api_key": os.getenv("ARK_API_KEY", "").strip(),
        "endpoint_id": os.getenv("ARK_ENDPOINT_ID", "").strip(),
        "base_url": os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip(),
    }


def _is_configured() -> bool:
    cfg = _get_ark_config()
    return bool(cfg["api_key"] and cfg["endpoint_id"])


# ============== Extraction Prompt ==============

MEMORY_EXTRACTION_PROMPT = """你是一个记忆提取助手。
用户的输入可能包含值得记住的事。

【判断标准 - 值得记住的事】
- 用户提到的工作/学习/生活相关重要事件
- 用户的喜好/厌恶（喜欢的食物/音乐/电影等）
- 用户的心情/状态（开心/难过/压力大/疲惫等）
- 用户的计划/目标/愿望
- 用户提到的纪念日/生日/特殊日子
- 用户的习惯/癖好/小秘密
- 有意义的人事物

【不值得记住的事】
- 无意义的寒暄（你好/在吗/哦）
- 简单问答题目的答案
- 重复的日常对话

【输出格式】
严格只输出 JSON，不要任何前缀后缀文字：
{
  "worth_remember": true或false,
  "content": "如果worth_remember为true，这是值得记住的事的一句话摘要（≤30字）",
  "reason": "判断理由（≤20字）"
}

【严格要求】
- worth_remember为false时，content和reason也要返回（填"无"或简短理由）
- content必须≤30字
- 输出必须是纯 JSON，不含任何其他文字。"""


def _call_doubao(messages: list, timeout: float = 8.0) -> str:
    """调用豆包 API，返回 assistant reply text。"""
    cfg = _get_ark_config()
    
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": cfg["endpoint_id"],
        "messages": messages,
        "max_tokens": 100,
        "temperature": 0.3,  # 低温度保证稳定输出
        "thinking": {"type": "disabled"},
    }
    
    url = f"{cfg['base_url']}/chat/completions"
    
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise Exception(f"Ark API error: {resp.status_code}")
        
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise Exception("No choices in response")
        return choices[0].get("message", {}).get("content", "").strip()


def _parse_extraction(raw: str) -> Tuple[bool, str, str]:
    """解析提取结果。"""
    try:
        # 尝试提取 JSON
        raw = raw.strip()
        # 去掉可能的 markdown 代码块
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])
        
        data = json.loads(raw)
        worth_remember = bool(data.get("worth_remember", False))
        content = str(data.get("content", "")).strip()
        reason = str(data.get("reason", "")).strip()
        return worth_remember, content, reason
    except Exception:
        return False, "", ""


def extract_memory(user_input_text: str) -> Optional[Dict[str, Any]]:
    """
    从用户输入中提取值得记住的事。
    
    Returns:
        capsule dict 或 None（不值得记住或提取失败）
    """
    if not _is_configured():
        return None
    
    if not user_input_text or len(user_input_text.strip()) < 3:
        return None
    
    messages = [
        {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
        {"role": "user", "content": f"请判断这段话是否包含值得记住的事：\n\n{user_input_text}"},
    ]
    
    try:
        raw = _call_doubao(messages, timeout=15.0)
        worth_remember, content, reason = _parse_extraction(raw)
        
        if worth_remember and content and len(content) > 0:
            return {
                "type": "user_said",
                "content": content,
                "created_at": datetime.utcnow().isoformat(),
            }
    except Exception:
        pass
    
    return None


def extract_memory_async(figure: dict, user_input_text: str, user_id: Optional[str] = None) -> None:
    """
    异步提取记忆（非阻塞）。
    
    这是一个简化版本，直接调用 extract_memory，
    在实际生产环境中可以改为后台任务队列。
    """
    try:
        capsule = extract_memory(user_input_text)
        if capsule:
            from data.store import get_figure, save_figure
            from app.core.relationship_engine import add_memory_capsule
            
            figure_id = figure.get("figure_id")
            if not figure_id:
                return
            
            # 重新获取最新的 figure（避免并发问题）
            figure = get_figure(figure_id, user_id=user_id)
            if not figure:
                return
            
            memory = figure.get("memory", {})
            add_memory_capsule(memory, capsule)
            figure["memory"] = memory
            save_figure(figure_id, figure, user_id=user_id)
    except Exception:
        # 提取失败不影响主流程，静默忽略
        pass