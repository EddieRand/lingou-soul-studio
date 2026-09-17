# LINGOU Hardware HAL

## Purpose

The hardware abstraction layer keeps board drivers and RTOS scheduling outside
the existing device voice protocol and application core. It is implemented in:

- `hardware_adapter/hal`: executable host-side contracts and fake HAL;
- `firmware/lingou_device_v1/hal`: firmware-side C++ contracts and board data;
- `hardware_adapter/tests/test_hal_contract.py`: lifecycle and protocol tests.

The HAL does not own owner, base, figure, persona, memory, session, turn or
audio identity. Those remain server-owned.

## Ports

`DeviceHAL` contains:

| Port | Responsibility |
|---|---|
| microphone | Fixed 16 kHz mono s16le capture frames |
| speaker | Fixed 24 kHz mono s16le output and immediate abort |
| indicator | Product state to LED or local indicator |
| inputs | Touch, pressure, button and reset events |
| network | Connect, disconnect and network snapshot |
| clock | Monotonic timing and UTC diagnostics |
| secure storage | Device identity and network secrets |
| resources | Heap, PSRAM, stack and CPU snapshots |

The Python and C++ contracts use the same port boundaries. The Python fake is a
protocol fixture; it is not a substitute for ESP32 drivers.

## Lifecycle

Components start in this order:

1. secure storage
2. network driver
3. microphone
4. speaker
5. physical inputs
6. indicator
7. resource monitor

They stop in reverse order. A component is added to the rollback stack before
its `start` call so a partial initialization failure also calls that
component's `stop` method. Shutdown attempts every component and reports all
cleanup failures.

`HALAudioBackend` adapts these ports to the existing
`PortableVoiceClient` interface. It reuses the existing
`session_id`/`turn_id`/`audio_id`, cancellation and playback-receipt state
machine instead of creating a second protocol implementation.

## Task Model

EV-03 freezes initial budgets, not measured utilization:

| Task | Priority | Stack budget | Queue | Core | Overflow |
|---|---:|---:|---:|---:|---|
| `lingou_control` | 8 | 4096 B | 32 | 0 | reject new |
| `lingou_capture` | 7 | 4096 B | 12 | 1 | drop oldest |
| `lingou_playback` | 7 | 4096 B | 8 | 1 | reject new |
| `lingou_network` | 6 | 6144 B | 24 | 0 | reject new |
| `lingou_diagnostics` | 2 | 3072 B | 64 | 0 | drop oldest |

These values are starting budgets. They must be replaced or confirmed using
target-board high-water and runtime measurements before hardware release.

EV-04 implements these budgets with fixed slot pools. Capture keeps the newest
20 ms input when the network consumer falls behind. Playback never waits for
queue space in the WebSocket callback; saturation fails and clears the affected
audio generation instead of delaying control traffic.

## DNESP32S3 Profile

Board-specific data lives in:

- Python: `hardware_adapter/hal/boards/dnesp32s3.py`
- Firmware: `firmware/lingou_device_v1/hal/dnesp32s3_board_profile.h`

Verified wiring:

| Function | GPIO |
|---|---:|
| WS2812B ring | 18 |
| FSR | 16 |
| INMP441 BCLK / WS / DIN | 5 / 7 / 4 |
| MAX98357A BCLK / LRC / DOUT | 6 / 15 / 17 |

The profile explicitly states `validated_aec=false`. EV-05 must not infer AEC
support from the existence of microphone and speaker ports.

## Resource Evidence

The resource contract supports:

- current and minimum free heap;
- free PSRAM;
- per-task stack high-water bytes;
- per-task CPU percentage.

EV-03 evidence distinguishes three different things:

1. task budgets: design values;
2. fake HAL snapshot: simulated test values;
3. target-board measurements: real device evidence.

Only the third category can be used for product decisions. At EV-03 execution
time no ESP32 serial device was connected, so target values remain `null`.
Arduino compile reported:

- program storage: 1,110,081 / 1,310,720 bytes (84%);
- global dynamic memory: 49,596 / 327,680 bytes (15%);
- remaining for local variables: 278,084 bytes.

Those linker values do not prove runtime free heap, PSRAM, stack safety or CPU
headroom.

## Extending to Another Board

1. Add a board profile containing only board capabilities and wiring.
2. Implement all eight ports behind the C++ HAL contract.
3. Run the fake HAL and protocol contracts before connecting providers.
4. Measure resource snapshots on the target board.
5. Do not add board branches to the service dialogue, memory or identity code.

No board implementation may weaken TLS, device credential validation,
playback receipts or late-turn isolation.
