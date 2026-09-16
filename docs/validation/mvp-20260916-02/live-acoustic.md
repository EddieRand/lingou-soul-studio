# Portable carrier live acoustic rerun

All runs used a temporary owner, base, figure, device credential and data
directory. The prompt was played through the system speaker and recaptured by
the system microphone; no prompt PCM was injected into the WebSocket.

## Final-code result

- Explicit devices: input `0`, output `1`.
- Provider readiness: waited for backend `status=ready` before prompt playback.
- ASR text: `好了吗`
- Reply: `已经准备好啦，你是想继续聊聊喜欢的蓝色相关的事，还是有别的想分享的呀？`
- Playback completed with original `audio_id`.
- Exactly one turn with `session_id` and `turn_id` was persisted.
- Client and temporary uvicorn process exited normally.

## Repair-run observations

- Two default-device runs completed end to end and exited normally. Their ASR
  texts were `皮` and `APP 安全`; both produced replies, completed playback and
  persisted one turn.
- One explicit-device run completed after reconnecting when the client
  incorrectly treated runtime `status=reconnected` as an audio negotiation
  status. The client now distinguishes initial and runtime status messages.
- One explicit-device run reached the 75-second acoustic recognition timeout.
  Cleanup still completed normally, confirming the prior shutdown timeout was
  fixed.
- The final explicit-device run above passed after adding the provider-ready
  handshake.

The automated acoustic path is operational, but the varied recognition text
shows that it does not replace the three-round human speech requirement in
`CARRIER-05`.
