"""In-memory Exact_IP_Map and Per-VRF Connected-Subnet Radix Tree index.

Replaces full routing table walks (Iron Rule #2) and full-table Python linear
scans with:
1. ``exact_ip_map``: O(1) lookup for every known managed device IP (management,
   Loopback, P2P interconnect, SVI, Secondary/sub, VIP), intentionally
   retaining ``down``/``shutdown`` interfaces so fault-lookup still identifies
   the owning device and interface.
2. ``per_vrf_trees``: Per-VRF longest-prefix-match (LPM) Radix Tree over active
   connected subnets, strictly excluding explicitly ``down``/``shutdown``
   interfaces and ordering multi-gateway candidates by
   ``VRRP/HSRP MASTER > ANYCAST_ACTIVE > active UP > BACKUP``.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from core.interface_utils import normalize_interface_name
from database import get_db_connection

logger = logging.getLogger(__name__)

_DOWN_STATES = frozenset({
    "down",
    "admin_down",
    "administratively down",
    "shutdown",
    "notpresent",
    "lowerlayerdown",
})
_DEFAULT_VRF_ALIASES = frozenset({"", "default", "global", "global_table", "--", "-"})
_MASTER_FHRP_STATES = frozenset({"master", "active"})
_BACKUP_FHRP_STATES = frozenset({"backup", "standby"})

try:
    import pytricia as _pytricia  # type: ignore[import-not-found]
except Exception:
    _pytricia = None


def _is_explicitly_down(admin_status: Any, oper_status: Any) -> bool:
    admin = str(admin_status or "").strip().lower()
    oper = str(oper_status or "").strip().lower()
    return admin in _DOWN_STATES or oper in _DOWN_STATES


def _normalize_vrf(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower() in _DEFAULT_VRF_ALIASES:
        return "default"
    return raw


def _parse_prefix_length(raw_prefix: Any, ip_version: int) -> int | None:
    if raw_prefix is None or isinstance(raw_prefix, bool):
        return None
    text = str(raw_prefix).strip().lstrip("/")
    if not text:
        return None
    try:
        if "." in text and ip_version == 4:
            return ipaddress.IPv4Network(f"0.0.0.0/{text}").prefixlen
        val = int(text)
    except (TypeError, ValueError):
        return None
    max_len = 32 if ip_version == 4 else 128
    return val if 0 <= val <= max_len else None


def _infer_ip_role(interface_name: str, interface_type: str, prefix_len: int | None, is_mgmt_ip: bool) -> str:
    if is_mgmt_ip:
        return "MGMT"
    lower_name = str(interface_name or "").strip().lower()
    lower_type = str(interface_type or "").strip().lower()
    if lower_type == "loopback" or lower_name.startswith(("loopback", "loop", "lo")):
        return "LOOPBACK"
    if any(lower_name.startswith(p) for p in ("mgmt", "meth", "m-gigabit", "mge", "fxp0", "management")):
        return "MGMT"
    if lower_type == "svi" or lower_name.startswith(("vlanif", "vlan-interface", "vlan", "bvi", "irb", "vbdif")):
        return "SVI_PRIMARY"
    if prefix_len in (30, 31):
        return "P2P_INTERCONNECT"
    return "INTERFACE_IP"


@dataclass(frozen=True)
class IPIndexRecord:
    ip: str
    prefix_len: int | None
    subnet_cidr: str
    vrf_name: str
    device_id: str
    hostname: str
    canonical_mgmt_ip: str
    site_id: str
    tenant_id: str
    interface_name: str
    interface_type: str
    ip_role: str
    vip_role: str | None = None
    admin_status: str = "unknown"
    oper_status: str = "unknown"
    is_down: bool = False
    device_status: str = "online"
    source: str = "cmdb"

    def gateway_priority_key(self) -> tuple[int, int, str, str]:
        vip_weight = {
            "MASTER": 0,
            "ANYCAST_ACTIVE": 1,
            None: 2,
            "BACKUP": 9,
        }.get(self.vip_role, 5)
        online_weight = 0 if str(self.device_status or "").lower() == "online" else 1
        return (vip_weight, online_weight, self.hostname.lower(), self.interface_name.lower())


class _TrieNode:
    __slots__ = ("left", "right", "cidr", "value")

    def __init__(self) -> None:
        self.left: _TrieNode | None = None
        self.right: _TrieNode | None = None
        self.cidr: str | None = None
        self.value: Any = None


class _BitwisePrefixTrie:
    """Pure-Python bitwise binary prefix trie supporting IPv4 (32) and IPv6 (128)."""

    def __init__(self, bits: int) -> None:
        self._bits = bits
        self._root = _TrieNode()

    def insert(self, net: ipaddress.IPv4Network | ipaddress.IPv6Network, value: Any) -> None:
        addr_int = int(net.network_address)
        plen = net.prefixlen
        node = self._root
        for shift in range(self._bits - 1, self._bits - 1 - plen, -1):
            bit = (addr_int >> shift) & 1
            if bit == 0:
                if node.left is None:
                    node.left = _TrieNode()
                node = node.left
            else:
                if node.right is None:
                    node.right = _TrieNode()
                node = node.right
        node.cidr = str(net)
        node.value = value

    def get_exact(self, net: ipaddress.IPv4Network | ipaddress.IPv6Network) -> Any:
        addr_int = int(net.network_address)
        plen = net.prefixlen
        node: _TrieNode | None = self._root
        for shift in range(self._bits - 1, self._bits - 1 - plen, -1):
            if node is None:
                return None
            bit = (addr_int >> shift) & 1
            node = node.left if bit == 0 else node.right
        return node.value if node is not None and node.cidr == str(net) else None

    def all_matches(self, addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> list[tuple[str, Any]]:
        addr_int = int(addr)
        node: _TrieNode | None = self._root
        matches: list[tuple[str, Any]] = []
        if node.cidr is not None:
            matches.append((node.cidr, node.value))
        for shift in range(self._bits - 1, -1, -1):
            bit = (addr_int >> shift) & 1
            node = node.left if bit == 0 else node.right
            if node is None:
                break
            if node.cidr is not None:
                matches.append((node.cidr, node.value))
        matches.reverse()  # Longest prefix first
        return matches


class DualFamilyRadixTree:
    """IPv4 + IPv6 prefix tree (uses pytricia if installed, else pure-Python bitwise trie)."""

    def __init__(self) -> None:
        self._use_pytricia = _pytricia is not None
        if self._use_pytricia:
            self._v4_pyt = _pytricia.PyTricia(32)
            self._v6_pyt = _pytricia.PyTricia(128)
        else:
            self._v4_trie = _BitwisePrefixTrie(32)
            self._v6_trie = _BitwisePrefixTrie(128)
        self._items: dict[str, list[IPIndexRecord]] = {}

    def add_record(self, subnet_cidr: str, record: IPIndexRecord) -> None:
        net = ipaddress.ip_network(subnet_cidr, strict=False)
        key = str(net)
        bucket = self._items.get(key)
        if bucket is None:
            bucket = []
            self._items[key] = bucket
            if self._use_pytricia:
                tree = self._v4_pyt if net.version == 4 else self._v6_pyt
                tree[key] = bucket
            else:
                trie = self._v4_trie if net.version == 4 else self._v6_trie
                trie.insert(net, bucket)
        bucket.append(record)

    def finalize(self) -> None:
        for bucket in self._items.values():
            bucket.sort(key=lambda r: r.gateway_priority_key())

    def all_matches(self, ip_str: str) -> list[tuple[str, list[IPIndexRecord]]]:
        try:
            addr = ipaddress.ip_address(str(ip_str or "").strip())
        except ValueError:
            return []
        if self._use_pytricia:
            tree = self._v4_pyt if addr.version == 4 else self._v6_pyt
            matches: list[tuple[str, list[IPIndexRecord]]] = []
            key = tree.get_key(str(addr))
            while key is not None:
                matches.append((key, tree[key]))
                key = tree.parent(key)
            return matches
        trie = self._v4_trie if addr.version == 4 else self._v6_trie
        return trie.all_matches(addr)


@dataclass
class IPAMRadixIndexSnapshot:
    built_at: float
    exact_ip_map: dict[str, list[IPIndexRecord]] = field(default_factory=dict)
    per_vrf_trees: dict[str, DualFamilyRadixTree] = field(default_factory=dict)
    p2p_subnets: dict[tuple[str, str], list[IPIndexRecord]] = field(default_factory=dict)

    @staticmethod
    def _matches_scope(
        rec: IPIndexRecord,
        *,
        tenant_id: str | None = None,
        site_id: str | None = None,
        vrf: str | None = None,
        authorized_device_ids: set[str] | None = None,
    ) -> bool:
        if authorized_device_ids is not None and rec.device_id not in authorized_device_ids:
            return False
        if tenant_id and rec.tenant_id and rec.tenant_id != tenant_id:
            return False
        if site_id and rec.site_id.lower() != site_id.strip().lower():
            return False
        if vrf is not None and str(vrf).strip() != "":
            req_vrf = _normalize_vrf(vrf)
            if rec.vrf_name.lower() != req_vrf.lower():
                return False
        return True

    def lookup_exact(
        self,
        ip: str,
        *,
        tenant_id: str | None = None,
        site_id: str | None = None,
        vrf: str | None = None,
        authorized_device_ids: Iterable[str] | None = None,
    ) -> list[IPIndexRecord]:
        try:
            normalized = str(ipaddress.ip_address(str(ip or "").strip()))
        except ValueError:
            return []
        allowed = {str(d) for d in authorized_device_ids} if authorized_device_ids is not None else None
        raw = self.exact_ip_map.get(normalized, [])
        matched = [
            rec for rec in raw
            if self._matches_scope(
                rec,
                tenant_id=tenant_id,
                site_id=site_id,
                vrf=vrf,
                authorized_device_ids=allowed,
            )
        ]
        # Prefer concrete interface records (Loopback/P2P/SVI) over generic
        # device-row MGMT fallback when both exist for the same device+IP.
        seen_by_device_if: dict[tuple[str, str, str], IPIndexRecord] = {}
        for rec in matched:
            key = (rec.device_id, normalize_interface_name(rec.interface_name).lower(), rec.vrf_name.lower())
            existing = seen_by_device_if.get(key)
            if existing is None or (existing.source == "device_mgmt" and rec.source != "device_mgmt"):
                seen_by_device_if[key] = rec
        # Collapse device_mgmt fallback if a real interface row exists for same device_id+ip
        devices_with_intf = {rec.device_id for rec in seen_by_device_if.values() if rec.source != "device_mgmt"}
        deduped = [
            rec for rec in seen_by_device_if.values()
            if not (rec.source == "device_mgmt" and rec.device_id in devices_with_intf)
        ]
        deduped.sort(key=lambda r: (
            0 if not r.is_down else 1,
            r.gateway_priority_key(),
        ))
        return deduped

    def lookup_connected_gateways(
        self,
        ip: str,
        *,
        tenant_id: str | None = None,
        site_id: str | None = None,
        vrf: str | None = None,
        authorized_device_ids: Iterable[str] | None = None,
    ) -> tuple[str, list[IPIndexRecord]]:
        """Return (longest_matched_cidr, priority_sorted_active_gateways)."""
        try:
            normalized = str(ipaddress.ip_address(str(ip or "").strip()))
        except ValueError:
            return "", []
        allowed = {str(d) for d in authorized_device_ids} if authorized_device_ids is not None else None
        if vrf is not None and str(vrf).strip() != "":
            req_vrf = _normalize_vrf(vrf)
            trees = [self.per_vrf_trees[k] for k in self.per_vrf_trees if k.lower() == req_vrf.lower()]
        else:
            trees = list(self.per_vrf_trees.values())

        best_plen = -1
        best_cidr = ""
        best_records: list[IPIndexRecord] = []
        for tree in trees:
            for cidr, bucket in tree.all_matches(normalized):
                scoped = [
                    rec for rec in bucket
                    if not rec.is_down
                    and self._matches_scope(
                        rec,
                        tenant_id=tenant_id,
                        site_id=site_id,
                        vrf=vrf,
                        authorized_device_ids=allowed,
                    )
                ]
                if not scoped:
                    continue
                plen = int(cidr.rsplit("/", 1)[-1])
                if plen > best_plen:
                    best_plen = plen
                    best_cidr = cidr
                    best_records = list(scoped)
                elif plen == best_plen:
                    best_records.extend(scoped)
                break  # Already longest match in this VRF tree

        # Deduplicate per (device_id, normalized_interface)
        unique: dict[tuple[str, str], IPIndexRecord] = {}
        for rec in best_records:
            key = (rec.device_id, normalize_interface_name(rec.interface_name).lower())
            if key not in unique or rec.gateway_priority_key() < unique[key].gateway_priority_key():
                unique[key] = rec
        ordered = sorted(unique.values(), key=lambda r: r.gateway_priority_key())
        return best_cidr, ordered

    def find_p2p_peer(
        self,
        record: IPIndexRecord,
        *,
        authorized_device_ids: Iterable[str] | None = None,
    ) -> IPIndexRecord | None:
        if record.prefix_len not in (30, 31) or not record.subnet_cidr:
            return None
        allowed = {str(d) for d in authorized_device_ids} if authorized_device_ids is not None else None
        peers = self.p2p_subnets.get((record.vrf_name.lower(), record.subnet_cidr), [])
        for candidate in peers:
            if candidate.device_id == record.device_id and candidate.ip == record.ip:
                continue
            if allowed is not None and candidate.device_id not in allowed:
                continue
            if candidate.ip != record.ip:
                return candidate
        return None

    def infer_sites_for_ip(
        self,
        ip: str,
        *,
        tenant_id: str | None = None,
        vrf: str | None = None,
        authorized_device_ids: Iterable[str] | None = None,
    ) -> set[str]:
        _cidr, gateways = self.lookup_connected_gateways(
            ip,
            tenant_id=tenant_id,
            vrf=vrf,
            authorized_device_ids=authorized_device_ids,
        )
        return {rec.site_id.lower() for rec in gateways if rec.site_id}


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, Mapping) or hasattr(row, "keys"):
        return dict(row)
    return {}


def build_ipam_radix_index(conn: Any = None) -> IPAMRadixIndexSnapshot:
    """Build a fresh Exact_IP_Map + Per_VRF_Radix_Tree snapshot from PostgreSQL."""
    owns_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    snapshot = IPAMRadixIndexSnapshot(built_at=time.monotonic())
    try:
        device_rows = db.execute(
            """SELECT d.id, d.hostname, d.ip_address, d.status,
                      COALESCE(NULLIF(BTRIM(d.tenant_id), ''), 'tenant-default') AS tenant_id,
                      COALESCE(NULLIF(BTRIM(pa.site_id), ''), NULLIF(BTRIM(d.site_id), ''), NULLIF(BTRIM(d.site), ''), '') AS site_id
                 FROM devices d
                 LEFT JOIN physical_assets pa ON pa.id = d.asset_id"""
        ).fetchall()
        devices_by_id: dict[str, dict[str, Any]] = {}
        for raw in device_rows:
            d = _row_dict(raw)
            dev_id = str(d.get("id") or "").strip()
            if not dev_id:
                continue
            devices_by_id[dev_id] = d
            mgmt_ip = str(d.get("ip_address") or "").strip()
            if mgmt_ip:
                try:
                    norm_mgmt = str(ipaddress.ip_address(mgmt_ip))
                except ValueError:
                    norm_mgmt = ""
                if norm_mgmt:
                    rec = IPIndexRecord(
                        ip=norm_mgmt,
                        prefix_len=32 if ipaddress.ip_address(norm_mgmt).version == 4 else 128,
                        subnet_cidr=f"{norm_mgmt}/{32 if ipaddress.ip_address(norm_mgmt).version == 4 else 128}",
                        vrf_name="default",
                        device_id=dev_id,
                        hostname=str(d.get("hostname") or dev_id),
                        canonical_mgmt_ip=norm_mgmt,
                        site_id=str(d.get("site_id") or ""),
                        tenant_id=str(d.get("tenant_id") or "tenant-default"),
                        interface_name="Management",
                        interface_type="management",
                        ip_role="MGMT",
                        admin_status="up" if str(d.get("status") or "").lower() == "online" else "unknown",
                        oper_status="up" if str(d.get("status") or "").lower() == "online" else "unknown",
                        is_down=False,
                        device_status=str(d.get("status") or "unknown"),
                        source="device_mgmt",
                    )
                    snapshot.exact_ip_map.setdefault(norm_mgmt, []).append(rec)

        # Load live FHRP (VRRP/HSRP) states to weight Master > Backup gateways
        fhrp_by_dev_if: dict[tuple[str, str], str] = {}
        try:
            fhrp_rows = db.execute(
                """SELECT device_id, interface_name, state
                     FROM ipam_current_fhrp_observations"""
            ).fetchall()
            for raw in fhrp_rows:
                f = _row_dict(raw)
                dev_id = str(f.get("device_id") or "").strip()
                if_key = normalize_interface_name(str(f.get("interface_name") or "")).lower()
                st = str(f.get("state") or "").strip().lower()
                if not dev_id or not if_key:
                    continue
                if st in _MASTER_FHRP_STATES:
                    fhrp_by_dev_if[(dev_id, if_key)] = "MASTER"
                elif st in _BACKUP_FHRP_STATES and fhrp_by_dev_if.get((dev_id, if_key)) != "MASTER":
                    fhrp_by_dev_if[(dev_id, if_key)] = "BACKUP"
        except Exception:
            pass

        def _index_interface_ip(
            *,
            device_id: str,
            interface_name: str,
            raw_ip: str,
            raw_prefix: Any,
            vrf_name: str,
            interface_type: str,
            admin_status: str,
            oper_status: str,
            source: str,
        ) -> None:
            dev = devices_by_id.get(device_id)
            if not dev:
                return
            ip_text = str(raw_ip or "").strip()
            if not ip_text:
                return
            embedded_plen = None
            try:
                if "/" in ip_text:
                    parsed_iface = ipaddress.ip_interface(ip_text)
                    parsed_ip = parsed_iface.ip
                    embedded_plen = parsed_iface.network.prefixlen
                else:
                    parsed_ip = ipaddress.ip_address(ip_text)
            except ValueError:
                return
            norm_ip = str(parsed_ip)
            plen = _parse_prefix_length(raw_prefix, parsed_ip.version)
            if plen is None:
                plen = embedded_plen
            subnet_cidr = ""
            if plen is not None:
                subnet_cidr = str(ipaddress.ip_network(f"{norm_ip}/{plen}", strict=False))
            norm_vrf = _normalize_vrf(vrf_name)
            is_down = _is_explicitly_down(admin_status, oper_status)
            mgmt_ip = str(dev.get("ip_address") or "").strip()
            is_mgmt = bool(mgmt_ip and mgmt_ip == norm_ip and str(interface_name).lower().startswith(("mgmt", "meth", "m-gig", "mge", "fxp0", "management")))
            ip_role = _infer_ip_role(interface_name, interface_type, plen, is_mgmt)
            if_key = normalize_interface_name(interface_name).lower()
            vip_role = fhrp_by_dev_if.get((device_id, if_key))

            rec = IPIndexRecord(
                ip=norm_ip,
                prefix_len=plen,
                subnet_cidr=subnet_cidr,
                vrf_name=norm_vrf,
                device_id=device_id,
                hostname=str(dev.get("hostname") or device_id),
                canonical_mgmt_ip=mgmt_ip,
                site_id=str(dev.get("site_id") or ""),
                tenant_id=str(dev.get("tenant_id") or "tenant-default"),
                interface_name=interface_name,
                interface_type=str(interface_type or ""),
                ip_role=ip_role,
                vip_role=vip_role,
                admin_status=str(admin_status or "unknown"),
                oper_status=str(oper_status or "unknown"),
                is_down=is_down,
                device_status=str(dev.get("status") or "unknown"),
                source=source,
            )
            snapshot.exact_ip_map.setdefault(norm_ip, []).append(rec)
            if plen in (30, 31) and subnet_cidr:
                snapshot.p2p_subnets.setdefault((norm_vrf.lower(), subnet_cidr), []).append(rec)
            # Only active (non-down), non-host connected subnets enter Per_VRF_Radix_Tree
            max_host_len = 32 if parsed_ip.version == 4 else 128
            if (
                not is_down
                and subnet_cidr
                and plen is not None
                and 0 < plen < max_host_len
                and ip_role != "LOOPBACK"
            ):
                tree = snapshot.per_vrf_trees.get(norm_vrf)
                if tree is None:
                    tree = DualFamilyRadixTree()
                    snapshot.per_vrf_trees[norm_vrf] = tree
                tree.add_record(subnet_cidr, rec)

        # Source 1: Authoritative CMDB multi-address interface observations
        try:
            cmdb_rows = db.execute(
                """SELECT a.device_id, a.interface_name, host(a.ip_address) AS ip_address,
                          a.ip_prefix_length, a.local_context_key, a.context_type,
                          o.interface_type, o.admin_status, o.oper_status
                     FROM cmdb_device_interface_address_observations a
                     JOIN cmdb_collection_snapshots s
                       ON s.device_id = a.device_id
                      AND s.domain = 'interface_inventory'
                      AND s.successful_generation = a.generation
                     LEFT JOIN cmdb_device_interface_observations o
                       ON o.device_id = a.device_id
                      AND o.generation = a.generation
                      AND o.normalized_interface_name = a.normalized_interface_name"""
            ).fetchall()
            for raw in cmdb_rows:
                r = _row_dict(raw)
                vrf = str(r.get("local_context_key") or "") if str(r.get("context_type") or "").lower() == "vrf" else "default"
                _index_interface_ip(
                    device_id=str(r.get("device_id") or ""),
                    interface_name=str(r.get("interface_name") or ""),
                    raw_ip=str(r.get("ip_address") or ""),
                    raw_prefix=r.get("ip_prefix_length"),
                    vrf_name=vrf,
                    interface_type=str(r.get("interface_type") or ""),
                    admin_status=str(r.get("admin_status") or "unknown"),
                    oper_status=str(r.get("oper_status") or "unknown"),
                    source="cmdb_multi_address",
                )
        except Exception:
            pass

        # Source 2: Legacy single-address CMDB observations (strictly fallback when
        # no multi-address child row exists for that interface+generation, so VRF
        # addresses in the child table never leak into the 'default' VRF tree).
        try:
            obs_rows = db.execute(
                """SELECT o.device_id, o.interface_name, o.ip_address, o.ip_prefix_length,
                          o.interface_type, o.admin_status, o.oper_status
                     FROM cmdb_device_interface_observations o
                     JOIN cmdb_collection_snapshots s
                       ON s.device_id = o.device_id
                      AND s.domain = 'interface_inventory'
                      AND s.successful_generation = o.generation
                    WHERE o.ip_address IS NOT NULL AND o.ip_address <> ''
                      AND NOT EXISTS (
                          SELECT 1
                            FROM cmdb_device_interface_address_observations a
                           WHERE a.device_id = o.device_id
                             AND a.normalized_interface_name = o.normalized_interface_name
                             AND a.generation = o.generation
                      )"""
            ).fetchall()
            for raw in obs_rows:
                r = _row_dict(raw)
                _index_interface_ip(
                    device_id=str(r.get("device_id") or ""),
                    interface_name=str(r.get("interface_name") or ""),
                    raw_ip=str(r.get("ip_address") or ""),
                    raw_prefix=r.get("ip_prefix_length"),
                    vrf_name="default",
                    interface_type=str(r.get("interface_type") or ""),
                    admin_status=str(r.get("admin_status") or "unknown"),
                    oper_status=str(r.get("oper_status") or "unknown"),
                    source="cmdb_interface",
                )
        except Exception:
            pass

        # Source 3: Shared interfaces table (includes SNMP-collected interfaces & VRFs)
        try:
            if_rows = db.execute(
                """SELECT i.device_id, i.interface_name,
                          COALESCE(NULLIF(BTRIM(i.primary_ip), ''), NULLIF(BTRIM(i.ip_address), '')) AS ip_address,
                          i.ip_prefix_length, i.interface_type,
                          COALESCE(i.certified_admin_status, i.admin_status, 'unknown') AS admin_status,
                          COALESCE(i.certified_oper_status, i.oper_status, 'unknown') AS oper_status,
                          COALESCE(v.vrf_name, 'default') AS vrf_name
                     FROM interfaces i
                     LEFT JOIN vrfs v ON v.id = i.vrf_id
                    WHERE COALESCE(NULLIF(BTRIM(i.primary_ip), ''), NULLIF(BTRIM(i.ip_address), '')) IS NOT NULL"""
            ).fetchall()
            for raw in if_rows:
                r = _row_dict(raw)
                _index_interface_ip(
                    device_id=str(r.get("device_id") or ""),
                    interface_name=str(r.get("interface_name") or ""),
                    raw_ip=str(r.get("ip_address") or ""),
                    raw_prefix=r.get("ip_prefix_length"),
                    vrf_name=str(r.get("vrf_name") or "default"),
                    interface_type=str(r.get("interface_type") or ""),
                    admin_status=str(r.get("admin_status") or "unknown"),
                    oper_status=str(r.get("oper_status") or "unknown"),
                    source="interfaces",
                )
        except Exception:
            pass

        # Source 4: Multi-domain ip_inventory
        try:
            inv_rows = db.execute(
                """SELECT device_id, interface, ip, mask,
                          COALESCE(vrf_name, 'default') AS vrf_name, type
                     FROM ip_inventory
                    WHERE ip IS NOT NULL AND ip <> ''"""
            ).fetchall()
            for raw in inv_rows:
                r = _row_dict(raw)
                _index_interface_ip(
                    device_id=str(r.get("device_id") or ""),
                    interface_name=str(r.get("interface") or ""),
                    raw_ip=str(r.get("ip") or ""),
                    raw_prefix=r.get("mask"),
                    vrf_name=str(r.get("vrf_name") or "default"),
                    interface_type=str(r.get("type") or ""),
                    admin_status="unknown",
                    oper_status="unknown",
                    source="ip_inventory",
                )
        except Exception:
            pass

        for tree in snapshot.per_vrf_trees.values():
            tree.finalize()
        return snapshot
    finally:
        if owns_conn:
            db.close()


_INDEX_LOCK = threading.RLock()
_CACHED_INDEX: IPAMRadixIndexSnapshot | None = None


def get_ipam_radix_index(
    conn: Any = None,
    *,
    ttl_seconds: float = 60.0,
    force_rebuild: bool = False,
) -> IPAMRadixIndexSnapshot:
    """Return a cached in-memory Exact_IP_Map + Per_VRF_Radix_Tree snapshot."""
    global _CACHED_INDEX
    # When an explicit transaction connection is provided by callers/tests,
    # build directly against that connection so uncommitted/isolated DB state is visible.
    if conn is not None:
        return build_ipam_radix_index(conn)
    with _INDEX_LOCK:
        now = time.monotonic()
        if (
            not force_rebuild
            and _CACHED_INDEX is not None
            and (now - _CACHED_INDEX.built_at) < max(1.0, float(ttl_seconds))
        ):
            return _CACHED_INDEX
        _CACHED_INDEX = build_ipam_radix_index()
        return _CACHED_INDEX


def invalidate_ipam_radix_index() -> None:
    """Clear the cached in-memory Radix index after interface/IP/VIP mutations."""
    global _CACHED_INDEX
    with _INDEX_LOCK:
        _CACHED_INDEX = None
