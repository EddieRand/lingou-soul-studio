"""Confirmed-fact memory with non-blocking candidate extraction."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import threading
from typing import Any, Callable, Optional
import unicodedata
import uuid

import httpx

from data.store import DataIntegrityError, get_figure, update_figure_atomic


MAX_CONFIRMED_FACTS = 10
MAX_MEMORY_CANDIDATES = 10
MAX_MEMORY_TOMBSTONES = 50
MAX_MEMORY_CONTENT_LENGTH = 120


class MemoryNotFoundError(RuntimeError):
    """The requested memory does not exist for this figure."""


class MemoryConflictError(RuntimeError):
    """The requested memory content duplicates another active record."""


class MemoryLimitError(RuntimeError):
    """The MVP confirmed-fact limit has been reached."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_ark_config() -> dict[str, str]:
    return {
        "api_key": os.getenv("ARK_API_KEY", "").strip(),
        "endpoint_id": os.getenv("ARK_ENDPOINT_ID", "").strip(),
        "base_url": os.getenv(
            "ARK_BASE_URL",
            "https://ark.cn-beijing.volces.com/api/v3",
        ).strip(),
    }


def _is_configured() -> bool:
    config = _get_ark_config()
    return bool(config["api_key"] and config["endpoint_id"])


MEMORY_EXTRACTION_PROMPT = """你是共同记忆候选提取器。
只判断用户是否明确表达了以后仍可能有用、且适合让用户确认的一条事实。

可以提取：
- 稳定偏好或厌恶
- 明确身份、关系或长期习惯
- 有后续意义的计划、目标、纪念日
- 用户明确希望记住的事实

不要提取：
- 寒暄、一次性问题、模型回复
- 对用户人格、心理或健康状态的推断
- 密码、验证码、支付信息、证件号等敏感凭据
- 模糊、未经用户表达的结论

严格只输出 JSON：
{"worth_remember": true或false, "content": "第一人称事实，最多60字"}
worth_remember=false 时 content 必须为空字符串。"""


def _call_doubao(messages: list[dict], timeout: float = 15.0) -> str:
    config = _get_ark_config()
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        response = client.post(
            f"{config['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": config["endpoint_id"],
                "messages": messages,
                "max_tokens": 120,
                "temperature": 0.1,
                "thinking": {"type": "disabled"},
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"Ark API error: {response.status_code}")
    choices = response.json().get("choices", [])
    if not choices:
        raise RuntimeError("No choices in response")
    return str(choices[0].get("message", {}).get("content", "")).strip()


def _normalize_content(content: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(content or ""))
    normalized = " ".join(normalized.split()).strip()
    if not normalized:
        raise ValueError("memory content cannot be empty")
    if len(normalized) > MAX_MEMORY_CONTENT_LENGTH:
        raise ValueError(
            f"memory content cannot exceed {MAX_MEMORY_CONTENT_LENGTH} characters"
        )
    return normalized


def _content_key(content: str) -> str:
    normalized = unicodedata.normalize("NFKC", content).casefold()
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_extraction(raw: str) -> Optional[str]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])
    try:
        result = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if result.get("worth_remember") is not True:
        return None
    try:
        content = _normalize_content(result.get("content"))
    except ValueError:
        return None
    return content[:60]


def extract_memory_candidate(user_input_text: str) -> Optional[str]:
    """Use the model to propose one candidate without writing storage."""
    if not _is_configured() or len(str(user_input_text or "").strip()) < 3:
        return None
    try:
        raw = _call_doubao([
            {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"判断下面输入：\n{user_input_text}",
            },
        ])
        return _parse_extraction(raw)
    except Exception:
        return None


def _memory_lists(memory: dict) -> tuple[list[dict], list[dict], list[dict]]:
    confirmed = [
        item for item in memory.get("confirmed_facts", [])
        if isinstance(item, dict) and item.get("memory_id") and item.get("content")
    ]
    candidates = [
        item for item in memory.get("memory_candidates", [])
        if isinstance(item, dict) and item.get("memory_id") and item.get("content")
    ]
    tombstones = [
        item for item in memory.get("memory_tombstones", [])
        if isinstance(item, dict) and item.get("content_key")
    ]
    memory["confirmed_facts"] = confirmed[-MAX_CONFIRMED_FACTS:]
    memory["memory_candidates"] = candidates[-MAX_MEMORY_CANDIDATES:]
    memory["memory_tombstones"] = tombstones[-MAX_MEMORY_TOMBSTONES:]
    return (
        memory["confirmed_facts"],
        memory["memory_candidates"],
        memory["memory_tombstones"],
    )


def _snapshot(figure: dict) -> dict:
    memory = figure.get("memory", {})
    confirmed, candidates, _ = _memory_lists(memory)
    return {
        "figure_id": figure["figure_id"],
        "confirmed_facts": deepcopy(confirmed),
        "candidates": deepcopy(candidates),
        "confirmed_limit": MAX_CONFIRMED_FACTS,
        "revision": int(memory.get("memory_revision", 0)),
        "updated_at": memory.get("memory_updated_at"),
    }


def _new_record(
    content: str,
    *,
    status: str,
    source: str,
    source_turn_id: Optional[str],
) -> dict:
    now = _now_iso()
    return {
        "memory_id": f"MEM-{uuid.uuid4().hex}",
        "content": _normalize_content(content),
        "content_key": _content_key(content),
        "status": status,
        "source": source,
        "source_turn_id": str(source_turn_id)[:128] if source_turn_id else None,
        "created_at": now,
        "updated_at": now,
    }


def _record_change(memory: dict) -> None:
    memory["memory_revision"] = int(memory.get("memory_revision", 0)) + 1
    memory["memory_updated_at"] = _now_iso()


def _mutate_memory(
    figure_id: str,
    user_id: str,
    operation: Callable[[dict], tuple[Optional[dict], bool]],
) -> tuple[Optional[dict], dict]:
    holder: dict[str, Optional[dict]] = {"record": None}

    def mutate(figure: dict) -> Optional[dict]:
        memory = figure.setdefault("memory", {})
        _memory_lists(memory)
        record, changed = operation(memory)
        holder["record"] = deepcopy(record)
        if not changed:
            return None
        _record_change(memory)
        figure["memory"] = memory
        return figure

    saved = update_figure_atomic(figure_id, mutate, user_id=user_id)
    return holder["record"], _snapshot(saved)


def list_memory_records(figure_id: str, *, user_id: str) -> dict:
    figure = get_figure(figure_id, user_id=user_id)
    if not figure:
        raise DataIntegrityError("figure is not owned by this user")
    return _snapshot(figure)


def add_memory_candidate(
    figure_id: str,
    content: str,
    *,
    source_turn_id: str,
    user_id: str,
) -> tuple[Optional[dict], bool]:
    normalized = _normalize_content(content)
    key = _content_key(normalized)
    created = False

    def operation(memory: dict) -> tuple[Optional[dict], bool]:
        nonlocal created
        confirmed, candidates, tombstones = _memory_lists(memory)
        if any(item.get("content_key") == key for item in tombstones):
            return None, False
        for item in [*confirmed, *candidates]:
            if item.get("content_key") == key:
                return item, False
        record = _new_record(
            normalized,
            status="pending",
            source="model",
            source_turn_id=source_turn_id,
        )
        candidates.append(record)
        memory["memory_candidates"] = candidates[-MAX_MEMORY_CANDIDATES:]
        created = True
        return record, True

    record, _ = _mutate_memory(figure_id, user_id, operation)
    return record, created


def create_confirmed_memory(
    figure_id: str,
    content: str,
    *,
    user_id: str,
) -> tuple[dict, bool]:
    normalized = _normalize_content(content)
    key = _content_key(normalized)
    created = False

    def operation(memory: dict) -> tuple[dict, bool]:
        nonlocal created
        confirmed, candidates, tombstones = _memory_lists(memory)
        for item in confirmed:
            if item.get("content_key") == key:
                return item, False
        if len(confirmed) >= MAX_CONFIRMED_FACTS:
            raise MemoryLimitError("confirmed memory limit reached")
        candidate = next(
            (item for item in candidates if item.get("content_key") == key),
            None,
        )
        if candidate:
            candidates.remove(candidate)
            record = {
                **candidate,
                "status": "confirmed",
                "source": "user",
                "updated_at": _now_iso(),
                "confirmed_at": _now_iso(),
            }
        else:
            record = _new_record(
                normalized,
                status="confirmed",
                source="user",
                source_turn_id=None,
            )
            record["confirmed_at"] = record["updated_at"]
        confirmed.append(record)
        memory["confirmed_facts"] = confirmed
        memory["memory_candidates"] = candidates
        memory["memory_tombstones"] = [
            item for item in tombstones if item.get("content_key") != key
        ]
        created = True
        return record, True

    record, _ = _mutate_memory(figure_id, user_id, operation)
    if record is None:
        raise DataIntegrityError("confirmed memory was not returned")
    return record, created


def confirm_memory_candidate(
    figure_id: str,
    memory_id: str,
    *,
    user_id: str,
) -> dict:
    def operation(memory: dict) -> tuple[dict, bool]:
        confirmed, candidates, tombstones = _memory_lists(memory)
        for item in confirmed:
            if item.get("memory_id") == memory_id:
                return item, False
        candidate = next(
            (item for item in candidates if item.get("memory_id") == memory_id),
            None,
        )
        if candidate is None:
            raise MemoryNotFoundError("memory candidate not found")
        duplicate = next(
            (
                item for item in confirmed
                if item.get("content_key") == candidate.get("content_key")
            ),
            None,
        )
        candidates.remove(candidate)
        if duplicate:
            memory["memory_candidates"] = candidates
            return duplicate, True
        if len(confirmed) >= MAX_CONFIRMED_FACTS:
            raise MemoryLimitError("confirmed memory limit reached")
        record = {
            **candidate,
            "status": "confirmed",
            "updated_at": _now_iso(),
            "confirmed_at": _now_iso(),
        }
        confirmed.append(record)
        memory["confirmed_facts"] = confirmed
        memory["memory_candidates"] = candidates
        memory["memory_tombstones"] = [
            item
            for item in tombstones
            if item.get("content_key") != record.get("content_key")
        ]
        return record, True

    record, _ = _mutate_memory(figure_id, user_id, operation)
    if record is None:
        raise DataIntegrityError("confirmed memory was not returned")
    return record


def update_memory_record(
    figure_id: str,
    memory_id: str,
    content: str,
    *,
    user_id: str,
) -> dict:
    normalized = _normalize_content(content)
    key = _content_key(normalized)

    def operation(memory: dict) -> tuple[dict, bool]:
        confirmed, candidates, tombstones = _memory_lists(memory)
        records = [*confirmed, *candidates]
        record = next(
            (item for item in records if item.get("memory_id") == memory_id),
            None,
        )
        if record is None:
            raise MemoryNotFoundError("memory record not found")
        if any(
            item.get("memory_id") != memory_id
            and item.get("content_key") == key
            for item in records
        ):
            raise MemoryConflictError("memory content already exists")
        old_key = str(record.get("content_key") or _content_key(record["content"]))
        if old_key == key and record.get("content") == normalized:
            return record, False
        tombstones.append({
            "content_key": old_key,
            "deleted_at": _now_iso(),
            "reason": "corrected",
        })
        record["content"] = normalized
        record["content_key"] = key
        record["updated_at"] = _now_iso()
        memory["memory_tombstones"] = [
            item
            for item in tombstones[-MAX_MEMORY_TOMBSTONES:]
            if item.get("content_key") != key
        ]
        return record, True

    record, _ = _mutate_memory(figure_id, user_id, operation)
    if record is None:
        raise DataIntegrityError("updated memory was not returned")
    return record


def delete_memory_record(
    figure_id: str,
    memory_id: str,
    *,
    user_id: str,
) -> dict:
    def operation(memory: dict) -> tuple[dict, bool]:
        confirmed, candidates, tombstones = _memory_lists(memory)
        record = next(
            (
                item for item in [*confirmed, *candidates]
                if item.get("memory_id") == memory_id
            ),
            None,
        )
        if record is None:
            raise MemoryNotFoundError("memory record not found")
        memory["confirmed_facts"] = [
            item for item in confirmed if item.get("memory_id") != memory_id
        ]
        memory["memory_candidates"] = [
            item for item in candidates if item.get("memory_id") != memory_id
        ]
        tombstones.append({
            "content_key": record.get("content_key") or _content_key(record["content"]),
            "deleted_at": _now_iso(),
            "reason": "deleted",
        })
        memory["memory_tombstones"] = tombstones[-MAX_MEMORY_TOMBSTONES:]
        return record, True

    record, _ = _mutate_memory(figure_id, user_id, operation)
    if record is None:
        raise DataIntegrityError("deleted memory was not returned")
    return record


def schedule_memory_extraction(
    figure_id: str,
    user_input_text: str,
    *,
    source_turn_id: str,
    user_id: str,
) -> Optional[threading.Thread]:
    """Extract after reply completion without blocking the response path."""
    if not _is_configured() or len(str(user_input_text or "").strip()) < 3:
        return None

    def worker() -> None:
        content = extract_memory_candidate(user_input_text)
        if not content:
            return
        try:
            add_memory_candidate(
                figure_id,
                content,
                source_turn_id=source_turn_id,
                user_id=user_id,
            )
        except (DataIntegrityError, ValueError):
            return

    thread = threading.Thread(
        target=worker,
        name=f"memory-extract-{figure_id}-{source_turn_id}",
        daemon=True,
    )
    thread.start()
    return thread
