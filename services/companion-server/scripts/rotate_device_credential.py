"""Rotate an existing production base credential and print it exactly once."""

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
    parser = argparse.ArgumentParser(
        description="Rotate one Lingou production device credential",
    )
    parser.add_argument("--base-id", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["LINGOU_DATA_DIR"] = str(args.data_dir.expanduser().resolve())

    from data.store import rotate_production_device_credential

    credential = f"{args.base_id}.{secrets.token_urlsafe(32)}"
    rotate_production_device_credential(
        args.base_id,
        device_credential=credential,
    )
    print(
        json.dumps(
            {
                "base_id": args.base_id,
                "device_credential": credential,
                "scope": ["events:write", "voice:stream"],
                "notice": (
                    "Credential shown once. Replace the device configuration; "
                    "the previous credential is now invalid."
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
