// @vitest-environment jsdom
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { useShallowStableObject } from './AppProviders';

describe('useShallowStableObject', () => {
  afterEach(() => {
    cleanup();
  });

  it('preserves object identity when all properties are shallowly equal and updates when any value changes', () => {
    const captured: Array<Record<string, unknown>> = [];
    const fn = () => undefined;

    const Probe = ({ a, b }: { a: number; b: () => void }) => {
      const stable = useShallowStableObject({ a, b });
      captured.push(stable);
      return <span>{stable.a}</span>;
    };

    const { rerender } = render(<Probe a={1} b={fn} />);
    rerender(<Probe a={1} b={fn} />);
    expect(captured).toHaveLength(2);
    expect(captured[1]).toBe(captured[0]);

    rerender(<Probe a={2} b={fn} />);
    expect(captured).toHaveLength(3);
    expect(captured[2]).not.toBe(captured[1]);
    expect(captured[2].a).toBe(2);
  });
});
