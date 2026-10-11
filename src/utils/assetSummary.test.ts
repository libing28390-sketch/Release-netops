import { describe, expect, it } from 'vitest';
import { getManagedAssetDeviceTotal } from './assetSummary';

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
});
