import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

/** Neutral empty state: icon, one title, one line, one action. */
export const EmptyState: React.FC<EmptyStateProps> = ({ icon: Icon, title, description, action, className }) => (
  <div className={cn('flex flex-col items-center rounded-xl border border-dashed border-line-strong bg-surface px-6 py-12 text-center', className)}>
    {Icon && (
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-muted text-fg-muted">
        <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
      </span>
    )}
    <h3 className="mt-3 text-base font-semibold text-fg">{title}</h3>
    {description && <p className="mt-1 max-w-md text-[13px] leading-5 text-fg-muted">{description}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export default EmptyState;
