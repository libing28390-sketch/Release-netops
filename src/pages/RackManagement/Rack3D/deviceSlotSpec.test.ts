import { describe, expect, it } from 'vitest';
import {
  detectVendorStyle,
  parseInterfaceSlotPort,
  resolveHardwareFaceplateSpec,
  resolveSlotPortCoordinates,
} from './deviceSlotSpec';

describe('slot-driven hardware profile engine', () => {
  it('identifies Cisco, Huawei, Ruijie, H3C, and UPS vendor styles', () => {
    expect(detectVendorStyle('Cisco', 'C9300-48P')).toBe('cisco');
    expect(detectVendorStyle('Huawei', 'CE6881-48S6CQ')).toBe('huawei');
    expect(detectVendorStyle('Ruijie', 'RG-S6510-48VS8CQ')).toBe('ruijie');
    expect(detectVendorStyle('H3C', 'S10508X-G')).toBe('h3c');
    expect(detectVendorStyle('APC', 'SRT3000RMXLI', 'generic_ups_2u', 'ups')).toBe('ups');
  });

  it('differentiates 24-port and 48-port Cisco Catalyst 9300 with modular NM-8X uplink slot', () => {
    const c24 = resolveHardwareFaceplateSpec({ vendor: 'Cisco', model: 'C9300-24P', heightU: 1 });
    const c48 = resolveHardwareFaceplateSpec({ vendor: 'Cisco', model: 'C9300-48P', heightU: 1 });

    expect(c24.formFactor).toBe('box');
    expect(c24.portDensity).toBe(24);
    expect(c24.hasModularUplinkSlot).toBe(true);
    expect(c24.boxBanks).toHaveLength(3); // 2x12 GE + right NM-8X slot

    expect(c48.portDensity).toBe(48);
    expect(c48.boxBanks).toHaveLength(5); // 4x12 GE + right NM-8X slot

    const downlink = resolveSlotPortCoordinates(c48, 'Gi1/0/1', 0.4245);
    const uplink = resolveSlotPortCoordinates(c48, 'Te1/1/1', 0.4245);
    expect(downlink).not.toBeNull();
    expect(uplink).not.toBeNull();
    expect(uplink!.x).toBeGreaterThan(downlink!.x);
  });

  it('builds slot-by-slot modular chassis specs and maps slot/subslot/port to distinct vertical rows', () => {
    const c9407 = resolveHardwareFaceplateSpec({ vendor: 'Cisco', model: 'C9407R', heightU: 10 });
    const ce12808 = resolveHardwareFaceplateSpec({ vendor: 'Huawei', model: 'CE12808', heightU: 8 });

    expect(c9407.formFactor).toBe('chassis');
    expect(c9407.chassisSlots.some(s => s.kind === 'mpu' && s.slotNumber === 3)).toBe(true);
    expect(c9407.chassisSlots.some(s => s.kind === 'power_shelf')).toBe(true);

    expect(ce12808.formFactor).toBe('chassis');
    const slot1Port1 = resolveSlotPortCoordinates(ce12808, 'XGE1/0/1', 3.55);
    const slot3Port1 = resolveSlotPortCoordinates(ce12808, '100GE3/0/1', 3.55);
    expect(slot1Port1).not.toBeNull();
    expect(slot3Port1).not.toBeNull();
    expect(slot1Port1!.yOffset).toBeGreaterThan(slot3Port1!.yOffset);
    expect(slot3Port1!.isQsfp).toBe(true);
  });

  it('resolves rack-mount UPS form factor cleanly for 2U and 3U units', () => {
    const ups = resolveHardwareFaceplateSpec({ vendor: 'Huawei', model: 'UPS2000-G-10KRTL', role: 'ups', heightU: 3 });
    expect(ups.formFactor).toBe('ups');
    expect(ups.heightU).toBe(3);
  });

  it('parses standard 3-tuple and 2-tuple interface names into slot/subslot/port', () => {
    expect(parseInterfaceSlotPort('Ten-GigabitEthernet2/0/15')).toEqual({
      slot: 2,
      subslot: 0,
      port: 15,
      isHighSpeed: false,
    });
    expect(parseInterfaceSlotPort('HundredGigE3/1/4')).toEqual({
      slot: 3,
      subslot: 1,
      port: 4,
      isHighSpeed: true,
    });
  });

  it('syncs real CMDB/SNMP port count and marks empty chassis slots as blank fillers', () => {
    const acSpec = resolveHardwareFaceplateSpec({
      vendor: 'H3C',
      model: 'WX5540H-HCL',
      role: 'wireless_controller',
      heightU: 1,
      physicalPortProfile: {
        source: 'CMDB+SNMP',
        total_ports: 28,
        up_count: 3,
        down_count: 25,
        slots: [{ slot: 1, total_ports: 28, up_count: 3, rj45_count: 24, sfp_count: 4, qsfp_count: 0, min_port: 0, max_port: 27 }],
        ports: [],
      },
    });
    expect(acSpec.portDensity).toBe(28);
    expect(acSpec.boxBanks).toHaveLength(3);

    const chassisSpec = resolveHardwareFaceplateSpec({
      vendor: 'Huawei',
      model: 'CE12808',
      role: 'switch',
      heightU: 8,
      physicalPortProfile: {
        source: 'CMDB+SNMP',
        total_ports: 48,
        up_count: 12,
        down_count: 36,
        slots: [{ slot: 1, total_ports: 48, up_count: 12, rj45_count: 0, sfp_count: 48, qsfp_count: 0, min_port: 1, max_port: 48 }],
        ports: [],
      },
    });
    const slot1 = chassisSpec.chassisSlots.find(s => s.slotNumber === 1);
    const slot2 = chassisSpec.chassisSlots.find(s => s.slotNumber === 2);
    expect(slot1?.kind).toBe('lpu_sfp');
    expect(slot1?.portCount).toBe(48);
    expect(slot2?.kind).toBe('blank');
    expect(slot2?.portCount).toBe(0);
  });
});
