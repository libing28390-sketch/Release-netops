import type { TableExportData } from '../../components/ui/TableExportMenu';

const sensitiveKey = /password|passwd|pwd|secret|token|credential|private.?key|community|pin|口令|密码|密钥|令牌/i;

export function getExecutionSnapshotCells(metricKey: string, metricValue: unknown): { value: string; error: string; isError: boolean } {
  const isError = Boolean(metricValue && typeof metricValue === 'object' && 'error' in metricValue);
  if (sensitiveKey.test(metricKey)) return { value: '', error: '', isError };
  if (isError) {
    const error = (metricValue as { error?: unknown }).error;
    return { value: '', error: error == null ? '' : String(error), isError: true };
  }
  return { value: metricValue == null ? String(metricValue) : String(metricValue), error: '', isError: false };
}

export function buildExecutionSnapshotExportData(metrics: Record<string, unknown>, language: string): TableExportData {
  const zh = language === 'zh';
  return {
    headers: zh ? ['指标键', '值', '错误'] : ['Metric Key', 'Value', 'Error'],
    rows: Object.entries(metrics).map(([key, metricValue]) => {
      const cells = getExecutionSnapshotCells(key, metricValue);
      return [key, cells.value, cells.error];
    }),
  };
}
