import { describe, expect, it } from 'vitest';
import { formatMessageDateTime } from './messageTime';

describe('formatMessageDateTime', () => {
  it('shows the full local date, weekday, and time for an ISO timestamp', () => {
    const formatted = formatMessageDateTime('2026-09-06T22:36:00+08:00', 'zh-CN');

    expect(formatted).toContain('2026');
    expect(formatted).toContain('9');
    expect(formatted).toContain('6');
    expect(formatted).toContain('星期日');
    expect(formatted).toContain('22:36');
  });

  it('preserves a legacy time-only value without exposing an invalid date', () => {
    expect(formatMessageDateTime('22:36', 'zh-CN')).toBe('22:36');
    expect(formatMessageDateTime(undefined, 'zh-CN')).toBe('');
  });
});
