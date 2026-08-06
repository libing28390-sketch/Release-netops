import { describe, expect, it } from 'vitest';
import {
  ALL_VENDOR_NAMES,
  IMPORT_VALUE_MAP,
  NETWORK_IMPORT_PLATFORM_VALUES,
  NETWORK_IMPORT_VENDOR_VALUES,
  NETWORK_VENDOR_GROUPS,
  VENDOR_PLATFORMS,
} from './constants';

describe('asset vendor catalog', () => {
  it('contains network and security vendor groups used by asset forms', () => {
    expect(NETWORK_VENDOR_GROUPS.map((group) => group.key)).toEqual(['network', 'security']);
    expect(ALL_VENDOR_NAMES).toContain('FiberHome');
    expect(ALL_VENDOR_NAMES).toContain('Hillstone');
    expect(ALL_VENDOR_NAMES).toContain('Sangfor');
    expect(ALL_VENDOR_NAMES).toContain('Check Point');
    expect(NETWORK_IMPORT_VENDOR_VALUES).toContain('山石');
    expect(NETWORK_IMPORT_VENDOR_VALUES).toContain('Hillstone');
  });

  it('provides a platform identity for the newly catalogued vendors', () => {
    expect(VENDOR_PLATFORMS.DCN[0].value).toBe('dcn_network');
    expect(VENDOR_PLATFORMS.FiberHome[0].value).toBe('fiberhome_fengine');
    expect(VENDOR_PLATFORMS.Hillstone[0].value).toBe('hillstone_stoneos');
    expect(VENDOR_PLATFORMS['Qi An Xin'][0].value).toBe('qianxin_firewall');
    expect(NETWORK_IMPORT_PLATFORM_VALUES).toContain('hillstone_stoneos');
    expect(IMPORT_VALUE_MAP.vendor['山石']).toBe('Hillstone');
    expect(IMPORT_VALUE_MAP.platform['Hillstone StoneOS']).toBe('hillstone_stoneos');
  });
});
