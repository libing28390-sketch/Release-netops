import { readVisibleTableData, TableExportData } from '../../components/ui/TableExportMenu';
import { authHeaders } from '../../api/http';
import { fetchAllPaginatedItems } from '../../utils/pagination';

export interface IpamExportColumn<T> {
  header: string;
  value: (item: T) => unknown;
}

const normalizeHeader = (value: string) => value.toLocaleLowerCase().replace(/[\s\p{P}\p{S}]/gu, '');

export function alignIpamExportDataToVisibleHeaders(table: HTMLTableElement | null, data: TableExportData): TableExportData {
  if (!table) throw new Error('IPAM table is not available for export');
  const visibleHeaders = readVisibleTableData(table).headers;
  const sourceIndexes = new Map(data.headers.map((header, index) => [normalizeHeader(header), index]));
  const selectedIndexes = visibleHeaders.map((header) => {
    const index = sourceIndexes.get(normalizeHeader(header));
    if (index === undefined) throw new Error(`No IPAM export mapping exists for visible column "${header}"`);
    return index;
  });
  return {
    headers: visibleHeaders,
    rows: data.rows.map((row) => selectedIndexes.map((index) => row[index] ?? '')),
  };
}

/** Keep explicit export rows aligned to the actual visible table headers. */
export function buildVisibleIpamExportData<T>(
  table: HTMLTableElement | null,
  columns: IpamExportColumn<T>[],
  records: T[],
): TableExportData {
  const rows = records.map((record) => columns.map((column) => column.value(record)));
  return alignIpamExportDataToVisibleHeaders(table, {
    headers: columns.map((column) => column.header),
    rows,
  });
}

/** Fetch every server-paginated IPAM record while retaining the active table filters. */
export function fetchAllIpamExportItems<T>(endpoint: string, filters: URLSearchParams): Promise<T[]> {
  return fetchAllPaginatedItems<T>(endpoint, new URLSearchParams(filters), 100);
}

export type IpamReconciliationTab = 'undocumented' | 'stale' | 'mismatched';
export interface IpamReconciliationResponse<T> {
  undocumented_endpoints?: T[];
  stale_ip_addresses?: T[];
  mismatched_endpoints?: T[];
  result_total?: number;
  page?: number;
  page_size?: number;
}

/** The reconciliation API places its paged rows in a tab-named property instead of `items`. */
export async function fetchAllIpamReconciliationItems<T>(
  endpoint: string,
  filters: URLSearchParams,
  tab: IpamReconciliationTab,
  request: typeof fetch = fetch,
): Promise<T[]> {
  const resultKey: Record<IpamReconciliationTab, keyof IpamReconciliationResponse<T>> = {
    undocumented: 'undocumented_endpoints',
    stale: 'stale_ip_addresses',
    mismatched: 'mismatched_endpoints',
  };
  const key = resultKey[tab];
  const rows: T[] = [];
  let expectedTotal: number | undefined;
  let page = 1;
  const pageSize = 100;

  while (expectedTotal === undefined || rows.length < expectedTotal) {
    const params = new URLSearchParams(filters);
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
    const response = await request(`${endpoint}?${params.toString()}`, { headers: authHeaders() });
    const payload = await response.json().catch(() => ({})) as IpamReconciliationResponse<T> & { detail?: string };
    if (!response.ok) throw new Error(payload.detail || `Failed to fetch IPAM reconciliation page ${page}`);

    const batch = payload[key];
    if (!Array.isArray(batch)) throw new Error('IPAM reconciliation returned an unsupported paginated response');
    const reportedTotal = Number(payload.result_total);
    if (!Number.isFinite(reportedTotal) || reportedTotal < 0) {
      throw new Error('IPAM reconciliation did not report a valid total; refusing to export partial results');
    }
    if (expectedTotal === undefined) expectedTotal = reportedTotal;
    if (reportedTotal !== expectedTotal) throw new Error('IPAM reconciliation total changed during export; retry the export');
    rows.push(...batch);

    if (rows.length >= expectedTotal) break;
    if (batch.length === 0) throw new Error(`IPAM reconciliation export ended at ${rows.length} of ${expectedTotal} rows`);
    page += 1;
  }

  return rows.slice(0, expectedTotal || 0);
}
