export type DiscoveryKind = 'ip' | 'mac' | 'all';
export type DiscoveryEvidenceStatus = 'recent' | 'historical' | 'scope_pending' | 'conflict';
export type DiscoveryRegistrationStatus = 'registered' | 'unregistered' | 'scope_pending';

export interface DiscoveredEndpointFilters {
  siteId: string;
  vrfId: string;
  deviceId: string;
  query: string;
  kind: DiscoveryKind;
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
  vrf_name?: string | null;
  scope_status?: string;
  registration_status?: string;
  subnet_id?: string | null;
  subnet_prefix?: string | null;
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
  hostname?: string | null;
}

export interface DiscoveryFilterOption {
  id: string;
  name: string;
}

export function buildDiscoveredEndpointQuery(filters: DiscoveredEndpointFilters): URLSearchParams {
  const params = new URLSearchParams({
    kind: filters.kind,
    page: String(Math.max(1, filters.page)),
    page_size: String(Math.max(1, filters.pageSize)),
  });
  if (filters.siteId) params.set('site_id', filters.siteId);
  if (filters.vrfId) params.set('vrf_id', filters.vrfId);
  if (filters.deviceId) params.set('device_id', filters.deviceId);
  if (filters.query.trim()) params.set('q', filters.query.trim());
  if (filters.evidenceStatus) params.set('evidence_status', filters.evidenceStatus);
  if (filters.registrationStatus) params.set('registration_status', filters.registrationStatus);
  return params;
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
  if (item.ip && !item.mac_observed_at) return zh ? '端口待定位（无 MAC 表证据）' : 'Port pending (no MAC-table evidence)';
  return zh ? '端口待定位' : 'Port pending';
}

export function getDiscoveryHostname(item: Pick<DiscoveredEndpointRow, 'hostname'>, zh: boolean): string {
  return item.hostname?.trim() || (zh ? '未知' : 'Unknown');
}

export function getDiscoveryTypeLabel(zh: boolean): string {
  return zh ? '类型未知' : 'Type unknown';
}

export function getDiscoveryEvidenceLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    recent: ['近期观察', 'Recent observation'],
    historical: ['历史观察', 'Historical observation'],
    scope_pending: ['归属待确认', 'Scope pending'],
    conflict: ['IP/MAC 冲突', 'IP/MAC conflict'],
    unknown: ['观察时间未知（不参与当前对账）', 'Observation time unknown (excluded from reconciliation)'],
  };
  const label = labels[status || ''];
  return label ? label[zh ? 0 : 1] : (zh ? '未知' : 'Unknown');
}

export function getDiscoveryRegistrationLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    registered: ['已登记', 'Registered'],
    unregistered: ['未登记', 'Unregistered'],
    scope_pending: ['归属待确认', 'Scope pending'],
  };
  const label = labels[status || ''];
  return label ? label[zh ? 0 : 1] : (zh ? '未知' : 'Unknown');
}

export function getDiscoveryCoverageLabel(status: string | undefined, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    complete: ['数据可核对', 'Ready to compare'],
    partial: ['部分来源待确认', 'Some sources need review'],
    unavailable: ['发现数据待更新', 'Discovery data needs updating'],
    no_inputs: ['暂无数据', 'No data yet'],
    scope_pending: ['来源归属待确认', 'Source scope needs review'],
  };
  return labels[status || '']?.[zh ? 0 : 1] || (zh ? '数据状态未知' : 'Data status unknown');
}
