import React, { createContext, useContext, ReactNode } from 'react';
import type { Device } from '../types';

interface AutomationContextValue {
  // automation domain
  scenarios: any[];
  platforms: Record<string, any>;
  selectedScenario: any;
  scenarioSearch: string;
  playbookVars: Record<string, string>;
  playbookPreview: any;
  playbookPlatform: string;
  playbookDeviceIds: string[];
  playbookConcurrency: number;
  playbookDryRun: boolean;
  executionStatus: string;
  quickPlaybookScenario: any;
  quickPlaybookVars: Record<string, string>;
  quickPlaybookPlatform: string;
  quickPlaybookDryRun: boolean;
  quickPlaybookConcurrency: number;
  quickPlaybookPreview: any;
  quickRiskConfirmed: boolean;
  filteredScenarios: any[];
  quickMissingRequiredFields: string[];
  quickHasMixedPlatforms: boolean;
  quickPlatformMismatch: boolean;
  isQuickPlaybookRunning: boolean;
  quickExecutionResult: any;
  wsCompleteMsg: string;
  deviceStatusMap: Record<string, any>;
  quickQueryRunning: boolean;
  quickQueryOutput: string;
  quickQueryLabel: string;
  quickQueryStructured: any;
  quickQueryView: 'terminal' | 'table';
  quickQueryMaximized: boolean;
  quickQueryCommands: string[];
  changeTicket: string;
  setChangeTicket: (ticket: string) => void;
  quickQueryTable: any;
  savedQueries: any[];
  handleAutomationSearch: (query: string) => void;
  handleScenarioSearch: (query: string) => void;
  handleToggleBatchMode: () => void;
  handleToggleBatchDevice: (deviceId: string) => void;
  handleSelectAutomationDevice: (device: Device) => void;
  handleClearSelection: () => void;
  batchMode: boolean;
  batchDeviceIds: string[];
  automationSearch: string;
  hasQuickTargets: boolean;
  openQuickPlaybookModal: (scenario: any) => void;
  handleClearQuickScenario: () => void;
  runQuickPlaybook: (dryRun?: boolean, changeTicket?: string) => Promise<void>;
  runQuickQuery: (label: string, commands: string, operationalCategory?: string, authRole?: string) => Promise<void>;
  handleResetQuickQuery: () => void;
  setQuickQueryView: (view: "table" | "terminal") => void;
  setQuickQueryMaximized: (maximized: boolean) => void;
  exportQuickQueryTable: (commands?: string[]) => void;
  copyTextWithFallback: (text: string) => Promise<boolean>;
  handleResetQuickExecutionState: () => void;
  handlePlaybookPlatformChange: (platform: string) => void;
  handlePlaybookVariableChange: (key: string, value: string) => void;
  handleSelectPlaybookScenario: (scenario: any) => void;
  openManualScenarioDraft: () => void;
  executePlaybook: (dryRunOverride?: boolean) => Promise<void>;
  setShowCustomCommandModal: (show: boolean) => void;
  setQuickPlaybookVars: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setQuickPlaybookConcurrency: (concurrency: number) => void;
  setQuickRiskConfirmed: (confirmed: boolean) => void;
  setShowCmdPreviewModal: (show: boolean) => void;
  handleTogglePlaybookDevice: (deviceId: string) => void;
  setPlaybookConcurrency: (concurrency: number) => void;
  previewPlaybook: (scenario: any, platform: string, variables: Record<string, string>) => Promise<void>;
  playbookExecutions: any[];
  playbookHistoryTotal: number;
  playbookHistoryPage: number;
  playbookHistoryStatusFilter: string;
  playbookHistoryScenarioSearch: string;
  activeExecutionId: string | null;
  wsMessages: any[];
  selectedExecutionLoading: boolean;
  selectedExecutionDetail: any;
  selectedDeviceDetail: any;
  selectedDeviceDetailLoading: boolean;
  selectedExecDevices: any[];
  selectedExecDevicesTotal: number;
  selectedExecDevicesPage: number;
  selectedExecDevicesStatusFilter: string;
  selectedExecDevicesLoading: boolean;
  handleRefreshHistory: () => Promise<void>;
  setPlaybookHistoryScenarioSearch: (search: string) => void;
  setPlaybookHistoryPage: (page: number) => void;
  setPlaybookHistoryStatusFilter: (filter: string) => void;
  handleSelectExecution: (execution: any) => Promise<void>;
  handleDeleteExecution: (executionId: string) => Promise<void>;
  handleExecDevicesStatusFilterChange: (filter: string) => void;
  handleExecDevicesPageChange: (page: number) => void;
  handleSelectExecDevice: (device: any) => void;
  findMatchingPlatform: (devicePlatform: string, platforms: string[] | Record<string, any>) => string | undefined;
  handleRerun: (execution: any) => Promise<void>;
  selectedJob: any;
  setSelectedJob: (job: any) => void;
  selectedDevice: any;
}

const AutomationContext = createContext<AutomationContextValue | null>(null);

export const useAutomationContext = () => {
  const context = useContext(AutomationContext);
  if (!context) {
    throw new Error('useAutomationContext must be used within AutomationProvider');
  }
  return context;
};

interface AutomationProviderProps {
  children: ReactNode;
  value: AutomationContextValue;
}

export const AutomationProvider: React.FC<AutomationProviderProps> = ({ children, value }) => (
  <AutomationContext.Provider value={value}>{children}</AutomationContext.Provider>
);