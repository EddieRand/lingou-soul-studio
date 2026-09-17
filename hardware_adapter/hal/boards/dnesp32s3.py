"""Verified DNESP32S3 board metadata; no protocol or business logic."""

from __future__ import annotations

from dataclasses import dataclass

from hardware_adapter.hal.contracts import (
    AudioFormat,
    MICROPHONE_FORMAT,
    SPEAKER_FORMAT,
)


@dataclass(frozen=True)
class BoardPinout:
    led: int
    fsr: int
    microphone_bclk: int
    microphone_ws: int
    microphone_data_in: int
    speaker_bclk: int
    speaker_lrc: int
    speaker_data_out: int


@dataclass(frozen=True)
class BoardProfile:
    profile_id: str
    mcu: str
    microphone_model: str
    amplifier_model: str
    microphone_format: AudioFormat
    speaker_format: AudioFormat
    pinout: BoardPinout
    validated_aec: bool


DNESP32S3_PROFILE = BoardProfile(
    profile_id="dnesp32s3-rev-a",
    mcu="ESP32-S3",
    microphone_model="INMP441",
    amplifier_model="MAX98357A",
    microphone_format=MICROPHONE_FORMAT,
    speaker_format=SPEAKER_FORMAT,
    pinout=BoardPinout(
        led=18,
        fsr=16,
        microphone_bclk=5,
        microphone_ws=7,
        microphone_data_in=4,
        speaker_bclk=6,
        speaker_lrc=15,
        speaker_data_out=17,
    ),
    validated_aec=False,
)
