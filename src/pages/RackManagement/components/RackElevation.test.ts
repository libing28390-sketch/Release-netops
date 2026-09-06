import { describe, expect, it } from 'vitest';
import { isStandardElevationPlacement } from './RackElevation';
import { RackDevice } from '../types';

function device(overrides: Partial<RackDevice>): RackDevice {
  return {
    id: 'device-1',
    name: 'device-1',
    rack_id: 'rack-1',
    device_type_id: 'type-1',
    start_u: 10,
    position: 'front',
    status: 'active',
    serial_number: '',
    asset_id: '',
    model: '',
    vendor: '',
    u_height: 1,
    device_role: 'switch',
    is_full_depth: 0,
    ...overrides,
  };
}

describe('RackElevation occupancy eligibility', () => {
  it('keeps unknown and invalid U rows out of occupancy while retaining valid U rows', () => {
    expect(isStandardElevationPlacement(device({ placement_status: 'confirmed' }))).toBe(true);
    expect(isStandardElevationPlacement(device({ placement_status: 'estimated' }))).toBe(true);
    expect(isStandardElevationPlacement(device({ placement_status: 'unknown' }))).toBe(false);
    expect(isStandardElevationPlacement(device({ placement_status: 'invalid' }))).toBe(false);
  });

  it('does not coerce non-U rows into a standard U slot', () => {
    expect(isStandardElevationPlacement(device({ mount_kind: 'zero_u', start_u: null, position: 'rear' }))).toBe(false);
    expect(isStandardElevationPlacement(device({ mount_kind: 'side_mount', start_u: null, position: 'left_side' }))).toBe(false);
  });
});

