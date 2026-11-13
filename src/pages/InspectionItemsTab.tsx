import { DataTable } from '../components/DataTable';
import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'motion/react';
import {
  Activity, Plus, X, Trash2, Pencil, Eye, Save, RotateCcw,
  Shield, CheckCircle2, Filter, Info, ListFilter, Copy, Check, Download, Database, FileCode,
  Terminal, Cpu
} from 'lucide-react';
import Pagination from '../components/Pagination';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import PageHero from '../components/PageHero';
import { fetchAllPaginatedItems } from '../utils/pagination';
import {
  alertPanelClass,
  alertSecondaryButtonClass,
  alertTableActionButtonClass,
} from './alertManagementShared';

import { TableActionCell, TableActionHeader } from '../components/ui/TableActionColumn';
import { ColumnSettingsButton, ListSearchInput, ListToolbar } from '../components/ui/TableListControls';
import { FormDialogShell } from '../components/ui/FormLayout';
import { loadVisibleColumnKeys, saveVisibleColumnKeys, type ColumnPreferenceDefinition } from '../components/ui/columnPreferences';
import { buildInspectionItemsExportData, filterInspectionItems, getFriendlyInspectionVendor } from './inspectionItemsExport';
import { useEscapeClose } from '../hooks/useEscapeClose';
interface InspectionItem {
  id: string;
  name: string;
  name_zh: string;
  category: string;
  check_key: string;
  description: string;
  method: string;
  command: string;
  vendor: string;
  oid: string;
  created_at: string;
  updated_at: string;
  script_id?: string | null;
  warning_threshold?: number | null;
  critical_threshold?: number | null;
  threshold_direction?: string;
  unit?: string | null;
  // ── 扩展字段（TextFSM 解析）──
  parse_type?: string;          // numeric | status | count | diff | info
  expected_value?: string | null;
  textfsm_template?: string;    // 模板文件名
  parse_field?: string;         // 提取的字段
  parse_filter?: string;        // 过滤条件（JSON）
  fallback_regex?: string;      // 正则兜底
  enabled?: number;             // 是否启用
}

interface InspectionItemFacets {
  all: number;
  categories: Record<string, number>;
  methods: Record<string, number>;
  vendors: Record<string, number>;
}

const PARSE_TYPE_OPTIONS = ['numeric', 'status', 'count', 'diff'] as const;

interface InspectionItemSignalContext {
  parse_type?: string;
  unit?: string | null;
  threshold_direction?: string;
  method?: string;
  check_key?: string;
  category?: string;
  expected_value?: string | null;
}

const isStatusInspectionItem = (item: InspectionItemSignalContext): boolean =>
  item.parse_type?.toLowerCase() === 'status';

const getInspectionThresholdUnit = (item: InspectionItemSignalContext, zh: boolean): string => {
  if (isStatusInspectionItem(item)) return zh ? '状态' : 'status';
  if (item.parse_type?.toLowerCase() === 'diff') return '%';
  const unit = item.unit?.trim();
  if (!unit) return zh ? '无单位' : 'unitless';
  if (unit.toLowerCase() === 'status') return zh ? '无单位' : 'unitless';
  if (unit.toLowerCase() === 'count') return zh ? '个' : 'count';
  return unit;
};

const formatInspectionThreshold = (
  item: InspectionItemSignalContext,
  value: number | null | undefined,
  zh: boolean,
  severity?: 'warning' | 'critical',
): string => {
  if (item.parse_type?.toLowerCase() === 'info') return zh ? '仅采集展示，不触发告警' : 'Collected for display only; no alert';
  if (value == null) return zh ? '未设置阈值' : 'Threshold not configured';
  if (isStatusInspectionItem(item)) return zh ? '按状态规则判定' : 'Evaluated by status rule';
  const unit = getInspectionThresholdUnit(item, zh);
  const valueWithUnit = unit === '%' || unit === '°C' ? `${value}${unit}` : `${value} ${unit}`;
  const condition = item.threshold_direction?.toLowerCase() === 'below'
    ? (zh ? `低于 ${valueWithUnit}` : `below ${valueWithUnit}`)
    : (zh ? `达到或超过 ${valueWithUnit}` : `at or above ${valueWithUnit}`);
  if (!severity) return condition;
  if (zh) return `${condition}时触发${severity === 'warning' ? '告警' : '严重告警'}`;
  return `${severity === 'warning' ? 'A warning' : 'A critical alert'} is triggered when the value is ${condition}`;
};

const getThresholdInputLabel = (item: InspectionItemSignalContext, zh: boolean): string => {
  const unit = getInspectionThresholdUnit(item, zh);
  if (isStatusInspectionItem(item)) return zh ? '状态规则' : 'Status rule';
  if (item.parse_type?.toLowerCase() === 'info') return zh ? '不适用' : 'Not applicable';
  const direction = item.threshold_direction?.toLowerCase() === 'below'
    ? (zh ? '低于' : 'below')
    : '≥';
  if (unit === (zh ? '无单位' : 'unitless')) return zh ? `无单位阈值（${direction}）` : `Unitless threshold (${direction})`;
  return zh ? `阈值（${direction} ${unit}）` : `Threshold (${direction} ${unit})`;
};

const getRoutingProtocolFromCheckKey = (checkKey?: string | null): 'bgp' | 'ospf' | null => {
  const tokens = String(checkKey || '').toLowerCase().split(/[^a-z0-9]+/);
  if (tokens.includes('bgp') && tokens.some(token => ['neighbor', 'peer', 'down', 'adjacency'].includes(token))) return 'bgp';
  if (tokens.includes('ospf') && tokens.some(token => ['neighbor', 'peer', 'down', 'adjacency'].includes(token))) return 'ospf';
  return null;
};

const getStatusThresholdExplanation = (
  item: InspectionItemSignalContext,
  severity: 'warning' | 'critical',
  zh: boolean,
): string => {
  const isSnmpComponent = item.method?.trim().toUpperCase() === 'SNMP'
    && /_(fan|psu)$/i.test(item.check_key || '');
  const isComplianceText = item.category?.toLowerCase() === 'compliance' && !isSnmpComponent;
  const expectedValue = item.expected_value?.trim();
  if (expectedValue) {
    if (severity === 'warning') {
      return isSnmpComponent
        ? (zh
          ? `期望状态“${expectedValue}”按精确值匹配；组件码：0=正常、1=告警、2=严重、3=未知`
          : `Expected state “${expectedValue}” uses exact matching; codes: 0=normal, 1=warning, 2=critical, 3=unknown`)
        : (zh
          ? `${isComplianceText ? `设备输出应包含“${expectedValue}”` : `状态值应与“${expectedValue}”完全一致`}；其他非空不匹配值触发告警，缺测/未知不视为正常`
          : `${isComplianceText ? `Device output should contain “${expectedValue}”` : `The state should exactly match “${expectedValue}”`}; other non-empty mismatches trigger a warning; missing/unknown is not healthy`);
    }
    return isSnmpComponent
      ? (zh
        ? '状态码 2（故障）或 fail/failed/failure 触发严重告警；0=正常、1=警告、3=未知，未知/缺测不参与判定'
        : 'State code 2 (failed) or fail/failed/failure triggers a critical alert; 0=normal, 1=warning, 3=unknown; unknown/missing is not evaluated')
      : (zh
        ? '普通状态不单独触发严重告警；状态不匹配按告警级处理，缺测/未知不参与严重级别判定'
        : 'Text states do not trigger a separate critical alert; mismatches remain warnings, and missing/unknown is not evaluated at critical level');
  }

  if (isSnmpComponent) {
    return severity === 'warning'
      ? (zh
        ? '组件状态码：0=正常，1=告警，2=严重，3=未知/未采集；未知状态按异常处理'
        : 'Component codes: 0=normal, 1=warning, 2=critical, 3=unknown/not collected; unfamiliar states are treated as abnormal')
      : (zh
        ? '状态码 2 或 fail/failed/failure 触发严重告警；1 或其他异常状态触发告警，3/缺测不参与判定'
        : 'Code 2 or fail/failed/failure triggers a critical alert; code 1 or other abnormal states trigger a warning, code 3/missing is not evaluated');
  }

  return severity === 'warning'
    ? (zh
      ? '以下值视为正常：normal、ok、up、true、1、running、operational、ready、active；其他非空异常状态触发告警，缺测/未知不视为正常'
      : 'Healthy values: normal, ok, up, true, 1, running, operational, ready, active; other non-empty abnormal states trigger a warning; missing/unknown is not healthy')
    : (zh
      ? '异常状态按告警级处理，不单独升级为严重告警'
      : 'Abnormal states trigger a warning; they are not escalated to a separate critical alert');
};

const getStatusExpectedValueHint = (item: InspectionItemSignalContext, zh: boolean): string => {
  const isSnmpComponent = item.method?.trim().toUpperCase() === 'SNMP'
    && /_(fan|psu)$/i.test(item.check_key || '');
  if (isSnmpComponent) {
    return zh
      ? '用于所有状态型指标。风扇/电源按组件状态精确匹配：0 正常、1 警告、2 失败、3 未知；失败仍为严重，未知/缺测不参与判定。'
      : 'Applies to all status metrics. Fan/PSU values use exact component-state matching: 0 ok, 1 warning, 2 failed, 3 unknown; failed remains critical and unknown/missing is not evaluated.';
  }
  return item.category?.toLowerCase() === 'compliance'
    ? (zh ? '普通文本状态按期望文本包含匹配；缺测/未知不参与判定。' : 'Text statuses use expected-text containment matching; missing/unknown is not evaluated.')
    : (zh ? '普通文本状态按精确匹配；不匹配时告警，缺测/未知不参与判定。' : 'Text statuses use exact matching; mismatches warn and missing/unknown is not evaluated.');
};


const VENDORS = [
  'Generic',
  // ── 主流厂商（友好名称 + 具体 platform code）──
  'Cisco', 'cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd',
  'Huawei', 'huawei_vrp', 'huawei_vrpv8', 'huawei_yunshan',
  'H3C', 'h3c_comware', 'h3c_comware_v3',
  'Juniper', 'juniper_junos',
  'Arista', 'arista_eos',
  'PaloAlto', 'paloalto_panos',
  'Fortinet',
  'Checkpoint', 'checkpoint_gaia',
  'Hillstone', 'hillstone_stoneos',
  'Ruijie', 'ruijie_os', 'ruijie_rgos', 'ZTE', 'zte_zxros', 'Maipu', 'maipu',
  // ── 其他 ──
  'Linux', 'Windows', 'VMware', 'Dell', 'HP', 'F5',
];
const CATEGORIES = [
  { id: 'Network', en: 'Network Device', zh: '网络设备' },
  { id: 'Server', en: 'Server / Host', zh: '服务器/主机' },
  { id: 'Connectivity', en: 'Connectivity', zh: '基础连通性' },
  { id: 'Interface', en: 'Interface', zh: '接口统计' },
  { id: 'Health', en: 'Health', zh: '业务健康度' },
  { id: 'Compliance', en: 'Compliance', zh: '合规性检查' }
];

const getFriendlyVendor = getFriendlyInspectionVendor;

const getInspectionMethodOptionValue = (method?: string): string => {
  const normalized = method?.trim().toUpperCase();
  if (normalized === 'SHELL') return 'Shell';
  if (normalized === 'AGENT') return 'Agent';
  return normalized || '';
};

type InspectionItemColumnKey =
  | 'nameZh' | 'name' | 'category' | 'vendor' | 'checkKey' | 'method' | 'parseType' | 'unit'
  | 'script' | 'oid' | 'description' | 'actions';

const INSPECTION_ITEM_COLUMN_STORAGE_KEY = 'netops:inspection-items:columns:v2';
const LEGACY_INSPECTION_ITEM_COLUMN_STORAGE_KEY = 'netops:inspection-items:columns:v1';
const LEGACY_DEFAULT_INSPECTION_ITEM_COLUMN_SETS: readonly (readonly string[])[] = [
  [
    'nameZh', 'name', 'category', 'vendor', 'checkKey', 'method', 'script', 'oid',
    'warningThreshold', 'criticalThreshold', 'description', 'actions',
  ],
  [
    'nameZh', 'name', 'category', 'vendor', 'checkKey', 'method', 'parseType', 'unit',
    'script', 'oid', 'warningThreshold', 'criticalThreshold', 'description', 'actions',
  ],
];

const loadInspectionItemColumnKeys = (
  definitions: readonly ColumnPreferenceDefinition<InspectionItemColumnKey>[],
): InspectionItemColumnKey[] => {
  const defaults = definitions
    .filter((column) => column.defaultVisible || column.required)
    .map((column) => column.key);
  if (typeof window === 'undefined') {
    return loadVisibleColumnKeys(INSPECTION_ITEM_COLUMN_STORAGE_KEY, definitions);
  }

  try {
    const storage = window.localStorage;
    if (storage.getItem(INSPECTION_ITEM_COLUMN_STORAGE_KEY) !== null) {
      return loadVisibleColumnKeys(INSPECTION_ITEM_COLUMN_STORAGE_KEY, definitions, storage);
    }

    const legacyValue = storage.getItem(LEGACY_INSPECTION_ITEM_COLUMN_STORAGE_KEY);
    if (legacyValue === null) return loadVisibleColumnKeys(INSPECTION_ITEM_COLUMN_STORAGE_KEY, definitions, storage);

    const legacyColumns = loadVisibleColumnKeys(LEGACY_INSPECTION_ITEM_COLUMN_STORAGE_KEY, definitions, storage);
    const wasLegacyDefault = LEGACY_DEFAULT_INSPECTION_ITEM_COLUMN_SETS.some((legacyDefaultColumns) => {
      const legacyDefaultSet = new Set(legacyDefaultColumns.filter(
        (key): key is InspectionItemColumnKey => definitions.some((column) => column.key === key),
      ));
      return legacyColumns.length === legacyDefaultSet.size
        && legacyColumns.every((key) => legacyDefaultSet.has(key));
    });
    return wasLegacyDefault ? defaults : legacyColumns;
  } catch {
    return loadVisibleColumnKeys(INSPECTION_ITEM_COLUMN_STORAGE_KEY, definitions);
  }
};

interface InspectionItemsTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

interface InspectionItemDetailsDialogProps {
  item: InspectionItem | null;
  language: string;
  scripts: Array<{ id: string; name?: string; content?: string }>;
  copiedId: string | null;
  onCopy: (text: string, id: string) => void;
  onClose: () => void;
  onEdit: (item: InspectionItem) => void;
}

const InspectionItemDetailsDialog: React.FC<InspectionItemDetailsDialogProps> = ({
  item,
  language,
  scripts,
  copiedId,
  onCopy,
  onClose,
  onEdit,
}) => {
  const zh = language === 'zh';
  const focusReturnRef = useRef<HTMLElement | null>(null);
  const isOpen = Boolean(item);
  useEscapeClose(isOpen, onClose);

  useEffect(() => {
    if (!isOpen) return;

    const activeElement = document.activeElement;
    focusReturnRef.current = activeElement instanceof HTMLElement && activeElement !== document.body
      ? activeElement
      : null;
    const focusFrame = window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('.inspection-item-detail-dialog button:not([disabled])')?.focus();
    });
    const trapTabNavigation = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const dialog = document.querySelector<HTMLElement>('.inspection-item-detail-dialog');
      if (!dialog) return;
      const focusableElements = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), a[href], select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };
    document.addEventListener('keydown', trapTabNavigation);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', trapTabNavigation);
      if (focusReturnRef.current?.isConnected) focusReturnRef.current.focus();
      focusReturnRef.current = null;
    };
  }, [isOpen]);

  if (!item) return null;

  const isStatusMetric = isStatusInspectionItem(item);
  const category = CATEGORIES.find(candidate => candidate.id.toLowerCase() === item.category?.toLowerCase());
  const script = item.script_id ? scripts.find(candidate => candidate.id === item.script_id) : undefined;
  const scriptName = script?.name?.replace(/（精细化）|\(精细化\)/g, '').trim();
  const sourceCode = item.script_id
    ? (script?.content || (zh ? '# 脚本内容加载中…' : '# Script content loading...'))
    : (item.command || (item.method?.toUpperCase() === 'SNMP'
      ? (zh ? '# SNMP 指标，无 CLI 指令' : '# SNMP-only metric — no CLI command')
      : (zh ? '# 未配置采集指令' : '# No command defined')));
  const warningRule = isStatusMetric
    ? getStatusThresholdExplanation(item, 'warning', zh)
    : formatInspectionThreshold(item, item.warning_threshold, zh, 'warning');
  const criticalRule = isStatusMetric
    ? getStatusThresholdExplanation(item, 'critical', zh)
    : formatInspectionThreshold(item, item.critical_threshold, zh, 'critical');
  const metadata = [
    { label: zh ? '分类' : 'Category', value: category ? (zh ? category.zh : category.en) : item.category || '—' },
    { label: zh ? '厂商 / 平台' : 'Vendor / Platform', value: getFriendlyVendor(item.vendor) || '—' },
    { label: zh ? '检查 Key' : 'Check Key', value: item.check_key || '—', mono: true },
    { label: zh ? '采集方式' : 'Method', value: item.method?.toUpperCase() || '—' },
    { label: zh ? '解析类型' : 'Parse type', value: item.parse_type || 'numeric' },
    { label: zh ? '单位' : 'Unit', value: getInspectionThresholdUnit(item, zh) },
    ...(scriptName ? [{ label: zh ? '绑定脚本' : 'Bound script', value: scriptName }] : []),
  ];
  const commandCopyKey = `${item.id}-cmd`;
  const oidCopyKey = `${item.id}-oid`;

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-3 backdrop-blur-[2px] sm:p-5"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}
    >
      <FormDialogShell
        title={item.name_zh || item.name || (zh ? '巡检指标详情' : 'Inspection metric details')}
        description={item.name_zh && item.name ? item.name : (zh ? '巡检指标详情' : 'Inspection metric details')}
        onClose={onClose}
        language={zh ? 'zh' : 'en'}
        widthClassName="max-w-4xl"
        className="inspection-item-detail-dialog w-full sm:max-h-[calc(100vh-2.5rem)]"
        bodyClassName="space-y-5"
        actions={(
          <div className="flex justify-end gap-2 px-5 py-3">
            <button type="button" onClick={onClose} className="inline-flex min-h-9 items-center rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-sm font-medium text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)]">
              {zh ? '关闭' : 'Close'}
            </button>
            <button type="button" onClick={() => onEdit(item)} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white hover:bg-blue-700">
              <Pencil size={14} />{zh ? '编辑指标' : 'Edit metric'}
            </button>
          </div>
        )}
      >
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {metadata.map(field => (
            <div key={field.label} className="min-w-0 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5">
              <p className="text-[11px] text-[var(--ui-fg-muted)]">{field.label}</p>
              <p className={`mt-1 break-words text-sm font-medium text-[var(--ui-fg)] ${'mono' in field && field.mono ? 'font-mono' : ''}`}>{field.value}</p>
            </div>
          ))}
          {item.expected_value && (
            <div className="min-w-0 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5">
              <p className="text-[11px] text-[var(--ui-fg-muted)]">{zh ? '期望状态值' : 'Expected state'}</p>
              <p className="mt-1 break-words text-sm font-medium text-[var(--ui-fg)]">{item.expected_value}</p>
            </div>
          )}
        </div>

        <section className="space-y-2.5">
          <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '告警与严重告警规则' : 'Warning and critical rules'}</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3.5 py-3 dark:border-amber-900/60 dark:bg-amber-950/20">
              <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">{zh ? '告警触发条件' : 'Warning condition'}</p>
              <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-[var(--ui-fg)]">{warningRule}</p>
            </div>
            <div className="rounded-lg border border-rose-200 bg-rose-50/50 px-3.5 py-3 dark:border-rose-900/50 dark:bg-rose-950/15">
              <p className="text-xs font-semibold text-rose-800 dark:text-rose-300">{zh ? '严重告警条件' : 'Critical condition'}</p>
              <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-[var(--ui-fg)]">{criticalRule}</p>
            </div>
          </div>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '指标说明' : 'Description'}</h3>
          <p className="whitespace-pre-wrap break-words rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3.5 py-3 text-sm leading-relaxed text-[var(--ui-fg)]">
            {item.description || (zh ? '暂无指标说明。' : 'No description provided.')}
          </p>
        </section>

        <section className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{item.script_id ? (zh ? '采集脚本' : 'Collection script') : (zh ? '采集指令' : 'Collection command')}</h3>
            <div className="flex items-center gap-2">
              {item.oid && (
                <button type="button" onClick={() => onCopy(item.oid, oidCopyKey)} className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs font-mono text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)]">
                  {copiedId === oidCopyKey ? <Check size={13} /> : <Copy size={13} />}
                  OID: {item.oid}
                </button>
              )}
              <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">{item.method?.toUpperCase() || '—'}</span>
            </div>
          </div>
          <div className="relative max-h-64 overflow-auto rounded-lg border border-slate-800 bg-[#00172d] p-3.5 pr-20">
            <code className="block whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-cyan-200">{sourceCode}</code>
            <button type="button" onClick={() => onCopy(sourceCode, commandCopyKey)} className="absolute right-2 top-2 inline-flex min-h-8 items-center gap-1.5 rounded-md border border-white/15 bg-white/10 px-2 text-xs text-white hover:bg-white/15">
              {copiedId === commandCopyKey ? <Check size={13} /> : <Copy size={13} />}
              {copiedId === commandCopyKey ? (zh ? '已复制' : 'Copied') : (zh ? '复制' : 'Copy')}
            </button>
          </div>
        </section>

        <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-[var(--ui-border)] pt-3 text-[11px] text-[var(--ui-fg-muted)]">
          <span>{zh ? '更新时间' : 'Updated'}：{item.updated_at || '—'}</span>
          <span className="font-mono">{zh ? '指标 ID' : 'Metric ID'}：{item.id}</span>
        </div>
      </FormDialogShell>
    </div>,
    document.body,
  );
};

const InspectionItemsTab: React.FC<InspectionItemsTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';

  const itemColumnDefinitions = useMemo<readonly ColumnPreferenceDefinition<InspectionItemColumnKey>[]>(() => [
    { key: 'nameZh', defaultVisible: true },
    { key: 'name', defaultVisible: false },
    { key: 'category', defaultVisible: true },
    { key: 'vendor', defaultVisible: true },
    { key: 'checkKey', defaultVisible: true },
    { key: 'method', defaultVisible: true },
    { key: 'parseType', defaultVisible: false },
    { key: 'unit', defaultVisible: false },
    { key: 'script', defaultVisible: false },
    { key: 'oid', defaultVisible: false },
    { key: 'description', defaultVisible: false },
    { key: 'actions', defaultVisible: true, required: true, isAction: true },
  ], []);
  const itemColumnOptions = useMemo(() => [
    { key: 'nameZh', label: zh ? '中文名称' : 'Chinese Name' },
    { key: 'name', label: zh ? '英文名称' : 'English Name' },
    { key: 'category', label: zh ? '分类' : 'Category' },
    { key: 'vendor', label: zh ? '厂商' : 'Vendor' },
    { key: 'checkKey', label: zh ? '检查 Key' : 'Check Key' },
    { key: 'method', label: zh ? '采集方式' : 'Method' },
    { key: 'parseType', label: zh ? '解析类型' : 'Parse type' },
    { key: 'unit', label: zh ? '单位' : 'Unit' },
    { key: 'script', label: zh ? '绑定脚本' : 'Bound Script' },
    { key: 'oid', label: 'OID' },
    { key: 'description', label: zh ? '描述' : 'Description' },
    { key: 'actions', label: zh ? '操作' : 'Actions', required: true, isAction: true },
  ], [zh]);

  const [items, setItems] = useState<InspectionItem[]>([]);
  const [facets, setFacets] = useState<InspectionItemFacets>({
    all: 0,
    categories: {},
    methods: {},
    vendors: {},
  });
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [loadError, setLoadError] = useState<'auth' | 'permission' | 'request' | ''>('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  
  const [form, setForm] = useState<Partial<InspectionItem>>({
    name: '', name_zh: '', category: 'Network', check_key: '', description: '',
    method: 'SNMP', command: '', vendor: '', oid: '', script_id: '',
    parse_type: 'numeric', unit: '', threshold_direction: 'above', expected_value: '',
    warning_threshold: undefined, critical_threshold: undefined
  });

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalItems, setTotalItems] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailItemId, setDetailItemId] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>('All');
  const [methodFilter, setMethodFilter] = useState<string>('All');
  const [vendorFilter, setVendorFilter] = useState<string>('All');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [scripts, setScripts] = useState<any[]>([]);
  const itemsRequestSequenceRef = useRef(0);
  const activeItemsRequestRef = useRef<AbortController | null>(null);
  const [visibleItemColumnKeys, setVisibleItemColumnKeys] = useState<InspectionItemColumnKey[]>(() =>
    loadInspectionItemColumnKeys(itemColumnDefinitions),
  );
  const visibleItemColumnSet = useMemo(() => new Set(visibleItemColumnKeys), [visibleItemColumnKeys]);

  const copyToClipboard = (text: string, id: string) => {
    try {
      // Primary method
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
      } else {
        // Fallback for non-HTTPS/older browsers
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
      showToast(zh ? '已成功复制到剪贴板' : 'Copied to clipboard successfully', 'success');
    } catch (err) {
      console.error('Failed to copy: ', err);
      showToast(zh ? '复制失败' : 'Failed to copy', 'error');
    }
  };


  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  const fetchItems = useCallback(async () => {
    activeItemsRequestRef.current?.abort();
    const controller = new AbortController();
    activeItemsRequestRef.current = controller;
    const requestSequence = ++itemsRequestSequenceRef.current;
    setLoading(true);
    setLoadError('');
    try {
      const params = new URLSearchParams({
        q: searchQuery.trim(),
        category: categoryFilter === 'All' ? '' : categoryFilter,
        method: methodFilter === 'All' ? '' : methodFilter,
        vendor: vendorFilter === 'All' ? '' : vendorFilter,
        page: String(currentPage),
        page_size: String(pageSize),
      });
      const r = await fetch(`/api/inspections/items/all?${params.toString()}`, { headers: authHeaders, signal: controller.signal });
      if (controller.signal.aborted || requestSequence !== itemsRequestSequenceRef.current) return;
      if (r.ok) {
        const j = await r.json();
        if (controller.signal.aborted || requestSequence !== itemsRequestSequenceRef.current) return;
        const data = j.data || {};
        if (Array.isArray(data)) {
          setItems(data);
          setTotalItems(data.length);
          setFacets({
            all: data.length,
            categories: data.reduce<Record<string, number>>((counts, item) => {
              counts[item.category] = (counts[item.category] || 0) + 1;
              return counts;
            }, {}),
            methods: data.reduce<Record<string, number>>((counts, item) => {
              const method = (item.method || '').toUpperCase();
              if (method) counts[method] = (counts[method] || 0) + 1;
              return counts;
            }, {}),
            vendors: data.reduce<Record<string, number>>((counts, item) => {
              const vendor = String(item.vendor || '').trim();
              if (vendor) counts[vendor] = (counts[vendor] || 0) + 1;
              return counts;
            }, {}),
          });
        } else {
          setItems(Array.isArray(data.items) ? data.items : []);
          setTotalItems(Number(data.total || 0));
          const nextFacets = data.facets || {};
          setFacets({
            all: Number(nextFacets.all || 0),
            categories: nextFacets.categories || {},
            methods: nextFacets.methods || {},
            vendors: nextFacets.vendors || {},
          });
        }
      } else {
        setItems([]);
        setTotalItems(0);
        setFacets({ all: 0, categories: {}, methods: {}, vendors: {} });
        setLoadError(r.status === 401 ? 'auth' : r.status === 403 ? 'permission' : 'request');
      }
    } catch {
      if (controller.signal.aborted || requestSequence !== itemsRequestSequenceRef.current) return;
      setItems([]);
      setTotalItems(0);
      setFacets({ all: 0, categories: {}, methods: {}, vendors: {} });
      setLoadError('request');
    } finally {
      if (requestSequence === itemsRequestSequenceRef.current) {
        setLoading(false);
        if (activeItemsRequestRef.current === controller) activeItemsRequestRef.current = null;
      }
    }
  }, [authHeaders, searchQuery, categoryFilter, methodFilter, vendorFilter, currentPage, pageSize]);

  const fetchScripts = useCallback(async () => {
    try {
      const r = await fetch('/api/scripts?page=1&page_size=100', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const data = j?.data || j;
        setScripts(Array.isArray(data) ? data : (data?.items || []));
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  useEffect(() => { 
    fetchItems();
    fetchScripts();
    return () => {
      itemsRequestSequenceRef.current += 1;
      activeItemsRequestRef.current?.abort();
      activeItemsRequestRef.current = null;
    };
  }, [fetchItems, fetchScripts]);

  useEffect(() => {
    saveVisibleColumnKeys(INSPECTION_ITEM_COLUMN_STORAGE_KEY, itemColumnDefinitions, visibleItemColumnKeys);
  }, [itemColumnDefinitions, visibleItemColumnKeys]);

  const handleAdd = async () => {
    if (!form.name || !form.name_zh || !form.check_key) {
      showToast(zh ? '请填写完整信息' : 'Please fill all fields', 'error');
      return;
    }
    try {
      const r = await fetch('/api/inspections/items', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(form)
      });
      if (r.ok) {
        showToast(zh ? '指标创建成功' : 'Item created', 'success');
        setShowAdd(false);
        setForm({ 
          name: '', name_zh: '', category: 'Network', check_key: '', 
          description: '', method: 'SNMP', command: '', vendor: '', oid: '',
          script_id: '', parse_type: 'numeric', unit: '', threshold_direction: 'above', expected_value: '',
          warning_threshold: undefined, critical_threshold: undefined
        });
        fetchItems();
      } else {
        showToast(r.status === 401
          ? (zh ? '登录状态已失效，请重新登录。' : 'Your session has expired. Please sign in again.')
          : r.status === 403
            ? (zh ? '你没有创建巡检指标的权限。' : 'You do not have permission to create inspection items.')
            : (zh ? '创建失败' : 'Failed to create'), 'error');
      }
    } catch {
      showToast(zh ? '创建失败' : 'Failed to create', 'error');
    }
  };

  const handleUpdate = async (id: string, updates: Partial<InspectionItem>) => {
    try {
      const r = await fetch(`/api/inspections/items/${id}`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify(updates)
      });
      if (r.ok) {
        showToast(zh ? '更新成功' : 'Updated', 'success');
        setEditingId(null);
        setExpandedId(null);
        fetchItems();
      } else {
        showToast(r.status === 401
          ? (zh ? '登录状态已失效，请重新登录。' : 'Your session has expired. Please sign in again.')
          : r.status === 403
            ? (zh ? '你没有编辑巡检指标的权限。' : 'You do not have permission to edit inspection items.')
            : (zh ? '更新失败' : 'Failed to update'), 'error');
      }
    } catch {
      showToast(zh ? '更新失败' : 'Failed to update', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(zh ? '确认删除该指标吗？' : 'Confirm delete?')) return;
    try {
      const r = await fetch(`/api/inspections/items/${id}`, {
        method: 'DELETE',
        headers: authHeaders
      });
      if (r.ok) {
        showToast(zh ? '指标已删除' : 'Deleted', 'success');
        fetchItems();
      } else {
        showToast(r.status === 401
          ? (zh ? '登录状态已失效，请重新登录。' : 'Your session has expired. Please sign in again.')
          : r.status === 403
            ? (zh ? '你没有删除巡检指标的权限。' : 'You do not have permission to delete inspection items.')
            : (zh ? '删除失败' : 'Failed to delete'), 'error');
      }
    } catch {
      showToast(zh ? '删除失败' : 'Failed to delete', 'error');
    }
  };

  const itemFilters = useMemo(() => ({
    category: categoryFilter,
    method: methodFilter,
    vendor: vendorFilter === 'All' ? 'All' : getFriendlyVendor(vendorFilter),
    search: searchQuery,
  }), [categoryFilter, methodFilter, vendorFilter, searchQuery]);
  const filteredItems = useMemo(() => filterInspectionItems(items, itemFilters), [items, itemFilters]);

  const exportData = useCallback(async () => {
    const params = new URLSearchParams({
      q: searchQuery.trim(),
      category: categoryFilter === 'All' ? '' : categoryFilter,
      method: methodFilter === 'All' ? '' : methodFilter,
      vendor: vendorFilter === 'All' ? '' : vendorFilter,
    });
    const allItems = await fetchAllPaginatedItems<InspectionItem>('/api/inspections/items/all', params, 100);
    const exportItems = filterInspectionItems(allItems, itemFilters);
    const exportData = buildInspectionItemsExportData(exportItems, scripts, language);
    return {
      ...exportData,
      rows: exportData.rows.map((row, index) => {
        const item = exportItems[index];
        if (!item) return row;
        const warning = isStatusInspectionItem(item)
          ? getStatusThresholdExplanation(item, 'warning', zh)
          : formatInspectionThreshold(item, item.warning_threshold, zh, 'warning');
        const critical = isStatusInspectionItem(item)
          ? getStatusThresholdExplanation(item, 'critical', zh)
          : formatInspectionThreshold(item, item.critical_threshold, zh, 'critical');
        return [...row.slice(0, 8), warning, critical, ...row.slice(10)];
      }),
    };
  }, [searchQuery, categoryFilter, methodFilter, vendorFilter, itemFilters, scripts, language, zh]);

  // Vendor facets use stored values for API filtering and friendly names for display.
  const availableVendors = useMemo(() => {
    return Object.entries(facets.vendors)
      .filter(([, count]) => Number(count) > 0)
      .map(([value]) => ({ value, label: getFriendlyVendor(value) }))
      .sort((left, right) => left.label.localeCompare(right.label) || left.value.localeCompare(right.value));
  }, [facets.vendors]);

  // 方法列表由后端 facet 提供，避免当前页没有某种方式时把它隐藏。
  const availableMethods = useMemo(() => {
    return Object.keys(facets.methods).filter(method => facets.methods[method] > 0).sort();
  }, [facets.methods]);

  // Counts come from server-side facets so they describe the full catalog,
  // rather than only the current paginated page.
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { All: facets.all };
    CATEGORIES.forEach(cat => {
      const match = Object.entries(facets.categories).find(([category]) => category.toLowerCase() === cat.id.toLowerCase());
      counts[cat.id] = Number(match?.[1] || 0);
    });
    return counts;
  }, [facets]);

  // Method facets ignore only the selected method while keeping the other
  // filters on the backend.
  const methodCounts = useMemo(() => facets.methods, [facets.methods]);
  const summaryCount = (value: number) => loading ? '…' : loadError ? '—' : value;
  const methodSummaryCounts = {
    snmp: Number(methodCounts.SNMP || 0),
    cliSsh: Number(methodCounts.CLI || 0) + Number(methodCounts.SSH || 0),
    shell: Number(methodCounts.SHELL || 0),
    other: Object.entries(methodCounts)
      .filter(([method]) => !['SNMP', 'CLI', 'SSH', 'SHELL'].includes(method.toUpperCase()))
      .reduce((total, [, count]) => total + Number(count || 0), 0),
  };
  const otherMethodDetails = Object.entries(methodCounts)
    .filter(([method, count]) => !['SNMP', 'CLI', 'SSH', 'SHELL'].includes(method.toUpperCase()) && Number(count) > 0)
    .map(([method, count]) => `${method} ${count}`)
    .join(' · ');

  // 切换 category 时重置 method/vendor，避免遗留无效过滤值
  useEffect(() => {
    setMethodFilter('All');
    setVendorFilter('All');
  }, [categoryFilter]);

  // The API already returns the current page. Keep only that bounded result
  // in the table instead of slicing a full inspection-item catalog locally.
  const paginatedItems = filteredItems;

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, categoryFilter, methodFilter, vendorFilter]);

  return (
    <div className="nx-page-shell flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={ListFilter}
        title={zh ? '巡检指标项管理' : 'Inspection Items Management'}
        subtitle={zh ? '定义与维护自动化巡检的核心监控指标' : 'Define and manage core metrics for automated inspection'}
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 space-y-4 min-h-0">
        {/* Compact summary strip */}
        <div className="grid flex-shrink-0 grid-cols-2 gap-x-6 gap-y-3 border-b border-slate-200/70 px-1 pb-3 md:grid-cols-3 xl:grid-cols-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <Activity size={16} className="shrink-0 text-blue-600" />
            <p className="truncate text-xs text-slate-500">{zh ? '当前结果总数' : 'Current result total'}</p>
            <span className="ml-auto text-base font-semibold tabular-nums text-slate-800">{summaryCount(totalItems)}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2.5">
            <Database size={16} className="shrink-0 text-blue-600" />
            <p className="truncate text-xs text-slate-500">{zh ? 'SNMP 指标' : 'SNMP metrics'}</p>
            <span className="ml-auto text-base font-semibold tabular-nums text-slate-800">{summaryCount(methodSummaryCounts.snmp)}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2.5">
            <Terminal size={16} className="shrink-0 text-blue-600" />
            <p className="truncate text-xs text-slate-500">{zh ? 'CLI / SSH 指标' : 'CLI / SSH metrics'}</p>
            <span className="ml-auto text-base font-semibold tabular-nums text-slate-800">{summaryCount(methodSummaryCounts.cliSsh)}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2.5">
            <FileCode size={16} className="shrink-0 text-blue-600" />
            <p className="truncate text-xs text-slate-500">{zh ? 'SHELL 指标' : 'SHELL metrics'}</p>
            <span className="ml-auto text-base font-semibold tabular-nums text-slate-800">{summaryCount(methodSummaryCounts.shell)}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2.5">
            <Activity size={16} className="shrink-0 text-blue-600" />
            <div className="min-w-0">
              <p className="truncate text-xs text-slate-500">{zh ? '其他采集方式' : 'Other methods'}</p>
              {otherMethodDetails && <p className="truncate text-[10px] text-slate-400" title={otherMethodDetails}>{otherMethodDetails}</p>}
            </div>
            <span className="ml-auto text-base font-semibold tabular-nums text-slate-800">{summaryCount(methodSummaryCounts.other)}</span>
          </div>
          <p className="col-span-full text-[10px] leading-relaxed text-slate-400">
            {zh
              ? '当前结果总数按全部筛选条件统计；采集方式数量来自服务端全量统计，保留关键词、分类和平台筛选，但不受当前采集方式筛选限制。'
              : 'Current results use all active filters. Method counts come from server-side facets, retain search, category, and platform filters, and ignore the selected method filter.'}
          </p>
        </div>
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Category filter tabs */}
        <div className="border-b border-slate-200/70 bg-white px-5 pt-2">
          <div className="flex items-center gap-1 overflow-x-auto no-scrollbar" role="tablist" aria-label={zh ? '指标分类' : 'Metric category'}>
            <button
              type="button"
              role="tab"
              aria-selected={categoryFilter === 'All'}
              onClick={() => setCategoryFilter('All')}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-xs transition-colors ${categoryFilter === 'All' ? 'border-blue-600 font-semibold text-blue-700' : 'border-transparent font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-800'}`}
            >
              {zh ? '全部指标' : 'All Metrics'}
              <span className={`ml-1.5 text-[10px] font-normal tabular-nums ${categoryFilter === 'All' ? 'text-blue-600' : 'text-slate-400'}`}>
                {categoryCounts['All']}
              </span>
            </button>
            {CATEGORIES.map(cat => {
              const isActive = categoryFilter === cat.id;
              return (
                <button
                  key={cat.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setCategoryFilter(cat.id)}
                  className={`whitespace-nowrap border-b-2 px-3 py-2 text-xs transition-colors ${isActive ? 'border-blue-600 font-semibold text-blue-700' : 'border-transparent font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-800'}`}
                >
                  {zh ? cat.zh : cat.en}
                  <span className={`ml-1.5 text-[10px] font-normal tabular-nums ${isActive ? 'text-blue-600' : 'text-slate-400'}`}>
                    {categoryCounts[cat.id] || 0}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Secondary filter row: Method chips + Vendor dropdown + active filter summary */}
        <div className="border-b border-slate-200/70 bg-white px-5 py-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <div className="mr-1 flex items-center gap-1.5">
              <Filter className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-xs font-medium text-slate-500">{zh ? '采集方式' : 'Method'}</span>
            </div>
            <button
              type="button"
              onClick={() => setMethodFilter('All')}
              className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${methodFilter === 'All' ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}`}
            >
              {zh ? '全部' : 'All'}
            </button>
            {availableMethods.map(m => {
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMethodFilter(methodFilter === m ? 'All' : m)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${methodFilter === m ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}`}
                >
                  {m}
                  <span className={`ml-1 text-[10px] font-normal tabular-nums ${methodFilter === m ? 'text-blue-600' : 'text-slate-400'}`}>{methodCounts[m] || 0}</span>
                </button>
              );
            })}

            <div className="ml-2 flex items-center gap-1.5">
              <span className="text-xs font-medium text-slate-500">{zh ? '适用平台' : 'Platform'}</span>
            </div>
            <select
              value={vendorFilter}
              aria-label={zh ? '适用平台' : 'Platform'}
              onChange={e => setVendorFilter(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 outline-none transition-colors focus:border-blue-500"
            >
              <option value="All">{zh ? '全部平台' : 'All Platforms'}</option>
              {availableVendors.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
            </select>

            {(searchQuery || categoryFilter !== 'All' || methodFilter !== 'All' || vendorFilter !== 'All') && (
              <button
                onClick={() => { setSearchQuery(''); setCategoryFilter('All'); setMethodFilter('All'); setVendorFilter('All'); }}
                className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-50 hover:text-blue-700"
                title={zh ? '清除全部筛选' : 'Clear all filters'}
              >
                <X className="w-3 h-3" />
                {zh ? '清除筛选' : 'Clear'}
                <span className="ml-1 text-[10px] tabular-nums text-slate-400">
                  {filteredItems.length}/{items.length}
                </span>
              </button>
            )}
          </div>
        </div>

        <ListToolbar
          className="shrink-0 border-b border-black/5 bg-white px-4 py-3"
          leadingAction={(
            <button
              type="button"
              onClick={() => setShowAdd(!showAdd)}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.98]"
            >
              <Plus className="h-4 w-4" />
              {zh ? '新建' : 'New'}
            </button>
          )}
        >
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <ListSearchInput
              language={language}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onClear={() => setSearchQuery('')}
              placeholder={zh ? '搜索指标...' : 'Search items...'}
              className="w-48 lg:w-64"
            />
            <ColumnSettingsButton
              columns={itemColumnOptions}
              visibleKeys={visibleItemColumnKeys}
              defaultVisibleKeys={itemColumnDefinitions.filter((column) => column.defaultVisible || column.required).map((column) => column.key)}
              onApply={(keys) => setVisibleItemColumnKeys(keys as InspectionItemColumnKey[])}
              language={language}
            />
          </div>
        </ListToolbar>

        <AnimatePresence>
          {showAdd && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden bg-black/5 border-b border-black/5">
              <div className="p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-bold text-blue-700 flex items-center gap-2">
                    <Plus className="w-4 h-4 text-blue-600" />
                    {zh ? '配置新指标' : 'Configure New Item'}
                  </h4>
                  <button onClick={() => setShowAdd(false)} className="p-1 rounded-lg text-black/30 hover:bg-black/10 transition-all">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '英文名称' : 'Name (EN)'}</label>
                    <input
                      type="text" value={form.name} aria-label={zh ? '英文名称' : 'Name (EN)'} onChange={e => setForm({ ...form, name: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '中文名称' : 'Name (ZH)'}</label>
                    <input
                      type="text" value={form.name_zh} aria-label={zh ? '中文名称' : 'Name (ZH)'} onChange={e => setForm({ ...form, name_zh: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '分类' : 'Category'}</label>
                    <select
                      value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      <option value="Network">{zh ? '网络设备' : 'Network Device'}</option>
                      <option value="Server">{zh ? '服务器/主机' : 'Server / Host'}</option>
                      <option value="Connectivity">{zh ? '基础连通性' : 'Connectivity'}</option>
                      <option value="Interface">{zh ? '接口统计' : 'Interface'}</option>
                      <option value="Health">{zh ? '业务健康度' : 'Health'}</option>
                      <option value="Compliance">{zh ? '合规性检查' : 'Compliance'}</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '检查 Key' : 'Check Key'}</label>
                    <input
                      type="text" value={form.check_key} aria-label={zh ? '检查 Key' : 'Check Key'} onChange={e => setForm({ ...form, check_key: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '采集方式' : 'Method'}</label>
                    <select
                      value={form.method} onChange={e => setForm({ ...form, method: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      <option value="CLI">CLI (网络设备)</option>
                      <option value="Shell">Shell (服务器)</option>
                      <option value="SNMP">SNMP</option>
                      <option value="SSH">SSH</option>
                      <option value="ICMP">ICMP</option>
                      <option value="TCP">TCP</option>
                      <option value="Agent">Agent</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '适用平台' : 'Platform'}</label>
                    <select
                      value={form.vendor} onChange={e => setForm({ ...form, vendor: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      <option value="">{zh ? '请选择适用平台' : 'Select Platform'}</option>
                      {VENDORS.map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '解析类型' : 'Parse type'}</label>
                    <select
                      value={form.parse_type || 'numeric'}
                      aria-label={zh ? '解析类型' : 'Parse type'}
                      onChange={e => {
                        const parseType = e.target.value;
                        setForm(current => ({
                          ...current,
                          parse_type: parseType,
                          unit: parseType === 'status' ? 'status' : current.unit === 'status' ? '' : current.unit,
                          warning_threshold: parseType === 'status' || parseType === 'info' ? undefined : current.warning_threshold,
                          critical_threshold: parseType === 'status' || parseType === 'info' ? undefined : current.critical_threshold,
                        }));
                      }}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      {PARSE_TYPE_OPTIONS.map(parseType => <option key={parseType} value={parseType}>{parseType}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '单位' : 'Unit'}</label>
                    <input
                      type="text"
                      value={form.parse_type === 'status' ? 'status' : form.unit === 'status' ? '' : form.unit || ''}
                      aria-label={zh ? '单位' : 'Unit'}
                      disabled={form.parse_type === 'status'}
                      onChange={e => setForm(current => ({ ...current, unit: e.target.value }))}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm disabled:bg-slate-100 disabled:text-slate-500"
                      placeholder={zh ? '可填写任意单位，如 %、°C、个连接' : 'Any unit, e.g. %, °C, connections'}
                    />
                  </div>
                  {form.parse_type !== 'status' && form.parse_type !== 'info' && (
                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '阈值方向' : 'Threshold direction'}</label>
                      <select
                        aria-label={zh ? '阈值方向' : 'Threshold direction'}
                        value={form.threshold_direction || 'above'}
                        onChange={e => setForm(current => ({ ...current, threshold_direction: e.target.value }))}
                        className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                      >
                        <option value="above">{zh ? '达到或超过（≥）' : 'At or above (≥)'}</option>
                        <option value="below">{zh ? '低于（<）' : 'Below (<)'}</option>
                      </select>
                    </div>
                  )}
                  {form.method === 'SNMP' && (
                    getRoutingProtocolFromCheckKey(form.check_key) ? (
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? 'SNMP 邻居表' : 'SNMP neighbor table'}</label>
                        <div className="rounded-xl border border-cyan-100 bg-cyan-50/70 px-3.5 py-2 text-xs text-cyan-800">
                          {zh ? '按 BGP/OSPF 标准 MIB 自动采集，无需填写单个 OID' : 'Uses the BGP/OSPF standard MIB table; no scalar OID is needed'}
                        </div>
                      </div>
                    ) : (
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? 'OID' : 'OID'}</label>
                        <input
                          type="text" value={form.oid || ''} onChange={e => setForm({ ...form, oid: e.target.value })}
                          className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                          placeholder={zh ? "请输入 OID" : "1.3.6.1..."}
                        />
                      </div>
                    )
                  )}
                  {isStatusInspectionItem(form) ? (
                    <>
                      <div className="rounded-xl border border-amber-200 bg-amber-50/70 px-3.5 py-3 text-xs text-amber-900">
                        <p className="font-semibold">{zh ? '状态判定' : 'Status evaluation'}</p>
                        <p className="mt-1 leading-relaxed">{getStatusThresholdExplanation(form, 'warning', zh)}</p>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-xs text-slate-700">
                        <p className="font-semibold">{zh ? '异常等级' : 'Severity'}</p>
                        <p className="mt-1 leading-relaxed">{getStatusThresholdExplanation(form, 'critical', zh)}</p>
                      </div>
                      <div className="lg:col-span-2">
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '期望状态值（可选）' : 'Expected status value (optional)'}</label>
                        <input
                          type="text"
                          aria-label={zh ? '期望状态值' : 'Expected status value'}
                          value={form.expected_value || ''}
                          onChange={e => setForm({ ...form, expected_value: e.target.value })}
                          className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                          placeholder={zh ? '例如 ok、up、running 或设备状态文本' : 'For example: ok, up, running, or a device status string'}
                        />
                        <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{getStatusExpectedValueHint(form, zh)}</p>
                      </div>
                    </>
                  ) : form.parse_type === 'info' ? (
                    <div className="lg:col-span-2 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-xs text-slate-600">
                      {zh ? '此类指标仅采集和展示，不会触发阈值告警。' : 'This metric is collected for display only and does not trigger threshold alerts.'}
                    </div>
                  ) : (
                    <>
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? `警告${getThresholdInputLabel(form, zh)}` : `Warning ${getThresholdInputLabel(form, zh)}`}</label>
                        <input
                          type="number" value={form.warning_threshold ?? ''} onChange={e => setForm({ ...form, warning_threshold: e.target.value ? parseFloat(e.target.value) : undefined })}
                          className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                          placeholder="80"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? `严重${getThresholdInputLabel(form, zh)}` : `Critical ${getThresholdInputLabel(form, zh)}`}</label>
                        <input
                          type="number" value={form.critical_threshold ?? ''} onChange={e => setForm({ ...form, critical_threshold: e.target.value ? parseFloat(e.target.value) : undefined })}
                          className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                          placeholder="95"
                        />
                      </div>
                    </>
                  )}
                  <div className="lg:col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '采集指令' : 'Command'}</label>
                    <input
                      type="text" value={form.command} onChange={e => setForm({ ...form, command: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button onClick={() => setShowAdd(false)} className="px-4 py-2 text-xs font-semibold text-black/40 hover:text-black transition-colors">{zh ? '取消' : 'Cancel'}</button>
                  <button onClick={handleAdd} className="px-6 py-2 rounded-xl bg-blue-600 text-white text-xs font-bold shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all">{zh ? '保存' : 'Save'}</button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* View Content — List (Table) */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          {loading ? (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-black/20 italic h-64">
              <div className="flex flex-col items-center gap-2">
                <RotateCcw className="w-5 h-5 animate-spin" />
                <span>{zh ? '获取中...' : 'Loading...'}</span>
              </div>
            </div>
          ) : loadError ? (
            <div role="alert" className="flex h-64 flex-col items-center justify-center gap-3 p-12 text-center text-sm text-rose-700">
              <span>{loadError === 'auth'
                ? (zh ? '登录状态已失效，请重新登录。' : 'Your session has expired. Please sign in again.')
                : loadError === 'permission'
                  ? (zh ? '你没有查看巡检指标的权限。' : 'You do not have permission to view inspection items.')
                  : (zh ? '巡检指标加载失败，请重试。' : 'Failed to load inspection items. Please try again.')}</span>
              <button type="button" onClick={() => void fetchItems()} className="rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50">
                {zh ? '重试' : 'Retry'}
              </button>
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-black/20 italic h-64">
              {zh ? '暂无匹配的指标项' : 'No items found'}
            </div>
          ) : (
            <DataTable unstyled exportConfig={{ filename: 'inspection-items', disabled: Boolean(editingId), exportData }} className="nx-data-table text-left">
              <thead className="sticky top-0 z-10">
                <tr className="border-y border-black/5 bg-[#f8fafc] text-[10px] font-bold uppercase tracking-widest text-black/40">
                  <th hidden={!editingId && !visibleItemColumnSet.has('nameZh')} className="px-6 py-4">{zh ? '中文名称' : 'Chinese Name'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('name')} className="px-6 py-4">{zh ? '英文名称' : 'English Name'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('category')} className="px-6 py-4">{zh ? '分类' : 'Category'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('vendor')} className="px-6 py-4">{zh ? '厂商' : 'Vendor'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('checkKey')} className="px-6 py-4">{zh ? '检查 Key' : 'Check Key'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('method')} className="px-6 py-4">{zh ? '采集方式' : 'Method'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('parseType')} className="px-6 py-4">{zh ? '解析类型' : 'Parse type'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('unit')} className="px-6 py-4">{zh ? '单位' : 'Unit'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('script')} className="px-6 py-4">{zh ? '绑定脚本' : 'Bound Script'}</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('oid')} className="px-6 py-4">OID</th>
                  <th hidden={!editingId && !visibleItemColumnSet.has('description')} className="px-6 py-4">{zh ? '描述' : 'Description'}</th>
                  <TableActionHeader className="px-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.04]">
                {paginatedItems.map((item) => {
                  const isEditing = editingId === item.id;
                  const isExpanded = expandedId === item.id;
                  const isStatusMetric = isStatusInspectionItem(item);
                  const isInfoMetric = item.parse_type?.toLowerCase() === 'info';
                  const selectedFormCategory = CATEGORIES.find(category => category.id.toLowerCase() === String(form.category || '').trim().toLowerCase())?.id || form.category || '';
                  const selectedFormMethod = getInspectionMethodOptionValue(form.method);
                  const statusWarningExplanation = isStatusMetric ? getStatusThresholdExplanation(isEditing ? form : item, 'warning', zh) : '';
                  const statusCriticalExplanation = isStatusMetric ? getStatusThresholdExplanation(isEditing ? form : item, 'critical', zh) : '';
                  const boundScriptName = item.script_id
                    ? (scripts.find(s => s.id === item.script_id)?.name || '').replace(/（精细化）|\(精细化\)/g, '').trim()
                    : '';
                  return (
                    <React.Fragment key={item.id}>
                      <tr className={`hover:bg-black/[0.01] transition-colors group ${isExpanded ? 'bg-blue-50/30' : ''}`}>
                        <td hidden={!editingId && !visibleItemColumnSet.has('nameZh')} className="px-6 py-4">
                          {isEditing ? (
                            <input
                              type="text"
                              value={form.name_zh || ''}
                              onChange={e => setForm({ ...form, name_zh: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-blue-200 text-xs focus:outline-none"
                              placeholder="Name (ZH)"
                              onClick={e => e.stopPropagation()}
                            />
                          ) : <span className="font-bold text-blue-700">{item.name_zh || '—'}</span>}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('name')} className="px-6 py-4">
                          {isEditing ? (
                            <div onClick={e => e.stopPropagation()}>
                              <input
                                type="text"
                                value={form.name || ''}
                                onChange={e => setForm({ ...form, name: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-blue-100 text-xs text-[var(--ui-fg)] focus:outline-none"
                                placeholder="Name (EN)"
                              />
                            </div>
                          ) : <span className="text-xs text-[var(--ui-fg-muted)] font-mono">{item.name || '—'}</span>}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('category')} className="px-6 py-4">
                          {isEditing ? (
                            <div onClick={e => e.stopPropagation()}>
                              <select
                                value={selectedFormCategory}
                                onChange={e => setForm({ ...form, category: e.target.value })}
                                className="w-full px-2 py-1 rounded border border-blue-200 text-xs focus:outline-none bg-white"
                              >
                                <option value="Network">Network</option>
                                <option value="Server">Server</option>
                                <option value="Connectivity">Connectivity</option>
                                <option value="Interface">Interface</option>
                                <option value="Health">Health</option>
                                <option value="Compliance">Compliance</option>
                              </select>
                            </div>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[11px] font-bold uppercase bg-blue-50 text-blue-700 w-fit">
                              {zh ? (CATEGORIES.find(c => c.id === item.category)?.zh || item.category) : item.category || '—'}
                            </span>
                          )}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('vendor')} className="px-6 py-4">
                          {isEditing ? (
                            <select value={form.vendor || ''} onChange={e => setForm({ ...form, vendor: e.target.value })} onClick={e => e.stopPropagation()} className="w-full px-2 py-1 rounded border border-blue-100 text-xs text-[var(--ui-fg)] focus:outline-none bg-white">
                              <option value="">{zh ? '选择厂商' : 'Vendor'}</option>
                              {VENDORS.map(v => <option key={v} value={v}>{v}</option>)}
                            </select>
                          ) : <span className="text-xs text-[var(--ui-fg)] font-semibold">{item.vendor || '—'}</span>}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('checkKey')} className="px-6 py-4 font-mono text-[11px] text-black/50 tracking-tight">
                          {isEditing ? (
                            <input
                              type="text"
                              value={form.check_key || ''}
                              onChange={e => setForm({ ...form, check_key: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-blue-200 text-xs focus:outline-none"
                              onClick={e => e.stopPropagation()}
                            />
                          ) : item.check_key || '—'}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('method')} className="px-6 py-4">
                          {isEditing ? (
                            <select value={selectedFormMethod} onChange={e => setForm({ ...form, method: e.target.value })} onClick={e => e.stopPropagation()} className="w-full px-2 py-1 rounded border border-blue-200 text-xs text-[var(--ui-fg)] focus:outline-none bg-white">
                              <option value="SNMP">SNMP</option><option value="SSH">SSH</option><option value="CLI">CLI</option><option value="Shell">Shell</option><option value="ICMP">ICMP</option><option value="TCP">TCP</option><option value="Agent">Agent</option>
                            </select>
                          ) : <span className="text-xs font-bold uppercase text-[var(--ui-fg)]">{item.method?.toUpperCase() || '—'}</span>}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('parseType')} className="px-6 py-4">
                          {isEditing ? (
                            <select
                              value={form.parse_type || 'numeric'}
                              onChange={e => {
                                const parseType = e.target.value;
                                setForm(current => ({
                                  ...current,
                                  parse_type: parseType,
                                  unit: parseType === 'status' ? 'status' : current.unit === 'status' ? '' : current.unit,
                                  warning_threshold: parseType === 'status' ? undefined : current.warning_threshold,
                                  critical_threshold: parseType === 'status' ? undefined : current.critical_threshold,
                                }));
                              }}
                              onClick={e => e.stopPropagation()}
                              className="w-full px-2 py-1 rounded border border-blue-200 text-xs text-[var(--ui-fg)] focus:outline-none bg-white"
                            >
                              {PARSE_TYPE_OPTIONS.map(parseType => <option key={parseType} value={parseType}>{parseType}</option>)}
                            </select>
                          ) : <span className="text-xs font-medium text-[var(--ui-fg)]">{item.parse_type || 'numeric'}</span>}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('unit')} className="px-6 py-4">
                          {isEditing && form.parse_type !== 'status' ? (
                            <input
                              type="text"
                              value={form.unit === 'status' ? '' : form.unit || ''}
                              aria-label={zh ? '单位' : 'Unit'}
                              onChange={e => setForm(current => ({ ...current, unit: e.target.value }))}
                              onClick={e => e.stopPropagation()}
                              className="w-full px-2 py-1 rounded border border-blue-200 text-xs text-[var(--ui-fg)] focus:outline-none bg-white"
                              placeholder={zh ? '任意单位' : 'Any unit'}
                            />
                          ) : <span className="text-xs text-[var(--ui-fg-muted)]">{getInspectionThresholdUnit(item, zh)}</span>}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('script')} className="px-6 py-4 text-xs text-[var(--ui-fg-muted)]">{boundScriptName || '—'}</td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('oid')} className="px-6 py-4 font-mono text-xs text-[var(--ui-fg-muted)]">
                          {isEditing && form.method === 'SNMP' && getRoutingProtocolFromCheckKey(form.check_key) ? (
                            <span className="text-xs font-medium text-blue-700">{zh ? '标准邻居 MIB' : 'Standard neighbor MIB'}</span>
                          ) : isEditing && form.method === 'SNMP' ? (
                            <input type="text" value={form.oid || ''} onChange={e => setForm({ ...form, oid: e.target.value })} onClick={e => e.stopPropagation()} className="w-full px-2 py-1 rounded border border-blue-200 text-xs text-[var(--ui-fg)] focus:outline-none" placeholder="OID" />
                          ) : item.oid || '—'}
                        </td>
                        <td hidden={!editingId && !visibleItemColumnSet.has('description')} className="px-6 py-4 text-xs text-black/60 italic">
                          {isEditing ? (
                            <div className="space-y-2" onClick={e => e.stopPropagation()}>
                              <textarea
                                value={form.description || ''}
                                onChange={e => setForm({ ...form, description: e.target.value })}
                                className="w-full px-2 py-1 rounded border border-blue-200 text-xs text-[var(--ui-fg)] focus:outline-none"
                                rows={1}
                                placeholder={zh ? "指标描述" : "Description"}
                              />
                              <textarea
                                value={form.command || ''}
                                onChange={e => setForm({ ...form, command: e.target.value })}
                                className="w-full px-2 py-1 rounded border border-blue-200 text-xs text-[var(--ui-fg)] focus:outline-none font-mono"
                                rows={2}
                                placeholder={zh ? "采集指令" : "Command"}
                              />
                            </div>
                          ) : (
                            <div className="line-clamp-2 max-w-[320px] break-all text-xs text-[var(--ui-fg-muted)] font-medium leading-relaxed" title={item.description}>
                              {item.description || (zh ? "暂无指标业务描述" : "No description")}
                            </div>
                          )}
                        </td>
                        <TableActionCell className="px-6 py-4 text-right whitespace-nowrap">
                          <ActionIconGroup label={zh ? '指标操作' : 'Metric actions'}>
                            {isEditing ? (
                              <>
                                <ActionIconButton
                                  icon={Save}
                                  label={zh ? '保存' : 'Save'}
                                  variant="success"
                                  onClick={(e) => { e.stopPropagation(); handleUpdate(item.id, form); }}
                                />
                                <ActionIconButton
                                  icon={X}
                                  label={zh ? '取消' : 'Cancel'}
                                  onClick={(e) => { e.stopPropagation(); setEditingId(null); setExpandedId(null); }}
                                />
                              </>
                            ) : (
                              <>
                                <ActionIconButton
                                  icon={Eye}
                                  label={zh ? '查看指标详情' : 'View metric details'}
                                  onClick={(e) => { e.stopPropagation(); setDetailItemId(item.id); }}
                                />
                                <ActionIconButton
                                  icon={Pencil}
                                  label={zh ? '编辑指标' : 'Edit Metric'}
                                  onClick={(e) => { e.stopPropagation(); setExpandedId(item.id); setEditingId(item.id); setForm({ ...item, threshold_direction: item.threshold_direction || 'above' }); }}
                                />
                                <ActionIconButton
                                  icon={Trash2}
                                  label={zh ? '删除指标' : 'Delete Metric'}
                                  variant="danger"
                                  onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }}
                                />
                              </>
                            )}
                          </ActionIconGroup>
                        </TableActionCell>
                      </tr>
                      <AnimatePresence>
                        {isExpanded && (
                          <tr>
                            <td colSpan={visibleItemColumnKeys.length} className="px-6 py-0 border-none">
                              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                <div className="py-4 px-8 bg-black/[0.01] rounded-xl mb-4 mt-1 border border-black/[0.03] grid grid-cols-1 md:grid-cols-2 gap-8 relative">
                                  <div className="absolute top-4 left-4 w-1 h-12 bg-cyan-500/20 rounded-full" />
                                  <div className="space-y-4">
                                    <div>
                                      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-fg-muted)] mb-2">{zh ? '详细描述' : 'DETAILED DESCRIPTION'}</h4>
                                      <p className="whitespace-normal break-all text-sm text-[var(--ui-fg)] leading-relaxed font-medium">{item.description || '-'}</p>
                                    </div>
                                    <div>
                                      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-fg-muted)] mb-2">{zh ? '阈值与状态规则' : 'THRESHOLDS & STATUS RULES'}</h4>
                                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                        <div className="space-y-2">
                                          <p className="mb-1 text-[10px] font-semibold text-amber-700 dark:text-amber-300">{zh ? '告警规则' : 'Warning rule'}</p>
                                          {isStatusMetric ? (
                                            <>
                                              <p className="whitespace-normal break-words text-xs leading-relaxed text-[var(--ui-fg)]">{statusWarningExplanation}</p>
                                              {isEditing && (
                                                <label className="block space-y-1">
                                                  <span className="block text-[10px] font-semibold text-slate-500">{zh ? '期望状态值（可选）' : 'Expected status value (optional)'}</span>
                                                  <input
                                                    type="text"
                                                    aria-label={zh ? '期望状态值' : 'Expected status value'}
                                                    value={form.expected_value || ''}
                                                    onChange={e => setForm(current => ({ ...current, expected_value: e.target.value }))}
                                                    className="w-full rounded border border-blue-200 bg-white px-2 py-1.5 text-xs text-[var(--ui-fg)] focus:outline-none"
                                                    placeholder={zh ? '如 ok、up 或设备状态' : 'e.g. ok, up, or device state'}
                                                  />
                                                  <span className="block text-[10px] leading-relaxed text-slate-500">{getStatusExpectedValueHint(form, zh)}</span>
                                                </label>
                                              )}
                                            </>
                                          ) : isInfoMetric ? (
                                            <p className="whitespace-normal break-words text-xs leading-relaxed text-[var(--ui-fg)]">{formatInspectionThreshold(item, item.warning_threshold, zh, 'warning')}</p>
                                          ) : isEditing ? (
                                            <div className="space-y-2">
                                              <div className="flex items-center gap-2">
                                                <span className="text-[10px] font-semibold text-slate-500">{zh ? '告警阈值' : 'Warning threshold'}</span>
                                                <input
                                                  type="number"
                                                  aria-label={zh ? '告警阈值' : 'Warning threshold'}
                                                  value={form.warning_threshold ?? ''}
                                                  onChange={e => setForm(current => ({ ...current, warning_threshold: e.target.value ? parseFloat(e.target.value) : undefined }))}
                                                  className="w-28 rounded border border-blue-200 bg-white px-2 py-1.5 text-xs text-[var(--ui-fg)] focus:outline-none"
                                                  placeholder={zh ? '未设置' : 'Not set'}
                                                />
                                                <span className="shrink-0 text-[10px] text-slate-500">{getInspectionThresholdUnit(form, zh)}</span>
                                              </div>
                                              <label className="flex items-center gap-2 text-[10px] text-slate-500">
                                                <span>{zh ? '比较方式' : 'Comparison'}</span>
                                                <select
                                                  aria-label={zh ? '阈值比较方式' : 'Threshold comparison'}
                                                  value={form.threshold_direction || 'above'}
                                                  onChange={e => setForm(current => ({ ...current, threshold_direction: e.target.value }))}
                                                  className="rounded border border-blue-200 bg-white px-2 py-1.5 text-xs text-[var(--ui-fg)] focus:outline-none"
                                                >
                                                  <option value="above">{zh ? '达到或超过（≥）' : 'At or above (≥)'}</option>
                                                  <option value="below">{zh ? '低于（<）' : 'Below (<)'}</option>
                                                </select>
                                              </label>
                                            </div>
                                          ) : (
                                            <p className="whitespace-normal break-words text-xs leading-relaxed text-[var(--ui-fg)]">{formatInspectionThreshold(item, item.warning_threshold, zh, 'warning')}</p>
                                          )}
                                        </div>
                                        <div className="space-y-2">
                                          <p className="mb-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300">{zh ? '严重规则' : 'Critical rule'}</p>
                                          {isStatusMetric ? (
                                            <p className="whitespace-normal break-words text-xs leading-relaxed text-[var(--ui-fg)]">{statusCriticalExplanation}</p>
                                          ) : isInfoMetric ? (
                                            <p className="whitespace-normal break-words text-xs leading-relaxed text-[var(--ui-fg)]">{formatInspectionThreshold(item, item.critical_threshold, zh, 'critical')}</p>
                                          ) : isEditing ? (
                                            <div className="flex items-center gap-2">
                                              <span className="text-[10px] font-semibold text-slate-500">{zh ? '严重阈值' : 'Critical threshold'}</span>
                                              <input
                                                type="number"
                                                aria-label={zh ? '严重阈值' : 'Critical threshold'}
                                                value={form.critical_threshold ?? ''}
                                                onChange={e => setForm(current => ({ ...current, critical_threshold: e.target.value ? parseFloat(e.target.value) : undefined }))}
                                                className="w-28 rounded border border-blue-200 bg-white px-2 py-1.5 text-xs text-[var(--ui-fg)] focus:outline-none"
                                                placeholder={zh ? '未设置' : 'Not set'}
                                              />
                                              <span className="shrink-0 text-[10px] text-slate-500">{getInspectionThresholdUnit(form, zh)}</span>
                                            </div>
                                          ) : (
                                            <p className="whitespace-normal break-words text-xs leading-relaxed text-[var(--ui-fg)]">{formatInspectionThreshold(item, item.critical_threshold, zh, 'critical')}</p>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                    <div className="flex gap-8">
                                      <div>
                                        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-fg-muted)] mb-1.5">{zh ? '更新时间' : 'UPDATED AT'}</h4>
                                        <p className="text-xs font-mono text-[var(--ui-fg-muted)]">{item.updated_at}</p>
                                      </div>
                                      <div>
                                        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-fg-muted)] mb-1.5">{zh ? '指标 ID' : 'METRIC ID'}</h4>
                                        <p className="text-xs font-mono text-[var(--ui-fg-muted)] uppercase">{item.id}</p>
                                      </div>
                                    </div>
                                  </div>
                                  <div className="bg-white/40 backdrop-blur-sm p-5 rounded-2xl border border-black/[0.03] space-y-4 shadow-sm">
                                    <div className="flex items-center justify-between">
                                      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-fg-muted)]">
                                        {item.script_id ? (zh ? '自动化采集脚本源代码' : 'AUTOMATED SCRIPT SOURCE') : (zh ? '数据采集与指令' : 'ACQUISITION & COMMAND')}
                                      </h4>
                                      <div className="flex gap-2">
                                        {item.oid && (
                                          <ActionButton
                                            icon={copiedId === `${item.id}-oid` ? Check : Copy}
                                            variant={copiedId === `${item.id}-oid` ? 'success' : 'accent'}
                                            type="button"
                                            onClick={(e) => { e.stopPropagation(); copyToClipboard(item.oid, `${item.id}-oid`); }}
                                            title={zh ? '点击复制 OID' : 'Click to copy OID'}
                                          >
                                            {copiedId === `${item.id}-oid` ? (
                                              <span>{zh ? '已复制' : 'Copied'}</span>
                                            ) : (
                                              <span className="font-mono tracking-tight">OID: {item.oid}</span>
                                            )}
                                          </ActionButton>
                                        )}
                                        <span className="px-2.5 py-1 rounded-lg bg-cyan-600 text-white text-[11px] font-bold shadow-sm">{item.method}</span>
                                      </div>
                                    </div>
                                    <div className="bg-[#00172d] p-4 rounded-xl border border-white/5 relative overflow-hidden shadow-inner">
                                      <div className="absolute top-0 right-0 w-24 h-24 bg-cyan-500/5 rounded-full -translate-y-1/2 translate-x-1/2 blur-2xl" />
                                      {(() => {
                                        const codeText = item.script_id
                                          ? (scripts.find(s => s.id === item.script_id)?.content || '# Script content loading...')
                                          : (item.command || (item.method?.toUpperCase() === 'SNMP' ? '# SNMP-only metric — no CLI command' : '# No command defined'));
                                        const copyKey = `${item.id}-cmd`;
                                        const isCopied = copiedId === copyKey;
                                        return (
                                          <div className="relative">
                                            <code className="text-[11px] text-cyan-300 font-mono whitespace-pre-wrap break-all relative z-10 block pr-24 leading-relaxed">
                                              {codeText}
                                            </code>
                                            <ActionButton
                                              icon={isCopied ? Check : Copy}
                                              variant={isCopied ? 'success' : 'accent'}
                                              type="button"
                                              onClick={(e) => { e.stopPropagation(); copyToClipboard(codeText, copyKey); }}
                                              title={zh ? '复制代码' : 'Copy code'}
                                              className="absolute right-0 top-0 z-20"
                                            >
                                              {isCopied ? (
                                                <span>{zh ? '已复制' : 'Copied'}</span>
                                              ) : (
                                                <span>{zh ? '复制' : 'Copy'}</span>
                                              )}
                                            </ActionButton>
                                          </div>
                                        );
                                      })()}
                                    </div>
                                  </div>
                                </div>
                              </motion.div>
                            </td>
                          </tr>
                        )}
                      </AnimatePresence>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </DataTable>
          )}
        </div>

        {/* Pagination */}
        <Pagination
          currentPage={currentPage}
          totalItems={totalItems}
          itemsPerPage={pageSize}
          onPageChange={setCurrentPage}
          onItemsPerPageChange={(size) => { setPageSize(size); setCurrentPage(1); }}
          language={language}
          alwaysVisible
        />
      </div>
      <InspectionItemDetailsDialog
        item={detailItemId ? items.find(candidate => candidate.id === detailItemId) || null : null}
        language={language}
        scripts={scripts}
        copiedId={copiedId}
        onCopy={copyToClipboard}
        onClose={() => setDetailItemId(null)}
        onEdit={(item) => {
          setDetailItemId(null);
          setExpandedId(item.id);
          setEditingId(item.id);
          setForm({ ...item, threshold_direction: item.threshold_direction || 'above' });
        }}
      />
      </div>
    </div>
  );
};

export default InspectionItemsTab;
