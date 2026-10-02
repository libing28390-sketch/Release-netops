import type { TableExportData } from '../components/ui/TableExportMenu';

export interface InspectionItemExportRecord {
  id: string;
  name?: string | null;
  name_zh?: string | null;
  category?: string | null;
  check_key?: string | null;
  description?: string | null;
  command?: string | null;
  method?: string | null;
  vendor?: string | null;
  oid?: string | null;
  script_id?: string | null;
  warning_threshold?: number | null;
  critical_threshold?: number | null;
}

export interface InspectionScriptLabel {
  id: string;
  name?: string | null;
}

export interface InspectionItemFilters {
  category: string;
  method: string;
  vendor: string;
  search: string;
}

const CATEGORIES: Record<string, { zh: string; en: string }> = {
  Network: { zh: '网络设备', en: 'Network Device' },
  Server: { zh: '服务器/主机', en: 'Server / Host' },
  Connectivity: { zh: '基础连通性', en: 'Connectivity' },
  Interface: { zh: '接口统计', en: 'Interface' },
  Health: { zh: '业务健康度', en: 'Health' },
  Compliance: { zh: '合规性检查', en: 'Compliance' },
};

export function getFriendlyInspectionVendor(vendor?: string | null): string {
  if (!vendor) return 'Generic';
  const lower = vendor.toLowerCase();
  if (lower.startsWith('cisco')) return 'Cisco';
  if (lower.startsWith('huawei')) return 'Huawei';
  if (lower.startsWith('h3c')) return 'H3C';
  if (lower.startsWith('juniper')) return 'Juniper';
  if (lower.startsWith('arista')) return 'Arista';
  if (lower.startsWith('paloalto') || lower.startsWith('panos')) return 'PaloAlto';
  if (lower.startsWith('fortinet')) return 'Fortinet';
  if (lower.startsWith('checkpoint') || lower.startsWith('gaia')) return 'Checkpoint';
  if (lower.startsWith('hillstone') || lower.startsWith('stoneos')) return 'Hillstone';
  if (lower.startsWith('ruijie')) return 'Ruijie';
  return vendor.charAt(0).toUpperCase() + vendor.slice(1);
}

export function filterInspectionItems<T extends InspectionItemExportRecord>(
  items: T[],
  filters: InspectionItemFilters,
): T[] {
  const query = filters.search.toLocaleLowerCase();
  return items.filter((item) => {
    if (filters.category !== 'All' && item.category !== filters.category) return false;
    if (filters.method !== 'All' && (item.method || '').toUpperCase() !== filters.method) return false;
    if (filters.vendor !== 'All' && getFriendlyInspectionVendor(item.vendor) !== filters.vendor) return false;
    if (!query) return true;
    return [item.name, item.name_zh, item.category, item.check_key, item.oid, item.command, item.description, item.vendor]
      .some((value) => String(value || '').toLocaleLowerCase().includes(query));
  });
}

const display = (value: unknown, fallback = '—') => value === null || value === undefined || value === '' ? fallback : String(value);
const threshold = (value?: number | null) => value == null ? '—' : `${value}%`;

export function buildInspectionItemsExportData(
  items: InspectionItemExportRecord[],
  scripts: InspectionScriptLabel[],
  language: string,
): TableExportData {
  const zh = language === 'zh';
  const scriptNames = new Map(scripts.map((script) => [script.id, script.name || '']));
  return {
    headers: zh
      ? ['中文名称', '英文名称', '分类', '厂商', '检查 Key', '采集方式', '绑定脚本', 'OID', '警告阈值', '严重阈值', '描述']
      : ['Chinese Name', 'English Name', 'Category', 'Vendor', 'Check Key', 'Collection Method', 'Bound Script', 'OID', 'Warning Threshold', 'Critical Threshold', 'Description'],
    rows: items.map((item) => [
      display(item.name_zh),
      display(item.name),
      CATEGORIES[item.category || ''] ? (zh ? CATEGORIES[item.category || ''].zh : CATEGORIES[item.category || ''].en) : display(item.category),
      display(item.vendor),
      display(item.check_key),
      display(item.method?.toUpperCase()),
      item.script_id ? display(scriptNames.get(item.script_id), '') : '',
      display(item.oid),
      threshold(item.warning_threshold),
      threshold(item.critical_threshold),
      display(item.description, zh ? '暂无指标业务描述' : 'No description'),
    ]),
  };
}
