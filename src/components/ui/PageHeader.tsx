import React from 'react';
import { cn } from '../../lib/cn';
import { InfoTip } from './InfoTip';

export interface PageHeaderProps {
  /** Page title (20px). State what the page manages. */
  title: React.ReactNode;
  /** One short line under the title. */
  description?: React.ReactNode;
  /** Secondary explanation shown behind an ⓘ next to the title. */
  info?: React.ReactNode;
  /** Accessible name for the ⓘ trigger. */
  infoLabel?: string;
  /** Right-aligned actions; put the primary action last. */
  actions?: React.ReactNode;
  className?: string;
}

/**
 * Shared page header for management pages.
 * Replaces gradient hero banners: title + one line + actions, nothing else.
 */
export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, info, infoLabel, actions, className }) => (
  <header className={cn('flex flex-wrap items-start justify-between gap-x-6 gap-y-3', className)}>
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-2">
        {/* The ⓘ sits next to the heading, not inside it: otherwise its
            tooltip text becomes part of the heading's accessible name. */}
        <h2 className="min-w-0 truncate text-xl font-semibold leading-tight text-fg">{title}</h2>
        {info && <InfoTip label={infoLabel}>{info}</InfoTip>}
      </div>
      {description && <p className="mt-1 text-[13px] leading-5 text-fg-muted">{description}</p>}
    </div>
    {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
  </header>
);

export default PageHeader;
