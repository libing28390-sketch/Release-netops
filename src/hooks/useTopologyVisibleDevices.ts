import { useEffect, useMemo, useState } from 'react';
import type { Device, TagDefinition } from '../types';
import type { TagExpressionGroup, TagFilterConfig } from '../components/TagConditionPicker';
import { NETWORK_TOPOLOGY_ROLE_VALUES } from '../domain/topologyRoles';
import { getTopologySiteKey } from '../utils/topologySiteOverview';

interface UseTopologyVisibleDevicesParams {
  devices: Device[];
  topologySearch: string;
  topologyStatusFilter: 'all' | 'online' | 'offline' | 'pending';
  topologyRoleFilter: string;
  topologySiteFilter: string;
  topologyTagFilter: TagFilterConfig;
}

export type TopologyDeviceStatusFilter = 'all' | 'online' | 'offline' | 'pending';

export const matchesTopologyStatusFilter = (
  device: Pick<Device, 'status'>,
  filter: TopologyDeviceStatusFilter,
): boolean => (
  filter === 'all' || String(device.status || '').trim().toLowerCase() === filter
);

const hasExpressionTerms = (group: TagExpressionGroup): boolean => (
  group.tag_ids.length > 0 || group.groups.some(hasExpressionTerms)
);

const CANONICAL_TOPOLOGY_ROLES = new Set(NETWORK_TOPOLOGY_ROLE_VALUES);
const LEGACY_TOPOLOGY_ROLE_ALIASES: Record<string, string> = {
  core_switch: 'core',
  aggregation_switch: 'distribution',
  access_switch: 'access',
  wireless_ac: 'wireless_controller',
  ap: 'wireless_ap',
  sd_wan_edge: 'sdwan_edge',
  other: 'other_network',
};

export const getTopologyRoleKey = (device: Device): string => {
  const rawRole = String(device.role || '').trim().toLowerCase();
  if (CANONICAL_TOPOLOGY_ROLES.has(rawRole)) return rawRole;
  if (LEGACY_TOPOLOGY_ROLE_ALIASES[rawRole]) return LEGACY_TOPOLOGY_ROLE_ALIASES[rawRole];
  const fingerprint = [device.role, device.hostname, device.model, device.platform]
    .map(value => String(value || '').toLowerCase())
    .join(' ');
  if (/(sd[-_ ]?wan)/.test(fingerprint)) return 'sdwan_edge';
  if (/(wireless controller|wireless[_ -]?ac|无线控制器|无线 ?ac)/.test(fingerprint)) return 'wireless_controller';
  if (/(wireless[_ -]?ap|无线接入点|无线 ?ap)/.test(fingerprint)) return 'wireless_ap';
  if (/(oob|out[-_ ]?of[-_ ]?band|带外)/.test(fingerprint)) return 'oob_switch';
  if (/(waf|web application firewall|web防火墙)/.test(fingerprint)) return 'waf';
  if (/(load[-_ ]?balanc|\blb\b|f5|big[-_ ]?ip|adc\b|netscaler|citrix adc|haproxy|nginx plus)/.test(fingerprint)) return 'load_balancer';
  if (/(vpn|ipsec gateway|ssl vpn|远程接入网关)/.test(fingerprint)) return 'vpn_gateway';
  if (/(firewall|防火墙|fortigate|forti|palo|pan-|checkpoint|srx|asa|ftd|fw\b)/.test(fingerprint)) return 'firewall';
  if (/(router|路由器|gateway|网关|wan|edge[- ]?router|isr|asr|mx\b)/.test(fingerprint)) return 'router';
  if (/(core|核心|backbone|骨干)/.test(fingerprint)) return 'core';
  if (/(distribution|aggregation|汇聚|分布)/.test(fingerprint)) return 'distribution';
  if (/(access|接入|acc[-_ ]?sw)/.test(fingerprint)) return 'access';
  if (/(edge|边缘)/.test(fingerprint)) return 'edge';
  if (/(switch|交换机)/.test(fingerprint)) return 'switch';
  return rawRole;
};

export const getTopologyRoleOptions = (devices: Device[]): string[] => {
  const customRoles = devices
    .map(getTopologyRoleKey)
    .filter(role => role && !CANONICAL_TOPOLOGY_ROLES.has(role));
  return [...NETWORK_TOPOLOGY_ROLE_VALUES, ...Array.from(new Set(customRoles)).sort((left, right) => left.localeCompare(right))];
};

export const matchesTopologyTagConditions = (device: Device, filter: TagFilterConfig) => {
  const expression = filter.expression;
  if (!expression || !hasExpressionTerms(expression)) return true;
  const deviceTagIds = new Set((device.tags || []).map((tag) => tag.id));
  const matchesGroup = (group: TagExpressionGroup, depth = 0): boolean => {
    if (depth > 16) return false;
    const values = [
      ...group.tag_ids.map(tagId => deviceTagIds.has(tagId)),
      ...group.groups.map(child => matchesGroup(child, depth + 1)),
    ];
    if (values.length === 0) return false;
    const result = group.operator === 'or' ? values.some(Boolean) : values.every(Boolean);
    return group.negated ? !result : result;
  };
  return matchesGroup(expression);
};

export const useTopologyVisibleDevices = ({
  devices,
  topologySearch,
  topologyStatusFilter,
  topologyRoleFilter,
  topologySiteFilter,
  topologyTagFilter,
}: UseTopologyVisibleDevicesParams) => {
  const [tagDefinitions, setTagDefinitions] = useState<TagDefinition[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const token = localStorage.getItem('netops_token');
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
    fetch('/api/tags/definitions', { headers, signal: controller.signal })
      .then(response => response.ok ? response.json() : Promise.reject(new Error('Failed to load tag definitions')))
      .then(payload => {
        const definitions = (Array.isArray(payload) ? payload : (payload.data ?? [])) as TagDefinition[];
        setTagDefinitions(definitions.filter(tag => Number(tag.is_active ?? 1) !== 0));
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setTagDefinitions(null);
      });
    return () => controller.abort();
  }, []);

  const topologySiteOptions = useMemo(() => {
    const sites = new Map<string, string>();
    devices.forEach((device) => {
      const id = getTopologySiteKey(device);
      if (id !== 'unassigned') {
        sites.set(id, String(device.site_name || device.site || device.site_code || id));
      }
    });
    return Array.from(sites.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((left, right) => left.name.localeCompare(right.name));
  }, [devices]);

  const topologyRoleOptions = useMemo(() => {
    return getTopologyRoleOptions(devices);
  }, [devices]);

  const topologyTagOptions = useMemo(() => {
    const tags = new Map<string, TagDefinition>();
    if (tagDefinitions !== null) {
      tagDefinitions.forEach(tag => tags.set(tag.id, tag));
    } else {
      devices.forEach((device) => {
        (device.tags || []).forEach((tag) => {
          if (!tags.has(tag.id)) tags.set(tag.id, tag);
        });
      });
    }
    return Array.from(tags.values()).sort((left, right) => (
      String(left.category).localeCompare(String(right.category))
      || Number(left.sort_order || 0) - Number(right.sort_order || 0)
      || String(left.label || left.code).localeCompare(String(right.label || right.code))
    ));
  }, [devices, tagDefinitions]);

  const topologyTagCandidateDevices = useMemo(() => {
    const query = topologySearch.trim().toLowerCase();
    const managed = devices.filter((device) => {
      const matchesQuery = !query || [device.hostname, device.ip_address, device.site, device.role].some((value) => String(value || '').toLowerCase().includes(query));
      const matchesStatus = matchesTopologyStatusFilter(device, topologyStatusFilter);
      const matchesRole = topologyRoleFilter === 'all' || getTopologyRoleKey(device) === topologyRoleFilter;
      const matchesSite = topologySiteFilter === 'all' || getTopologySiteKey(device) === topologySiteFilter;
      return matchesQuery && matchesStatus && matchesRole && matchesSite;
    });

    // Unmanaged LLDP peers are retained by the discovery API as evidence,
    // but they are not CMDB assets and should not become pseudo-devices on the
    // primary topology canvas. Rendering them as "?" nodes makes a confirmed
    // device chain look disconnected and noisy. They remain available to the
    // backend/inspection views for later onboarding.
    return managed;
  }, [devices, topologyRoleFilter, topologySearch, topologySiteFilter, topologyStatusFilter]);

  const topologyVisibleDevices = useMemo(() => {
    // Tag conditions are evaluated as a recursive AND/OR/NOT expression before rendering.
    if (!hasExpressionTerms(topologyTagFilter.expression)) return topologyTagCandidateDevices;
    return topologyTagCandidateDevices.filter((device) => matchesTopologyTagConditions(device, topologyTagFilter));
  }, [topologyTagCandidateDevices, topologyTagFilter]);

  return {
    topologySiteOptions,
    topologyRoleOptions,
    topologyTagOptions,
    topologyTagCandidateDevices,
    topologyVisibleDevices,
  };
};
