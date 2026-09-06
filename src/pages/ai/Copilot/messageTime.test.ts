import { describe, expect, it } from 'vitest';
import { formatMessageDateTime } from './messageTime';

describe('formatMessageDateTime', () => {
  it('shows the full local date, weekday, and time for an ISO timestamp', () => {
    const timestamp = '2026-09-06T22:36:00+08:00';
    const formatted = formatMessageDateTime(timestamp, 'zh-CN');
    const expected = new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      weekday: 'long',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(timestamp));

    expect(formatted).toBe(expected);
    expect(formatted).toContain('2026');
    expect(formatted).toContain('星期日');

    const parts = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    }).formatToParts(new Date(timestamp));
    const hour = parts.find((part) => part.type === 'hour')?.value;
    const minute = parts.find((part) => part.type === 'minute')?.value;
    expect(hour).toBeDefined();
    expect(minute).toBeDefined();
    expect(formatted).toContain(`${hour}:${minute}`);
  });

  it('preserves a legacy time-only value without exposing an invalid date', () => {
    expect(formatMessageDateTime('22:36', 'zh-CN')).toBe('22:36');
    expect(formatMessageDateTime(undefined, 'zh-CN')).toBe('');
  });
});
