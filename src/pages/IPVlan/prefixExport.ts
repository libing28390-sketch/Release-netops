export interface PrefixExportRecord {
  id?: string | number | null;
  parent_prefix_id?: string | null;
  prefix?: string | null;
  name?: string | null;
  status?: string | null;
  network_type?: string | null;
  vrf_id?: string | number | null;
  vrf_name?: string | null;
  vlan_id?: string | number | null;
  vlan_name?: string | null;
  vlan_display_name?: string | null;
  tenant_id?: string | null;
  tenant_name?: string | null;
  site_id?: string | null;
  site_name?: string | null;
  site_code?: string | null;
  gateway?: string | null;
  gateway_device_id?: string | null;
  gateway_device_name?: string | null;
  gateway_interface_id?: string | null;
  total_ips?: number | null;
  used_ips?: number | null;
  active_ips?: number | null;
  utilization?: number | null;
  classification_status?: string | null;
  classification_confidence?: number | null;
  manual_override?: number | boolean | string | null;
  mixed_network?: number | boolean | string | null;
  conflict_status?: string | null;
  traceable?: number | boolean | string | null;
  last_seen_at?: string | null;
  description?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export type PrefixExportCell = string | number;

export interface PrefixExportData {
  headers: string[];
  rows: PrefixExportCell[][];
}

export async function fetchAllPrefixPages(
  endpoint: string,
  filters: Record<string, string>,
  headers: HeadersInit,
  language: 'zh' | 'en',
  request: typeof fetch = fetch,
): Promise<PrefixExportRecord[]> {
  const pageSize = 100;
  const fetchPage = async (page: number, requestedPageSize = pageSize) => {
    const query = new URLSearchParams({ ...filters, page: String(page), page_size: String(requestedPageSize) });
    const response = await request(`${endpoint}?${query.toString()}`, { headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.detail || (language === 'zh' ? '读取前缀列表失败' : 'Unable to load prefixes for export'));
    }
    return payload;
  };

  const firstPage = await fetchPage(1);
  if (Array.isArray(firstPage)) return firstPage;
  if (!Array.isArray(firstPage?.items)) {
    throw new Error(language === 'zh' ? '前缀接口返回格式无法识别' : 'The prefix API returned an unsupported response');
  }

  const total = Number(firstPage.total);
  const actualPageSize = Number(firstPage.page_size) || pageSize;
  if (!Number.isFinite(total) || total < firstPage.items.length || actualPageSize < 1 || (total > 0 && firstPage.items.length === 0)) {
    throw new Error(language === 'zh' ? '服务端返回了不完整的分页数据，无法安全导出全部前缀' : 'The server returned incomplete pagination data; all prefixes cannot be exported safely');
  }

  const allPrefixes: PrefixExportRecord[] = [...firstPage.items];
  for (let page = Number(firstPage.page || 1) + 1; allPrefixes.length < total; page += 1) {
    const nextPage = await fetchPage(page, actualPageSize);
    if (!Array.isArray(nextPage?.items) || nextPage.items.length === 0) {
      throw new Error(language === 'zh' ? '读取后续分页失败，未生成部分导出文件' : 'A later page failed to load; no partial export was created');
    }
    allPrefixes.push(...nextPage.items);
  }
  return allPrefixes.slice(0, total);
}

const text = (value: unknown): string => value == null ? '' : String(value);
const flag = (value: number | boolean | string | null | undefined, zh: boolean): string => {
  if (value === null || value === undefined || value === '') return '';
  const enabled = value === true || value === 1 || value === '1';
  return zh ? (enabled ? '是' : '否') : (enabled ? 'Yes' : 'No');
};

const statusLabel = (status: string | null | undefined, zh: boolean): string => {
  const labels: Record<string, { zh: string; en: string }> = {
    container: { zh: '容器', en: 'Container' },
    active: { zh: '使用中', en: 'Active' },
    reserved: { zh: '已保留', en: 'Reserved' },
    deprecated: { zh: '已弃用', en: 'Deprecated' },
  };
  if (!status) return '';
  return labels[status]?.[zh ? 'zh' : 'en'] || status;
};

export function mapPrefixesForExport(prefixes: PrefixExportRecord[], language: 'zh' | 'en'): PrefixExportData {
  const zh = language === 'zh';
  const columns: Array<{ header: string; value: (prefix: PrefixExportRecord) => PrefixExportCell }> = [
    { header: zh ? '前缀ID' : 'Prefix ID', value: (prefix) => text(prefix.id) },
    { header: zh ? '父前缀ID' : 'Parent Prefix ID', value: (prefix) => text(prefix.parent_prefix_id) },
    { header: zh ? '前缀/CIDR' : 'Prefix / CIDR', value: (prefix) => text(prefix.prefix) },
    { header: zh ? '名称' : 'Name', value: (prefix) => text(prefix.name) },
    { header: zh ? '地址族' : 'Address Family', value: (prefix) => prefix.prefix?.includes(':') ? 'IPv6' : 'IPv4' },
    { header: zh ? '状态' : 'Status', value: (prefix) => statusLabel(prefix.status, zh) },
    { header: zh ? '网络类型' : 'Network Type', value: (prefix) => text(prefix.network_type) },
    { header: zh ? '站点' : 'Site', value: (prefix) => text(prefix.site_name || prefix.site_code) },
    { header: zh ? '站点ID' : 'Site ID', value: (prefix) => text(prefix.site_id) },
    { header: 'VRF', value: (prefix) => text(prefix.vrf_name) },
    { header: zh ? 'VRF ID' : 'VRF ID', value: (prefix) => text(prefix.vrf_id) },
    { header: 'VLAN', value: (prefix) => text(prefix.vlan_name || prefix.vlan_display_name || prefix.vlan_id) },
    { header: zh ? 'VLAN ID' : 'VLAN ID', value: (prefix) => text(prefix.vlan_id) },
    { header: zh ? '租户' : 'Tenant', value: (prefix) => text(prefix.tenant_name) },
    { header: zh ? '租户ID' : 'Tenant ID', value: (prefix) => text(prefix.tenant_id) },
    { header: zh ? '网关' : 'Gateway', value: (prefix) => text(prefix.gateway) },
    { header: zh ? '网关设备' : 'Gateway Device', value: (prefix) => text(prefix.gateway_device_name) },
    { header: zh ? '网关设备ID' : 'Gateway Device ID', value: (prefix) => text(prefix.gateway_device_id) },
    { header: zh ? '网关接口ID' : 'Gateway Interface ID', value: (prefix) => text(prefix.gateway_interface_id) },
    { header: zh ? '地址总数（导出时快照）' : 'Total IPs (export snapshot)', value: (prefix) => prefix.total_ips ?? 0 },
    { header: zh ? '已分配地址（导出时快照）' : 'Used IPs (export snapshot)', value: (prefix) => prefix.used_ips ?? 0 },
    { header: zh ? '在线地址（导出时快照）' : 'Active IPs (export snapshot)', value: (prefix) => prefix.active_ips ?? 0 },
    { header: zh ? '利用率%（导出时快照）' : 'Utilization % (export snapshot)', value: (prefix) => prefix.utilization ?? 0 },
    { header: zh ? '分类状态' : 'Classification Status', value: (prefix) => text(prefix.classification_status) },
    { header: zh ? '分类置信度' : 'Classification Confidence', value: (prefix) => prefix.classification_confidence ?? '' },
    { header: zh ? '人工覆盖' : 'Manual Override', value: (prefix) => flag(prefix.manual_override, zh) },
    { header: zh ? '混合网络' : 'Mixed Network', value: (prefix) => flag(prefix.mixed_network, zh) },
    { header: zh ? '冲突状态' : 'Conflict Status', value: (prefix) => text(prefix.conflict_status) },
    { header: zh ? '可追踪' : 'Traceable', value: (prefix) => flag(prefix.traceable, zh) },
    { header: zh ? '最近发现时间' : 'Last Seen At', value: (prefix) => text(prefix.last_seen_at) },
    { header: zh ? '描述' : 'Description', value: (prefix) => text(prefix.description) },
    { header: zh ? '创建时间' : 'Created At', value: (prefix) => text(prefix.created_at) },
    { header: zh ? '更新时间' : 'Updated At', value: (prefix) => text(prefix.updated_at) },
  ];

  return {
    headers: columns.map((column) => column.header),
    rows: prefixes.map((prefix) => columns.map((column) => column.value(prefix))),
  };
}

function escapeCsvCell(value: PrefixExportCell): string {
  const raw = String(value);
  const safe = /^[\t\r\n ]*[=+\-@]/u.test(raw) ? `'${raw}` : raw;
  return `"${safe.replace(/"/gu, '""')}"`;
}

export function serializePrefixCsv(data: PrefixExportData): string {
  const lines = [data.headers, ...data.rows].map((row) => row.map(escapeCsvCell).join(','));
  return `\uFEFF${lines.join('\r\n')}`;
}
