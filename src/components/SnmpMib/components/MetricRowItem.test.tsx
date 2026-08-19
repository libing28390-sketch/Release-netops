import { describe, it, expect } from 'vitest';
import {
  METRIC_CATALOG,
  catalogEntry,
  createDefinition,
  allowedModes,
  modeLabel,
  metricLabel,
  toPayload,
  hasDefinition,
} from './MetricRowItem';
import { DEFAULT_INTERFACE_CONFIG, INTERFACE_OID_FIELDS } from './InterfaceConfigSection';

describe('MetricRowItem & InterfaceConfig tests', () => {
  it('should return catalog entries correctly', () => {
    expect(catalogEntry('cpu')).toBeDefined();
    expect(catalogEntry('cpu')?.defaultUnit).toBe('%');
    expect(catalogEntry('temperature')?.defaultUnit).toBe('°C');
    expect(catalogEntry('fan')?.defaultMode).toBe('status_code');
  });

  it('should provide localized labels', () => {
    expect(metricLabel('cpu', true)).toBe('CPU 使用率');
    expect(metricLabel('cpu', false)).toBe('CPU');
    expect(modeLabel('direct_percent', true)).toBe('直接百分比（Gauge）');
    expect(modeLabel('status_code', true)).toBe('状态码 → 布尔值');
  });

  it('should restrict allowed modes based on output type', () => {
    expect(allowedModes('fan')).toEqual(['status_code']);
    expect(allowedModes('temperature')).toEqual(['direct_value']);
    expect(allowedModes('cpu')).toContain('direct_percent');
    expect(allowedModes('cpu')).toContain('used_total_percent');
  });

  it('should build valid payload when definition is configured', () => {
    const def = createDefinition('cpu');
    def.oid = '1.3.6.1.4.1.9.9.109.1.1.1.1.3';
    def.scale = '0.1';
    def.offset = '0';
    expect(hasDefinition(def)).toBe(true);

    const payload = toPayload(def);
    expect(payload.oid).toBe('1.3.6.1.4.1.9.9.109.1.1.1.1.3');
    expect(payload.scale).toBe(0.1);
    expect(payload.mode).toBe('direct_percent');
  });

  it('should define all interface traffic/error OID fields with IF-MIB defaults', () => {
    expect(INTERFACE_OID_FIELDS.length).toBe(28);
    expect(DEFAULT_INTERFACE_CONFIG.if_name_oid).toBe('1.3.6.1.2.1.31.1.1.1.1');
    expect(DEFAULT_INTERFACE_CONFIG.if_hc_in_octets_oid).toBe('1.3.6.1.2.1.31.1.1.1.6');
    expect(DEFAULT_INTERFACE_CONFIG.if_hc_in_ucast_pkts_oid).toBe('1.3.6.1.2.1.31.1.1.1.7');
    expect(DEFAULT_INTERFACE_CONFIG.dot3_hc_fcs_errors_oid).toBe('1.3.6.1.2.1.10.7.11.1.2');
    expect(DEFAULT_INTERFACE_CONFIG.if_oper_status_oid).toBe('1.3.6.1.2.1.2.2.1.8');
  });
});
