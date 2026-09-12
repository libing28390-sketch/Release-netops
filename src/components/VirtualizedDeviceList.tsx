/**
 * VirtualizedDeviceList — windowed scrolling for the per-device left rails on
 * `/monitor/servers` and `/monitor/networks`.
 *
 * Both pages render an identical card per device, and historically used a
 * plain `{list.map(...)}` which mounts every card into the DOM. That works
 * fine up to a few hundred entries; beyond ~1000 devices the initial paint
 * and subsequent scrolling get jerky because every card carries its own
 * button + lucide icon + nested spans.
 *
 * This component uses @tanstack/react-virtual to mount only the rows that
 * are visible in the viewport (plus a small overscan buffer). The browser
 * still shows a normal scrollbar because we reserve the full virtual height.
 */
import React, { useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

interface VirtualizedDeviceListProps<T> {
  /** The full filtered+sorted list — virtualization makes the length irrelevant for perf. */
  items: T[];
  /** Stable per-item key. */
  getKey: (item: T) => string;
  /** Renders one card. The inner element should fill the row; height is fixed by `rowHeight`. */
  renderItem: (item: T) => React.ReactNode;
  /** Empty-state element shown when `items.length === 0`. */
  empty?: React.ReactNode;
  /**
   * Estimated row height in pixels. The card markup in both monitoring pages
   * renders to roughly 60px (py-2.5 + a 32px icon + 4px gap-y from `space-y-1`).
   */
  rowHeight?: number;
  /** Extra rows to render outside the visible window for smoother scrolling. */
  overscan?: number;
  /** Container className (allows the parent to keep its existing scroll/padding setup). */
  className?: string;
}

export function VirtualizedDeviceList<T>({
  items,
  getKey,
  renderItem,
  empty,
  rowHeight = 60,
  overscan = 8,
  className = 'flex-1 overflow-auto p-2',
}: VirtualizedDeviceListProps<T>) {
  const parentRef = useRef<HTMLDivElement | null>(null);

  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan,
  });

  if (items.length === 0) {
    return (
      <div className={className} ref={parentRef}>
        {empty}
      </div>
    );
  }

  const totalSize = rowVirtualizer.getTotalSize();
  const virtualItems = rowVirtualizer.getVirtualItems();

  return (
    <div className={className} ref={parentRef}>
      {/* Spacer reserves the full virtual height so the scrollbar is faithful. */}
      <div style={{ height: totalSize, width: '100%', position: 'relative' }}>
        {virtualItems.map((vi) => {
          const item = items[vi.index];
          return (
            <div
              key={getKey(item)}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${vi.start}px)`,
                paddingBottom: 4, // matches `space-y-1` (≈ 4px) between rows
              }}
            >
              {renderItem(item)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default VirtualizedDeviceList;
