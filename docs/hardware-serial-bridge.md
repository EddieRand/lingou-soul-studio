# Lingou Hardware Serial Bridge

This document describes the legacy event bridge. It remains useful for
touch/FSR diagnostics, but it is not the step-11 independent voice path.
The step-11 independent-device MVP is documented in
[`docs/portable-device-mvp.md`](portable-device-mvp.md) and connects to the
backend directly from a Linux/macOS carrier. The ESP32 firmware remains a
future-hardware reference implementation.

This bridge connects the ESP32-S3 base firmware to the existing Lingou backend.

Current ESP32 text protocol:

```text
FSR_RAW=4095 STATE=NO_TOUCH
STATE_CHANGED=LIGHT_TOUCH
STATE_CHANGED=HEAVY_PRESS
EVENT=KNOCK_EDGE VALUE=1
EVENT=DOUBLE_TAP_WAKE
```

Bridge mapping:

| ESP32 line | Backend event |
| --- | --- |
| `STATE_CHANGED=LIGHT_TOUCH` | `light_touch` |
| `STATE_CHANGED=HEAVY_PRESS` | `heavy_press` |
| `EVENT=DOUBLE_TAP_WAKE` | `double_tap` |
| `EVENT=FIGURE_PLACED` | `figure_placed` |
| `EVENT=KNOCK_EDGE VALUE=x` | raw only, not sent by default |

Quiet dry run (no backend or credential required):

```bash
cd /Users/bytedance/Downloads/LINGOU
python3 -m hardware_adapter.serial_bridge --port /dev/cu.usbmodem101 --dry-run
```

Without `--base-id`, dry-run output uses the non-device marker
`DRY-RUN-UNASSIGNED`. Dry-run never sends an HTTP request.

Provision a physical base before generating its QR label:

```bash
cd /Users/bytedance/Downloads/LINGOU/services/companion-server
.venv/bin/python -B -m scripts.provision_base \
  --base-id BASE-DEVICE-001 \
  --data-dir /absolute/path/to/runtime-data
```

The command prints `qr_payload` and `device_credential` once. Put only the QR
payload on the label. Store the device credential in protected device
configuration; never encode it in the QR code or commit it. New credentials
have `events:write` and `voice:stream`.

For a base provisioned before step 11, rotate the production credential
explicitly:

```bash
cd /Users/bytedance/Downloads/LINGOU/services/companion-server
.venv/bin/python -B -m scripts.rotate_device_credential \
  --base-id BASE-DEVICE-001 \
  --data-dir /absolute/path/to/runtime-data
```

Send events with the provisioned device credential:

```bash
cd /Users/bytedance/Downloads/LINGOU
export LINGOU_DEVICE_CREDENTIAL='BASE-DEVICE-001.<device secret>'
python3 -m hardware_adapter.serial_bridge \
  --port /dev/cu.usbmodem101 \
  --base-id BASE-DEVICE-001
```

Non-dry-run mode requires an explicit `--base-id` and either
`--device-credential`, `LINGOU_DEVICE_CREDENTIAL`, or the legacy development
variable `LINGOU_TEST_DEVICE_CREDENTIAL`. Validation happens
before the serial port is opened. The default endpoint is
`POST /api/device/events`; requests use:

```http
Authorization: Device <development-test-credential>
Content-Type: application/json

{
  "event_type":"light_touch",
  "event_id":"<unique UUID>",
  "occurred_at":"<timezone-aware ISO-8601 timestamp>"
}
```

The bridge does not send `base_id` in the request. The backend maps the
credential to its provisioned base; the command-line base ID is only the local
adapter identity and operator-visible expectation. Before opening the serial
port, the bridge also checks that the base ID prefix in the credential matches
`--base-id`. The bridge never prints the credential. Prefer the environment
variable because command-line arguments may be visible to other local processes.

Production events require the unique ID and timestamp. The backend rejects an
event ID already accepted for that base and rejects timestamps outside a
five-minute window. An unbound base or revoked credential cannot submit events.

Test-device authentication is development-only and disabled by default in the
backend. It must be explicitly enabled with
`LINGOU_ENABLE_TEST_DEVICE_AUTH=1`. An authenticated user can then create a
development base through `POST /api/bases/test-bases` and issue or rotate its
24-hour, device-scoped credential through
`POST /api/bases/{base_id}/test-device-credential`. The plaintext credential is
returned once; rotating it invalidates the previous value.

The test-device endpoints remain available only when
`LINGOU_ENABLE_TEST_DEVICE_AUTH=1`; they are for isolated development and do
not replace factory provisioning.

If Python cannot import `serial`, install pyserial in the backend environment:

```bash
python3 -m pip install pyserial
```
