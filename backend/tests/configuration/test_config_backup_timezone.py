from datetime import datetime, timezone

from api.configs import _utc_now, _utc_now_iso
from services.config_backup_policy_service import _now as policy_now


def test_configs_utc_now_and_iso_format():
    dt = _utc_now()
    assert dt.tzinfo is not None
    assert dt.tzinfo == timezone.utc

    iso_str = _utc_now_iso()
    assert "+00:00" in iso_str or iso_str.endswith("Z")
    # Verify parsing as ISO format preserves UTC
    parsed = datetime.fromisoformat(iso_str)
    assert parsed.tzinfo is not None


def test_config_backup_policy_now_is_utc_aware():
    now_str = policy_now()
    assert "+00:00" in now_str or now_str.endswith("Z")
    parsed = datetime.fromisoformat(now_str)
    assert parsed.tzinfo is not None
