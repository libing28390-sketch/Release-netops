import React, { useId } from 'react';
import { Info } from 'lucide-react';
import { cn } from '../../lib/cn';

export interface InfoTipProps {
  /** Tooltip content. Keep it short: one or two sentences. */
  children: React.ReactNode;
  /** Accessible name of the trigger. */
  label?: string;
  className?: string;
}

/**
 * Small "ⓘ" trigger that reveals secondary explanations on hover or focus.
 * Use it instead of permanent helper paragraphs and banners.
 */
export const InfoTip: React.FC<InfoTipProps> = ({ children, label = 'More information', className }) => {
  const id = useId();
  return (
    <span className={cn('group/infotip relative inline-flex align-middle', className)}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="inline-flex h-5 w-5 items-center justify-center rounded-md text-fg-subtle transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Info size={15} strokeWidth={1.8} aria-hidden="true" />
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none invisible absolute left-1/2 top-full z-40 mt-2 w-72 -translate-x-1/2 rounded-md bg-fg px-3 py-2 text-xs font-normal leading-5 text-surface opacity-0 shadow-lg transition-opacity duration-150 group-hover/infotip:visible group-hover/infotip:opacity-100 group-focus-within/infotip:visible group-focus-within/infotip:opacity-100"
      >
        {children}
      </span>
    </span>
  );
};

export default InfoTip;
