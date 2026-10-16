import type { TableExportData } from '../components/ui/TableExportMenu';

export interface MacChangeExportEntry {
  id?: number | string;
  ip: string;
  old_mac: string;
  new_mac: string;
  old_vendor?: string | null;
  new_vendor?: string | null;
  old_device?: string | null;
  new_device?: string | null;
  detected_at: string;
}

export interface MacChangePage {
  entries: MacChangeExportEntry[];
  total: number;
}

export async function loadAllMacChangeEntries(
  fetchPage: (offset: number, limit: number) => Promise<MacChangePage>,
  pageSize = 1000,
): Promise<MacChangeExportEntry[]> {
  const safePageSize = Math.max(1, Math.floor(pageSize));
  const entries: MacChangeExportEntry[] = [];
  let total = Number.POSITIVE_INFINITY;

  while (entries.length < total) {
    const page = await fetchPage(entries.length, safePageSize);
    total = Math.max(0, Number(page.total) || 0);
    const items = Array.isArray(page.entries) ? page.entries : [];
    if (items.length === 0) {
      if (entries.length < total) throw new Error(`MAC 变化记录分页提前结束：已读取 ${entries.length} / ${total} 条`);
      break;
    }
    entries.push(...items);
  }

  return Number.isFinite(total) ? entries.slice(0, total) : entries;
}

export function filterMacChangeEntries(entries: MacChangeExportEntry[], query: string): MacChangeExportEntry[] {
  const term = query.trim().toLowerCase();
  if (!term) return entries;
  return entries.filter(entry => [
    entry.ip,
    entry.old_mac,
    entry.new_mac,
    entry.old_vendor,
    entry.new_vendor,
    entry.old_device,
    entry.new_device,
  ].some(value => String(value || '').toLowerCase().includes(term)));
}

export function buildMacChangeExportData(
  entries: MacChangeExportEntry[],
  zh: boolean,
  formatDetectedAt: (value: string) => string = value => value,
): TableExportData {
  return {
    headers: [
      'IP',
      zh ? '旧 MAC' : 'Old MAC',
      zh ? '新 MAC' : 'New MAC',
      zh ? '旧厂商' : 'Old vendor',
      zh ? '新厂商' : 'New vendor',
      zh ? '来源设备' : 'Device',
      zh ? '检测时间' : 'Detected',
    ],
    rows: entries.map(entry => [
      entry.ip,
      entry.old_mac,
      entry.new_mac,
      entry.old_vendor || '?',
      entry.new_vendor || '?',
      entry.new_device || '-',
      formatDetectedAt(entry.detected_at),
    ]),
  };
}
