# Lingou DNESP32S3 reference firmware

This firmware is retained as a future-hardware reference. The adjusted step-11
MVP uses the portable Linux/macOS carrier described in
[`docs/portable-device-mvp.md`](../../docs/portable-device-mvp.md); final custom
hardware requires a separate hardware-engineering acceptance.

EV-03 moves board constants into
[`hal/dnesp32s3_board_profile.h`](hal/dnesp32s3_board_profile.h) and defines
the firmware-side port boundaries in
[`hal/lingou_hal_contract.h`](hal/lingou_hal_contract.h). EV-04 adds fixed
capture/playback slot pools and dedicated FreeRTOS audio tasks so WebSocket
callbacks never write I2S directly.

EV-05 adds an opt-in ESP-SR 2.4.6 acoustic front end in
[`hal/esp_sr_acoustic_frontend.h`](hal/esp_sr_acoustic_frontend.h). It combines
full-duplex low-cost AEC, WebRTC noise suppression and digital AGC. See
[`docs/acoustic-frontend.md`](../../docs/acoustic-frontend.md) for the signal
path and target acceptance matrix.

| Function | GPIO |
|---|---|
| WS2812B ring | 18 |
| FSR | 16 |
| INMP441 BCLK / WS / DIN | 5 / 7 / 4 |
| MAX98357A BCLK / LRC / DOUT | 6 / 15 / 17 |

The device connects directly to `WS(S) /api/asr/device-stream`; no browser,
serial bridge or development computer participates in a voice turn. The
backend derives the base, owner and active figure from the `Device` credential.
It then uses the same voice session, persona, recent history and confirmed
memory path as H5.

## Provisioning

For a new base, use `scripts/provision_base.py`. New credentials include
`events:write` and `voice:stream`.

For a base provisioned before device voice support, explicitly rotate its
credential:

```bash
cd services/companion-server
.venv/bin/python -B -m scripts.rotate_device_credential \
  --base-id BASE-DEVICE-001 \
  --data-dir /absolute/path/to/runtime-data
```

The old credential becomes invalid. The new credential is printed once.

Copy `device_config.example.h` to `device_config.h` and fill in Wi-Fi, server
and credential values. `device_config.h` is ignored by Git. For production WSS,
set `LINGOU_SERVER_USE_TLS` to `1` and provide the server CA certificate;
firmware refuses TLS without a CA.

## Build

Required versions used by the step-11 verification:

- ESP32 Arduino core `3.3.10`
- Adafruit NeoPixel `1.15.5`
- WebSockets `2.7.2`
- ArduinoJson `7.4.3`

```bash
ARDUINO_CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
"$ARDUINO_CLI" lib install "WebSockets@2.7.2"
"$ARDUINO_CLI" lib install "ArduinoJson@7.4.3"
"$ARDUINO_CLI" compile \
  --fqbn esp32:esp32:esp32s3 \
  firmware/lingou_device_v1
```

The checked-in configuration keeps ESP-SR disabled. An EV-05 target build must
set `LINGOU_ENABLE_ESP_SR_AFE=1` in the ignored `device_config.h` and use the
N16R8 profile:

```bash
"$ARDUINO_CLI" compile \
  --fqbn esp32:esp32:esp32s3:FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,PSRAM=opi \
  firmware/lingou_device_v1
```

Select the actual DNESP32S3 serial port when uploading. Do not upload while
the board is absent or while another serial monitor owns the port.

## Runtime behavior

- Startup flashes red exactly three times, then attempts Wi-Fi and WSS.
- Microphone sends 20 ms frames of 16 kHz, signed 16-bit little-endian PCM.
- The capture task writes to a 12-frame bounded queue. If the network consumer
  falls behind, it drops the oldest unsent frame rather than blocking I2S.
- Backend returns 24 kHz, signed 16-bit little-endian mono PCM in frames no
  larger than 4096 bytes.
- The WebSocket callback copies downlink data into an eight-slot jitter buffer.
  A dedicated task duplicates mono samples to stereo and uses finite 15 ms I2S
  writes. Queue saturation fails the active audio instead of blocking control.
- Playback receipts are emitted by the control loop from playback-task events;
  `playback_completed` is suppressed after cancellation or generation change.
- A heavy FSR press while the character is speaking stops I2S output and
  cancels the original server turn. The local abort path invalidates the old
  generation and clears DMA before sending network receipts, with a 40 ms
  software lock timeout.
- With ESP-SR disabled, playback mutes the microphone and the heavy press is
  the reliable interruption mechanism.
- With ESP-SR enabled and initialized, microphone capture remains active during
  playback. The 24 kHz speaker PCM is converted to a delayed 16 kHz digital
  reference for AEC before NS and AGC process the uplink.
- Wi-Fi, server and audio failures use a red/amber ring and local two-tone
  prompt. Recovery reconnects to a fresh voice session; queued replies are not
  replayed.
- When idle, the I2S DMA buffer is zeroed so MAX98357A output remains low.
- Every 10 seconds serial output reports queue depth, overflow, dropped-frame,
  underrun and maximum queue-wait counters under the `AUDIO_PIPELINE` prefix.
- The same interval reports acoustic profile, frame, clipping, reference
  overflow/underflow and processing-failure counters.

The 40 ms interruption value is an implementation bound, not measured
speaker-stop latency. `VALIDATED_AEC` remains false until target-board raw,
reference and processed recordings pass the EV-05 acceptance thresholds.

## Protocol

WebSocket request:

```http
GET /api/asr/device-stream
Authorization: Device BASE-DEVICE-001.<secret>
Sec-WebSocket-Protocol: lingou.device.voice.v1
```

Binary device-to-server frames are raw microphone PCM. Server-to-device audio
uses an `audio_chunk` JSON descriptor immediately followed by one binary PCM
frame. Every descriptor includes `session_id`, `turn_id`, `audio_id`,
`chunk_index`, `chunk_count`, format and sample-rate fields.

The device sends:

```json
{"type":"audio_playback","stage":"playback_completed","session_id":"...","turn_id":"...","audio_id":"..."}
```

Explicit interruption sends:

```json
{"type":"cancel_turn","session_id":"..."}
```

The same physical base permits only one live H5 or device voice connection.
The newer connection replaces the older one with close code `4410`. When H5
replaces the device, firmware pauses automatic reconnect so it cannot steal the
session back; a deliberate heavy press resumes device voice after H5 is done.
