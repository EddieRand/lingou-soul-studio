"""Initial RTOS task and queue budgets for the hardware adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskRole(str, Enum):
    CONTROL = "control"
    AUDIO_CAPTURE = "audio_capture"
    AUDIO_PLAYBACK = "audio_playback"
    NETWORK = "network"
    DIAGNOSTICS = "diagnostics"


class QueueOverflowPolicy(str, Enum):
    DROP_OLDEST = "drop_oldest"
    REJECT_NEW = "reject_new"
    BLOCK_WITH_TIMEOUT = "block_with_timeout"


@dataclass(frozen=True)
class TaskSpec:
    role: TaskRole
    name: str
    priority: int
    stack_budget_bytes: int
    queue_capacity: int
    overflow_policy: QueueOverflowPolicy
    core_affinity: Optional[int]
    responsibility: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("task name must not be empty")
        if self.priority <= 0:
            raise ValueError("task priority must be positive")
        if self.stack_budget_bytes < 2048:
            raise ValueError("task stack budget must be at least 2048 bytes")
        if self.queue_capacity <= 0:
            raise ValueError("task queue capacity must be positive")
        if self.core_affinity not in (None, 0, 1):
            raise ValueError("core affinity must be 0, 1 or None")


DEVICE_TASK_MODEL = (
    TaskSpec(
        role=TaskRole.CONTROL,
        name="lingou_control",
        priority=8,
        stack_budget_bytes=4096,
        queue_capacity=32,
        overflow_policy=QueueOverflowPolicy.REJECT_NEW,
        core_affinity=0,
        responsibility=(
            "Own session state, cancellation, lifecycle and indicator commands."
        ),
    ),
    TaskSpec(
        role=TaskRole.AUDIO_CAPTURE,
        name="lingou_capture",
        priority=7,
        stack_budget_bytes=8192,
        queue_capacity=12,
        overflow_policy=QueueOverflowPolicy.DROP_OLDEST,
        core_affinity=1,
        responsibility=(
            "Read fixed microphone frames, run the acoustic front end and "
            "hand 20 ms output frames to media transport."
        ),
    ),
    TaskSpec(
        role=TaskRole.AUDIO_PLAYBACK,
        name="lingou_playback",
        priority=7,
        stack_budget_bytes=4096,
        queue_capacity=8,
        overflow_policy=QueueOverflowPolicy.REJECT_NEW,
        core_affinity=1,
        responsibility=(
            "Write ordered output frames and allow control to abort immediately."
        ),
    ),
    TaskSpec(
        role=TaskRole.NETWORK,
        name="lingou_network",
        priority=6,
        stack_budget_bytes=6144,
        queue_capacity=24,
        overflow_policy=QueueOverflowPolicy.REJECT_NEW,
        core_affinity=0,
        responsibility=(
            "Own Wi-Fi, TLS, transport heartbeats and reconnect backoff."
        ),
    ),
    TaskSpec(
        role=TaskRole.DIAGNOSTICS,
        name="lingou_diagnostics",
        priority=2,
        stack_budget_bytes=3072,
        queue_capacity=64,
        overflow_policy=QueueOverflowPolicy.DROP_OLDEST,
        core_affinity=0,
        responsibility=(
            "Sample resource and network counters without blocking media tasks."
        ),
    ),
)


def validate_task_model(
    task_model: tuple[TaskSpec, ...] = DEVICE_TASK_MODEL,
) -> None:
    roles = [spec.role for spec in task_model]
    names = [spec.name for spec in task_model]
    if len(roles) != len(set(roles)):
        raise ValueError("task roles must be unique")
    if len(names) != len(set(names)):
        raise ValueError("task names must be unique")
    missing = set(TaskRole) - set(roles)
    if missing:
        raise ValueError(
            "task model is missing roles: "
            f"{sorted(role.value for role in missing)}"
        )
