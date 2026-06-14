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
