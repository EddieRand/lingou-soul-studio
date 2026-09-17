"""Ordered startup and rollback for a complete device HAL."""

from __future__ import annotations

from dataclasses import dataclass

from hardware_adapter.hal.contracts import DeviceHAL, LifecyclePort


@dataclass(frozen=True)
class ComponentFailure:
    component: str
    error: str


class HALStartupError(RuntimeError):
    def __init__(
        self,
        component: str,
        cause: BaseException,
        rollback_failures: tuple[ComponentFailure, ...],
    ):
        super().__init__(f"failed to start HAL component {component}: {cause}")
        self.component = component
        self.cause = cause
        self.rollback_failures = rollback_failures


class HALShutdownError(RuntimeError):
    def __init__(self, failures: tuple[ComponentFailure, ...]):
        details = ", ".join(
            f"{failure.component}: {failure.error}"
            for failure in failures
        )
        super().__init__(f"failed to stop HAL components: {details}")
        self.failures = failures


class DeviceHALSupervisor:
    """Start components once and always stop them in reverse order."""

    def __init__(self, hal: DeviceHAL):
        self.hal = hal
        self._started: list[tuple[str, LifecyclePort]] = []

    @property
    def started_components(self) -> tuple[str, ...]:
        return tuple(name for name, _component in self._started)

    async def start(self) -> None:
        if self._started:
            return
        for name, component in self.hal.lifecycle_components():
            self._started.append((name, component))
            try:
                await component.start()
            except BaseException as exc:
                failures = await self._rollback()
                raise HALStartupError(name, exc, failures) from exc

    async def _rollback(self) -> tuple[ComponentFailure, ...]:
        failures: list[ComponentFailure] = []
        while self._started:
            name, component = self._started.pop()
            try:
                await component.stop()
            except BaseException as exc:
                failures.append(ComponentFailure(name, str(exc)))
        return tuple(failures)

    async def stop(self) -> None:
        failures = await self._rollback()
        if failures:
            raise HALShutdownError(failures)

    async def __aenter__(self) -> DeviceHAL:
        await self.start()
        return self.hal

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.stop()
