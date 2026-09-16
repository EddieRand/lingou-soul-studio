"""Offline, manifest-driven migration into owner-scoped runtime storage.

The default command only inventories legacy files. ``apply`` is also a dry run
unless ``--commit`` is present.  The module deliberately has no dependency on
the running FastAPI application or ``data.store`` so an operator can inspect a
copy of a data directory without initializing application state.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Iterable
import uuid


MANIFEST_SCHEMA_VERSION = 1
TARGET_SCHEMA_VERSION = 2
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

MIGRATION_DIR_NAME = ".ownership_migration"
LEDGER_RELATIVE_PATH = PurePosixPath(MIGRATION_DIR_NAME, "ledger.json")

TARGET_TYPES = {
    "figure",
    "base",
    "events",
    "dialogue_logs",
    "sync_queue",
    "cloud_data",
    "voice_upload",
}

INVENTORY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("figures/*.json", "figure"),
    ("bases/*.json", "base"),
    ("events/*.json", "events"),
    ("dialogue_logs/*.json", "dialogue_logs"),
    ("sync_queue/sync_queue.json", "sync_queue"),
    ("cloud_data/*.json", "cloud_data"),
    ("voice_uploads/*/*", "voice_upload"),
    # Older releases already placed some JSON under a user directory without
    # stamping a canonical owner. Inventory those files for explicit review;
    # current schema-v2 records are filtered out below.
    ("user_data/*/figures/*.json", "figure"),
    ("user_data/*/events/*.json", "events"),
    ("user_data/*/dialogue_logs/*.json", "dialogue_logs"),
    ("user_data/*/sync/sync_queue.json", "sync_queue"),
    ("user_data/*/sync/cloud_data.json", "cloud_data"),
)


class MigrationError(ValueError):
    """The inventory or migration request is unsafe or internally invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace one file atomically and never create it with public permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_create(path: Path, content: bytes) -> None:
    """Create an immutable migration artifact, accepting only an exact replay."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == content:
            return
        raise MigrationError(f"archive collision: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise MigrationError(f"archive collision: {path}")
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise MigrationError(
            f"{field} must be 1-128 characters using letters, digits, '_' or '-'"
        )
    return value


def _validate_exact_keys(value: dict, allowed: set[str], context: str) -> None:
    extra = set(value) - allowed
    missing = allowed - set(value)
    if missing:
        raise MigrationError(f"{context} is missing: {', '.join(sorted(missing))}")
    if extra:
        raise MigrationError(f"{context} has unknown fields: {', '.join(sorted(extra))}")


def _safe_source_path(data_dir: Path, relative: Any) -> tuple[str, Path]:
    if not isinstance(relative, str) or not relative:
        raise MigrationError("source must be a non-empty relative POSIX path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise MigrationError(f"unsafe source path: {relative!r}")
    if not pure.parts or pure.parts[0] == MIGRATION_DIR_NAME:
        raise MigrationError(f"source is outside the legacy input set: {relative!r}")
    normalized = pure.as_posix()
    candidate = (data_dir / Path(*pure.parts)).resolve(strict=True)
    try:
        candidate.relative_to(data_dir)
    except ValueError as exc:
        raise MigrationError(f"source escapes data directory: {relative!r}") from exc
    if not candidate.is_file():
        raise MigrationError(f"source is not a regular file: {relative!r}")
    return normalized, candidate


def _validate_source_for_type(source: str, target_type: str, target_id: str) -> None:
    pure = PurePosixPath(source)
    parts = pure.parts
    global_source = {
        "figure": len(parts) == 2 and parts[0] == "figures",
        "base": len(parts) == 2 and parts[0] == "bases",
        "events": len(parts) == 2 and parts[0] == "events",
        "dialogue_logs": len(parts) == 2 and parts[0] == "dialogue_logs",
        "sync_queue": len(parts) == 2 and parts[0] == "sync_queue",
        "cloud_data": len(parts) == 2 and parts[0] == "cloud_data",
        "voice_upload": len(parts) == 3 and parts[0] == "voice_uploads",
    }[target_type]
    namespaced_source = (
        len(parts) == 4
        and parts[0] == "user_data"
        and target_type in {"figure", "events", "dialogue_logs"}
        and parts[2]
        == {
            "figure": "figures",
            "events": "events",
            "dialogue_logs": "dialogue_logs",
        }.get(target_type)
    ) or (
        len(parts) == 4
        and parts[0] == "user_data"
        and parts[2] == "sync"
        and target_type in {"sync_queue", "cloud_data"}
    )
    expected_suffix = target_type == "voice_upload" or pure.suffix == ".json"
    if not (global_source or namespaced_source) or not expected_suffix:
        raise MigrationError(
            f"source {source!r} is not allowed for target type {target_type!r}"
        )
    if target_type == "sync_queue" and pure.name != "sync_queue.json":
        raise MigrationError("sync_queue source must be sync_queue/sync_queue.json")
    if (
        target_type == "cloud_data"
        and parts[0] == "user_data"
        and pure.name != "cloud_data.json"
    ):
        raise MigrationError("namespaced cloud_data source must end with sync/cloud_data.json")
    if target_type == "voice_upload" and pure.parts[1] != target_id:
        raise MigrationError("voice_upload target.id must match its legacy figure directory")


def _is_current_owner_scoped_json(source: str, target_type: str, content: bytes) -> bool:
    """Skip already-canonical user_data JSON during legacy inventory."""
    parts = PurePosixPath(source).parts
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False

    if target_type == "base" and len(parts) == 2 and parts[0] == "bases":
        if not isinstance(value, dict):
            return False
        if (
            value.get("schema_version") == TARGET_SCHEMA_VERSION
            and value.get("base_id") == PurePosixPath(source).stem
            and value.get("status") == "unbound"
            and value.get("provisioning_state") == "ready"
            and not any(
                value.get(field)
                for field in ("owner_user_id", "owner_id", "bound_user_id")
            )
            and isinstance(value.get("pairing_token_hash"), str)
            and isinstance(value.get("device_credential_hash"), str)
        ):
            return True
        owner = value.get("owner_user_id")
        declared = {
            str(value[key])
            for key in ("owner_user_id", "owner_id", "bound_user_id")
            if value.get(key)
        }
        return (
            isinstance(owner, str)
            and bool(ID_RE.fullmatch(owner))
            and value.get("schema_version") == TARGET_SCHEMA_VERSION
            and value.get("base_id") == PurePosixPath(source).stem
            and declared == {owner}
        )

    if len(parts) != 4 or parts[0] != "user_data" or target_type == "voice_upload":
        return False
    namespace_owner = parts[1]
    if not ID_RE.fullmatch(namespace_owner):
        return False

    def canonical(record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        declared = {
            str(record[key])
            for key in ("owner_user_id", "owner_id", "bound_user_id")
            if record.get(key)
        }
        return (
            record.get("schema_version") == TARGET_SCHEMA_VERSION
            and record.get("owner_user_id") == namespace_owner
            and declared == {namespace_owner}
        )

    if target_type == "figure":
        return canonical(value)
    if target_type in {"events", "dialogue_logs"}:
        return isinstance(value, list) and all(canonical(item) for item in value)
    if target_type == "sync_queue":
        return (
            canonical(value)
            and isinstance(value.get("items", []), list)
            and all(canonical(item) for item in value.get("items", []))
        )
    if target_type == "cloud_data":
        return canonical(value) and all(
            isinstance(value.get(field, []), list)
            and all(canonical(item) for item in value.get(field, []))
            for field in ("figures", "dialogue_logs", "events")
        )
    return False


def _target_relative_path(owner: str, target_type: str, target_id: str) -> PurePosixPath:
    if target_type == "figure":
        return PurePosixPath("user_data", owner, "figures", f"{target_id}.json")
    if target_type == "base":
        return PurePosixPath("bases", f"{target_id}.json")
    if target_type == "events":
        return PurePosixPath("user_data", owner, "events", f"{target_id}.json")
    if target_type == "dialogue_logs":
        return PurePosixPath("user_data", owner, "dialogue_logs", f"{target_id}.json")
    if target_type == "sync_queue":
        return PurePosixPath("user_data", owner, "sync", "sync_queue.json")
    if target_type == "cloud_data":
        return PurePosixPath("user_data", owner, "sync", "cloud_data.json")
    if target_type == "voice_upload":
        raise MigrationError("voice_upload target path requires its source filename")
    raise MigrationError(f"unsupported target type: {target_type!r}")


def _safe_target_path(data_dir: Path, relative: PurePosixPath) -> Path:
    path = data_dir / Path(*relative.parts)
    if path.is_symlink():
        raise MigrationError(f"target cannot be a symbolic link: {relative}")
    parent = path.parent.resolve(strict=False)
    try:
        parent.relative_to(data_dir)
    except ValueError as exc:
        raise MigrationError(f"target escapes data directory: {relative}") from exc
    return path


def _validate_target_id(target_type: str, target_id: Any) -> str:
    target_id = _validate_id(target_id, "target.id")
    if target_type in {"events", "dialogue_logs"} and not MONTH_RE.fullmatch(target_id):
        raise MigrationError(f"target.id for {target_type} must use YYYY-MM")
    if target_type == "sync_queue" and target_id != "sync_queue":
        raise MigrationError("target.id for sync_queue must be 'sync_queue'")
    if target_type == "cloud_data" and target_id != "cloud_data":
        raise MigrationError("target.id for cloud_data must be 'cloud_data'")
    return target_id


def _registered_owner_ids(data_dir: Path) -> set[str]:
    users_path = data_dir / "users.json"
    try:
        raw = json.loads(users_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError("users.json is required to verify registered owners") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("users.json is unreadable or invalid JSON") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("users"), list):
        raise MigrationError("users.json must contain a users array")
    owners: set[str] = set()
    for index, user in enumerate(raw["users"]):
        if not isinstance(user, dict):
            raise MigrationError(f"users.json users[{index}] must be an object")
        owner = _validate_id(user.get("user_id"), f"users[{index}].user_id")
        if owner in owners:
            raise MigrationError(f"users.json contains duplicate user_id: {owner}")
        owners.add(owner)
    return owners


def _parse_json_source(content: bytes, source: str) -> Any:
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"source is not valid UTF-8 JSON: {source}") from exc


def _assert_existing_owner(record: dict, owner: str, context: str) -> None:
    declared = {
        str(record[key])
        for key in ("owner_user_id", "owner_id", "bound_user_id")
        if record.get(key)
    }
    if len(declared) > 1 or (declared and next(iter(declared)) != owner):
        raise MigrationError(f"{context} already declares a different or conflicting owner")


def _stamp_record(record: Any, owner: str, context: str) -> dict:
    if not isinstance(record, dict):
        raise MigrationError(f"{context} must be a JSON object")
    result = deepcopy(record)
    _assert_existing_owner(result, owner, context)
    result["schema_version"] = TARGET_SCHEMA_VERSION
    result["owner_user_id"] = owner
    result.pop("owner_id", None)
    result.pop("bound_user_id", None)
    return result


def _transform(content: bytes, source: str, owner: str, target_type: str, target_id: str) -> bytes:
    if target_type == "voice_upload":
        return content
    value = _parse_json_source(content, source)
    if target_type == "figure":
        result = _stamp_record(value, owner, source)
        existing_id = result.get("figure_id") or result.get("id")
        if existing_id and existing_id != target_id:
            raise MigrationError(f"{source} declares a different figure id")
        result["figure_id"] = target_id
        return _json_bytes(result)
    if target_type == "base":
        result = _stamp_record(value, owner, source)
        existing_id = result.get("base_id") or result.get("id")
        if existing_id and existing_id != target_id:
            raise MigrationError(f"{source} declares a different base id")
        result["base_id"] = target_id
        result["bound_user_id"] = owner
        return _json_bytes(result)
    if target_type in {"events", "dialogue_logs"}:
        if not isinstance(value, list):
            raise MigrationError(f"{source} must be a JSON array")
        stamped = [
            _stamp_record(item, owner, f"{source}[{index}]")
            for index, item in enumerate(value)
        ]
        return _json_bytes(stamped)
    if target_type in {"sync_queue", "cloud_data"}:
        result = _stamp_record(value, owner, source)
        if target_type == "sync_queue":
            items = result.get("items", [])
            if not isinstance(items, list):
                raise MigrationError(f"{source}.items must be a JSON array")
            result["items"] = [
                _stamp_record(item, owner, f"{source}.items[{index}]")
                for index, item in enumerate(items)
            ]
        else:
            for field in ("figures", "dialogue_logs", "events"):
                records = result.get(field, [])
                if not isinstance(records, list):
                    raise MigrationError(f"{source}.{field} must be a JSON array")
                result[field] = [
                    _stamp_record(item, owner, f"{source}.{field}[{index}]")
                    for index, item in enumerate(records)
                ]
        return _json_bytes(result)
    raise MigrationError(f"unsupported target type: {target_type!r}")


def inventory(data_dir: Path) -> dict:
    """Return a review-only draft. Owners are intentionally never inferred."""
    data_dir = data_dir.expanduser().resolve(strict=True)
    if not data_dir.is_dir():
        raise MigrationError("data directory is not a directory")
    entries: list[dict] = []
    for pattern, target_type in INVENTORY_PATTERNS:
        for path in sorted(data_dir.glob(pattern)):
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(data_dir)
            except ValueError as exc:
                raise MigrationError(f"inventory path escapes data directory: {path}") from exc
            if not resolved.is_file():
                continue
            relative = path.relative_to(data_dir).as_posix()
            content = resolved.read_bytes()
            if _is_current_owner_scoped_json(relative, target_type, content):
                continue
            if target_type == "sync_queue":
                target_id = "sync_queue"
            elif target_type == "cloud_data":
                target_id = "cloud_data"
            elif target_type == "voice_upload":
                target_id = path.parent.name
            else:
                target_id = path.stem
            entries.append(
                {
                    "source": relative,
                    "owner_user_id": None,
                    "sha256": _sha256(content),
                    "target": {"type": target_type, "id": target_id},
                    "size_bytes": len(content),
                    "review_status": "owner_required",
                }
            )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mode": "inventory_only",
        "generated_at": _utc_now(),
        "entries": entries,
    }


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError(f"manifest does not exist: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("manifest is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise MigrationError("manifest must be a JSON object")
    _validate_exact_keys(value, {"schema_version", "entries"}, "manifest")
    if value["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise MigrationError(f"manifest.schema_version must be {MANIFEST_SCHEMA_VERSION}")
    if not isinstance(value["entries"], list) or not value["entries"]:
        raise MigrationError("manifest.entries must be a non-empty array")
    return value


def _entry_identity(entry: dict) -> str:
    canonical = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256(canonical.encode("utf-8"))


def _load_ledger(data_dir: Path) -> dict:
    path = _safe_target_path(data_dir, LEDGER_RELATIVE_PATH)
    if not path.exists():
        return {"schema_version": 1, "completed": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("migration ledger is unreadable or invalid JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("completed"), list)
    ):
        raise MigrationError("migration ledger has an invalid schema")
    return value


def _completed_by_id(ledger: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in ledger["completed"]:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(field), str) and item[field]
            for field in ("entry_id", "source", "target")
        ):
            raise MigrationError("migration ledger contains an invalid entry")
        if item["entry_id"] in result:
            raise MigrationError("migration ledger contains duplicate entry ids")
        result[item["entry_id"]] = item
    return result


def _validate_manifest(data_dir: Path, manifest: dict) -> list[dict]:
    registered = _registered_owner_ids(data_dir)
    prepared: list[dict] = []
    source_paths: set[str] = set()
    target_paths: set[str] = set()
    for index, raw in enumerate(manifest["entries"]):
        context = f"manifest.entries[{index}]"
        if not isinstance(raw, dict):
            raise MigrationError(f"{context} must be an object")
        _validate_exact_keys(raw, {"source", "owner_user_id", "sha256", "target"}, context)
        owner = _validate_id(raw["owner_user_id"], f"{context}.owner_user_id")
        if owner not in registered:
            raise MigrationError(f"{context}.owner_user_id is not a registered user")
        digest = raw["sha256"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise MigrationError(f"{context}.sha256 must be a lowercase SHA-256 digest")
        if not isinstance(raw["target"], dict):
            raise MigrationError(f"{context}.target must be an object")
        _validate_exact_keys(raw["target"], {"type", "id"}, f"{context}.target")
        target_type = raw["target"]["type"]
        if target_type not in TARGET_TYPES:
            raise MigrationError(f"{context}.target.type is unsupported")
        target_id = _validate_target_id(target_type, raw["target"]["id"])
        source, source_path = _safe_source_path(data_dir, raw["source"])
        _validate_source_for_type(source, target_type, target_id)
        source_key = str(source_path.resolve())
        if source_key in source_paths:
            raise MigrationError(f"manifest contains duplicate source: {source}")
        source_paths.add(source_key)
        if target_type == "voice_upload":
            target_relative = PurePosixPath(
                "user_data",
                owner,
                "voice_uploads",
                target_id,
                PurePosixPath(source).name,
            )
        else:
            target_relative = _target_relative_path(owner, target_type, target_id)
        observed_source = source_path.read_bytes()
        content = observed_source
        target_path = _safe_target_path(data_dir, target_relative)
        if _sha256(content) != digest:
            archive_relative = PurePosixPath(
                MIGRATION_DIR_NAME,
                "legacy_sources",
                digest,
                source,
            )
            archive = _safe_target_path(data_dir, archive_relative)
            if (
                source_path.resolve() != target_path.resolve()
                or not archive.is_file()
                or _sha256(archive.read_bytes()) != digest
            ):
                raise MigrationError(f"{context}.sha256 does not match source bytes")
            content = archive.read_bytes()
        target_key = target_relative.as_posix()
        if target_key in target_paths:
            raise MigrationError(f"manifest contains duplicate target: {target_key}")
        target_paths.add(target_key)
        clean_entry = {
            "source": source,
            "owner_user_id": owner,
            "sha256": digest,
            "target": {"type": target_type, "id": target_id},
        }
        prepared.append(
            {
                "entry": clean_entry,
                "entry_id": _entry_identity(clean_entry),
                "source_path": source_path,
                "observed_source_bytes": observed_source,
                "source_bytes": content,
                "target_relative": target_relative,
                "target_path": target_path,
                "target_bytes": _transform(content, source, owner, target_type, target_id),
            }
        )
    return prepared


def plan_or_apply(data_dir: Path, manifest_path: Path, *, commit: bool = False) -> dict:
    data_dir = data_dir.expanduser().resolve(strict=True)
    if not data_dir.is_dir():
        raise MigrationError("data directory is not a directory")
    manifest = _load_manifest(manifest_path.expanduser().resolve(strict=True))
    prepared = _validate_manifest(data_dir, manifest)
    ledger = _load_ledger(data_dir)
    completed = _completed_by_id(ledger)
    completed_sources = {
        str((data_dir / item["source"]).resolve()): entry_id
        for entry_id, item in completed.items()
    }
    completed_targets = {
        str((data_dir / item["target"]).resolve()): entry_id
        for entry_id, item in completed.items()
    }
    plan: list[dict] = []

    # Validate all collisions before the first mutation.
    for item in prepared:
        target_path = item["target_path"]
        previous_source = completed_sources.get(str(item["source_path"].resolve()))
        if previous_source is not None and previous_source != item["entry_id"]:
            raise MigrationError(f"source already assigned by a completed migration: {item['entry']['source']}")
        previous_target = completed_targets.get(str(target_path.resolve()))
        if previous_target is not None and previous_target != item["entry_id"]:
            raise MigrationError(f"target already assigned by a completed migration: {item['target_relative']}")
        desired = item["target_bytes"]
        ledger_item = completed.get(item["entry_id"])
        if ledger_item:
            if ledger_item.get("target") != item["target_relative"].as_posix():
                raise MigrationError("ledger target does not match manifest entry")
            if not target_path.is_file() or _sha256(target_path.read_bytes()) != _sha256(desired):
                raise MigrationError(
                    f"completed migration target was changed: {item['target_relative']}"
                )
            status = "already_applied"
        elif target_path.exists() and target_path.resolve() != item["source_path"].resolve():
            if not target_path.is_file() or target_path.read_bytes() != desired:
                raise MigrationError(f"target collision: {item['target_relative']}")
            status = "recover_ledger"
        else:
            status = "ready"
        plan.append(
            {
                "entry_id": item["entry_id"],
                "source": item["entry"]["source"],
                "target": item["target_relative"].as_posix(),
                "status": status,
            }
        )

    if not commit:
        return {"mode": "dry_run", "committed": False, "entries": plan}

    # Recheck every source after planning and before the first mutation. The
    # operator is expected to stop the service, but a changed or replaced file
    # must still abort the whole manifest before this process writes anything.
    for item in prepared:
        source, current_path = _safe_source_path(data_dir, item["entry"]["source"])
        if source != item["entry"]["source"] or current_path != item["source_path"]:
            raise MigrationError(f"source changed during validation: {source}")
        if current_path.read_bytes() != item["observed_source_bytes"]:
            raise MigrationError(f"source changed during validation: {source}")

    ledger_changed = False
    for item, planned in zip(prepared, plan, strict=True):
        if planned["status"] == "already_applied":
            continue
        source_path = item["source_path"]
        target_path = item["target_path"]
        if source_path.resolve() == target_path.resolve():
            # Bases and already-namespaced legacy JSON can migrate in place.
            # Preserve the exact old bytes under a content-addressed archive first.
            archive_relative = PurePosixPath(
                MIGRATION_DIR_NAME,
                "legacy_sources",
                item["entry"]["sha256"],
                item["entry"]["source"],
            )
            archive = _safe_target_path(data_dir, archive_relative)
            _atomic_create(archive, item["source_bytes"])
        if planned["status"] == "ready":
            _atomic_write(target_path, item["target_bytes"])
        ledger["completed"].append(
            {
                "entry_id": item["entry_id"],
                "source": item["entry"]["source"],
                "source_sha256": item["entry"]["sha256"],
                "target": item["target_relative"].as_posix(),
                "target_sha256": _sha256(item["target_bytes"]),
                "completed_at": _utc_now(),
            }
        )
        ledger_changed = True

    if ledger_changed:
        ledger_path = _safe_target_path(data_dir, LEDGER_RELATIVE_PATH)
        _atomic_write(ledger_path, _json_bytes(ledger))
    return {"mode": "apply", "committed": True, "entries": plan}


def _write_result(result: dict, output: Path | None) -> None:
    content = _json_bytes(result)
    if output is None:
        sys.stdout.buffer.write(content)
        return
    output = output.expanduser().resolve()
    _atomic_write(output, content)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory or explicitly migrate legacy Lingou data ownership"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("inventory", "apply"),
        default="inventory",
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="perform validated writes; apply is a dry run without this flag",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "inventory":
            if args.manifest is not None or args.commit:
                raise MigrationError("inventory does not accept --manifest or --commit")
            result = inventory(args.data_dir)
        else:
            if args.manifest is None:
                raise MigrationError("apply requires --manifest")
            result = plan_or_apply(args.data_dir, args.manifest, commit=args.commit)
        _write_result(result, args.output)
    except (MigrationError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"ownership migration refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
