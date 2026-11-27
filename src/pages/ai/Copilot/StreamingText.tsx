import React from 'react';

/**
 * Plain-text rendering of an answer that is still streaming.
 *
 * Tokens are appended to one string.  Rendering that string as a single text
 * node meant React rewrote the node's data on every flush, and the DOM
 * collapses a selection inside a text node whose data is replaced -- so text
 * could not be selected or copied while the answer was streaming.
 *
 * The text is split at fixed offsets instead.  Because a stream only
 * appends, every segment except the last one keeps exactly the same text, so
 * its DOM node is never touched and a selection inside it survives.  The
 * visual result is identical: the segments are inline spans inside a
 * `white-space: pre-wrap` block.
 */
export const STREAM_SEGMENT_CHARS = 256;

export function splitStreamingSegments(content: string, size: number = STREAM_SEGMENT_CHARS): string[] {
  const text = String(content ?? '');
  const step = Math.max(1, Math.floor(size));
  const segments: string[] = [];
  for (let start = 0; start < text.length; start += step) {
    segments.push(text.slice(start, start + step));
  }
  return segments;
}

const StreamingSegment = React.memo(({ text }: { text: string }) => (
  <span data-copilot-stream-segment="true">{text}</span>
));
StreamingSegment.displayName = 'StreamingSegment';

export const StreamingText: React.FC<{ content: string; className?: string }> = ({ content, className }) => (
  <div className={className} data-copilot-streaming-text="true">
    {splitStreamingSegments(content).map((segment, index) => (
      // Index keys are intended: segment i always covers the same offsets.
      <StreamingSegment key={index} text={segment} />
    ))}
  </div>
);
