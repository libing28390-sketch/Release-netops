import { describe, expect, it } from 'vitest';
import { formatUptimeSeconds } from './formatUptimeSeconds';

describe('formatUptimeSeconds', () => {
  it.each([null, undefined, '', Number.NaN, Number.POSITIVE_INFINITY, -1])(
    'returns no-data for %s',
    (value) => {
      expect(formatUptimeSeconds(value, 'zh')).toBe('--');
    },
  );

  it('formats seconds as days and hours in Chinese', () => {
    expect(formatUptimeSeconds(90061, 'zh')).toBe('1天 1小时');
  });

  it('formats seconds as hours and minutes in English', () => {
    expect(formatUptimeSeconds(3661, 'en')).toBe('1h 1m');
  });
});
