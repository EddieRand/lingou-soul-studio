"""
Volcengine TTS v2 WebSocket Bidirectional Protocol Implementation (Official Version).
"""

import struct
import uuid
from enum import IntEnum
from typing import Optional


class MsgType(IntEnum):
    FullClientRequest = 0b1
    FullServerResponse = 0b1001
    AudioOnlyServer = 0b1011
    Error = 0b1111


class MsgTypeFlagBits(IntEnum):
    WithEvent = 0b100


class EventType(IntEnum):
    None_ = 0
    StartConnection = 1
    FinishConnection = 2
    ConnectionStarted = 50
    ConnectionFailed = 51
    ConnectionFinished = 52
    StartSession = 100
    CancelSession = 101
    FinishSession = 102
    SessionStarted = 150
    SessionCanceled = 151
    SessionFinished = 152
    SessionFailed = 153
    UsageResponse = 154
    TaskRequest = 200
    TTSSentenceStart = 350
    TTSSentenceEnd = 351
    TTSResponse = 352
    TTSEnded = 359
    TTSSubtitle = 364


class Message:
    def __init__(
        self,
        type: MsgType,
        flag: int = 0,
        event: Optional[EventType] = None,
        session_id: Optional[str] = None,
        payload: bytes = b"",
    ):
        self.type = type
        self.flag = flag
        self.event = event
        self.session_id = session_id
        self.payload = payload

    def marshal(self) -> bytes:
        """Serialize message to bytes."""
        version = (1 << 4) | 1
        type_flag = (self.type.value << 4) | (self.flag & 0x0F)
        payload_type = (1 << 4) | 0
        reserved = 0

        header = struct.pack(">BBBB", version, type_flag, payload_type, reserved)
        body = b""

        if self.flag & MsgTypeFlagBits.WithEvent.value:
            body += struct.pack(">I", self.event.value)

        if self.session_id:
            session_bytes = self.session_id.encode("utf-8")
            body += struct.pack(">I", len(session_bytes))
            body += session_bytes

        body += struct.pack(">I", len(self.payload))
        body += self.payload

        return header + body

    @classmethod
    def unmarshal(cls, data: bytes) -> "Message":
        """Deserialize bytes to Message."""
        if len(data) < 4:
            raise ValueError("Invalid message: too short")

        version, type_flag, payload_type, reserved = struct.unpack(">BBBB", data[:4])
        
        # MsgType 解析容错
        msg_type_raw = (type_flag >> 4) & 0x0F
        try:
            msg_type = MsgType(msg_type_raw)
        except ValueError:
            msg_type = msg_type_raw
        
        flag = type_flag & 0x0F

        offset = 4
        event = None
        session_id = None

        if flag & MsgTypeFlagBits.WithEvent.value:
            if offset + 4 > len(data):
                raise ValueError("Invalid message: missing event")
            event_raw = struct.unpack(">I", data[offset:offset+4])[0]
            # EventType 解析容错
            try:
                event = EventType(event_raw)
            except ValueError:
                event = event_raw  # 未定义事件，保留原值不报错
            offset += 4

        if msg_type not in (MsgType.FullClientRequest, MsgType.FullServerResponse):
            # 容错解析 session_id：数据不足时跳过，不报错
            if offset + 4 <= len(data):
                session_id_len = struct.unpack(">I", data[offset:offset+4])[0]
                offset += 4
                if offset + session_id_len <= len(data):
                    session_id = data[offset:offset+session_id_len].decode("utf-8")
                    offset += session_id_len
                else:
                    session_id = ""
            else:
                session_id = ""

        if offset + 4 > len(data):
            raise ValueError("Invalid message: missing payload length")
        payload_len = struct.unpack(">I", data[offset:offset+4])[0]
        offset += 4
        if offset + payload_len > len(data):
            raise ValueError("Invalid message: missing payload")
        payload = data[offset:offset+payload_len]

        return cls(
            type=msg_type,
            flag=flag,
            event=event,
            session_id=session_id,
            payload=payload,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "Message":
        """Alias for unmarshal."""
        return cls.unmarshal(data)


async def receive_message(ws) -> Message:
    """Receive and parse a message from WebSocket."""
    data = await ws.recv()
    return Message.from_bytes(data)


async def wait_for_event(ws, msg_type: MsgType, event_type: EventType) -> Message:
    """Wait for a specific event type."""
    while True:
        msg = await receive_message(ws)
        if msg.type == msg_type and msg.event == event_type:
            return msg


async def start_connection(ws) -> None:
    """Send StartConnection message."""
    msg = Message(
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent.value,
        event=EventType.StartConnection,
        payload=b'{"event":"StartConnection"}',
    )
    await ws.send(msg.marshal())


async def start_session(ws, payload: bytes, session_id: str) -> None:
    """Send StartSession message."""
    msg = Message(
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent.value,
        event=EventType.StartSession,
        session_id=session_id,
        payload=payload,
    )
    await ws.send(msg.marshal())


async def task_request(ws, payload: bytes, session_id: str) -> None:
    """Send TaskRequest message."""
    msg = Message(
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent.value,
        event=EventType.TaskRequest,
        session_id=session_id,
        payload=payload,
    )
    await ws.send(msg.marshal())


async def finish_session(ws, session_id: str) -> None:
    """Send FinishSession message."""
    msg = Message(
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent.value,
        event=EventType.FinishSession,
        session_id=session_id,
        payload=b'{"event":"FinishSession"}',
    )
    await ws.send(msg.marshal())


async def finish_connection(ws) -> None:
    """Send FinishConnection message."""
    msg = Message(
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent.value,
        event=EventType.FinishConnection,
        payload=b'{"event":"FinishConnection"}',
    )
    await ws.send(msg.marshal())


def generate_connect_id() -> str:
    """Generate a unique X-Api-Connect-Id."""
    return str(uuid.uuid4())


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())
