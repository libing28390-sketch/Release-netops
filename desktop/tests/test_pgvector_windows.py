from __future__ import annotations

import hashlib
import zipfile

import pytest

from desktop.pgvector_windows import (
    PGVECTOR_WINDOWS_ASSETS,
    PgvectorWindowsAsset,
    asset_for_postgres_major,
    extract_extension_files,
    verify_asset_digest,
)


def test_pgvector_windows_assets_are_pinned_for_supported_postgres_versions():
    assert tuple(sorted(PGVECTOR_WINDOWS_ASSETS)) == (13, 14, 15, 16, 17, 18)
    asset = asset_for_postgres_major(17)
    assert asset.filename == "vector.v0.8.6-pg17.zip"
    assert asset.url.endswith("/0.8.6_17/vector.v0.8.6-pg17.zip")
    assert len(asset.sha256) == 64


def test_extract_extension_files_only_stages_required_members(tmp_path):
    archive_path = tmp_path / "pgvector.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("release/lib/vector.dll", b"dll")
        archive.writestr("release/share/extension/vector.control", b"control")
        archive.writestr("release/share/extension/vector--0.8.6.sql", b"sql")
        archive.writestr("release/README.md", b"ignored")

    staged = extract_extension_files(archive_path, tmp_path / "staged")

    assert set(staged) == {"vector.dll", "vector.control", "vector--0.8.6.sql"}
    assert staged["vector.dll"].read_bytes() == b"dll"
    assert staged["vector.control"].read_bytes() == b"control"
    assert staged["vector--0.8.6.sql"].read_bytes() == b"sql"


def test_extract_extension_files_rejects_archives_without_sql(tmp_path):
    archive_path = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("lib/vector.dll", b"dll")
        archive.writestr("share/extension/vector.control", b"control")

    with pytest.raises(RuntimeError, match=r"vector--\*\.sql"):
        extract_extension_files(archive_path, tmp_path / "staged")


def test_extract_extension_files_rejects_case_insensitive_duplicates(tmp_path):
    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("lib/vector.dll", b"dll")
        archive.writestr("share/extension/vector.control", b"control")
        archive.writestr("share/extension/vector--0.8.6.sql", b"sql")
        archive.writestr("share/extension/VECTOR--0.8.6.SQL", b"duplicate")

    with pytest.raises(RuntimeError, match="重复成员"):
        extract_extension_files(archive_path, tmp_path / "staged")


def test_verify_asset_digest_reports_tampering(tmp_path):
    archive_path = tmp_path / "asset.zip"
    archive_path.write_bytes(b"trusted content")
    asset = PgvectorWindowsAsset(17, archive_path.name, hashlib.sha256(b"other").hexdigest())

    with pytest.raises(RuntimeError, match="SHA-256 不匹配"):
        verify_asset_digest(archive_path, asset)
