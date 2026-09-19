import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MonitoringReportsPage from './MonitoringReportsPage';

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
};

const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(data),
}) as unknown as Response;

const ReportRouteControls = () => {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate('/monitor/reports/devices')}>Open device report</button>;
};

describe('MonitoringReportsPage requests', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('keeps data and loading state owned by the latest tab request', async () => {
    const firstRequest = deferred<Response>();
    const secondRequest = deferred<Response>();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockReturnValueOnce(firstRequest.promise).mockReturnValueOnce(secondRequest.promise);

    render(
      <MemoryRouter initialEntries={['/monitor/reports/interfaces']}>
        <ReportRouteControls />
        <MonitoringReportsPage language="en" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Open device report' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    await act(async () => {
      secondRequest.resolve(response({
        items: [{
          id: 'latest-device', hostname: 'latest-vm', ip_address: '192.0.2.10', vendor: 'vmware', platform: 'vm',
          site_name: 'Lab', role: 'server', status: 'ONLINE', cpu_usage: null, memory_usage: null,
          temperature_str: null, risk_level: 'NO_DATA', sample_quality: 'NO_DATA', sample_time: null,
        }],
        summary: { total_devices: 1, avg_cpu: null, avg_mem: null, high_cpu_count: null, high_mem_count: null, sample_quality: 'NO_DATA' },
      }));
      await secondRequest.promise;
    });

    expect(await screen.findByText('latest-vm')).toBeTruthy();
    expect(screen.getAllByText('NO_DATA').length).toBeGreaterThan(0);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);

    await act(async () => {
      firstRequest.resolve(response({
        items: [{ id: 'stale-interface', hostname: 'stale-interface', max_util: 10 }],
        summary: { total_interfaces: 1 },
      }));
      await firstRequest.promise;
    });

    expect(screen.queryByText('stale-interface')).toBeNull();
    expect(screen.queryByText('Loading live telemetry and CMDB metadata…')).toBeNull();
  });

  it('renders a localized permission state for report access denial', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ detail: 'forbidden' }, 403));

    render(
      <MemoryRouter initialEntries={['/monitor/reports/devices']}>
        <MonitoringReportsPage language="en" />
      </MemoryRouter>,
    );

    expect(await screen.findByText('You do not have permission to view monitoring reports')).toBeTruthy();
  });

  it('shows missing interface samples as unavailable rather than zero or normal', async () => {
    vi.mocked(fetch).mockResolvedValue(response({
      items: [{
        id: 'no-sample-port', hostname: 'no-sample-device', vendor: 'vmware', ip_address: '192.0.2.20',
        site_name: 'Lab', role: 'server', interface_name: 'vmnic0', oper_status: 'UP', speed_str: null,
        in_bps_str: null, out_bps_str: null, max_util: null, sample_quality: 'NO_DATA', sample_time: null,
        total_errors: 0, alert_level: 'NORMAL', advice: 'Normal',
      }],
      summary: {
        total_interfaces: 1, up_interfaces: 1, down_interfaces: null, high_util_count: null,
        critical_util_count: null, error_interfaces_count: null, avg_utilization: null,
        sample_quality: 'NO_DATA', sample_time: null,
      },
    }));

    render(
      <MemoryRouter initialEntries={['/monitor/reports/interfaces']}>
        <MonitoringReportsPage language="en" />
      </MemoryRouter>,
    );

    expect(await screen.findByText('no-sample-device')).toBeTruthy();
    expect(screen.getAllByText('NO_DATA').length).toBeGreaterThan(0);
    expect(screen.queryByText('0.0%')).toBeNull();
    expect(screen.queryByText('Normal')).toBeNull();
    expect(screen.queryByText('All UP')).toBeNull();
  });
});
