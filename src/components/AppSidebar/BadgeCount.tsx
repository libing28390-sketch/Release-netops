import React from 'react';
import { cn } from '../../lib/cn';
import type { BadgeProps } from './types';

/**
 * Badge pill component for displaying numeric counts.
 * - Default: muted slate (bg-slate-700 text-slate-300)
 * - Critical: red glow (bg-red-500/20 text-red-400)
 * - Overflow: shows "99+" for counts > 99
 */
const BadgeCount: React.FC<BadgeProps> = ({ count, critical = false }) => {
  if (count <= 0) return null;

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-full text-[10px] font-semibold font-mono leading-none px-1.5 py-0.5',
        critical
          ? 'bg-red-500/15 text-red-600 dark:bg-red-500/20 dark:text-red-400'
          : 'bg-[var(--app-hover-bg)] text-[var(--muted-text)] border border-[var(--card-border)]'
      )}
      aria-label={`${count} items`}
    >
      {count > 99 ? '99+' : count}
    </span>
  );
};

export default BadgeCount;
