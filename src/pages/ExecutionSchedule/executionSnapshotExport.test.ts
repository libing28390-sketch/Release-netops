import { describe, expect, it } from 'vitest';
import { buildExecutionSnapshotExportData } from './executionSnapshotExport';

describe('execution snapshot export', () => {
  it('splits value and error into separate columns and blanks values for sensitive metric keys', () => {
    const data = buildExecutionSnapshotExportData({
      'system.cpu': '12%',
      'ssh.error': { error: 'connection refused' },
      'device.password': 'super-secret-value',
      'api_token': { error: 'secret diagnostic' },
    }, 'en');

    expect(data.headers).toEqual(['Metric Key', 'Value', 'Error']);
    expect(data.rows).toEqual([
      ['system.cpu', '12%', ''],
      ['ssh.error', '', 'connection refused'],
      ['device.password', '', ''],
      ['api_token', '', ''],
    ]);
    expect(data.rows).toHaveLength(4);
    expect(JSON.stringify(data.rows)).not.toContain('super-secret-value');
    expect(JSON.stringify(data.rows)).not.toContain('secret diagnostic');
  });
});
