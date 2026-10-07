import { describe, expect, it } from 'vitest';
import { getVendor, isAutomationPlatformSupported, normalizeAutomationPlatform } from './helpers';

describe('Huawei YunShan automation platform mapping', () => {
  it('normalizes documented aliases to the independent platform and Huawei vendor', () => {
    expect(['yunshan', 'yunshanos', 'YunShan OS', 'huawei_yunshan_os']
      .map(normalizeAutomationPlatform)).toEqual(Array(4).fill('huawei_yunshan'));
    expect(getVendor('huawei_yunshan')).toBe('Huawei');
  });

  it('does not treat a YunShan platform as a VRP scenario family', () => {
    expect(isAutomationPlatformSupported('huawei_yunshan', ['huawei_yunshan'])).toBe(true);
    expect(isAutomationPlatformSupported('huawei_yunshan', ['huawei_vrp'])).toBe(false);
  });
});
