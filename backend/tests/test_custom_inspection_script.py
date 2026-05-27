import uuid
import pytest
from datetime import datetime
from database import get_db_connection
from services.inspection_service import run_inspection, get_inspection_run_detail

def test_run_inspection_with_custom_check_items(isolated_db, monkeypatch):
    # 1. Seed a device
    conn = get_db_connection()
    try:
        device_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, platform, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (device_id, "test-switch", "192.168.1.1", "cisco_ios", "Switch", "online")
        )

        # 2. Seed a standard inspection item
        conn.execute("DELETE FROM inspection_items")
        item_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO inspection_items (
                id, name, name_zh, category, check_key, description, method, command, vendor, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (item_id, "Cisco IOS CPU", "CPU利用率", "Network", "cisco_ios_cpu", "CPU Check", "CLI", "show processes cpu sorted", "cisco_ios", now, now)
        )
        conn.commit()
    finally:
        conn.close()

    # 3. Mock SSH ping and Netmiko command collector
    monkeypatch.setattr(
        "services.inspection_service._ping_device",
        lambda ip, count=2, timeout=2: {"success": True, "latency_ms": 1.5}
    )
    monkeypatch.setattr(
        "services.inspection_service._check_ssh",
        lambda ip, port=22, timeout=3: {"success": True}
    )

    collected_commands = []
    def mock_netmiko_collect(device, commands, use_admin_creds=False):
        nonlocal collected_commands
        collected_commands = commands
        # Return mock outputs
        return {
            "show processes cpu sorted": "CPU utilization for five seconds: 12%/5%; one minute: 10%; five minutes: 9%",
            "show clock": "22:45:00.123 UTC Wed May 27 2026",
        }
    monkeypatch.setattr("services.inspection_service._netmiko_collect", mock_netmiko_collect)

    # 4. Trigger the custom inspection run using check_items
    custom_check_items = ["show processes cpu sorted", "show clock"]
    
    result = run_inspection(
        scope_type="devices",
        scope_filter=device_id,
        trigger_type="scheduled",
        schedule_id=None,
        created_by="scheduler:test-job",
        check_items=custom_check_items
    )

    assert result["success"] is True
    run_id = result["run_id"]

    # 5. Verify database execution logs
    # Unmatched "show clock" should be executed and collected in raw_outputs_json
    assert "show processes cpu sorted" in collected_commands
    assert "show clock" in collected_commands

    detail = get_inspection_run_detail(run_id)
    assert detail is not None
    assert len(detail["results"]) == 1

    device_res = detail["results"][0]
    import json
    raw_outputs = json.loads(device_res["raw_outputs_json"])
    assert "show processes cpu sorted" in raw_outputs
    assert "show clock" in raw_outputs
    assert "22:45:00.123 UTC" in raw_outputs["show clock"]
