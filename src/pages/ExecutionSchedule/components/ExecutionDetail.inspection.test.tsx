import React, { useState } from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InspectionView } from './ExecutionDetail';

const makeViewProps = (result: Record<string, unknown>, tab: 'analysis' | 'snapshot' | 'compliance' | 'raw' = 'analysis') => ({
  zh: true,
  inspectionDetail: { results: [result] },
  selectedInspDeviceId: String(result.device_id || 'device-1'),
  setSelectedInspDeviceId: vi.fn(),
  collapsedCmds: {},
  toggleCmdCollapse: vi.fn(),
  expandAllCmds: vi.fn(),
  collapseAllCmds: vi.fn(),
  inspParseResults: {},
  inspCopiedKey: null,
  inspDetailTab: tab,
  setInspDetailTab: vi.fn(),
  inspParseViewMode: {},
  setInspParseViewMode: vi.fn() as any,
  trendData: null,
  trendLoading: false,
  setTrendData: vi.fn(),
  onParseCmd: vi.fn(),
  onCopyText: vi.fn(),
  onFetchTrend: vi.fn(),
  setCollapsedCmds: vi.fn() as any,
  setInspParseResults: vi.fn() as any,
});

const InspectionViewHarness: React.FC<{ result: Record<string, unknown> }> = ({ result }) => {
  const [tab, setTab] = useState<'analysis' | 'snapshot' | 'compliance' | 'raw'>('analysis');
  return <InspectionView {...makeViewProps(result, tab)} setInspDetailTab={setTab} />;
};

describe('InspectionView summary', () => {
  afterEach(cleanup);

  it('shows a concise prioritized summary and keeps full raw output under collapsed technical details', async () => {
    const result = {
      id: 'result-1',
      device_id: 'device-1',
      hostname: 'leaf-1',
      ip_address: '192.0.2.10',
      platform: 'cisco_ios',
      health_status: 'warning',
      health_score: 75,
      ping_ok: 1,
      ssh_ok: 1,
      analysis_json: [
        { metric: 'CPU 使用率', key: 'cpu_util', value: 95, unit: '%', status: 'critical', conclusion: 'CPU 严重超标', suggestion: '检查占用最高的进程。' },
        { metric: '设备温度', key: 'temp_C', value: 42, unit: '°C', status: 'warning', conclusion: '温度接近告警线', suggestion: '关注温度变化。' },
        { metric: '风扇状态', key: 'fan_status', value: null, unit: 'status', parse_type: 'status', status: 'NOT_COLLECTED', conclusion: '未采集' },
      ],
      findings_json: [
        { type: 'data_error', severity: 'critical', message: 'CPU 使用率严重超标' },
        { type: 'data_error', severity: 'warning', message: '设备温度需要关注' },
      ],
      correlated_risks_json: [],
      metrics_json: {
        cpu_util: 95,
        cpu_util_status: 'ERROR',
        temp_C: 42,
        temp_C_status: 'SUCCESS',
        fan_status: null,
        fan_status_status: 'NOT_COLLECTED',
      },
      raw_outputs_json: { 'show environment': 'RAW_DETAIL_RETAINED' },
    };
    const user = userEvent.setup();
    render(<InspectionViewHarness result={result} />);

    const summary = screen.getByRole('region', { name: '巡检结果摘要' });
    expect(within(summary).getByText('需要处理')).toBeTruthy();
    expect(within(summary).getByText('严重 1 · 警告 1')).toBeTruthy();
    expect(within(summary).getByText('CPU 严重超标')).toBeTruthy();
    expect(within(summary).getByText('建议：检查占用最高的进程。')).toBeTruthy();
    expect(within(summary).getByText('CPU 使用率')).toBeTruthy();
    expect(within(summary).getByText('95%')).toBeTruthy();
    expect(within(summary).getByText('设备温度')).toBeTruthy();
    expect(within(summary).getByText('42°C')).toBeTruthy();
    expect(within(summary).getByText('未采集')).toBeTruthy();
    expect(within(summary).getByText(/未采集或状态未知，不计为严重故障/)).toBeTruthy();
    expect(screen.getByText('Ping: OK')).toBeTruthy();
    expect(screen.getByText('SSH: OK')).toBeTruthy();

    const details = screen.getByText('技术详情').closest('details');
    expect(details?.open).toBe(false);
    await user.click(screen.getByText('技术详情'));
    await user.click(screen.getByRole('button', { name: '原始输出' }));
    expect(await screen.findByText('RAW_DETAIL_RETAINED')).toBeTruthy();
  });

  it('keeps unknown and not-collected statuses out of critical counts', () => {
    const result = {
      id: 'result-2',
      device_id: 'device-2',
      hostname: 'leaf-2',
      ip_address: '192.0.2.11',
      health_status: 'unknown',
      ping_ok: 1,
      ssh_ok: 1,
      analysis_json: [{ metric: '电源状态', key: 'psu_status', status: 'unknown', value: null }],
      findings_json: [{ type: 'collection', severity: 'unknown', message: '电源状态未采集' }],
      correlated_risks_json: [],
      metrics_json: { psu_status_status: 'NOT_COLLECTED' },
      raw_outputs_json: {},
    };
    render(<InspectionView {...makeViewProps(result)} />);

    const summary = screen.getByRole('region', { name: '巡检结果摘要' });
    expect(within(summary).getByText('状态未知')).toBeTruthy();
    expect(within(summary).getByText('严重 0 · 警告 0')).toBeTruthy();
    expect(within(summary).getByText(/未采集或状态未知/)).toBeTruthy();
    expect(within(summary).queryByText('需要处理')).toBeNull();
    expect(screen.getAllByText('状态未知').length).toBeGreaterThan(0);
  });

  it('renders status-valued core metrics as normal, alert, failure, or not collected', () => {
    const result = {
      id: 'result-3',
      device_id: 'device-3',
      hostname: 'leaf-3',
      ip_address: '192.0.2.12',
      health_status: 'critical',
      ping_ok: 1,
      ssh_ok: 1,
      analysis_json: [
        { metric: '另一风扇状态', key: 'network_fan', unit: 'status', parse_type: 'status', value: 0, status: 'healthy' },
        { metric: 'CPU 使用率', key: 'cpu_util', unit: '%', value: 20, status: 'healthy' },
        { metric: '内存使用率', key: 'memory_usage', unit: '%', value: 40, status: 'healthy' },
        { metric: '设备温度', key: 'device_temp', unit: '°C', value: 35, status: 'healthy' },
        { metric: '电源状态', key: 'hardware_psu', unit: 'status', parse_type: 'status', value: 2, status: 'critical' },
        { metric: '风扇状态', key: 'hardware_fan', unit: 'status', parse_type: 'status', value: 1, status: 'warning' },
        { metric: '备用风扇状态', key: 'fan_backup_status', unit: 'status', parse_type: 'status', value: null, status: 'NOT_COLLECTED' },
      ],
      findings_json: [],
      correlated_risks_json: [],
      metrics_json: {
        hardware_fan: 1,
        hardware_fan_status: 'WARNING',
        hardware_psu: 2,
        hardware_psu_status: 'ERROR',
        fan_backup_status: null,
        fan_backup_status_status: 'NOT_COLLECTED',
        network_fan: 0,
        network_fan_status: 'SUCCESS',
        cpu_util: 20,
        cpu_util_status: 'SUCCESS',
        memory_usage: 40,
        memory_usage_status: 'SUCCESS',
        device_temp: 35,
        device_temp_status: 'SUCCESS',
      },
      raw_outputs_json: {},
    };
    render(<InspectionView {...makeViewProps(result)} />);

    const summary = screen.getByRole('region', { name: '巡检结果摘要' });
    const metricCardText = (label: string, value: string) => within(summary)
      .getAllByText(label)
      .map(element => element.parentElement?.textContent || '')
      .find(text => text.includes(value));
    expect(metricCardText('另一风扇状态', '正常')).toContain('正常');
    expect(metricCardText('风扇状态', '告警')).toContain('告警');
    expect(metricCardText('电源状态', '故障')).toContain('故障');
    expect(metricCardText('备用风扇状态', '未采集')).toContain('未采集');
    expect(metricCardText('风扇状态', '告警')).not.toContain('1');
    expect(metricCardText('电源状态', '故障')).not.toContain('2');
  });

  it('uses expected status values when no evaluated metric status is available', () => {
    const result = {
      id: 'result-expected',
      device_id: 'device-expected',
      hostname: 'leaf-expected',
      ip_address: '192.0.2.14',
      health_status: 'warning',
      ping_ok: 1,
      ssh_ok: 1,
      analysis_json: [
        { metric: '风扇管理状态', key: 'fan_management_status', unit: 'status', parse_type: 'status', value: 'up', status: 'unknown', expected_value: 'ready' },
      ],
      findings_json: [],
      correlated_risks_json: [],
      metrics_json: { fan_management_status: 'up' },
      raw_outputs_json: {},
    };
    render(<InspectionView {...makeViewProps(result)} />);

    const summary = screen.getByRole('region', { name: '巡检结果摘要' });
    const metricCard = within(summary).getAllByText('风扇管理状态').find(element => element.parentElement?.textContent?.includes('告警'));
    expect(metricCard?.parentElement?.textContent).toContain('告警');
  });

  it('distinguishes connectivity success, failure, unknown, and not-collected states', () => {
    const firstResult = {
      id: 'result-4',
      device_id: 'device-4',
      hostname: 'leaf-4',
      ip_address: '192.0.2.13',
      health_status: 'warning',
      ping_ok: 1,
      ssh_ok: 0,
      analysis_json: [],
      findings_json: [],
      correlated_risks_json: [],
      metrics_json: {},
      raw_outputs_json: {},
    };
    const { unmount } = render(<InspectionView {...makeViewProps(firstResult)} />);
    expect(screen.getByText('Ping: OK').className).toContain('text-emerald-400');
    expect(screen.getByText('SSH: FAIL').className).toContain('text-red-400');
    unmount();

    const secondResult = {
      ...firstResult,
      id: 'result-5',
      device_id: 'device-5',
      ping_ok: 'unknown',
      ssh_ok: null,
    };
    render(<InspectionView {...makeViewProps(secondResult)} />);
    const pingBadge = screen.getByText('Ping: 未知');
    const sshBadge = screen.getByText('SSH: 未采集');
    expect(pingBadge.className).toContain('text-slate-400');
    expect(sshBadge.className).toContain('text-slate-400');
    expect(pingBadge.className).not.toContain('text-red-400');
    expect(sshBadge.className).not.toContain('text-red-400');
  });
});
