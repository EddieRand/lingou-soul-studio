"""Provision one physical base and print its secrets exactly once.

Run against the intended data directory before shipping the device. The QR
payload is printed for label generation; the device credential must be written
to the device's protected configuration and must not be placed in the QR code.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision one Lingou base")
    parser.add_argument("--base-id", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["LINGOU_DATA_DIR"] = str(args.data_dir.expanduser().resolve())

    from data.store import provision_base

    pairing_token = f"{args.base_id}.{secrets.token_urlsafe(32)}"
    device_credential = f"{args.base_id}.{secrets.token_urlsafe(32)}"
    provision_base(
        args.base_id,
        pairing_token=pairing_token,
        device_credential=device_credential,
    )
    print(
        json.dumps(
            {
                "base_id": args.base_id,
                "qr_payload": f"lingou://pair?token={pairing_token}",
                "device_credential": device_credential,
                "scope": ["events:write", "voice:stream"],
                "notice": "Secrets are shown once; store the device credential securely.",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
