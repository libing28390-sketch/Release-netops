import { describe, expect, it } from 'vitest';
import { inferPlatformVendor, platformVendorLabel } from './platformVendor';

describe('YunShan platform vendor mapping', () => {
  it('recognizes YunShan codes and names as Huawei', () => {
    expect(inferPlatformVendor('huawei_yunshan')).toBe('huawei');
    expect(inferPlatformVendor('YunShan OS')).toBe('huawei');
    expect(inferPlatformVendor('yunshanos')).toBe('huawei');
    expect(platformVendorLabel('huawei', 'zh')).toBe('华为');
  });
});
