import { create } from 'zustand';

type Updater<T> = T | ((prev: T) => T);

interface AutomationState {
  playbookHistoryPage: number;
  setPlaybookHistoryPage: (val: Updater<number>) => void;
  playbookHistoryTotal: number;
  setPlaybookHistoryTotal: (val: Updater<number>) => void;
  playbookHistoryStatusFilter: string;
  setPlaybookHistoryStatusFilter: (val: Updater<string>) => void;
  playbookHistoryScenarioSearch: string;
  setPlaybookHistoryScenarioSearch: (val: Updater<string>) => void;
  selectedExecDevices: any[];
  setSelectedExecDevices: (val: Updater<any[]>) => void;
  selectedExecDevicesTotal: number;
  setSelectedExecDevicesTotal: (val: Updater<number>) => void;
  selectedExecDevicesPage: number;
  setSelectedExecDevicesPage: (val: Updater<number>) => void;
  selectedExecDevicesStatusFilter: string;
  setSelectedExecDevicesStatusFilter: (val: Updater<string>) => void;
  selectedExecDevicesLoading: boolean;
  setSelectedExecDevicesLoading: (val: Updater<boolean>) => void;
  selectedExecutionDetail: any | null;
  setSelectedExecutionDetail: (val: Updater<any | null>) => void;
  selectedExecutionLoading: boolean;
  setSelectedExecutionLoading: (val: Updater<boolean>) => void;
  selectedDeviceDetail: any | null;
  setSelectedDeviceDetail: (val: Updater<any | null>) => void;
  selectedDeviceDetailLoading: boolean;
  setSelectedDeviceDetailLoading: (val: Updater<boolean>) => void;
  
  newScenarioForm: {
    name: string;
    name_zh: string;
    description: string;
    description_zh: string;
    category: string;
    icon: string;
    risk: string;
    platform: string;
    pre_check: string;
    execute: string;
    post_check: string;
    rollback: string;
  };
  setNewScenarioForm: (val: Updater<any>) => void;
  newScenarioVariables: any[];
  setNewScenarioVariables: (val: Updater<any[]>) => void;
  scenarioDraftOrigin: any;
  setScenarioDraftOrigin: (val: Updater<any>) => void;
  isSavingScenario: boolean;
  setIsSavingScenario: (val: Updater<boolean>) => void;
}

export const useAutomationStore = create<AutomationState>((set) => ({
  playbookHistoryPage: 1,
  setPlaybookHistoryPage: (val) => set((state) => ({ playbookHistoryPage: typeof val === 'function' ? val(state.playbookHistoryPage) : val })),
  playbookHistoryTotal: 0,
  setPlaybookHistoryTotal: (val) => set((state) => ({ playbookHistoryTotal: typeof val === 'function' ? val(state.playbookHistoryTotal) : val })),
  playbookHistoryStatusFilter: 'all',
  setPlaybookHistoryStatusFilter: (val) => set((state) => ({ playbookHistoryStatusFilter: typeof val === 'function' ? val(state.playbookHistoryStatusFilter) : val })),
  playbookHistoryScenarioSearch: '',
  setPlaybookHistoryScenarioSearch: (val) => set((state) => ({ playbookHistoryScenarioSearch: typeof val === 'function' ? val(state.playbookHistoryScenarioSearch) : val })),
  
  selectedExecDevices: [],
  setSelectedExecDevices: (val) => set((state) => ({ selectedExecDevices: typeof val === 'function' ? val(state.selectedExecDevices) : val })),
  selectedExecDevicesTotal: 0,
  setSelectedExecDevicesTotal: (val) => set((state) => ({ selectedExecDevicesTotal: typeof val === 'function' ? val(state.selectedExecDevicesTotal) : val })),
  selectedExecDevicesPage: 1,
  setSelectedExecDevicesPage: (val) => set((state) => ({ selectedExecDevicesPage: typeof val === 'function' ? val(state.selectedExecDevicesPage) : val })),
  selectedExecDevicesStatusFilter: 'all',
  setSelectedExecDevicesStatusFilter: (val) => set((state) => ({ selectedExecDevicesStatusFilter: typeof val === 'function' ? val(state.selectedExecDevicesStatusFilter) : val })),
  selectedExecDevicesLoading: false,
  setSelectedExecDevicesLoading: (val) => set((state) => ({ selectedExecDevicesLoading: typeof val === 'function' ? val(state.selectedExecDevicesLoading) : val })),
  
  selectedExecutionDetail: null,
  setSelectedExecutionDetail: (val) => set((state) => ({ selectedExecutionDetail: typeof val === 'function' ? val(state.selectedExecutionDetail) : val })),
  selectedExecutionLoading: false,
  setSelectedExecutionLoading: (val) => set((state) => ({ selectedExecutionLoading: typeof val === 'function' ? val(state.selectedExecutionLoading) : val })),
  
  selectedDeviceDetail: null,
  setSelectedDeviceDetail: (val) => set((state) => ({ selectedDeviceDetail: typeof val === 'function' ? val(state.selectedDeviceDetail) : val })),
  selectedDeviceDetailLoading: false,
  setSelectedDeviceDetailLoading: (val) => set((state) => ({ selectedDeviceDetailLoading: typeof val === 'function' ? val(state.selectedDeviceDetailLoading) : val })),

  newScenarioForm: {
    name: '',
    name_zh: '',
    description: '',
    description_zh: '',
    category: 'Custom',
    icon: '🧩',
    risk: 'medium',
    platform: 'cisco_ios',
    pre_check: '',
    execute: '',
    post_check: '',
    rollback: '',
  },
  setNewScenarioForm: (val) => set((state) => ({ newScenarioForm: typeof val === 'function' ? val(state.newScenarioForm) : val })),
  newScenarioVariables: [],
  setNewScenarioVariables: (val) => set((state) => ({ newScenarioVariables: typeof val === 'function' ? val(state.newScenarioVariables) : val })),
  scenarioDraftOrigin: { kind: 'manual', variableKeys: [] },
  setScenarioDraftOrigin: (val) => set((state) => ({ scenarioDraftOrigin: typeof val === 'function' ? val(state.scenarioDraftOrigin) : val })),
  isSavingScenario: false,
  setIsSavingScenario: (val) => set((state) => ({ isSavingScenario: typeof val === 'function' ? val(state.isSavingScenario) : val })),
}));
