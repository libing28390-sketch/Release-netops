import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../../../types';
import { DeviceSelectionStep } from './DeviceSelectionStep';

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, initial: _initial, animate: _animate, exit: _exit, transition: _transition, ...props }: React.HTMLAttributes<HTMLDivElement> & Record<string, unknown>) => <div {...props}>{children}</div>,
    button: ({ children, initial: _initial, animate: _animate, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & Record<string, unknown>) => <button {...props}>{children}</button>,
  },
}));
vi.mock('../../../components/DataTable', () => ({ DataTable: ({ children }: { children: React.ReactNode }) => <table>{children}</table> }));
vi.mock('../../../components/Pagination', () => ({ default: () => null }));

const device = {
  id: 'device-1',
  hostname: 'router-1',
  ip_address: '192.0.2.1',
  status: 'online',
  vendor: 'Cisco',
  platform: 'cisco_ios',
  role: 'router',
} as Device;

const makeProps = () => ({
  isZh: false,
  language: 'en',
  automationSearch: '',
  onAutomationSearchChange: vi.fn(),
  deviceTree: [],
  treeFilterSite: null,
  treeFilterRole: null,
  handleTreeFilter: vi.fn(),
  setTreeFilterSite: vi.fn(),
  setTreeFilterRole: vi.fn(),
  deviceTypeFilter: 'all' as const,
  setDeviceTypeFilter: vi.fn(),
  statusFilter: 'all',
  setStatusFilter: vi.fn(),
  deviceItems: [device],
  totalDevices: 1,
  onlineDeviceCount: 1,
  devicePageLoading: false,
  devicePageError: '',
  onRetryDevicePage: vi.fn(),
  exportAllMatchingDevices: vi.fn().mockResolvedValue({ headers: [], rows: [] }),
  vendors: ['Cisco', 'Huawei'],
  vendorFilter: 'all',
  setVendorFilter: vi.fn(),
  devicePageSize: 10,
  setDevicePageSize: vi.fn(),
  deviceViewMode: 'grid' as const,
  setDeviceViewMode: vi.fn(),
  batchMode: true,
  onToggleBatchMode: vi.fn(),
  batchDeviceIds: ['device-1'],
  onToggleBatchDevice: vi.fn(),
  onRememberDevice: vi.fn(),
  selectedDevice: null,
  devicePage: 1,
  setDevicePage: vi.fn(),
  targetCount: 1,
  handleClearSelection: vi.fn(),
  devices: [device],
});

const SelectionHarness = () => {
  const [showSelectedDrawer, setShowSelectedDrawer] = React.useState(false);
  const [batchDeviceIds, setBatchDeviceIds] = React.useState(['device-1']);
  return (
    <DeviceSelectionStep
      {...makeProps()}
      batchDeviceIds={batchDeviceIds}
      targetCount={batchDeviceIds.length}
      onToggleBatchDevice={(deviceId) => setBatchDeviceIds((current) => (
        current.includes(deviceId) ? current.filter((id) => id !== deviceId) : [...current, deviceId]
      ))}
      showSelectedDrawer={showSelectedDrawer}
      setShowSelectedDrawer={setShowSelectedDrawer}
    />
  );
};

describe('DeviceSelectionStep accessible controls', () => {
  afterEach(() => cleanup());

  it('labels device filters and view controls and exposes the selected-device drawer state', () => {
    render(<SelectionHarness />);

    expect(screen.getByRole('textbox', { name: 'Search devices by IP or hostname' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Filter devices by vendor' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Grid view' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'List view' }).getAttribute('aria-pressed')).toBe('false');

    const selectedDevicesButton = screen.getByRole('button', { name: '1 selected' });
    expect(selectedDevicesButton.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(selectedDevicesButton);

    const drawer = screen.getByRole('region', { name: 'Selected Devices (1)' });
    expect(screen.getByRole('button', { name: 'Remove router-1' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close selected devices' }));
    expect(screen.queryByRole('region', { name: 'Selected Devices (1)' })).toBeNull();
    expect(drawer.isConnected).toBe(false);
    expect(document.activeElement).toBe(selectedDevicesButton);
  });

  it('closes the drawer when the final device is removed and keeps it closed for a later selection', async () => {
    render(<SelectionHarness />);

    fireEvent.click(screen.getByRole('button', { name: '1 selected' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove router-1' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Selected Devices (1)' })).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: /Select router-1/ }));
    const selectedDevicesButton = screen.getByRole('button', { name: '1 selected' });
    expect(selectedDevicesButton.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('region', { name: 'Selected Devices (1)' })).toBeNull();
  });

  it('dismisses the selected-device drawer with Escape and returns focus to its trigger', async () => {
    render(<SelectionHarness />);
    const trigger = screen.getByRole('button', { name: '1 selected' });
    fireEvent.click(trigger);

    expect(screen.getByRole('region', { name: 'Selected Devices (1)' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('region', { name: 'Selected Devices (1)' })).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });
});
