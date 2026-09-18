# EV-05 Acoustic Front End

Date: 2026-09-17

Branch: `feat/hardware-voice-adapter`

Base commit: `7f5e7ed641c529dffc04eb22b820a5586e12987c`

## Scope

EV-05 adds an opt-in acoustic front end to the hardware adapter without
changing dialogue, memory, persona, ownership, session, turn or playback
receipt semantics.

The implementation is complete enough to compile and run on an N16R8
ESP32-S3 target. No target board was connected, so this record separates
implementation evidence from acoustic acceptance.

## Selected Implementation

Provider: Espressif ESP-SR 2.4.6, already shipped by ESP32 Arduino core 3.3.10.

Profile: `esp-sr-2.4.6-fd-lowcost-v1`

- AEC: `AEC_MODE_FD_LOW_COST`, one microphone, one reference, filter length 4;
- residual echo suppression: `AEC_NLP_LEVEL_AGGR`;
- noise suppression: 10 ms WebRTC NS, medium mode;
- gain control: digital WebRTC AGC, 9 dB gain, -3 dBFS target and limiter;
- input: INMP441 16 kHz mono signed 16-bit after I2S conversion;
- reference: accepted 24 kHz playback PCM converted statefully to 16 kHz;
- initial reference delay: 60 ms;
- capture remains active during playback only when the complete front end
  initializes successfully.

The current MAX98357A path exposes no sampled amplifier output. The AEC
reference is therefore the digital pre-amplifier signal. Amplifier and speaker
nonlinearity remain target risks.

## Safety Gates

- `LINGOU_ENABLE_ESP_SR_AFE` defaults to `0`.
- Enabled initialization requires PSRAM and fails with `psram_required` rather
  than silently enabling partial full-duplex capture.
- AEC buffers are 16-byte aligned as required by ESP-SR.
- Playback reference data is tagged with the EV-04 playback generation.
- Cancel, disconnect and session replacement clear the reference, processing
  buffers and pending microphone frames.
- `VALIDATED_AEC` remains `false`; protocol capabilities must not advertise
  validated AEC.

## Versioned Tuning

The checked-in C++ and Python contracts agree on:

| Setting | Value |
|---|---:|
| Profile | `esp-sr-2.4.6-fd-lowcost-v1` |
| AEC filter length | 4 |
| Reference delay | 60 ms |
| Microphone gain | Q8 256 / 1.0 |
| Clip limit | 30000 |
| NS mode | 1 |
| AGC gain | 9 dB |
| AGC target | -3 dBFS |

Changing any of these for product use requires a new profile version and new
evidence.

## Host And Contract Evidence

```bash
python3 -B -m unittest discover -s hardware_adapter/tests -v
```

Result: 70 passed, 0 failed.

The six EV-05-specific tests cover:

- profile bounds and version;
- 24 kHz to 16 kHz reference conversion across block boundaries;
- gain and clipping behavior;
- ESP-SR mode, PSRAM gate, 16-byte alignment and opt-in policy;
- physical-evidence collector archiving and threshold evaluation;
- Chinese character error rate.

```bash
cd services/companion-server
.venv/bin/python -B tests/test_device_voice.py
```

Result: 13 passed, 0 failed.

## Firmware Build Evidence

Default half-duplex compatibility build:

```bash
arduino-cli compile \
  --fqbn esp32:esp32:esp32s3 \
  firmware/lingou_device_v1
```

Result:

- program storage: 1,117,545 / 1,310,720 bytes (85%);
- global dynamic memory: 95,436 / 327,680 bytes (29%);
- remaining for local variables: 232,244 bytes.

ESP-SR-enabled N16R8 build:

```bash
arduino-cli compile \
  --fqbn esp32:esp32:esp32s3:FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,PSRAM=opi \
  firmware/lingou_device_v1
```

The ignored `device_config.h` used only placeholder network values and the
checked-in EV-05 tuning values.

Result:

- program storage: 1,206,175 / 3,145,728 bytes (38%);
- global dynamic memory: 116,072 / 327,680 bytes (35%);
- remaining for local variables: 211,608 bytes.

Linker values do not include runtime AEC/NS/AGC allocations and do not prove
that the physical module has 8 MB usable PSRAM.

`git diff --check` also passed.

## Evidence Collector

[`collect_ev05_acoustic_baseline.py`](../../../services/companion-server/scripts/collect_ev05_acoustic_baseline.py)
requires raw and processed 16 kHz mono s16le WAVs, and accepts an optional
playback reference WAV. It:

- refuses target evidence without `--confirm-target-capture`;
- copies recordings without modifying them;
- records SHA-256, hardware ID, firmware commit and exact tuning;
- calculates RMS, peak, clipping, attenuation and optional character error
  rate;
- evaluates the fixed thresholds in
  [`acoustic-frontend.md`](../../acoustic-frontend.md).

The automated collector test uses synthetic tones only to verify the tool. It
is not acoustic evidence.

## Missing Target Evidence

No target recordings or serial resource data exist yet. All of the following
remain open:

- confirm actual module Flash and PSRAM capacity;
- record silence, near speech, far speech, stationary noise, echo-only and
  double-talk scenarios;
- sweep reference delay around the initial 60 ms value;
- verify no stable self-conversation during playback;
- verify user speech remains recognizable during playback;
- measure clipping, ERLE/attenuation, character error rate, stack high-water,
  free heap/PSRAM and CPU load;
- verify enclosure, microphone sealing, speaker isolation and maximum volume.

## Exit Decision

EV-05 integration, configuration, compile validation and evidence tooling are
complete. EV-05 remains open for physical acoustic acceptance. Do not set
`VALIDATED_AEC=true`, advertise `aec=true`, or begin EV-06 automatic voice
barge-in acceptance until the missing target evidence passes.
