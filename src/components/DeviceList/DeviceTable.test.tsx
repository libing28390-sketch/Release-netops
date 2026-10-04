import type { ComponentProps } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../../types';
import DeviceTable from './DeviceTable';
import { DEFAULT_COLUMNS } from './deviceColumns';

afterEach(() => cleanup());

const sampleDevice = {
  id: 'device-1',
  hostname: 'S6850-6',
  asset_tag: 'NET-BJ-00112',
  ip_address: '10.254.0.6',
  device_category: 'switch',
  role: 'access',
  connection_method: 'ssh',
  vendor: 'H3C',
  platform: 'h3c_comware',
  model: 'S6800',
  version: '7.1.070',
  status: 'online',
  health_status: 'healthy',
  compliance: 'unknown',
  lifecycle_status: 'production',
  sn: '',
  uptime: '',
  site: 'WH-DC-02',
  rack: 'internal-rack-id',
  rack_id: 'internal-rack-id',
  rack_code: 'RACK-CODE-01',
  rack_name: 'WH-DC-02-R01',
  rack_unit: 'U16',
} as unknown as Device;

function renderTable(overrides: Partial<ComponentProps<typeof DeviceTable>> = {}) {
  const onShowDetails = vi.fn();
  const props: ComponentProps<typeof DeviceTable> = {
    rows: [sampleDevice],
    loading: false,
    language: 'zh',
    sortConfig: null,
    onSort: () => {},
    selectedIds: [],
    onSelectChange: () => {},
    onShowDetails,
    onManage: () => {},
    onTestConnection: () => {},
    deviceConnectionChecks: {},
    connectionTestingDeviceId: null,
    columns: DEFAULT_COLUMNS,
    exportData: async () => ({ headers: [], rows: [] }),
    ...overrides,
  };
  return { ...render(<DeviceTable {...props} />), onShowDetails };
}

describe('network device table core columns', () => {
  it('fits core columns to the available table width and hides secondary platform diagnostics', () => {
    renderTable();
    const table = screen.getByRole('table');

    expect(table.className).toContain('w-full');
    expect(table.className).not.toContain('2200px');
    expect(within(table).getByRole('columnheader', { name: '设备名称' })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: '管理 IP' })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: '平台' })).toBeNull();
    expect(within(table).queryByText('h3c_comware')).toBeNull();

    expect(within(table).getByRole('cell', { name: 'WH-DC-02-R01' })).toBeTruthy();
    expect(within(table).queryByText('internal-rack-id')).toBeNull();
  });

  it('opens device detail from a row with the normalized rack name intact', () => {
    const { onShowDetails } = renderTable();

    fireEvent.click(screen.getByText('S6850-6'));

    expect(onShowDetails).toHaveBeenCalledWith(sampleDevice);
  });

  it('shows aligned loading and empty states using the visible column count', () => {
    const loadingView = renderTable({ rows: [], loading: true });
    const loadingCell = screen.getByText('加载中…').closest('td');
    expect(loadingCell?.colSpan).toBe(2 + Object.values(DEFAULT_COLUMNS).filter(Boolean).length);
    loadingView.unmount();

    renderTable({ rows: [], loading: false });
    const emptyCell = screen.getByText('没有匹配的设备').closest('td');
    expect(emptyCell?.colSpan).toBe(2 + Object.values(DEFAULT_COLUMNS).filter(Boolean).length);
  });
});
