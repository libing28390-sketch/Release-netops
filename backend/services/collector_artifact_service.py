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

    def publish(self, source: str | Path, *, config_version: int) -> dict[str, Any]:
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

        if self.current.exists():
            if self.previous.exists():
                shutil.rmtree(self.previous)
            self._copy_tree_atomic(self.current, self.previous)
        self._copy_tree_atomic(version_dir, self.current)
        self._sync_runtime(config_version=config_version, status="APPLIED")
        return {
            "status": "APPLIED",
            "config_version": int(config_version),
            "current_version": self.current_version(),
            "previous_version": self.previous_version(),
        }

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
