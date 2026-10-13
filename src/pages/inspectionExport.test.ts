import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildInspectionResultExportData, buildInspectionRunExportData, buildRecentInspectionRunExportData, fetchAllInspectionRuns } from './inspectionExport';

describe('inspection exports', () => {
  afterEach(() => vi.restoreAllMocks());

  it('splits inspection run scope and health distribution while excluding run IDs', () => {
    const data = buildInspectionRunExportData([{
      id: 'run-internal-id', trigger_type: 'manual', scope_type: 'site', scope_filter: 'DC-1', created_by: 'admin',
      total_devices: 3, healthy_count: 1, warning_count: 1, critical_count: 1, avg_health_score: 66, started_at: '2026-09-28T12:30:45Z',
    }], 'zh');

    expect(data.headers).toEqual(['触发方式', '范围类型', '范围', '创建人', '设备总数', '正常设备', '告警设备', '严重设备', '平均得分', '开始时间']);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0]).toEqual(['manual', 'site', 'DC-1', 'admin', '3', '1', '1', '1', '66', '2026-09-28 12:30:45']);
    expect(data.rows[0].join(' ')).not.toContain('run-internal-id');
  });

  it('filters all loaded runs by the visible search fields', () => {
    const data = buildInspectionRunExportData([
      { id: 'secret-id-a', trigger_type: 'manual', scope_type: 'site', scope_filter: 'DC-1' },
      { id: 'secret-id-b', trigger_type: 'scheduled', scope_type: 'device', scope_filter: 'edge-02' },
    ], 'en', 'edge-02');

    expect(data.rows).toHaveLength(1);
    expect(data.rows[0][0]).toBe('scheduled');
  });

  it('exports the compact recent-runs table in visible column order without the hidden run ID or creator', () => {
    const data = buildRecentInspectionRunExportData([{
      id: 'internal-run-id', trigger_type: 'manual', scope_type: 'site', scope_filter: 'DC-1', created_by: 'private-operator',
      total_devices: 3, healthy_count: 1, warning_count: 1, critical_count: 1, avg_health_score: 66, started_at: '2026-09-28T12:30:45Z',
    }], 'en');

    expect(data.headers).toEqual(['Trigger', 'Scope Type', 'Scope', 'Devices', 'Healthy', 'Warning', 'Critical', 'Avg Score', 'Time']);
    expect(data.rows[0]).toEqual(['manual', 'site', 'DC-1', '3', '1', '1', '1', '66', '2026-09-28 12:30:45']);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0].join(' ')).not.toContain('internal-run-id');
    expect(data.rows[0].join(' ')).not.toContain('private-operator');
  });

  it('splits per-device result composites into separate columns', () => {
    const data = buildInspectionResultExportData([{
      id: 'result-db-id', device_id: 'device-db-id', hostname: 'edge-01', ip_address: '192.0.2.1', platform: 'cisco_ios',
      health_status: 'warning', health_score: 78, cpu_usage: 20, memory_usage: 42, temperature: 38,
      fan_status: 1, psu_status: 0, interface_total: 24, interface_down: 1, ping_ok: 1, ssh_ok: 0,
    }], 'en');

    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0]).toEqual(['edge-01', '192.0.2.1', 'cisco_ios', 'warning', '78', '20%', '42%', '38°C', '✓', '✗', '24', '1', '✓', '✗']);
    expect(data.rows[0].join(' ')).not.toContain('device-db-id');
  });

  it('fetches every offset-based history page and preserves the server total', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { total: 3, items: [{ id: 'a' }, { id: 'b' }] } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { total: 3, items: [{ id: 'c' }] } }), { status: 200 }));
    const rows = await fetchAllInspectionRuns({}, fetcher as typeof fetch, 2);

    expect(rows.map((row) => row.id)).toEqual(['a', 'b', 'c']);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/inspections?limit=2&offset=0',
      '/api/inspections?limit=2&offset=2',
    ]);
  });
});
