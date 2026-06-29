"""
Volcengine TTS v2 WebSocket Bidirectional Client (Official API).

Implements bidirectional streaming TTS for uranus series speakers.
"""

import os
import asyncio
import json
import websockets
from typing import Optional

from .volc_tts_v2_protocol import (
    MsgType,
    EventType,
    start_connection,
    start_session,
    task_request,
    finish_session,
    finish_connection,
    wait_for_event,
    receive_message,
    generate_connect_id,
    generate_session_id,
)


def _volc_v2_config() -> dict:
    return {
        "api_key": os.getenv("VOLC_TTS_API_KEY", "").strip(),
        "endpoint": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
    }


def is_v2_configured() -> bool:
    cfg = _volc_v2_config()
    return bool(cfg["api_key"])


async def _synthesize_v2_async(text: str, speaker: str) -> Optional[bytes]:
    """
    Async implementation of TTS v2 bidirectional streaming.
    
    Flow:
        1. connect → start_connection → wait_for_event(ConnectionStarted)
        2. start_session → wait_for_event(SessionStarted)
        3. task_request → finish_session
        4. loop receive_message: collect AudioOnlyServer frames
        5. on SessionFinished → finish_connection → return mp3 bytes
    """
    cfg = _volc_v2_config()
    if not cfg["api_key"]:
        return None

    headers = {
        "X-Api-Key": cfg["api_key"],
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Connect-Id": generate_connect_id(),
        "X-Control-Require-Usage-Tokens-Return": "*",
    }

    session_id = generate_session_id()
    audio_chunks = []

    try:
        async with websockets.connect(
            cfg["endpoint"], 
            additional_headers=headers,
            max_size=10 * 1024 * 1024
        ) as ws:
            # Step 1: Start connection
            await start_connection(ws)
            await wait_for_event(ws, MsgType.FullServerResponse, EventType.ConnectionStarted)

            # Step 2: Start session
            start_session_payload = json.dumps({
                "event": int(EventType.StartSession),
                "req_params": {
                    "speaker": speaker,
                    "audio_params": {
                        "format": "mp3",
                        "sample_rate": 24000,
                    },
                },
            }).encode()
            await start_session(ws, start_session_payload, session_id)
            await wait_for_event(ws, MsgType.FullServerResponse, EventType.SessionStarted)

            # Step 3: Send task request
            task_payload = json.dumps({
                "event": int(EventType.TaskRequest),
                "req_params": {
                    "text": text,
                },
            }).encode()
            await task_request(ws, task_payload, session_id)

            # Step 4: Finish session (signals end of input)
            await finish_session(ws, session_id)

            # Step 5: Receive audio and wait for SessionFinished
            while True:
                msg = await receive_message(ws)

                # msg.type 可能是 MsgType 枚举或 int（容错处理）
                msg_type_val = msg.type.value if isinstance(msg.type, MsgType) else msg.type
                if msg_type_val == MsgType.AudioOnlyServer.value:
                    audio_chunks.append(msg.payload)

                elif msg_type_val == MsgType.FullServerResponse.value:
                    # event 可能是 EventType 枚举或 int（容错处理）
                    event_val = msg.event.value if isinstance(msg.event, EventType) else msg.event
                    if event_val == EventType.SessionFinished.value:
                        break
                    elif event_val in (EventType.SessionFailed.value, EventType.SessionCanceled.value):
                        return None
                    # 其余事件(TTSSentenceStart/TTSResponse/TTSSentenceEnd 等)忽略,继续循环收音频

            # Step 6: Finish connection
            await finish_connection(ws)

    except Exception as e:
        import traceback
        print(f"[TTS v2 Error] {e}")
        traceback.print_exc()
        return None

    if not audio_chunks:
        return None

    return b"".join(audio_chunks)


def synthesize_v2(text: str, speaker: str) -> Optional[bytes]:
    """
    Synchronous wrapper for TTS v2.
    
    Returns MP3 bytes or None on failure.
    """
    if not text or not speaker:
        return None

    try:
        return asyncio.run(_synthesize_v2_async(text, speaker))
    except Exception as e:
        import traceback
        print(f"[TTS v2 Sync Error] {e}")
        traceback.print_exc()
        return None
