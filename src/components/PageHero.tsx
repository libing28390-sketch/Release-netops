/**
 * PageHero — Unified page header block used across secondary (non-dashboard) pages.
 *
 * Structure:
 *   [colored icon tile] · [title + subtitle]                         [actions (optional)]
 *   ─────────────────────────────────────────────────────────────────────────────────────
 *   [eyebrow / tabs / extras (optional)]
 *
 * Visual language matches the Operation Workspace (AccessCenterTab):
 *   - Square rounded icon tile, 48px, solid accent background, white glyph
 *   - Title: shared 20px/700 page-title treatment, heading color
 *   - Subtitle: shared 12px muted treatment, separated from title with a "·" or newline
 *
 * All colors use CSS custom properties from index.css so light/dark themes auto-adapt.
 */
import React from 'react';
import type { LucideIcon } from 'lucide-react';

export interface PageHeroProps {
  /** Required: main icon rendered inside the tile */
  icon: React.ComponentType<any>;
  /** Primary page title (Chinese or current locale) */
  title: string;
  /** Optional short description shown below the title */
  subtitle?: string;
  /** Optional tiny eyebrow label shown above the title — e.g. current module name */
  eyebrow?: string;
  /** Accent color for the icon tile background. Defaults to the brand cyan. */
  accent?: string;
  /** Right-aligned area for buttons, search boxes, status pills, etc. */
  actions?: React.ReactNode;
  /** Optional extra row rendered under the main header (tabs, chips...) */
  extras?: React.ReactNode;
  /** Container className passthrough */
  className?: string;
}

const DEFAULT_ACCENT = 'var(--ui-accent)';

const PageHero: React.FC<PageHeroProps> = ({
  icon: Icon,
  title,
  subtitle,
  eyebrow,
  accent = DEFAULT_ACCENT,
  actions,
  extras,
  className,
}) => {
  return (
    <div
      className={`flex-shrink-0 px-6 pt-5 pb-4 border-b ${className ?? ''}`}
      style={{
        background: 'var(--header-bg)',
        borderColor: 'var(--header-border)',
      }}
    >
      <div className="flex items-start justify-between gap-4">
        {/* Left: icon tile + title block */}
        <div className="flex items-center gap-3.5 min-w-0">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm"
            style={{
              background: accent,
              color: '#ffffff',
              boxShadow: accent === DEFAULT_ACCENT
                ? '0 6px 16px -6px color-mix(in srgb, var(--ui-accent) 40%, transparent)'
                : `0 6px 16px -6px ${accent}66`,
            }}
          >
            <Icon className="w-6 h-6" strokeWidth={1.8} />
          </div>
          <div className="min-w-0">
            {eyebrow && (
              <div
                className="nx-page-eyebrow mb-0.5"
                style={{ color: accent }}
              >
                {eyebrow}
              </div>
            )}
            <h1
              className="nx-page-title truncate"
              style={{ color: 'var(--heading-text)' }}
            >
              {title}
            </h1>
            {subtitle && (
              <p
                className="nx-page-subtitle mt-0.5 truncate"
                style={{ color: 'var(--muted-text)' }}
              >
                {subtitle}
              </p>
            )}
          </div>
        </div>

        {/* Right: actions area */}
        {actions && (
          <div className="flex items-center gap-2 flex-shrink-0">
            {actions}
          </div>
        )}
      </div>

      {extras && (
        <div className="mt-4">
          {extras}
        </div>
      )}
    </div>
  );
};

export default PageHero;
