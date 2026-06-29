# services/companion-server/app/core/voxcpm2_adapter.py
"""
VoxCPM2 voice cloning adapter.
Abstract interface for voice cloning TTS.
Future: clone_voice / get_clone_status / synthesize_with_cloned.
MVP: NotImplementedError stub.
"""

from pathlib import Path
from typing import Optional

# voice_profile fields used as future clone carriers:
#   voice_mode: "voice_clone" | "default"
#   clone_status: "not_started" | "pending" | "cloning" | "ready" | "failed"
#   clone_engine: "voxcpm2" | None
#   recording_url: path to reference audio (from /api/voice/upload)


def clone_voice(reference_audio_path: str, figure_id: str) -> str:
    """
    Start a voice cloning job.
    Returns job_id for status polling.
    Raises NotImplementedError in MVP.
    """
    raise NotImplementedError(
        "VoxCPM2 voice cloning not yet implemented. "
        "Upload reference audio via POST /api/voice/upload, "
        "then call this function once the model is deployed."
    )


def get_clone_status(job_id: str) -> dict:
    """
    Poll voice cloning job status.
    Returns dict: {status: "pending"|"cloning"|"ready"|"failed", progress: float, error: str|None}
    Raises NotImplementedError in MVP.
    """
    raise NotImplementedError(
        "VoxCPM2 voice cloning not yet implemented."
    )


def synthesize_with_cloned(text: str, figure_id: str) -> Optional[str]:
    """
    Synthesize audio using a cloned voice.
    Requires clone_status == "ready".
    Returns mp3 file path or None.
    Raises NotImplementedError in MVP.
    """
    raise NotImplementedError(
        "VoxCPM2 voice cloning not yet implemented."
    )


def is_cloning_available() -> bool:
    """Returns True if VoxCPM2 service is deployed and available."""
    return False
