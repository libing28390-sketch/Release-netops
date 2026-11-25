import { describe, expect, it } from 'vitest';
import { RackSummary } from '../types';
import {
  buildDataCenterRoomModel,
  buildRackFleetLayout,
  computeRackPowerMetrics,
  computeRackThermalMetrics,
} from './fleetLayout';

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

  it('derives complete datacenter room infrastructure (trays, CRAC, PDF, UPS) from placements', () => {
    const racks = [makeRack(0), makeRack(1), makeRack(2), makeRack(20), makeRack(21)];
    const placements = buildRackFleetLayout(racks);
    const room = buildDataCenterRoomModel(placements);

    expect(room.rows.length).toBeGreaterThanOrEqual(2);
    expect(room.cracUnits.length).toBeGreaterThanOrEqual(room.rows.length + 2);
    expect(room.pdfCabinets).toHaveLength(room.rows.length);
    expect(room.upsUnits).toHaveLength(2);
    expect(room.odfUnits.length).toBeGreaterThanOrEqual(1);
    expect(room.zones.some(z => z.kind === 'odf')).toBe(true);
    expect(room.zones.some(z => z.kind === 'core_network')).toBe(true);
    expect(room.trays.some(t => t.kind === 'fiber')).toBe(true);
    expect(room.trays.some(t => t.kind === 'power')).toBe(true);
    expect(room.totals.rackCount).toBe(5);
    expect(room.totals.totalPowerKw).toBeCloseTo(4, 1);
  });

  it('computes distinct power and thermal metrics for active vs empty racks', () => {
    const emptyRack = { ...makeRack(1), power_used_watts: 0, power_utilization_pct: null };
    const activeRack = { ...makeRack(2), power_used_watts: 1800, power_utilization_pct: null };
    const hotRack = { ...makeRack(3), power_used_watts: 4800, power_utilization_pct: 80 };

    expect(computeRackPowerMetrics(emptyRack).tier).toBe('idle');
    expect(computeRackPowerMetrics(activeRack).utilizationPct).toBe(30);
    expect(computeRackPowerMetrics(hotRack).tier).toBe('critical');

    expect(computeRackThermalMetrics(emptyRack).tier).toBe('cold');
    expect(computeRackThermalMetrics(activeRack).exhaustC).toBeGreaterThan(30);
    expect(computeRackThermalMetrics(activeRack).tier).toBe('warm');
    expect(computeRackThermalMetrics(hotRack).tier).toBe('critical');
  });

  it('aligns IT rows, KEBOS UPS, CRAC-W, and ODF into GB 50174-2017 parallel rows with >=300mm tray separation', () => {
    const racks = [makeRack(0), makeRack(2), makeRack(20), makeRack(22)];
    const placements = buildRackFleetLayout(racks);
    const room = buildDataCenterRoomModel(placements);

    // Tight flush in-row cabinet pitch (0.84m) instead of scattered wide gaps
    const row0 = room.rows[0].placements;
    expect(Math.abs(row0[1].position[0] - row0[0].position[0])).toBeCloseTo(0.84, 2);

    // Paired IT rows face each other across a unified 1.20m enclosed cold aisle (GB 50174-2017)
    expect(room.rows[0].facing).toBe(1);
    expect(room.rows[1].facing).toBe(-1);
    expect(room.coldAisles).toHaveLength(1);
    expect(room.coldAisles[0].width).toBeCloseTo(1.2, 2);

    // UPS, Battery Banks & ODF stand in a parallel front-facing infrastructure row (rotationY === 0) with flush front doors
    expect(room.upsUnits.every(u => u.rotationY === 0 && u.label.includes('KEBOS'))).toBe(true);
    expect(room.batteryUnits).toHaveLength(2);
    expect(room.batteryUnits.every(b => b.rotationY === 0 && b.label.includes('BATT'))).toBe(true);
    expect(room.odfUnits.every(o => o.rotationY === 0)).toBe(true);
    const upsFrontZ = room.upsUnits[0].position[2] + room.upsUnits[0].depth / 2;
    const battFrontZ = room.batteryUnits[0].position[2] + room.batteryUnits[0].depth / 2;
    const odfFrontZ = room.odfUnits[0].position[2] + room.odfUnits[0].depth / 2;
    expect(battFrontZ).toBeCloseTo(upsFrontZ, 2);
    expect(odfFrontZ).toBeCloseTo(upsFrontZ, 2);

    // Overhead weak-current fiber tray sits >= 0.30m above strong-current power tray (GB 50462-2015)
    // and In-Row CRAC height clears overhead power tray cleanly without collision
    const fiberY = room.trays.find(t => t.kind === 'fiber')!.start[1];
    const powerY = room.trays.find(t => t.kind === 'power')!.start[1];
    expect(fiberY - powerY).toBeGreaterThanOrEqual(0.3);
    const inRowCracs = room.cracUnits.filter(c => c.cracRole === 'inrow');
    const perimeterCracs = room.cracUnits.filter(c => c.cracRole === 'perimeter');
    expect(inRowCracs.length).toBeGreaterThanOrEqual(2);
    expect(perimeterCracs.length).toBeGreaterThanOrEqual(2);
    expect(inRowCracs.every(c => c.position[1] + c.height / 2 < powerY)).toBe(true);
  });

  it('binds real CMDB ODF frames into the 3D ODF bank while keeping flush Z-datum alignment', () => {
    const racks = [makeRack(0), makeRack(2)];
    const placements = buildRackFleetLayout(racks);
    const room = buildDataCenterRoomModel(placements, [
      {
        id: 'odf-cmdb-1',
        frame_code: 'WH-ODF-01',
        name: 'ODF-01 核心光配',
        vendor: 'Huawei',
        model: 'GPX147-576',
        site_label: 'WH-DC-01',
        room: 'A1机房',
        tray_count: 12,
        ports_per_tray: 48,
        total_cores: 576,
        occupied_cores: 24,
        reserved_cores: 4,
        fault_cores: 0,
        utilization_pct: 4.2,
        connector_type: 'LC/UPC',
        fiber_mode: 'mixed',
        trays: [
          { id: 't1', tray_no: 1, tray_code: 'A01', label: '核心上联', port_count: 48, fiber_mode: 'OS2', occupied_count: 24, reserved_count: 4, fault_count: 0 },
        ],
      },
    ]);

    expect(room.odfUnits).toHaveLength(1);
    expect(room.odfUnits[0].id).toBe('odf-cmdb-1');
    expect(room.odfUnits[0].isPlaceholder).toBe(false);
    expect(room.odfUnits[0].odfFrame?.occupied_cores).toBe(24);
    expect(room.odfUnits[0].sublabel).toContain('24/576芯');
    const upsFrontZ = room.upsUnits[0].position[2] + room.upsUnits[0].depth / 2;
    const odfFrontZ = room.odfUnits[0].position[2] + room.odfUnits[0].depth / 2;
    expect(odfFrontZ).toBeCloseTo(upsFrontZ, 2);
  });

  it('builds a collision-free GB 50174 Dual-Pod hall for 100 racks with external spines and scaled UPS/CRAC', () => {
    const racks100 = Array.from({ length: 100 }, (_, i) => ({
      ...makeRack(i * 2),
      id: `rack-100-${i}`,
      name: i < 20 ? `CORE-${i}` : i < 64 ? `SRV-${i}` : i < 82 ? `FW-${i}` : `GEN-${i}`,
      site_label: 'DC-A',
      row: String.fromCharCode(65 + Math.floor(i / 10)),
      power_used_watts: 2600,
    }));

    const placements = buildRackFleetLayout(racks100);
    const room = buildDataCenterRoomModel(placements);

    expect(placements).toHaveLength(100);
    // Activates symmetric Dual-Pod ("田字形") with >= 1.75m central walkway
    const leftRows = room.rows.filter(r => r.podSide === 'left');
    const rightRows = room.rows.filter(r => r.podSide === 'right');
    expect(leftRows.length).toBeGreaterThanOrEqual(4);
    expect(rightRows.length).toBeGreaterThanOrEqual(4);
    const leftMaxX = Math.max(...leftRows.map(r => r.xMax));
    const rightMinX = Math.min(...rightRows.map(r => r.xMin));
    expect(rightMinX - leftMaxX).toBeGreaterThanOrEqual(1.75);

    // Every single row length <= 15m per GB 50174-2017 §4.2.2
    expect(room.rows.every(r => r.spanX <= 15.0)).toBe(true);

    // Zero bounding-box collisions among all racks and infrastructure cabinets
    const boxes = [
      ...placements.map(p => ({
        id: p.rack.id,
        minX: p.position[0] - 0.41,
        maxX: p.position[0] + 0.41,
        minZ: p.position[2] - 0.48,
        maxZ: p.position[2] + 0.48,
      })),
      ...[...room.cracUnits, ...room.pdfCabinets, ...room.upsUnits, ...room.batteryUnits, ...room.odfUnits].map(u => ({
        id: u.id,
        minX: u.position[0] - u.width / 2,
        maxX: u.position[0] + u.width / 2,
        minZ: u.position[2] - u.depth / 2,
        maxZ: u.position[2] + u.depth / 2,
      })),
    ];
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const ox = Math.min(boxes[i].maxX, boxes[j].maxX) - Math.max(boxes[i].minX, boxes[j].minX);
        const oz = Math.min(boxes[i].maxZ, boxes[j].maxZ) - Math.max(boxes[i].minZ, boxes[j].minZ);
        expect(ox > 0.005 && oz > 0.005).toBe(false);
      }
    }

    // Zero cold-aisle collisions
    room.coldAisles.forEach(a => {
      const aMinX = a.centerX - a.spanX / 2;
      const aMaxX = a.centerX + a.spanX / 2;
      const aMinZ = a.z - a.width / 2;
      const aMaxZ = a.z + a.width / 2;
      boxes.forEach(b => {
        const ox = Math.min(aMaxX, b.maxX) - Math.max(aMinX, b.minX);
        const oz = Math.min(aMaxZ, b.maxZ) - Math.max(aMinZ, b.minZ);
        expect(ox > 0.02 && oz > 0.02).toBe(false);
      });
    });

    // Overhead power & fiber spines stay strictly external to all IT rows
    const maxItX = Math.max(...room.rows.map(r => r.xMax));
    const minItX = Math.min(...room.rows.map(r => r.xMin));
    const fiberSpine = room.trays.find(t => t.id === 'tray-fiber-spine')!;
    const powerSpine = room.trays.find(t => t.id === 'tray-power-spine')!;
    expect(fiberSpine.start[0]).toBeGreaterThan(maxItX);
    expect(powerSpine.start[0]).toBeLessThan(minItX);

    // 260 kW hall scales UPS >= 3 units and perimeter CRAC-W >= 4 units
    expect(room.upsUnits.length).toBeGreaterThanOrEqual(3);
    expect(room.cracUnits.filter(c => c.cracRole === 'perimeter').length).toBeGreaterThanOrEqual(4);
  });
});
