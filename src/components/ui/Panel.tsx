import React from 'react';
import { cn } from '../../lib/cn';

export interface PanelProps extends React.HTMLAttributes<HTMLElement> {
  as?: 'section' | 'div' | 'aside';
}

/** Flat surface with a 1px border and 12px radius. No gradients, no shadow. */
export const Panel: React.FC<PanelProps> = ({ as: Tag = 'section', className, children, ...props }) => (
  <Tag {...props} className={cn('min-w-0 rounded-xl border border-line bg-surface', className)}>
    {children}
  </Tag>
);

export interface PanelHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export const PanelHeader: React.FC<PanelHeaderProps> = ({ title, description, actions, className }) => (
  <div className={cn('flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3', className)}>
    <div className="min-w-0">
      <h3 className="truncate text-base font-semibold text-fg">{title}</h3>
      {description && <p className="mt-0.5 text-xs text-fg-muted">{description}</p>}
    </div>
    {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
  </div>
);

export default Panel;
