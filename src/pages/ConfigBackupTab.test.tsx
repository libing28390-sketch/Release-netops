import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DateRangeCalendar } from './ConfigBackupTab';

describe('Config backup date range calendar', () => {
  it('labels dates, reflects the active quick range, and preserves range selection', () => {
    const onChange = vi.fn();

    render(
      <DateRangeCalendar
        start="2026-10-01"
        end="2026-10-07"
        today="2026-10-07"
        zh={false}
        onChange={onChange}
      />,
    );

    expect(screen.getByText('October 2026').getAttribute('aria-live')).toBe('polite');
    expect(screen.getByRole('button', { name: 'October 2, 2026' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'October 1, 2026' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Last 7d' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Next month' }).hasAttribute('disabled')).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'October 2, 2026' }));
    expect(onChange).toHaveBeenCalledWith('2026-10-02', '');

    fireEvent.click(screen.getByRole('button', { name: 'Previous month' }));
    expect(screen.getByText('September 2026')).toBeTruthy();
  });

  it('localizes the calendar navigation and date names', () => {
    render(
      <DateRangeCalendar
        start="2026-10-01"
        end=""
        today="2026-10-07"
        zh
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '上个月' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '2026年10月2日' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '近7天' }).getAttribute('aria-pressed')).toBe('false');
  });
});
