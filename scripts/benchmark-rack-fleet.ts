import { performance } from 'node:perf_hooks';
import { buildRackFleetLayout } from '../src/pages/RackManagement/Rack3D/fleetLayout';
import type { RackSummary } from '../src/pages/RackManagement/types';

const SIZES = [50, 100, 500];
const ITERATIONS = 25;

function makeRack(index: number): RackSummary {
  return {
    id: `benchmark-rack-${index}`,
    name: `R-${String(index).padStart(3, '0')}`,
    datacenter: 'BENCHMARK',
    floor: `${Math.floor(index / 100) + 1}F`,
    room: `Room-${Math.floor(index / 50) + 1}`,
    row: String.fromCharCode(65 + (Math.floor(index / 20) % 20)),
    total_u: 42,
    description: '',
    status: 'active',
    created_at: '2026-08-28T00:00:00Z',
    updated_at: '2026-08-28T00:00:00Z',
    site_label: 'BENCHMARK',
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
    unlinked_asset_count: 0,
    unmonitored_device_count: 0,
    invalid_device_count: 0,
    health_status: 'healthy',
    data_quality_status: 'complete',
  };
}

function percentile(values: number[], fraction: number): number {
  const ordered = [...values].sort((left, right) => left - right);
  return ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * fraction))] || 0;
}

for (const size of SIZES) {
  const racks = Array.from({ length: size }, (_, index) => makeRack(index));
  const layoutTimes: number[] = [];
  let placements = buildRackFleetLayout(racks);

  for (let iteration = 0; iteration < ITERATIONS; iteration += 1) {
    const startedAt = performance.now();
    placements = buildRackFleetLayout(racks);
    layoutTimes.push(performance.now() - startedAt);
  }

  const switchTimes: number[] = [];
  for (let iteration = 0; iteration < ITERATIONS; iteration += 1) {
    const selectedId = racks[(iteration * 17) % racks.length].id;
    const startedAt = performance.now();
    placements.find(item => item.rack.id === selectedId);
    switchTimes.push(performance.now() - startedAt);
  }

  // The overview owns one instance matrix and one RGB color per summary.
  // This is the deterministic client-side GPU buffer budget; it excludes the
  // browser/renderer baseline and is intentionally reported separately.
  const instanceBufferBytes = size * 16 * Float32Array.BYTES_PER_ELEMENT;
  const colorBufferBytes = size * 3 * Float32Array.BYTES_PER_ELEMENT;
  const estimatedInstanceBytes = instanceBufferBytes + colorBufferBytes;

  console.log(JSON.stringify({
    size,
    overviewSummaryRequests: 1,
    layoutRequestsOnFirstScreen: 0,
    layoutRequestsOnSingleRackOpen: 1,
    layoutBuildMs: {
      median: Number(percentile(layoutTimes, 0.5).toFixed(3)),
      p95: Number(percentile(layoutTimes, 0.95).toFixed(3)),
    },
    summarySelectionSwitchMs: {
      median: Number(percentile(switchTimes, 0.5).toFixed(3)),
      p95: Number(percentile(switchTimes, 0.95).toFixed(3)),
    },
    estimatedInstancedMeshBufferBytes: estimatedInstanceBytes,
    fps: 'requires browser GPU pass; run the acceptance checklist on the target browser',
  }));
}
