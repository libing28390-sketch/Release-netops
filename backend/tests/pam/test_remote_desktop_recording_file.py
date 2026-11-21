from __future__ import annotations

from services.pam_recording_storage import _is_stable_guac_file


def test_completed_guac_recording_requires_a_nonempty_stable_regular_file(tmp_path):
    missing_path = tmp_path / "missing.guac"
    empty_path = tmp_path / "empty.guac"
    good_path = tmp_path / "recording.guac"
    empty_path.write_bytes(b"")
    good_path.write_bytes(b"1.size,1.1,1;\n")

    assert not _is_stable_guac_file(missing_path)
    assert not _is_stable_guac_file(empty_path)
    assert _is_stable_guac_file(good_path)
