import type { TableExportData } from '../components/ui/TableExportMenu';
import type { AlertRecord } from '../types';

interface AlertExportFormatters {
  severity: (value: AlertRecord['severity']) => string;
  timestamp: (value?: string | null) => string;
  duration: (value?: number | null) => string;
  unassigned: string;
}

export interface AlertDeskExportFormatters extends AlertExportFormatters {
  workflow: (value: AlertRecord['workflow_status']) => string;
  metricType: (value: string) => string;
}

export interface AlertHistoryExportFormatters extends AlertExportFormatters {
  notification: (value?: string | null) => string;
}

const alertDeskHeaders = (language: string) => language === 'zh'
  ? ['告警标题', '告警信息', '指标类型', '发生次数', '主机名', 'IP 地址', '接口', '站点', '级别', '状态', '责任人', '发生时间', '持续时间']
  : ['Alert', 'Message', 'Metric Type', 'Occurrences', 'Hostname', 'IP Address', 'Interface', 'Site', 'Severity', 'Status', 'Assignee', 'Created At', 'Duration'];

const alertHistoryHeaders = (language: string) => language === 'zh'
  ? ['告警标题', '告警信息', '发生次数', '主机名', 'IP 地址', '接口', '站点', '级别', '通知', '责任人', '发生时间', '恢复时间', '持续时间']
  : ['Alert', 'Message', 'Occurrences', 'Hostname', 'IP Address', 'Interface', 'Site', 'Severity', 'Notify', 'Assignee', 'Created At', 'Resolved At', 'Duration'];

export const getAlertDeskExportHeaders = alertDeskHeaders;
export const getAlertHistoryExportHeaders = alertHistoryHeaders;

export function buildAlertDeskExportData(
  alerts: AlertRecord[],
  language: string,
  formatters: AlertDeskExportFormatters,
): TableExportData {
  return {
    headers: alertDeskHeaders(language),
    rows: alerts.map((alert) => [
      alert.title || '--',
      alert.message || '--',
      alert.metric_type && alert.metric_type !== 'unknown' ? formatters.metricType(alert.metric_type) : '--',
      String(alert.occurrence_count ?? 1),
      alert.hostname || '--',
      alert.ip_address || '--',
      alert.interface_name || '--',
      alert.site || '--',
      formatters.severity(alert.severity),
      formatters.workflow(alert.workflow_status),
      alert.assignee || formatters.unassigned,
      formatters.timestamp(alert.created_at),
      formatters.duration(alert.duration_seconds),
    ]),
  };
}

export function buildAlertHistoryExportData(
  alerts: AlertRecord[],
  language: string,
  formatters: AlertHistoryExportFormatters,
): TableExportData {
  return {
    headers: alertHistoryHeaders(language),
    rows: alerts.map((alert) => [
      alert.title || '--',
      alert.message || '--',
      String(alert.occurrence_count ?? 1),
      alert.hostname || '--',
      alert.ip_address || '--',
      alert.interface_name || '--',
      alert.site || '--',
      formatters.severity(alert.severity),
      formatters.notification(alert.notification_status),
      alert.assignee || formatters.unassigned,
      formatters.timestamp(alert.created_at),
      formatters.timestamp(alert.resolved_at),
      formatters.duration(alert.duration_seconds),
    ]),
  };
}
