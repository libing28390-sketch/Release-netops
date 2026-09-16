import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '../../lib/cn';

interface NavSectionProps {
  /** Section header label */
  label: string;
  /** Optional icon component for the header */
  icon?: React.ComponentType<any>;
  /** Whether section starts expanded (uncontrolled mode) */
  defaultOpen?: boolean;
  /** Controlled open state (overrides defaultOpen when defined) */
  isOpen?: boolean;
  /** Callback when section header is clicked (controlled mode) */
  onToggle?: () => void;
  /** Whether any child in this section is active */
  hasActiveChild?: boolean;
  /** Optional badge element (rendered between label and chevron) */
  badge?: React.ReactNode;
  /** Child nav items */
  children: React.ReactNode;
}

/**
 * Collapsible navigation section.
 *
 * Header:
 *   [Icon?] [Label] ........... [Badge?] [Chevron ▸]
 *   text-[11px] font-semibold uppercase tracking-widest text-slate-500
 *
 * Collapse:
 *   max-h-96 ↔ max-h-0  transition 300ms
 *   Chevron rotates 0° → 90°
 */
const NavSection: React.FC<NavSectionProps> = ({
  label,
  icon: Icon,
  defaultOpen = true,
  isOpen: controlledOpen,
  onToggle,
  hasActiveChild = false,
  badge,
  children,
}) => {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isOpen = controlledOpen !== undefined ? controlledOpen : internalOpen;

  const handleToggle = () => {
    if (onToggle) {
      onToggle();
    } else {
      setInternalOpen(v => !v);
    }
  };

  return (
    <div className="mt-5 first:mt-0">
      {/* Section header */}
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-2 px-3 py-1.5 group/section hover:bg-[var(--app-hover-bg)] rounded-lg transition-colors"
        aria-expanded={isOpen}
        aria-label={label}
      >
        {Icon && (
          <Icon
            size={12}
            className={cn(
              'flex-shrink-0 transition-colors'
            )}
            style={{
              color: hasActiveChild ? '#0078d4' : 'var(--dim-text)',
            }}
          />
        )}
        <span
          className={cn(
            'flex-1 text-left text-[13px] font-semibold tracking-wide select-none transition-colors'
          )}
          style={{
            color: hasActiveChild ? '#0078d4' : 'var(--muted-text)',
          }}
        >
          {label}
        </span>
        {badge && <span className="flex-shrink-0">{badge}</span>}
        <ChevronRight
          size={12}
          className={cn(
            'flex-shrink-0 transition-transform duration-200',
            isOpen ? 'rotate-90' : 'rotate-0'
          )}
          style={{
            color: 'var(--dim-text)',
          }}
        />
      </button>

      {/* Collapsible children */}
      <div
        className={cn(
          'overflow-hidden transition-all duration-300',
          isOpen ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0'
        )}
      >
        <div className="mt-1 space-y-px">
          {children}
        </div>
      </div>
    </div>
  );
};

export default NavSection;
