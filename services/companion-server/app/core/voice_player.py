# services/companion-server/app/core/voice_player.py
"""
Voice player: delegates to tts_adapter.
Keeps the speak() signature for backwards compatibility.
"""

from app.core.tts_adapter import speak_with_engine, synthesize_and_save


def speak(
    text: str,
    voice_profile: dict,
    figure_id: str,
    async_mode: bool = True,
    soul_profile: dict = None,
    force_offline: bool = False,
) -> dict:
    """
    Speak text using the configured TTS engine.
    Replaces the old macOS say-only implementation.
    """
    return speak_with_engine(
        text=text,
        voice_profile=voice_profile,
        figure_id=figure_id,
        async_mode=async_mode,
        soul_profile=soul_profile,
        force_offline=force_offline,
    )
