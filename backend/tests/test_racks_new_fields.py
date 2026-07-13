import pytest
import uuid
from database import get_db_connection
from services import rack_service

def test_racks_new_fields_and_sync(isolated_db):
    conn = get_db_connection()
    try:
        # 1. Create site for rack (since site_id is required)
        site_id = "site-default"
        
        # 2. Create rack with legacy fields
        rack = rack_service.create_rack(
            conn,
            name="Test Rack 01",
            datacenter="Beijing DC",
            room="Room 302",
            row="Row B",
            total_u=48,
            description="Testing new fields",
            status="active",
            power_capacity_watts=8000,
            site_id=site_id,
            rack_code="RACK-TEST-01"
        )
        
        # Verify legacy fields
        assert rack["name"] == "Test Rack 01"
        assert rack["datacenter"] == "Beijing DC"
        assert rack["room"] == "Room 302"
        assert rack["row"] == "Row B"
        assert rack["total_u"] == 48
        assert rack["description"] == "Testing new fields"
        assert rack["status"] == "active"
        assert rack["power_capacity_watts"] == 8000
        
        # Verify new fields (synchronized)
        assert rack["rack_name"] == "Test Rack 01"
        assert rack["room_name"] == "Room 302"
        assert rack["row_name"] == "Row B"
        assert rack["remarks"] == "Testing new fields"
        assert rack["power_capacity_w"] == 8000
        assert rack["site_id"] == site_id
        assert rack["rack_code"] == "RACK-TEST-01"
        
        # 3. Update using legacy field
        updated = rack_service.update_rack(
            conn,
            rack["id"],
            room="Room 404",
            description="Updated description"
        )
        assert updated["room"] == "Room 404"
        assert updated["room_name"] == "Room 404"
        assert updated["description"] == "Updated description"
        assert updated["remarks"] == "Updated description"
        
        # 4. Update using new field
        updated2 = rack_service.update_rack(
            conn,
            rack["id"],
            room_name="Room 505",
            remarks="Second update"
        )
        assert updated2["room"] == "Room 505"
        assert updated2["room_name"] == "Room 505"
        assert updated2["description"] == "Second update"
        assert updated2["remarks"] == "Second update"
        
        # 5. Verify rack_code unique constraint
        with pytest.raises(Exception):
            rack_service.create_rack(
                conn,
                name="Dup Rack",
                rack_code="RACK-TEST-01"
            )
            
    finally:
        conn.close()


def test_create_rack_with_new_fields_and_kwargs(isolated_db):
    conn = get_db_connection()
    try:
        # Create a rack by passing all fields in the RackCreate schema (including rack_name, remarks, etc.)
        rack = rack_service.create_rack(
            conn,
            name="Test Rack 02",
            datacenter="Shanghai DC",
            room="Room 501",
            row="Row C",
            total_u=42,
            description="Testing schema dict unpack",
            status="active",
            power_capacity_watts=6000,
            site_id="site-default",
            rack_code="RACK-TEST-02",
            rack_name="Test Rack 02 - New",
            room_name="Room 501 - New",
            row_name="Row C - New",
            remarks="Testing remarks field",
            power_capacity_w=6500,
            used_u=10,
            available_u=32,
            current_power_w=1500,
            power_utilization=0.23,
            max_weight_kg=1000,
            current_weight_kg=120,
            cooling_zone="Zone A"
        )
        
        # Verify both sets of fields are populated correctly and respect values passed as kwargs
        assert rack["name"] == "Test Rack 02"
        assert rack["rack_name"] == "Test Rack 02 - New"
        assert rack["datacenter"] == "Shanghai DC"
        assert rack["room"] == "Room 501"
        assert rack["room_name"] == "Room 501 - New"
        assert rack["row"] == "Row C"
        assert rack["row_name"] == "Row C - New"
        assert rack["description"] == "Testing schema dict unpack"
        assert rack["remarks"] == "Testing remarks field"
        assert rack["power_capacity_watts"] == 6000
        assert rack["power_capacity_w"] == 6500
        assert rack["used_u"] == 10
        assert rack["available_u"] == 32
        assert rack["current_power_w"] == 1500
        assert rack["power_utilization"] == 0.23
        assert rack["max_weight_kg"] == 1000
        assert rack["current_weight_kg"] == 120
        assert rack["cooling_zone"] == "Zone A"
        
    finally:
        conn.close()


def test_api_create_rack_endpoint(isolated_db, requester):
    from api.racks import api_create_rack
    from schemas.schemas import RackCreate

    body = RackCreate(
        name="Test API Rack",
        datacenter="Shenzhen DC",
        room="Room 601",
        row="Row D",
        total_u=42,
        description="Testing endpoint creation",
        status="active",
        power_capacity_watts=7000,
        rack_code="RACK-API-TEST",
        rack_name="Test API Rack Name",
        room_name="Room 601 Name",
        row_name="Row D Name",
        remarks="Endpoint remarks",
        power_capacity_w=7200,
        used_u=5,
        available_u=37,
        current_power_w=800,
        power_utilization=0.11,
        max_weight_kg=800,
        current_weight_kg=50,
        cooling_zone="Zone B"
    )

    response = api_create_rack(body=body, user=requester)
    assert response["success"] is True
    assert response["message"] == "Rack created"
    
    data = response["data"]
    assert data["name"] == "Test API Rack"
    assert data["rack_name"] == "Test API Rack Name"
    assert data["datacenter"] == "Shenzhen DC"
    assert data["room"] == "Room 601"
    assert data["room_name"] == "Room 601 Name"
    assert data["row"] == "Row D"
    assert data["row_name"] == "Row D Name"
    assert data["description"] == "Testing endpoint creation"
    assert data["remarks"] == "Endpoint remarks"
    assert data["power_capacity_watts"] == 7000
    assert data["power_capacity_w"] == 7200
    assert data["used_u"] == 5
    assert data["available_u"] == 37
    assert data["current_power_w"] == 800
    assert data["power_utilization"] == 0.11
    assert data["max_weight_kg"] == 800
    assert data["current_weight_kg"] == 50
    assert data["cooling_zone"] == "Zone B"


def test_api_batch_create_racks_endpoint(isolated_db, requester):
    from api.racks import api_batch_create_racks
    from schemas.schemas import RackCreate
    
    body = [
        RackCreate(
            name="Batch Rack 01",
            datacenter="Beijing DC",
            room="Room 101",
            row="Row X",
            total_u=42,
            rack_code="RACK-BATCH-01"
        ),
        RackCreate(
            name="Batch Rack 02",
            datacenter="Beijing DC",
            room="Room 101",
            row="Row X",
            total_u=42,
            rack_code="RACK-BATCH-02"
        )
    ]
    
    # 1. Success case
    response = api_batch_create_racks(body=body, user=requester)
    assert response["success"] is True
    assert len(response["data"]) == 2
    assert response["data"][0]["name"] == "Batch Rack 01"
    assert response["data"][1]["name"] == "Batch Rack 02"
    
    # 2. Failure case (duplicate rack_code in batch)
    dup_body = [
        RackCreate(
            name="Batch Rack 03",
            datacenter="Beijing DC",
            room="Room 101",
            row="Row X",
            total_u=42,
            rack_code="RACK-BATCH-01"  # Already exists!
        )
    ]
    
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException) as exc_info:
        api_batch_create_racks(body=dup_body, user=requester)
    assert exc_info.value.status_code == 400
    assert "导入第 1 行机柜数据失败" in exc_info.value.detail


def test_api_batch_create_racks_rolls_back_on_partial_failure(isolated_db, requester):
    from api.racks import api_batch_create_racks
    from schemas.schemas import RackCreate
    from fastapi import HTTPException

    body = [
        RackCreate(
            name="Batch Rollback 01",
            datacenter="Beijing DC",
            room="Room 101",
            row="Row X",
            total_u=42,
            rack_code="RACK-ROLLBACK-01"
        ),
        RackCreate(
            name="Batch Rollback Duplicate",
            datacenter="Beijing DC",
            room="Room 101",
            row="Row X",
            total_u=42,
            rack_code="RACK-ROLLBACK-01"
        ),
    ]

    with pytest.raises(HTTPException) as exc_info:
        api_batch_create_racks(body=body, user=requester)

    assert exc_info.value.status_code == 400
    assert "导入第 2 行机柜数据失败" in exc_info.value.detail

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM racks WHERE rack_code = ?",
            ("RACK-ROLLBACK-01",),
        ).fetchone()
        assert row["cnt"] == 0
    finally:
        conn.close()


def test_placement_strategy_and_concurrency(isolated_db):
    conn = get_db_connection()
    try:
        # Create a rack with top_first placement strategy
        rack = rack_service.create_rack(
            conn,
            name="Strategy Test Rack",
            datacenter="Beijing DC",
            room="Room 302",
            row="Row B",
            total_u=42,
            description="Testing strategy field",
            status="active",
            power_capacity_watts=8000,
            site_id="site-default",
            rack_code="RACK-STRATEGY-01",
            placement_strategy="top_first"
        )
        assert rack["placement_strategy"] == "top_first"

        # Update strategy to bottom_first
        updated = rack_service.update_rack(
            conn,
            rack["id"],
            placement_strategy="bottom_first"
        )
        assert updated["placement_strategy"] == "bottom_first"

        # Test concurrency check (calling _check_u_constraints won't fail and PostgreSQL SELECT FOR UPDATE executes cleanly)
        rack_service._check_u_constraints(conn, rack["id"], start_u=10, u_height=2, position="front")
    finally:
        conn.close()
