import { create } from 'zustand';
import type { HostResourceSnapshot } from '../types';

interface MonitoringState {
  // Search
  monitorSearch: string;
  monitorSearchResults: any[];
  monitorSearching: boolean;

  // Selected device
  monitorSelectedDevice: any | null;

  // Data
  monitorOverview: any | null;
  monitorRealtime: any | null;
  monitorTrend: any | null;

  // Trend controls
  monitorTrendInterface: string;
  monitorTrendResolution: '1m' | '5m';
  monitorTrendStartInput: string;
  monitorTrendEndInput: string;
  monitorTrendRange: { start_time?: string; end_time?: string };
  monitorTrendZoom: { startIndex: number; endIndex: number } | null;
  monitorTrendDragStart: number | null;
  monitorTrendDragEnd: number | null;
  monitorTrendMetrics: string[];
  monitorTrendUiMode: 'pro' | 'compact';

  // Alerts
  monitorAlerts: any[];
  monitorAlertTotal: number;
  monitorAlertsPage: number;
  monitorAlertsPageSize: number;
  monitorAlertsSeverity: string;
  monitorAlertsPhase: string;

  // UI state
  monitorLoading: boolean;
  monitorPageVisible: boolean;
  monitorDashboardSiteFilter: string;
  monitorDashboardAlertFilter: 'all' | 'critical' | 'major' | 'warning';

  // Host resources
  hostResources: HostResourceSnapshot | null;

  // Actions
  setMonitorSearch: (v: string) => void;
  setMonitorSearchResults: (v: any[]) => void;
  setMonitorSearching: (v: boolean) => void;
  setMonitorSelectedDevice: (v: any | null) => void;
  setMonitorOverview: (v: any | null) => void;
  setMonitorRealtime: (v: any | null) => void;
  setMonitorTrend: (v: any | null) => void;
  setMonitorTrendInterface: (v: string) => void;
  setMonitorTrendResolution: (v: '1m' | '5m') => void;
  setMonitorTrendStartInput: (v: string) => void;
  setMonitorTrendEndInput: (v: string) => void;
  setMonitorTrendRange: (v: { start_time?: string; end_time?: string }) => void;
  setMonitorTrendZoom: (v: { startIndex: number; endIndex: number } | null) => void;
  setMonitorTrendDragStart: (v: number | null) => void;
  setMonitorTrendDragEnd: (v: number | null) => void;
  setMonitorTrendMetrics: (v: string[] | ((prev: string[]) => string[])) => void;
  setMonitorTrendUiMode: (v: 'pro' | 'compact') => void;
  setMonitorAlerts: (v: any[]) => void;
  setMonitorAlertTotal: (v: number) => void;
  setMonitorAlertsPage: (v: number) => void;
  setMonitorAlertsSeverity: (v: string) => void;
  setMonitorAlertsPhase: (v: string) => void;
  setMonitorLoading: (v: boolean) => void;
  setMonitorPageVisible: (v: boolean) => void;
  setMonitorDashboardSiteFilter: (v: string) => void;
  setMonitorDashboardAlertFilter: (v: 'all' | 'critical' | 'major' | 'warning') => void;
  setHostResources: (v: HostResourceSnapshot | null) => void;

  /** Reset all transient monitoring state (called when leaving the monitoring tab) */
  resetMonitoringState: () => void;
}

const getInitialTrendUiMode = (): 'pro' | 'compact' => {
  try {
    const saved = localStorage.getItem('netops_monitor_trend_ui_mode');
    return saved === 'pro' ? 'pro' : 'compact';
  } catch {
    return 'compact';
  }
};

export const useMonitoringStore = create<MonitoringState>((set, get) => ({
  monitorSearch: '',
  monitorSearchResults: [],
  monitorSearching: false,
  monitorSelectedDevice: null,
  monitorOverview: null,
  monitorRealtime: null,
  monitorTrend: null,
  monitorTrendInterface: '',
  monitorTrendResolution: '1m',
  monitorTrendStartInput: '',
  monitorTrendEndInput: '',
  monitorTrendRange: {},
  monitorTrendZoom: null,
  monitorTrendDragStart: null,
  monitorTrendDragEnd: null,
  monitorTrendMetrics: ['in_bps', 'out_bps'],
  monitorTrendUiMode: getInitialTrendUiMode(),
  monitorAlerts: [],
  monitorAlertTotal: 0,
  monitorAlertsPage: 1,
  monitorAlertsPageSize: 10,
  monitorAlertsSeverity: 'all',
  monitorAlertsPhase: 'all',
  monitorLoading: false,
  monitorPageVisible: typeof document === 'undefined' ? true : document.visibilityState === 'visible',
  monitorDashboardSiteFilter: 'all',
  monitorDashboardAlertFilter: 'all',
  hostResources: null,

  setMonitorSearch: (v) => set({ monitorSearch: v }),
  setMonitorSearchResults: (v) => set({ monitorSearchResults: v }),
  setMonitorSearching: (v) => set({ monitorSearching: v }),
  setMonitorSelectedDevice: (v) => set({ monitorSelectedDevice: v }),
  setMonitorOverview: (v) => set({ monitorOverview: v }),
  setMonitorRealtime: (v) => set({ monitorRealtime: v }),
  setMonitorTrend: (v) => set({ monitorTrend: v }),
  setMonitorTrendInterface: (v) => set({ monitorTrendInterface: v }),
  setMonitorTrendResolution: (v) => set({ monitorTrendResolution: v }),
  setMonitorTrendStartInput: (v) => set({ monitorTrendStartInput: v }),
  setMonitorTrendEndInput: (v) => set({ monitorTrendEndInput: v }),
  setMonitorTrendRange: (v) => set({ monitorTrendRange: v }),
  setMonitorTrendZoom: (v) => set({ monitorTrendZoom: v }),
  setMonitorTrendDragStart: (v) => set({ monitorTrendDragStart: v }),
  setMonitorTrendDragEnd: (v) => set({ monitorTrendDragEnd: v }),
  setMonitorTrendMetrics: (v) => set((state) => ({
    monitorTrendMetrics: typeof v === 'function' ? v(state.monitorTrendMetrics) : v,
  })),
  setMonitorTrendUiMode: (v) => {
    try { localStorage.setItem('netops_monitor_trend_ui_mode', v); } catch { /* ignore */ }
    set({ monitorTrendUiMode: v });
  },
  setMonitorAlerts: (v) => set({ monitorAlerts: v }),
  setMonitorAlertTotal: (v) => set({ monitorAlertTotal: v }),
  setMonitorAlertsPage: (v) => set({ monitorAlertsPage: v }),
  setMonitorAlertsSeverity: (v) => set({ monitorAlertsSeverity: v }),
  setMonitorAlertsPhase: (v) => set({ monitorAlertsPhase: v }),
  setMonitorLoading: (v) => set({ monitorLoading: v }),
  setMonitorPageVisible: (v) => set({ monitorPageVisible: v }),
  setMonitorDashboardSiteFilter: (v) => set({ monitorDashboardSiteFilter: v }),
  setMonitorDashboardAlertFilter: (v) => set({ monitorDashboardAlertFilter: v }),
  setHostResources: (v) => set({ hostResources: v }),

  resetMonitoringState: () => set({
    monitorSearch: '',
    monitorSearchResults: [],
    monitorSearching: false,
    monitorSelectedDevice: null,
    monitorOverview: null,
    monitorRealtime: null,
    monitorTrend: null,
    monitorTrendInterface: '',
    monitorTrendResolution: '1m',
    monitorTrendStartInput: '',
    monitorTrendEndInput: '',
    monitorTrendRange: {},
    monitorTrendZoom: null,
    monitorTrendDragStart: null,
    monitorTrendDragEnd: null,
    monitorTrendMetrics: ['in_bps', 'out_bps'],
    monitorAlerts: [],
    monitorAlertTotal: 0,
    monitorAlertsPage: 1,
    monitorAlertsSeverity: 'all',
    monitorAlertsPhase: 'all',
    monitorLoading: false,
    monitorDashboardSiteFilter: 'all',
    monitorDashboardAlertFilter: 'all',
  }),
}));
