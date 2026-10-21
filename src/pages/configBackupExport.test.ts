import { describe, expect, it } from 'vitest';
import { buildBackupRunExportData } from './configBackupExport';

describe('configuration backup run exports', () => {
  it('matches the visible site result chips and keeps each value under its header', () => {
    const data = buildBackupRunExportData([{
      id: 'internal-run-id',
      started_at: '2026-09-28T10:00:00Z',
      trigger: 'manual',
      author: 'admin',
      status: 'partial',
      total_devices: 5,
      success_count: 3,
      failed_count: 1,
      skipped_count: 1,
      site_summary: [
        { site: 'DC-1', success: 2, failed: 1, unknown: 0, skipped: 0 },
        { site: 'DC-2', success: 1, failed: 0, unknown: 1, skipped: 1 },
      ],
    }], 'en', (value) => value);

    expect(data.headers).toEqual([
      'Started', 'Trigger', 'Operator', 'Sites', 'Site Results', 'Status',
      'Successful Devices', 'Failed Devices', 'Unknown Devices', 'Skipped Devices', 'Total Devices',
    ]);
    expect(data.rows[0]).toEqual([
      '2026-09-28T10:00:00Z', 'manual', 'admin', 'DC-1, DC-2', 'Attention 1; Attention 1', 'Attention', 3, 1, 1, 1, 5,
    ]);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0].join(' ')).not.toContain('internal-run-id');
    expect(data.rows[0][4]).not.toContain('DC-1:');
    expect(data.rows[0][4]).not.toContain('skipped');
  });
});
