import type { TableExportData } from '../components/ui/TableExportMenu';

export interface InspectionRunExportRecord {
  id: string;
  trigger_type?: string | null;
  scope_type?: string | null;
  scope_filter?: string | null;
  created_by?: string | null;
  total_devices?: number | null;
  healthy_count?: number | null;
  warning_count?: number | null;
  critical_count?: number | null;
  avg_health_score?: number | null;
  started_at?: string | null;
}

export interface InspectionResultExportRecord {
  id?: string;
  device_id?: string;
  hostname?: string | null;
  ip_address?: string | null;
  platform?: string | null;
  health_status?: string | null;
  health_score?: number | null;
  cpu_usage?: number | null;
  memory_usage?: number | null;
  temperature?: number | null;
  fan_status?: boolean | 0 | 1 | string | null;
  psu_status?: boolean | 0 | 1 | string | null;
  interface_total?: number | null;
  interface_down?: number | null;
  ping_ok?: number | boolean | null;
  ssh_ok?: number | boolean | null;
}

const display = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value);
const readableDate = (value?: string | null) => value ? value.replace('T', ' ').slice(0, 19) : '—';
const stateLabel = (value: unknown) => {
  if (value === true || value === 1 || value === '1' || value === 'true') return '✓';
  if (value === false || value === 0 || value === '0' || value === 'false') return '✗';
  return display(value);
};

export function filterInspectionRuns(runs: InspectionRunExportRecord[], search: string): InspectionRunExportRecord[] {
  const query = search.trim().toLocaleLowerCase();
  if (!query) return runs;
  return runs.filter((run) => [run.id, run.created_by, run.trigger_type, run.scope_type, run.scope_filter]
    .some((value) => String(value || '').toLocaleLowerCase().includes(query)));
}

export function buildInspectionRunExportData(
  runs: InspectionRunExportRecord[],
  language: string,
  search = '',
): TableExportData {
  const zh = language === 'zh';
  const filtered = filterInspectionRuns(runs, search);
  return {
    headers: zh
      ? ['触发方式', '范围类型', '范围', '创建人', '设备总数', '正常设备', '告警设备', '严重设备', '平均得分', '开始时间']
      : ['Trigger', 'Scope Type', 'Scope', 'Created By', 'Total Devices', 'Healthy Devices', 'Warning Devices', 'Critical Devices', 'Average Score', 'Started At'],
    rows: filtered.map((run) => [
      display(run.trigger_type),
      display(run.scope_type),
      display(run.scope_filter || (zh ? '全部' : 'all')),
      display(run.created_by || 'system'),
      display(run.total_devices),
      display(run.healthy_count),
      display(run.warning_count),
      display(run.critical_count),
      display(run.avg_health_score),
      readableDate(run.started_at),
    ]),
  };
}

/** Export the compact dashboard table, whose columns differ from history. */
export function buildRecentInspectionRunExportData(
  runs: InspectionRunExportRecord[],
  language: string,
): TableExportData {
  const zh = language === 'zh';
  return {
    headers: zh
      ? ['触发类型', '范围类型', '范围', '设备总数', '正常设备', '告警设备', '严重设备', '平均得分', '执行时间']
      : ['Trigger', 'Scope Type', 'Scope', 'Devices', 'Healthy', 'Warning', 'Critical', 'Avg Score', 'Time'],
    rows: runs.map((run) => [
      display(run.trigger_type),
      display(run.scope_type),
      display(run.scope_filter || (zh ? '全部' : 'all')),
      display(run.total_devices),
      display(run.healthy_count),
      display(run.warning_count),
      display(run.critical_count),
      display(run.avg_health_score),
      run.started_at ? run.started_at.replace('T', ' ').slice(0, 19) : '-',
    ]),
  };
}

export function buildInspectionResultExportData(
  results: InspectionResultExportRecord[],
  language: string,
): TableExportData {
  const zh = language === 'zh';
  return {
    headers: zh
      ? ['主机名', 'IP 地址', '厂商平台', '健康状态', '得分', 'CPU', '内存', '温度', '风扇状态', '电源状态', '接口总数', '接口 Down 数', 'Ping', 'SSH']
      : ['Hostname', 'IP Address', 'Platform', 'Health Status', 'Score', 'CPU', 'Memory', 'Temperature', 'Fan Status', 'PSU Status', 'Total Interfaces', 'Down Interfaces', 'Ping', 'SSH'],
    rows: results.map((result) => [
      display(result.hostname),
      display(result.ip_address),
      display(result.platform),
      display(result.health_status),
      display(result.health_score),
      result.cpu_usage == null ? '—' : `${result.cpu_usage}%`,
      result.memory_usage == null ? '—' : `${result.memory_usage}%`,
      result.temperature == null ? '—' : `${result.temperature}°C`,
      stateLabel(result.fan_status),
      stateLabel(result.psu_status),
      display(result.interface_total),
      display(result.interface_down),
      stateLabel(result.ping_ok),
      stateLabel(result.ssh_ok),
    ]),
  };
}

/** Fetch all runs from the offset-based inspection history API. */
export async function fetchAllInspectionRuns<T extends InspectionRunExportRecord = InspectionRunExportRecord>(
  headers: HeadersInit,
  fetcher: typeof fetch = fetch,
  pageSize = 500,
): Promise<T[]> {
  const all: T[] = [];
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;

  while (true) {
    const response = await fetcher(`/api/inspections?limit=${pageSize}&offset=${offset}`, { headers });
    if (!response.ok) throw new Error(`Failed to fetch inspection runs (HTTP ${response.status})`);
    const payload = await response.json();
    const data = payload?.data;
    const items: T[] = Array.isArray(data)
      ? data
      : Array.isArray(data?.items)
        ? data.items
        : [];
    const reportedTotal = typeof data?.total === 'number' ? data.total : payload?.total;
    if (typeof reportedTotal === 'number' && Number.isFinite(reportedTotal)) total = Math.max(0, reportedTotal);

    if (items.length === 0) {
      if (Number.isFinite(total) && all.length < total) {
        throw new Error(`Inspection history ended at ${all.length} of ${total} rows`);
      }
      break;
    }

    all.push(...items);
    if (all.length >= total || (total === Number.POSITIVE_INFINITY && items.length < pageSize)) break;
    offset += items.length;
  }
  return all;
}
