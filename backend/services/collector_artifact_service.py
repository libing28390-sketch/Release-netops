"""Filesystem handoff for a collector's versioned Last Known Good artifact.

The Control Plane compiles artifacts; a collection node applies them locally.
This small store implements the node-side invariant used by P0-T14/T15:
invalid or interrupted publishes never replace ``current`` and rollback always
has a concrete previous version to restore.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from services.monitoring_compiler import CompileError, validate_artifact


class ArtifactStoreError(RuntimeError):
    """A collector artifact cannot be safely applied or rolled back."""


def collector_artifact_is_current(
    artifact_path: str | Path,
    *,
    config_version: int,
    checksum: str,
) -> bool:
    """Return whether a compiled artifact is intact and already applied.

    This is a read-only predicate: it never creates or repairs collector
    directories, and treats absent or malformed artifacts as not current.
    """
    try:
        if isinstance(config_version, bool) or not isinstance(config_version, int) or config_version < 1:
            return False
        if not isinstance(checksum, str) or not checksum:
            return False

        raw_artifact_path = os.fspath(artifact_path)
        if not raw_artifact_path.strip() or Path(raw_artifact_path) == Path("."):
            return False
        source = Path(raw_artifact_path)
        collector_id: str | None = None
        for directory in (source, source.parent / "current", source.parent / "runtime"):
            manifest = validate_artifact(directory).get("manifest")
            if not isinstance(manifest, dict):
                return False
            current_collector_id = manifest.get("collector_id")
            if not isinstance(current_collector_id, str) or not current_collector_id.strip():
                return False
            if collector_id is None:
                collector_id = current_collector_id
            elif current_collector_id != collector_id:
                return False
            if type(manifest.get("config_version")) is not int or manifest["config_version"] != config_version:
                return False
            if manifest.get("checksum") != checksum:
                return False

        runtime_state = json.loads(
            (source.parent / "runtime" / "current_version.json").read_text(encoding="utf-8")
        )
        return (
            isinstance(runtime_state, dict)
            and type(runtime_state.get("config_version")) is int
            and runtime_state.get("config_version") == config_version
            and runtime_state.get("status") == "APPLIED"
        )
    except (CompileError, OSError, ValueError, TypeError):
        # Missing files, invalid encodings/JSON, and validation failures all
        # mean that the artifact cannot be proven current. Do not surface any
        # artifact contents (which can include credentials) to the caller.
        return False


class CollectorArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.versions = self.root / "versions"
        self.current = self.root / "current"
        self.previous = self.root / "previous"
        self.runtime = self.root / "runtime"
        self.queue = self.root / "queue"
        for directory in (self.versions, self.runtime, self.queue):
            directory.mkdir(parents=True, exist_ok=True)

    def _inside_root(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactStoreError("artifact path must stay inside collector root") from exc
        return resolved

    @staticmethod
    def _version_name(version: int) -> str:
        if int(version) < 1:
            raise ArtifactStoreError("config version must be positive")
        return f"{int(version):08d}"

    def _read_version(self, directory: Path) -> int:
        manifest = directory / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return int(payload["config_version"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ArtifactStoreError(f"invalid artifact manifest: {directory}") from exc

    def current_version(self) -> int | None:
        if not self.current.exists():
            return None
        return self._read_version(self.current)

    def previous_version(self) -> int | None:
        if not self.previous.exists():
            return None
        return self._read_version(self.previous)

    def _sync_runtime(self, *, config_version: int, status: str, **details: Any) -> None:
        """Expose the active artifact through the shared collector runtime path."""
        if not self.current.exists():
            raise ArtifactStoreError("current artifact is missing")
        self._copy_tree_atomic(self.current, self.runtime)
        runtime_state = {"config_version": int(config_version), "status": status, **details}
        (self.runtime / "current_version.json").write_text(
            json.dumps(runtime_state, indent=2) + "\n",
            encoding="utf-8",
        )

    def _copy_tree_atomic(self, source: Path, destination: Path) -> None:
        source = self._inside_root(source)
        destination = self._inside_root(destination)
        if not source.is_dir():
            raise ArtifactStoreError(f"artifact directory not found: {source}")
        temp = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex[:10]}")
        if temp.exists():
            shutil.rmtree(temp)
        shutil.copytree(source, temp)
        try:
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(temp, destination)
        except Exception:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
            raise

    def publish(
        self,
        source: str | Path,
        *,
        config_version: int,
        runtime_status: str = "APPLIED",
    ) -> dict[str, Any]:
        source_path = self._inside_root(Path(source))
        try:
            validation = validate_artifact(source_path)
        except CompileError as exc:
            raise ArtifactStoreError(str(exc)) from exc
        manifest_version = int(validation["manifest"].get("config_version") or 0)
        if manifest_version != int(config_version):
            raise ArtifactStoreError("artifact version does not match publish version")

        version_dir = self.versions / self._version_name(config_version)
        if source_path != version_dir:
            if version_dir.exists():
                shutil.rmtree(version_dir)
            self._copy_tree_atomic(source_path, version_dir)

        rotate_previous = False
        if self.current.exists():
            try:
                current_manifest = validate_artifact(self.current).get("manifest")
            except (CompileError, OSError, ValueError, TypeError):
                # A damaged current artifact cannot replace the last known good
                # copy, but it must not block publishing a validated source.
                current_manifest = None
            current_version = current_manifest.get("config_version") if isinstance(current_manifest, dict) else None
            if type(current_version) is int and current_version != int(config_version):
                try:
                    runtime_state = json.loads(
                        (self.runtime / "current_version.json").read_text(encoding="utf-8")
                    )
                except (OSError, ValueError, TypeError):
                    runtime_state = None
                current_is_confirmed = (
                    isinstance(runtime_state, dict)
                    and runtime_state.get("status") in {"APPLIED", "ROLLED_BACK"}
                    and type(runtime_state.get("config_version")) is int
                    and runtime_state["config_version"] == current_version
                )
                rotate_previous = current_is_confirmed

        if rotate_previous:
            if self.previous.exists():
                shutil.rmtree(self.previous)
            self._copy_tree_atomic(self.current, self.previous)
        self._copy_tree_atomic(version_dir, self.current)
        self._sync_runtime(config_version=config_version, status=runtime_status)
        return {
            "status": runtime_status,
            "config_version": int(config_version),
            "current_version": self.current_version(),
            "previous_version": self.previous_version(),
        }

    def mark_runtime_applied(self, config_version: int) -> dict[str, Any]:
        """Atomically mark the already-copied runtime artifact as applied."""
        expected_version = int(config_version)
        self._version_name(expected_version)
        if self._read_version(self.runtime) != expected_version:
            raise ArtifactStoreError("runtime artifact version does not match applied version")

        state_path = self.runtime / "current_version.json"
        try:
            runtime_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ArtifactStoreError("runtime state is invalid") from exc
        if (
            not isinstance(runtime_state, dict)
            or type(runtime_state.get("config_version")) is not int
            or runtime_state["config_version"] != expected_version
        ):
            raise ArtifactStoreError("runtime state version does not match applied version")

        runtime_state["status"] = "APPLIED"
        temp_path = state_path.with_name(f".{state_path.name}.tmp-{uuid.uuid4().hex[:10]}")
        try:
            with temp_path.open("w", encoding="utf-8") as state_file:
                json.dump(runtime_state, state_file, indent=2)
                state_file.write("\n")
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temp_path, state_path)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise ArtifactStoreError("could not update runtime state") from exc
        return {"status": "APPLIED", "config_version": expected_version}

    def rollback(self) -> dict[str, Any]:
        if not self.previous.exists():
            raise ArtifactStoreError("no previous Last Known Good artifact is available")
        previous_version = self.previous_version()
        if previous_version is None:
            raise ArtifactStoreError("previous artifact has no valid version")
        current_version = self.current_version()
        if self.current.exists():
            backup = self.root / f".rollback-backup-{uuid.uuid4().hex[:10]}"
            self._copy_tree_atomic(self.current, backup)
            try:
                shutil.rmtree(self.current)
                os.replace(self.previous, self.current)
                os.replace(backup, self.previous)
            except Exception:
                if not self.current.exists() and backup.exists():
                    os.replace(backup, self.current)
                raise
            finally:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
        else:
            os.replace(self.previous, self.current)
        self._sync_runtime(config_version=previous_version, status="ROLLED_BACK", from_version=current_version)
        return {
            "status": "ROLLED_BACK",
            "config_version": previous_version,
            "previous_version": self.previous_version(),
        }
