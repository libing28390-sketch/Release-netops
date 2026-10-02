import type { TableExportData } from '../components/ui/TableExportMenu';
import type { AlertRecord } from '../types';

export interface AlertSiteDirectoryItem {
  id?: string | null;
  site_name?: string | null;
  site_code?: string | null;
}

export type AlertSiteLabels = ReadonlyMap<string, string>;

const normalizeSiteKey = (value: unknown): string => String(value || '').trim().toLowerCase();

export function buildAlertSiteLabels(sites: AlertSiteDirectoryItem[]): AlertSiteLabels {
  const labels = new Map<string, string>();
  sites.forEach((site) => {
    const label = String(site.site_name || '').trim();
    // site_name comes from the CMDB directory and is authoritative even if
    // a user has chosen a name that resembles a generated identifier.
    if (!label) return;
    [site.id, site.site_code, site.site_name].forEach((key) => {
      const normalized = normalizeSiteKey(key);
      if (normalized) labels.set(normalized, label);
    });
  });
  return labels;
}

function isInternalSiteId(value: string): boolean {
  return /^(?:site-[a-z0-9]+|default_site)$/i.test(value)
    || /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export function alertSiteLabel(
  alert: AlertRecord,
  labels: AlertSiteLabels | undefined,
  unassigned: string,
): string {
  const rawAlert = alert as AlertRecord & {
    site_id?: string | null;
    site_name?: string | null;
    site_code?: string | null;
  };
  const directName = String(rawAlert.site_name || '').trim();
  if (directName && !isInternalSiteId(directName)) {
    return labels?.get(normalizeSiteKey(directName)) || directName;
  }

  const siteCandidates = [rawAlert.site, rawAlert.site_id, rawAlert.site_code, rawAlert.site_name]
    .map((value) => String(value || '').trim())
    .filter(Boolean);
  for (const candidate of siteCandidates) {
    const mappedLabel = labels?.get(normalizeSiteKey(candidate));
    if (mappedLabel) return mappedLabel;
  }

  return unassigned;
}

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
  siteLabels?: AlertSiteLabels,
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
      alertSiteLabel(alert, siteLabels, language === 'zh' ? '未分配站点' : 'Unassigned site'),
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
  siteLabels?: AlertSiteLabels,
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
      alertSiteLabel(alert, siteLabels, language === 'zh' ? '未分配站点' : 'Unassigned site'),
      formatters.severity(alert.severity),
      formatters.notification(alert.notification_status),
      alert.assignee || formatters.unassigned,
      formatters.timestamp(alert.created_at),
      formatters.timestamp(alert.resolved_at),
      formatters.duration(alert.duration_seconds),
    ]),
  };
}
