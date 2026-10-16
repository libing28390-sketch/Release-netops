export const ALERT_DESK_COLUMN_DEFS = [
  { key: 'title', zh: '告警标题', en: 'Alert title' },
  { key: 'message', zh: '告警信息', en: 'Alert message' },
  { key: 'metricType', zh: '指标类型', en: 'Metric type' },
  { key: 'occurrences', zh: '发生次数', en: 'Occurrences' },
  { key: 'hostname', zh: '主机名', en: 'Hostname' },
  { key: 'ipAddress', zh: 'IP 地址', en: 'IP address' },
  { key: 'interface', zh: '接口', en: 'Interface' },
  { key: 'site', zh: '站点', en: 'Site' },
  { key: 'severity', zh: '级别', en: 'Severity' },
  { key: 'workflow', zh: '状态', en: 'Status' },
  { key: 'assignee', zh: '责任人', en: 'Assignee' },
  { key: 'createdAt', zh: '发生时间', en: 'Created at' },
  { key: 'duration', zh: '持续时间', en: 'Duration' },
] as const;

export type AlertDeskColumnKey = (typeof ALERT_DESK_COLUMN_DEFS)[number]['key'];
export type AlertDeskColumnVisibility = Record<AlertDeskColumnKey, boolean>;

export const ALERT_DESK_COLUMN_STORAGE_KEY = 'netops:alerts:desk:columns:v1';

const DEFAULT_ALERT_DESK_COLUMNS: AlertDeskColumnVisibility = {
  title: true,
  message: true,
  metricType: false,
  occurrences: false,
  hostname: true,
  ipAddress: true,
  interface: false,
  site: false,
  severity: true,
  workflow: true,
  assignee: true,
  createdAt: true,
  duration: true,
};

type ColumnStorage = Pick<Storage, 'getItem' | 'setItem'>;

function browserStorage(): ColumnStorage | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function defaultAlertDeskColumnVisibility(): AlertDeskColumnVisibility {
  return { ...DEFAULT_ALERT_DESK_COLUMNS };
}

export function normalizeAlertDeskColumnVisibility(value: unknown): AlertDeskColumnVisibility {
  const saved = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return Object.fromEntries(ALERT_DESK_COLUMN_DEFS.map(({ key }) => [
    key,
    typeof saved[key] === 'boolean' ? saved[key] : DEFAULT_ALERT_DESK_COLUMNS[key],
  ])) as AlertDeskColumnVisibility;
}

export function loadAlertDeskColumnVisibility(storage = browserStorage()): AlertDeskColumnVisibility {
  if (!storage) return defaultAlertDeskColumnVisibility();
  try {
    const saved = storage.getItem(ALERT_DESK_COLUMN_STORAGE_KEY);
    return saved ? normalizeAlertDeskColumnVisibility(JSON.parse(saved)) : defaultAlertDeskColumnVisibility();
  } catch {
    return defaultAlertDeskColumnVisibility();
  }
}

export function saveAlertDeskColumnVisibility(
  columns: AlertDeskColumnVisibility,
  storage = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(ALERT_DESK_COLUMN_STORAGE_KEY, JSON.stringify(normalizeAlertDeskColumnVisibility(columns)));
  } catch {
    // Keep the in-memory selection when browser storage is unavailable.
  }
}

export function setAlertDeskColumnVisibility(
  current: AlertDeskColumnVisibility,
  key: AlertDeskColumnKey,
  visible: boolean,
): AlertDeskColumnVisibility {
  const visibleCount = ALERT_DESK_COLUMN_DEFS.filter((column) => current[column.key]).length;
  if (!visible && current[key] && visibleCount <= 1) return current;
  return { ...current, [key]: visible };
}
