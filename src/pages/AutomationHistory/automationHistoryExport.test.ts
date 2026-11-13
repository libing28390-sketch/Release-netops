import { describe, expect, it } from 'vitest';
import { buildAutomationHistoryExportData } from './automationHistoryExport';

describe('automation history export', () => {
  it('exports separate visible execution type and status fields without IDs, actions, or device IDs', () => {
    const data = buildAutomationHistoryExportData([{
      id: 'internal-execution-id',
      _type: 'job',
      status: 'dry_run_complete',
      scenario_name: 'Nightly audit',
      total_devices: 2,
      device_ids: '["device-internal-a","device-internal-b"]',
      created_at: '2026-09-28T10:30:00Z',
      success_count: 2,
      failed_count: 0,
      author: 'scheduler',
      output: 'private execution output',
    }], 'en');

    expect(data.headers).toEqual([
      'Scenario Name', 'Execution Type', 'Triggered At', 'Status',
      'Total Devices', 'Successful Devices', 'Failed Devices', 'Operator',
    ]);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0][0]).toBe('Nightly audit');
    expect(data.rows[0][1]).toBe('DIRECT');
    expect(data.rows[0][3]).toBe('Dry-Run');
    expect(data.rows[0].join(' ')).not.toContain('internal-execution-id');
    expect(data.rows[0].join(' ')).not.toContain('device-internal');
    expect(data.rows[0].join(' ')).not.toContain('private execution output');
  });

  it('uses the same fallback status label shown by the table for unknown statuses', () => {
    const data = buildAutomationHistoryExportData([{
      id: 'row-id', _type: 'playbook', status: 'unrecognized', created_at: '2026-09-28T10:30:00Z',
    }], 'zh');

    expect(data.rows[0][1]).toBe('流程');
    expect(data.rows[0][3]).toBe('执行失败');
  });
});
