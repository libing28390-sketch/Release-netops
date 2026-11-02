import { describe, expect, it } from 'vitest';
import { formatLocalDateInput, getDefaultLeaseDateRange } from './DHCPLeaseTab';

describe('DHCP lease local date defaults', () => {
  it('formats date input values from local calendar fields, not UTC serialization', () => {
    const localDate = {
      getFullYear: () => 2026,
      getMonth: () => 9,
      getDate: () => 29,
    } as Pick<Date, 'getFullYear' | 'getMonth' | 'getDate'>;

    expect(formatLocalDateInput(localDate)).toBe('2026-10-29');
  });

  it('defaults a new lease to the local date and seven local calendar days later', () => {
    const now = new Date(2026, 9, 29, 0, 30);
    const expectedEnd = new Date(now);
    expectedEnd.setDate(expectedEnd.getDate() + 7);

    expect(getDefaultLeaseDateRange(now)).toEqual({
      start: formatLocalDateInput(now),
      end: formatLocalDateInput(expectedEnd),
    });
  });
});
