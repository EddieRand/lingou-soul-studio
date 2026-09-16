"""Owner-scoped JSON storage for Lingou runtime data.

Normal application reads never fall back to the legacy global directories.
Legacy data is intentionally exposed only through the offline migration module.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Optional
import uuid


DATA_DIR = Path(
    os.environ.get("LINGOU_DATA_DIR")
    or Path(__file__).parent.parent.parent.parent / "data"
).expanduser().resolve()

USER_DATA_DIR = DATA_DIR / "user_data"
BASES_DIR = DATA_DIR / "bases"
FIGURES_DIR = DATA_DIR / "figures"  # legacy, migration-only
ARCHETYPES_DIR = DATA_DIR / "archetypes"
EVENTS_DIR = DATA_DIR / "events"  # legacy, migration-only
DIALOGUE_LOGS_DIR = DATA_DIR / "dialogue_logs"  # legacy, migration-only
SYNC_QUEUE_DIR = DATA_DIR / "sync_queue"  # legacy, migration-only
VOICE_UPLOADS_DIR = DATA_DIR / "voice_uploads"  # legacy, migration-only
TRANSACTIONS_DIR = DATA_DIR / ".transactions"

_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_store_lock = threading.RLock()
_MANAGED_MEMORY_FIELDS = (
    "confirmed_facts",
    "memory_candidates",
    "memory_tombstones",
    "memory_revision",
    "memory_updated_at",
)


class DataIntegrityError(RuntimeError):
    """Stored data violates an ownership invariant."""


class PairingError(RuntimeError):
    """Base pairing request cannot be completed."""


class InvalidPairingTokenError(PairingError):
    """Pairing payload is invalid or does not match a provisioned base."""


class BaseAlreadyBoundError(PairingError):
    """The provisioned base belongs to another account."""


class AccountAlreadyHasBaseError(PairingError):
    """The MVP account already owns a different base."""


class DeviceEventReplayError(RuntimeError):
    """A production device event was already accepted."""


for directory in (
    USER_DATA_DIR,
    BASES_DIR,
    FIGURES_DIR,
    ARCHETYPES_DIR,
    EVENTS_DIR,
    DIALOGUE_LOGS_DIR,
    SYNC_QUEUE_DIR,
    VOICE_UPLOADS_DIR,
    TRANSACTIONS_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_resource_id(value: str, field_name: str = "resource_id") -> str:
    """Return a path-safe identifier or raise ValueError."""
    if not isinstance(value, str) or not _RESOURCE_ID_RE.fullmatch(value):
        raise ValueError(
            f"{field_name} must be 1-128 characters using letters, digits, '_' or '-'"
        )
    return value


def figure_storage_key(owner_user_id: str, figure_id: str) -> str:
    """Build a non-reversible, owner-scoped key for audio/cache directories."""
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    figure_id = validate_resource_id(figure_id, "figure_id")
    owner_prefix = hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:20]
    return f"{owner_prefix}-{figure_id}"


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_dir(user_id: str, *, create: bool = False) -> Path:
    user_id = validate_resource_id(user_id, "user_id")
    path = USER_DATA_DIR / user_id
    return _ensure_directory(path) if create else path


def _user_resource_dir(user_id: str, name: str, *, create: bool = False) -> Path:
    path = _user_dir(user_id, create=create) / name
    return _ensure_directory(path) if create else path


def _user_figures_dir(user_id: str, *, create: bool = False) -> Path:
    return _user_resource_dir(user_id, "figures", create=create)


def _user_events_dir(user_id: str, *, create: bool = False) -> Path:
    return _user_resource_dir(user_id, "events", create=create)


def _user_dialogue_logs_dir(user_id: str, *, create: bool = False) -> Path:
    return _user_resource_dir(user_id, "dialogue_logs", create=create)


def _user_sync_dir(user_id: str, *, create: bool = False) -> Path:
    return _user_resource_dir(user_id, "sync", create=create)


def _user_voice_uploads_dir(user_id: str, *, create: bool = False) -> Path:
    return _user_resource_dir(user_id, "voice_uploads", create=create)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Any) -> None:
    """Write JSON atomically with private file permissions."""
    _ensure_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with _store_lock:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _transaction_relative_path(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(DATA_DIR).as_posix()
    except ValueError as exc:
        raise DataIntegrityError("transaction path escapes the data directory") from exc


def _recover_pending_transactions() -> None:
    """Finish prepared JSON transactions before serving runtime reads."""
    for journal in sorted(TRANSACTIONS_DIR.glob("*.json")):
        payload = _read_json(journal)
        if not isinstance(payload, dict) or not isinstance(payload.get("writes"), list):
            raise DataIntegrityError(f"invalid transaction journal: {journal.name}")
        for entry in payload["writes"]:
            if not isinstance(entry, dict) or set(entry) != {"path", "data"}:
                raise DataIntegrityError(f"invalid transaction entry: {journal.name}")
            relative = Path(str(entry["path"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise DataIntegrityError(f"unsafe transaction path: {journal.name}")
            target = (DATA_DIR / relative).resolve(strict=False)
            _transaction_relative_path(target)
            _write_json(target, entry["data"])
        journal.unlink(missing_ok=True)


def _write_json_transaction(writes: dict[Path, Any]) -> None:
    """Persist a recoverable multi-file update using redo journaling."""
    if not writes:
        return
    with _store_lock:
        entries = [
            {"path": _transaction_relative_path(path), "data": deepcopy(data)}
            for path, data in writes.items()
        ]
        journal = TRANSACTIONS_DIR / f"{uuid.uuid4().hex}.json"
        _write_json(
            journal,
            {
                "schema_version": 1,
                "created_at": _now_iso(),
                "writes": entries,
            },
        )
        try:
            for path, data in writes.items():
                _write_json(path, data)
        except Exception as exc:
            # Leave the redo journal in place. A restart completes every write
            # before the application can read runtime state.
            raise DataIntegrityError(
                "transaction interrupted; recovery is required before retry"
            ) from exc
        else:
            journal.unlink(missing_ok=True)


_recover_pending_transactions()


def _record_owner(data: dict) -> Optional[str]:
    owners = {
        str(data[key])
        for key in ("owner_user_id", "owner_id")
        if data.get(key)
    }
    if len(owners) > 1:
        raise DataIntegrityError("record contains conflicting owners")
    owner = next(iter(owners), None)
    if owner is None:
        return None
    try:
        return validate_resource_id(owner, "owner_user_id")
    except ValueError as exc:
        raise DataIntegrityError("record contains an invalid owner") from exc


def _owned_record(data: Any, owner_user_id: str) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    stored_owner = _record_owner(data)
    # Runtime reads fail closed. Owner-less legacy records must be handled by
    # the offline migration tool rather than silently claimed by the reader.
    # Legacy aliases alone are not enough: a readable runtime record must be
    # canonical schema v2 and carry the canonical owner field itself.
    if (
        data.get("schema_version") != 2
        or data.get("owner_user_id") != owner_user_id
        or stored_owner != owner_user_id
    ):
        return None
    result = deepcopy(data)
    result["schema_version"] = 2
    result["owner_user_id"] = owner_user_id
    result.pop("owner_id", None)
    return result


def _prepare_owned_record(data: dict, owner_user_id: str) -> dict:
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    stored_owner = _record_owner(data)
    if stored_owner is not None and stored_owner != owner_user_id:
        raise DataIntegrityError("record owner does not match storage owner")
    result = deepcopy(data)
    result["schema_version"] = 2
    result["owner_user_id"] = owner_user_id
    result.pop("owner_id", None)
    return result


# ============== Base ==============

def base_owner_id(base: dict) -> Optional[str]:
    owners = {
        str(base[key])
        for key in ("owner_user_id", "owner_id", "bound_user_id")
        if base.get(key)
    }
    if len(owners) != 1:
        return None
    owner = next(iter(owners))
    try:
        return validate_resource_id(owner, "owner_user_id")
    except ValueError:
        return None


def _scoped_secret(value: str, field_name: str) -> tuple[str, str]:
    if not isinstance(value, str) or "." not in value:
        raise ValueError(f"{field_name} must use <base-id>.<secret>")
    base_id, secret = value.split(".", 1)
    validate_resource_id(base_id, "base_id")
    if len(secret) < 32 or len(secret) > 256:
        raise ValueError(f"{field_name} secret must contain 32-256 characters")
    return base_id, secret


def _credential_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def provision_base(
    base_id: str,
    *,
    pairing_token: str,
    device_credential: str,
) -> dict:
    """Create one unbound factory record without retaining plaintext secrets."""
    base_id = validate_resource_id(base_id, "base_id")
    pairing_base_id, _ = _scoped_secret(pairing_token, "pairing_token")
    credential_base_id, _ = _scoped_secret(device_credential, "device_credential")
    if pairing_base_id != base_id or credential_base_id != base_id:
        raise ValueError("provisioning secrets do not belong to base_id")
    path = BASES_DIR / f"{base_id}.json"
    now = _now_iso()
    result = {
        "schema_version": 2,
        "base_id": base_id,
        "active_figure_id": None,
        "status": "unbound",
        "provisioning_state": "ready",
        "pairing_token_hash": _credential_hash(pairing_token),
        "device_credential_hash": _credential_hash(device_credential),
        "device_credential_kind": "production",
        "device_credential_status": "active",
        "device_credential_scope": ["events:write", "voice:stream"],
        "recent_device_events": [],
        "created_at": now,
        "updated_at": now,
    }
    with _store_lock:
        if path.exists():
            raise DataIntegrityError("base is already provisioned")
        _write_json(path, result)
    return deepcopy(result)


def rotate_production_device_credential(
    base_id: str,
    *,
    device_credential: str,
) -> dict:
    """Explicitly rotate one factory credential and grant current device scopes."""
    base_id = validate_resource_id(base_id, "base_id")
    credential_base_id, _ = _scoped_secret(
        device_credential,
        "device_credential",
    )
    if credential_base_id != base_id:
        raise ValueError("device credential does not belong to base_id")
    path = BASES_DIR / f"{base_id}.json"
    with _store_lock:
        base = _read_json(path)
        if (
            not isinstance(base, dict)
            or base.get("schema_version") != 2
            or base.get("base_id") != base_id
            or base.get("device_credential_kind") != "production"
        ):
            raise DataIntegrityError("production base is not provisioned")
        updated = deepcopy(base)
        updated["device_credential_hash"] = _credential_hash(device_credential)
        updated["device_credential_status"] = "active"
        updated["device_credential_scope"] = ["events:write", "voice:stream"]
        updated.pop("device_credential_revoked_at", None)
        updated["updated_at"] = _now_iso()
        _write_json(path, updated)
        return deepcopy(updated)


def claim_base(pairing_token: str, *, owner_user_id: str) -> tuple[dict, bool]:
    """Claim a provisioned base. Returns (base, newly_claimed)."""
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    try:
        base_id, _ = _scoped_secret(pairing_token.strip(), "pairing_token")
    except ValueError as exc:
        raise InvalidPairingTokenError("invalid pairing token") from exc
    path = BASES_DIR / f"{base_id}.json"
    with _store_lock:
        base = _read_json(path)
        if (
            not isinstance(base, dict)
            or base.get("schema_version") != 2
            or base.get("base_id") != base_id
            or base.get("provisioning_state") != "ready"
            or not hmac.compare_digest(
                str(base.get("pairing_token_hash", "")),
                _credential_hash(pairing_token.strip()),
            )
        ):
            raise InvalidPairingTokenError("invalid pairing token")
        current_owner = base_owner_id(base)
        if current_owner == owner_user_id:
            owned = get_base_for_owner(base_id, owner_user_id)
            if not owned:
                raise DataIntegrityError("owned base record is malformed")
            return owned, False
        if current_owner is not None:
            raise BaseAlreadyBoundError("base belongs to another account")
        if list_bases_for_owner(owner_user_id):
            raise AccountAlreadyHasBaseError("account already owns another base")
        result = deepcopy(base)
        result.update(
            owner_user_id=owner_user_id,
            bound_user_id=owner_user_id,
            active_figure_id=None,
            status="bound",
            bound_at=_now_iso(),
            updated_at=_now_iso(),
        )
        _write_json(path, result)
        return result, True


def save_base(base_id: str, data: dict, *, owner_user_id: str) -> dict:
    base_id = validate_resource_id(base_id, "base_id")
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    declared_owners = {
        str(data[key])
        for key in ("owner_user_id", "owner_id", "bound_user_id")
        if data.get(key)
    }
    if len(declared_owners) > 1 or (
        declared_owners and next(iter(declared_owners)) != owner_user_id
    ):
        raise DataIntegrityError("base owner cannot be changed by save_base")
    result = deepcopy(data)
    result.update(
        schema_version=2,
        base_id=base_id,
        owner_user_id=owner_user_id,
        bound_user_id=owner_user_id,
    )
    result.pop("owner_id", None)
    path = BASES_DIR / f"{base_id}.json"
    with _store_lock:
        existing = _read_json(path)
        if existing is not None and (
            not isinstance(existing, dict)
            or existing.get("schema_version") != 2
            or existing.get("owner_user_id") != owner_user_id
            or base_owner_id(existing) != owner_user_id
        ):
            raise DataIntegrityError("existing base cannot be claimed or reassigned")
        _write_json(path, result)
    return result


def get_base(base_id: str) -> Optional[dict]:
    base_id = validate_resource_id(base_id, "base_id")
    data = _read_json(BASES_DIR / f"{base_id}.json")
    return deepcopy(data) if isinstance(data, dict) else None


def get_base_for_owner(base_id: str, owner_user_id: str) -> Optional[dict]:
    base_id = validate_resource_id(base_id, "base_id")
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    base = get_base(base_id)
    if (
        not base
        or base.get("schema_version") != 2
        or base.get("base_id") != base_id
        or base.get("owner_user_id") != owner_user_id
        or base_owner_id(base) != owner_user_id
    ):
        return None
    result = deepcopy(base)
    result.update(
        schema_version=2,
        owner_user_id=owner_user_id,
        bound_user_id=owner_user_id,
    )
    result.pop("owner_id", None)
    return result


def list_bases() -> list[dict]:
    results: list[dict] = []
    for path in sorted(BASES_DIR.glob("*.json")):
        data = _read_json(path)
        if isinstance(data, dict):
            results.append(deepcopy(data))
    return results


def list_bases_for_owner(owner_user_id: str) -> list[dict]:
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    results: list[dict] = []
    for path in sorted(BASES_DIR.glob("*.json")):
        try:
            base = get_base_for_owner(path.stem, owner_user_id)
        except ValueError:
            continue
        if base:
            results.append(base)
    return results


def delete_base(base_id: str, *, owner_user_id: str) -> bool:
    if not get_base_for_owner(base_id, owner_user_id):
        return False
    path = BASES_DIR / f"{validate_resource_id(base_id, 'base_id')}.json"
    with _store_lock:
        if not path.exists():
            return False
        path.unlink()
    return True


def revoke_device_credential(base_id: str, *, owner_user_id: str) -> dict:
    """Revoke a provisioned device identity without exposing its secret."""
    with _store_lock:
        base = get_base_for_owner(base_id, owner_user_id)
        if not base:
            raise DataIntegrityError("base is not owned by this user")
        base["device_credential_status"] = "revoked"
        base["device_credential_revoked_at"] = _now_iso()
        base["updated_at"] = _now_iso()
        return save_base(base_id, base, owner_user_id=owner_user_id)


def register_device_event(
    base_id: str,
    event_id: str,
    occurred_at: datetime,
    *,
    owner_user_id: str,
    max_clock_skew_seconds: int = 300,
) -> None:
    """Atomically reserve one production event ID and reject stale replays."""
    base_id = validate_resource_id(base_id, "base_id")
    event_id = validate_resource_id(event_id, "event_id")
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if abs((now - occurred_at.astimezone(timezone.utc)).total_seconds()) > max_clock_skew_seconds:
        raise DeviceEventReplayError("device event timestamp is outside the accepted window")
    with _store_lock:
        base = get_base_for_owner(base_id, owner_user_id)
        if not base:
            raise DataIntegrityError("base is not owned by this user")
        recent = [
            item for item in base.get("recent_device_events", [])
            if isinstance(item, dict) and item.get("event_id")
        ]
        if any(item["event_id"] == event_id for item in recent):
            raise DeviceEventReplayError("device event was already accepted")
        recent.append(
            {
                "event_id": event_id,
                "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
                "received_at": now.isoformat(),
            }
        )
        base["recent_device_events"] = recent[-128:]
        base["updated_at"] = now.isoformat()
        save_base(base_id, base, owner_user_id=owner_user_id)


# ============== Figure ==============

def save_figure(figure_id: str, data: dict, *, user_id: str) -> dict:
    figure_id = validate_resource_id(figure_id, "figure_id")
    user_id = validate_resource_id(user_id, "user_id")
    result = _prepare_owned_record(data, user_id)
    result["figure_id"] = figure_id
    path = _user_figures_dir(user_id, create=True) / f"{figure_id}.json"
    _write_json(path, result)
    return result


def get_figure(figure_id: str, *, user_id: str) -> Optional[dict]:
    figure_id = validate_resource_id(figure_id, "figure_id")
    user_id = validate_resource_id(user_id, "user_id")
    path = _user_figures_dir(user_id) / f"{figure_id}.json"
    result = _owned_record(_read_json(path), user_id)
    if not result or result.get("figure_id") != figure_id:
        return None
    return result


def update_figure_atomic(
    figure_id: str,
    mutate: Callable[[dict], Optional[dict]],
    *,
    user_id: str,
) -> dict:
    """Read, optionally mutate and replace one figure under the store lock."""
    figure_id = validate_resource_id(figure_id, "figure_id")
    user_id = validate_resource_id(user_id, "user_id")
    path = _user_figures_dir(user_id, create=True) / f"{figure_id}.json"
    with _store_lock:
        current = _owned_record(_read_json(path), user_id)
        if not current or current.get("figure_id") != figure_id:
            raise DataIntegrityError("figure is not owned by this user")
        updated = mutate(deepcopy(current))
        if updated is None:
            return deepcopy(current)
        if not isinstance(updated, dict):
            raise DataIntegrityError("figure mutation must return a record")
        saved = _prepare_owned_record(updated, user_id)
        saved["figure_id"] = figure_id
        saved["updated_at"] = _now_iso()
        _write_json(path, saved)
        return deepcopy(saved)


def list_figures(*, user_id: str) -> list[dict]:
    user_id = validate_resource_id(user_id, "user_id")
    directory = _user_figures_dir(user_id)
    if not directory.exists():
        return []
    results: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = get_figure(path.stem, user_id=user_id)
        except ValueError:
            continue
        if data:
            results.append(data)
    return results


def delete_figure(figure_id: str, *, user_id: str) -> bool:
    if not get_figure(figure_id, user_id=user_id):
        return False
    path = _user_figures_dir(user_id) / f"{validate_resource_id(figure_id, 'figure_id')}.json"
    with _store_lock:
        if not path.exists():
            return False
        path.unlink()
    return True


def _activation_writes(
    base_id: str,
    figure: dict,
    owner_user_id: str,
    *,
    now: str,
) -> dict[Path, Any]:
    base = get_base_for_owner(base_id, owner_user_id)
    if not base:
        raise DataIntegrityError("base is not owned by this user")
    figure_id = validate_resource_id(str(figure.get("figure_id", "")), "figure_id")
    current = _prepare_owned_record(figure, owner_user_id)
    current["figure_id"] = figure_id
    writes: dict[Path, Any] = {}

    for other in list_bases_for_owner(owner_user_id):
        if other["base_id"] != base_id and other.get("active_figure_id") == figure_id:
            other["active_figure_id"] = None
            other["status"] = "bound"
            other["updated_at"] = now
            writes[BASES_DIR / f"{other['base_id']}.json"] = other

    previous_figure_id = base.get("active_figure_id")
    if previous_figure_id and previous_figure_id != figure_id:
        previous = get_figure(str(previous_figure_id), user_id=owner_user_id)
        if previous:
            previous["base_id"] = None
            previous["updated_at"] = now
            writes[
                _user_figures_dir(owner_user_id, create=True)
                / f"{previous_figure_id}.json"
            ] = previous

    current["base_id"] = base_id
    current["updated_at"] = now
    writes[
        _user_figures_dir(owner_user_id, create=True) / f"{figure_id}.json"
    ] = current

    base["active_figure_id"] = figure_id
    base["status"] = "waiting"
    base["activation_revision"] = str(uuid.uuid4())
    base["updated_at"] = now
    writes[BASES_DIR / f"{base_id}.json"] = base
    return writes


def activate_figure(
    base_id: str,
    figure_id: str,
    *,
    owner_user_id: str,
) -> tuple[dict, dict]:
    """Atomically make one owned figure active on one owned base."""
    base_id = validate_resource_id(base_id, "base_id")
    figure_id = validate_resource_id(figure_id, "figure_id")
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    with _store_lock:
        _recover_pending_transactions()
        figure = get_figure(figure_id, user_id=owner_user_id)
        if not figure:
            raise DataIntegrityError("figure is not owned by this user")
        _write_json_transaction(
            _activation_writes(
                base_id,
                figure,
                owner_user_id,
                now=_now_iso(),
            )
        )
        saved_base = get_base_for_owner(base_id, owner_user_id)
        saved_figure = get_figure(figure_id, user_id=owner_user_id)
        if not saved_base or not saved_figure:
            raise DataIntegrityError("activation transaction did not persist")
        return saved_base, saved_figure


def create_figure_idempotent(
    figure_id: str,
    data: dict,
    *,
    user_id: str,
    creation_request_id: Optional[str] = None,
    activate_base_id: Optional[str] = None,
) -> tuple[dict, bool]:
    """Create once per owner/request and optionally activate in one transaction."""
    figure_id = validate_resource_id(figure_id, "figure_id")
    user_id = validate_resource_id(user_id, "user_id")
    if creation_request_id is not None:
        creation_request_id = validate_resource_id(
            creation_request_id,
            "creation_request_id",
        )
    if activate_base_id is not None:
        activate_base_id = validate_resource_id(activate_base_id, "base_id")

    with _store_lock:
        _recover_pending_transactions()
        if creation_request_id:
            for existing in list_figures(user_id=user_id):
                if existing.get("creation_request_id") == creation_request_id:
                    if activate_base_id:
                        _write_json_transaction(
                            _activation_writes(
                                activate_base_id,
                                existing,
                                user_id,
                                now=_now_iso(),
                            )
                        )
                        existing = get_figure(
                            str(existing["figure_id"]),
                            user_id=user_id,
                        )
                        if not existing:
                            raise DataIntegrityError(
                                "idempotent activation did not persist"
                            )
                    return existing, False

        result = _prepare_owned_record(data, user_id)
        result["figure_id"] = figure_id
        if creation_request_id:
            result["creation_request_id"] = creation_request_id
        path = _user_figures_dir(user_id, create=True) / f"{figure_id}.json"
        if path.exists():
            raise DataIntegrityError("figure id already exists")
        if activate_base_id:
            writes = _activation_writes(
                activate_base_id,
                result,
                user_id,
                now=_now_iso(),
            )
        else:
            writes = {path: result}
        _write_json_transaction(writes)
        saved = get_figure(figure_id, user_id=user_id)
        if not saved:
            raise DataIntegrityError("figure creation transaction did not persist")
        return saved, True


def unbind_base(base_id: str, *, owner_user_id: str) -> dict:
    """Persistently detach a base while preserving its factory identity."""
    base_id = validate_resource_id(base_id, "base_id")
    owner_user_id = validate_resource_id(owner_user_id, "owner_user_id")
    with _store_lock:
        _recover_pending_transactions()
        base = get_base_for_owner(base_id, owner_user_id)
        if not base:
            raise DataIntegrityError("base is not owned by this user")
        now = _now_iso()
        writes: dict[Path, Any] = {}
        for figure in list_figures(user_id=owner_user_id):
            if figure.get("base_id") == base_id:
                figure["base_id"] = None
                figure["updated_at"] = now
                writes[
                    _user_figures_dir(owner_user_id, create=True)
                    / f"{figure['figure_id']}.json"
                ] = figure

        unbound = deepcopy(base)
        for field in (
            "owner_user_id",
            "bound_user_id",
            "owner_id",
            "bound_at",
            "activation_revision",
        ):
            unbound.pop(field, None)
        unbound.update(
            schema_version=2,
            base_id=base_id,
            active_figure_id=None,
            status="unbound",
            unbound_at=now,
            updated_at=now,
        )
        writes[BASES_DIR / f"{base_id}.json"] = unbound
        _write_json_transaction(writes)
        return unbound


# ============== Archetypes ==============

ARCHETYPES_FILE = ARCHETYPES_DIR / "archetypes.json"


def get_archetypes() -> list[dict]:
    data = _read_json(ARCHETYPES_FILE)
    return data if isinstance(data, list) else []


def save_archetypes(archetypes: list[dict]) -> list[dict]:
    _write_json(ARCHETYPES_FILE, archetypes)
    return archetypes


# ============== Events ==============

def _events_file(year_month: str, user_id: str, *, create: bool = False) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}", year_month):
        raise ValueError("year_month must use YYYY-MM")
    return _user_events_dir(user_id, create=create) / f"{year_month}.json"


def save_event(event_data: dict, *, user_id: str) -> dict:
    result = _prepare_owned_record(event_data, user_id)
    year_month = str(result.get("triggered_at", _now_iso()))[:7]
    path = _events_file(year_month, user_id, create=True)
    with _store_lock:
        events = _read_json(path) or []
        if not isinstance(events, list):
            raise DataIntegrityError("event file is not a list")
        events.append(result)
        _write_json(path, events)
    return result


def list_events(
    *,
    user_id: str,
    base_id: Optional[str] = None,
    figure_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    user_id = validate_resource_id(user_id, "user_id")
    if base_id:
        validate_resource_id(base_id, "base_id")
    if figure_id:
        validate_resource_id(figure_id, "figure_id")
    directory = _user_events_dir(user_id)
    all_events: list[dict] = []
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            monthly = _read_json(path) or []
            if isinstance(monthly, list):
                for event in monthly:
                    owned = _owned_record(event, user_id)
                    if owned:
                        all_events.append(owned)
    if base_id:
        all_events = [item for item in all_events if item.get("base_id") == base_id]
    if figure_id:
        all_events = [item for item in all_events if item.get("figure_id") == figure_id]
    if from_date:
        all_events = [item for item in all_events if item.get("triggered_at", "") >= from_date]
    if to_date:
        all_events = [item for item in all_events if item.get("triggered_at", "") <= to_date]
    all_events.sort(key=lambda item: item.get("triggered_at", ""), reverse=True)
    return all_events[: max(0, min(limit, 500))]


# ============== Dialogue Logs ==============

def _dialogue_logs_file(year_month: str, user_id: str, *, create: bool = False) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}", year_month):
        raise ValueError("year_month must use YYYY-MM")
    return _user_dialogue_logs_dir(user_id, create=create) / f"{year_month}.json"


def save_dialogue_log(log_data: dict, *, user_id: str) -> dict:
    result = _prepare_owned_record(log_data, user_id)
    year_month = str(result.get("created_at", _now_iso()))[:7]
    path = _dialogue_logs_file(year_month, user_id, create=True)
    with _store_lock:
        logs = _read_json(path) or []
        if not isinstance(logs, list):
            raise DataIntegrityError("dialogue log file is not a list")
        logs.append(result)
        _write_json(path, logs)
    return result


def save_dialogue_turn(
    figure_id: str,
    figure: dict,
    log_data: dict,
    *,
    user_id: str,
) -> tuple[dict, dict]:
    """Commit the updated figure and its dialogue log as one recoverable unit."""
    figure_id = validate_resource_id(figure_id, "figure_id")
    user_id = validate_resource_id(user_id, "user_id")
    saved_figure = _prepare_owned_record(figure, user_id)
    saved_figure["figure_id"] = figure_id
    saved_log = _prepare_owned_record(log_data, user_id)
    if saved_log.get("figure_id") != figure_id:
        raise DataIntegrityError("dialogue log figure does not match updated figure")
    year_month = str(saved_log.get("created_at", _now_iso()))[:7]
    log_path = _dialogue_logs_file(year_month, user_id, create=True)
    figure_path = _user_figures_dir(user_id, create=True) / f"{figure_id}.json"
    with _store_lock:
        _recover_pending_transactions()
        current_figure = _owned_record(_read_json(figure_path), user_id)
        if current_figure:
            current_memory = current_figure.get("memory", {})
            saved_memory = saved_figure.setdefault("memory", {})
            for field in _MANAGED_MEMORY_FIELDS:
                if field in current_memory:
                    saved_memory[field] = deepcopy(current_memory[field])
        logs = _read_json(log_path) or []
        if not isinstance(logs, list):
            raise DataIntegrityError("dialogue log file is not a list")
        logs.append(saved_log)
        _write_json_transaction(
            {
                figure_path: saved_figure,
                log_path: logs,
            }
        )
    return saved_figure, saved_log


def list_dialogue_logs(
    *,
    user_id: str,
    figure_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    user_id = validate_resource_id(user_id, "user_id")
    if figure_id:
        validate_resource_id(figure_id, "figure_id")
    directory = _user_dialogue_logs_dir(user_id)
    all_logs: list[dict] = []
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            monthly = _read_json(path) or []
            if isinstance(monthly, list):
                for log in monthly:
                    owned = _owned_record(log, user_id)
                    if owned:
                        all_logs.append(owned)
    if figure_id:
        all_logs = [item for item in all_logs if item.get("figure_id") == figure_id]
    if from_date:
        all_logs = [item for item in all_logs if item.get("created_at", "") >= from_date]
    if to_date:
        all_logs = [item for item in all_logs if item.get("created_at", "") <= to_date]
    all_logs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return all_logs[: max(0, min(limit, 500))]


# ============== Sync Queue ==============

def _sync_queue_file(user_id: str, *, create: bool = False) -> Path:
    return _user_sync_dir(user_id, create=create) / "sync_queue.json"


def _read_sync_queue(user_id: str) -> dict:
    data = _read_json(_sync_queue_file(user_id))
    if not isinstance(data, dict):
        return {
            "schema_version": 2,
            "owner_user_id": user_id,
            "items": [],
            "created_at": _now_iso(),
        }
    owned = _owned_record(data, user_id)
    if owned is None:
        raise DataIntegrityError("sync queue owner mismatch")
    owned.setdefault("items", [])
    return owned


def _write_sync_queue(data: dict, user_id: str) -> dict:
    result = _prepare_owned_record(data, user_id)
    _write_json(_sync_queue_file(user_id, create=True), result)
    return result


def get_sync_queue(*, user_id: str) -> dict:
    return _read_sync_queue(validate_resource_id(user_id, "user_id"))


def append_sync_item(
    figure_id: str,
    item_type: str,
    item_data: dict,
    *,
    user_id: str,
) -> dict:
    user_id = validate_resource_id(user_id, "user_id")
    figure_id = validate_resource_id(figure_id, "figure_id")
    with _store_lock:
        queue = _read_sync_queue(user_id)
        item = {
            "schema_version": 2,
            "owner_user_id": user_id,
            "queue_id": str(uuid.uuid4()),
            "figure_id": figure_id,
            "type": item_type,
            "data": deepcopy(item_data),
            "sync_status": "pending",
            "created_at": _now_iso(),
        }
        queue.setdefault("items", []).append(item)
        queue["updated_at"] = _now_iso()
        return _write_sync_queue(queue, user_id)


def flush_sync_queue(queue_id: Optional[str] = None, *, user_id: str) -> dict:
    user_id = validate_resource_id(user_id, "user_id")
    if queue_id:
        validate_resource_id(queue_id, "queue_id")
    with _store_lock:
        queue = _read_sync_queue(user_id)
        now = _now_iso()
        for item in queue.get("items", []):
            if item.get("sync_status") == "pending" and (
                queue_id is None or item.get("queue_id") == queue_id
            ):
                item["sync_status"] = "synced"
                item["synced_at"] = now
        queue["updated_at"] = now
        return _write_sync_queue(queue, user_id)


# ============== Cloud Sync ==============

def _cloud_data_file(user_id: str, *, create: bool = False) -> Path:
    return _user_sync_dir(user_id, create=create) / "cloud_data.json"


def save_cloud_data(user_id: str, data: dict) -> dict:
    user_id = validate_resource_id(user_id, "user_id")
    result = _prepare_owned_record(data, user_id)
    result["synced_at"] = _now_iso()
    _write_json(_cloud_data_file(user_id, create=True), result)
    return result


def get_cloud_data(user_id: str) -> dict:
    user_id = validate_resource_id(user_id, "user_id")
    data = _read_json(_cloud_data_file(user_id))
    if data is None:
        return {
            "schema_version": 2,
            "owner_user_id": user_id,
            "figures": [],
            "dialogue_logs": [],
            "events": [],
            "synced_at": None,
        }
    result = _owned_record(data, user_id)
    if result is None:
        raise DataIntegrityError("cloud snapshot owner mismatch")
    result.setdefault("figures", [])
    result.setdefault("dialogue_logs", [])
    result.setdefault("events", [])
    return result


# ============== Voice Uploads ==============

def resolve_voice_reference(path: str, *, storage_key: str) -> Path:
    """Allow a reference only within the authenticated owner/figure upload scope."""
    if not isinstance(path, str) or not path:
        raise ValueError("voice reference is unavailable")
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("voice reference must be an absolute upload path")
    resolved = candidate.resolve(strict=True)
    parts = resolved.relative_to(USER_DATA_DIR).parts
    if (
        len(parts) != 4
        or parts[1] != "voice_uploads"
        or figure_storage_key(parts[0], parts[2]) != storage_key
        or not resolved.is_file()
    ):
        raise ValueError("voice reference does not belong to this owner and figure")
    return resolved


def get_voice_upload_dir(figure_id: str, *, user_id: str) -> Path:
    figure_id = validate_resource_id(figure_id, "figure_id")
    return _ensure_directory(_user_voice_uploads_dir(user_id, create=True) / figure_id)


def save_voice_upload(
    figure_id: str,
    filename: str,
    content: bytes,
    *,
    user_id: str,
) -> Path:
    import time

    upload_dir = get_voice_upload_dir(figure_id, user_id=user_id)
    safe_filename = Path(filename).name or "recording.bin"
    safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", safe_filename)[:120]
    path = upload_dir / f"{int(time.time() * 1000)}_{safe_filename}"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return path
