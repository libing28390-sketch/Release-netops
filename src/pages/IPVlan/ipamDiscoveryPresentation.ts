export type DiscoveryKind = 'ip' | 'mac' | 'all';
export type DiscoveryEvidenceStatus = 'recent' | 'stale' | 'scope_pending' | 'conflict';
export type DiscoveryRegistrationStatus = 'registered' | 'unregistered' | 'scope_pending' | 'not_applicable';

export interface DiscoveredEndpointFilters {
  siteId: string;
  vrfId: string;
  deviceId: string;
  query: string;
  kind: DiscoveryKind;
  networkScope: 'business_vlan' | 'all';
  endpointClass: 'all' | 'terminal' | 'infrastructure' | 'access_host' | 'candidate';
  evidenceStatus: string;
  registrationStatus: string;
  page: number;
  pageSize: number;
}

export interface DiscoveredEndpointRow {
  id: string;
  ip: string | null;
  mac: string | null;
  tenant_id?: string | null;
  site_id?: string | null;
  site_name?: string | null;
  vrf_id?: string | null;
  address_space_id?: string | null;
  address_space_name?: string | null;
  vrf_name?: string | null;
  address_space_kind?: 'global' | 'vrf' | string;
  vrf_context_status?: string;
  vrf_context_inferred?: boolean;
  scope_status?: string;
  registration_status?: string;
  subnet_id?: string | null;
  subnet_prefix?: string | null;
  suggested_subnet_id?: string | null;
  suggested_subnet_prefix?: string | null;
  source_device_id?: string | null;
  source_device_name?: string | null;
  switch_id?: string | null;
  switch_name?: string | null;
  switch_port?: string | null;
  vlan?: string | null;
  observed_at?: string | null;
  mac_observed_at?: string | null;
  projected_at?: string | null;
  evidence_status?: string;
  collection_status?: string;
  generation?: number;
  latest_attempt_generation?: number;
  last_success_generation?: number;
  last_success_at?: string | null;
  hostname?: string | null;
  source_type?: string;
  observation_source?: string;
  path_ambiguity?: boolean;
  path_ambiguity_reason?: string;
  path_classification?: string;
  path_evidence?: string;
  aggregation_name?: string;
  aggregation_protocol?: string;
  topology_link_kind?: string;
  virtual_gateway_mac?: boolean;
  endpoint_class?: string;
  endpoint_class_reason?: string;
}

export interface DiscoveryFilterOption {
  id: string;
  name: string;
}

export function canRegisterEndpoint(item: DiscoveredEndpointRow): boolean {
  const source = (item.observation_source || item.source_type || '').toLowerCase();
  return Boolean(item.ip && item.observed_at)
    && ['arp', 'ndp'].includes(source)
    && item.endpoint_class !== 'infrastructure'
    && item.registration_status !== 'registered'
    && !['stale', 'conflict'].includes(item.evidence_status || '');
}

export function buildDiscoveredEndpointQuery(filters: DiscoveredEndpointFilters): URLSearchParams {
  const params = new URLSearchParams({
    kind: filters.kind,
    network_scope: filters.kind === 'mac' ? 'all' : filters.networkScope,
    page: String(Math.max(1, filters.page)),
    page_size: String(Math.max(1, filters.pageSize)),
  });
  if (filters.siteId) params.set('site_id', filters.siteId);
  if (filters.vrfId) params.set('vrf_id', filters.vrfId);
  if (filters.deviceId) params.set('device_id', filters.deviceId);
  if (filters.query.trim()) params.set('q', filters.query.trim());
  if (filters.evidenceStatus) params.set('evidence_status', filters.evidenceStatus);
  if (filters.registrationStatus) params.set('registration_status', filters.registrationStatus);
  if (filters.endpointClass !== 'all') params.set('endpoint_class', filters.endpointClass);
  return params;
}

export function getEndpointClassLabel(value: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    infrastructure: ['基础设施 IP', 'Infrastructure IPs'],
    access_host: ['已定位接入口', 'Access port located'],
    candidate: ['接入口待定位', 'Access port pending'],
    mac_only: ['仅有 MAC', 'MAC only'],
  };
  return labels[value || '']?.[zh ? 0 : 1] || (zh ? '类型待确认' : 'Type pending');
}

export function getEndpointClassReason(value: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    current_l3_interface_ip: ['设备三层接口 IP', 'Matches a current device L3 interface IP'],
    managed_device_ip: ['已登记设备的管理 IP', 'Matches an IP assigned to a registered device'],
    managed_device_site_mismatch: ['同一 IP 已登记在另一站点，归属待核实', 'The same IP is registered at another site; ownership needs review'],
    virtual_gateway_mac: ['虚拟网关 MAC', 'Matches a virtual gateway MAC'],
    same_device_vlan_fdb_access: ['MAC 地址表已定位到同 VLAN 的 Access 接口', 'A MAC address table entry on the same device and VLAN matches a port explicitly marked Access'],
    access_path_not_confirmed: ['尚未定位到唯一接入口', 'No unique access port located yet'],
    fdb_without_ip: ['未获取到对应 IP', 'MAC address table observation without an observed IP'],
  };
  return labels[value || '']?.[zh ? 0 : 1] || '';
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function normalizeDiscoveryOptions(value: unknown, idKeys: string[], nameKeys: string[]): DiscoveryFilterOption[] {
  const root = asRecord(value);
  const rows = Array.isArray(value)
    ? value
    : Array.isArray(root?.items)
      ? root.items
      : Array.isArray(root?.data)
        ? root.data
        : [];
  return rows.flatMap((raw) => {
    const row = asRecord(raw);
    if (!row) return [];
    const id = idKeys.map((key) => row[key]).find((candidate) => typeof candidate === 'string' && candidate.trim());
    if (typeof id !== 'string') return [];
    const name = nameKeys.map((key) => row[key]).find((candidate) => typeof candidate === 'string' && candidate.trim());
    return [{ id, name: typeof name === 'string' ? name : id }];
  });
}

export function getDiscoveryPortLabel(item: Pick<DiscoveredEndpointRow, 'ip' | 'mac_observed_at' | 'switch_port'>, zh: boolean): string {
  if (item.switch_port?.trim()) return item.switch_port;
  return zh ? '端口待定位' : 'Port pending';
}

export function getDiscoveryPathLabel(
  item: Pick<DiscoveredEndpointRow, 'path_classification' | 'aggregation_name' | 'virtual_gateway_mac'>,
  zh: boolean,
): string {
  const aggregation = item.aggregation_name?.trim();
  const suffix = aggregation ? ` · ${aggregation}` : '';
  const labels: Record<string, [string, string]> = {
    logical_aggregation: ['逻辑聚合接口', 'Logical aggregation'],
    aggregation_member: ['聚合成员', 'Aggregation member'],
    topology_aggregation_link: ['拓扑聚合链路', 'Topology aggregation link'],
    trunk_tagged_interface: ['Trunk / 标签接口（非唯一终端口）', 'Trunk / tagged interface (not a unique edge port)'],
    topology_neighbor_link: ['拓扑邻接链路', 'Topology neighbor link'],
    access_edge: ['Access 接入口', 'Interface explicitly marked Access'],
    unknown: ['接入路径待核实', 'Path unconfirmed'],
  };
  const label = labels[item.path_classification || '']?.[zh ? 0 : 1] || '';
  const virtualMac = item.virtual_gateway_mac
    ? (zh ? '虚拟网关 MAC' : 'Virtual gateway MAC')
    : '';
  return [label ? `${label}${suffix}` : '', virtualMac].filter(Boolean).join(' · ');
}

export function getDiscoveryHostname(item: Pick<DiscoveredEndpointRow, 'hostname'>, zh: boolean): string {
  return item.hostname?.trim() || (zh ? '未知' : 'Unknown');
}

export function getDiscoveryTypeLabel(zh: boolean): string {
  return zh ? '类型未知' : 'Type unknown';
}

export function getDiscoveryEvidenceLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    recent: ['最近采集', 'Recent collection'],
    stale: ['采集记录较旧', 'Older collection data'],
    scope_pending: ['所属网络待确认', 'Network scope pending'],
    conflict: ['IP/MAC 冲突', 'IP/MAC conflict'],
    unknown: ['采集时间未知（暂不参与对账）', 'Observation time unknown (excluded from reconciliation)'],
  };
  const label = labels[status || ''];
  return label ? label[zh ? 0 : 1] : (zh ? '未知' : 'Unknown');
}

export function getDiscoveryCollectionStatusLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    complete: ['采集完成', 'Collection complete'],
    complete_empty: ['采集完成（空结果）', 'Collection complete (empty)'],
    scope_unknown: ['所属网络待确认', 'Network scope pending'],
    partial: ['部分采集', 'Partial collection'],
    failed: ['采集失败', 'Collection failed'],
    unsupported: ['设备不支持', 'Unsupported by device'],
  };
  const label = labels[status || ''];
  return label ? label[zh ? 0 : 1] : (status || (zh ? '状态待确认' : 'Status pending'));
}

export function getDiscoveryRegistrationLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    registered: ['已登记', 'Registered'],
    unregistered: ['未登记', 'Unregistered'],
    scope_pending: ['所属网络待确认', 'Network scope pending'],
    not_applicable: ['仅有 MAC，无法登记 IP', 'MAC only; IP registration unavailable'],
  };
  const label = labels[status || ''];
  return label ? label[zh ? 0 : 1] : (zh ? '未知' : 'Unknown');
}

export function getDiscoveryObservationSourceLabel(observationSource: unknown, sourceType: unknown, zh: boolean): string {
  const source = [observationSource, sourceType].find((candidate) => typeof candidate === 'string' && candidate.trim());
  const normalizedSource = typeof source === 'string' ? source.trim() : '';
  if (!normalizedSource) return zh ? '来源待确认' : 'Source pending';

  const labels: Record<string, [string, string]> = {
    arp: ['ARP 表', 'ARP table'],
    ndp: ['IPv6 邻居表（ND）', 'IPv6 neighbor table (ND)'],
    fdb: ['MAC 地址表（FDB）', 'MAC address table (FDB)'],
  };
  const label = labels[normalizedSource.toLowerCase()];
  if (label) return label[zh ? 0 : 1];

  return zh ? `来源待确认（${normalizedSource}）` : `Source pending (${normalizedSource})`;
}

export function getDiscoveryCoverageLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    complete: ['数据可核对', 'Ready to compare'],
    partial: ['采集或网络归属待核实', 'Scope or coverage needs review'],
    unavailable: ['暂无可用采集记录', 'No usable discovery evidence'],
    no_inputs: ['暂无数据', 'No data yet'],
    scope_pending: ['所属网络待确认', 'Network scope pending'],
  };
  return labels[status || '']?.[zh ? 0 : 1] || (zh ? '数据状态未知' : 'Data status unknown');
}
