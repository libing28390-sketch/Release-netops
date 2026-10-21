import { describe, expect, it } from 'vitest';
import { getTimeColumnScrollTop } from './DateTimePicker';

describe('getTimeColumnScrollTop', () => {
  it.each([32, 36])('centers each hour value when the rendered row is %i pixels high', (rowHeight) => {
    const viewportHeight = 160;
    const padding = 64;
    const maxHourScrollTop = padding * 2 + 24 * rowHeight - viewportHeight;

    for (const hour of [0, 12, 23]) {
      const selectedTop = padding + hour * rowHeight;
      const scrollTop = getTimeColumnScrollTop(0, 0, viewportHeight, selectedTop, rowHeight);
      const selectedVisibleTop = selectedTop - scrollTop;
      const expectedVisibleTop = (viewportHeight - rowHeight) / 2;

      expect(selectedVisibleTop).toBe(expectedVisibleTop);
      expect(scrollTop).toBeGreaterThanOrEqual(0);
      expect(scrollTop).toBeLessThanOrEqual(maxHourScrollTop);
    }
  });

  it.each([32, 36])('centers first, middle and last minute values when rows are %i pixels high', (rowHeight) => {
    const viewportHeight = 160;
    const padding = 64;
    const maxMinuteScrollTop = padding * 2 + 60 * rowHeight - viewportHeight;

    for (const minute of [0, 33, 59]) {
      const selectedTop = padding + minute * rowHeight;
      const scrollTop = getTimeColumnScrollTop(0, 0, viewportHeight, selectedTop, rowHeight);
      const selectedVisibleTop = selectedTop - scrollTop;
      const expectedVisibleTop = (viewportHeight - rowHeight) / 2;

      expect(selectedVisibleTop).toBe(expectedVisibleTop);
      expect(scrollTop).toBeGreaterThanOrEqual(0);
      expect(scrollTop).toBeLessThanOrEqual(maxMinuteScrollTop);
    }
  });

  it('uses the current scroll offset and actual DOM positions', () => {
    const scrollTop = getTimeColumnScrollTop(256, 100, 160, 340, 36);

    expect(scrollTop).toBe(434);
    expect(256 + 340 - 100 - scrollTop).toBe(62);
  });
});
