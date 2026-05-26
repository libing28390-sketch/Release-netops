import type { Device } from '../../types';

export type StepId = 1 | 2 | 3 | 4;

export interface ScenarioVariable {
  key: string;
  label?: string;
  label_zh?: string;
  required?: boolean;
  type?: string;
  placeholder?: string;
  platform_hints?: Record<string, string>;
}

export interface AutomationScenario {
  id: string;
  icon?: string;
  risk: 'low' | 'medium' | 'high';
  name: string;
  name_zh?: string;
  description: string;
  description_zh?: string;
  supported_platforms?: string[];
  default_platform?: string;
  variables?: ScenarioVariable[];
  category?: string;
}

export interface QuickPlaybookPreview {
  pre_check?: string[];
  execute?: string[];
  post_check?: string[];
  rollback?: string[];
}

export interface QuickQueryTable {
  category: any;
  records: Record<string, any>[];
  columns: string[];
}

export interface DeviceExecutionPhase {
  success: boolean;
  output?: string;
}

export interface DeviceExecutionState {
  hostname: string;
  status: string;
  phases: Record<string, DeviceExecutionPhase>;
  error?: string;
}

export interface AutomationExecuteTabProps {
  t: (key: string) => string;
  language: string;
  sectionHeaderRowClass: string;
  devices: Device[];
  selectedDevice: Device | null;
  batchMode: boolean;
  batchDeviceIds: string[];
  automationSearch: string;
  scenarioSearch: string;
  changeTicket?: string;
  setChangeTicket?: (val: string) => void;
  savedQueries: any[];
  filteredScenarios: AutomationScenario[];
  quickPlaybookScenario: AutomationScenario | null;
  quickPlaybookVars: Record<string, string>;
  quickPlaybookPlatform: string;
  quickPlaybookDryRun: boolean;
  quickPlaybookConcurrency: number;
  quickPlaybookPreview: QuickPlaybookPreview | null;
  quickRiskConfirmed: boolean;
  hasQuickTargets: boolean;
  quickMissingRequiredFields: string[];
  quickHasMixedPlatforms: boolean;
  quickPlatformMismatch: boolean;
  isQuickPlaybookRunning: boolean;
  quickExecutionResult: any;
  executionStatus: string;
  wsCompleteMsg: any;
  deviceStatusMap: Record<string, DeviceExecutionState>;
  quickQueryRunning: boolean;
  quickQueryOutput: string;
  quickQueryLabel: string;
  quickQueryStructured: any;
  quickQueryView: 'terminal' | 'table';
  quickQueryMaximized: boolean;
  quickQueryCommands: string[];
  quickQueryTable: QuickQueryTable;
  onNavigate: (path: string) => void;
  onAutomationSearchChange: (value: string) => void;
  onScenarioSearchChange: (value: string) => void;
  onToggleBatchMode: () => void;
  onToggleBatchDevice: (deviceId: string) => void;
  onSelectDevice: (device: Device) => void;
  onOpenCustomCommandModal: () => void;
  onOpenScenario: (scenario: AutomationScenario) => void;
  onClearScenario: () => void;
  onQuickPlaybookVarChange: (key: string, value: string) => void;
  onQuickPlaybookConcurrencyChange: (value: number) => void;
  onQuickRiskConfirmedChange: (value: boolean) => void;
  onRunValidation: (changeTicket?: string) => void;
  onRunApply: (changeTicket?: string) => void;
  onRunQuickQuery: (label: string, commands: string, operationalCategory?: string, authRole?: string) => void;
  onResetQuickQuery: () => void;
  onQuickQueryViewChange: (view: 'terminal' | 'table') => void;
  onQuickQueryMaximizedChange: (value: boolean) => void;
  onOpenCommandPreview: () => void;
  onExportQuickQueryTable: (commands: string[]) => void;
  copyTextWithFallback: (text: string) => Promise<boolean>;
  showToast: (message: string, tone: 'success' | 'error' | 'warning' | 'info') => void;
  onResetExecutionState: () => void;
  getPlatformLabel: (platform: string) => string;
}
