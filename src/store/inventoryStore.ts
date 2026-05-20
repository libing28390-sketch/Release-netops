import { create } from 'zustand';
import type { Device } from '../types';

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
  inventoryLoading: boolean;
  inventoryRefreshTick: number;
  assetsTotal: number;

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
  setInventorySortConfig: (config: { key: keyof Device; direction: 'asc' | 'desc' } | null) => void;
  setSelectedDeviceIds: (ids: string[] | ((prev: string[]) => string[])) => void;
  setInventoryRefreshTick: (tick: number | ((prev: number) => number)) => void;
  setAssetsTotal: (total: number) => void;
  setDeviceToDelete: (id: string | null) => void;
  setIsDeletingSelected: (v: boolean) => void;
  setShowDeleteModal: (v: boolean) => void;

  // Fetch logic
  fetchInventory: (normalizeDeviceRecord: (record: any) => Device) => Promise<void>;
  fetchAssetsTotal: () => Promise<void>;
}

export const useInventoryStore = create<InventoryState>((set, get) => ({
  inventoryPage: 1,
  inventoryPageSize: 15,
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
  inventoryLoading: false,
  inventoryRefreshTick: 0,
  assetsTotal: 0,
  deviceToDelete: null,
  isDeletingSelected: false,
  showDeleteModal: false,
  
  setInventoryPage: (page) => set({ inventoryPage: page }),
  setInventoryPageSize: (size) => set({ inventoryPageSize: size, inventoryPage: 1 }),
  setInventorySearch: (search) => set({ inventorySearch: search, inventoryPage: 1 }),
  setInventoryPlatformFilter: (filter) => set({ inventoryPlatformFilter: filter, inventoryPage: 1 }),
  setInventoryRoleFilter: (filter) => set({ inventoryRoleFilter: filter, inventoryPage: 1 }),
  setInventoryStatusFilter: (filter) => set({ inventoryStatusFilter: filter, inventoryPage: 1 }),
  setInventoryLifecycleFilter: (filter) => set({ inventoryLifecycleFilter: filter, inventoryPage: 1 }),
  setInventorySortConfig: (config) => set({ inventorySortConfig: config }),
  setSelectedDeviceIds: (ids) => set((state) => ({
    selectedDeviceIds: typeof ids === 'function' ? ids(state.selectedDeviceIds) : ids,
  })),
  setInventoryRefreshTick: (tick) => set((state) => ({
    inventoryRefreshTick: typeof tick === 'function' ? tick(state.inventoryRefreshTick) : tick,
  })),
  setAssetsTotal: (total) => set({ assetsTotal: total }),
  setDeviceToDelete: (id) => set({ deviceToDelete: id }),
  setIsDeletingSelected: (v) => set({ isDeletingSelected: v }),
  setShowDeleteModal: (v) => set({ showDeleteModal: v }),

  fetchInventory: async (normalizeDeviceRecord) => {
    const state = get();
    set({ inventoryLoading: true });
    try {
      const params = new URLSearchParams({
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

      const resp = await fetch(`/api/devices?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed to fetch inventory data');
      const data = await resp.json();

      if (Array.isArray(data)) {
        set({ 
          inventoryRows: data.map((item: any) => normalizeDeviceRecord(item)),
          inventoryTotal: data.length,
          inventoryStatusCounts: {},
          inventoryLoading: false
        });
      } else {
        set({
          inventoryRows: Array.isArray(data.items) ? data.items.map((item: any) => normalizeDeviceRecord(item)) : [],
          inventoryTotal: typeof data.total === 'number' ? data.total : 0,
          inventoryStatusCounts: data.status_counts && typeof data.status_counts === 'object' ? data.status_counts : {},
          inventoryLoading: false
        });
      }
    } catch {
      set({ inventoryRows: [], inventoryTotal: 0, inventoryStatusCounts: {}, inventoryLoading: false });
    }
  },

  fetchAssetsTotal: async () => {
    try {
      const resp = await fetch('/api/assets/summary');
      if (resp.ok) {
        const data = await resp.json();
        set({ assetsTotal: data.total || 0 });
      }
    } catch {
      // Ignore
    }
  }
}));
