# LINGOU Acoustic Front End

## Decision

EV-05 uses the direct DSP APIs shipped in Espressif ESP-SR 2.4.6:

- `AEC_MODE_FD_LOW_COST` with one microphone and one playback reference;
- aggressive nonlinear echo suppression;
- 10 ms WebRTC noise suppression in medium mode;
- WebRTC digital AGC with limiter enabled.

This keeps the acoustic implementation inside the hardware adapter and does
not change the server dialogue, memory, persona, ownership or turn state
machines. The implementation is
[`esp_sr_acoustic_frontend.h`](../firmware/lingou_device_v1/hal/esp_sr_acoustic_frontend.h).

Espressif documents `AEC_MODE_FD_LOW_COST` as the recommended balance for
full-duplex dialogue. It requires signed 16-bit, 16 kHz microphone and playback
reference input. See:

- <https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/acoustic_echo_cancellation/README.html>
- <https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html>
- <https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/Espressif_Microphone_Design_Guidelines.html>

## Signal Path

```text
INMP441 32-bit I2S
  -> signed 16-bit conversion
  -> versioned digital gain and clipping guard
  -> ESP-SR full-duplex AEC
  -> WebRTC NS
  -> WebRTC digital AGC + limiter
  -> 20 ms / 16 kHz / mono capture queue
  -> lingou.device.voice.v1

24 kHz mono playback
  -> bounded playback queue
  -> I2S speaker write
  -> stateful 24 kHz to 16 kHz reference conversion
  -> configurable reference delay
  -> AEC reference ring
```

The reference converter consumes every three 24 kHz samples and emits two
16 kHz samples. Its state is preserved across playback blocks. Reference data
is tagged with the EV-04 playback generation; cancelled or replaced generations
cannot enter the new AEC stream.

The configured delay is inserted when the first PCM block is accepted by I2S,
not when the earlier `speaking=start` control message arrives. This prevents
TTS generation time from consuming the delay before audible playback begins.

The current MAX98357A wiring has no separately sampled PA output. The reference
therefore comes from the digital PCM accepted by I2S, not from the amplifier
output. Espressif recommends taking the reference as close to the speaker path
as possible. Any nonlinear amplifier or speaker distortion remains a physical
validation risk.

## Versioned Profile

Profile: `esp-sr-2.4.6-fd-lowcost-v1`

| Setting | Value |
|---|---:|
| AEC mode | `AEC_MODE_FD_LOW_COST` |
| AEC filter length | 4 |
| NLP | `AEC_NLP_LEVEL_AGGR` |
| Reference delay | 60 ms |
| NS mode | 1, medium |
| AGC mode | `AGC_MODE_2` |
| AGC gain | 9 dB |
| AGC target | -3 dBFS |
| Microphone pre-gain | 1.0 (`Q8=256`) |
| Software clip limit | 30000 |
| Input/output | 16 kHz mono s16le |

The 60 ms reference delay is an initial calibration value, not a measured
property. It must be swept on the assembled enclosure.

## Enablement Gate

The checked-in default is:

```c
#define LINGOU_ENABLE_ESP_SR_AFE 0
```

This preserves the validated half-duplex path. To test EV-05, set it to `1` in
the ignored `device_config.h`. The firmware then requires PSRAM and fails
initialization with `psram_required` instead of silently running a partially
configured full-duplex path.

Use the 16 MB Flash and 8 MB OPI PSRAM target profile:

```bash
ARDUINO_CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
"$ARDUINO_CLI" compile \
  --fqbn esp32:esp32:esp32s3:FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,PSRAM=opi \
  firmware/lingou_device_v1
```

The direct AEC/NS/AGC APIs do not require WakeNet or MultiNet model loading.
Do not advertise `aec=true` in protocol capabilities until target acoustic
acceptance passes and `VALIDATED_AEC` is changed deliberately.

## Telemetry

`ACOUSTIC_FRONTEND` serial records include:

- profile, requested/active state and AEC frame size;
- input/output frame and AEC block counts;
- clipped samples;
- reference overflow, underflow and maximum depth;
- processed-output overflow and processing failures.

These counters diagnose transport and scheduling behavior. They do not prove
echo cancellation quality.

## Target Acceptance Matrix

Use fixed geometry, enclosure, volume, firmware commit and profile for every
run. Raw microphone, processed microphone and reference WAVs must be retained.

| Scenario | Initial threshold |
|---|---|
| Silence | processed RMS <= -45 dBFS; clipping <= 0.1% |
| Near speech | -30 to -8 dBFS; CER <= 10%; clipping <= 0.1% |
| Far speech | -36 to -8 dBFS; CER <= 20%; clipping <= 0.1% |
| Stationary noise | processed attenuation >= 6 dB; clipping <= 0.1% |
| Echo only | processed attenuation >= 12 dB; clipping <= 0.1% |
| Double talk | CER <= 15%; clipping <= 0.1% |

These thresholds are fixed before target testing. If the enclosure cannot meet
them, retain the failed evidence and revise the hardware or profile in a new
version instead of weakening this record.

Archive and evaluate a capture with:

```bash
python -B services/companion-server/scripts/collect_ev05_acoustic_baseline.py \
  --scenario echo_only \
  --raw-wav /path/to/raw-microphone.wav \
  --processed-wav /path/to/processed-microphone.wav \
  --reference-wav /path/to/playback-reference.wav \
  --hardware-id DNESP32S3-01 \
  --firmware-commit "$(git rev-parse HEAD)" \
  --output-dir docs/validation/ev05-acoustic-YYYYMMDD \
  --confirm-target-capture
```

The collector verifies 16 kHz mono s16le WAV format, copies the recordings,
stores SHA-256 hashes, records the exact profile and evaluates the scenario
against the fixed threshold.
