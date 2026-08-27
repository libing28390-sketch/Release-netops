import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RackVM } from '../types';
import { Rack3DContainer } from './index';

const { mockIsWebGLAvailable } = vi.hoisted(() => ({ mockIsWebGLAvailable: vi.fn() }));

vi.mock('./utils/webgl', () => ({ isWebGLAvailable: mockIsWebGLAvailable }));
vi.mock('./RackScene', () => ({
  RackScene: (props: { focusTarget?: { centerY: number } | null; selectedDeviceId?: string | null }) => (
    <div
      data-testid="rack-scene"
      data-focus={props.focusTarget?.centerY ?? ''}
      data-selected={props.selectedDeviceId || ''}
    />
  ),
}));
vi.mock('./RackDeviceTooltip', () => ({ RackDeviceTooltip: () => <div data-testid="device-tooltip" /> }));

const rackVM: RackVM = {
  id: 'rack-1',
  name: 'A-01',
  siteId: 'site-a',
  siteLabel: 'DC-A',
  floor: '3F',
  room: '301',
  row: 'A',
  totalU: 42,
  widthMm: 600,
  depthMm: 1000,
  heightMm: 1867,
  usedU: 1,
  availableU: 41,
  ratedPowerTotalWatts: 200,
  dataQuality: { valid: true, issues: [] },
  devices: [
    {
      id: 'rack-device-1',
      rackId: 'rack-1',
      name: 'SW-CORE-01',
      assetId: 'asset-1',
      networkDeviceId: 'network-device-1',
      deviceTypeId: 'type-1',
      vendor: 'H3C',
      model: 'S6850',
      role: 'switch',
      startU: 40,
      heightU: 1,
      endU: 40,
      face: 'front',
      isFullDepth: true,
      serialNumber: 'SN-1',
      lifecycleStatus: 'active',
      healthStatus: 'healthy',
      metrics: { ratedPowerWatts: 200, powerSource: 'RATED' },
      dataQuality: { valid: true, issues: [] },
      coordinates: { centerY: 17.56, height: 0.42, depth: 7.5, centerZ: 0, width: 4.78 },
    },
  ],
  validDevices: [],
  invalidDevices: [],
};
rackVM.validDevices = rackVM.devices;

describe('Rack3DContainer read-only workbench', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.restoreAllMocks();
    mockIsWebGLAvailable.mockReset();
    mockIsWebGLAvailable.mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ links: [], truncated: false }),
    }));
  });

  it('labels the view as read-only and delegates fullscreen to the workspace shell', async () => {
    const onToggleFullscreen = vi.fn();
    const onFallbackTo2D = vi.fn();
    render(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId={null}
        onSelectDevice={vi.fn()}
        onFallbackTo2D={onFallbackTo2D}
        isFullscreen={false}
        onToggleFullscreen={onToggleFullscreen}
        zh
      />,
    );

    expect(screen.getByText('只读')).toBeTruthy();
    expect(screen.queryByText('安装')).toBeNull();
    fireEvent.click(screen.getByTitle('全屏显示'));
    expect(onToggleFullscreen).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('在 2D 中查看'));
    expect(onFallbackTo2D).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/topology/links?limit=500&rack_id=rack-1&site_id=site-a',
      expect.any(Object),
    ));
  });

  it('focuses the scene when selection comes from the list or search', async () => {
    const onSelectDevice = vi.fn();
    const { rerender } = render(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId={null}
        onSelectDevice={onSelectDevice}
        onFallbackTo2D={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
        zh
      />,
    );

    fireEvent.change(screen.getByPlaceholderText('搜索设备...'), { target: { value: 'core' } });
    fireEvent.click(screen.getByText('SW-CORE-01'));
    expect(onSelectDevice).toHaveBeenCalledWith('rack-device-1');

    rerender(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId="rack-device-1"
        onSelectDevice={onSelectDevice}
        onFallbackTo2D={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
        zh
      />,
    );

    await waitFor(() => expect(screen.getByTestId('rack-scene').getAttribute('data-focus')).toBe('17.56'));
  });

  it('preserves view and layer state while fullscreen status changes', () => {
    const props = {
      rackVM,
      selectedDeviceId: 'rack-device-1',
      onSelectDevice: vi.fn(),
      onFallbackTo2D: vi.fn(),
      onToggleFullscreen: vi.fn(),
      zh: true,
    };
    const { rerender } = render(<Rack3DContainer {...props} isFullscreen={false} />);

    fireEvent.click(screen.getByTitle('背面视角（电源与风扇）'));
    fireEvent.click(screen.getByText('更多图层'));
    fireEvent.click(screen.getByTitle('显示全部走线'));

    rerender(<Rack3DContainer {...props} isFullscreen />);
    expect(screen.getByTitle('背面视角（电源与风扇）').className).toContain('bg-cyan-600');
    expect(screen.getByTitle('显示全部走线').className).toContain('bg-cyan-600');

    rerender(<Rack3DContainer {...props} isFullscreen={false} />);
    expect(screen.getByTitle('背面视角（电源与风扇）').className).toContain('bg-cyan-600');
    expect(screen.getByTitle('显示全部走线').className).toContain('bg-cyan-600');
    expect(screen.getByTestId('rack-scene').getAttribute('data-selected')).toBe('rack-device-1');
  });

  it('keeps secondary layers behind a compact menu', () => {
    render(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId={null}
        onSelectDevice={vi.fn()}
        onFallbackTo2D={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
        zh
      />,
    );

    expect(screen.queryByTitle('显示全部走线')).toBeNull();
    fireEvent.click(screen.getByText('更多图层'));
    expect(screen.getByTitle('显示全部走线')).toBeTruthy();
    expect(screen.getByText('门体显示')).toBeTruthy();
    expect(screen.getByText('U 标尺')).toBeTruthy();
  });

  it('falls back to 2D when WebGL is unavailable', async () => {
    mockIsWebGLAvailable.mockReturnValue(false);
    const onFallbackTo2D = vi.fn();
    render(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId={null}
        onSelectDevice={vi.fn()}
        onFallbackTo2D={onFallbackTo2D}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
        zh
      />,
    );

    await waitFor(() => expect(screen.getByText('当前浏览器或环境不支持 WebGL 硬件加速')).toBeTruthy());
    fireEvent.click(screen.getByText('返回 2D 视图'));
    expect(onFallbackTo2D).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('rack-scene')).toBeNull();
  });

  it('explains topology failures and retries the request', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ links: [], truncated: false }),
      });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId={null}
        onSelectDevice={vi.fn()}
        onFallbackTo2D={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
        zh
      />,
    );

    await waitFor(() => expect(screen.getByText('拓扑不可用')).toBeTruthy());
    fireEvent.click(screen.getByTitle('重新请求拓扑数据'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('无已验证链路')).toBeTruthy());
  });
});
