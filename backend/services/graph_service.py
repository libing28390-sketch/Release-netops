import logging
import ipaddress
from typing import List, Dict, Any, Optional, Set
from database.core import get_db_connection

_logger = logging.getLogger(__name__)

class GraphService:
    def get_graph(self, types_filter: Optional[List[str]] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Builds the complete Network Knowledge Graph (NKG) from database tables.
        Returns a dict containing:
          - "nodes": List of graph node dictionaries
          - "edges": List of graph relationship dictionaries
        """
        conn = get_db_connection()
        try:
            # 1. Fetch data from SSoT tables
            devices_rows = conn.execute("SELECT id, hostname, ip_address, platform, status, sn, model, version FROM devices").fetchall()
            interfaces_rows = conn.execute("SELECT id, device_id, interface_name, name_display, description, interface_type, admin_status, oper_status, mac_address, speed, vrf_id, switchport_mode, access_vlan, native_vlan, allowed_vlans FROM interfaces").fetchall()
            vlan_rows = conn.execute("SELECT id, vlan_id, name, status FROM vlans").fetchall()
            vrf_rows = conn.execute("SELECT id, vrf_name, rd, description FROM vrfs").fetchall()
            prefix_rows = conn.execute("SELECT id, prefix, gateway, description, status, name, vrf_id FROM prefixes").fetchall()
            ip_rows = conn.execute("SELECT id, subnet_id, address, device_id, interface_name, status, description, vrf_id, interface_id FROM ip_addresses").fetchall()
            route_rows = conn.execute("SELECT id, device_id, vrf_name, destination, next_hop, outgoing_interface, protocol, metric FROM route_table WHERE active = 1").fetchall()
            endpoint_rows = conn.execute("SELECT id, ip, mac, hostname, vendor, switch_id, switch_port, vlan, vrf, is_active FROM network_endpoints WHERE is_active = 1").fetchall()
            link_rows = conn.execute("SELECT id, link_key, source_device_id, source_interface_id, source_port, target_device_id, target_interface_id, target_port, discovery_source, status FROM topology_links").fetchall()

            # Convert rows to dicts
            devices = [dict(r) for r in devices_rows]
            interfaces = [dict(r) for r in interfaces_rows]
            vlans = [dict(r) for r in vlan_rows]
            vrfs = [dict(r) for r in vrf_rows]
            prefixes = [dict(r) for r in prefix_rows]
            ips = [dict(r) for r in ip_rows]
            routes = [dict(r) for r in route_rows]
            endpoints = [dict(r) for r in endpoint_rows]
            links = [dict(r) for r in link_rows]
            
            nodes = []
            edges = []

            # Helpers to track added node IDs to prevent duplicates
            added_nodes: Set[str] = set()

            def add_node(node_id: str, node_type: str, name: str, properties: Dict[str, Any]):
                if types_filter and node_type not in types_filter:
                    return False
                if node_id in added_nodes:
                    return True
                nodes.append({
                    "id": node_id,
                    "type": node_type,
                    "name": name,
                    "label": name,
                    "properties": properties
                })
                added_nodes.add(node_id)
                return True

            def add_edge(source: str, target: str, edge_type: str, properties: Optional[Dict[str, Any]] = None):
                # Only add edge if both endpoints are active nodes (or filters allowed them)
                if types_filter:
                    # If we filter by types, only keep edges connecting visible nodes
                    if source not in added_nodes or target not in added_nodes:
                        return
                edges.append({
                    "source": source,
                    "target": target,
                    "type": edge_type,
                    "properties": properties or {}
                })

            # Create Nodes
            # Device Nodes
            for d in devices:
                add_node(
                    node_id=f"device:{d['id']}",
                    node_type="device",
                    name=d["hostname"] or d["id"],
                    properties={
                        "ip_address": d["ip_address"] or "",
                        "platform": d["platform"] or "",
                        "vendor": d["sn"] or "", # Or vendor field if populated
                        "model": d["model"] or "",
                        "version": d["version"] or "",
                        "status": d["status"] or "active"
                    }
                )

            # Interface Nodes
            for i in interfaces:
                add_node(
                    node_id=f"interface:{i['id']}",
                    node_type="interface",
                    name=i["name_display"] or i["interface_name"],
                    properties={
                        "description": i["description"] or "",
                        "interface_type": i["interface_type"] or "physical",
                        "admin_status": i["admin_status"] or "down",
                        "oper_status": i["oper_status"] or "down",
                        "mac_address": i["mac_address"] or "",
                        "speed": i["speed"] or 0.0
                    }
                )

            # VLAN Nodes
            for v in vlans:
                add_node(
                    node_id=f"vlan:{v['vlan_id']}",
                    node_type="vlan",
                    name=v["name"] or f"VLAN {v['vlan_id']}",
                    properties={
                        "vlan_id": v["vlan_id"],
                        "status": v["status"] or "active"
                    }
                )

            # VRF Nodes
            for vr in vrfs:
                add_node(
                    node_id=f"vrf:{vr['vrf_name']}",
                    node_type="vrf",
                    name=vr["vrf_name"],
                    properties={
                        "rd": vr["rd"] or "",
                        "description": vr["description"] or ""
                    }
                )

            # Prefix Nodes
            for p in prefixes:
                add_node(
                    node_id=f"prefix:{p['prefix']}",
                    node_type="prefix",
                    name=p["prefix"],
                    properties={
                        "status": p["status"] or "active",
                        "name": p["name"] or "",
                        "gateway": p["gateway"] or "",
                        "description": p["description"] or ""
                    }
                )

            # IP Address Nodes
            for ip_ent in ips:
                add_node(
                    node_id=f"ip:{ip_ent['address']}",
                    node_type="ip_address",
                    name=ip_ent["address"],
                    properties={
                        "status": ip_ent["status"] or "active",
                        "description": ip_ent["description"] or ""
                    }
                )

            # Route Nodes
            for r in routes:
                route_name = f"{r['device_id']}:{r['destination']}"
                add_node(
                    node_id=f"route:{route_name}",
                    node_type="route",
                    name=r["destination"],
                    properties={
                        "vrf": r["vrf_name"] or "default",
                        "next_hop": r["next_hop"] or "",
                        "outgoing_interface": r["outgoing_interface"] or "",
                        "protocol": r["protocol"] or "static",
                        "metric": r["metric"] or 0
                    }
                )

            # Endpoint Nodes
            for e in endpoints:
                add_node(
                    node_id=f"endpoint:{e['mac']}",
                    node_type="endpoint",
                    name=e["ip"] or e["mac"],
                    properties={
                        "ip": e["ip"] or "",
                        "mac": e["mac"],
                        "hostname": e["hostname"] or "",
                        "vendor": e["vendor"] or "",
                        "vlan": e["vlan"] or "",
                        "vrf": e["vrf"] or ""
                    }
                )

            # Build a lookup mapping from (device_id, name) -> interface_id
            interface_lookup = {}
            for i in interfaces:
                interface_lookup[(i['device_id'], i['interface_name'].lower())] = i['id']
                if i['name_display']:
                    interface_lookup[(i['device_id'], i['name_display'].lower())] = i['id']

            # Create Edges
            # 1. Device ➔ Interface (HAS_INTERFACE)
            for i in interfaces:
                add_edge(
                    source=f"device:{i['device_id']}",
                    target=f"interface:{i['id']}",
                    edge_type="HAS_INTERFACE"
                )

            # 2. Interface ➔ Interface (LINKED_TO)
            for l in links:
                src_id = l["source_interface_id"] or interface_lookup.get((l["source_device_id"], l["source_port"].lower())) or f"{l['source_device_id']}:{l['source_port']}"
                tgt_id = l["target_interface_id"] or interface_lookup.get((l["target_device_id"], l["target_port"].lower())) or f"{l['target_device_id']}:{l['target_port']}"
                add_edge(
                    source=f"interface:{src_id}",
                    target=f"interface:{tgt_id}",
                    edge_type="LINKED_TO",
                    properties={
                        "discovery_source": l["discovery_source"] or "lldp",
                        "status": l["status"] or "up"
                    }
                )

            # 3. Interface ➔ VLAN (MEMBER_OF_VLAN)
            for i in interfaces:
                vlan_ids = []
                if i["access_vlan"]:
                    vlan_ids.append(i["access_vlan"])
                if i["native_vlan"]:
                    vlan_ids.append(i["native_vlan"])
                if i["allowed_vlans"]:
                    try:
                        vlan_list = [int(v.strip()) for v in str(i["allowed_vlans"]).split(",") if v.strip().isdigit()]
                        vlan_ids.extend(vlan_list)
                    except Exception:
                        pass
                
                for vid in set(vlan_ids):
                    add_edge(
                        source=f"interface:{i['id']}",
                        target=f"vlan:{vid}",
                        edge_type="MEMBER_OF_VLAN"
                    )

            # 4. Interface ➔ VRF (IN_VRF)
            for i in interfaces:
                if i["vrf_id"]:
                    add_edge(
                        source=f"interface:{i['id']}",
                        target=f"vrf:{i['vrf_id']}",
                        edge_type="IN_VRF"
                    )

            # 5. Interface ➔ IP Address (ASSIGNED_IP)
            for ip_ent in ips:
                intf_id = ip_ent["interface_id"] or interface_lookup.get((ip_ent["device_id"], ip_ent["interface_name"].lower())) or f"{ip_ent['device_id']}:{ip_ent['interface_name']}"
                if ip_ent["device_id"] and ip_ent["interface_name"]:
                    add_edge(
                        source=f"interface:{intf_id}",
                        target=f"ip:{ip_ent['address']}",
                        edge_type="ASSIGNED_IP"
                    )

            # 6. IP Address ➔ Prefix (MEMBER_OF_PREFIX)
            prefix_nets = []
            for p in prefixes:
                try:
                    prefix_nets.append({
                        "id": f"prefix:{p['prefix']}",
                        "net": ipaddress.ip_network(p["prefix"], strict=False)
                    })
                except ValueError:
                    pass
            
            for ip_ent in ips:
                try:
                    ip_addr = ipaddress.ip_address(ip_ent["address"])
                    for pnet in prefix_nets:
                        if ip_addr in pnet["net"]:
                            add_edge(
                                source=f"ip:{ip_ent['address']}",
                                target=pnet["id"],
                                edge_type="MEMBER_OF_PREFIX"
                            )
                except ValueError:
                    pass

            # 7. Prefix hierarchy tree (PARENT_OF_PREFIX)
            prefix_nets.sort(key=lambda x: x["net"].prefixlen)
            for idx, child in enumerate(prefix_nets):
                for parent in prefix_nets[:idx]:
                    if child["net"].subnet_of(parent["net"]) and child["net"] != parent["net"]:
                        add_edge(
                            source=parent["id"],
                            target=child["id"],
                            edge_type="PARENT_OF_PREFIX"
                        )
                        break

            # 8. Device ➔ Route (HAS_ROUTE)
            for r in routes:
                route_name = f"{r['device_id']}:{r['destination']}"
                add_edge(
                    source=f"device:{r['device_id']}",
                    target=f"route:{route_name}",
                    edge_type="HAS_ROUTE"
                )

            # 9. Route ➔ Next hop IP (NEXT_HOP_IP) or Route ➔ Interface (OUTGOING_INTERFACE)
            for r in routes:
                route_name = f"{r['device_id']}:{r['destination']}"
                if r["next_hop"] and r["next_hop"].replace(".", "").isdigit():
                    add_edge(
                        source=f"route:{route_name}",
                        target=f"ip:{r['next_hop']}",
                        edge_type="NEXT_HOP_IP"
                    )
                if r["outgoing_interface"]:
                    intf_id = interface_lookup.get((r["device_id"], r["outgoing_interface"].lower())) or f"{r['device_id']}:{r['outgoing_interface']}"
                    add_edge(
                        source=f"route:{route_name}",
                        target=f"interface:{intf_id}",
                        edge_type="OUTGOING_INTERFACE"
                    )

            # 10. Endpoint ➔ Interface (CONNECTED_TO)
            for e in endpoints:
                if e["switch_id"] and e["switch_port"]:
                    intf_id = interface_lookup.get((e["switch_id"], e["switch_port"].lower())) or f"{e['switch_id']}:{e['switch_port']}"
                    add_edge(
                        source=f"endpoint:{e['mac']}",
                        target=f"interface:{intf_id}",
                        edge_type="CONNECTED_TO"
                    )

            return {
                "nodes": nodes,
                "edges": edges
            }

        finally:
            conn.close()

    def find_path(self, source_id: str, target_id: str) -> List[Dict[str, Any]]:
        """
        Finds the shortest network path (sequence of nodes and edges) between 
        a source node ID and a target node ID using BFS.
        """
        graph = self.get_graph()
        nodes = graph["nodes"]
        edges = graph["edges"]

        # Build adjacency mapping (treating edges as undirected for generic reachability)
        adj = {}
        for edge in edges:
            s = edge["source"]
            t = edge["target"]
            adj.setdefault(s, []).append((t, edge))
            adj.setdefault(t, []).append((s, edge))

        # Perform BFS shortest path search
        queue = [[source_id]]
        visited = {source_id}

        while queue:
            path = queue.pop(0)
            curr = path[-1]
            if curr == target_id:
                # Reconstruct full hop detail (nodes interleaved with connecting edges)
                result_path = []
                for idx, node_id in enumerate(path):
                    node_obj = next((n for n in nodes if n["id"] == node_id), None)
                    if node_obj:
                        result_path.append({"type": "node", "data": node_obj})
                    if idx < len(path) - 1:
                        next_node_id = path[idx + 1]
                        # Find matching connecting edge
                        connecting_edge = None
                        for neighbor, edge_obj in adj.get(node_id, []):
                            if neighbor == next_node_id:
                                connecting_edge = edge_obj
                                break
                        if connecting_edge:
                            result_path.append({"type": "edge", "data": connecting_edge})
                return result_path

            for neighbor, edge in adj.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return []
