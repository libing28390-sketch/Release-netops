import { describe, expect, it } from 'vitest';
import { getDevicePlatformAdaptation, getPlatformProfileDisplayLabel } from './platformVersion';

describe('platform adaptation display', () => {
  it('renders a concrete binding name instead of the internal profile id', () => {
    expect(getPlatformProfileDisplayLabel(
      { id: 'system-profile-h3c_comware_v5', platform_code: '' },
      'system-profile-h3c_comware_v5',
      'zh',
    )).toBe('华三 Comware V5');
  });

  it('shows a default adaptation for legacy unbound H3C devices', () => {
    const result = getDevicePlatformAdaptation({ platform: 'h3c_comware', version: '7.1.064' }, 'zh');
    expect(result.explicit).toBe(false);
    expect(result.label).toBe('华三 Comware V7');
    expect(result.version).toBe('v7');
  });

  it('keeps explicit Ruijie profile metadata readable', () => {
    const result = getDevicePlatformAdaptation({
      platform: 'ruijie_rgos',
      version: 'EG_RGOS 11.9(6)B13P1',
      platform_profile_id: 'system-profile-ruijie_rgos_v11',
    }, 'zh');
    expect(result.explicit).toBe(true);
    expect(result.label).toBe('锐捷 RGOS V11');
    expect(result.version).toBe('v11');
  });
});
