from __future__ import annotations

from uuid import uuid4

import pytest

from database import get_db_connection
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    allocate_next_address,
    create_address,
    create_lease,
    create_pool,
    create_subnet,
    create_vip,
    reserve_address,
    update_address,
)


def test_allocate_next_replays_same_idempotency_key_and_rejects_changed_payload(isolated_db) -> None:
    del isolated_db
    space = create_address_space(
        name=f"IPAM idempotency {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="10.254.98.0/29",
        address_space_id=space["id"],
        gateway="10.254.98.1",
        network_type="management",
        name="IPAM idempotency test",
    )

    first = allocate_next_address(
        prefix["id"],
        hostname="idempotent-host",
        requested_by="operator",
        purpose="management",
        idempotency_key="allocate-last-address-001",
    )
    replay = allocate_next_address(
        prefix["id"],
        hostname="idempotent-host",
        requested_by="operator",
        purpose="management",
        idempotency_key="allocate-last-address-001",
    )

    assert replay == first
    assert first["address"] == "10.254.98.2"
    with pytest.raises(ValueError, match="different request body"):
        allocate_next_address(
            prefix["id"],
            hostname="changed-host",
            requested_by="operator",
            purpose="management",
            idempotency_key="allocate-last-address-001",
        )


def test_address_revision_rejects_stale_edit(isolated_db) -> None:
    del isolated_db
    space = create_address_space(
        name=f"IPAM revision {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="10.254.97.0/29",
        address_space_id=space["id"],
        gateway="10.254.97.1",
        network_type="management",
        name="IPAM revision test",
    )
    address = create_address(prefix["id"], address="10.254.97.2", hostname="before")

    assert update_address(address["id"], hostname="after", expected_revision=1)
    with pytest.raises(ValueError, match="revision is stale"):
        update_address(address["id"], hostname="stale overwrite", expected_revision=1)

    with get_db_connection() as conn:
        current = conn.execute(
            "SELECT hostname, revision FROM ip_addresses WHERE id = ?",
            (address["id"],),
        ).fetchone()
    assert current["hostname"] == "after"
    assert int(current["revision"]) == 2


def test_ipam_audit_failure_rolls_back_address_write(isolated_db, monkeypatch) -> None:
    del isolated_db
    space = create_address_space(
        name=f"IPAM audit rollback {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="10.254.96.0/29",
        address_space_id=space["id"],
        gateway="10.254.96.1",
        network_type="management",
        name="IPAM audit rollback test",
    )

    from services import ipam_service

    def fail_audit(**_kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(ipam_service, "log_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit write failed"):
        create_address(
            prefix["id"],
            address="10.254.96.2",
            hostname="must rollback",
            audit_context={'actor_username': 'operator', 'actor_role': 'Operator'},
        )

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM ip_addresses WHERE subnet_id = ? AND address = ?",
            (prefix["id"], "10.254.96.2"),
        ).fetchone()
    assert row is None

def test_resource_create_operations_replay_and_reject_changed_payloads(isolated_db) -> None:
    del isolated_db
    space = create_address_space(
        name=f"IPAM resource idempotency {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    audit = {
        "actor_id": "idempotency-operator",
        "actor_username": "idempotency-operator",
        "actor_role": "Administrator",
    }

    prefix_args = {
        "prefix": "10.252.0.0/24",
        "address_space_id": space["id"],
        "gateway": "10.252.0.1",
        "name": "idempotent-prefix",
    }
    prefix = create_subnet(
        **prefix_args, idempotency_key="prefix-create-replay", audit_context=audit,
    )
    assert create_subnet(
        **prefix_args, idempotency_key="prefix-create-replay", audit_context=audit,
    ) == prefix
    with pytest.raises(ValueError, match="different request body"):
        create_subnet(
            **{**prefix_args, "name": "changed-prefix"},
            idempotency_key="prefix-create-replay",
            audit_context=audit,
        )

    address_args = {
        "address": "10.252.0.2",
        "hostname": "manual-idempotent-host",
        "purpose": "server",
    }
    address = create_address(
        prefix["id"], **address_args,
        idempotency_key="manual-address-create-replay", audit_context=audit,
    )
    assert create_address(
        prefix["id"], **address_args,
        idempotency_key="manual-address-create-replay", audit_context=audit,
    ) == address
    with pytest.raises(ValueError, match="different request body"):
        create_address(
            prefix["id"], **{**address_args, "hostname": "changed-host"},
            idempotency_key="manual-address-create-replay", audit_context=audit,
        )

    reservation_args = {
        "address": "10.252.0.3",
        "hostname": "reserved-idempotent-host",
        "requested_by": "operator",
    }
    reservation = reserve_address(
        prefix["id"], **reservation_args,
        idempotency_key="reservation-create-replay", audit_context=audit,
    )
    assert reserve_address(
        prefix["id"], **reservation_args,
        idempotency_key="reservation-create-replay", audit_context=audit,
    ) == reservation
    with pytest.raises(ValueError, match="different request body"):
        reserve_address(
            prefix["id"], **{**reservation_args, "hostname": "changed-reservation"},
            idempotency_key="reservation-create-replay", audit_context=audit,
        )

    pool_args = {
        "name": "idempotent-external-pool",
        "prefix_id": prefix["id"],
        "start_ip": "10.252.0.20",
        "end_ip": "10.252.0.29",
        "management_mode": "external_dhcp",
        "allocation_allowed": False,
    }
    pool = create_pool(
        **pool_args, idempotency_key="pool-create-replay", audit_context=audit,
    )
    assert create_pool(
        **pool_args, idempotency_key="pool-create-replay", audit_context=audit,
    ) == pool
    with pytest.raises(ValueError, match="different request body"):
        create_pool(
            **{**pool_args, "description": "changed"},
            idempotency_key="pool-create-replay",
            audit_context=audit,
        )

    vip_args = {
        "address": "10.252.0.40",
        "vip_type": "vrrp",
        "prefix_id": prefix["id"],
        "description": "idempotent VIP",
    }
    vip = create_vip(
        **vip_args, idempotency_key="vip-create-replay", audit_context=audit,
    )
    assert create_vip(
        **vip_args, idempotency_key="vip-create-replay", audit_context=audit,
    ) == vip
    with pytest.raises(ValueError, match="different request body"):
        create_vip(
            **{**vip_args, "description": "changed"},
            idempotency_key="vip-create-replay",
            audit_context=audit,
        )

    lease_args = {
        "address": "10.252.0.21",
        "mac_address": "00:11:22:33:44:55",
        "hostname": "idempotent-lease",
        "dhcp_server": "dhcp-idempotency-test",
        "pool_id": pool["id"],
    }
    lease = create_lease(
        **lease_args, idempotency_key="lease-create-replay", audit_context=audit,
    )
    assert create_lease(
        **lease_args, idempotency_key="lease-create-replay", audit_context=audit,
    ) == lease
    with pytest.raises(ValueError, match="different request body"):
        create_lease(
            **{**lease_args, "hostname": "changed-lease"},
            idempotency_key="lease-create-replay",
            audit_context=audit,
        )

    resource_ids = (
        prefix["id"], address["id"], reservation["id"], pool["id"], vip["id"], lease["id"],
    )
    placeholders = ", ".join("?" for _ in resource_ids)
    with get_db_connection() as conn:
        audit_counts = conn.execute(
            f"""SELECT target_id, COUNT(*) AS count
                  FROM audit_events
                 WHERE target_id IN ({placeholders})
                 GROUP BY target_id""",
            resource_ids,
        ).fetchall()
        idempotency_count = conn.execute(
            """SELECT COUNT(*) AS count FROM ipam_idempotency_records
                 WHERE idempotency_key IN (
                     'prefix-create-replay', 'manual-address-create-replay',
                     'reservation-create-replay', 'pool-create-replay',
                     'vip-create-replay', 'lease-create-replay'
                 )"""
        ).fetchone()["count"]

    assert {row["target_id"]: int(row["count"]) for row in audit_counts} == {
        resource_id: 1 for resource_id in resource_ids
    }
    assert idempotency_count == 6

def test_prefix_create_route_reads_idempotency_key_http_header(isolated_db, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    from api import ipam as ipam_api

    del isolated_db
    space = create_address_space(
        name=f"IPAM HTTP idempotency {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    user = {
        "id": "ipam-http-idempotency-user",
        "username": "ipam-http-idempotency",
        "role": "Administrator",
        "tenant_id": "tenant-default",
    }
    app = FastAPI()
    app.include_router(ipam_api.router, prefix="/api")
    route = next(
        item for item in ipam_api.router.routes
        if isinstance(item, APIRoute)
        and item.path == "/ipam/subnets"
        and "POST" in item.methods
    )

    def override_dependencies(dependant) -> None:
        if dependant.call is not None:
            app.dependency_overrides[dependant.call] = lambda: user
        for child in dependant.dependencies:
            override_dependencies(child)

    for dependency in route.dependant.dependencies:
        override_dependencies(dependency)

    monkeypatch.setattr(ipam_api, "tenant_id_for_write", lambda **_kwargs: "tenant-default")
    monkeypatch.setattr(ipam_api, "enforce_resource_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ipam_api, "_enforce_address_space_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ipam_api, "_ipam_audit_context", lambda _user: None)

    request_body = {
        "prefix": "10.253.0.0/24",
        "address_space_id": space["id"],
        "name": "HTTP idempotent Prefix",
    }
    with TestClient(app) as client:
        first = client.post(
            "/api/ipam/subnets",
            json=request_body,
            headers={"Idempotency-Key": "prefix-http-replay"},
        )
        replay = client.post(
            "/api/ipam/subnets",
            json=request_body,
            headers={"Idempotency-Key": "prefix-http-replay"},
        )
        conflict = client.post(
            "/api/ipam/subnets",
            json={**request_body, "name": "changed HTTP Prefix"},
            headers={"Idempotency-Key": "prefix-http-replay"},
        )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert "different request body" in conflict.json()["detail"]

def test_all_idempotency_routes_bind_and_forward_http_header(isolated_db) -> None:
    import ast
    from pathlib import Path

    from fastapi.routing import APIRoute

    from api import ipam as ipam_api

    del isolated_db
    expected = {
        "api_generate_interface_prefixes": ("POST", "/ipam/prefixes/generate-from-interfaces", "generate_interface_prefixes"),
        "api_create_subnet": ("POST", "/ipam/subnets", "create_subnet"),
        "api_create_address": ("POST", "/ipam/subnets/{subnet_id}/addresses", "create_address"),
        "api_allocate_next_address": ("POST", "/ipam/subnets/{subnet_id}/allocate-next", "allocate_next_address"),
        "api_reserve_address": ("POST", "/ipam/subnets/{subnet_id}/reserve", "reserve_address"),
        "api_create_pool": ("POST", "/ipam/pools", "create_pool"),
        "api_create_vip": ("POST", "/ipam/vips", "create_vip"),
        "api_create_lease": ("POST", "/ipam/leases", "create_lease"),
        "api_create_fhrp_group": ("POST", "/ipam/fhrp/groups", "create_fhrp_group"),
        "api_update_fhrp_group": ("PUT", "/ipam/fhrp/groups/{group_id}", "update_fhrp_group"),
        "api_delete_fhrp_group": ("DELETE", "/ipam/fhrp/groups/{group_id}", "delete_fhrp_group"),
        "api_add_fhrp_group_member": ("POST", "/ipam/fhrp/groups/{group_id}/members", "add_fhrp_group_member"),
        "api_remove_fhrp_group_member": ("DELETE", "/ipam/fhrp/groups/{group_id}/members/{member_id}", "remove_fhrp_group_member"),
        "api_attach_fhrp_group_vip": ("POST", "/ipam/fhrp/groups/{group_id}/vips", "attach_fhrp_group_vip"),
        "api_detach_fhrp_group_vip": ("DELETE", "/ipam/fhrp/groups/{group_id}/vips/{vip_id}", "detach_fhrp_group_vip"),
    }
    routes = {
        route.endpoint.__name__: route
        for route in ipam_api.router.routes
        if isinstance(route, APIRoute)
    }
    idempotency_routes = {
        route.endpoint.__name__
        for route in routes.values()
        if any(
            field.name == "idempotency_key"
            and field.alias == "Idempotency-Key"
            for field in route.dependant.header_params
        )
    }
    assert idempotency_routes == set(expected)

    module_tree = ast.parse(Path(ipam_api.__file__).read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in module_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for route_name, (method, path, service_name) in expected.items():
        route = routes[route_name]
        assert route.path == path
        assert route.methods == {method}
        header_fields = [
            field for field in route.dependant.header_params
            if field.name == "idempotency_key"
        ]
        assert len(header_fields) == 1
        assert header_fields[0].alias == "Idempotency-Key"

        service_calls = [
            node for node in ast.walk(functions[route_name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == service_name
        ]
        assert len(service_calls) == 1
        key_argument = next(
            keyword.value for keyword in service_calls[0].keywords
            if keyword.arg == "idempotency_key"
        )
        assert isinstance(key_argument, ast.Call)
        assert isinstance(key_argument.func, ast.Name)
        assert key_argument.func.id == "_normalize_idempotency_key"
        assert len(key_argument.args) == 1
        assert isinstance(key_argument.args[0], ast.Name)
        assert key_argument.args[0].id == "idempotency_key"
