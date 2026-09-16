import type { Device } from '../../types';

export type WsMessage = {
  type?: string;
  total_devices?: number;
  dry_run?: boolean;
  hostname?: string;
  index?: number;
  total?: number;
  phase?: string;
  commands?: string[];
  output?: { output?: string };
  status?: string;
  device_id?: string;
  error?: string;
  summary?: { success?: number; total?: number; failed?: number };
};

export type PlaybookExecution = {
  id: string;
  _type?: 'job' | 'playbook';
  status?: string;
  scenario_name?: string;
  total_devices?: number;
  device_ids?: string;
  device_id?: string;
  created_at: string;
  success_count?: number;
  failed_count?: number;
  partial_count?: number;
  duration_ms?: number;
  dry_run?: boolean;
  task_name?: string;
  output?: string;
  author?: string;
  ip_address?: string;
};

export type ExecutionDevice = {
  device_id: string;
  hostname: string;
  ip_address?: string;
  status?: string;
  duration_ms?: number;
  error_message?: string;
};

export type ExecutionDeviceDetail = {
  hostname?: string;
  ip_address?: string;
  status?: string;
  duration_ms?: number;
  error_message?: string;
  phases_json?: string;
};

export interface AutomationHistoryTabProps {
  t: (key: string) => string;
  language: string;
  devices: Device[];
  playbookExecutions: PlaybookExecution[];
  playbookHistoryTotal: number;
  playbookHistoryPage: number;
  playbookHistoryStatusFilter: string;
  playbookHistoryScenarioSearch: string;
  activeExecutionId: string | null;
  executionStatus: string;
  wsMessages: WsMessage[];
  selectedExecutionLoading: boolean;
  selectedExecutionDetail: PlaybookExecution | null;
  selectedExecDevices: ExecutionDevice[];
  selectedExecDevicesTotal: number;
  selectedExecDevicesPage: number;
  selectedExecDevicesStatusFilter: string;
  selectedExecDevicesLoading: boolean;
  selectedDeviceDetail: ExecutionDeviceDetail | null;
  selectedDeviceDetailLoading: boolean;
  onRefreshHistory: (page?: number, statusFilter?: string, scenarioFilter?: string) => Promise<void> | void;
  onScenarioSearchChange: (value: string) => void;
  onHistoryPageChange: (page: number) => void;
  onHistoryStatusFilterChange: (value: string) => void;
  playbookHistoryPageSize?: number;
  onHistoryPageSizeChange?: (size: number) => void;
  onSelectExecution: (execution: PlaybookExecution) => Promise<void> | void;
  onDeleteExecution: (execution: PlaybookExecution) => Promise<void> | void;
  onExecDevicesStatusFilterChange: (value: string) => Promise<void> | void;
  onExecDevicesPageChange: (page: number) => Promise<void> | void;
  onSelectExecDevice: (deviceId: string) => Promise<void> | void;
  onCloseDeviceDetail: () => void;
  onRerun: (execution: PlaybookExecution) => void;
}
