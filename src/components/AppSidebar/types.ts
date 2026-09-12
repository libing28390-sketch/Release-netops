/**
 * Type definitions for AppSidebar navigation components.
 */

/** A navigable child item within a NavGroup */
export interface NavChild {
  /** Unique identifier */
  id: string;
  /** Chinese label */
  label: string;
  /** English label */
  labelEn?: string;
  /** lucide-react icon key (only used in section-type groups) */
  icon?: string;
  /** Route path */
  path: string;
  /** Badge key to look up in alertCounts */
  badge?: 'monitoring' | 'alerts';
  /** Whether badge should use critical (red) styling */
  badgeCritical?: boolean;
  /** Prefix for active route matching (e.g. '/config/' matches /config/backup, /config/diff) */
  activeMatch?: string;
  /** If set, only users with this role (or higher) can see this item */
  requiredRole?: string;
}

/** A top-level navigation group / section */
export interface NavGroup {
  /** Unique identifier */
  id: string;
  /** Chinese section label */
  label: string;
  /** English section label */
  labelEn?: string;
  /** lucide-react icon key for the section header */
  icon?: string;
  /** Badge key shown on section header */
  badge?: 'monitoring' | 'alerts';
  /** Whether section badge uses critical styling */
  badgeCritical?: boolean;
  /** If true, renders as flat section (children have individual icons) */
  section?: boolean;
  /** Child navigation items */
  children: NavChild[];
}

/** Props for the AppSidebar component */
export interface AppSidebarProps {
  /** Badge counts keyed by badge identifier */
  alertCounts?: { monitoring?: number; alerts?: number };
  /** Whether any P1 critical alert exists (turns alert badge red) */
  isP1Critical?: boolean;
  /** Additional CSS classes on the root element */
  className?: string;
  /** Navigation callback — overrides internal useNavigate() */
  onNavigate?: (path: string) => void;
  /** Called when search bar is activated or "/" pressed */
  onOpenSearch?: () => void;
  /** UI language: 'zh' | 'en'. Defaults to 'zh'. */
  language?: string;
  /** Current user role for RBAC filtering (e.g. 'Administrator', 'Operator', 'Viewer') */
  userRole?: string;
  /** Mobile drawer open state. Omit for desktop-only usage. */
  mobileOpen?: boolean;
  /** Called when mobile drawer should close */
  onMobileClose?: () => void;
}

/** Props for the BadgeCount pill component */
export interface BadgeProps {
  /** Numeric count to display */
  count: number;
  /** Use red/critical styling instead of default muted */
  critical?: boolean;
}
