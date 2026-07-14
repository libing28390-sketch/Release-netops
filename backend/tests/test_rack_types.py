import pytest

from database import get_db_connection
from services import rack_service


def test_rack_type_crud_and_rack_reference(isolated_db):
    conn = get_db_connection()
    try:
        rack_type = rack_service.create_rack_type(
            conn,
            name="48U Lab Cabinet",
            vendor="Generic",
            model="NW-48U-1000D",
            total_u=48,
            width_mm=600,
            depth_mm=1000,
            max_weight_kg=1200,
            power_capacity_watts=12000,
            allow_front_rear_mount=True,
        )

        assert rack_type["name"] == "48U Lab Cabinet"
        assert rack_type["total_u"] == 48

        rack = rack_service.create_rack(
            conn,
            name="A01",
            datacenter="BJ-DC1",
            rack_type_id=rack_type["id"],
            total_u=48,
            width_mm=600,
            depth_mm=1000,
            power_capacity_watts=12000,
        )

        assert rack["rack_type_id"] == rack_type["id"]
        assert rack["total_u"] == 48
        assert rack["width_mm"] == 600
        assert rack["depth_mm"] == 1000

        with pytest.raises(ValueError, match="using it"):
            rack_service.delete_rack_type(conn, rack_type["id"])

        updated = rack_service.update_rack_type(conn, rack_type["id"], description="standard network rack")
        assert updated["description"] == "standard network rack"
    finally:
        conn.close()
