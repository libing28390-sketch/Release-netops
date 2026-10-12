import { describe, it, expect } from 'vitest';
import {
  normalizeRackToVM,
  normalizeHealthStatus,
  calculateDeviceCoordinates,
  U_HEIGHT_3D,
  CHASSIS_DEPTH_FULL,
  CHASSIS_DEPTH_HALF
} from '../rackViewModel';
import { RackLayout, RackDevice } from '../../types';

describe('RackViewModel Adapter & Quality Validator', () => {
  const baseRack: RackLayout = {
    id: 'rack-01',
    name: 'DC01-A01',
    datacenter: 'BJ-DC',
    room: 'Server-Room-1',
    row: 'Row-A',
    total_u: 42,
    width_mm: 600,
    depth_mm: 1000,
    description: 'Core Rack',
    status: 'active',
    front_used: 0,
    rear_used: 0,
    total_used: 0,
    available_u: 42,
    devices: []
  };

  it('should correctly normalize a standard 42U rack with 1U/2U/4U valid devices', () => {
    const devices: RackDevice[] = [
      {
        id: 'dev-1',
        name: 'SW-CORE-01',
        rack_id: 'rack-01',
        device_type_id: 'dt-switch-2u',
        start_u: 40,
        position: 'front',
        status: 'active',
        serial_number: 'SN123456',
        asset_id: 'asset-01',
        model: 'CE6850',
        vendor: 'Huawei',
        u_height: 2,
        device_role: 'switch',
        is_full_depth: 1,
        power_watts: 350
      },
      {
        id: 'dev-2',
        name: 'SRV-COMPUTE-01',
        rack_id: 'rack-01',
        device_type_id: 'dt-server-4u',
        start_u: 1,
        position: 'front',
        status: 'active',
        serial_number: 'SN789012',
        asset_id: 'asset-02',
        model: 'PowerEdge R750',
        vendor: 'Dell',
        u_height: 4,
        device_role: 'server',
        is_full_depth: 1,
        power_watts: 800
      }
    ];

    const vm = normalizeRackToVM({ ...baseRack, devices });

    expect(vm.totalU).toBe(42);
    expect(vm.dataQuality.valid).toBe(true);
    expect(vm.validDevices.length).toBe(2);
    expect(vm.invalidDevices.length).toBe(0);
    expect(vm.ratedPowerTotalWatts).toBe(1150);

    // Verify dev-1 (2U at start_u 40 -> spans U40 and U41)
    const dev1 = vm.devices.find(d => d.id === 'dev-1')!;
    expect(dev1.startU).toBe(40);
    expect(dev1.heightU).toBe(2);
    expect(dev1.endU).toBe(41);
    expect(dev1.coordinates.centerY).toBeCloseTo((40 - 1 + 1) * U_HEIGHT_3D, 4);

    // Verify dev-2 (4U at start_u 1 -> spans U1 to U4)
    const dev2 = vm.devices.find(d => d.id === 'dev-2')!;
    expect(dev2.startU).toBe(1);
    expect(dev2.heightU).toBe(4);
    expect(dev2.endU).toBe(4);
    expect(dev2.coordinates.centerY).toBeCloseTo((1 - 1 + 2) * U_HEIGHT_3D, 4);
  });

  it('should support 24U and 48U rack capacities and calculate correct coordinates', () => {
    const rack24 = normalizeRackToVM({ ...baseRack, total_u: 24 });
    expect(rack24.totalU).toBe(24);
    expect(rack24.heightMm).toBe(Math.round(24 * 44.45));

    const rack48 = normalizeRackToVM({ ...baseRack, total_u: 48 });
    expect(rack48.totalU).toBe(48);
    expect(rack48.heightMm).toBe(Math.round(48 * 44.45));
  });

  it('should detect U-overflow and out-of-bounds devices without crashing', () => {
    const overflowDevices: RackDevice[] = [
      {
        id: 'bad-dev-1',
        name: 'OVERFLOW-DEVICE',
        rack_id: 'rack-01',
        device_type_id: 'dt-switch-4u',
        start_u: 41, // 41 + 4 - 1 = 44 > 42U
        position: 'front',
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: 'S6800',
        vendor: 'H3C',
        u_height: 4,
        device_role: 'switch',
        is_full_depth: 1
      },
      {
        id: 'bad-dev-2',
        name: 'NEGATIVE-U-DEVICE',
        rack_id: 'rack-01',
        device_type_id: 'dt-switch-1u',
        start_u: 0,
        position: 'front',
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: 'Nexus 9300',
        vendor: 'Cisco',
        u_height: 1,
        device_role: 'switch',
        is_full_depth: 0
      }
    ];

    const vm = normalizeRackToVM({ ...baseRack, devices: overflowDevices });

    expect(vm.invalidDevices.length).toBe(2);
    expect(vm.dataQuality.valid).toBe(false);
    expect(vm.invalidDevices[0].dataQuality.issues.length).toBeGreaterThan(0);
    expect(vm.invalidDevices[1].dataQuality.issues.length).toBeGreaterThan(0);
  });

  it('should detect U-position overlaps on the same face', () => {
    const overlappingDevices: RackDevice[] = [
      {
        id: 'dev-a',
        name: 'SWITCH-A',
        rack_id: 'rack-01',
        device_type_id: 'dt-1',
        start_u: 20,
        position: 'front',
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: '',
        vendor: '',
        u_height: 2,
        device_role: 'switch',
        is_full_depth: 0
      },
      {
        id: 'dev-b',
        name: 'SWITCH-B',
        rack_id: 'rack-01',
        device_type_id: 'dt-1',
        start_u: 21, // Overlaps with U20-U21 of dev-a
        position: 'front',
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: '',
        vendor: '',
        u_height: 1,
        device_role: 'switch',
        is_full_depth: 0
      }
    ];

    const vm = normalizeRackToVM({ ...baseRack, devices: overlappingDevices });
    expect(vm.invalidDevices.some(d => d.id === 'dev-b')).toBe(true);
    expect(vm.invalidDevices.find(d => d.id === 'dev-b')?.dataQuality.issues[0]).toContain('空间重叠');
  });

  it('should handle full-depth vs half-depth Z positions correctly', () => {
    const full = calculateDeviceCoordinates(10, 1, 'front', true);
    expect(full.depth).toBe(CHASSIS_DEPTH_FULL);
    expect(full.centerZ).toBe(0);

    const halfFront = calculateDeviceCoordinates(10, 1, 'front', false);
    expect(halfFront.depth).toBe(CHASSIS_DEPTH_HALF);
    expect(halfFront.centerZ).toBeGreaterThan(0);

    const halfRear = calculateDeviceCoordinates(10, 1, 'rear', false);
    expect(halfRear.depth).toBe(CHASSIS_DEPTH_HALF);
    expect(halfRear.centerZ).toBeLessThan(0);
  });

  it('scales device depth with a non-standard rack depth', () => {
    const wallRack = normalizeRackToVM({
      ...baseRack,
      width_mm: 450,
      depth_mm: 450,
      devices: [{
        id: 'wall-full-depth',
        name: 'WALL-FULL-DEPTH',
        rack_id: 'rack-01',
        device_type_id: 'dt-wall',
        start_u: 1,
        position: 'full_depth',
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: '',
        vendor: '',
        u_height: 1,
        device_role: 'switch',
        is_full_depth: 0,
      }],
    });
    const device = wallRack.devices[0];
    expect(device.coordinates.depth).toBeCloseTo(3.375, 5);
    expect(device.coordinates.depth).toBeLessThan(CHASSIS_DEPTH_FULL);
    expect(device.coordinates.width).toBeCloseTo(3.5795, 4);
    expect(device.coordinates.width).toBeLessThan(4.786);
  });

  it('should normalize health telemetry accurately and NOT fake unknown as healthy', () => {
    // Missing health
    expect(normalizeHealthStatus(undefined, 'active')).toBe('unknown');

    // Offline lifecycle
    expect(normalizeHealthStatus(undefined, 'offline')).toBe('offline');

    // Healthy
    expect(normalizeHealthStatus({ status: 'healthy', cpu_usage: 25 }, 'active')).toBe('healthy');

    // Warning from status
    expect(normalizeHealthStatus({ status: 'warning', warning_open_alerts: 1 }, 'active')).toBe('warning');

    // Critical from status
    expect(normalizeHealthStatus({ status: 'critical', critical_open_alerts: 2 }, 'active')).toBe('critical');

    // Implicit critical from high CPU
    expect(normalizeHealthStatus({ cpu_usage: 95 }, 'active')).toBe('critical');

    // Implicit warning from elevated memory
    expect(normalizeHealthStatus({ memory_usage: 82 }, 'active')).toBe('warning');

    // Implicit critical from temperature
    expect(normalizeHealthStatus({ temp: 78 }, 'active')).toBe('critical');
  });

  it('should handle unknown position gracefully by defaulting to front and recording issue', () => {
    const weirdDevice: RackDevice = {
      id: 'weird-1',
      name: 'UNKNOWN-POS',
      rack_id: 'rack-01',
      device_type_id: 'dt-1',
      start_u: 10,
      position: 'side-mounted',
      status: 'active',
      serial_number: '',
      asset_id: '',
      model: '',
      vendor: '',
      u_height: 1,
      device_role: 'switch',
      is_full_depth: 0
    };

    const vm = normalizeRackToVM({ ...baseRack, devices: [weirdDevice] });
    const dev = vm.devices.find(d => d.id === 'weird-1')!;
    expect(dev.face).toBe('front');
    expect(dev.dataQuality.issues.some(i => i.includes('未知朝向'))).toBe(true);
  });

  it('does not treat string zero as full-depth and exposes unknown height explicitly', () => {
    const devices: RackDevice[] = [
      {
        id: 'string-zero',
        name: 'STRING-ZERO',
        rack_id: 'rack-01',
        device_type_id: 'dt-1',
        start_u: 10,
        position: 'front',
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: '',
        vendor: '',
        u_height: 1,
        device_role: 'switch',
        is_full_depth: '0' as unknown as number,
      },
      {
        id: 'unknown-height',
        name: 'UNKNOWN-HEIGHT',
        rack_id: 'rack-01',
        device_type_id: 'dt-2',
        start_u: 12,
        position: 'front',
        height_u: null,
        status: 'active',
        serial_number: '',
        asset_id: '',
        model: '',
        vendor: '',
        u_height: 0,
        device_role: 'switch',
        is_full_depth: 0,
      },
    ];

    const vm = normalizeRackToVM({ ...baseRack, devices });
    const halfDepth = vm.devices.find(device => device.id === 'string-zero')!;
    const unknownHeight = vm.devices.find(device => device.id === 'unknown-height')!;
    expect(halfDepth.isFullDepth).toBe(false);
    expect(unknownHeight.heightKnown).toBe(false);
    expect(unknownHeight.dataQuality.valid).toBe(false);
    expect(unknownHeight.heightU).toBe(1); // bounded render placeholder, not a data claim
  });
});
