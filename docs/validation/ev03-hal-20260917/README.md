# EV-03 Board HAL And Task Model

- Date: 2026-09-17
- Branch: `feat/hardware-voice-adapter`
- Base commit: `7cfb8b94ff2482970d95ac8f858ab274a4920d5d`
- Status: software-side HAL complete; target-board resource acceptance pending

## Completed

- Created the independent hardware adapter branch from the verified software
  freeze commit.
- Added board-neutral microphone, speaker, indicator, input, network, clock,
  secure-storage and resource-monitor ports.
- Added ordered startup, reverse shutdown and partial-start rollback.
- Added a five-task RTOS ownership model with bounded queues and stack budgets.
- Added a deterministic fake HAL.
- Reused the existing `PortableVoiceClient` session/turn/audio and playback
  receipt state machine through `HALAudioBackend`.
- Moved DNESP32S3 pins and audio formats into board-specific profiles.
- Added matching firmware-side C++ HAL interfaces.

Design details:
[`../../hardware-hal.md`](../../hardware-hal.md).

## Isolation

Generic HAL files do not import or reference:

- service dialogue or storage modules;
- owner or persona data;
- memory state;
- GPIO constants.

GPIO and board models only exist in the DNESP32S3 board profiles. The server
dialogue, memory, persona, identity and session/turn modules were not modified.

## Tests

HAL contract:

```bash
services/companion-server/.venv/bin/python -B \
  hardware_adapter/tests/test_hal_contract.py
```

Result: `11/11` passed.

Coverage includes:

- deterministic start and reverse stop order;
- cleanup of the component whose startup failed;
- cleanup attempts continuing after multiple stop errors;
- microphone, speaker, input, indicator, network and secure storage ports;
- fake resource snapshots marked as simulated;
- one bounded queue per task role;
- DNESP32S3 pinout and AEC status;
- consistency with `ws-pcm-s16le-v1`;
- fake HAL running the existing session/turn/audio playback-receipt contract;
- generic HAL independence from service core and GPIO.

Full hardware adapter suite and backend device-voice regression are recorded in
the final EV-03 run summary:

- hardware adapter, protocol, firmware and HAL contracts: `58/58` passed;
- backend device voice: `13/13` passed;
- Python compile checks: passed;
- `git diff --check`: passed.

## Firmware Compile

```bash
"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" \
  compile \
  --fqbn esp32:esp32:esp32s3 \
  firmware/lingou_device_v1
```

Result: passed after moving board constants into the profile.

Compile evidence:
[`firmware-compile-baseline.json`](firmware-compile-baseline.json).

## Resource Baseline

Contract and availability evidence:
[`hal-baseline.json`](hal-baseline.json).

The fake HAL contains simulated heap, PSRAM, stack and CPU values only to prove
the data shape. It has an explicit
`must_not_be_used_as_target_hardware_evidence=true` marker.

No ESP32 target serial device was connected:

- `/dev/cu.Bluetooth-Incoming-Port`
- `/dev/cu.debug-console`

Therefore these target values remain unmeasured:

- current/minimum free heap;
- free PSRAM;
- per-task stack high-water;
- per-task CPU usage.

The compile-time Flash and global-memory numbers are real linker output, but
they are not runtime resource evidence.

## Exit Decision

EV-03 implementation and host contracts are complete. The task remains open
for target-board resource measurements because its full acceptance criteria
require real heap, PSRAM, stack and CPU evidence.

The original EV-03 gate required all of the following before EV-04:

1. the target board is connected;
2. EV-03 runtime resource fields are populated;
3. the remaining `SW-GATE` human and H5 checks are resolved or explicitly
   re-prioritized.

On 2026-09-17 the user explicitly re-prioritized item 3 and requested EV-04
implementation without waiting for target hardware. This permits code and host
validation only. It does not convert the missing EV-03 target measurements into
a pass or authorize hardware release.
