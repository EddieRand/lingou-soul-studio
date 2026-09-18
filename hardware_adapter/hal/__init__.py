"""Board-independent hardware abstraction for Lingou voice devices."""

from hardware_adapter.hal.acoustic_profile import (
    ACOUSTIC_PROFILE_VERSION,
    DEFAULT_ACOUSTIC_PROFILE,
    AcousticProfile,
)
from hardware_adapter.hal.contracts import (
    AudioFormat,
    AudioFrame,
    DeviceHAL,
    IndicatorState,
    InputEvent,
    InputEventKind,
    MICROPHONE_FORMAT,
    NetworkSnapshot,
    NetworkState,
    ResourceSnapshot,
    SPEAKER_FORMAT,
)
from hardware_adapter.hal.lifecycle import DeviceHALSupervisor
from hardware_adapter.hal.task_model import DEVICE_TASK_MODEL

__all__ = [
    "ACOUSTIC_PROFILE_VERSION",
    "AcousticProfile",
    "AudioFormat",
    "AudioFrame",
    "DEVICE_TASK_MODEL",
    "DEFAULT_ACOUSTIC_PROFILE",
    "DeviceHAL",
    "DeviceHALSupervisor",
    "IndicatorState",
    "InputEvent",
    "InputEventKind",
    "MICROPHONE_FORMAT",
    "NetworkSnapshot",
    "NetworkState",
    "ResourceSnapshot",
    "SPEAKER_FORMAT",
]
