import type { TableExportData } from '../components/ui/TableExportMenu';

export type ServerQuickFilter = 'all' | 'offline' | 'warning' | 'healthy';

export interface ServerExportRecord {
  id: string;
  hostname?: string | null;
  management_ip?: string | null;
  device_role?: string | null;
  vendor?: string | null;
  model?: string | null;
  datacenter?: string | null;
  rack?: string | null;
  rack_unit?: string | number | null;
  status?: string | null;
  department?: string | null;
}

export interface ServerVerificationExport {
  ping?: boolean | number | null;
  ssh?: boolean | number | null;
}

export interface ServerExportOptions {
  language: string;
  quickFilter: ServerQuickFilter;
  statusFilter?: string;
  vendorFilter?: string;
  datacenterFilter?: string;
  sortConfig?: { key: string; direction: 'asc' | 'desc' } | null;
  verification?: Record<string, ServerVerificationExport | undefined>;
}

const STATUS_LABELS: Record<string, { zh: string; en: string }> = {
  active: { zh: '在线', en: 'Online' },
  inactive: { zh: '离线', en: 'Offline' },
  maintenance: { zh: '维护中', en: 'Maintenance' },
  decommissioned: { zh: '已退役', en: 'Retired' },
};

const QUICK_STATUS: Record<Exclude<ServerQuickFilter, 'all'>, string> = {
  offline: 'inactive',
  warning: 'maintenance',
  healthy: 'active',
};

const display = (value: unknown, fallback = '—') => value === null || value === undefined || value === '' ? fallback : String(value);
const verificationLabel = (value: boolean | number | null | undefined) => value === true || value === 1 ? 'OK' : value === false || value === 0 ? 'FAIL' : '—';

export function filterInventoryServers<T extends ServerExportRecord>(
  records: T[],
  options: Pick<ServerExportOptions, 'quickFilter' | 'statusFilter' | 'vendorFilter' | 'datacenterFilter'>,
): T[] {
  return records.filter((record) => {
    if (options.statusFilter && options.statusFilter !== 'all' && record.status !== options.statusFilter) return false;
    if (options.vendorFilter && record.vendor !== options.vendorFilter) return false;
    if (options.datacenterFilter && record.datacenter !== options.datacenterFilter) return false;
    return options.quickFilter === 'all'
      || record.status === QUICK_STATUS[options.quickFilter as Exclude<ServerQuickFilter, 'all'>];
  });
}

export function buildInventoryServersExportData(
  records: ServerExportRecord[],
  options: ServerExportOptions,
): TableExportData {
  const zh = options.language === 'zh';
  const headers = zh
    ? ['主机名', '管理 IP', '角色', '厂商', '型号', '数据中心', '机柜', 'U 位', '状态', 'Ping', 'SSH', '部门']
    : ['Hostname', 'Management IP', 'Role', 'Vendor', 'Model', 'Datacenter', 'Rack', 'Rack Unit', 'Status', 'Ping', 'SSH', 'Department'];

  const filtered = filterInventoryServers(records, options);

  const sorted = options.sortConfig
    ? [...filtered].sort((left, right) => {
      const key = options.sortConfig!.key as keyof ServerExportRecord;
      const a = String(left[key] ?? '');
      const b = String(right[key] ?? '');
      const result = a.localeCompare(b);
      return options.sortConfig!.direction === 'asc' ? result : -result;
    })
    : filtered;

  return {
    headers,
    rows: sorted.map((record) => {
      const status = STATUS_LABELS[record.status || 'decommissioned'] || STATUS_LABELS.decommissioned;
      const verification = options.verification?.[record.id];
      return [
        display(record.hostname, 'Unknown'),
        display(record.management_ip, '0.0.0.0'),
        display(record.device_role),
        display(record.vendor),
        display(record.model),
        display(record.datacenter),
        display(record.rack),
        record.rack_unit === null || record.rack_unit === undefined || record.rack_unit === '' ? '—' : `U${record.rack_unit}`,
        zh ? status.zh : status.en,
        verificationLabel(verification?.ping),
        verificationLabel(verification?.ssh),
        display(record.department),
      ];
    }),
  };
}
