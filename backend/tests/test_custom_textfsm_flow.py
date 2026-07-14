import os
import pytest
from fastapi.testclient import TestClient
from main import app
from services.textfsm_builder_service import auto_generate_template
from core.textfsm import parse_with_template_content

client = TestClient(app)

# Helper to get admin headers
def get_auth_headers():
    # Login as admin to get auth token
    resp = client.post("/api/login", json={"username": "admin", "password": "admin"})
    if resp.status_code == 200:
        token = resp.json().get("token")
        return {"Authorization": f"Bearer {token}"}
    return {}

def test_auto_generate_template_logic():
    # Test tabular output generation
    sample = """
    Interface    Status    Speed      Duplex
    Eth1/1       up        1000       full
    Eth1/2       down      auto       auto
    """
    res = auto_generate_template(sample)
    fsm_code = res["template"]
    
    assert "Value INTERFACE (\\S+)" in fsm_code
    assert "Value STATUS (\\S+)" in fsm_code
    assert "Value SPEED (\\S+)" in fsm_code
    assert "Value DUPLEX (.+?)" in fsm_code
    assert "Start" in fsm_code
    assert "INTERFACE" in fsm_code
    assert "STATUS" in fsm_code

def test_parse_with_template_content():
    template = """Value INTERFACE (\\S+)
Value STATUS (\\S+)

Start
  ^\\s*${INTERFACE}\\s+${STATUS} -> Record
"""
    output = "Eth1/1       up\nEth1/2       down"
    records = parse_with_template_content(template, output)
    assert len(records) == 2
    assert records[0]["INTERFACE"] == "Eth1/1"
    assert records[0]["STATUS"] == "up"
    assert records[1]["INTERFACE"] == "Eth1/2"
    assert records[1]["STATUS"] == "down"

def test_api_endpoints(isolated_db):
    headers = get_auth_headers()
    
    # 1. Test auto-generate endpoint
    sample = """
    Port      Vlan    Status
    Gi1/0/1   10      connected
    Gi1/0/2   20      notconnect
    """
    resp = client.post(
        "/api/textfsm/auto-generate",
        json={"sample_output": sample},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    content = data["data"]["content"]
    assert "Value PORT" in content
    assert "Value VLAN" in content
    
    # 2. Test run test parse endpoint
    template = """Value PORT (Gi\\S+)
Value VLAN (\\d+)

Start
  ^\\s*${PORT}\\s+${VLAN} -> Record
"""
    resp = client.post(
        "/api/textfsm/test",
        json={"content": template, "sample_output": sample},
        headers=headers
    )
    assert resp.status_code == 200
    test_data = resp.json()
    assert test_data["success"] is True
    assert len(test_data["data"]["records"]) == 2
    assert test_data["data"]["records"][0]["PORT"] == "Gi1/0/1"
    
    # 3. Test save custom template endpoint
    resp = client.post(
        "/api/textfsm/templates",
        json={
            "platform": "cisco_ios",
            "command": "show custom template test cmd",
            "content": template
        },
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    
    # 4. Clean up / delete template
    filename = "cisco_ios_show_custom_template_test_cmd.textfsm"
    resp = client.delete(
        f"/api/textfsm/templates/{filename}",
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
