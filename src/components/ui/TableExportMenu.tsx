import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Download, FileSpreadsheet, FileText, LoaderCircle } from 'lucide-react';
import { ActionIconButton } from './ActionIconButton';

export type TableExportFormat = 'xlsx' | 'csv';
type ExportCell = string;
export type TableExportMarker = 'include' | 'ignore' | 'sensitive' | 'public';

/** Explicit data source for visual record grids that are not native HTML tables. */
export interface TableExportData {
  headers: string[];
  rows: unknown[][];
  columnMarkers?: Array<TableExportMarker | undefined>;
}

export type TableExportDataSource = TableExportData | (() => TableExportData | Promise<TableExportData>);

interface PreparedTableDownload {
  href: string;
  filename: string;
}

type PreparedTableDownloads = Record<TableExportFormat, PreparedTableDownload>;

export interface TableExportMenuProps {
  /** Reference to the table this menu exports. The visible table headers define the export columns and order. */
  tableRef?: React.RefObject<HTMLTableElement | null>;
  /** Explicit visible columns and rows for CSS-grid record lists. */
  exportData?: TableExportDataSource;
  /** Download filename without an extension. */
  filename: string;
  /** Optional language override. Defaults to the browser language. */
  language?: 'zh' | 'en';
  className?: string;
  disabled?: boolean;
  onExportError?: (error: Error) => void;
}

const normalizeHeader = (value: string) => value.toLocaleLowerCase().replace(/[\s\p{P}\p{S}]/gu, '');

const SYSTEM_ID_HEADERS = new Set([
  'id', 'uuid', 'guid', 'pk', 'primarykey', 'internalid', 'systemid', 'recordid', 'rowid', 'objectid', 'entityid',
  'assetid', 'siteid', 'deviceid', 'userid', 'tenantid', 'rackid', 'modelid', 'configid', 'organizationid', 'orgid', 'locationid',
  'vendorid', 'providerid', 'familyid', 'seriesid', 'productmodelid', 'sourceid', 'targetid', 'requestid', 'alertid', 'eventid', 'ruleid', 'jobid',
  'taskid', 'sessionid', 'executionid', 'runid', 'profileid', 'policyid', 'templateid', 'metricid', 'interfaceid', 'linkid', 'portid',
  'prefixid', 'poolid', 'ipaddressid', 'addressid', 'reservationid', 'assetidentifier', 'siteidentifier',
  '内部id', '系统id', '主键', '记录id', '行id', '对象id', '实体id', '资产id', '站点id', '设备id', '用户id', '租户id', '机柜id', '型号id', '配置id',
  '组织id', '位置id', '厂商id', '系列id', '产品型号id', '来源id', '目标id', '请求id', '告警id', '事件id', '规则id', '作业id',
  '任务id', '会话id', '执行id', '运行id', '策略id', '模板id', '指标id', '接口id', '链路id', '端口id', '前缀id', '地址池id', 'ip地址id', '地址id', '预约id',
]);

const ACTION_HEADERS = new Set(['操作', 'action', 'actions', '操作项', '更多操作']);
const SENSITIVE_HEADER = /(password|passwd|pwd|secret|credential|privatekey|accesskey|apikey|authorization|authkey|signingkey|clientsecret|bearer|webhook|connectionstring|connstring|dsn|community|fixedpin|pincode|pin码|固定pin|动态pin|pin口令|口令|密码|凭据|密钥|秘钥|令牌|授权码|认证码|验证码|加签|机器人地址|团体字|团体名|团体字符串)/i;
const NON_SECRET_LABEL_HEADER = /^(?:credential|credentials|凭据|apikey|accesskey|privatekey|密钥|秘钥)(?:name|label|title|名称|名字|标签|标题)$/i;
const TOKEN_SECRET_HEADER = /token/i;
const NON_SECRET_TOKEN_HEADER = /(?:tokens?(?:count|usage|used|consumed|in|out|budget|limit|用量|数量|消耗)|令牌用量|用量token)$/i;

function isExcludedHeader(header: string, explicit?: TableExportMarker): boolean {
  const normalized = normalizeHeader(header);
  return explicit === 'ignore'
    || (explicit !== 'include' && (ACTION_HEADERS.has(normalized) || SYSTEM_ID_HEADERS.has(normalized)));
}

function isSensitiveHeader(header: string, explicit?: TableExportMarker): boolean {
  const normalized = normalizeHeader(header);
  return explicit === 'sensitive'
    || (explicit !== 'public' && (
      (SENSITIVE_HEADER.test(normalized) && !NON_SECRET_LABEL_HEADER.test(normalized))
      || (TOKEN_SECRET_HEADER.test(normalized) && normalized !== 'tokens' && !NON_SECRET_TOKEN_HEADER.test(normalized))
    ));
}

function getVisibleColumns(table: HTMLTableElement): { index: number; header: string; sensitive: boolean }[] {
  const headerRow = table.tHead?.rows[0];
  if (!headerRow) return [];

  return Array.from(headerRow.cells).flatMap((cell, index) => {
    const header = (cell.innerText || cell.textContent || '').replace(/\s+/g, ' ').trim();
    const explicit = cell.dataset.export?.toLowerCase() as TableExportMarker | undefined;
    const isExcluded = cell.classList.contains('nx-action-column-header') || isExcludedHeader(header, explicit);
    const isHidden = cell.hidden || cell.getAttribute('aria-hidden') === 'true'
      || (typeof window !== 'undefined' && window.getComputedStyle(cell).display === 'none');
    if (!header || isExcluded || isHidden) return [];
    const sensitive = isSensitiveHeader(header, explicit);
    return [{ index, header, sensitive }];
  });
}

function getCellValue(cell: HTMLTableCellElement): ExportCell {
  const explicitValue = cell.dataset.exportValue;
  if (explicitValue !== undefined) return explicitValue.replace(/\s+/g, ' ').trim();
  const clone = cell.cloneNode(true) as HTMLTableCellElement;
  const replaceControlsWithLiveValues = (source: ParentNode, target: ParentNode) => {
    const selector = 'input:not([type="checkbox"]):not([type="radio"]):not([type="password"]):not([type="hidden"]), textarea, select';
    const sourceControls = source.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector);
    const targetControls = target.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector);
    sourceControls.forEach((sourceControl, index) => {
      const targetControl = targetControls.item(index);
      if (!targetControl) return;
      const value = sourceControl instanceof HTMLSelectElement
        ? sourceControl.selectedOptions[0]?.textContent ?? ''
        : sourceControl.value;
      targetControl.replaceWith(document.createTextNode(value));
    });
  };
  const primaryValue = clone.matches('[data-export-primary]')
    ? clone
    : clone.querySelector<HTMLElement>('[data-export-primary]');
  if (primaryValue) {
    const sourcePrimaryValue = cell.matches('[data-export-primary]')
      ? cell
      : cell.querySelector<HTMLElement>('[data-export-primary]');
    if (sourcePrimaryValue) replaceControlsWithLiveValues(sourcePrimaryValue, primaryValue);
    primaryValue.querySelectorAll('[data-export="ignore"], [data-export-ignore], [data-action-icon]').forEach((element) => element.remove());
    return (primaryValue.innerText ?? primaryValue.textContent ?? '').replace(/\s+/g, ' ').trim();
  }
  clone.querySelectorAll('[data-export="ignore"], [data-export-ignore], [data-action-icon]').forEach((element) => element.remove());
  replaceControlsWithLiveValues(cell, clone);
  return (clone.innerText ?? clone.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/** Read the currently rendered table view, retaining its visible column names and order. */
export function readVisibleTableData(table: HTMLTableElement): { headers: string[]; rows: ExportCell[][] } {
  const columns = getVisibleColumns(table);
  const rows = Array.from(table.tBodies).flatMap((body) => Array.from(body.rows))
    .filter((row) => !row.hidden && row.getAttribute('aria-hidden') !== 'true')
    .filter((row) => !(row.cells.length === 1 && row.cells[0].colSpan >= columns.length && columns.length > 1))
    .map((row) => columns.map(({ index, sensitive }) => sensitive || !row.cells[index] ? '' : getCellValue(row.cells[index])));
  return { headers: columns.map(({ header }) => header), rows };
}

/** Apply the same header, internal-ID, and sensitive-value rules to a visual grid data source. */
export function readExplicitTableData(data: TableExportData): { headers: string[]; rows: ExportCell[][] } {
  const columns = data.headers.flatMap((rawHeader, index) => {
    const header = String(rawHeader ?? '').replace(/\s+/g, ' ').trim();
    const explicit = data.columnMarkers?.[index];
    if (!header || isExcludedHeader(header, explicit)) return [];
    return [{ index, header, sensitive: isSensitiveHeader(header, explicit) }];
  });
  const rows = data.rows.map((row) => columns.map(({ index, sensitive }) => {
    if (sensitive) return '';
    const value = row[index];
    return value === null || value === undefined ? '' : String(value).replace(/\s+/g, ' ').trim();
  }));
  return { headers: columns.map(({ header }) => header), rows };
}

function escapeCsv(value: string): string {
  // Prevent user-controlled cell contents from becoming spreadsheet formulas.
  const safe = /^[\s]*[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function serializeTableCsv(headers: string[], rows: string[][]): string {
  return `\uFEFF${[headers, ...rows].map((row) => row.map(escapeCsv).join(',')).join('\r\n')}`;
}

function safeFilename(value: string): string {
  return value.trim().replace(/[\\/:*?"<>|]+/g, '_').replace(/\.+$/g, '') || 'table-export';
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.style.position = 'fixed';
  anchor.style.left = '-10000px';
  anchor.style.top = '0';
  anchor.style.width = '1px';
  anchor.style.height = '1px';
  anchor.style.overflow = 'hidden';
  anchor.setAttribute('aria-hidden', 'true');
  anchor.tabIndex = -1;
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    window.setTimeout(() => {
      anchor.remove();
      URL.revokeObjectURL(url);
    }, 1000);
  }
}

export function exportVisibleTable(table: HTMLTableElement, format: TableExportFormat, filename: string): void {
  void exportTableData(readVisibleTableData(table), format, filename);
}

export function exportExplicitTable(data: TableExportData, format: TableExportFormat, filename: string): void {
  void exportTableData(readExplicitTableData(data), format, filename);
}

async function createExportPayload(data: { headers: string[]; rows: ExportCell[][] }, format: TableExportFormat, filename: string): Promise<{ blob: Blob; filename: string }> {
  const { headers, rows } = data;
  if (!headers.length) throw new Error('The table has no exportable columns.');
  const normalizedFilename = safeFilename(filename);
  if (format === 'xlsx') {
    const XLSX = await import('xlsx');
    const worksheet = XLSX.utils.aoa_to_sheet([headers, ...rows]);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Data');
    const contents = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' });
    const blob = new Blob([contents], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    return { blob, filename: `${normalizedFilename}.xlsx` };
  }
  const blob = new Blob([serializeTableCsv(headers, rows)], { type: 'text/csv;charset=utf-8;' });
  return { blob, filename: `${normalizedFilename}.csv` };
}

async function createPreparedDownloads(data: { headers: string[]; rows: ExportCell[][] }, filename: string): Promise<PreparedTableDownloads> {
  const xlsxPayload = await createExportPayload(data, 'xlsx', filename);
  const csvPayload = await createExportPayload(data, 'csv', filename);
  const xlsxHref = URL.createObjectURL(xlsxPayload.blob);
  try {
    const csvHref = URL.createObjectURL(csvPayload.blob);
    return {
      xlsx: { href: xlsxHref, filename: xlsxPayload.filename },
      csv: { href: csvHref, filename: csvPayload.filename },
    };
  } catch (error) {
    URL.revokeObjectURL(xlsxHref);
    throw error;
  }
}

async function exportTableData(data: { headers: string[]; rows: ExportCell[][] }, format: TableExportFormat, filename: string): Promise<void> {
  const payload = await createExportPayload(data, format, filename);
  downloadBlob(payload.blob, payload.filename);
}

export const TableExportMenu: React.FC<TableExportMenuProps> = ({
  tableRef,
  exportData,
  filename,
  language,
  className,
  disabled = false,
  onExportError,
}) => {
  const [open, setOpen] = useState(false);
  const [isPreparingData, setIsPreparingData] = useState(false);
  const [preparedData, setPreparedData] = useState<{ headers: string[]; rows: ExportCell[][] } | null>(null);
  const [preparedDownloads, setPreparedDownloads] = useState<PreparedTableDownloads | null>(null);
  const [exportError, setExportError] = useState('');
  const exportDataRequestId = useRef(0);
  const lastExportDataSource = useRef(exportData);
  const preparedDownloadUrls = useRef<string[]>([]);
  const zh = language === 'zh' || (!language && typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh'));

  useEffect(() => () => {
    preparedDownloadUrls.current.splice(0).forEach((href) => URL.revokeObjectURL(href));
  }, []);

  const clearPreparedDownloads = useCallback((delayMs = 0) => {
    const hrefs = preparedDownloadUrls.current.splice(0);
    setPreparedDownloads(null);
    const revoke = () => hrefs.forEach((href) => URL.revokeObjectURL(href));
    if (delayMs > 0) window.setTimeout(revoke, delayMs);
    else revoke();
  }, []);

  const setPreparedExportData = useCallback(async (data: TableExportData | null, requestId: number) => {
    const normalized = data
      ? readExplicitTableData(data)
      : tableRef?.current
        ? readVisibleTableData(tableRef.current)
        : null;
    if (!normalized) throw new Error('Export table is unavailable.');
    const downloads = await createPreparedDownloads(normalized, filename);
    if (requestId !== exportDataRequestId.current) {
      URL.revokeObjectURL(downloads.xlsx.href);
      URL.revokeObjectURL(downloads.csv.href);
      return;
    }
    setPreparedData(normalized);
    setPreparedDownloads(downloads);
    preparedDownloadUrls.current.push(downloads.xlsx.href, downloads.csv.href);
  }, [filename, tableRef]);

  const prepareExportData = useCallback(() => {
    const requestId = ++exportDataRequestId.current;
    clearPreparedDownloads(1000);
    setPreparedData(null);
    setExportError('');
    setIsPreparingData(true);
    let request: Promise<TableExportData | null>;
    try {
      request = typeof exportData === 'function'
        ? Promise.resolve(exportData())
        : Promise.resolve(exportData ?? null);
    } catch (error) {
      request = Promise.reject(error);
    }
    void request.then(async (data) => {
      if (requestId !== exportDataRequestId.current) return;
      await setPreparedExportData(data ?? null, requestId);
    }).catch((error) => {
      if (requestId !== exportDataRequestId.current) return;
      setPreparedData(null);
      clearPreparedDownloads();
      const normalizedError = error instanceof Error ? error : new Error(String(error));
      setExportError(normalizedError.message);
      onExportError?.(normalizedError);
    }).finally(() => {
      if (requestId === exportDataRequestId.current) setIsPreparingData(false);
    });
  }, [clearPreparedDownloads, exportData, onExportError, setPreparedExportData]);

  useEffect(() => {
    const sourceChanged = lastExportDataSource.current !== exportData;
    lastExportDataSource.current = exportData;
    if (open && sourceChanged) prepareExportData();
  }, [exportData, open, prepareExportData]);

  const toggleMenu = () => {
    if (open) {
      exportDataRequestId.current += 1;
      setIsPreparingData(false);
      setPreparedData(null);
      clearPreparedDownloads(1000);
      setOpen(false);
      return;
    }
    setOpen(true);
    prepareExportData();
  };

  const scheduleDownloadCleanup = (href: string) => {
    window.setTimeout(() => {
      URL.revokeObjectURL(href);
      preparedDownloadUrls.current = preparedDownloadUrls.current.filter((item) => item !== href);
    }, 60_000);
  };

  return (
    <div className={`relative inline-flex ${className ?? ''}`} data-table-export-menu="true">
      <ActionIconButton
        icon={isPreparingData ? LoaderCircle : Download}
        iconClassName={isPreparingData ? 'animate-spin' : undefined}
        label={isPreparingData ? (zh ? '正在加载导出数据' : 'Loading export data') : (zh ? '导出表格' : 'Export table')}
        tooltip={isPreparingData ? (zh ? '正在加载导出数据' : 'Loading export data') : (zh ? '导出表格' : 'Export table')}
        size="md"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggleMenu}
      />
      {open && (
        <div role="menu" className="absolute right-0 top-full z-40 mt-1 min-w-48 rounded-lg border border-slate-200 bg-white p-1 shadow-xl dark:border-slate-700 dark:bg-slate-900">
          {isPreparingData && <p role="status" aria-live="polite" className="px-3 py-1.5 text-[11px] text-slate-500">{zh ? '正在加载导出数据…' : 'Preparing export data…'}</p>}
          {!isPreparingData && preparedData && (
            <p role="status" aria-live="polite" className="px-3 py-1.5 text-[11px] text-slate-500">
              {zh ? `已准备 ${preparedData.rows.length} 条记录，请选择格式下载。` : `${preparedData.rows.length} rows ready. Select a format to download.`}
            </p>
          )}
          {preparedDownloads ? (
            <>
              <a role="menuitem" href={preparedDownloads.xlsx.href} download={preparedDownloads.xlsx.filename} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800" onClick={() => scheduleDownloadCleanup(preparedDownloads.xlsx.href)}>
                <FileSpreadsheet size={15} aria-hidden="true" />{zh ? '导出 Excel (.xlsx)' : 'Export Excel (.xlsx)'}
              </a>
              <a role="menuitem" href={preparedDownloads.csv.href} download={preparedDownloads.csv.filename} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800" onClick={() => scheduleDownloadCleanup(preparedDownloads.csv.href)}>
                <FileText size={15} aria-hidden="true" />{zh ? '导出 CSV (.csv)' : 'Export CSV (.csv)'}
              </a>
            </>
          ) : (
            <>
              <button type="button" role="menuitem" disabled className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-slate-700 disabled:opacity-50 dark:text-slate-200" onClick={() => undefined}>
                <FileSpreadsheet size={15} aria-hidden="true" />{zh ? '导出 Excel (.xlsx)' : 'Export Excel (.xlsx)'}
              </button>
              <button type="button" role="menuitem" disabled className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-slate-700 disabled:opacity-50 dark:text-slate-200" onClick={() => undefined}>
                <FileText size={15} aria-hidden="true" />{zh ? '导出 CSV (.csv)' : 'Export CSV (.csv)'}
              </button>
            </>
          )}
          {exportError && <p role="alert" className="px-3 py-1.5 text-[11px] text-rose-600 dark:text-rose-400">{exportError}</p>}
          {exportError && !preparedDownloads && !isPreparingData && (
            <button type="button" className="w-full rounded-md px-3 py-1.5 text-left text-[11px] font-medium text-cyan-700 hover:bg-cyan-50 dark:text-cyan-300 dark:hover:bg-cyan-950/40" onClick={prepareExportData}>
              {zh ? '重试加载导出数据' : 'Retry loading export data'}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default TableExportMenu;
