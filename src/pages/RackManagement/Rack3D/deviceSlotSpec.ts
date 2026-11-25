/**
 * Slot-driven 3D hardware profile engine for fixed (box) switches, modular
 * chassis switches (4U-14U with MPU/SUP + LPU slots + Power Shelf), firewalls,
 * wireless controllers, and rack-mount UPS units (2U/3U).
 *
 * Drives three subsystems from one single source of truth:
 *   1. High-resolution silkscreen faceplate rendering (textures.ts)
 *   2. Slot/subslot/port -> 3D physical cable coordinate mapping (RackCableLayer.tsx)
 *   3. Device LED/slot identity matching (RackDeviceItem.tsx)
 */

import type { DevicePhysicalPortProfile } from '../types';

export type HardwareFormFactor = 'box' | 'chassis' | 'ups' | 'firewall' | 'wireless_ac' | 'server' | 'patch_panel';

export type VendorStyle = 'h3c' | 'cisco' | 'huawei' | 'ruijie' | 'ups' | 'generic';

export type SlotCardKind = 'mpu' | 'lpu_sfp' | 'lpu_rj45' | 'lpu_qsfp' | 'power_shelf' | 'blank';

export interface ChassisSlotDefinition {
  slotNumber: number;
  label: string;
  kind: SlotCardKind;
  /** Normalized vertical band inside chassis [0 = top, 1 = bottom] */
  yTopFrac: number;
  yBotFrac: number;
  portCount: number;
  portType: 'sfp' | 'rj45' | 'qsfp' | 'mgmt' | 'none';
}

export interface BoxSlotBankDefinition {
  subslot: number;
  label: string;
  startPort: number;
  cols: number;
  rows: 2;
  /** Physical X range in scene decimeters (-2.20 .. +2.20) */
  xStart: number;
  xEnd: number;
  kind: 'rj45' | 'sfp' | 'qsfp';
  modular?: boolean;
}

export interface HardwareFaceplateSpec {
  vendorStyle: VendorStyle;
  formFactor: HardwareFormFactor;
  heightU: number;
  /** Total downlink port density inferred from model/assetKey (e.g. 24, 32, 48) */
  portDensity: number;
  /** Modular uplink/subcard slot supported on right side of box switch */
  hasModularUplinkSlot: boolean;
  /** Box-level port bank layout (used for 1U/2U fixed switches) */
  boxBanks: BoxSlotBankDefinition[];
  /** Horizontal card slots (used for >=4U modular chassis switches) */
  chassisSlots: ChassisSlotDefinition[];
}

export function detectVendorStyle(vendor?: string, model?: string, assetKey?: string, role?: string): VendorStyle {
  const id = `${assetKey || ''} ${vendor || ''} ${model || ''} ${role || ''}`.toLowerCase();
  if (/(ups|smart-?ups|ups2000|liebert|eaton|不间断电源)/.test(id)) return 'ups';
  if (/(cisco|catalyst|nexus|c9300|c9400|c9500|n9k|ws-c|思科)/.test(id)) return 'cisco';
  if (/(huawei|cloudengine|ce68|ce88|ce128|s57|s67|s127|华为)/.test(id)) return 'huawei';
  if (/(ruijie|rg-s|rg-n18|锐捷)/.test(id)) return 'ruijie';
  if (/(h3c|s68|s5130|s5560|s10500|s12500|secpath|f10\d\d|wx55|新华三|华三)/.test(id)) return 'h3c';
  return 'generic';
}

export function inferPortDensity(model?: string, assetKey?: string): number {
  const text = `${model || ''} ${assetKey || ''}`.toLowerCase();
  if (/(?:32c|32q|32cq|32x100|32p)/.test(text)) return 32;
  if (/(?:48|52|54|56)/.test(text)) return 48;
  if (/(?:24|28|30|20xs)/.test(text)) return 24;
  return 48;
}

export function parseInterfaceSlotPort(interfaceName: string): {
  slot: number;
  subslot: number;
  port: number;
  isHighSpeed: boolean;
} {
  const name = String(interfaceName || '').trim();
  const isHighSpeed = /(?:qsfp|fge|hge|40ge|100ge|400ge|40g|100g|400g|fortygig|hundredgig)/i.test(name);
  // Standard 3-tuple: GE1/0/24, XGE2/0/15, Gi1/1/8, HundredGigE3/0/4
  const threeTuple = name.match(/(\d+)\s*\/\s*(\d+)\s*\/\s*(\d+)$/);
  if (threeTuple) {
    return {
      slot: parseInt(threeTuple[1], 10),
      subslot: parseInt(threeTuple[2], 10),
      port: parseInt(threeTuple[3], 10),
      isHighSpeed,
    };
  }
  // 2-tuple: Eth1/49, Ethernet2/12
  const twoTuple = name.match(/(\d+)\s*\/\s*(\d+)$/);
  if (twoTuple) {
    return {
      slot: parseInt(twoTuple[1], 10),
      subslot: 0,
      port: parseInt(twoTuple[2], 10),
      isHighSpeed,
    };
  }
  const trailing = name.match(/(\d+)$/);
  return {
    slot: 1,
    subslot: 0,
    port: trailing ? parseInt(trailing[1], 10) : 1,
    isHighSpeed,
  };
}

function buildModularChassisSlots(vendorStyle: VendorStyle, heightU: number): ChassisSlotDefinition[] {
  // Cisco Catalyst 9407R (10U): 2 LPU top + 2 central SUP (Slots 3-4) + 3 LPU + Power Shelf
  if (vendorStyle === 'cisco' && heightU >= 9) {
    return [
      { slotNumber: 1, label: 'SLOT 1 · C9400-LC-48UX', kind: 'lpu_rj45', yTopFrac: 0.06, yBotFrac: 0.16, portCount: 48, portType: 'rj45' },
      { slotNumber: 2, label: 'SLOT 2 · C9400-LC-48S', kind: 'lpu_sfp', yTopFrac: 0.17, yBotFrac: 0.27, portCount: 48, portType: 'sfp' },
      { slotNumber: 3, label: 'SLOT 3 · SUP-1 ACTIVE', kind: 'mpu', yTopFrac: 0.28, yBotFrac: 0.38, portCount: 4, portType: 'mgmt' },
      { slotNumber: 4, label: 'SLOT 4 · SUP-2 STANDBY', kind: 'mpu', yTopFrac: 0.39, yBotFrac: 0.49, portCount: 4, portType: 'mgmt' },
      { slotNumber: 5, label: 'SLOT 5 · C9400-LC-48XS', kind: 'lpu_sfp', yTopFrac: 0.50, yBotFrac: 0.60, portCount: 48, portType: 'sfp' },
      { slotNumber: 6, label: 'SLOT 6 · C9400-LC-24XS', kind: 'lpu_sfp', yTopFrac: 0.61, yBotFrac: 0.71, portCount: 24, portType: 'sfp' },
      { slotNumber: 7, label: 'SLOT 7 · C9400-LC-36CQ', kind: 'lpu_qsfp', yTopFrac: 0.72, yBotFrac: 0.82, portCount: 36, portType: 'qsfp' },
      { slotNumber: 0, label: 'POWER SHELF · 4×3200W AC', kind: 'power_shelf', yTopFrac: 0.84, yBotFrac: 0.96, portCount: 0, portType: 'none' },
    ];
  }

  // Huawei CE12800 / H3C S10500X / Ruijie RG-N18000 (4U-8U+): 2 MPU top + 4 LPU + Power Shelf
  const mpuPrefix = vendorStyle === 'huawei' ? 'CE-MPUA' : vendorStyle === 'ruijie' ? 'M18000-CM' : 'LSUM1MPU';
  const lpuPrefix = vendorStyle === 'huawei' ? 'CE-L48XS' : vendorStyle === 'ruijie' ? 'M18000-48XS' : 'LSUM1LPU';
  const qsfpPrefix = vendorStyle === 'huawei' ? 'CE-L36CQ' : vendorStyle === 'ruijie' ? 'M18000-36CQ' : 'LSUM1CGQ';

  return [
    { slotNumber: 9, label: `MPU-A · ${mpuPrefix} (ACT)`, kind: 'mpu', yTopFrac: 0.06, yBotFrac: 0.16, portCount: 4, portType: 'mgmt' },
    { slotNumber: 10, label: `MPU-B · ${mpuPrefix} (STB)`, kind: 'mpu', yTopFrac: 0.17, yBotFrac: 0.27, portCount: 4, portType: 'mgmt' },
    { slotNumber: 1, label: `SLOT 1 · ${lpuPrefix}`, kind: 'lpu_sfp', yTopFrac: 0.29, yBotFrac: 0.41, portCount: 48, portType: 'sfp' },
    { slotNumber: 2, label: `SLOT 2 · ${lpuPrefix}`, kind: 'lpu_sfp', yTopFrac: 0.42, yBotFrac: 0.54, portCount: 48, portType: 'sfp' },
    { slotNumber: 3, label: `SLOT 3 · ${qsfpPrefix}`, kind: 'lpu_qsfp', yTopFrac: 0.55, yBotFrac: 0.67, portCount: 36, portType: 'qsfp' },
    { slotNumber: 4, label: `SLOT 4 · ${qsfpPrefix}`, kind: 'lpu_qsfp', yTopFrac: 0.68, yBotFrac: 0.80, portCount: 36, portType: 'qsfp' },
    { slotNumber: 0, label: 'POWER SHELF · 4×3000W N+N', kind: 'power_shelf', yTopFrac: 0.83, yBotFrac: 0.96, portCount: 0, portType: 'none' },
  ];
}

export function resolveHardwareFaceplateSpec(params: {
  vendor?: string;
  model?: string;
  role?: string;
  assetKey?: string;
  heightU?: number;
  physicalPortProfile?: DevicePhysicalPortProfile | null;
}): HardwareFaceplateSpec {
  const heightU = Math.max(1, Math.round(params.heightU || 1));
  const id = `${params.assetKey || ''} ${params.vendor || ''} ${params.model || ''} ${params.role || ''}`.toLowerCase();
  const vendorStyle = detectVendorStyle(params.vendor, params.model, params.assetKey, params.role);
  const profile = params.physicalPortProfile || null;
  const portDensity = profile && profile.total_ports > 0
    ? profile.total_ports
    : inferPortDensity(params.model, params.assetKey);

  if (vendorStyle === 'ups' || /\bups\b/.test(id)) {
    return {
      vendorStyle: 'ups',
      formFactor: 'ups',
      heightU: Math.max(2, heightU),
      portDensity: 0,
      hasModularUplinkSlot: false,
      boxBanks: [],
      chassisSlots: [],
    };
  }

  if (/(firewall|f10\d\d|secpath|usg|ngfw|防火墙)/.test(id)) {
    return {
      vendorStyle,
      formFactor: 'firewall',
      heightU,
      portDensity: 24,
      hasModularUplinkSlot: true,
      boxBanks: [
        { subslot: 0, label: 'HA / MGMT', startPort: 1, cols: 2, rows: 2, xStart: -1.45, xEnd: -1.25, kind: 'rj45' },
        { subslot: 0, label: 'GE 1/0/5-16', startPort: 5, cols: 6, rows: 2, xStart: -0.85, xEnd: -0.05, kind: 'rj45' },
        { subslot: 0, label: '10G SFP+ 17-24', startPort: 17, cols: 4, rows: 2, xStart: 0.25, xEnd: 0.82, kind: 'sfp' },
      ],
      chassisSlots: [],
    };
  }

  if (/(wireless_ac|wireless_controller|wx55|wlan|\bac\b|无线控制器)/.test(id)) {
    const startBase = profile?.slots?.[0]?.min_port ?? 0;
    const totalP = profile?.total_ports || 28;
    const sfpCnt = profile?.slots?.reduce((s, x) => s + x.sfp_count + x.qsfp_count, 0) || 4;
    const geCnt = Math.max(8, totalP - sfpCnt);
    return {
      vendorStyle,
      formFactor: 'wireless_ac',
      heightU,
      portDensity: totalP,
      hasModularUplinkSlot: false,
      boxBanks: [
        { subslot: 0, label: `GE ${startBase}-${startBase + Math.min(12, geCnt) - 1}`, startPort: startBase, cols: 6, rows: 2, xStart: -0.52, xEnd: 0.24, kind: 'rj45' },
        ...(geCnt > 12
          ? [{ subslot: 0, label: `GE ${startBase + 12}-${startBase + Math.min(24, geCnt) - 1}`, startPort: startBase + 12, cols: 6, rows: 2 as const, xStart: 0.36, xEnd: 1.12, kind: 'rj45' as const }]
          : []),
        { subslot: 1, label: `10G SFP+ ${startBase + geCnt}-${startBase + totalP - 1}`, startPort: startBase + geCnt, cols: Math.max(2, Math.min(4, Math.ceil(sfpCnt / 2))), rows: 2, xStart: 1.32, xEnd: 1.98, kind: 'sfp' },
      ],
      chassisSlots: [],
    };
  }

  if (/(patch_panel|patch panel|配线)/.test(id)) {
    return {
      vendorStyle: 'generic',
      formFactor: 'patch_panel',
      heightU,
      portDensity: 24,
      hasModularUplinkSlot: false,
      boxBanks: [],
      chassisSlots: [],
    };
  }

  if (/(server|storage|服务器|存储)/.test(id)) {
    return {
      vendorStyle: 'generic',
      formFactor: 'server',
      heightU,
      portDensity: 0,
      hasModularUplinkSlot: false,
      boxBanks: [],
      chassisSlots: [],
    };
  }

  // Modular Chassis Switch (4U+ or explicit chassis models: C9400, CE12800, S12700, S10500X, RG-N18000)
  const isModularChassis = heightU >= 4
    || /(chassis|9404|9407|9410|9504|9508|ce128|s12700|s10500|s12500|n18000|ruijie_dc_family|9904|c89e)/.test(id);
  if (isModularChassis) {
    const baseSlots = buildModularChassisSlots(vendorStyle, Math.max(4, heightU));
    // Synchronize real populated CMDB/SNMP slots (and mark empty slots as blank fillers!)
    const syncedSlots = profile && profile.slots.length > 0
      ? baseSlots.map(slot => {
          if (slot.kind === 'mpu' || slot.kind === 'power_shelf') return slot;
          const realSlot = profile.slots.find(rs => rs.slot === slot.slotNumber);
          if (!realSlot || realSlot.total_ports === 0) {
            return {
              ...slot,
              kind: 'blank' as const,
              label: `SLOT ${slot.slotNumber} · EMPTY (BLANK FILLER)`,
              portCount: 0,
              portType: 'none' as const,
            };
          }
          const dominantType = realSlot.qsfp_count > 0 && realSlot.qsfp_count >= realSlot.sfp_count
            ? 'qsfp'
            : realSlot.sfp_count >= realSlot.rj45_count
              ? 'sfp'
              : 'rj45';
          const cardKind = dominantType === 'qsfp' ? 'lpu_qsfp' : dominantType === 'sfp' ? 'lpu_sfp' : 'lpu_rj45';
          return {
            ...slot,
            kind: cardKind as SlotCardKind,
            label: `SLOT ${slot.slotNumber} · ${realSlot.total_ports}×${dominantType.toUpperCase()} (${realSlot.up_count} UP)`,
            portCount: realSlot.total_ports,
            portType: dominantType as 'sfp' | 'rj45' | 'qsfp',
          };
        })
      : baseSlots;

    return {
      vendorStyle,
      formFactor: 'chassis',
      heightU: Math.max(4, heightU),
      portDensity: profile?.total_ports || 192,
      hasModularUplinkSlot: false,
      boxBanks: [],
      chassisSlots: syncedSlots,
    };
  }

  // Fixed / Box 1U Switch — Vendor & Port-Density Specific Slot Banks
  const isCampusCopper = /(9300|s57|s5130|24p|48p|28p|52p|-t\b)/.test(id) && !/(nexus|93180|ce68|s68|s67|s6510|sfp)/.test(id);
  const hasModularUplinkSlot = /(9300|s5755|s5560|s6730)/.test(id);

  if (isCampusCopper && portDensity <= 24) {
    return {
      vendorStyle,
      formFactor: 'box',
      heightU,
      portDensity: 24,
      hasModularUplinkSlot,
      boxBanks: [
        { subslot: 0, label: 'GE 1-12', startPort: 1, cols: 6, rows: 2, xStart: -0.62, xEnd: 0.16, kind: 'rj45' },
        { subslot: 0, label: 'GE 13-24', startPort: 13, cols: 6, rows: 2, xStart: 0.34, xEnd: 1.12, kind: 'rj45' },
        {
          subslot: 1,
          label: vendorStyle === 'cisco' ? 'SLOT 1 · NM-8X' : 'SLOT 1 · 10G/25G',
          startPort: 25,
          cols: 4,
          rows: 2,
          xStart: 1.42,
          xEnd: 2.02,
          kind: 'sfp',
          modular: hasModularUplinkSlot,
        },
      ],
      chassisSlots: [],
    };
  }

  if (isCampusCopper) {
    return {
      vendorStyle,
      formFactor: 'box',
      heightU,
      portDensity: 48,
      hasModularUplinkSlot,
      boxBanks: [
        { subslot: 0, label: '1-12', startPort: 1, cols: 6, rows: 2, xStart: -1.68, xEnd: -1.00, kind: 'rj45' },
        { subslot: 0, label: '13-24', startPort: 13, cols: 6, rows: 2, xStart: -0.88, xEnd: -0.20, kind: 'rj45' },
        { subslot: 0, label: '25-36', startPort: 25, cols: 6, rows: 2, xStart: -0.08, xEnd: 0.60, kind: 'rj45' },
        { subslot: 0, label: '37-48', startPort: 37, cols: 6, rows: 2, xStart: 0.72, xEnd: 1.40, kind: 'rj45' },
        {
          subslot: 1,
          label: vendorStyle === 'cisco' ? 'SLOT 1 · NM-8X' : 'SLOT 1 · UPLINK',
          startPort: 49,
          cols: 4,
          rows: 2,
          xStart: 1.58,
          xEnd: 2.08,
          kind: 'sfp',
          modular: hasModularUplinkSlot,
        },
      ],
      chassisSlots: [],
    };
  }

  // High-density Data Center / Aggregation Optical Box Switch (48x SFP28 + 6/8x QSFP28)
  return {
    vendorStyle,
    formFactor: 'box',
    heightU,
    portDensity: 48,
    hasModularUplinkSlot: false,
    boxBanks: [
      { subslot: 0, label: '1-12', startPort: 1, cols: 6, rows: 2, xStart: -2.08, xEnd: -1.32, kind: 'sfp' },
      { subslot: 0, label: '13-24', startPort: 13, cols: 6, rows: 2, xStart: -1.24, xEnd: -0.48, kind: 'sfp' },
      { subslot: 0, label: '25-36', startPort: 25, cols: 6, rows: 2, xStart: -0.40, xEnd: 0.36, kind: 'sfp' },
      { subslot: 0, label: '37-48', startPort: 37, cols: 6, rows: 2, xStart: 0.44, xEnd: 1.20, kind: 'sfp' },
      { subslot: 1, label: 'QSFP28 49-56', startPort: 49, cols: 4, rows: 2, xStart: 1.34, xEnd: 2.08, kind: 'qsfp' },
    ],
    chassisSlots: [],
  };
}

/**
 * Resolve exact physical 3D port coordinates (x, yOffset in scene decimeters)
 * for any modular chassis slot or box-switch bank.
 */
export function resolveSlotPortCoordinates(
  spec: HardwareFaceplateSpec,
  interfaceName: string,
  deviceHeightDm: number,
): { x: number; yOffset: number; isQsfp: boolean } | null {
  const parsed = parseInterfaceSlotPort(interfaceName);

  if (spec.formFactor === 'chassis' && spec.chassisSlots.length > 0) {
    const lpuSlots = spec.chassisSlots.filter(s => s.kind !== 'power_shelf' && s.kind !== 'blank');
    const matched = lpuSlots.find(s => s.slotNumber === parsed.slot)
      || lpuSlots.find(s => s.kind.startsWith('lpu'))
      || lpuSlots[0];
    const centerFrac = (matched.yTopFrac + matched.yBotFrac) / 2;
    const slotHeight = (matched.yBotFrac - matched.yTopFrac) * deviceHeightDm;
    const isOdd = parsed.port % 2 === 1;
    const rowShift = isOdd ? slotHeight * 0.18 : -slotHeight * 0.18;
    const yOffset = (0.5 - centerFrac) * deviceHeightDm + rowShift;

    const maxCols = Math.max(2, Math.ceil(Math.max(4, matched.portCount) / 2));
    const col = Math.min(maxCols - 1, Math.floor((Math.max(1, parsed.port) - 1) / 2));
    const xStart = -1.65;
    const xEnd = 1.92;
    const x = xStart + (col / Math.max(1, maxCols - 1)) * (xEnd - xStart);
    return { x, yOffset, isQsfp: matched.portType === 'qsfp' || parsed.isHighSpeed };
  }

  if (spec.formFactor === 'box' && spec.boxBanks.length > 0) {
    // Subslot 1 (e.g. Cisco Gi1/1/1..8) targets the modular right-side uplink bank directly
    let targetBank = parsed.subslot >= 1
      ? spec.boxBanks.find(b => b.subslot >= 1)
      : undefined;
    let effectivePort = parsed.port;

    if (!targetBank) {
      if (parsed.isHighSpeed && parsed.port <= 8) {
        const qsfpBank = spec.boxBanks.find(b => b.kind === 'qsfp');
        if (qsfpBank) {
          targetBank = qsfpBank;
          effectivePort = qsfpBank.startPort + parsed.port - 1;
        }
      }
      if (!targetBank) {
        targetBank = spec.boxBanks.find(
          b => effectivePort >= b.startPort && effectivePort < b.startPort + b.cols * b.rows,
        ) || spec.boxBanks[0];
      }
    } else if (effectivePort < targetBank.startPort) {
      effectivePort = targetBank.startPort + Math.max(0, effectivePort - 1);
    }

    const offset = Math.max(0, effectivePort - targetBank.startPort);
    const col = Math.min(targetBank.cols - 1, Math.floor(offset / 2));
    const isOdd = effectivePort % 2 === 1;
    const x = targetBank.cols <= 1
      ? (targetBank.xStart + targetBank.xEnd) / 2
      : targetBank.xStart + (col / (targetBank.cols - 1)) * (targetBank.xEnd - targetBank.xStart);
    const yOffset = isOdd ? 0.044 : -0.084;
    return { x, yOffset, isQsfp: targetBank.kind === 'qsfp' };
  }

  return null;
}
