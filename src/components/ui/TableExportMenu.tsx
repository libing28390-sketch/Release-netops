import React, { useState } from 'react';
import { Download, FileSpreadsheet, FileText, LoaderCircle } from 'lucide-react';
import * as XLSX from 'xlsx';
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

function downloadCsv(contents: string, filename: string): void {
  const blob = new Blob([contents], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${filename}.csv`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportVisibleTable(table: HTMLTableElement, format: TableExportFormat, filename: string): void {
  exportTableData(readVisibleTableData(table), format, filename);
}

export function exportExplicitTable(data: TableExportData, format: TableExportFormat, filename: string): void {
  exportTableData(readExplicitTableData(data), format, filename);
}

function exportTableData(data: { headers: string[]; rows: ExportCell[][] }, format: TableExportFormat, filename: string): void {
  const { headers, rows } = data;
  if (!headers.length) throw new Error('The table has no exportable columns.');
  const normalizedFilename = safeFilename(filename);
  if (format === 'xlsx') {
    const worksheet = XLSX.utils.aoa_to_sheet([headers, ...rows]);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Data');
    XLSX.writeFile(workbook, `${normalizedFilename}.xlsx`);
    return;
  }
  downloadCsv(serializeTableCsv(headers, rows), normalizedFilename);
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
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const zh = language === 'zh' || (!language && typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh'));

  const runExport = async (format: TableExportFormat) => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      const explicitData = typeof exportData === 'function' ? await exportData() : exportData;
      const table = tableRef?.current;
      if (explicitData) exportExplicitTable(explicitData, format, filename);
      else if (table) exportVisibleTable(table, format, filename);
      else throw new Error('Export table is unavailable.');
      setExportError('');
      setOpen(false);
    } catch (error) {
      const normalizedError = error instanceof Error ? error : new Error(String(error));
      setExportError(normalizedError.message);
      onExportError?.(normalizedError);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className={`relative inline-flex ${className ?? ''}`} data-table-export-menu="true">
      <ActionIconButton
        icon={isExporting ? LoaderCircle : Download}
        iconClassName={isExporting ? 'animate-spin' : undefined}
        label={isExporting ? (zh ? '正在准备导出' : 'Preparing export') : (zh ? '导出表格' : 'Export table')}
        tooltip={isExporting ? (zh ? '正在准备导出' : 'Preparing export') : (zh ? '导出表格' : 'Export table')}
        size="md"
        disabled={disabled || isExporting}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open && (
        <div role="menu" className="absolute right-0 top-full z-40 mt-1 min-w-48 rounded-lg border border-slate-200 bg-white p-1 shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <button type="button" role="menuitem" disabled={isExporting} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:text-slate-200 dark:hover:bg-slate-800" onClick={() => void runExport('xlsx')}>
            <FileSpreadsheet size={15} aria-hidden="true" />{zh ? '导出 Excel (.xlsx)' : 'Export Excel (.xlsx)'}
          </button>
          <button type="button" role="menuitem" disabled={isExporting} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:text-slate-200 dark:hover:bg-slate-800" onClick={() => void runExport('csv')}>
            <FileText size={15} aria-hidden="true" />{zh ? '导出 CSV (.csv)' : 'Export CSV (.csv)'}
          </button>
          {exportError && <p role="alert" className="px-3 py-1.5 text-[11px] text-rose-600 dark:text-rose-400">{exportError}</p>}
        </div>
      )}
    </div>
  );
};

export default TableExportMenu;
