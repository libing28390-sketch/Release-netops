import React from 'react';
import { cn } from '../../lib/cn';
import type { StatusTone } from './StatusBadge';

export interface SummaryItem {
  key: string;
  value: React.ReactNode;
  label: React.ReactNode;
  /** Optional status dot before the value. */
  tone?: StatusTone;
}

const dotClasses: Record<StatusTone, string> = {
  neutral: 'bg-fg-subtle',
  accent: 'bg-accent',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
};

export interface SummaryBarProps {
  items: SummaryItem[];
  label?: string;
  className?: string;
}

/**
 * One-line page summary. Use it instead of a row of KPI cards when the
 * numbers are context, not the subject of the page.
 */
export const SummaryBar: React.FC<SummaryBarProps> = ({ items, label, className }) => (
  <dl
    aria-label={label}
    className={cn('flex flex-wrap items-center gap-x-6 gap-y-1.5 rounded-lg border border-line bg-surface px-4 py-2.5 text-[13px] text-fg-muted', className)}
  >
    {items.map((item) => (
      <div key={item.key} className="flex items-center gap-1.5">
        {item.tone && <span className={cn('h-[7px] w-[7px] rounded-full', dotClasses[item.tone])} aria-hidden="true" />}
        <dd className="font-semibold tabular-nums text-fg">{item.value}</dd>
        <dt>{item.label}</dt>
      </div>
    ))}
  </dl>
);

export default SummaryBar;
