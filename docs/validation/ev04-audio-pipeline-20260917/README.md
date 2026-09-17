# EV-04 Non-blocking Audio Pipeline

Date: 2026-09-17

Branch: `feat/hardware-voice-adapter`

Base commit: `7cfb8b94ff2482970d95ac8f858ab274a4920d5d`

## Scope

This task moves microphone capture and speaker output out of the Arduino
network/control loop while preserving `lingou.device.voice.v1`,
`session_id`/`turn_id`/`audio_id`, playback receipts, cancellation and late
generation isolation. It does not change dialogue, memory, persona, ownership
or server turn logic.

The user explicitly requested implementation before the EV-03 target resource
measurements and software `SW-GATE` were complete. This record therefore
separates host/static evidence from target-board acceptance.

## Implemented Pipeline

### Capture

- `lingou_capture` continuously reads exact 20 ms, 16 kHz mono microphone
  frames.
- Twelve fixed 640-byte slots bound queued capture data to 240 ms.
- When all slots are occupied, the producer reuses the oldest queued slot and
  increments overflow and dropped-frame counters.
- The network loop sends at most four queued frames per iteration and clears
  queued input while disconnected, replaced or playing output.

### Playback

- The WebSocket binary callback validates metadata, copies PCM into one of
  eight fixed 4096-byte slots and returns without writing I2S.
- `lingou_playback` owns mono-to-stereo conversion and all speaker writes.
- Every I2S write uses a 15 ms timeout. No `portMAX_DELAY` remains.
- Playback saturation rejects the new frame, fails active audio and clears the
  affected generation instead of blocking WebSocket control processing.
- Playback-task events return `decoded`, `playback_started` and
  `playback_completed` to the network loop. Events from old generations are
  discarded.

### Cancellation

- Local cancel, `stop_audio`, disconnect and session replacement increment
  `playbackGeneration` before clearing queued slots.
- The stop path clears speaker DMA before sending failure receipts.
- The software lock acquisition bound is 40 ms; the active I2S write timeout is
  15 ms.
- A stale task event cannot emit `playback_completed` after cancellation.

The 40 ms value is an implementation bound, not measured acoustic stop latency.

### Telemetry

Serial output under `AUDIO_PIPELINE` reports:

- current and maximum capture/playback queue depth;
- capture/playback overflow and dropped-frame counts;
- playback underrun count;
- playback-event drops;
- maximum capture/playback queue wait in milliseconds.

The portable carrier uses the same eight-frame rejection policy and exposes
playback overflow, dropped-frame, maximum depth and maximum wait counters.

## Automated Evidence

Commands:

```bash
python3 -B -m unittest discover -s hardware_adapter/tests -v
```

Result: 64 passed, 0 failed.

Coverage includes:

- fixed queue capacities and overflow policies;
- WebSocket callback isolation from I2S writes;
- finite I2S timeout and generation-first cancellation;
- slow playback cancellation without a late completed receipt;
- deterministic bounded-queue overflow cleanup;
- fake HAL reuse of the existing session/turn/audio contract.

```bash
cd services/companion-server
.venv/bin/python -B tests/test_device_voice.py
```

Result: 13 passed, 0 failed.

```bash
"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" \
  compile --fqbn esp32:esp32:esp32s3 firmware/lingou_device_v1
```

Result:

- program storage: 1,116,297 / 1,310,720 bytes (85%);
- global dynamic memory: 94,060 / 327,680 bytes (28%);
- remaining for local variables: 233,620 bytes.

`git diff --check` also passed.

## Missing Target Evidence

No ESP32 serial device was connected. The following remain unverified:

- actual `stop_audio`/FSR-to-silence latency at the speaker;
- sustained capture and playback queue depths under real Wi-Fi jitter;
- audible underruns, clipping and tail truncation;
- task stack high-water, heap/PSRAM and CPU use;
- reconnect and cancellation behavior on the physical I2S devices.

## Exit Decision

EV-04 code implementation and host/static validation are complete. EV-04
remains open for target-board acceptance; the implementation must not be
described as hardware-validated until the missing evidence above is recorded.
