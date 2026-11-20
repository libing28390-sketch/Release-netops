from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.pam_remote_desktop import normalize_profile_payload


FINGERPRINT = "4CE56BB09B6F1B96A521AE58EFCEA743ECBB632A9C8D29F999D01CE47F9FF80E"


def test_rdp_profile_normalizes_certificate_fingerprint():
    profile = normalize_profile_payload("rdp", {"rdp_cert_fingerprint": FINGERPRINT.lower()})

    assert profile["rdp_cert_fingerprint"] == FINGERPRINT


def test_rdp_profile_rejects_malformed_certificate_fingerprint():
    with pytest.raises(HTTPException) as exc_info:
        normalize_profile_payload("rdp", {"rdp_cert_fingerprint": "AB:CD"})

    assert exc_info.value.status_code == 422


def test_vnc_profile_does_not_keep_rdp_certificate_fingerprint():
    profile = normalize_profile_payload("vnc", {"rdp_cert_fingerprint": FINGERPRINT})

    assert profile["rdp_cert_fingerprint"] == ""
