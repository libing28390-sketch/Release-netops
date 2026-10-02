import type { TableExportData } from '../../components/ui/TableExportMenu';
import type { PlaybookExecution } from './types';

export function getAutomationHistoryStatusLabel(status: string | undefined, language: string): string {
  const zh = language === 'zh';
  const labels: Record<string, string> = {
    success: zh ? '执行成功' : 'Success',
    running: zh ? '执行中' : 'Running',
    pending: zh ? '排队中' : 'Pending',
    awaiting_approval: zh ? '待审批' : 'Awaiting approval',
    approval_rejected: zh ? '审批拒绝' : 'Approval rejected',
    dry_run_complete: zh ? '模拟完成' : 'Dry-Run',
  };
  return labels[status || ''] || (zh ? '执行失败' : 'Failed');
}

export function getAutomationHistoryTypeLabel(execution: Pick<PlaybookExecution, '_type'>, language: string): string {
  if (execution._type === 'job') return 'DIRECT';
  return language === 'zh' ? '流程' : 'PLAYBOOK';
}

function formatExecutionTime(value: string | undefined, language: string): string {
  if (!value) return '--';
  return new Date(value).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US');
}

function getDeviceCount(execution: PlaybookExecution): number {
  if (execution.total_devices) return execution.total_devices;
  try { return JSON.parse(execution.device_ids || '[]').length; } catch { return 0; }
}

export function buildAutomationHistoryExportData(executions: PlaybookExecution[], language: string): TableExportData {
  const zh = language === 'zh';
  return {
    headers: zh
      ? ['任务名称', '执行方式', '触发时间', '状态', '设备数', '成功设备数', '失败设备数', '执行人']
      : ['Scenario Name', 'Execution Type', 'Triggered At', 'Status', 'Total Devices', 'Successful Devices', 'Failed Devices', 'Operator'],
    rows: executions.map((execution) => [
      execution.scenario_name || execution.task_name || (zh ? '快捷命令' : 'Direct Command'),
      getAutomationHistoryTypeLabel(execution, language),
      formatExecutionTime(execution.created_at, language),
      getAutomationHistoryStatusLabel(execution.status, language),
      getDeviceCount(execution),
      execution.success_count || 0,
      execution.failed_count || 0,
      execution.author || 'admin',
    ]),
  };
}
