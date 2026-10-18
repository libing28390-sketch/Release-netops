import { create } from 'zustand';
import type { Device } from '../types';
import { displaySiteLabel } from '../utils/deviceUtils';
import { authHeaders } from '../api/http';
import {
  getManagedAssetDeviceOnlineTotal,
  getManagedAssetDeviceTotal,
  getManagedAssetPlatformCounts,
} from '../utils/assetSummary';

// ─── Inline normalizer (mirrors useInventory.normalizeDeviceRecord) ───────────
// Keeping this in the store means fetchInventory() needs no external argument,
// so InventoryDevicesTab can call it directly without prop-drilling.
const safeJsonArray = (value: any): any[] => {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
};

const normalizeDeviceRecord = (raw: any): Device => {
  const hostname =
    typeof raw?.hostname === 'string' && raw.hostname.trim()
      ? raw.hostname
      : typeof raw?.id === 'string'
        ? raw.id
        : 'Unknown';

  return {
    ...raw,
    id: String(raw?.id || ''),
    hostname,
    ip_address: typeof raw?.ip_address === 'string' ? raw.ip_address : '',
    platform: typeof raw?.platform === 'string' ? raw.platform : 'unknown',
    status:
      raw?.status === 'online' || raw?.status === 'offline' || raw?.status === 'pending'
        ? raw.status
        : 'offline',
    lifecycle_status:
      typeof raw?.lifecycle_status === 'string' && raw.lifecycle_status.trim()
        ? raw.lifecycle_status
        : 'staging',
    compliance:
      raw?.compliance === 'compliant' ||
      raw?.compliance === 'non-compliant' ||
      raw?.compliance === 'unknown'
        ? raw.compliance
        : 'unknown',
    role: typeof raw?.role === 'string' ? raw.role : '',
    site: displaySiteLabel(raw),
    model: typeof raw?.model === 'string' ? raw.model : '',
    version: typeof raw?.version === 'string' ? raw.version : '',
    sn: typeof raw?.sn === 'string' ? raw.sn : '',
    uptime: typeof raw?.uptime === 'string' ? raw.uptime : '',
    connection_method: raw?.connection_method === 'netconf' ? 'netconf' : 'ssh',
    config_history: safeJsonArray(raw?.config_history),
    interface_data: safeJsonArray(raw?.interface_data),
    cpu_history: safeJsonArray(raw?.cpu_history),
    memory_history: safeJsonArray(raw?.memory_history),
    health_status: ['healthy', 'warning', 'critical', 'unknown'].includes(
      String(raw?.health_status),
    )
      ? raw.health_status
      : 'unknown',
    health_score:
      typeof raw?.health_score === 'number'
        ? raw.health_score
        : Number(raw?.health_score || 0),
    health_summary:
      typeof raw?.health_summary === 'string' ? raw.health_summary : '',
    health_reasons: Array.isArray(raw?.health_reasons) ? raw.health_reasons : [],
    open_alert_count:
      typeof raw?.open_alert_count === 'number'
        ? raw.open_alert_count
        : Number(raw?.open_alert_count || 0),
    critical_open_alerts:
      typeof raw?.critical_open_alerts === 'number'
        ? raw.critical_open_alerts
        : Number(raw?.critical_open_alerts || 0),
    major_open_alerts:
      typeof raw?.major_open_alerts === 'number'
        ? raw.major_open_alerts
        : Number(raw?.major_open_alerts || 0),
    warning_open_alerts:
      typeof raw?.warning_open_alerts === 'number'
        ? raw.warning_open_alerts
        : Number(raw?.warning_open_alerts || 0),
    interface_down_count:
      typeof raw?.interface_down_count === 'number'
        ? raw.interface_down_count
        : Number(raw?.interface_down_count || 0),
    interface_flap_count:
      typeof raw?.interface_flap_count === 'number'
        ? raw.interface_flap_count
        : Number(raw?.interface_flap_count || 0),
    high_util_interface_count:
      typeof raw?.high_util_interface_count === 'number'
        ? raw.high_util_interface_count
        : Number(raw?.high_util_interface_count || 0),
    interface_error_count:
      typeof raw?.interface_error_count === 'number'
        ? raw.interface_error_count
        : Number(raw?.interface_error_count || 0),
  } as Device;
};

let latestInventoryRequestId = 0;
let latestAssetSummaryRequestId = 0;

// ─── Store ────────────────────────────────────────────────────────────────────

interface InventoryState {
  inventoryPage: number;
  inventoryPageSize: number;
  inventorySearch: string;
  inventoryPlatformFilter: string;
  inventoryRoleFilter: string;
  inventoryStatusFilter: string;
  inventoryLifecycleFilter: string;
  inventorySortConfig: { key: keyof Device; direction: 'asc' | 'desc' } | null;
  selectedDeviceIds: string[];

  // Data state
  inventoryRows: Device[];
  inventoryTotal: number;
  inventoryStatusCounts: Record<string, number>;
  inventoryHealthCounts: {
    healthy: number;
    warning: number;
    staging_maintenance: number;
  } | null;
  inventoryLoading: boolean;
  inventoryError: string | null;
  inventoryRefreshTick: number;
  assetsTotal: number | null;
  assetsOnlineTotal: number | null;
  assetsTotalError: string | null;
  assetsPlatformCounts: Record<string, number> | null;
  assetsPlatformError: string | null;

  // Delete modal state
  deviceToDelete: string | null;
  isDeletingSelected: boolean;
  showDeleteModal: boolean;

  // Actions
  setInventoryPage: (page: number) => void;
  setInventoryPageSize: (size: number) => void;
  setInventorySearch: (search: string) => void;
  setInventoryPlatformFilter: (filter: string) => void;
  setInventoryRoleFilter: (filter: string) => void;
  setInventoryStatusFilter: (filter: string) => void;
  setInventoryLifecycleFilter: (filter: string) => void;
  setInventorySortConfig: (
    config: { key: keyof Device; direction: 'asc' | 'desc' } | null,
  ) => void;
  setSelectedDeviceIds: (ids: string[] | ((prev: string[]) => string[])) => void;
  setInventoryRefreshTick: (tick: number | ((prev: number) => number)) => void;
  setAssetsTotal: (total: number) => void;
  resetAssetsTotal: () => void;
  setDeviceToDelete: (id: string | null) => void;
  setIsDeletingSelected: (v: boolean) => void;
  setShowDeleteModal: (v: boolean) => void;

  // Fetch logic — no external normalizer needed
  fetchInventory: () => Promise<void>;
  fetchAssetsTotal: (signal?: AbortSignal) => Promise<void>;
}

export const useInventoryStore = create<InventoryState>((set, get) => ({
  inventoryPage: 1,
  inventoryPageSize: 10,
  inventorySearch: '',
  inventoryPlatformFilter: 'all',
  inventoryRoleFilter: 'all',
  inventoryStatusFilter: 'all',
  inventoryLifecycleFilter: 'all',
  inventorySortConfig: null,
  selectedDeviceIds: [],

  inventoryRows: [],
  inventoryTotal: 0,
  inventoryStatusCounts: {},
  inventoryHealthCounts: null,
  inventoryLoading: false,
  inventoryError: null,
  inventoryRefreshTick: 0,
  assetsTotal: null,
  assetsOnlineTotal: null,
  assetsTotalError: null,
  assetsPlatformCounts: null,
  assetsPlatformError: null,
  deviceToDelete: null,
  isDeletingSelected: false,
  showDeleteModal: false,

  setInventoryPage: (page) => set({ inventoryPage: page }),
  setInventoryPageSize: (size) => set({ inventoryPageSize: size, inventoryPage: 1 }),
  setInventorySearch: (search) => set({ inventorySearch: search, inventoryPage: 1 }),
  setInventoryPlatformFilter: (filter) =>
    set({ inventoryPlatformFilter: filter, inventoryPage: 1 }),
  setInventoryRoleFilter: (filter) =>
    set({ inventoryRoleFilter: filter, inventoryPage: 1 }),
  setInventoryStatusFilter: (filter) =>
    set({ inventoryStatusFilter: filter, inventoryPage: 1 }),
  setInventoryLifecycleFilter: (filter) =>
    set({ inventoryLifecycleFilter: filter, inventoryPage: 1 }),
  setInventorySortConfig: (config) => set({ inventorySortConfig: config }),
  setSelectedDeviceIds: (ids) =>
    set((state) => ({
      selectedDeviceIds:
        typeof ids === 'function' ? ids(state.selectedDeviceIds) : ids,
    })),
  setInventoryRefreshTick: (tick) =>
    set((state) => ({
      inventoryRefreshTick:
        typeof tick === 'function' ? tick(state.inventoryRefreshTick) : tick,
    })),
  setAssetsTotal: (total) => {
    latestAssetSummaryRequestId += 1;
    set({
      assetsTotal: total,
      assetsOnlineTotal: null,
      assetsTotalError: null,
      assetsPlatformCounts: null,
      assetsPlatformError: null,
    });
  },
  resetAssetsTotal: () => {
    latestAssetSummaryRequestId += 1;
    set({
      assetsTotal: null,
      assetsOnlineTotal: null,
      assetsTotalError: null,
      assetsPlatformCounts: null,
      assetsPlatformError: null,
    });
  },
  setDeviceToDelete: (id) => set({ deviceToDelete: id }),
  setIsDeletingSelected: (v) => set({ isDeletingSelected: v }),
  setShowDeleteModal: (v) => set({ showDeleteModal: v }),

  fetchInventory: async () => {
    const state = get();
    const requestId = ++latestInventoryRequestId;
    set({ inventoryLoading: true, inventoryError: null });
    try {
      const params = new URLSearchParams({
        mode: 'light',
        search: state.inventorySearch,
        platform: state.inventoryPlatformFilter,
        role: state.inventoryRoleFilter,
        status: state.inventoryStatusFilter,
        page: String(state.inventoryPage),
        page_size: String(state.inventoryPageSize),
        sort_key: state.inventorySortConfig?.key || 'hostname',
        sort_direction: state.inventorySortConfig?.direction || 'asc',
        asset_type: 'network_device',
      });

      const resp = await fetch(`/api/devices?${params.toString()}`, { headers: authHeaders() });
      if (requestId !== latestInventoryRequestId) return;
      if (!resp.ok) {
        const errorBody = await resp.json().catch(() => null);
        const detail = typeof errorBody?.detail === 'string' ? errorBody.detail : '';
        throw new Error(detail || (resp.status === 401
          ? '登录已过期，请重新登录后重试'
          : resp.status === 403
            ? '当前账号无权查看网络设备'
            : `加载网络设备失败（${resp.status}）`));
      }
      const data = await resp.json();
      if (requestId !== latestInventoryRequestId) return;

      if (Array.isArray(data)) {
        set({
          inventoryRows: data.map(normalizeDeviceRecord),
          inventoryTotal: data.length,
          inventoryStatusCounts: {},
          inventoryHealthCounts: null,
          inventoryError: null,
          inventoryLoading: false,
        });
      } else {
        set({
          inventoryRows: Array.isArray(data.items)
            ? data.items.map(normalizeDeviceRecord)
            : [],
          inventoryTotal: typeof data.total === 'number' ? data.total : 0,
          inventoryStatusCounts:
            data.status_counts && typeof data.status_counts === 'object'
              ? data.status_counts
              : {},
          inventoryHealthCounts:
            data.health_counts &&
            typeof data.health_counts === 'object' &&
            Number.isFinite(Number(data.health_counts.healthy)) &&
            Number.isFinite(Number(data.health_counts.warning)) &&
            Number.isFinite(Number(data.health_counts.staging_maintenance))
              ? {
                  healthy: Math.max(0, Number(data.health_counts.healthy)),
                  warning: Math.max(0, Number(data.health_counts.warning)),
                  staging_maintenance: Math.max(0, Number(data.health_counts.staging_maintenance)),
                }
              : null,
          inventoryError: null,
          inventoryLoading: false,
        });
      }
    } catch (error) {
      if (requestId !== latestInventoryRequestId) return;
      set({
        inventoryRows: [],
        inventoryTotal: 0,
        inventoryStatusCounts: {},
        inventoryHealthCounts: null,
        inventoryError: error instanceof Error ? error.message : '加载网络设备失败',
        inventoryLoading: false,
      });
    }
  },

  fetchAssetsTotal: async (signal) => {
    const requestId = ++latestAssetSummaryRequestId;
    set({ assetsTotalError: null });
    try {
      const resp = await fetch('/api/assets/summary', { headers: authHeaders(), signal });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const summary = await resp.json();
      const assetsTotal = getManagedAssetDeviceTotal(summary);
      if (assetsTotal === null) throw new Error('Invalid asset summary response');
      const assetsOnlineTotal = getManagedAssetDeviceOnlineTotal(summary);
      const assetsPlatformCounts = getManagedAssetPlatformCounts(summary, assetsTotal);

      if (requestId === latestAssetSummaryRequestId) {
        set({
          assetsTotal,
          assetsOnlineTotal,
          assetsTotalError: null,
          assetsPlatformCounts,
          assetsPlatformError: assetsPlatformCounts === null
            ? 'Invalid asset platform summary response'
            : null,
        });
      }
    } catch {
      if (requestId === latestAssetSummaryRequestId && !signal?.aborted) {
        set({ assetsTotalError: 'Failed to load asset device total' });
      }
    }
  },
}));
