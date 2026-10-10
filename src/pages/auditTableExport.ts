import type { TableExportData } from '../components/ui/TableExportMenu';
import type { AuditEvent } from '../types';

export interface AuditExportFormatters {
  timestamp: (value: string) => string;
  summary: (value: string) => string;
  eventType: (value: string) => string;
  category: (value: string) => string;
  status: (value: string) => string;
  severity: (value: AuditEvent['severity']) => string;
  unknownTarget: string;
}

export const getAuditExportHeaders = (language: string) => language === 'zh'
  ? ['时间', '摘要', '事件类型', '分类', '目标', '用户', '状态', '严重度']
  : ['Timestamp', 'Summary', 'Event Type', 'Category', 'Target', 'User', 'Status', 'Severity'];

export function buildAuditExportData(
  events: AuditEvent[],
  language: string,
  formatters: AuditExportFormatters,
): TableExportData {
  return {
    headers: getAuditExportHeaders(language),
    rows: events.map((event) => [
      formatters.timestamp(event.created_at),
      formatters.summary(event.summary),
      formatters.eventType(event.event_type),
      formatters.category(event.category),
      event.target_name || formatters.unknownTarget,
      event.actor_username || 'system',
      formatters.status(event.status),
      formatters.severity(event.severity),
    ]),
  };
}
