import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../types';
import { apiRequest } from '../api/http';
import BatchPlatformBindingModal, {
  extractSoftwareMajorVersion,
  getProfileAdaptationMajorVersion,
} from './BatchPlatformBindingModal';

vi.mock('../api/http', () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);

const makeDevice = (version: string): Device => ({
  id: 'device-1',
  hostname: 'edge-1',
  ip_address: '192.0.2.1',
  platform: 'h3c_comware',
  status: 'online',
  compliance: 'unknown',
  sn: 'serial-1',
  model: 'S6800',
  version,
  role: 'access',
  site: 'lab',
  uptime: '',
  connection_method: 'ssh',
  config_history: [],
  vendor: 'h3c',
});

const profiles = [{
  id: 'h3c-v5',
  platform_code: 'h3c_comware_v5',
  vendor: 'H3C',
  catalog_vendor: 'h3c',
  platform_family: 'h3c_comware',
  version: 'v5',
  name_zh: 'Comware V5',
  name_en: 'Comware V5',
}];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('BatchPlatformBindingModal version guard', () => {
  it('extracts Comware and Ruijie software majors while ignoring unknown values', () => {
    expect(extractSoftwareMajorVersion('7.1.064')).toBe(7);
    expect(extractSoftwareMajorVersion('EG_RGOS 11.9(6)B13P1')).toBe(11);
    expect(extractSoftwareMajorVersion('5900 V6.00.04.20P01')).toBe(6);
    expect(extractSoftwareMajorVersion('ZSRV2 V3.00.30(1.2.9)')).toBe(3);
    expect(extractSoftwareMajorVersion('S211C011D007P08')).toBeNull();
    expect(extractSoftwareMajorVersion('unknown')).toBeNull();
    expect(extractSoftwareMajorVersion('common')).toBeNull();
    expect(extractSoftwareMajorVersion('')).toBeNull();
  });

  it('recognizes the target profile version as a command/parser adaptation version', () => {
    expect(getProfileAdaptationMajorVersion(profiles[0])).toBe(5);
  });

  it('disables binding when the device software major conflicts with the target profile', async () => {
    mockedApiRequest.mockResolvedValue({ data: profiles });
    render(
      <BatchPlatformBindingModal
        deviceIds={['device-1']}
        devices={[makeDevice('7.1.064')]}
        language="zh"
        onClose={vi.fn()}
        onCompleted={vi.fn()}
      />,
    );

    const vendor = await screen.findByLabelText('平台厂商');
    fireEvent.change(vendor, { target: { value: 'h3c' } });
    fireEvent.change(screen.getByLabelText('平台类型'), { target: { value: 'h3c_comware' } });
    fireEvent.change(screen.getByLabelText('平台版本'), { target: { value: 'v5' } });

    const conflict = await screen.findByRole('alert');
    expect(conflict.textContent).toContain('设备的软件主版本为 v7');
    expect(conflict.textContent).toContain('目标命令/解析适配版本为 v5');
    expect((screen.getAllByRole('button', { name: '新增绑定' })[1] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('此版本用于选择命令和解析模板，不代表设备当前运行的软件版本。')).toBeTruthy();
  });

  it('enables an explicit administrator override after confirmation', async () => {
    mockedApiRequest.mockResolvedValue({ data: profiles });
    render(
      <BatchPlatformBindingModal
        deviceIds={['device-1']}
        devices={[makeDevice('7.1.064')]}
        language="zh"
        onClose={vi.fn()}
        onCompleted={vi.fn()}
      />,
    );

    fireEvent.change(await screen.findByLabelText('平台厂商'), { target: { value: 'h3c' } });
    fireEvent.change(screen.getByLabelText('平台类型'), { target: { value: 'h3c_comware' } });
    fireEvent.change(screen.getByLabelText('平台版本'), { target: { value: 'v5' } });
    fireEvent.click(await screen.findByRole('checkbox'));

    await waitFor(() => expect((screen.getAllByRole('button', { name: '新增绑定' })[1] as HTMLButtonElement).disabled).toBe(false));
  });

  it('does not block when the device version is empty or unknown', async () => {
    mockedApiRequest.mockResolvedValue({ data: profiles });
    const { rerender } = render(
      <BatchPlatformBindingModal
        deviceIds={['device-1']}
        devices={[makeDevice('unknown')]}
        language="zh"
        onClose={vi.fn()}
        onCompleted={vi.fn()}
      />,
    );

    fireEvent.change(await screen.findByLabelText('平台厂商'), { target: { value: 'h3c' } });
    fireEvent.change(screen.getByLabelText('平台类型'), { target: { value: 'h3c_comware' } });
    fireEvent.change(screen.getByLabelText('平台版本'), { target: { value: 'v5' } });
    await waitFor(() => expect((screen.getAllByRole('button', { name: '新增绑定' })[1] as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByRole('alert')).toBeNull();

    rerender(
      <BatchPlatformBindingModal
        deviceIds={['device-1']}
        devices={[makeDevice('common')]}
        language="zh"
        onClose={vi.fn()}
        onCompleted={vi.fn()}
      />,
    );
    expect(extractSoftwareMajorVersion('common')).toBeNull();
  });
});
