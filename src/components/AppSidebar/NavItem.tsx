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
  if (mini) {
    return (
      <div className="relative group/navitem flex justify-center">
        <button
          onClick={onClick}
          className={cn(
            'relative flex items-center justify-center w-10 h-10 rounded-lg transition-all duration-150',
            active
              ? 'bg-cyan-500/[0.08] text-cyan-400'
              : 'text-slate-500 hover:bg-white/5 hover:text-slate-300'
          )}
          aria-label={label}
          aria-current={active ? 'page' : undefined}
        >
          {Icon && <Icon size={20} />}
          {badgeDot && (
            <span
              className={cn(
                'absolute top-1 right-1 h-2 w-2 rounded-full ring-2 ring-[#0d1117]',
                badgeDotCritical ? 'bg-red-500' : 'bg-cyan-500'
              )}
            />
          )}
        </button>
        {/* Tooltip */}
        <div
          className="absolute left-full top-1/2 -translate-y-1/2 ml-3
            pointer-events-none opacity-0 group-hover/navitem:opacity-100
            transition-opacity duration-150 z-50
            bg-slate-800 text-slate-100 text-[12px] font-medium
            py-1.5 px-3 rounded-lg shadow-lg shadow-black/40 whitespace-nowrap
            border border-slate-700"
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
          ? 'border-l-cyan-400 bg-cyan-500/[0.08] text-white font-medium rounded-r-lg'
          : 'border-l-transparent text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-lg'
      )}
      aria-current={active ? 'page' : undefined}
    >
      {Icon && (
        <Icon
          size={indent ? 14 : 16}
          className={cn(
            'flex-shrink-0 transition-colors duration-150',
            active ? 'text-cyan-400' : 'text-slate-500'
          )}
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
