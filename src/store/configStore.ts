import { create } from 'zustand';
import type { ConfigSnapshot, Device } from '../types';

type Updater<T> = T | ((prev: T) => T);

interface ConfigState {
  retentionDays: number;
  setRetentionDays: (val: Updater<number>) => void;
  retentionMaxPerDevice: number;
  setRetentionMaxPerDevice: (val: Updater<number>) => void;
  configSnapshots: ConfigSnapshot[];
  setConfigSnapshots: (val: Updater<ConfigSnapshot[]>) => void;
  configSnapshotsLoading: boolean;
  setConfigSnapshotsLoading: (val: Updater<boolean>) => void;
  configCenterDevice: Device | null;
  setConfigCenterDevice: (val: Updater<Device | null>) => void;
  configViewContent: string;
  setConfigViewContent: (val: Updater<string>) => void;
  configViewSnapshot: ConfigSnapshot | null;
  setConfigViewSnapshot: (val: Updater<ConfigSnapshot | null>) => void;
  configSnapshotKeyword: string;
  setConfigSnapshotKeyword: (val: Updater<string>) => void;
  configSearchQuery: string;
  setConfigSearchQuery: (val: Updater<string>) => void;
  configSearchResults: any[];
  setConfigSearchResults: (val: Updater<any[]>) => void;
  configSearchLoading: boolean;
  setConfigSearchLoading: (val: Updater<boolean>) => void;
  isTakingSnapshot: boolean;
  setIsTakingSnapshot: (val: Updater<boolean>) => void;
  activeBackupRunId: string | null;
  setActiveBackupRunId: (val: Updater<string | null>) => void;
  scheduleEnabled: boolean;
  setScheduleEnabled: (val: Updater<boolean>) => void;
  scheduleCron: string;
  setScheduleCron: (val: Updater<string>) => void;
  scheduleLoading: boolean;
  setScheduleLoading: (val: Updater<boolean>) => void;
}

export const useConfigStore = create<ConfigState>((set) => ({
  retentionDays: 365,
  setRetentionDays: (val) => set((state) => ({ retentionDays: typeof val === 'function' ? val(state.retentionDays) : val })),
  retentionMaxPerDevice: 30,
  setRetentionMaxPerDevice: (val) => set((state) => ({ retentionMaxPerDevice: typeof val === 'function' ? val(state.retentionMaxPerDevice) : val })),
  configSnapshots: [],
  setConfigSnapshots: (val) => set((state) => ({ configSnapshots: typeof val === 'function' ? val(state.configSnapshots) : val })),
  configSnapshotsLoading: false,
  setConfigSnapshotsLoading: (val) => set((state) => ({ configSnapshotsLoading: typeof val === 'function' ? val(state.configSnapshotsLoading) : val })),
  configCenterDevice: null,
  setConfigCenterDevice: (val) => set((state) => ({ configCenterDevice: typeof val === 'function' ? val(state.configCenterDevice) : val })),
  configViewContent: '',
  setConfigViewContent: (val) => set((state) => ({ configViewContent: typeof val === 'function' ? val(state.configViewContent) : val })),
  configViewSnapshot: null,
  setConfigViewSnapshot: (val) => set((state) => ({ configViewSnapshot: typeof val === 'function' ? val(state.configViewSnapshot) : val })),
  configSnapshotKeyword: '',
  setConfigSnapshotKeyword: (val) => set((state) => ({ configSnapshotKeyword: typeof val === 'function' ? val(state.configSnapshotKeyword) : val })),
  configSearchQuery: '',
  setConfigSearchQuery: (val) => set((state) => ({ configSearchQuery: typeof val === 'function' ? val(state.configSearchQuery) : val })),
  configSearchResults: [],
  setConfigSearchResults: (val) => set((state) => ({ configSearchResults: typeof val === 'function' ? val(state.configSearchResults) : val })),
  configSearchLoading: false,
  setConfigSearchLoading: (val) => set((state) => ({ configSearchLoading: typeof val === 'function' ? val(state.configSearchLoading) : val })),
  isTakingSnapshot: false,
  setIsTakingSnapshot: (val) => set((state) => ({ isTakingSnapshot: typeof val === 'function' ? val(state.isTakingSnapshot) : val })),
  activeBackupRunId: null,
  setActiveBackupRunId: (val) => set((state) => ({ activeBackupRunId: typeof val === 'function' ? val(state.activeBackupRunId) : val })),
  scheduleEnabled: true,
  setScheduleEnabled: (val) => set((state) => ({ scheduleEnabled: typeof val === 'function' ? val(state.scheduleEnabled) : val })),
  scheduleCron: '0 2 * * *',
  setScheduleCron: (val) => set((state) => ({ scheduleCron: typeof val === 'function' ? val(state.scheduleCron) : val })),
  scheduleLoading: false,
  setScheduleLoading: (val) => set((state) => ({ scheduleLoading: typeof val === 'function' ? val(state.scheduleLoading) : val })),
}));
