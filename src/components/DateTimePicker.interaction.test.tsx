import React from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DateTimePicker from './DateTimePicker';

const originalRectDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'getBoundingClientRect');
const originalClientHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
const originalOffsetHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
const originalScrollToDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo');

const installTimeColumnGeometry = () => {
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get() {
      if ((this as HTMLElement).matches('[data-time-column]')) return 160;
      return originalClientHeightDescriptor?.get?.call(this) ?? 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get() {
      if ((this as HTMLElement).matches('[data-time-value]')) return 36;
      return originalOffsetHeightDescriptor?.get?.call(this) ?? 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value(this: HTMLElement) {
      const rect = (top: number, height: number, width: number): DOMRect => ({
        x: 0,
        y: top,
        top,
        right: width,
        bottom: top + height,
        left: 0,
        width,
        height,
        toJSON: () => ({}),
      });

      if (this.matches('[data-time-column]')) return rect(100, 160, 48);
      if (this.matches('[data-time-value]')) {
        const column = this.closest('[data-time-column]') as HTMLElement;
        const value = Number(this.getAttribute('data-time-value'));
        return rect(100 + 64 + value * 36 - column.scrollTop, 36, 48);
      }
      return originalRectDescriptor?.value?.call(this) ?? rect(0, 0, 0);
    },
  });

  const scrollTo = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
    this.scrollTop = options.top ?? this.scrollTop;
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: scrollTo,
  });
  return scrollTo;
};

afterEach(() => {
  cleanup();
  for (const [property, descriptor] of [
    ['getBoundingClientRect', originalRectDescriptor],
    ['clientHeight', originalClientHeightDescriptor],
    ['offsetHeight', originalOffsetHeightDescriptor],
    ['scrollTo', originalScrollToDescriptor],
  ] as const) {
    if (descriptor) Object.defineProperty(HTMLElement.prototype, property, descriptor);
    else Reflect.deleteProperty(HTMLElement.prototype, property);
  }
  vi.restoreAllMocks();
});

describe('DateTimePicker time column scrolling', () => {
  it('positions selected values on open and smoothly recenters each changed column', async () => {
    const scrollTo = installTimeColumnGeometry();
    const user = userEvent.setup();
    render(<DateTimePicker value="2026-10-21T12:33" onChange={vi.fn()} language="en" />);

    await user.click(screen.getByRole('button', { name: '2026-10-21 12:33' }));

    const hourColumn = screen.getByRole('group', { name: 'Hour' });
    const minuteColumn = screen.getByRole('group', { name: 'Minute' });
    expect(hourColumn.scrollTop).toBe(434);
    expect(minuteColumn.scrollTop).toBe(1190);
    expect(within(hourColumn).getByRole('button', { name: '12' }).getAttribute('aria-pressed')).toBe('true');

    await user.click(within(hourColumn).getByRole('button', { name: '14' }));
    await user.click(within(minuteColumn).getByRole('button', { name: '35' }));

    expect(scrollTo).toHaveBeenNthCalledWith(1, { top: 506, behavior: 'smooth' });
    expect(scrollTo).toHaveBeenNthCalledWith(2, { top: 1262, behavior: 'smooth' });
    expect(hourColumn.scrollTop).toBe(506);
    expect(minuteColumn.scrollTop).toBe(1262);
  });
});
