"""Storage-backed active-credential and playback lifecycle fault probes."""
import asyncio
import json
from pathlib import Path
import os
import pty
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

VALIDATION_OUT = os.getenv(
    "LINGOU_VALIDATION_OUT",
    str(Path(__file__).resolve().parent),
)
import probe_api as q
from hardware_adapter.portable_voice_client import SoundDeviceAudioBackend

OUT = Path(VALIDATION_OUT)
OUT.mkdir(parents=True, exist_ok=True)
rows = []


def record(case, name, passed, data):
    rows.append({"case":case,"variant":name,"passed":passed,"observation":data})
    (OUT / "session-results.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(case,name,"PASS" if passed else "FAIL",flush=True)


def active_auth():
    for action in ("revoke", "rotate", "unbind"):
        a=q.fixture()
        state={"upstream_frames":0}
        class Upstream:
            async def send(self, frame):
                state["upstream_frames"]+=1
                await state["session"]._send_ws({"type":"qa_upstream_observation","frames":state["upstream_frames"]})
            async def close(self): pass
        async def connect(session):
            state["session"]=session
            session.volc_ws=Upstream()
            session._connected=True
            await session._send_ws({"type":"qa_upstream_ready"})
        with patch.object(q.asr,"is_asr_available",return_value=True), \
             patch.object(q.asr.VoiceCallSession,"_start_volc_connection_background",new=connect):
            with q.http.websocket_connect("/api/asr/device-stream",
                subprotocols=[q.asr.DEVICE_WS_PROTOCOL],
                headers={"Authorization":"Device "+a["device"]}) as ws:
                ws.receive_json()
                ws.receive_json()
                ws.send_bytes(b"\0"*640)
                ws.receive_json()
                if action=="revoke":
                    q.http.post(f"/api/bases/{a['base']}/device-credential/revoke",headers=a["headers"])
                elif action=="rotate":
                    q.store.rotate_production_device_credential(a["base"],device_credential=a["base"]+"."+"n"*43)
                else:
                    q.http.post(f"/api/bases/{a['base']}/unbind",headers=a["headers"])
                valid_now=q.device_auth.authenticate_device_credential(a["device"],required_scope="voice:stream") is not None
                ws.send_bytes(b"\1\0"*320)
                observation=ws.receive()
                count=state["upstream_frames"]
                record("DEVAUTH-05",action, not valid_now and count==1,
                       {"credential_currently_valid":valid_now,"upstream_frames_before":1,"upstream_frames_after":count,
                        "existing_ws_still_open":observation["type"]=="websocket.send",
                        "scope":"real authenticated WS and real send_audio; fake ASR transport; no paid calls"})


class WS:
    def __init__(self): self.messages=[]
    async def send_json(self,x): self.messages.append(x)
    async def send_bytes(self,b): pass
    async def close(self,**kw): pass


async def receipt_order():
    for variant in ("wrong identities","completed before started","completed then failed"):
        ws=WS()
        session=q.asr.VoiceCallSession(ws,"BASE-RECEIPT","OWNER-RECEIPT")
        q.asr.voice_session_registry.replace(session)
        turn=await session._begin_turn("fixture")
        await session._send_turn_audio(turn,b"\1\0"*200)
        aid=next(iter(turn.audio_ids))
        turn.audio_stream_complete=True
        msg={"type":"audio_playback","session_id":session.session_id,"turn_id":turn.turn_id,
             "audio_id":aid,"stage":"playback_completed"}
        if variant=="wrong identities":
            for key in ("session_id","turn_id","audio_id"):
                await session.handle_client_message({**msg,key:"WRONG"})
            passed=not turn.playback_done.is_set()
        elif variant=="completed before started":
            await session.handle_client_message(msg)
            passed=not turn.playback_done.is_set()
        else:
            for stage in ("decoded","playback_started","playback_completed","playback_failed"):
                await session.handle_client_message({**msg,"stage":stage})
            passed=not (turn.audio_failed and "playback_completed" in turn.timestamps)
        record("PROTOCOL-06",variant,passed,
               {"playback_done":turn.playback_done.is_set(),"audio_failed":turn.audio_failed,
                "marks":list(turn.timestamps),"terminal_ids":len(turn.audio_terminal_ids)})
        await session.close_volc()
        q.asr.voice_session_registry.discard(session)


async def output_timeout():
    ws=WS()
    session=q.asr.VoiceCallSession(ws,"BASE-TIMEOUT","OWNER-TIMEOUT",client_kind="device",output_audio_format="pcm")
    q.asr.voice_session_registry.replace(session)
    session._reconnect_for_next_turn=AsyncMock()
    def generate(base,text,**kw):
        kw["text_sink"]("fixture")
        kw["audio_sink"](b"\0"*200)
        return {"reply":"fixture","brain_mode":"online","tts_engine":"fixture"}
    start=time.monotonic()
    with patch.object(q.asr,"process_text_input",side_effect=generate):
        await session._finalize_text("fixture")
        turn=session._active_turn
        await asyncio.wait_for(asyncio.shield(turn.task),35)
    metrics=[m for m in ws.messages if m.get("type")=="turn_metrics"]
    record("OUTPUT-05","no receipt 30-second timeout",bool(metrics) and metrics[-1]["status"]=="audio_failed",
           {"elapsed_seconds":round(time.monotonic()-start,2),"metrics":metrics})
    await session.close_volc()
    q.asr.voice_session_registry.discard(session)


async def partial_start():
    input_state={"created":False,"closed":False}
    class Input:
        def __init__(self,**kw): input_state["created"]=True
        def close(self): input_state["closed"]=True
        def stop(self): pass
    def output(**kw): raise RuntimeError("fixture output init failed")
    fake=SimpleNamespace(RawInputStream=Input,RawOutputStream=output)
    from hardware_adapter.portable_voice_client import PortableVoiceClient
    audio=SoundDeviceAudioBackend()
    c=PortableVoiceClient(server_url="ws://127.0.0.1:1",device_credential="BASE.x",audio=audio)
    try:
        with patch.object(audio,"_sounddevice",return_value=fake):
            await c.run()
    except RuntimeError as exc:
        record("CARRIER-07","partial input creation then output init fails",input_state["closed"],
               {**input_state,"error":str(exc)})
    finally:
        audio._input_stream=None


def keyboard_shutdown():
    script=r'''
import asyncio, signal, sys
sys.path.insert(0, sys.argv[1])
from hardware_adapter.portable_voice_client import PortableVoiceClient,_keyboard_control
class Audio:
 async def start(self): pass
 async def stop(self): pass
 async def stop_playback(self): pass
 def set_input_muted(self,x): pass
async def main():
 c=PortableVoiceClient(server_url="ws://127.0.0.1:1",device_credential="BASE.x",audio=Audio())
 asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,c.request_stop)
 async def conn(): await c.stop_event.wait()
 c._run_connection=conn
 key=asyncio.create_task(_keyboard_control(c))
 print("READY",flush=True)
 await c.run()
 key.cancel()
 await asyncio.gather(key,return_exceptions=True)
 print("COROUTINES_FINISHED",flush=True)
asyncio.run(main())
print("PROCESS_FINISHED",flush=True)
'''
    master,slave=pty.openpty()
    proc=subprocess.Popen([sys.executable,"-B","-c",script,str(q.ROOT)],
                          stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        ready=proc.stdout.readline().strip()
        time.sleep(0.1)
        proc.terminate()
        try:
            output,_=proc.communicate(timeout=2)
            exited=True
        except subprocess.TimeoutExpired:
            proc.kill()
            output,_=proc.communicate(timeout=2)
            exited=False
        record("CARRIER-07","PTY keyboard + SIGTERM",exited,{"ready":ready,"exited_within_2s":exited,"output":output})
    finally:
        if proc.poll() is None: proc.kill();proc.wait()
        os.close(master);os.close(slave)


def run():
    with q.http:
        active_auth()
    asyncio.run(receipt_order())
    asyncio.run(partial_start())
    keyboard_shutdown()
    asyncio.run(output_timeout())
    q.temp.cleanup()


if __name__=="__main__":
    run()
