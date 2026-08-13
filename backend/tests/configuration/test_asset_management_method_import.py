from __future__ import annotations

from api import assets
from database import get_db_connection
from schemas.web import WebAccessProfileInput


def test_batch_import_persists_web_only_management_method_and_sanitizes_password(isolated_db):
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="WEB-ONLY-IMPORT-1",
            hostname="web-only-import-1",
            management_ip="192.0.2.81",
            vendor="H3C",
            model="SecPath",
            platform="h3c_comware",
            connection_method="web",
            management_port=0,
            web_profiles=[WebAccessProfileInput(
                profile_name="HTTPS management",
                scheme="https",
                port=443,
                path="/login",
                credential_mode="independent",
                normal_username="web-user",
                normal_password="web-secret",
            )],
        )
    ])

    assert result["created"] == 1
    listed = assets.list_assets(q="WEB-ONLY-IMPORT-1", page=1, page_size=10)
    item = listed["items"][0]
    assert item["connection_method"] == "web"
    assert item["management_port"] == 0
    assert len(item["web_profiles"]) == 1
    profile = item["web_profiles"][0]
    assert profile["credential_mode"] == "independent"
    assert profile["normal_username"] == "web-user"
    assert profile["normal_password"] == ""
    assert profile["normal_password_set"] is True

    with get_db_connection() as conn:
        stored = conn.execute(
            "SELECT normal_password FROM asset_web_access_profiles WHERE asset_id = ?",
            (item["id"],),
        ).fetchone()
    assert stored["normal_password"]
    assert stored["normal_password"] != "web-secret"
