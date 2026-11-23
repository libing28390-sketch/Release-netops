import React from 'react';
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { STREAM_SEGMENT_CHARS, StreamingText, splitStreamingSegments } from './StreamingText';

describe('StreamingText', () => {
  afterEach(() => cleanup());

  it('splits at fixed offsets so earlier segments never change while appending', () => {
    const first = splitStreamingSegments('a'.repeat(STREAM_SEGMENT_CHARS + 10));
    const second = splitStreamingSegments('a'.repeat(STREAM_SEGMENT_CHARS + 10) + 'bbb');
    expect(first[0]).toBe(second[0]);
    expect(second.join('')).toBe('a'.repeat(STREAM_SEGMENT_CHARS + 10) + 'bbb');
    expect(splitStreamingSegments('')).toEqual([]);
  });

  it('keeps the DOM node of a completed segment, and a selection inside it, across stream updates', () => {
    const base = 'x'.repeat(STREAM_SEGMENT_CHARS);
    const { container, rerender } = render(<StreamingText content={`${base}tail`} />);
    const firstSegment = container.querySelector('[data-copilot-stream-segment="true"]');
    expect(firstSegment?.textContent).toBe(base);

    const range = document.createRange();
    range.selectNodeContents(firstSegment as Node);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);

    rerender(<StreamingText content={`${base}tail and more streamed text`} />);

    expect(container.querySelector('[data-copilot-stream-segment="true"]')).toBe(firstSegment);
    expect(firstSegment?.firstChild?.textContent).toBe(base);
    expect(window.getSelection()?.toString()).toBe(base);
    expect(container.textContent).toBe(`${base}tail and more streamed text`);
  });
});
