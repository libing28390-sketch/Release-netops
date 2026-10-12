import { describe, expect, it } from 'vitest';
import { RackSummary } from '../types';
import { buildRackFleetLayout } from './fleetLayout';

const makeRack = (index: number): RackSummary => ({
  id: `rack-${index}`,
  name: `R-${String(index).padStart(3, '0')}`,
  datacenter: 'DC-A',
  floor: `${Math.floor(index / 100) + 1}F`,
  room: `Room-${Math.floor(index / 50) + 1}`,
  row: String.fromCharCode(65 + (Math.floor(index / 20) % 20)),
  total_u: 42,
  description: '',
  status: 'active',
  created_at: '2026-08-28T00:00:00Z',
  updated_at: '2026-08-28T00:00:00Z',
  site_label: index % 2 === 0 ? 'DC-A' : 'DC-B',
  device_count: 8,
  front_used: 8,
  rear_used: 0,
  used_u: 8,
  available_u: 34,
  u_utilization_pct: 19,
  power_used_watts: 800,
  power_utilization_pct: 20,
  monitored_device_count: 8,
  healthy_device_count: 8,
  offline_device_count: 0,
  unknown_monitoring_device_count: 0,
  unlinked_asset_count: 0,
  unmonitored_device_count: 0,
  invalid_device_count: 0,
  health_status: 'healthy',
  data_quality_status: 'complete',
});

describe('buildRackFleetLayout', () => {
  it('creates deterministic inferred positions grouped by CMDB hierarchy', () => {
    const placements = buildRackFleetLayout([makeRack(2), makeRack(0), makeRack(1)]);

    expect(placements).toHaveLength(3);
    expect(placements.every(item => item.inferred)).toBe(true);
    expect(placements.map(item => item.instanceIndex)).toEqual([0, 1, 2]);
    expect(new Set(placements.map(item => item.position.join(','))).size).toBe(3);
    expect(placements[0].groupLabel).toContain('DC-A');
  });

  for (const size of [50, 100, 500]) {
    it(`builds ${size} summary instances within the lightweight layout budget`, () => {
      const racks = Array.from({ length: size }, (_, index) => makeRack(index));
      const startedAt = performance.now();
      const placements = buildRackFleetLayout(racks);
      const elapsedMs = performance.now() - startedAt;

      expect(placements).toHaveLength(size);
      expect(new Set(placements.map(item => item.rack.id)).size).toBe(size);
      expect(elapsedMs).toBeLessThan(1000);
    });
  }
});
