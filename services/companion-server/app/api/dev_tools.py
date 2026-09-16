"""Gates for deferred gameplay and local-only diagnostic operations."""

from __future__ import annotations

import os

from fastapi import HTTPException, status


DEV_TOOLS_ENV = "LINGOU_ENABLE_DEV_TOOLS"


def dev_tools_enabled() -> bool:
    return os.getenv(DEV_TOOLS_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_dev_tools() -> None:
    if not dev_tools_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="资源不存在或不可访问",
        )
