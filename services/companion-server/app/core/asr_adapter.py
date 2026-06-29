# services/companion-server/app/core/asr_adapter.py
"""
ASR (Automatic Speech Recognition) adapter.
火山引擎「大模型流式语音识别」(sauc bigmodel) WebSocket 实现。

官方协议文档：
  - WebSocket URL: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
  - 鉴权：请求头 X-Api-Key / X-Api-Resource-Id / X-Api-Request-Id
  - 二进制帧：4字节header + 4字节payload_size + gzip(payload)

音频格式要求：
  - PCM 单声道 16000Hz int16 小端

凭证（环境变量）：
  - VOLC_TTS_API_KEY 或 VOLC_ASR_API_KEY
  - VOLC_ASR_RESOURCE_ID（默认：volc.bigasr.sauc.duration）
"""

import os
import json
import gzip
import uuid
import struct
import asyncio
import websockets
from typing import Optional, Callable

# 火山 sauc bigmodel WebSocket URL
VOLC_ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DEFAULT_RESOURCE_ID = "volc.bigasr.sauc.duration"


def _get_asr_config() -> dict:
    """获取火山 ASR 配置（从环境变量）"""
    # 优先使用 VOLC_ASR_API_KEY，否则复用 VOLC_TTS_API_KEY
    api_key = os.environ.get("VOLC_ASR_API_KEY") or os.environ.get("VOLC_TTS_API_KEY", "")
    resource_id = os.environ.get("VOLC_ASR_RESOURCE_ID", DEFAULT_RESOURCE_ID)
    return {
        "api_key": api_key,
        "resource_id": resource_id,
    }


def is_asr_available() -> bool:
    """Returns True if ASR service is configured."""
    cfg = _get_asr_config()
    return bool(cfg["api_key"] and cfg["resource_id"])


def transcribe(audio_path: str) -> str:
    """Transcribe audio file to text (非流式，占位)."""
    raise NotImplementedError("ASR 当前仅支持流式 WebSocket。请使用 transcribe_stream。")


def transcribe_bytes(audio_bytes: bytes, format: str = "wav") -> str:
    """Transcribe raw audio bytes to text (非流式，占位)."""
    raise NotImplementedError("ASR 当前仅支持流式 WebSocket。请使用 transcribe_stream。")


# ============== 火山二进制帧协议 ==============

def _build_frame_header(message_type: int, flags: int = 0) -> bytes:
    """
    构造火山二进制帧 4 字节 header。

    Header 格式（大端）：
      byte0: 高4位 protocol version (0b0001), 低4位 header size (0b0001=4字节)
      byte1: 高4位 message type, 低4位 flags
      byte2: 高4位 serialization (0b0001=JSON), 低4位 compression (0b0001=Gzip)
      byte3: 保留 0x00

    Message type:
      0b0001 = full client request (带配置)
      0b0010 = audio only request (纯音频)
      0b1001 = server response
      0b1111 = error

    Flags:
      0b0000 = 无 seq
      0b0010 = 负包（最后一包，指示结束）
    """
    # byte0: version=1, header_size=1 (各占4位)
    byte0 = (0b0001 << 4) | 0b0001  # 0x11

    # byte1: message_type (高4位), flags (低4位)
    byte1 = (message_type << 4) | flags

    # byte2: serialization=1 (JSON), compression=1 (Gzip)
    byte2 = (0b0001 << 4) | 0b0001  # 0x11

    # byte3: 保留
    byte3 = 0x00

    return bytes([byte0, byte1, byte2, byte3])


def _build_full_client_request() -> bytes:
    """
    构造 full client request 帧（第一帧，带配置）。

    Payload JSON:
      {"user":{"uid":"lingou"},
       "audio":{"format":"pcm","codec":"raw","rate":16000,"bits":16,"channel":1},
       "request":{"model_name":"bigmodel","enable_itn":true,"enable_punc":true,"show_utterances":true,
                  "vad":{"enabled":true,"max_speech_duration":60}}}

    火山 VAD/端点检测：
      - show_utterances: true → 返回 utterance 级别结果（每句话独立）
      - vad.enabled: true → 开启端点检测（静音时自动截断）
      - max_speech_duration: 60s → 最长单句时长限制
    """
    payload_json = {
        "user": {"uid": "lingou"},
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
            "vad": {
                "enabled": True,
                "max_speech_duration": 60,
            },
        },
    }

    # Gzip 压缩 payload
    payload_bytes = json.dumps(payload_json).encode("utf-8")
    payload_gz = gzip.compress(payload_bytes)

    # Header: message_type=0b0001 (full client request), flags=0
    header = _build_frame_header(message_type=0b0001, flags=0b0000)

    # Payload size (4字节大端)
    payload_size = struct.pack(">I", len(payload_gz))

    # 完整帧: header + payload_size + payload_gz
    return header + payload_size + payload_gz


def _build_audio_frame(audio_chunk: bytes, is_last: bool = False) -> bytes:
    """
    构造 audio only request 帧。

    Args:
        audio_chunk: PCM 音频分片（int16 小端）
        is_last: 是否最后一包（flags=0b0010 负包）
    """
    # Gzip 压缩音频数据
    payload_gz = gzip.compress(audio_chunk)

    # Header: message_type=0b0010 (audio only request)
    # flags: 0b0000 普通, 0b0010 负包（最后一包）
    flags = 0b0010 if is_last else 0b0000
    header = _build_frame_header(message_type=0b0010, flags=flags)

    # Payload size (4字节大端)
    payload_size = struct.pack(">I", len(payload_gz))

    return header + payload_size + payload_gz


def _parse_server_response(frame: bytes) -> dict:
    """
    解析 server response 帧。

    火山 server response(message_type=0b1001) 的帧结构：
      4字节header + [可选4字节sequence] + 4字节payload_size(大端) + payload(gzip压缩的JSON)

    火山响应结构（实测）：
      result = {
        "text": "完整累积文本",
        "utterances": [
          {"text": "第一句", "definite": true/false},
          {"text": "第二句", "definite": true/false},
          ...
        ]
      }

    Returns:
        {
          "text": str,           # 顶层累积文本
          "utterances": [        # utterance 列表（每个含 text + definite）
            {"text": str, "definite": bool},
            ...
          ]
        }
        或 {}（解析失败时）
    """
    if len(frame) < 8:
        return {}

    # message_type 和 flags
    message_type = (frame[1] >> 4) & 0x0F
    flags = frame[1] & 0x0F

    # message_type=0b1111 才是真错误帧
    if message_type == 0b1111:
        return {"error": "服务器返回错误帧"}

    # 只处理 server response (type=0b1001)
    if message_type != 0b1001:
        return {}

    # 偏移：跳过 header（4字节）
    off = 4

    # flags 含 sequence number 时（0b0001 / 0b0011）跳过4字节 seq
    if flags in (0b0001, 0b0011):
        off += 4

    # payload_size（4字节大端）
    if len(frame) < off + 4:
        return {}
    payload_size = int.from_bytes(frame[off:off+4], "big")
    off += 4

    # payload
    if len(frame) < off + payload_size:
        return {}
    payload = frame[off:off+payload_size]

    # gzip 解压
    try:
        payload = gzip.decompress(payload)
    except Exception:
        pass  # 可能未压缩

    # JSON 解析
    try:
        d = json.loads(payload.decode("utf-8"))
    except Exception:
        return {}

    # 提取 utterances 列表
    result = d.get("result", {}) or {}
    text = result.get("text", "")

    # utterances 在 result.utterances，每个含 text + definite
    utterances_raw = result.get("utterances", []) or []
    utterances = [
        {"text": u.get("text", ""), "definite": bool(u.get("definite"))}
        for u in utterances_raw
    ]

    return {"text": text, "utterances": utterances}


class VolcASRStream:
    """
    火山 sauc bigmodel 流式 ASR WebSocket 客户端。

    使用方式：
        async with VolcASRStream(on_result callback) as asr:
            await asr.send_audio(audio_chunk)
            ...
        # 结束时自动获取最终结果
    """

    def __init__(
        self,
        on_interim: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.cfg = _get_asr_config()
        self.on_interim = on_interim
        self.on_final = on_final
        self.on_error = on_error
        self.ws = None
        self._final_text = ""
        self._connected = False
        self._request_id = str(uuid.uuid4())

    async def connect(self) -> bool:
        """连接火山 ASR WebSocket"""
        if not is_asr_available():
            if self.on_error:
                self.on_error("语音服务未配置（缺少 API Key 或 Resource ID）")
            return False

        # 构建请求头（火山新版鉴权）
        headers = {
            "X-Api-Key": self.cfg["api_key"],
            "X-Api-Resource-Id": self.cfg["resource_id"],
            "X-Api-Request-Id": self._request_id,
        }

        try:
            # websockets 15.x 用 additional_headers，旧版用 extra_headers
            # 优先尝试新版参数，TypeError 则回退旧版
            try:
                self.ws = await websockets.connect(
                    VOLC_ASR_URL,
                    additional_headers=headers,
                    ping_interval=None,
                    ping_timeout=None,
                )
            except TypeError:
                # 旧版 websockets（< 15.0）用 extra_headers
                self.ws = await websockets.connect(
                    VOLC_ASR_URL,
                    extra_headers=headers,
                    ping_interval=None,
                    ping_timeout=None,
                )
            
            self._connected = True

            # 发送 full client request（第一帧，带配置）
            init_frame = _build_full_client_request()
            await self.ws.send(init_frame)

            return True
        except Exception as e:
            if self.on_error:
                self.on_error(f"ASR WebSocket 连接失败: {e}")
            return False

    async def send_audio(self, audio_chunk: bytes, is_last: bool = False) -> bool:
        """
        发送音频分片（PCM 16kHz 单声道 int16）。

        Args:
            audio_chunk: PCM 音频分片
            is_last: 是否最后一包
        """
        if not self._connected or not self.ws:
            return False

        try:
            frame = _build_audio_frame(audio_chunk, is_last=is_last)
            await self.ws.send(frame)
            return True
        except Exception as e:
            if self.on_error:
                self.on_error(f"发送音频失败: {e}")
            return False

    async def receive_loop(self):
        """接收识别结果循环（后台运行）"""
        if not self.ws:
            return

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue

                # 解析 server response 帧
                if isinstance(msg, bytes):
                    result = _parse_server_response(msg)
                else:
                    # 文本帧（可能是错误）
                    try:
                        result = json.loads(msg)
                    except:
                        result = {"error": msg}

                if result.get("error"):
                    if self.on_error:
                        # Bug2 Fix: 回调可能是 async 协程，需要 await
                        await self._call_callback(self.on_error, result["error"])
                    continue

                text = result.get("text", "")
                is_final = result.get("is_final", False)

                if text:
                    if is_final:
                        self._final_text = text
                        if self.on_final:
                            await self._call_callback(self.on_final, text)
                    else:
                        # 中间结果
                        if self.on_interim:
                            await self._call_callback(self.on_interim, text)

        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            if self.on_error:
                await self._call_callback(self.on_error, f"接收结果失败: {e}")

    async def _call_callback(self, callback, *args):
        """
        调用回调函数（支持同步、异步、返回协程的同步lambda）。
        Bug2 Fix: lambda 返回协程时，iscoroutinefunction(lambda)=False，
        但返回值是协程，需要 await。
        """
        if callback is None:
            return
        try:
            result = callback(*args)
            # 关键：检查返回值是否是协程（lambda 返回的协程也要 await）
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass  # 回调失败忽略

    async def close(self):
        """关闭连接并发送结束信号"""
        if self.ws:
            try:
                # 发送最后一包（负包，flags=0b0010）
                # 空音频数据，只指示结束
                await self.send_audio(b"", is_last=True)

                # 等待最终结果
                await asyncio.sleep(0.5)

                await self.ws.close()
            except Exception:
                pass
        self._connected = False

    def get_final_text(self) -> str:
        """获取最终识别文本"""
        return self._final_text


async def transcribe_stream_async(
    audio_chunks: list,
    on_interim: Optional[Callable[[str], None]] = None,
    on_final: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> str:
    """
    流式语音识别（异步版本）。

    Args:
        audio_chunks: PCM 音频分片列表
        on_interim: 中间结果回调
        on_final: 最终结果回调
        on_error: 错误回调

    Returns:
        最终识别文本
    """
    if not is_asr_available():
        if on_error:
            on_error("语音服务未配置")
        return ""

    asr = VolcASRStream(on_interim=on_interim, on_final=on_final, on_error=on_error)

    if not await asr.connect():
        return ""

    # 启动接收循环（后台任务）
    receive_task = asyncio.create_task(asr.receive_loop())

    try:
        # 发送音频分片
        for i, chunk in enumerate(audio_chunks):
            is_last = (i == len(audio_chunks) - 1)
            await asr.send_audio(chunk, is_last=is_last)
            await asyncio.sleep(0.02)  # 小延迟

        # 等待接收任务结束
        await asyncio.wait_for(receive_task, timeout=5.0)
    except Exception as e:
        if on_error:
            on_error(f"识别失败: {e}")
    finally:
        if not receive_task.done():
            receive_task.cancel()

    return asr.get_final_text()


def transcribe_stream(
    audio_chunks: list,
    on_interim: Optional[Callable[[str], None]] = None,
    on_final: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> str:
    """
    流式语音识别（同步包装）。
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        transcribe_stream_async(audio_chunks, on_interim, on_final, on_error)
    )


# ============== 最小连通测试 ==============

async def _test_connection():
    """
    最小连通测试：发送 full client request + 静音 PCM，验证能收到 server response。
    """
    if not is_asr_available():
        print("ASR 未配置，跳过测试")
        return False

    print("=== 火山 ASR 连通测试 ===")
    print(f"URL: {VOLC_ASR_URL}")
    print(f"Resource ID: {_get_asr_config()['resource_id']}")

    cfg = _get_asr_config()
    headers = {
        "X-Api-Key": cfg["api_key"],
        "X-Api-Resource-Id": cfg["resource_id"],
        "X-Api-Request-Id": str(uuid.uuid4()),
    }

    try:
        # websockets 15.x 用 additional_headers，旧版用 extra_headers
        try:
            ws = await websockets.connect(
                VOLC_ASR_URL,
                additional_headers=headers,
                ping_interval=None,
                ping_timeout=None,
            )
        except TypeError:
            ws = await websockets.connect(
                VOLC_ASR_URL,
                extra_headers=headers,
                ping_interval=None,
                ping_timeout=None,
            )
        print("✓ WebSocket 连接成功")

        # 发送 full client request
        init_frame = _build_full_client_request()
        print(f"发送 full client request: header={init_frame[:4].hex()}, payload_size={len(init_frame)-8}")
        await ws.send(init_frame)

        # 发送一段静音 PCM（1秒，16kHz，int16）
        silence_pcm = b"\x00\x00" * 16000  # 32000 bytes
        audio_frame = _build_audio_frame(silence_pcm, is_last=True)
        print(f"发送 audio frame (静音+负包): header={audio_frame[:4].hex()}")
        await ws.send(audio_frame)

        # 接收 server response
        msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
        if isinstance(msg, bytes):
            print(f"收到 binary frame: len={len(msg)}, header={msg[:4].hex()}")
            result = _parse_server_response(msg)
            print(f"解析结果: {result}")
        else:
            print(f"收到 text frame: {msg}")

        await ws.close()
        print("✓ 测试完成")
        return True

    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_asr_connection():
    """同步包装的连通测试"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(_test_connection())


if __name__ == "__main__":
    # 直接运行此文件执行连通测试
    test_asr_connection()