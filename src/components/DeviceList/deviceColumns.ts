export type ColumnKey =
  | 'hostname' | 'assetTag' | 'managementIp' | 'category' | 'role' | 'connectionMethod'
  | 'vendor' | 'model' | 'version' | 'adaptation'
  | 'site' | 'rack' | 'rackUnit' | 'tags' | 'status' | 'health' | 'lifecycle' | 'checkStatus' | 'checkTime' | 'cpu' | 'memory' | 'actions';

export type ColumnVisibility = Record<ColumnKey, boolean>;

export const COLUMN_VISIBILITY_STORAGE_KEY = 'netops:network-devices:columns:v2';

export const COLUMN_KEYS: readonly ColumnKey[] = [
  'hostname', 'assetTag', 'managementIp', 'category', 'role', 'connectionMethod',
  'vendor', 'model', 'version', 'adaptation', 'site', 'rack', 'rackUnit', 'tags',
  'status', 'health', 'lifecycle', 'checkStatus', 'checkTime', 'cpu', 'memory',
  'actions',
];

export const DEFAULT_COLUMNS: ColumnVisibility = {
  hostname: true,
  assetTag: true,
  managementIp: true,
  category: true,
  role: true,
  connectionMethod: false,
  vendor: true,
  model: true,
  version: false,
  adaptation: false,
  site: true,
  rack: true,
  rackUnit: true,
  tags: false,
  status: true,
  health: true,
  lifecycle: false,
  checkStatus: false,
  checkTime: false,
  cpu: false,
  memory: false,
  actions: true,
};

export function defaultColumnVisibility(): ColumnVisibility {
  return { ...DEFAULT_COLUMNS };
}

type ColumnStorage = Pick<Storage, 'getItem' | 'setItem'>;

function browserStorage(): ColumnStorage | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function normalizeColumnVisibility(value: unknown): ColumnVisibility {
  const saved = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const columns = Object.fromEntries(
    COLUMN_KEYS.map((key) => [
      key,
      key === 'actions'
        ? true
        : typeof saved[key] === 'boolean'
          ? saved[key]
          : DEFAULT_COLUMNS[key],
    ]),
  );
  return columns as ColumnVisibility;
}

export function loadColumnVisibility(storage = browserStorage()): ColumnVisibility {
  if (!storage) return defaultColumnVisibility();
  try {
    const saved = storage.getItem(COLUMN_VISIBILITY_STORAGE_KEY);
    return saved ? normalizeColumnVisibility(JSON.parse(saved)) : defaultColumnVisibility();
  } catch {
    return defaultColumnVisibility();
  }
}

export function saveColumnVisibility(
  columns: ColumnVisibility,
  storage = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(COLUMN_VISIBILITY_STORAGE_KEY, JSON.stringify(normalizeColumnVisibility(columns)));
  } catch {
    // Storage can be disabled by browser policy; the in-memory selection still works.
  }
}

export function setColumnVisibility(
  current: ColumnVisibility,
  key: ColumnKey,
  visible: boolean,
): ColumnVisibility {
  if (key === 'actions' && !visible) return current;
  if (!visible) {
    const visibleDataColumns = COLUMN_KEYS.filter((columnKey) => columnKey !== 'actions' && current[columnKey]);
    if (visibleDataColumns.length <= 1 && current[key]) return current;
  }
  return { ...current, [key]: visible, actions: true };
}

export function rackDisplayName(device: {
  rack_name?: string | null;
}): string {
  return device.rack_name?.trim() || '—';
}
