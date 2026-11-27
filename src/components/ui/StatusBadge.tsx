import React from 'react';
import { cn } from '../../lib/cn';

export type StatusTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

const toneClasses: Record<StatusTone, { badge: string; dot: string }> = {
  neutral: { badge: 'bg-surface-emphasis text-fg-muted', dot: 'bg-fg-subtle' },
  accent: { badge: 'bg-accent-subtle text-accent', dot: 'bg-accent' },
  success: { badge: 'bg-success-subtle text-success', dot: 'bg-success' },
  warning: { badge: 'bg-warning-subtle text-warning', dot: 'bg-warning' },
  danger: { badge: 'bg-danger-subtle text-danger', dot: 'bg-danger' },
};

export interface StatusBadgeProps {
  tone?: StatusTone;
  /** Show a leading status dot. */
  dot?: boolean;
  /** Render code-like values (error codes, classifications) in mono. */
  mono?: boolean;
  className?: string;
  children: React.ReactNode;
}

/** Pill used for every status, classification and tag in tables and details. 12px, never smaller. */
export const StatusBadge: React.FC<StatusBadgeProps> = ({ tone = 'neutral', dot = false, mono = false, className, children }) => (
  <span
    className={cn(
      'inline-flex h-[22px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-medium',
      mono && 'font-mono',
      toneClasses[tone].badge,
      className,
    )}
  >
    {dot && <span className={cn('h-1.5 w-1.5 rounded-full', toneClasses[tone].dot)} aria-hidden="true" />}
    {children}
  </span>
);

export default StatusBadge;
