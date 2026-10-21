import { describe, expect, it } from 'vitest';
import { getRackProfile, inferRackProfile } from './rackProfiles';

const device = (role: string, model = '') => ({ role, model, vendor: '' });

describe('rack purpose profiles', () => {
  it('classifies an all-switch network cabinet as high-density switching', () => {
    const profile = inferRackProfile([
      device('switch', 'S6800'),
      device('switch', 'S6800'),
      device('switch', 'S6850'),
      device('firewall', 'F1090'),
    ]);

    expect(profile.id).toBe('network-high-density');
    expect(profile.category).toBe('network');
  });

  it('keeps a mostly passive cabling cabinet distinct from a network cabinet', () => {
    const profile = inferRackProfile([
      device('patch_panel', 'Cat6 24P'),
      device('patch_panel', 'LC 48P'),
      device('cabling', 'horizontal manager'),
      device('switch', 'access'),
    ]);

    expect(profile.id).toBe('cabling');
  });

  it('exposes the complete reusable profile catalog', () => {
    expect(getRackProfile('network-high-density').recommendedLayoutZh).toHaveLength(3);
    expect(getRackProfile('power-ups').labelZh).toContain('UPS');
  });
});
