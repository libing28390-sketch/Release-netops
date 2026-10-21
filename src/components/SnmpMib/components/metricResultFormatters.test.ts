import { describe, expect, it } from 'vitest';
import {
  formatMetricValue,
  formatUptime,
  summarizeRawValue,
} from './metricResultFormatters';

describe('SNMP metric result formatters', () => {
  it('renders uptime seconds as a readable duration', () => {
    expect(formatUptime(14974, true)).toBe('4小时 9分钟 34秒');
    expect(formatUptime(14974, false)).toBe('4h 9m 34s');
    expect(formatMetricValue('uptime', { value: 14974, unit: 's' }, true)).toBe('4小时 9分钟 34秒');
  });

  it('supports common uptime string formats', () => {
    expect(formatUptime('1d 2h 3m 4s', true)).toBe('1天 2小时 3分钟 4秒');
    expect(formatUptime('01:02:03', false)).toBe('1h 2m 3s');
  });

  it('keeps non-uptime values and units unchanged', () => {
    expect(formatMetricValue('temperature', { value: 45, unit: '°C' }, true)).toBe('45 °C');
    expect(formatMetricValue('fan', { value: true, unit: 'bool' }, true)).toBe('正常');
  });

  it('summarizes repeated raw status codes instead of expanding every row', () => {
    expect(summarizeRawValue([2, 2, 2, 3], true)).toBe('2 × 3项；3');
    expect(summarizeRawValue('2, 2, 2, 3', false)).toBe('2 × 3 items, 3');
  });
});
