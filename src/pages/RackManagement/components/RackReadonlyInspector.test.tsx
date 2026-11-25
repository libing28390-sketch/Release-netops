import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RackDeviceVM } from '../types';
import { RackReadonlyInspector } from './RackReadonlyInspector';

vi.mock('./DevicePortMatrix', () => ({
  DevicePortMatrix: () => <div data-testid="device-port-matrix" />,
}));

const baseDevice: RackDeviceVM = {
  id: 'rd-1',
  rackId: 'rack-1',
  name: 'S6850-6',
  assetId: 'asset-f934d4235347',
  assetTag: 'NET-BJ-009',
  networkDeviceId: 'a54b5da5-75c6-45ef-87a7-dd4b180098f9',
  networkHostname: 'S6850-6',
  networkIp: '10.254.0.6',
  deviceTypeId: 'dt-1',
  vendor: 'H3C',
  model: 'S6850',
  role: 'switch',
  startU: 9,
  heightU: 1,
  endU: 9,
  startKnown: true,
  heightKnown: true,
  face: 'front',
  mountKind: 'u_mount',
  position: 'front',
  placementStatus: 'estimated',
  renderable: true,
  isFullDepth: true,
  serialNumber: 'ID8e44477c0600',
  lifecycleStatus: 'active',
  healthStatus: 'healthy',
  metrics: { ratedPowerWatts: 200, powerSource: 'RATED' },
  dataQuality: { valid: true, issues: [] },
  coordinates: { centerY: 4, height: 0.44, depth: 7.5, centerZ: 0, width: 4.78 },
};

describe('RackReadonlyInspector', () => {
  afterEach(() => cleanup());

  it('displays human-readable monitoring target, asset tag, and localized placement status instead of raw UUIDs', () => {
    render(<RackReadonlyInspector device={baseDevice} zh />);

    expect(screen.getByText('S6850-6 · 10.254.0.6')).toBeTruthy();
    expect(screen.getByText('NET-BJ-009')).toBeTruthy();
    expect(screen.getByText('估算')).toBeTruthy();
    expect(screen.queryByText('a54b5da5-75c6-45ef-87a7-dd4b180098f9')).toBeNull();
    expect(screen.queryByText('asset-f934d4235347')).toBeNull();
  });

  it('shows linked fallback without exposing raw UUID when hostname/IP are absent', () => {
    render(
      <RackReadonlyInspector
        device={{ ...baseDevice, networkHostname: undefined, networkIp: undefined }}
        zh
      />,
    );

    expect(screen.getByText('已关联监控')).toBeTruthy();
    expect(screen.queryByText('a54b5da5-75c6-45ef-87a7-dd4b180098f9')).toBeNull();
  });
});
