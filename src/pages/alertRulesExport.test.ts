import { describe, expect, it } from 'vitest';
import type { AlertRuleSettings } from '../types';
import { buildAlertRulesExportData, getAlertRulesExportHeaders } from './alertRulesExport';

describe('alert rules export', () => {
  it('keeps each visible rule field in its own matching export column and omits internal IDs', () => {
    const rule = {
      id: 'internal-rule-id',
      name: 'CPU high',
      metric_type: 'cpu',
      scope_type: 'site',
      scope_match_mode: 'exact',
      scope_value: 'site-1',
      severity: 'major',
      threshold: 80,
      for_duration_seconds: 90,
      enabled: false,
      aggregation_mode: 'dedupe_key',
      notification_repeat_window_seconds: 0,
      notification_channels: ['email'],
      notification_group_names: ['NOC'],
      notify_on_active: true,
      notify_on_recovery: true,
      notify_on_reopen_after_maintenance: false,
      rule_supported: true,
      collection: {
        collection_source: 'template',
        collection_label: 'SNMP',
        collection_label_en: 'SNMP',
        template_linked: true,
        template_section: 'System',
        oid_paths: [],
      },
      updated_at: '2026-09-28T01:00:00Z',
    } as unknown as AlertRuleSettings;

    const exported = buildAlertRulesExportData([rule], 'en', (channel) => channel === 'email' ? 'Email' : channel);
    const column = (name: string) => exported.headers.indexOf(name);

    expect(exported.headers).toEqual(getAlertRulesExportHeaders('en'));
    expect(exported.rows).toHaveLength(1);
    expect(exported.rows[0]).toHaveLength(exported.headers.length);
    expect(exported.headers).toEqual([
      'Rule', 'Metric', 'Collector', 'Template section', 'Scope type', 'Scope value', 'Threshold', 'Duration',
      'Severity', 'Notification channels', 'Notification groups', 'Status', 'Executor', 'Updated',
    ]);
    expect(exported.rows[0][column('Collector')]).toBe('SNMP');
    expect(exported.rows[0][column('Template section')]).toBe('System');
    expect(exported.rows[0][column('Scope type')]).toBeTruthy();
    expect(exported.rows[0][column('Scope value')]).toBeTruthy();
    expect(exported.rows[0][column('Threshold')]).toBe('> 80%');
    expect(exported.rows[0][column('Duration')]).toBe('1m');
    expect(exported.rows[0][column('Notification channels')]).toBe('Email');
    expect(exported.rows[0][column('Notification groups')]).toBe('NOC');
    expect(exported.rows[0]).not.toContain('internal-rule-id');
  });
});
