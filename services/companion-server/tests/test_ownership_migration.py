"""Run explicitly: python -B tests/test_ownership_migration.py."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True

from scripts import ownership_migration as migration


class OwnershipMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lingou-ownership-migration-")
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name).resolve() / "data"
        self.data_dir.mkdir()
        self.owner = "USER-A"
        self.other_owner = "USER-B"
        self._write_json(
            "users.json",
            {
                "users": [
                    {"user_id": self.owner, "username": "alice"},
                    {"user_id": self.other_owner, "username": "bob"},
                ]
            },
        )

    def _path(self, relative: str) -> Path:
        return self.data_dir / relative

    def _write_json(self, relative: str, value) -> Path:
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _manifest(self, entries: list[dict]) -> Path:
        path = Path(self.temporary.name) / "manifest.json"
        path.write_text(
            json.dumps({"schema_version": 1, "entries": entries}),
            encoding="utf-8",
        )
        return path

    def _entry(
        self,
        source: str,
        target_type: str,
        target_id: str,
        *,
        owner: str | None = None,
        digest: str | None = None,
    ) -> dict:
        return {
            "source": source,
            "owner_user_id": owner or self.owner,
            "sha256": digest or self._digest(self._path(source)),
            "target": {"type": target_type, "id": target_id},
        }

    def test_inventory_is_review_only_and_does_not_infer_owner(self):
        source = self._write_json("figures/FIG-1.json", {"name": "fixture"})
        before = source.read_bytes()

        result = migration.inventory(self.data_dir)

        self.assertEqual(result["mode"], "inventory_only")
        self.assertEqual(len(result["entries"]), 1)
        item = result["entries"][0]
        self.assertEqual(item["source"], "figures/FIG-1.json")
        self.assertIsNone(item["owner_user_id"])
        self.assertEqual(item["review_status"], "owner_required")
        self.assertEqual(item["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse((self.data_dir / migration.MIGRATION_DIR_NAME).exists())

    def test_namespaced_legacy_is_inventoried_without_owner_inference(self):
        legacy = self._write_json(
            "user_data/USER-A/figures/FIG-1.json",
            {"figure_id": "FIG-1", "name": "legacy"},
        )
        self._write_json(
            "user_data/USER-B/figures/CURRENT.json",
            {
                "schema_version": 2,
                "owner_user_id": "USER-B",
                "figure_id": "CURRENT",
                "name": "current",
            },
        )
        self._write_json(
            "bases/CURRENT-BASE.json",
            {
                "schema_version": 2,
                "owner_user_id": "USER-B",
                "bound_user_id": "USER-B",
                "base_id": "CURRENT-BASE",
            },
        )

        result = migration.inventory(self.data_dir)

        self.assertEqual(
            [item["source"] for item in result["entries"]],
            ["user_data/USER-A/figures/FIG-1.json"],
        )
        self.assertIsNone(result["entries"][0]["owner_user_id"])
        self.assertEqual(result["entries"][0]["sha256"], self._digest(legacy))

    def test_unbound_provisioned_base_is_not_treated_as_legacy(self):
        self._write_json(
            "bases/BASE-PROVISIONED.json",
            {
                "schema_version": 2,
                "base_id": "BASE-PROVISIONED",
                "active_figure_id": None,
                "status": "unbound",
                "provisioning_state": "ready",
                "pairing_token_hash": "a" * 64,
                "device_credential_hash": "b" * 64,
            },
        )

        result = migration.inventory(self.data_dir)

        self.assertEqual(result["entries"], [])

    def test_namespaced_legacy_can_be_explicitly_migrated_in_place(self):
        source = self._write_json(
            "user_data/USER-A/figures/FIG-1.json",
            {"figure_id": "FIG-1", "name": "legacy"},
        )
        original = source.read_bytes()
        digest = self._digest(source)
        manifest = self._manifest(
            [
                self._entry(
                    "user_data/USER-A/figures/FIG-1.json",
                    "figure",
                    "FIG-1",
                )
            ]
        )

        migration.plan_or_apply(self.data_dir, manifest, commit=True)

        migrated = json.loads(source.read_text(encoding="utf-8"))
        archive = self._path(
            f".ownership_migration/legacy_sources/{digest}/"
            "user_data/USER-A/figures/FIG-1.json"
        )
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["owner_user_id"], self.owner)
        replay = migration.plan_or_apply(self.data_dir, manifest, commit=True)
        self.assertEqual(replay["entries"][0]["status"], "already_applied")

    def test_apply_defaults_to_dry_run_and_never_writes(self):
        source = self._write_json("figures/FIG-1.json", {"name": "fixture"})
        manifest = self._manifest([self._entry("figures/FIG-1.json", "figure", "FIG-1")])

        result = migration.plan_or_apply(self.data_dir, manifest)

        self.assertEqual(result["mode"], "dry_run")
        self.assertFalse(result["committed"])
        self.assertEqual(result["entries"][0]["status"], "ready")
        self.assertFalse(self._path("user_data/USER-A/figures/FIG-1.json").exists())
        self.assertFalse((self.data_dir / migration.MIGRATION_DIR_NAME).exists())
        self.assertEqual(json.loads(source.read_text())["name"], "fixture")

    def test_commit_preserves_source_stamps_owner_and_is_idempotent(self):
        source = self._write_json("figures/FIG-1.json", {"name": "fixture"})
        source_bytes = source.read_bytes()
        manifest = self._manifest([self._entry("figures/FIG-1.json", "figure", "FIG-1")])

        first = migration.plan_or_apply(self.data_dir, manifest, commit=True)
        target = self._path("user_data/USER-A/figures/FIG-1.json")
        first_target_bytes = target.read_bytes()
        ledger = self._path(".ownership_migration/ledger.json")
        first_ledger = json.loads(ledger.read_text(encoding="utf-8"))
        second = migration.plan_or_apply(self.data_dir, manifest, commit=True)

        self.assertEqual(first["entries"][0]["status"], "ready")
        self.assertEqual(second["entries"][0]["status"], "already_applied")
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(target.read_bytes(), first_target_bytes)
        migrated = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["owner_user_id"], self.owner)
        self.assertEqual(migrated["figure_id"], "FIG-1")
        self.assertEqual(len(first_ledger["completed"]), 1)
        self.assertEqual(
            len(json.loads(ledger.read_text(encoding="utf-8"))["completed"]),
            1,
        )
        self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)

    def test_base_in_place_migration_archives_legacy_bytes_and_replays(self):
        source = self._write_json("bases/BASE-1.json", {"base_id": "BASE-1", "name": "fixture"})
        source_bytes = source.read_bytes()
        digest = self._digest(source)
        manifest = self._manifest([self._entry("bases/BASE-1.json", "base", "BASE-1")])

        migration.plan_or_apply(self.data_dir, manifest, commit=True)
        migrated = json.loads(source.read_text(encoding="utf-8"))
        archive = self._path(
            f".ownership_migration/legacy_sources/{digest}/bases/BASE-1.json"
        )
        replay = migration.plan_or_apply(self.data_dir, manifest, commit=True)

        self.assertEqual(archive.read_bytes(), source_bytes)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(migrated["owner_user_id"], self.owner)
        self.assertEqual(migrated["bound_user_id"], self.owner)
        self.assertEqual(replay["entries"][0]["status"], "already_applied")

    def test_rejects_unregistered_owner_and_invalid_identifiers(self):
        self._write_json("figures/FIG-1.json", {"name": "fixture"})
        unregistered = self._manifest(
            [self._entry("figures/FIG-1.json", "figure", "FIG-1", owner="USER-C")]
        )
        with self.assertRaisesRegex(migration.MigrationError, "not a registered user"):
            migration.plan_or_apply(self.data_dir, unregistered, commit=True)

        invalid = self._manifest(
            [self._entry("figures/FIG-1.json", "figure", "../FIG-1")]
        )
        with self.assertRaisesRegex(migration.MigrationError, "target.id"):
            migration.plan_or_apply(self.data_dir, invalid, commit=True)

    def test_rejects_source_traversal_symlink_escape_and_wrong_source_kind(self):
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        escaped = self._manifest(
            [
                {
                    "source": "../outside.json",
                    "owner_user_id": self.owner,
                    "sha256": self._digest(outside),
                    "target": {"type": "figure", "id": "FIG-1"},
                }
            ]
        )
        with self.assertRaisesRegex(migration.MigrationError, "unsafe source"):
            migration.plan_or_apply(self.data_dir, escaped, commit=True)

        link = self._path("figures/FIG-1.json")
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        symlink_manifest = self._manifest(
            [
                {
                    "source": "figures/FIG-1.json",
                    "owner_user_id": self.owner,
                    "sha256": self._digest(outside),
                    "target": {"type": "figure", "id": "FIG-1"},
                }
            ]
        )
        with self.assertRaisesRegex(migration.MigrationError, "escapes data directory"):
            migration.plan_or_apply(self.data_dir, symlink_manifest, commit=True)

        link.unlink()
        self._write_json("events/2026-09.json", [])
        wrong_kind = self._manifest(
            [self._entry("events/2026-09.json", "figure", "FIG-1")]
        )
        with self.assertRaisesRegex(migration.MigrationError, "not allowed"):
            migration.plan_or_apply(self.data_dir, wrong_kind, commit=True)

    def test_rejects_hash_mismatch_declared_owner_and_target_collision(self):
        self._write_json("figures/FIG-1.json", {"name": "fixture"})
        bad_hash = self._manifest(
            [self._entry("figures/FIG-1.json", "figure", "FIG-1", digest="0" * 64)]
        )
        with self.assertRaisesRegex(migration.MigrationError, "does not match"):
            migration.plan_or_apply(self.data_dir, bad_hash, commit=True)

        self._write_json(
            "figures/FIG-1.json",
            {"name": "fixture", "owner_user_id": self.other_owner},
        )
        declared_owner = self._manifest(
            [self._entry("figures/FIG-1.json", "figure", "FIG-1")]
        )
        with self.assertRaisesRegex(migration.MigrationError, "different or conflicting owner"):
            migration.plan_or_apply(self.data_dir, declared_owner, commit=True)

        self._write_json("figures/FIG-1.json", {"name": "fixture"})
        collision_manifest = self._manifest(
            [self._entry("figures/FIG-1.json", "figure", "FIG-1")]
        )
        collision = self._write_json(
            "user_data/USER-A/figures/FIG-1.json",
            {"owner_user_id": self.owner, "name": "other"},
        )
        collision_bytes = collision.read_bytes()
        with self.assertRaisesRegex(migration.MigrationError, "target collision"):
            migration.plan_or_apply(self.data_dir, collision_manifest, commit=True)
        self.assertEqual(collision.read_bytes(), collision_bytes)
        self.assertFalse(self._path(".ownership_migration/ledger.json").exists())

    def test_source_change_after_planning_aborts_before_any_write(self):
        first = self._write_json("figures/ONE.json", {"name": "one"})
        second = self._write_json("figures/TWO.json", {"name": "two"})
        manifest = self._manifest(
            [
                self._entry("figures/ONE.json", "figure", "ONE"),
                self._entry("figures/TWO.json", "figure", "TWO"),
            ]
        )
        original_load_ledger = migration._load_ledger

        def mutate_after_manifest_validation(data_dir: Path) -> dict:
            second.write_text('{"name":"changed"}', encoding="utf-8")
            return original_load_ledger(data_dir)

        with mock.patch.object(
            migration,
            "_load_ledger",
            side_effect=mutate_after_manifest_validation,
        ):
            with self.assertRaisesRegex(migration.MigrationError, "changed during validation"):
                migration.plan_or_apply(self.data_dir, manifest, commit=True)

        self.assertTrue(first.exists())
        self.assertFalse(self._path("user_data/USER-A/figures/ONE.json").exists())
        self.assertFalse(self._path("user_data/USER-A/figures/TWO.json").exists())
        self.assertFalse(self._path(".ownership_migration/ledger.json").exists())

    def test_rejects_duplicate_targets_before_any_write(self):
        first = self._write_json("figures/ONE.json", {"name": "one"})
        second = self._write_json("figures/TWO.json", {"name": "two"})
        manifest = self._manifest(
            [
                self._entry("figures/ONE.json", "figure", "SAME"),
                self._entry("figures/TWO.json", "figure", "SAME"),
            ]
        )
        with self.assertRaisesRegex(migration.MigrationError, "duplicate target"):
            migration.plan_or_apply(self.data_dir, manifest, commit=True)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertFalse(self._path("user_data/USER-A/figures/SAME.json").exists())

    def test_rejects_duplicate_source_assignment_before_any_write(self):
        source = self._write_json("figures/ONE.json", {"name": "private"})
        manifest = self._manifest(
            [
                self._entry("figures/ONE.json", "figure", "ONE", owner=self.owner),
                self._entry(
                    "figures/ONE.json",
                    "figure",
                    "COPY",
                    owner=self.other_owner,
                ),
            ]
        )

        with self.assertRaisesRegex(migration.MigrationError, "duplicate source"):
            migration.plan_or_apply(self.data_dir, manifest, commit=True)

        self.assertTrue(source.exists())
        self.assertFalse(self._path("user_data/USER-A/figures/ONE.json").exists())
        self.assertFalse(self._path("user_data/USER-B/figures/COPY.json").exists())
        self.assertFalse(self._path(".ownership_migration/ledger.json").exists())

    def test_rejects_target_symlink_escape_before_any_write(self):
        self._write_json("figures/FIG-1.json", {"name": "fixture"})
        outside = Path(self.temporary.name) / "outside-target"
        outside.mkdir()
        self._path("user_data").symlink_to(outside, target_is_directory=True)
        manifest = self._manifest(
            [self._entry("figures/FIG-1.json", "figure", "FIG-1")]
        )

        with self.assertRaisesRegex(migration.MigrationError, "target escapes"):
            migration.plan_or_apply(self.data_dir, manifest, commit=True)

        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self._path(".ownership_migration/ledger.json").exists())

    def test_completed_source_cannot_be_reassigned_by_a_new_manifest(self):
        source = self._write_json("figures/FIG-1.json", {"name": "private"})
        first = self._entry("figures/FIG-1.json", "figure", "FIG-1")
        migration.plan_or_apply(self.data_dir, self._manifest([first]), commit=True)
        ledger = self._path(".ownership_migration/ledger.json")
        ledger_before = ledger.read_bytes()
        self._write_json("figures/NEW.json", {"name": "new"})

        reassignment = self._entry(
            "figures/FIG-1.json", "figure", "FIG-1", owner=self.other_owner
        )
        manifest = self._manifest([
            self._entry("figures/NEW.json", "figure", "NEW"),
            reassignment,
        ])
        for commit in (False, True):
            with self.subTest(commit=commit), self.assertRaisesRegex(
                migration.MigrationError, "source.*already"
            ):
                migration.plan_or_apply(self.data_dir, manifest, commit=commit)
        self.assertFalse(self._path("user_data/USER-B/figures/FIG-1.json").exists())
        self.assertFalse(self._path("user_data/USER-A/figures/NEW.json").exists())
        self.assertEqual(ledger.read_bytes(), ledger_before)
        self.assertEqual(json.loads(source.read_text())["name"], "private")

    def test_new_source_can_follow_a_completed_manifest(self):
        self._write_json("figures/ONE.json", {"name": "one"})
        first = self._entry("figures/ONE.json", "figure", "ONE")
        migration.plan_or_apply(self.data_dir, self._manifest([first]), commit=True)
        self._write_json("figures/TWO.json", {"name": "two"})
        second = self._entry(
            "figures/TWO.json", "figure", "TWO", owner=self.other_owner
        )
        result = migration.plan_or_apply(
            self.data_dir, self._manifest([first, second]), commit=True
        )
        self.assertEqual(
            [item["status"] for item in result["entries"]],
            ["already_applied", "ready"],
        )
        self.assertEqual(
            json.loads(self._path("user_data/USER-B/figures/TWO.json").read_text())[
                "owner_user_id"
            ],
            self.other_owner,
        )

    def test_monthly_records_and_sync_items_receive_owner(self):
        self._write_json("events/2026-09.json", [{"event_id": "EVENT-1"}])
        self._write_json(
            "sync_queue/sync_queue.json",
            {"items": [{"queue_id": "QUEUE-1", "data": {"value": 1}}]},
        )
        manifest = self._manifest(
            [
                self._entry("events/2026-09.json", "events", "2026-09"),
                self._entry("sync_queue/sync_queue.json", "sync_queue", "sync_queue"),
            ]
        )

        migration.plan_or_apply(self.data_dir, manifest, commit=True)

        event = json.loads(
            self._path("user_data/USER-A/events/2026-09.json").read_text(encoding="utf-8")
        )[0]
        queue = json.loads(
            self._path("user_data/USER-A/sync/sync_queue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(event["owner_user_id"], self.owner)
        self.assertEqual(queue["owner_user_id"], self.owner)
        self.assertEqual(queue["items"][0]["owner_user_id"], self.owner)

    def test_binary_voice_upload_is_copied_without_modifying_legacy_source(self):
        source = self._path("voice_uploads/FIG-1/sample.wav")
        source.parent.mkdir(parents=True)
        content = b"RIFF\x00\x01fixture-voice"
        source.write_bytes(content)
        inventory = migration.inventory(self.data_dir)
        manifest = self._manifest(
            [self._entry("voice_uploads/FIG-1/sample.wav", "voice_upload", "FIG-1")]
        )

        migration.plan_or_apply(self.data_dir, manifest, commit=True)

        target = self._path("user_data/USER-A/voice_uploads/FIG-1/sample.wav")
        inventory_item = next(
            item for item in inventory["entries"] if item["source"].endswith("sample.wav")
        )
        self.assertEqual(inventory_item["target"], {"type": "voice_upload", "id": "FIG-1"})
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_cli_apply_requires_manifest_and_commit_is_explicit(self):
        self.assertEqual(migration.main(["apply", "--data-dir", str(self.data_dir)]), 2)
        self.assertFalse(self._path(".ownership_migration/ledger.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
