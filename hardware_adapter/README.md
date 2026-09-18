# Hardware adapter

## Board HAL

`hardware_adapter/hal` defines the board-neutral voice-device ports, lifecycle,
task budgets, fake HAL and bridge into the existing device voice client.
DNESP32S3 GPIO values live only in its board profile. See
[the HAL design](../docs/hardware-hal.md) and
[EV-03 evidence](../docs/validation/ev03-hal-20260917/README.md).
The bounded capture/playback implementation and its remaining physical checks
are recorded in
[EV-04 evidence](../docs/validation/ev04-audio-pipeline-20260917/README.md).

Run its contracts without target hardware:

```bash
python -B hardware_adapter/tests/test_hal_contract.py
```

The fake resource values prove the schema only; they are not target ESP32
measurements.

## Acoustic validation

`hal/acoustic_profile.py` mirrors the versioned EV-05 gain, clipping and
playback-reference conversion contract for host tests. The firmware uses the
ESP-SR implementation documented in
[`docs/acoustic-frontend.md`](../docs/acoustic-frontend.md).

After capturing raw and processed 16 kHz mono WAVs from the physical target,
archive and evaluate each required scenario with:

```bash
python -B services/companion-server/scripts/collect_ev05_acoustic_baseline.py \
  --scenario echo_only \
  --raw-wav /path/to/raw.wav \
  --processed-wav /path/to/processed.wav \
  --reference-wav /path/to/reference.wav \
  --hardware-id DNESP32S3-01 \
  --firmware-commit "$(git rev-parse HEAD)" \
  --output-dir docs/validation/ev05-acoustic-YYYYMMDD \
  --confirm-target-capture
```

The collector refuses to label input as target evidence without the explicit
confirmation flag.

## Portable carrier MVP

`portable_voice_client` turns a Linux/macOS computer with a microphone and
speaker into the step-11 independent device MVP. It talks to the device
WebSocket directly, uses no browser or user Bearer token, reports real playback,
and reconnects after transient network failures. Its playback queue is bounded
to eight frames; saturation fails and clears active audio rather than delaying
control messages.

```bash
python3 -m venv .venv-portable
.venv-portable/bin/python -m pip install \
  -r hardware_adapter/requirements-portable-device.txt

export LINGOU_DEVICE_CREDENTIAL='BASE-DEVICE-001.<device secret>'
export LINGOU_DEVICE_VOICE_URL='wss://your-host/api/asr/device-stream'
.venv-portable/bin/python -B \
  -m hardware_adapter.portable_voice_client
```

Press Enter or send `SIGUSR1` to interrupt playback. See
[the portable carrier guide](../docs/portable-device-mvp.md) for audio-device
selection, credential rotation, systemd/launchd startup and validation.

## Serial event bridge

`serial_bridge` parses ESP32 serial output and forwards supported events with
an independent device credential. It does not use a user Bearer token. This is
an event diagnostic bridge, not the independent voice runtime; the latter is
implemented by [`firmware/lingou_device_v1`](../firmware/lingou_device_v1/README.md)
and connects directly over Wi-Fi.

Offline parsing needs no backend credentials:

```bash
python3 -m hardware_adapter.serial_bridge --port /dev/cu.usbmodem101 --dry-run
```

For a provisioned physical base, provide its explicit ID and device credential:

```bash
export LINGOU_DEVICE_CREDENTIAL='<provisioned device credential>'
python3 -m hardware_adapter.serial_bridge \
  --port /dev/cu.usbmodem101 \
  --base-id BASE-DEVICE-001
```

The request goes to `POST /api/device/events` with `Authorization: Device ...`
and includes `event_type`, a unique `event_id`, and `occurred_at`. The backend
derives the base from the credential and rejects replayed or stale events.
Development credentials remain available through
`LINGOU_TEST_DEVICE_CREDENTIAL` when the backend explicitly enables test
device authentication. See [the full bridge guide](../docs/hardware-serial-bridge.md).
