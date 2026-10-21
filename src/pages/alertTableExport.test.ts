import { describe, expect, it } from 'vitest';
import type { AlertRecord } from '../types';
import {
  buildAlertDeskExportData,
  buildAlertHistoryExportData,
  buildAlertSiteLabels,
} from './alertTableExport';

const formatters = {
  severity: (value: AlertRecord['severity']) => value,
  timestamp: (value?: string | null) => value || '',
  duration: (value?: number | null) => String(value ?? ''),
  unassigned: '未分派',
  workflow: (value: AlertRecord['workflow_status']) => String(value),
  metricType: (value: string) => value,
  notification: (value?: string | null) => value || '—',
};

const alert = (overrides: Record<string, unknown> = {}) => ({
  id: 'alert-1',
  dedupe_key: 'device-1:cpu',
  source: 'monitoring',
  severity: 'major',
  title: 'CPU high',
  message: 'CPU usage exceeded threshold',
  created_at: '2026-09-28T12:00:00Z',
  workflow_status: 'open',
  ...overrides,
} as AlertRecord);

describe('alert export site labels', () => {
  it.each(['site-abc123', 'default_site', 'b0212392-4778-47bd-8bfe-6c325cd69e61'])(
    'preserves the canonical CMDB site name %s even when it resembles an ID',
    (siteName) => {
      const siteLabels = buildAlertSiteLabels([{ id: 'site-directory-1', site_name: siteName }]);
      const item = alert({ site_id: 'site-directory-1' });
      expect(buildAlertDeskExportData([item], 'zh', formatters, siteLabels).rows[0][7]).toBe(siteName);
      expect(buildAlertHistoryExportData([item], 'zh', formatters, siteLabels).rows[0][6]).toBe(siteName);
    },
  );

  it('uses the site name for internal site IDs and site codes in both alert exports', () => {
    const siteLabels = buildAlertSiteLabels([{
      id: 'site-abc123',
      site_code: 'SITE-ABC123',
      site_name: '华东数据中心',
    }]);
    const item = alert({ site: 'site-abc123', site_code: 'SITE-ABC123' });

    const desk = buildAlertDeskExportData([item], 'zh', formatters, siteLabels);
    const history = buildAlertHistoryExportData([item], 'zh', formatters, siteLabels);

    expect(desk.rows[0][7]).toBe('华东数据中心');
    expect(history.rows[0][6]).toBe('华东数据中心');
    expect(JSON.stringify([desk, history])).not.toContain('site-abc123');
  });

  it('prefers a direct site name and hides an unresolved built-in site ID', () => {
    const direct = buildAlertDeskExportData(
      [alert({ site: 'site-abc123', site_name: '华南机房' })],
      'zh',
      formatters,
      new Map(),
    );
    const unresolved = buildAlertDeskExportData(
      [alert({ site: 'site-abc123' })],
      'zh',
      formatters,
      new Map(),
    );

    expect(direct.rows[0][7]).toBe('华南机房');
    expect(unresolved.rows[0][7]).toBe('未分配站点');
  });
});
