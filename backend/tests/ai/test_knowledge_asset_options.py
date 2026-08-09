import importlib
import sqlite3


knowledge_service_module = importlib.import_module("ai.services.knowledge_service")


def test_asset_vendor_platform_options_follow_network_asset_inventory(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE physical_assets (
            vendor TEXT,
            platform TEXT,
            asset_type TEXT
        );
        INSERT INTO physical_assets VALUES
          ('H3C', 'h3c_comware', 'network_device'),
          ('H3C', 'hp_comware', 'network_device'),
          ('Huawei', 'huawei_vrp', 'network_device'),
          ('Dell', 'linux', 'server'),
          ('', 'cisco_ios', 'network_device');
        """
    )
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_asset_vendor_platform_options()

    assert result["source"] == "physical_assets"
    assert result["asset_count"] == 3
    assert [vendor["value"] for vendor in result["vendors"]] == ["H3C", "Huawei"]
    assert [platform["value"] for platform in result["vendors"][0]["platforms"]] == [
        "h3c_comware",
        "hp_comware",
    ]
