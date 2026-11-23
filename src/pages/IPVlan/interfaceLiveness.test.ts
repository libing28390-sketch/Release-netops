import { describe, expect, it } from 'vitest';
import {
  describeInterfaceLiveness,
  formatLivenessAge,
  formatLivenessWindow,
  interfaceLivenessSourceLabel,
  type InterfaceLiveness,
} from './interfaceLiveness';

const live = (overrides: Partial<InterfaceLiveness> = {}): InterfaceLiveness => ({
  state: 'up',
  freshness: 'recent',
  source: 'snmp',
  age_minutes: 5,
  window_minutes: 1440,
  alive: true,
  ...overrides,
});

describe('formatLivenessAge', () => {
  it.each([
    [0, '0 分钟前', '0m ago'],
    [59, '59 分钟前', '59m ago'],
    [60, '1 小时前', '1h ago'],
    [2879, '47 小时前', '47h ago'],
    [2880, '2 天前', '2d ago'],
    [16918, '11 天前', '11d ago'],
  ])('%s minutes -> %s', (minutes, zh, en) => {
    expect(formatLivenessAge(minutes, true)).toBe(zh);
    expect(formatLivenessAge(minutes, false)).toBe(en);
  });

  it('is empty when the observation time is unknown', () => {
    expect(formatLivenessAge(null, true)).toBe('');
    expect(formatLivenessAge(undefined, true)).toBe('');
    expect(formatLivenessAge(Number.NaN, true)).toBe('');
    expect(formatLivenessAge(-1, true)).toBe('');
  });
});

describe('formatLivenessWindow', () => {
  it('prefers whole days, then hours, then minutes', () => {
    expect(formatLivenessWindow(1440, true)).toBe('1 天');
    expect(formatLivenessWindow(5760, true)).toBe('4 天');
    expect(formatLivenessWindow(360, true)).toBe('6 小时');
    expect(formatLivenessWindow(90, true)).toBe('90 分钟');
  });

  it('falls back to the backend default of one day', () => {
    expect(formatLivenessWindow(undefined, true)).toBe('1 天');
    expect(formatLivenessWindow(0, false)).toBe('1 d');
  });
});

describe('interfaceLivenessSourceLabel', () => {
  it('names the collection source', () => {
    expect(interfaceLivenessSourceLabel('snmp', true)).toBe('SNMP 接口表');
    expect(interfaceLivenessSourceLabel('cli_snapshot', true)).toBe('CLI 接口采集');
    expect(interfaceLivenessSourceLabel(undefined, true)).toBe('未知来源');
  });
});

describe('describeInterfaceLiveness', () => {
  it('shows nothing without an interface state', () => {
    expect(describeInterfaceLiveness(undefined, true)).toBeNull();
    expect(describeInterfaceLiveness(null, true)).toBeNull();
    expect(describeInterfaceLiveness(live({ state: 'unknown', freshness: 'unknown' }), true)).toBeNull();
  });

  it('marks a recently collected up interface as current', () => {
    const badge = describeInterfaceLiveness(live(), true);
    expect(badge).toMatchObject({ label: '接口 up', ageText: '5 分钟前', tone: 'current' });
    expect(badge?.title).toBe('设备接口地址，存活以接口状态为准（来源：SNMP 接口表，5 分钟前采集）');
  });

  it('marks an up state older than the window as stale and says so', () => {
    const badge = describeInterfaceLiveness(
      live({ freshness: 'historical', source: 'cli_snapshot', age_minutes: 16918, alive: false }),
      true,
    );
    expect(badge).toMatchObject({ label: '接口 up', ageText: '11 天前', tone: 'stale' });
    expect(badge?.title).toContain('来源：CLI 接口采集');
    expect(badge?.title).toContain('已超过 1 天，可能不是当前状态');
  });

  it('uses the configured window in the stale hint', () => {
    const badge = describeInterfaceLiveness(
      live({ freshness: 'historical', age_minutes: 600, window_minutes: 360, alive: false }),
      true,
    );
    expect(badge?.title).toContain('已超过 6 小时');
  });

  it.each([
    ['down', '接口 down', 'Intf down'],
    ['admin_down', '接口已关闭', 'Intf shut'],
  ] as const)('treats %s as down even when it is fresh', (state, zhLabel, enLabel) => {
    expect(describeInterfaceLiveness(live({ state, alive: false }), true)).toMatchObject({ label: zhLabel, tone: 'down' });
    expect(describeInterfaceLiveness(live({ state, alive: false }), false)).toMatchObject({ label: enLabel, tone: 'down' });
  });

  it('omits the age when the observation time is unknown', () => {
    const badge = describeInterfaceLiveness(live({ age_minutes: null }), true);
    expect(badge?.ageText).toBe('');
    expect(badge?.title).toBe('设备接口地址，存活以接口状态为准（来源：SNMP 接口表）');
  });
});
