import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RackVM } from '../types';
import { Rack3DContainer } from './index';

vi.mock('./utils/webgl', () => ({ isWebGLAvailable: () => true }));
vi.mock('./RackScene', () => ({
  RackScene: (props: { focusTarget?: { centerY: number } | null }) => (
    <div data-testid="rack-scene" data-focus={props.focusTarget?.centerY ?? ''} />
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ links: [], truncated: false }),
    }));
  });

  it('labels the view as read-only and delegates fullscreen to the workspace shell', async () => {
    const onToggleFullscreen = vi.fn();
    render(
      <Rack3DContainer
        rackVM={rackVM}
        selectedDeviceId={null}
        onSelectDevice={vi.fn()}
        onFallbackTo2D={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={onToggleFullscreen}
        zh
      />,
    );

    expect(screen.getByText('只读')).toBeTruthy();
    expect(screen.queryByText('安装')).toBeNull();
    fireEvent.click(screen.getByTitle('全屏显示'));
    expect(onToggleFullscreen).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/topology/links?limit=500&site_id=site-a',
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
});
