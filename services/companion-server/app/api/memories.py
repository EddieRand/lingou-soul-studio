"""Owner-scoped confirmed memory API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import get_current_user
from app.api.ownership import current_user_id, owned_figure_or_404
from app.core.memory_engine import (
    MemoryConflictError,
    MemoryLimitError,
    MemoryNotFoundError,
    confirm_memory_candidate,
    create_confirmed_memory,
    delete_memory_record,
    list_memory_records,
    update_memory_record,
)
from data.store import DataIntegrityError, validate_resource_id


router = APIRouter()


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryContentRequest(_StrictModel):
    content: str = Field(min_length=1, max_length=120)


def _memory_id_or_404(memory_id: str) -> str:
    try:
        return validate_resource_id(memory_id, "memory_id")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEMORY_NOT_FOUND", "message": "记忆不存在"},
        ) from exc


def _memory_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MEMORY_INVALID",
                "message": str(exc),
            },
        )
    if isinstance(exc, MemoryLimitError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_LIMIT_REACHED",
                "message": "最多保留 10 条已确认记忆，请先整理现有内容",
            },
        )
    if isinstance(exc, MemoryConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_CONFLICT",
                "message": "已有相同内容的记忆",
            },
        )
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "MEMORY_NOT_FOUND", "message": "记忆不存在"},
    )


@router.get("/{figure_id}/memories")
def get_memories(
    figure_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user_id(current_user)
    owned_figure_or_404(figure_id, user_id)
    try:
        return list_memory_records(figure_id, user_id=user_id)
    except DataIntegrityError as exc:
        raise _memory_error(exc) from exc


@router.post("/{figure_id}/memories", status_code=status.HTTP_201_CREATED)
def create_memory(
    figure_id: str,
    request: MemoryContentRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user_id(current_user)
    owned_figure_or_404(figure_id, user_id)
    try:
        record, created = create_confirmed_memory(
            figure_id,
            request.content,
            user_id=user_id,
        )
    except (DataIntegrityError, MemoryConflictError, MemoryLimitError, ValueError) as exc:
        raise _memory_error(exc) from exc
    return {"memory": record, "created": created}


@router.post("/{figure_id}/memories/{memory_id}/confirm")
def confirm_memory(
    figure_id: str,
    memory_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user_id(current_user)
    owned_figure_or_404(figure_id, user_id)
    memory_id = _memory_id_or_404(memory_id)
    try:
        record = confirm_memory_candidate(
            figure_id,
            memory_id,
            user_id=user_id,
        )
    except (DataIntegrityError, MemoryNotFoundError, MemoryLimitError) as exc:
        raise _memory_error(exc) from exc
    return {"memory": record}


@router.put("/{figure_id}/memories/{memory_id}")
def update_memory(
    figure_id: str,
    memory_id: str,
    request: MemoryContentRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user_id(current_user)
    owned_figure_or_404(figure_id, user_id)
    memory_id = _memory_id_or_404(memory_id)
    try:
        record = update_memory_record(
            figure_id,
            memory_id,
            request.content,
            user_id=user_id,
        )
    except (
        DataIntegrityError,
        MemoryConflictError,
        MemoryNotFoundError,
        ValueError,
    ) as exc:
        raise _memory_error(exc) from exc
    return {"memory": record}


@router.delete("/{figure_id}/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    figure_id: str,
    memory_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user_id(current_user)
    owned_figure_or_404(figure_id, user_id)
    memory_id = _memory_id_or_404(memory_id)
    try:
        delete_memory_record(figure_id, memory_id, user_id=user_id)
    except (DataIntegrityError, MemoryNotFoundError) as exc:
        raise _memory_error(exc) from exc
    return None
