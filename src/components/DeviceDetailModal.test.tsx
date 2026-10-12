import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../types';
import { apiRequest } from '../api/http';
import DeviceDetailModal from './DeviceDetailModal';

vi.mock('../api/http', () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);

const profile = {
  id: 'h3c-v5',
  platform_code: 'h3c_comware_v5',
  vendor: 'H3C',
  catalog_vendor: 'h3c',
  platform_family: 'h3c_comware',
  version: 'v5',
  name_zh: 'Comware V5',
  name_en: 'Comware V5',
};

const device: Device = {
  id: 'device-1',
  hostname: 'edge-1',
  ip_address: '192.0.2.1',
  platform: 'h3c_comware',
  platform_profile_id: profile.id,
  platform_binding: profile,
  platform_locked: true,
  status: 'online',
  compliance: 'unknown',
  sn: 'serial-1',
  model: 'S6800',
  version: '7.1.064',
  role: 'access',
  site: 'lab',
  uptime: '',
  connection_method: 'ssh',
  config_history: [],
  vendor: 'h3c',
};

const renderModal = () => render(
  <DeviceDetailModal
    language="zh"
    t={(key) => key}
    viewingDevice={device}
    currentUserRole="Operator"
    viewingDeviceConnectionSummary={null}
    connectionTestingDeviceId={null}
    onClose={vi.fn()}
    onTestConnection={vi.fn()}
    isTestingConnection={false}
    onSnmpSyncNow={vi.fn()}
    snmpSyncingId={null}
    onPlatformBindingSaved={vi.fn()}
    onGoToAutomation={vi.fn()}
  />,
);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DeviceDetailModal platform binding permissions', () => {
  it('allows an unchanged existing binding to be saved idempotently for an Operator despite a version notice', async () => {
    mockedApiRequest.mockResolvedValue({ data: [profile] });
    renderModal();

    const versionSelect = await screen.findByLabelText('平台版本');
    await waitFor(() => expect((versionSelect as HTMLSelectElement).disabled).toBe(true));
    expect(screen.getByRole('alert').textContent).toContain('版本提示');

    const saveButton = screen.getByRole('button', { name: '保存绑定' });
    expect((saveButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(saveButton);

    await screen.findByText(/已绑定当前平台：Comware V5/);
    expect(mockedApiRequest).toHaveBeenCalledTimes(1);
    expect(mockedApiRequest).toHaveBeenCalledWith('/api/platform-registry/profiles');
  });
});
