import React from 'react';
import { cn } from '../../lib/cn';

interface NavItemProps {
  /** Display text */
  label: string;
  /** Whether this item is the currently active route */
  active: boolean;
  /** Optional icon component */
  icon?: React.ElementType;
  /** Level-2 indented item (smaller text, deeper padding) */
  indent?: boolean;
  /** Optional badge element rendered after label */
  badge?: React.ReactNode;
  /** Mini (collapsed) mode: icon-only with hover tooltip */
  mini?: boolean;
  /** Whether to show a small dot indicator on the icon (mini mode badges) */
  badgeDot?: boolean;
  /** Critical dot color (red instead of cyan) */
  badgeDotCritical?: boolean;
  /** Click handler */
  onClick: () => void;
}

/**
 * Single navigation item in the sidebar.
 *
 * Typography:
 *   Level-1: text-[15px] font-medium text-slate-300
 *   Level-2: text-[13px] font-normal text-slate-400 (indent=true)
 *
 * Active state:
 *   border-l-[3px] border-l-cyan-400 bg-cyan-500/[0.08] text-white
 *
 * Mini mode:
 *   Icon only, centered, tooltip on hover
 */
const NavItem: React.FC<NavItemProps> = ({
  label,
  active,
  icon: Icon,
  indent = false,
  badge,
  mini = false,
  badgeDot = false,
  badgeDotCritical = false,
  onClick,
}) => {
  const ACCENT = '#0078d4';

  if (mini) {
    return (
      <div className="relative group/navitem flex justify-center">
        <button
          onClick={onClick}
          className={cn(
            'relative flex items-center justify-center w-10 h-10 rounded-lg transition-all duration-150',
            active
              ? 'bg-[rgba(0,120,212,0.08)] text-[#0078d4]'
              : 'text-[var(--muted-text)] hover:bg-[var(--app-hover-bg)] hover:text-[var(--app-text)]'
          )}
          aria-label={label}
          aria-current={active ? 'page' : undefined}
        >
          {Icon && <Icon size={20} />}
          {badgeDot && (
            <span
              className={cn(
                'absolute top-1 right-1 h-2 w-2 rounded-full ring-2 ring-[var(--sidebar-bg)]',
                badgeDotCritical ? 'bg-red-500' : 'bg-[#0078d4]'
              )}
            />
          )}
        </button>
        {/* Tooltip */}
        <div
          className="absolute left-full top-1/2 -translate-y-1/2 ml-3
            pointer-events-none opacity-0 group-hover/navitem:opacity-100
            transition-opacity duration-150 z-50
            bg-[var(--card-bg)] text-[var(--app-text)] text-[12px] font-medium
            py-1.5 px-3 rounded-lg shadow-lg whitespace-nowrap
            border border-[var(--card-border)]"
          role="tooltip"
        >
          {label}
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-2.5 transition-all duration-150 border-l-[3px]',
        indent ? 'pl-9 pr-3 py-[7px]' : 'pl-3 pr-3 py-2',
        active
          ? 'border-l-[#0078d4] bg-[rgba(0,120,212,0.08)] text-[#0078d4] font-semibold rounded-r-lg'
          : 'border-l-transparent text-[var(--body-text)] hover:bg-[var(--app-hover-bg)] hover:text-[var(--app-text)] rounded-lg'
      )}
      style={{
        color: active ? '#0078d4' : undefined,
      }}
      aria-current={active ? 'page' : undefined}
    >
      {Icon && (
        <Icon
          size={indent ? 14 : 16}
          className={cn(
            'flex-shrink-0 transition-colors duration-150'
          )}
          style={{
            color: active ? '#0078d4' : 'var(--muted-text)',
          }}
        />
      )}
      <span
        className={cn(
          'flex-1 text-left truncate',
          indent ? 'text-[13.5px] font-normal' : 'text-[14px] font-medium'
        )}
      >
        {label}
      </span>
      {badge}
    </button>
  );
};

export default NavItem;
