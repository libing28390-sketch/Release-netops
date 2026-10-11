import { describe, expect, it } from 'vitest';
import { getManagedAssetDeviceOnlineTotal, getManagedAssetDeviceTotal } from './assetSummary';

describe('getManagedAssetDeviceTotal', () => {
  it('uses the same network-device plus server scope as Asset Management', () => {
    expect(getManagedAssetDeviceTotal({
      total: 17,
      by_type: { network_device: 6, server: 4, other: 7 },
    })).toBe(10);
  });

  it('preserves a valid zero count', () => {
    expect(getManagedAssetDeviceTotal({
      total: 0,
      by_type: { network_device: 0, server: 0 },
    })).toBe(0);
  });

  it('rejects malformed summary data instead of displaying a misleading zero', () => {
    expect(getManagedAssetDeviceTotal({ total: 12 })).toBeNull();
    expect(getManagedAssetDeviceTotal({ by_type: { network_device: 3, server: -1 } })).toBeNull();
  });

  it('reads the online count from the same asset summary scope', () => {
    expect(getManagedAssetDeviceOnlineTotal({
      by_online_status: { online: 3, offline: 8, pending: 2 },
    })).toBe(3);
    expect(getManagedAssetDeviceOnlineTotal({ by_online_status: { online: 0 } })).toBe(0);
    expect(getManagedAssetDeviceOnlineTotal({ by_online_status: { online: '3' } })).toBeNull();
  });
});
