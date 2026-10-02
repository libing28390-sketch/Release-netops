import { describe, expect, it } from 'vitest';
import type { AlertRecord, AuditEvent } from '../types';
import { buildAlertDeskExportData, buildAlertHistoryExportData, buildAlertSiteLabels, getAlertDeskExportHeaders, getAlertHistoryExportHeaders } from './alertTableExport';
import { buildAuditExportData, getAuditExportHeaders } from './auditTableExport';

const alertFormatters = {
  severity: (value: string) => `severity:${value}`,
  workflow: (value: string) => `workflow:${value}`,
  notification: (value?: string | null) => `notification:${value || '--'}`,
  metricType: (value: string) => `metric:${value}`,
  timestamp: (value?: string | null) => value || '--',
  duration: (value?: number | null) => value == null ? '--' : `${value}s`,
  unassigned: 'Unassigned',
};

const alertFixture: AlertRecord = {
  id: 'internal-alert-id',
  dedupe_key: 'internal-dedupe-key',
  source: 'internal-source',
  metric_type: 'cpu',
  notification_status: 'succeeded',
  severity: 'critical',
  title: 'CPU high',
  message: 'CPU utilization reached 95%',
  device_id: 'internal-device-id',
  interface_name: 'Ethernet1/1',
  hostname: 'core-01',
  ip_address: '192.0.2.10',
  site_id: 'site-cmdb-1',
  site: 'site-cmdb-1',
  created_at: '2026-09-28 12:00:00',
  resolved_at: '2026-09-28 12:10:00',
  workflow_status: 'resolved',
  assignee: 'admin',
  occurrence_count: 3,
  duration_seconds: 600,
};

const alertSiteLabels = buildAlertSiteLabels([{ id: 'site-cmdb-1', site_name: 'DC-1' }]);

describe('alert table exports', () => {
  it('splits every visible alert-desk value into a matching business column', () => {
    const data = buildAlertDeskExportData([alertFixture], 'zh', alertFormatters, alertSiteLabels);

    expect(data.headers).toEqual(getAlertDeskExportHeaders('zh'));
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0]).toEqual([
      'CPU high', 'CPU utilization reached 95%', 'metric:cpu', '3', 'core-01', '192.0.2.10', 'Ethernet1/1', 'DC-1',
      'severity:critical', 'workflow:resolved', 'admin', '2026-09-28 12:00:00', '600s',
    ]);
    expect(data.headers).not.toContain('操作');
    expect(data.rows[0].join(' ')).not.toContain('internal-alert-id');
    expect(data.rows[0].join(' ')).not.toContain('internal-device-id');
    expect(data.rows[0].join(' ')).not.toContain('internal-dedupe-key');
  });

  it('keeps historical alert notification, times, and object attributes in separate columns', () => {
    const data = buildAlertHistoryExportData([alertFixture], 'en', alertFormatters, alertSiteLabels);

    expect(data.headers).toEqual(getAlertHistoryExportHeaders('en'));
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0]).toEqual([
      'CPU high', 'CPU utilization reached 95%', '3', 'core-01', '192.0.2.10', 'Ethernet1/1', 'DC-1',
      'severity:critical', 'notification:succeeded', 'admin', '2026-09-28 12:00:00', '2026-09-28 12:10:00', '600s',
    ]);
  });
});

describe('audit table exports', () => {
  it('separates summary, event type, status, and severity without internal IDs or actions', () => {
    const event: AuditEvent = {
      id: 'internal-event-id',
      event_type: 'DEVICE_UPDATE',
      category: 'inventory',
      severity: 'high',
      status: 'success',
      actor_username: 'admin',
      target_id: 'internal-target-id',
      device_id: 'internal-device-id',
      summary: 'Updated device core-01',
      created_at: '2026-09-28T12:00:00Z',
    };
    const data = buildAuditExportData([event], 'zh', {
      timestamp: (value) => value,
      summary: (value) => `summary:${value}`,
      eventType: (value) => `type:${value}`,
      category: (value) => `category:${value}`,
      status: (value) => `status:${value}`,
      severity: (value) => `severity:${value}`,
      unknownTarget: '未知',
    });

    expect(data.headers).toEqual(getAuditExportHeaders('zh'));
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0]).toEqual([
      '2026-09-28T12:00:00Z', 'summary:Updated device core-01', 'type:DEVICE_UPDATE',
      'category:inventory', '未知', 'admin', 'status:success', 'severity:high',
    ]);
    expect(data.headers).not.toContain('操作');
    expect(data.rows[0].join(' ')).not.toContain('internal-');
  });
});
