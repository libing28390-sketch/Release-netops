import { describe, expect, it } from 'vitest';
import { isIntegratedGpuRenderer, resolveRoomRenderBudget } from './gpuProfile';
import { computeRackPowerMetrics, computeRackThermalMetrics } from './DataCenterRoomScene';
import { RackSummary } from '../types';

const sampleRack = (watts: number, pct?: number): RackSummary => ({
  id: 'r1',
  name: 'J-01',
  total_u: 42,
  used_u: watts > 0 ? 9 : 0,
  available_u: watts > 0 ? 33 : 42,
  u_utilization_pct: watts > 0 ? 21 : 0,
  power_used_watts: watts,
  power_utilization_pct: pct ?? null,
  device_count: watts > 0 ? 9 : 0,
  front_used: watts > 0 ? 9 : 0,
  rear_used: 0,
  monitored_device_count: 0,
  healthy_device_count: 0,
  offline_device_count: 0,
  unknown_monitoring_device_count: 0,
  unlinked_asset_count: 0,
  unmonitored_device_count: 0,
  invalid_device_count: 0,
  health_status: watts > 0 ? 'healthy' : 'empty',
  data_quality_status: 'complete',
  site_label: 'WH-DC-01',
  status: 'active',
  description: '',
  created_at: '',
  updated_at: '',
});

describe('gpuProfile integrated GPU optimization', () => {
  it('detects common Intel/AMD integrated and software renderers accurately', () => {
    expect(isIntegratedGpuRenderer('ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)')).toBe(true);
    expect(isIntegratedGpuRenderer('ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11)')).toBe(true);
    expect(isIntegratedGpuRenderer('AMD Radeon(TM) Graphics')).toBe(true);
    expect(isIntegratedGpuRenderer('Google SwiftShader')).toBe(true);
    expect(isIntegratedGpuRenderer('')).toBe(true);
  });

  it('recognizes discrete GPUs for high quality defaults', () => {
    expect(isIntegratedGpuRenderer('ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11)')).toBe(false);
    expect(isIntegratedGpuRenderer('AMD Radeon RX 7800 XT')).toBe(false);
    expect(isIntegratedGpuRenderer('Intel(R) Arc(TM) A750 Graphics')).toBe(false);
  });

  it('disables shadows, HiDPI supersampling, and DOM badge flood while keeping IBL parity in eco mode', () => {
    const eco = resolveRoomRenderBudget('eco', 60);
    expect(eco.shadows).toBe(false);
    expect(eco.useIbl).toBe(true);
    expect(eco.dpr).toEqual([1, 1]);
    expect(eco.airflowDefault).toBe(false);
    expect(eco.maxHtmlLabels).toBeLessThanOrEqual(12);

    const highLarge = resolveRoomRenderBudget('high', 60);
    expect(highLarge.shadows).toBe(false);
    expect(highLarge.dpr[1]).toBeLessThanOrEqual(1.25);
  });

  it('produces distinct power load and thermal CFD metrics for active vs idle racks', () => {
    const activePower = computeRackPowerMetrics(sampleRack(1800));
    const idlePower = computeRackPowerMetrics(sampleRack(0));
    expect(activePower.kw).toBe(1.8);
    expect(activePower.utilizationPct).toBe(30);
    expect(activePower.color).not.toBe(idlePower.color);

    const activeThermal = computeRackThermalMetrics(sampleRack(1800));
    const idleThermal = computeRackThermalMetrics(sampleRack(0));
    expect(activeThermal.exhaustTempC).toBeCloseTo(31.2, 1);
    expect(idleThermal.exhaustTempC).toBeCloseTo(19.5, 1);
    expect(activeThermal.plumeIntensity).toBeGreaterThan(0);
    expect(idleThermal.plumeIntensity).toBe(0);
    expect(activeThermal.color).toBe('#f59e0b');
    expect(idleThermal.color).toBe('#1d4ed8');
  });
});
