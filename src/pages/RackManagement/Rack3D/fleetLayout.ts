import { RackSummary } from '../types';

export type DataCenterZoneKind =
  | 'core_network'
  | 'compute'
  | 'security'
  | 'odf'
  | 'power_cooling'
  | 'general';

export type RackCabinetArchetype = 'standard' | 'chassis_core' | 'server' | 'odf';

export type PodSide = 'center' | 'left' | 'right';

export interface RackFleetPlacement {
  rack: RackSummary;
  instanceIndex: number;
  groupKey: string;
  groupLabel: string;
  zoneKind: DataCenterZoneKind;
  archetype: RackCabinetArchetype;
  /** +1 faces +Z (front toward +Z cold aisle), -1 faces -Z (face-to-face cold aisle per GB 50174-2017) */
  facing: 1 | -1;
  podSide?: PodSide;
  inferred: true;
  position: [number, number, number];
}

export interface DataCenterColdAisleModel {
  id: string;
  label: string;
  z: number;
  width: number;
  centerX: number;
  spanX: number;
  enclosed: boolean;
}

export interface DataCenterRowModel {
  id: string;
  label: string;
  zoneKind: DataCenterZoneKind;
  z: number;
  xMin: number;
  xMax: number;
  centerX: number;
  spanX: number;
  rackCount: number;
  totalPowerW: number;
  usedU: number;
  totalU: number;
  /** +1 faces +Z (default front), -1 faces -Z */
  facing: 1 | -1;
  podSide?: PodSide;
  placements: RackFleetPlacement[];
}

export interface OdfTrayRoomSummary {
  id: string;
  tray_no: number;
  tray_code: string;
  label?: string;
  port_count: number;
  fiber_mode: string;
  connector_type?: string;
  occupied_count: number;
  reserved_count: number;
  fault_count: number;
}

export interface OdfFrameRoomInput {
  id: string;
  frame_code: string;
  name: string;
  vendor?: string;
  model?: string;
  site_label?: string;
  room?: string;
  row?: string;
  tray_count: number;
  ports_per_tray: number;
  total_cores: number;
  occupied_cores: number;
  reserved_cores: number;
  fault_cores: number;
  idle_cores?: number;
  utilization_pct: number;
  connector_type?: string;
  fiber_mode?: string;
  status?: string;
  trays?: OdfTrayRoomSummary[];
}

export interface DataCenterEquipmentPlacement {
  id: string;
  label: string;
  sublabel: string;
  kind: 'crac' | 'pdf' | 'ups' | 'battery' | 'odf';
  cracRole?: 'inrow' | 'perimeter';
  position: [number, number, number];
  rotationY: number;
  width: number;
  height: number;
  depth: number;
  loadKw?: number;
  supplyTempC?: number;
  fiberCores?: number;
  odfFrame?: OdfFrameRoomInput | null;
  isPlaceholder?: boolean;
}

export interface DataCenterZoneModel {
  id: string;
  kind: DataCenterZoneKind;
  labelZh: string;
  labelEn: string;
  accentColor: string;
  rackCount: number;
  bounds: {
    minX: number;
    maxX: number;
    minZ: number;
    maxZ: number;
    centerX: number;
    centerZ: number;
    width: number;
    depth: number;
  };
}

export interface DataCenterTraySegment {
  id: string;
  kind: 'fiber' | 'power';
  start: [number, number, number];
  end: [number, number, number];
  width: number;
}

export interface DataCenterRoomModel {
  rows: DataCenterRowModel[];
  coldAisles: DataCenterColdAisleModel[];
  zones: DataCenterZoneModel[];
  cracUnits: DataCenterEquipmentPlacement[];
  pdfCabinets: DataCenterEquipmentPlacement[];
  upsUnits: DataCenterEquipmentPlacement[];
  batteryUnits: DataCenterEquipmentPlacement[];
  odfUnits: DataCenterEquipmentPlacement[];
  trays: DataCenterTraySegment[];
  bounds: {
    minX: number;
    maxX: number;
    minZ: number;
    maxZ: number;
    width: number;
    depth: number;
    centerX: number;
    centerZ: number;
    ceilingY: number;
  };
  totals: {
    rackCount: number;
    totalPowerKw: number;
    cracCount: number;
    pdfCount: number;
    odfCount: number;
    avgUtilizationPct: number;
    peakPowerRackName: string;
    peakPowerKw: number;
    hottestRackName: string;
    hottestTempC: number;
  };
}

export interface RackPowerMetrics {
  watts: number;
  kw: number;
  capacityWatts: number;
  utilizationPct: number;
  color: string;
  tier: 'idle' | 'low' | 'normal' | 'high' | 'critical';
}

export interface RackThermalMetrics {
  watts: number;
  supplyC: number;
  exhaustC: number;
  exhaustTempC: number;
  deltaT: number;
  plumeIntensity: number;
  color: string;
  tier: 'cold' | 'cool' | 'warm' | 'hot' | 'critical';
}

export const ZONE_META: Record<DataCenterZoneKind, { zh: string; en: string; color: string; order: number }> = {
  core_network: { zh: '核心网络区', en: 'Core Network', color: '#0ea5e9', order: 1 },
  security: { zh: '安全边界区', en: 'Security Zone', color: '#f43f5e', order: 2 },
  compute: { zh: '算力服务器区', en: 'Compute Zone', color: '#10b981', order: 3 },
  odf: { zh: 'ODF 光配区', en: 'ODF Zone', color: '#eab308', order: 4 },
  power_cooling: { zh: '供配电/制冷区', en: 'Power & Cooling', color: '#818cf8', order: 5 },
  general: { zh: '综合机柜区', en: 'General Racks', color: '#38bdf8', order: 6 },
};

export function inferRackZoneKind(rack: RackSummary): DataCenterZoneKind {
  const hay = [
    rack.cooling_zone,
    rack.room,
    rack.row,
    rack.name,
    rack.description,
    rack.remarks,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  if (/(odf|光配|配线架|光纤配线|mdf|patch)/.test(hay)) return 'odf';
  if (/(安全|防火墙|dmz|sec|firewall|waf|bastion)/.test(hay)) return 'security';
  if (/(算力|服务器|计算|存储|gpu|compute|server|storage|cloud|db|大数据)/.test(hay)) return 'compute';
  if (/(核心|路由|骨干|交换|网络|core|spine|router|switch|net|ne40|n610|s6850|ce128)/.test(hay)) return 'core_network';
  // Active network-heavy cabinets default to Core Network when in a network room
  if ((rack.device_count || 0) > 0) return 'core_network';
  return 'core_network';
}

export function inferRackArchetype(rack: RackSummary, zoneKind: DataCenterZoneKind): RackCabinetArchetype {
  if (zoneKind === 'odf') return 'odf';
  const hay = [rack.name, rack.description, rack.remarks, rack.cooling_zone]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  if (/(odf|光配|配线架)/.test(hay)) return 'odf';
  if (/(ne40|ne5000|n610|s10500|c9407|ce128|n18000|框式|核心路由|spine|chassis)/.test(hay)) return 'chassis_core';
  if (zoneKind === 'compute' || /(srv|server|算力|计算|存储|gpu)/.test(hay)) return 'server';
  // High-power dense network cabinets (>=3.5 kW or >=18U) render as modular core chassis silhouette
  if ((rack.power_used_watts || 0) >= 3500 || (rack.used_u || 0) >= 18) return 'chassis_core';
  return 'standard';
}

export function computeRackPowerMetrics(rack: RackSummary): RackPowerMetrics {
  const watts = Math.max(0, Number(rack.power_used_watts) || 0);
  const kw = Number((watts / 1000).toFixed(2));
  const configuredCap = Math.max(0, Number(rack.power_capacity_watts || rack.power_capacity_w || 0));
  const capacityWatts = configuredCap > 0 ? configuredCap : 6000;
  const utilizationPct = rack.power_utilization_pct != null && Number.isFinite(rack.power_utilization_pct)
    ? Math.max(0, Math.min(100, Math.round(rack.power_utilization_pct)))
    : Math.max(0, Math.min(100, Math.round((watts / capacityWatts) * 100)));

  if (watts <= 0) {
    return { watts, kw, capacityWatts, utilizationPct: 0, color: '#334155', tier: 'idle' };
  }
  if (utilizationPct >= 80) {
    return { watts, kw, capacityWatts, utilizationPct, color: '#ef4444', tier: 'critical' };
  }
  if (utilizationPct >= 60) {
    return { watts, kw, capacityWatts, utilizationPct, color: '#f59e0b', tier: 'high' };
  }
  if (utilizationPct >= 35) {
    return { watts, kw, capacityWatts, utilizationPct, color: '#10b981', tier: 'normal' };
  }
  return { watts, kw, capacityWatts, utilizationPct, color: '#38bdf8', tier: 'low' };
}

export function computeRackThermalMetrics(rack: RackSummary): RackThermalMetrics {
  const watts = Math.max(0, Number(rack.power_used_watts) || 0);
  const supplyC = 19.5;
  // Standard ASHRAE air delta-T approximation (~6.5°C per kW at typical cabinet airflow)
  const deltaT = Number(Math.min(35.5, (watts / 1000) * 6.5).toFixed(1));
  const exhaustC = Number((supplyC + deltaT).toFixed(1));
  const plumeIntensity = watts > 0 ? Number(Math.min(1, Math.max(0.25, deltaT / 22)).toFixed(2)) : 0;

  if (watts <= 0 || exhaustC < 21) {
    return { watts, supplyC, exhaustC, exhaustTempC: exhaustC, deltaT, plumeIntensity, color: '#1d4ed8', tier: 'cold' };
  }
  if (exhaustC < 27) {
    return { watts, supplyC, exhaustC, exhaustTempC: exhaustC, deltaT, plumeIntensity, color: '#06b6d4', tier: 'cool' };
  }
  if (exhaustC < 34) {
    return { watts, supplyC, exhaustC, exhaustTempC: exhaustC, deltaT, plumeIntensity, color: '#f59e0b', tier: 'warm' };
  }
  if (exhaustC < 42) {
    return { watts, supplyC, exhaustC, exhaustTempC: exhaustC, deltaT, plumeIntensity, color: '#f97316', tier: 'hot' };
  }
  return { watts, supplyC, exhaustC, exhaustTempC: exhaustC, deltaT, plumeIntensity, color: '#ef4444', tier: 'critical' };
}

const compareText = (left: string | undefined, right: string | undefined) =>
  (left || '').localeCompare(right || '', undefined, { numeric: true, sensitivity: 'base' });

const CAB_W = 0.82;
const CAB_D = 0.96;
const CAB_H = 2.0;
const FLUSH_GAP = 0.02;
const CABINET_PITCH_X = 0.84; // 0.82m cabinet + 20mm engineering joint
const PDF_W = 0.82;
const INROW_CRAC_W = 0.84;
const CENTRAL_CORRIDOR_W = 1.8; // 3 x 600mm raised-floor tiles (GB 50174-2017 >= 1.5m)
const COLD_OR_HOT_PITCH_Z = 2.16; // 0.96m cabinet depth + 1.20m cold/hot aisle
const ZONE_CORRIDOR_PITCH_Z = 2.76; // 0.96m cabinet depth + 1.80m main walkway

function splitBalancedChunks<T>(items: T[], targetCols: number, forceEvenChunks: boolean): T[][] {
  if (items.length === 0) return [];
  let numChunks = Math.max(1, Math.ceil(items.length / targetCols));
  if (forceEvenChunks && items.length >= 4 && numChunks % 2 !== 0) {
    numChunks += 1;
  }
  const base = Math.floor(items.length / numChunks);
  const rem = items.length % numChunks;
  const chunks: T[][] = [];
  let offset = 0;
  for (let i = 0; i < numChunks; i++) {
    const size = base + (i < rem ? 1 : 0);
    if (size > 0) {
      chunks.push(items.slice(offset, offset + size));
    }
    offset += size;
  }
  return chunks;
}

function pickOptimalPodColumns(rackCount: number, useDualPod: boolean): number {
  if (!useDualPod) return 12;
  if (rackCount <= 3) return rackCount;
  const candidates = [10, 9, 8, 7, 11, 12];
  let bestCols = 9;
  let bestScore = -Infinity;
  for (const cols of candidates) {
    let chunks = Math.ceil(rackCount / cols);
    if (rackCount >= 4 && chunks % 2 !== 0) chunks += 1;
    const zBands = Math.ceil(chunks / 2);
    const avgPerRow = rackCount / chunks;
    if (avgPerRow > 12) continue;
    let score = 0;
    // Strongly prefer even number of Z-bands so every cold aisle pairs face-to-face cleanly
    if (zBands % 2 === 0) score += 100;
    // Keep pod row well-populated (avoid skinny 2-3 rack rows when alternatives exist)
    if (avgPerRow >= 6) score += 35;
    else if (avgPerRow >= 4) score += 15;
    // Prefer 8-10 racks/row (row span <= 11.8m, well under GB 50174 15m egress limit)
    score -= Math.abs(avgPerRow - 9) * 4;
    if (score > bestScore) {
      bestScore = score;
      bestCols = cols;
    }
  }
  return bestCols;
}

function computeRackSpanWithMidCrac(rackCount: number): number {
  if (rackCount <= 0) return 0;
  const hasMidCrac = rackCount >= 7;
  return rackCount * CABINET_PITCH_X - FLUSH_GAP + (hasMidCrac ? INROW_CRAC_W + FLUSH_GAP : 0);
}

export function buildRackFleetLayout(racks: RackSummary[]): RackFleetPlacement[] {
  const enriched = racks.map(rack => {
    const zoneKind = inferRackZoneKind(rack);
    const archetype = inferRackArchetype(rack, zoneKind);
    return { rack, zoneKind, archetype };
  });

  const ordered = [...enriched].sort((left, right) =>
    (ZONE_META[left.zoneKind].order - ZONE_META[right.zoneKind].order) ||
    compareText(left.rack.site_label, right.rack.site_label) ||
    compareText(left.rack.floor, right.rack.floor) ||
    compareText(left.rack.room, right.rack.room) ||
    compareText(left.rack.row, right.rack.row) ||
    compareText(left.rack.name, right.rack.name)
  );

  type EnrichedItem = { rack: RackSummary; zoneKind: DataCenterZoneKind; archetype: RackCabinetArchetype };
  const groups = new Map<string, EnrichedItem[]>();
  ordered.forEach(item => {
    const groupKey = [
      item.zoneKind,
      item.rack.site_label,
      item.rack.floor,
      item.rack.room,
      item.rack.row,
    ].map(value => value || '—').join(' / ');
    const group = groups.get(groupKey) || [];
    group.push(item);
    groups.set(groupKey, group);
  });

  // Adaptive Single-Pod (<= 24 racks) vs GB 50174-2017 "田字形" Dual-Pod (> 24 racks, central 1.80m corridor)
  const useDualPod = ordered.length > 24;

  interface PendingBandRow {
    groupKey: string;
    displayLabel: string;
    zoneKind: DataCenterZoneKind;
    podSide: PodSide;
    z: number;
    facing: 1 | -1;
    items: EnrichedItem[];
  }

  // Group chunks by zoneKind so Dual-Pod pairs rows neatly side-by-side within each zone
  const zoneGroupsMap = new Map<DataCenterZoneKind, Array<{ groupKey: string; items: EnrichedItem[] }>>();
  groups.forEach((groupItems, groupKey) => {
    const zk = groupItems[0].zoneKind;
    const list = zoneGroupsMap.get(zk) || [];
    list.push({ groupKey, items: groupItems });
    zoneGroupsMap.set(zk, list);
  });

  const pendingRows: PendingBandRow[] = [];
  let zCursor = 0;
  let hasPlacedAnyZone = false;

  Array.from(zoneGroupsMap.entries())
    .sort(([a], [b]) => ZONE_META[a].order - ZONE_META[b].order)
    .forEach(([zoneKind, zGroups]) => {
      if (hasPlacedAnyZone) {
        zCursor += ZONE_CORRIDOR_PITCH_Z;
      }
      hasPlacedAnyZone = true;

      // Flatten all row chunks inside this functional zone
      const zoneChunks: Array<{ groupKey: string; displayLabel: string; items: EnrichedItem[] }> = [];
      const zoneRackTotal = zGroups.reduce((sum, g) => sum + g.items.length, 0);
      const targetCols = pickOptimalPodColumns(zoneRackTotal, useDualPod);

      zGroups.forEach(({ groupKey, items }) => {
        const displayLabel = [
          ZONE_META[zoneKind].zh,
          items[0].rack.site_label,
          items[0].rack.floor,
          items[0].rack.room,
          items[0].rack.row,
        ].filter(v => v && v !== '—').join(' / ');

        // Split group evenly; if Dual-Pod and group has >=4 racks inside a zone with multiple racks, keep even chunks
        const chunks = splitBalancedChunks(items, targetCols, useDualPod && items.length >= 4);
        chunks.forEach(chunk => {
          zoneChunks.push({ groupKey, displayLabel, items: chunk });
        });
      });

      if (!useDualPod) {
        zoneChunks.forEach((chunk, bandIdx) => {
          if (bandIdx > 0) zCursor += COLD_OR_HOT_PITCH_Z;
          pendingRows.push({
            groupKey: chunk.groupKey,
            displayLabel: chunk.displayLabel,
            zoneKind,
            podSide: 'center',
            z: Number(zCursor.toFixed(3)),
            facing: bandIdx % 2 === 0 ? 1 : -1,
            items: chunk.items,
          });
        });
      } else {
        // Pair chunks side-by-side into Left Pod and Right Pod across the 1.80m central corridor
        let bandIdx = 0;
        for (let i = 0; i < zoneChunks.length; i += 2) {
          if (bandIdx > 0) zCursor += COLD_OR_HOT_PITCH_Z;
          const facing: 1 | -1 = bandIdx % 2 === 0 ? 1 : -1;
          const leftChunk = zoneChunks[i];
          const rightChunk = zoneChunks[i + 1];

          pendingRows.push({
            groupKey: leftChunk.groupKey,
            displayLabel: leftChunk.displayLabel,
            zoneKind,
            podSide: 'left',
            z: Number(zCursor.toFixed(3)),
            facing,
            items: leftChunk.items,
          });
          if (rightChunk) {
            pendingRows.push({
              groupKey: rightChunk.groupKey,
              displayLabel: rightChunk.displayLabel,
              zoneKind,
              podSide: 'right',
              z: Number(zCursor.toFixed(3)),
              facing,
              items: rightChunk.items,
            });
          }
          bandIdx += 1;
        }
      }
    });

  // Compute uniform Pod-level X start datum so every PDF column-head lines up laser-straight
  const maxCenterRackSpan = Math.max(
    0,
    ...pendingRows.filter(r => r.podSide === 'center').map(r => computeRackSpanWithMidCrac(r.items.length)),
  );
  const maxLeftRackSpan = Math.max(
    0,
    ...pendingRows.filter(r => r.podSide === 'left').map(r => computeRackSpanWithMidCrac(r.items.length)),
  );

  const placements: RackFleetPlacement[] = [];
  pendingRows.forEach(row => {
    const rowCols = row.items.length;
    const hasMidCrac = rowCols >= 7;
    const splitIdx = hasMidCrac ? Math.floor(rowCols / 2) : rowCols;

    let firstRackLeftEdge: number;
    if (row.podSide === 'left') {
      // All Left Pod PDFs align vertically; widest Left Pod end-CRAC stops cleanly at -CENTRAL_CORRIDOR_W / 2
      firstRackLeftEdge = -(CENTRAL_CORRIDOR_W / 2) - INROW_CRAC_W - FLUSH_GAP - maxLeftRackSpan;
    } else if (row.podSide === 'right') {
      // All Right Pod PDFs align vertically at +CENTRAL_CORRIDOR_W / 2 along the central 1.80m corridor
      firstRackLeftEdge = CENTRAL_CORRIDOR_W / 2 + PDF_W + FLUSH_GAP;
    } else {
      // Single-Pod center alignment
      firstRackLeftEdge = -maxCenterRackSpan / 2;
    }

    row.items.forEach((item, column) => {
      const midCracShift = hasMidCrac && column >= splitIdx ? INROW_CRAC_W + FLUSH_GAP : 0;
      const xCenter = firstRackLeftEdge + CAB_W / 2 + column * CABINET_PITCH_X + midCracShift;
      placements.push({
        rack: item.rack,
        instanceIndex: placements.length,
        groupKey: row.groupKey,
        groupLabel: row.displayLabel || row.groupKey,
        zoneKind: item.zoneKind,
        archetype: item.archetype,
        facing: row.facing,
        podSide: row.podSide,
        inferred: true,
        position: [
          Number(xCenter.toFixed(3)),
          1.0, // Unified 2.00m cabinet datum (centerY = 1.00m, flush with PDF & In-Row CRAC)
          row.z,
        ],
      });
    });
  });

  return placements;
}

/**
 * Derive a GB 50174-2017 (Tier-4 / A-Grade) & GB 50462-2015 compliant modular Data Center hall:
 * - Parallel, laser-aligned cabinet rows on the 600mm raised-floor module
 * - Flush in-row alignment: [PDF Column-Head] + [Tight IT Cabinet Row] + [In-Row CRAC] on one Z datum
 * - Face-to-face 1.20m enclosed cold aisles & back-to-back 1.20m hot aisles
 * - Dedicated parallel Infrastructure Equipment Row separated by a 1.80m main service corridor:
 *   [KEBOS UPS-A | KEBOS UPS-B] -- [CRAC-W1 | CRAC-W2] -- [ODF-01...] all facing +Z flush in one row
 * - Stratified overhead cable trays (Fiber Y=2.68m above Power Y=2.34m, 340mm >= 300mm GB separation)
 */
export function buildDataCenterRoomModel(
  placements: RackFleetPlacement[],
  odfFrames: OdfFrameRoomInput[] = [],
): DataCenterRoomModel {
  if (!placements.length) {
    return {
      rows: [],
      coldAisles: [],
      zones: [],
      cracUnits: [],
      pdfCabinets: [],
      upsUnits: [],
      batteryUnits: [],
      odfUnits: [],
      trays: [],
      bounds: {
        minX: -6,
        maxX: 6,
        minZ: -5,
        maxZ: 5,
        width: 12,
        depth: 10,
        centerX: 0,
        centerZ: 0,
        ceilingY: 4.25,
      },
      totals: {
        rackCount: 0,
        totalPowerKw: 0,
        cracCount: 0,
        pdfCount: 0,
        odfCount: 0,
        avgUtilizationPct: 0,
        peakPowerRackName: '—',
        peakPowerKw: 0,
        hottestRackName: '—',
        hottestTempC: 19.5,
      },
    };
  }

  // Group placements by (podSide, Z) into clean datacenter rows
  const rowBucketMap = new Map<string, RackFleetPlacement[]>();
  placements.forEach(p => {
    const podSide = p.podSide || 'center';
    const key = `${podSide}::${p.position[2].toFixed(2)}`;
    const list = rowBucketMap.get(key) || [];
    list.push(p);
    rowBucketMap.set(key, list);
  });

  const podOrder: Record<PodSide, number> = { left: 0, center: 1, right: 2 };
  const sortedRowEntries = Array.from(rowBucketMap.entries()).sort((a, b) => {
    const [podA, zA] = a[0].split('::');
    const [podB, zB] = b[0].split('::');
    return (Number(zA) - Number(zB)) || ((podOrder[podA as PodSide] ?? 1) - (podOrder[podB as PodSide] ?? 1));
  });

  const rows: DataCenterRowModel[] = sortedRowEntries.map(([, list], idx) => {
    const sortedList = [...list].sort((a, b) => a.position[0] - b.position[0]);
    const z = Number(sortedList[0].position[2].toFixed(2));
    const xs = sortedList.map(item => item.position[0]);
    const xMin = Math.min(...xs) - CAB_W / 2;
    const xMax = Math.max(...xs) + CAB_W / 2;
    const totalPowerW = sortedList.reduce((sum, item) => sum + (Number(item.rack.power_used_watts) || 0), 0);
    const usedU = sortedList.reduce((sum, item) => sum + (Number(item.rack.used_u) || 0), 0);
    const totalU = sortedList.reduce((sum, item) => sum + Math.max(1, Number(item.rack.total_u) || 42), 0);
    const sample = sortedList[0].rack;
    const zoneKind = sortedList[0].zoneKind;
    const facing = sortedList[0].facing ?? 1;
    const podSide = sortedList[0].podSide || 'center';
    const rowName = sample.row && sample.row !== '—'
      ? `ROW-${sample.row}`
      : `ROW-${String.fromCharCode(65 + (idx % 26))}`;
    const roomPrefix = sample.room && sample.room !== '—' ? `${sample.room} · ` : '';
    const podTag = podSide === 'left' ? 'L-' : podSide === 'right' ? 'R-' : '';

    return {
      id: `row-${idx}`,
      label: `${roomPrefix}${podTag}${rowName}`,
      zoneKind,
      z,
      xMin,
      xMax,
      centerX: (xMin + xMax) / 2,
      spanX: Math.max(CAB_W, xMax - xMin),
      rackCount: sortedList.length,
      totalPowerW,
      usedU,
      totalU,
      facing,
      podSide,
      placements: sortedList,
    };
  });

  const cracUnits: DataCenterEquipmentPlacement[] = [];
  const pdfCabinets: DataCenterEquipmentPlacement[] = [];
  const upsUnits: DataCenterEquipmentPlacement[] = [];
  const batteryUnits: DataCenterEquipmentPlacement[] = [];
  const odfUnits: DataCenterEquipmentPlacement[] = [];
  const trays: DataCenterTraySegment[] = [];

  const FIBER_TRAY_Y = 2.68; // GB 50462-2015: Weak-current optical raceway upper tier
  const POWER_TRAY_Y = 2.34; // Strong-current A/B busway lower tier (340mm >= 300mm vertical separation)

  // 1. Flush In-Row Infrastructure: [PDF Column-Head] + [IT Racks (+ optional Mid-Row CRAC)] + [In-Row CRAC]
  let itModuleMinX = Infinity;
  let itModuleMaxX = -Infinity;

  rows.forEach((row, idx) => {
    const rotY = row.facing === -1 ? Math.PI : 0;
    const pdfCenterX = Number((row.xMin - FLUSH_GAP - PDF_W / 2).toFixed(3));
    const cracCenterX = Number((row.xMax + FLUSH_GAP + INROW_CRAC_W / 2).toFixed(3));
    const rowPowerKw = Math.max(0.8, Number((row.totalPowerW / 1000).toFixed(1)));

    itModuleMinX = Math.min(itModuleMinX, pdfCenterX - PDF_W / 2);
    itModuleMaxX = Math.max(itModuleMaxX, cracCenterX + INROW_CRAC_W / 2);

    pdfCabinets.push({
      id: `pdf-${idx + 1}`,
      label: `PDF-${String(idx + 1).padStart(2, '0')} 列头柜`,
      sublabel: `A/B ${rowPowerKw} kW`,
      kind: 'pdf',
      position: [pdfCenterX, CAB_H / 2, row.z],
      rotationY: rotY,
      width: PDF_W,
      height: CAB_H,
      depth: CAB_D,
      loadKw: rowPowerKw,
    });

    // Place interleaved Mid-Row In-Row CRAC cleanly inside any reserved >1.2m center gap
    for (let r = 1; r < row.placements.length; r++) {
      const prevX = row.placements[r - 1].position[0];
      const currX = row.placements[r].position[0];
      if (currX - prevX > 1.2) {
        const midCracX = Number(((prevX + currX) / 2).toFixed(3));
        cracUnits.push({
          id: `crac-row-${idx + 1}-mid`,
          label: `CRAC-${String(idx + 1).padStart(2, '0')}M`,
          sublabel: '19.5°C · 行间',
          kind: 'crac',
          cracRole: 'inrow',
          position: [midCracX, CAB_H / 2, row.z],
          rotationY: rotY,
          width: INROW_CRAC_W,
          height: CAB_H,
          depth: CAB_D,
          supplyTempC: 19.5,
        });
      }
    }

    cracUnits.push({
      id: `crac-row-${idx + 1}`,
      label: `CRAC-${String(idx + 1).padStart(2, '0')}`,
      sublabel: '19.5°C · 48%RH',
      kind: 'crac',
      cracRole: 'inrow',
      position: [cracCenterX, CAB_H / 2, row.z],
      rotationY: rotY,
      width: INROW_CRAC_W,
      height: CAB_H,
      depth: CAB_D,
      supplyTempC: 19.5,
    });

    // Update row bounds so containment canopy spans flush from PDF to end In-Row CRAC!
    row.xMin = pdfCenterX - PDF_W / 2;
    row.xMax = cracCenterX + INROW_CRAC_W / 2;
    row.centerX = (row.xMin + row.xMax) / 2;
    row.spanX = row.xMax - row.xMin;
  });

  // 2. Build GB 50174-2017 Cold Aisle Containment models ONLY within the SAME Pod & Zone
  const coldAisles: DataCenterColdAisleModel[] = [];
  const handledRows = new Set<number>();
  for (let i = 0; i < rows.length; i++) {
    if (handledRows.has(i)) continue;
    const rA = rows[i];
    let partnerIdx = -1;
    if (rA.facing === 1) {
      partnerIdx = rows.findIndex(
        (cand, j) =>
          !handledRows.has(j)
          && j !== i
          && (cand.podSide || 'center') === (rA.podSide || 'center')
          && cand.zoneKind === rA.zoneKind
          && cand.facing === -1
          && Math.abs((cand.z - rA.z) - 2.16) < 0.35,
      );
    }
    if (partnerIdx >= 0) {
      const rB = rows[partnerIdx];
      handledRows.add(i);
      handledRows.add(partnerIdx);
      const minX = Math.min(rA.xMin, rB.xMin);
      const maxX = Math.max(rA.xMax, rB.xMax);
      coldAisles.push({
        id: `aisle-${rA.id}-${rB.id}`,
        label: `${rA.label} / ${rB.label}`,
        z: Number(((rA.z + rB.z) / 2).toFixed(3)),
        width: 1.2,
        centerX: (minX + maxX) / 2,
        spanX: maxX - minX,
        enclosed: true,
      });
    } else {
      handledRows.add(i);
      coldAisles.push({
        id: `aisle-${rA.id}`,
        label: rA.label,
        z: Number((rA.z + rA.facing * (CAB_D / 2 + 0.6)).toFixed(3)),
        width: 1.2,
        centerX: rA.centerX,
        spanX: rA.spanX,
        enclosed: true,
      });
    }
  }

  // 3. Dedicated Parallel Infrastructure Equipment Row (GB 50174-2017 §4.1.2 & §8.1:
  //    Aligned cleanly in ONE straight parallel row behind the 1.80m main service corridor,
  //    all facing +Z with flush front doors: [KEBOS UPS-A | UPS-B]  [CRAC-W1 | CRAC-W2]  [ODF-01...])
  const firstItRowZ = rows[0].z;
  const lastItRowZ = rows[rows.length - 1].z;
  const MAIN_CORRIDOR_W = 1.8; // GB 50174-2017 >= 1.5m -> 3 x 600mm floor tiles
  const INFRA_DEPTH = 0.9;
  const infraFrontZ = firstItRowZ - CAB_D / 2 - MAIN_CORRIDOR_W;
  const infraCenterZ = Number((infraFrontZ - INFRA_DEPTH / 2).toFixed(3));

  const totalPowerKw = Number(
    (placements.reduce((sum, p) => sum + (Number(p.rack.power_used_watts) || 0), 0) / 1000).toFixed(2),
  );

  const BATT_W = 0.72;
  const UPS_W = 0.98;
  const UPS_H = 2.08;
  const BANK_SEAM = 0.04;
  const SUBBANK_GAP = 0.6; // 1 x 600mm tile clean separation between Power & Cooling
  const EMI_GAP = 0.9; // GB 50174 strong/weak-current separation between Cooling/Power & ODF

  // Scale N+1 / 2N UPS, Battery Banks, Perimeter CRAC-W & ODF dynamically to hall IT load & rack count
  const upsCount = totalPowerKw <= 110
    ? 2
    : Math.min(6, Math.max(3, Math.ceil(totalPowerKw / 95) + 1));
  const battCount = totalPowerKw <= 110
    ? 2
    : Math.min(4, Math.ceil(upsCount / 2) * 2);
  const leftBattCount = Math.floor(battCount / 2);
  const rightBattCount = battCount - leftBattCount;

  const perimeterCracCount = Math.min(
    8,
    Math.max(2, Math.ceil(Math.max(rows.length * 0.6, totalPowerKw / 55))),
  );
  const CRAC_W = 1.06;
  const CRAC_H = 2.08;

  const realOdfFrames = Array.isArray(odfFrames) ? odfFrames.slice(0, 6) : [];
  const odfCount = realOdfFrames.length > 0
    ? realOdfFrames.length
    : Math.min(6, Math.max(1, Math.ceil(placements.length / 24)));
  const ODF_W = 0.84;
  const ODF_H = 2.06;
  const ODF_D = 0.48;

  // Symmetrical Power Bank: [KEBOS BATT-L... | KEBOS UPS-A..N | KEBOS BATT-R...]
  const powerSlotCount = upsCount + battCount;
  const upsBankW = upsCount * UPS_W + battCount * BATT_W + Math.max(0, powerSlotCount - 1) * BANK_SEAM;
  const cracBankW = perimeterCracCount * CRAC_W + (perimeterCracCount - 1) * BANK_SEAM;
  const odfBankW = odfCount * ODF_W + (odfCount - 1) * BANK_SEAM;
  const totalInfraRowW = upsBankW + SUBBANK_GAP + cracBankW + EMI_GAP + odfBankW;

  const itCenterX = (itModuleMinX + itModuleMaxX) / 2;
  let cursorX = itCenterX - totalInfraRowW / 2;

  // 3a. Left Bank: Symmetrical KEBOS Battery Banks + N+1 KEBOS UPS Cabinets (flush, facing +Z)
  const upsBankMinX = cursorX;
  let battSeq = 0;
  for (let i = 0; i < leftBattCount; i++) {
    const labelChar = String.fromCharCode(65 + battSeq++);
    const cx = Number((cursorX + BATT_W / 2).toFixed(3));
    batteryUnits.push({
      id: `batt-main-${labelChar.toLowerCase()}`,
      label: `KEBOS BATT-${labelChar} 480V`,
      sublabel: 'FLOAT · 100%',
      kind: 'battery',
      position: [cx, UPS_H / 2, infraCenterZ],
      rotationY: 0,
      width: BATT_W,
      height: UPS_H,
      depth: INFRA_DEPTH,
    });
    cursorX += BATT_W + BANK_SEAM;
  }

  const perUpsKw = Number((Math.max(18.4, totalPowerKw / Math.max(1, upsCount - 1))).toFixed(1));
  for (let i = 0; i < upsCount; i++) {
    const labelChar = String.fromCharCode(65 + i);
    const isStandby = i === upsCount - 1;
    const cx = Number((cursorX + UPS_W / 2).toFixed(3));
    upsUnits.push({
      id: `ups-main-${labelChar.toLowerCase()}`,
      label: `KEBOS UPS-${labelChar} 120kVA`,
      sublabel: isStandby ? 'STANDBY · 100%' : `ONLINE · ${perUpsKw}kW`,
      kind: 'ups',
      position: [cx, UPS_H / 2, infraCenterZ],
      rotationY: 0, // Faces +Z straight into the 1.80m main service corridor!
      width: UPS_W,
      height: UPS_H,
      depth: INFRA_DEPTH,
      loadKw: isStandby ? 0 : perUpsKw,
    });
    cursorX += UPS_W + (i < upsCount - 1 || rightBattCount > 0 ? BANK_SEAM : 0);
  }

  for (let i = 0; i < rightBattCount; i++) {
    const labelChar = String.fromCharCode(65 + battSeq++);
    const cx = Number((cursorX + BATT_W / 2).toFixed(3));
    batteryUnits.push({
      id: `batt-main-${labelChar.toLowerCase()}`,
      label: `KEBOS BATT-${labelChar} 480V`,
      sublabel: 'FLOAT · 100%',
      kind: 'battery',
      position: [cx, UPS_H / 2, infraCenterZ],
      rotationY: 0,
      width: BATT_W,
      height: UPS_H,
      depth: INFRA_DEPTH,
    });
    cursorX += BATT_W + (i < rightBattCount - 1 ? BANK_SEAM : 0);
  }
  const upsBankMaxX = cursorX;

  cursorX += SUBBANK_GAP;

  // 3b. Center Bank: Perimeter Precision CRAC-W Units (flush side-by-side, front aligned with UPS!)
  for (let i = 0; i < perimeterCracCount; i++) {
    const cx = Number((cursorX + CRAC_W / 2).toFixed(3));
    cracUnits.push({
      id: `crac-wall-${i + 1}`,
      label: `CRAC-W${i + 1}`,
      sublabel: '18.8°C · 35kW',
      kind: 'crac',
      cracRole: 'perimeter',
      position: [cx, CRAC_H / 2, infraCenterZ],
      rotationY: 0,
      width: CRAC_W,
      height: CRAC_H,
      depth: INFRA_DEPTH,
      supplyTempC: 18.8,
    });
    cursorX += CRAC_W + (i < perimeterCracCount - 1 ? BANK_SEAM : 0);
  }
  const cracBankMaxX = cursorX;

  cursorX += EMI_GAP;

  // 3c. Right Bank: Dedicated ODF Optical Distribution Frames (front doors flush on EXACT same Z datum!)
  const odfBankMinX = cursorX;
  const odfCenterZ = Number((infraFrontZ - ODF_D / 2).toFixed(3));
  if (realOdfFrames.length > 0) {
    realOdfFrames.forEach((frame, i) => {
      const cx = Number((cursorX + ODF_W / 2).toFixed(3));
      const totalCores = Math.max(1, frame.total_cores || frame.tray_count * frame.ports_per_tray || 576);
      odfUnits.push({
        id: frame.id,
        label: frame.name || frame.frame_code || `ODF-${String(i + 1).padStart(2, '0')}`,
        sublabel: `${frame.occupied_cores || 0}/${totalCores}芯 · ${frame.connector_type || 'LC/UPC'}`,
        kind: 'odf',
        position: [cx, ODF_H / 2, odfCenterZ],
        rotationY: 0, // Faces +Z parallel with UPS & CRAC in ONE neat straight equipment row!
        width: ODF_W,
        height: ODF_H,
        depth: ODF_D,
        fiberCores: totalCores,
        odfFrame: frame,
        isPlaceholder: false,
      });
      cursorX += ODF_W + (i < realOdfFrames.length - 1 ? BANK_SEAM : 0);
    });
  } else {
    for (let i = 0; i < odfCount; i++) {
      const cx = Number((cursorX + ODF_W / 2).toFixed(3));
      odfUnits.push({
        id: `odf-main-${i + 1}`,
        label: `ODF-${String(i + 1).padStart(2, '0')} 光纤配线架`,
        sublabel: '576 芯 · 未录入 CMDB',
        kind: 'odf',
        position: [cx, ODF_H / 2, odfCenterZ],
        rotationY: 0, // Faces +Z parallel with UPS & CRAC in ONE neat straight equipment row!
        width: ODF_W,
        height: ODF_H,
        depth: ODF_D,
        fiberCores: 576,
        odfFrame: null,
        isPlaceholder: true,
      });
      cursorX += ODF_W + (i < odfCount - 1 ? BANK_SEAM : 0);
    }
  }
  const odfBankMaxX = cursorX;

  // 4. Hall Perimeter Bounds snapped cleanly to 600mm raised-floor tiles (GB 50174 wall clearance >= 1.2m)
  const contentMinX = Math.min(itModuleMinX, upsBankMinX);
  const contentMaxX = Math.max(itModuleMaxX, odfBankMaxX);
  const maxColdZ = Math.max(
    lastItRowZ + CAB_D / 2,
    ...coldAisles.map(a => a.z + a.width / 2),
  );
  const WALL_CLEARANCE = 1.5; // >= 1.2m perimeter maintenance walkway per GB 50174-2017
  const snapTile = (val: number, dir: -1 | 1) =>
    Number(((dir < 0 ? Math.floor(val / 0.6) : Math.ceil(val / 0.6)) * 0.6).toFixed(2));

  const minX = snapTile(contentMinX - WALL_CLEARANCE, -1);
  const maxX = snapTile(contentMaxX + WALL_CLEARANCE, 1);
  const minZ = snapTile(infraCenterZ - INFRA_DEPTH / 2 - 1.2, -1);
  const maxZ = snapTile(maxColdZ + 1.5, 1);
  const width = Number((maxX - minX).toFixed(2));
  const depth = Number((maxZ - minZ).toFixed(2));
  const centerX = Number(((minX + maxX) / 2).toFixed(2));
  const centerZ = Number(((minZ + maxZ) / 2).toFixed(2));
  const ceilingY = 4.25;

  // 5. GB 50462-2015 Stratified Overhead Cable Trays (Left Strong-Current Power Spine / Right Weak-Current Fiber Spine)
  // Both spines are strictly external to ALL IT rows & infrastructure banks (never crossing above IT racks!)
  const powerSpineX = Number((Math.min(itModuleMinX, upsBankMinX) - 0.55).toFixed(3));
  const fiberSpineX = Number((Math.max(itModuleMaxX, odfBankMaxX) + 0.55).toFixed(3));
  const powerSpineStartZ = infraCenterZ - 0.12;
  const fiberSpineStartZ = odfCenterZ + 0.02;

  // Group rows by Z-band so Dual-Pod left & right pods share one clean continuous horizontal tray per Z-row
  const rowsByZBand = new Map<string, DataCenterRowModel[]>();
  rows.forEach(row => {
    const zKey = row.z.toFixed(2);
    const list = rowsByZBand.get(zKey) || [];
    list.push(row);
    rowsByZBand.set(zKey, list);
  });

  Array.from(rowsByZBand.values()).forEach((bandRows, idx) => {
    const refRow = bandRows[0];
    const bandMinX = Math.min(...bandRows.map(r => r.xMin));
    const bandMaxX = Math.max(...bandRows.map(r => r.xMax));
    const fiberZ = Number((refRow.z + refRow.facing * 0.24).toFixed(3));
    const powerZ = Number((refRow.z - refRow.facing * 0.24).toFixed(3));

    trays.push({
      id: `tray-fiber-row-${idx}`,
      kind: 'fiber',
      start: [bandMinX, FIBER_TRAY_Y, fiberZ],
      end: [fiberSpineX + 0.15, FIBER_TRAY_Y, fiberZ],
      width: 0.3,
    });

    trays.push({
      id: `tray-power-row-${idx}`,
      kind: 'power',
      start: [powerSpineX - 0.15, POWER_TRAY_Y, powerZ],
      end: [bandMaxX, POWER_TRAY_Y, powerZ],
      width: 0.34,
    });
  });

  // Top lateral fiber bridge above the ODF bank + straight Z weak-current optical spine on far right perimeter
  const lastRowFiberZ = rows[rows.length - 1].z + rows[rows.length - 1].facing * 0.24;
  trays.push({
    id: 'tray-fiber-odf-header',
    kind: 'fiber',
    start: [odfBankMinX - 0.1, FIBER_TRAY_Y, fiberSpineStartZ],
    end: [fiberSpineX + 0.15, FIBER_TRAY_Y, fiberSpineStartZ],
    width: 0.32,
  });
  trays.push({
    id: 'tray-fiber-spine',
    kind: 'fiber',
    start: [fiberSpineX, FIBER_TRAY_Y, fiberSpineStartZ],
    end: [fiberSpineX, FIBER_TRAY_Y, Math.max(fiberSpineStartZ + 0.6, lastRowFiberZ + 0.15)],
    width: 0.36,
  });

  // Top lateral power busway above KEBOS UPS/BATT bank + straight Z strong-current power spine on far left perimeter
  const lastRowPowerZ = rows[rows.length - 1].z - rows[rows.length - 1].facing * 0.24;
  trays.push({
    id: 'tray-power-ups-feed',
    kind: 'power',
    start: [powerSpineX - 0.15, POWER_TRAY_Y, powerSpineStartZ],
    end: [upsBankMaxX + 0.1, POWER_TRAY_Y, powerSpineStartZ],
    width: 0.36,
  });
  trays.push({
    id: 'tray-power-spine',
    kind: 'power',
    start: [powerSpineX, POWER_TRAY_Y, powerSpineStartZ],
    end: [powerSpineX, POWER_TRAY_Y, Math.max(powerSpineStartZ + 0.6, lastRowPowerZ + 0.15)],
    width: 0.4,
  });

  // 6. Clean Non-Overlapping Functional Zones (IT Micro-Modules + Power/Cooling Row + ODF Row)
  const zones: DataCenterZoneModel[] = [];
  const rowsByZone = new Map<DataCenterZoneKind, DataCenterRowModel[]>();
  rows.forEach(row => {
    const list = rowsByZone.get(row.zoneKind) || [];
    list.push(row);
    rowsByZone.set(row.zoneKind, list);
  });

  Array.from(rowsByZone.entries())
    .sort(([a], [b]) => ZONE_META[a].order - ZONE_META[b].order)
    .forEach(([kind, zoneRows]) => {
      const zMinX = Math.min(...zoneRows.map(r => r.xMin)) - 0.25;
      const zMaxX = Math.max(...zoneRows.map(r => r.xMax)) + 0.25;
      const zMinZ = Math.min(...zoneRows.map(r => r.z)) - CAB_D / 2 - 0.25;
      const zMaxZ = Math.max(
        ...zoneRows.map(r => r.z + (r.facing === 1 ? CAB_D / 2 + 1.32 : CAB_D / 2 + 0.25)),
      );
      const meta = ZONE_META[kind];
      zones.push({
        id: `zone-${kind}`,
        kind,
        labelZh: meta.zh,
        labelEn: meta.en,
        accentColor: meta.color,
        rackCount: zoneRows.reduce((s, r) => s + r.rackCount, 0),
        bounds: {
          minX: zMinX,
          maxX: zMaxX,
          minZ: zMinZ,
          maxZ: zMaxZ,
          centerX: (zMinX + zMaxX) / 2,
          centerZ: (zMinZ + zMaxZ) / 2,
          width: zMaxX - zMinX,
          depth: zMaxZ - zMinZ,
        },
      });
    });

  // Power & Cooling Infrastructure Bank Zone ([KEBOS UPS-A/B] + [CRAC-W1/W2])
  const pMinX = upsBankMinX - 0.25;
  const pMaxX = cracBankMaxX + 0.25;
  const pMinZ = infraCenterZ - INFRA_DEPTH / 2 - 0.25;
  const pMaxZ = infraFrontZ + 0.35;
  zones.push({
    id: 'zone-power',
    kind: 'power_cooling',
    labelZh: ZONE_META.power_cooling.zh,
    labelEn: ZONE_META.power_cooling.en,
    accentColor: ZONE_META.power_cooling.color,
    rackCount: upsUnits.length + batteryUnits.length + perimeterCracCount,
    bounds: {
      minX: pMinX,
      maxX: pMaxX,
      minZ: pMinZ,
      maxZ: pMaxZ,
      centerX: (pMinX + pMaxX) / 2,
      centerZ: (pMinZ + pMaxZ) / 2,
      width: pMaxX - pMinX,
      depth: pMaxZ - pMinZ,
    },
  });

  // Dedicated ODF Optical Distribution Zone (right end of the parallel Infrastructure Row)
  if (odfUnits.length > 0 && !zones.some(z => z.kind === 'odf')) {
    const oMinX = odfBankMinX - 0.25;
    const oMaxX = odfBankMaxX + 0.25;
    const oMinZ = infraCenterZ - INFRA_DEPTH / 2 - 0.25;
    const oMaxZ = infraFrontZ + 0.35;
    zones.push({
      id: 'zone-odf',
      kind: 'odf',
      labelZh: ZONE_META.odf.zh,
      labelEn: ZONE_META.odf.en,
      accentColor: ZONE_META.odf.color,
      rackCount: odfUnits.length,
      bounds: {
        minX: oMinX,
        maxX: oMaxX,
        minZ: oMinZ,
        maxZ: oMaxZ,
        centerX: (oMinX + oMaxX) / 2,
        centerZ: (oMinZ + oMaxZ) / 2,
        width: oMaxX - oMinX,
        depth: oMaxZ - oMinZ,
      },
    });
  }

  const totalUsedU = placements.reduce((sum, p) => sum + (Number(p.rack.used_u) || 0), 0);
  const totalCapU = placements.reduce((sum, p) => sum + Math.max(1, Number(p.rack.total_u) || 42), 0);

  let peakPowerRackName = '—';
  let peakPowerKw = 0;
  let hottestRackName = '—';
  let hottestTempC = 19.5;
  placements.forEach(p => {
    const pm = computeRackPowerMetrics(p.rack);
    if (pm.kw > peakPowerKw) {
      peakPowerKw = pm.kw;
      peakPowerRackName = p.rack.name;
    }
    const tm = computeRackThermalMetrics(p.rack);
    if (tm.exhaustC > hottestTempC) {
      hottestTempC = tm.exhaustC;
      hottestRackName = p.rack.name;
    }
  });

  return {
    rows,
    coldAisles,
    zones,
    cracUnits,
    pdfCabinets,
    upsUnits,
    batteryUnits,
    odfUnits,
    trays,
    bounds: {
      minX,
      maxX,
      minZ,
      maxZ,
      width,
      depth,
      centerX,
      centerZ,
      ceilingY,
    },
    totals: {
      rackCount: placements.length,
      totalPowerKw,
      cracCount: cracUnits.length,
      pdfCount: pdfCabinets.length,
      odfCount: odfUnits.length,
      avgUtilizationPct: Math.round((totalUsedU / Math.max(1, totalCapU)) * 100),
      peakPowerRackName,
      peakPowerKw,
      hottestRackName,
      hottestTempC,
    },
  };
}
