/**
 * AppSidebar — Main navigation sidebar for Nexora.
 *
 * Features:
 *   - Mini mode toggle (260px ↔ 64px) with localStorage persistence
 *   - Collapsible section groups with chevron animation
 *   - Active route detection via useLocation()
 *   - Search shortcut bar ("/" global keyboard shortcut)
 *   - Badge counts with P1 critical styling
 *   - Mobile drawer mode with backdrop
 *   - Fully accessible (keyboard navigable, aria attributes)
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  BarChart2,
  Bell,
  ClipboardList,
  Clock,
  FileText,
  FileCode2,
  GitBranch,
  Globe,
  Home,
  Key,
  Lock,
  Monitor,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Server,
  Settings,
  Shield,
  ShieldAlert,
  Terminal,
  User,
  X,
  Zap,
} from 'lucide-react';
import { cn } from '../../lib/cn';
import { navConfig } from './navConfig';
import type { AppSidebarProps, NavChild } from './types';
import BadgeCount from './BadgeCount';
import NavItem from './NavItem';
import NavSection from './NavSection';
import { useSystem } from '../../hooks/useSystem';

/** Map icon string keys (from navConfig) → lucide component */
const iconMap: Record<string, React.ElementType> = {
  Activity, BarChart2, Bell, ClipboardList, Clock, FileCode2, FileText, GitBranch, Globe, Key, Lock, Monitor, Server, Settings, Shield, ShieldAlert, Terminal, User, Zap,
};

/** RBAC role hierarchy levels */
const ROLE_LEVEL: Record<string, number> = { Administrator: 3, Operator: 2, Viewer: 1 };

const LS_KEY = 'nexora_sidebar';

const AppSidebar: React.FC<AppSidebarProps> = ({
  alertCounts = {},
  isP1Critical = false,
  className,
  onNavigate,
  onOpenSearch,
  language = 'zh',
  userRole,
  mobileOpen,
  onMobileClose,
}) => {
  const zh = language === 'zh';
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const { systemInfo } = useSystem();

  /* ─────────── Mini mode ─────────── */
  const [mini, setMini] = useState(() => {
    try { return localStorage.getItem(LS_KEY) === 'mini'; } catch { return false; }
  });

  const toggleMini = useCallback(() => {
    setMini(prev => {
      const next = !prev;
      try { localStorage.setItem(LS_KEY, next ? 'mini' : 'expanded'); } catch { /* noop */ }
      return next;
    });
  }, []);

  /* ─────────── Mobile detection ─────────── */
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const showDrawer = isMobile ? (mobileOpen ?? false) : true;
  const effectiveMini = !isMobile && mini;

  /* ─────────── "/" keyboard shortcut ─────────── */
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) {
        e.preventDefault();
        if (onOpenSearch) {
          onOpenSearch();
        } else {
          searchRef.current?.focus();
        }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onOpenSearch]);

  /* ─────────── Navigation ─────────── */
  const handleNav = useCallback((path: string) => {
    if (onNavigate) {
      onNavigate(path);
    } else {
      navigate(path);
    }
  }, [onNavigate, navigate]);

  /* ─────────── Active detection ─────────── */
  const isActive = useCallback((item: NavChild): boolean => {
    const { pathname } = location;
    if (pathname === item.path) return true;
    if (item.activeMatch) {
      // Support comma-separated list of prefixes
      const prefixes = item.activeMatch.split(',');
      return prefixes.some(p => pathname.startsWith(p));
    }
    return false;
  }, [location]);

  const sectionHasActive = useCallback(
    (children: NavChild[]) => children.some(c => isActive(c)),
    [isActive],
  );

  /* ─────────── Badge helpers ─────────── */
  const getBadgeCount = useCallback(
    (key?: 'monitoring' | 'alerts') => (key ? alertCounts[key] ?? 0 : 0),
    [alertCounts],
  );

  /* ─────────── Label helper ─────────── */
  const L = useCallback(
    (label: string, labelEn?: string) => (zh ? label : (labelEn ?? label)),
    [zh],
  );

  /* ─────────── RBAC filter ─────────── */
  const filterByRole = useCallback(
    (children: NavChild[]): NavChild[] =>
      children.filter(c => {
        if (!c.requiredRole) return true;
        const userLvl = ROLE_LEVEL[userRole ?? ''] ?? 0;
        const reqLvl = ROLE_LEVEL[c.requiredRole] ?? 99;
        return userLvl >= reqLvl;
      }),
    [userRole],
  );

  /* ─────────── Accordion: only one group open ─────────── */
  const getActiveGroupId = useCallback((): string | null => {
    for (const g of navConfig) {
      if (g.children.some(c => isActive(c))) return g.id;
    }
    return null;
  }, [isActive]);

  const [openGroupId, setOpenGroupId] = useState<string | null>(() => getActiveGroupId());

  // Sync open group when route changes
  useEffect(() => {
    const activeId = getActiveGroupId();
    if (activeId) setOpenGroupId(activeId);
  }, [location.pathname, getActiveGroupId]);

  const toggleGroup = useCallback((groupId: string) => {
    setOpenGroupId((prev: string | null) => prev === groupId ? null : groupId);
  }, []);

  /* ═══════════════════════════════════════
     RENDER — Mini mode
     ═══════════════════════════════════════ */
  const renderMini = () => (
    <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3 space-y-1">
      <NavItem
        label={zh ? '首页' : 'Home'}
        active={location.pathname === '/dashboard'}
        icon={Home}
        mini
        onClick={() => handleNav('/dashboard')}
      />
      <div className="border-t border-[var(--header-border)] my-2" />
      {navConfig.map((group, gi) => {
        const GIcon = group.icon ? iconMap[group.icon] : undefined;
        const visibleChildren = filterByRole(group.children);
        if (visibleChildren.length === 0) return null;
        const hasActive = sectionHasActive(visibleChildren);
        const badgeVal = getBadgeCount(group.badge);

        return (
          <React.Fragment key={group.id}>
            {gi > 0 && <div className="border-t border-[var(--header-border)] my-2" />}

            {group.section ? (
              /* Section group: individual child icons */
              visibleChildren.map(child => {
                const CIcon = child.icon ? iconMap[child.icon] : undefined;
                return (
                  <NavItem
                    key={child.id}
                    label={L(child.label, child.labelEn)}
                    active={isActive(child)}
                    icon={CIcon}
                    mini
                    onClick={() => handleNav(child.path)}
                  />
                );
              })
            ) : (
              /* Regular group: single group icon → first child */
              <NavItem
                label={L(group.label, group.labelEn)}
                active={hasActive}
                icon={GIcon}
                mini
                badgeDot={badgeVal > 0}
                badgeDotCritical={!!group.badgeCritical && isP1Critical}
                onClick={() => handleNav(group.children[0].path)}
              />
            )}
          </React.Fragment>
        );
      }).filter(Boolean)}
    </div>
  );

  /* ═══════════════════════════════════════
     RENDER — Full (expanded) mode
     ═══════════════════════════════════════ */
  const renderFull = () => (
    <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 pb-4" aria-label="Navigation">
      <NavItem
        label={zh ? '首页' : 'Home'}
        active={location.pathname === '/dashboard'}
        icon={Home}
        onClick={() => handleNav('/dashboard')}
      />
      {navConfig.map(group => {
        const GIcon = group.icon ? iconMap[group.icon] : undefined;
        const groupLabel = L(group.label, group.labelEn);
        const visibleChildren = filterByRole(group.children);
        if (visibleChildren.length === 0) return null;
        const hasActive = sectionHasActive(visibleChildren);
        const badgeVal = getBadgeCount(group.badge);
        const groupBadge =
          badgeVal > 0
            ? <BadgeCount count={badgeVal} critical={!!group.badgeCritical && isP1Critical} />
            : undefined;

        if (group.section) {
          /* Flat section (e.g. 平台管理) */
          return (
            <NavSection
              key={group.id}
              label={groupLabel}
              isOpen={openGroupId === group.id}
              onToggle={() => toggleGroup(group.id)}
              hasActiveChild={hasActive}
            >
              {visibleChildren.map(child => {
                const CIcon = child.icon ? iconMap[child.icon] : undefined;
                return (
                  <NavItem
                    key={child.id}
                    label={L(child.label, child.labelEn)}
                    active={isActive(child)}
                    icon={CIcon}
                    onClick={() => handleNav(child.path)}
                  />
                );
              })}
            </NavSection>
          );
        }

        /* Collapsible group */
        return (
          <NavSection
            key={group.id}
            label={groupLabel}
            icon={GIcon}
            isOpen={openGroupId === group.id}
            onToggle={() => toggleGroup(group.id)}
            hasActiveChild={hasActive}
            badge={groupBadge}
          >
            {visibleChildren.map(child => {
              const CIcon = child.icon ? iconMap[child.icon] : undefined;
              return (
                <NavItem
                  key={child.id}
                  label={L(child.label, child.labelEn)}
                  active={isActive(child)}
                  icon={CIcon}
                  indent
                  onClick={() => handleNav(child.path)}
                />
              );
            })}
          </NavSection>
        );
      })}
    </nav>
  );

  /* ═══════════════════════════════════════
     MAIN LAYOUT
     ═══════════════════════════════════════ */
  return (
    <>
      {/* Mobile backdrop */}
      {isMobile && showDrawer && (
        <div
          className="fixed inset-0 z-[25] bg-black/60 backdrop-blur-[2px]"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'flex flex-col flex-shrink-0 bg-[var(--sidebar-bg)] border-r border-[var(--header-border)] transition-all duration-300 overflow-hidden',
          isMobile
            ? cn(
                'fixed inset-y-0 left-0 z-30 shadow-2xl w-[260px]',
                showDrawer ? 'translate-x-0' : '-translate-x-full'
              )
            : effectiveMini
              ? 'w-[64px]'
              : 'w-[260px]',
          className
        )}
        role="navigation"
        aria-label="Main navigation"
      >
        {/* ── Logo header ── */}
        <div
          className={cn(
            'flex items-center border-b border-[var(--header-border)] flex-shrink-0',
            effectiveMini ? 'justify-center px-2 py-3.5' : 'justify-between px-4 py-3'
          )}
        >
          {!effectiveMini && (
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-[rgba(0,120,212,0.08)] border border-[rgba(0,120,212,0.15)] flex items-center justify-center flex-shrink-0">
                <Activity size={16} className="text-[#0078d4]" />
              </div>
              <div className="min-w-0">
                <h1 className="text-base font-bold text-[var(--heading-text)] tracking-tight leading-none">{systemInfo?.system_name || 'Nexora'}</h1>
                <p className="text-xs text-[var(--dim-text)] mt-0.5 leading-none">
                  {zh ? '智能网络中枢' : 'SMART NET HUB'}
                </p>
              </div>
            </div>
          )}

          {effectiveMini && (
            <div className="w-8 h-8 rounded-lg bg-[rgba(0,120,212,0.08)] border border-[rgba(0,120,212,0.15)] flex items-center justify-center">
              <Activity size={16} className="text-[#0078d4]" />
            </div>
          )}

          {/* Mini toggle button (desktop only) */}
          {!isMobile && (
            <button
              onClick={toggleMini}
              className="p-1.5 rounded-md text-[var(--muted-text)] hover:text-[var(--app-text)] hover:bg-[var(--app-hover-bg)] transition-colors flex-shrink-0"
              aria-label={effectiveMini ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {effectiveMini ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          )}

          {/* Close button (mobile only) */}
          {isMobile && (
            <button
              onClick={onMobileClose}
              className="p-1.5 rounded-md text-[var(--muted-text)] hover:text-[var(--app-text)] hover:bg-[var(--app-hover-bg)]"
              aria-label="Close sidebar"
            >
              <X size={16} />
            </button>
          )}
        </div>

        {/* ── Search bar ── */}
        {!effectiveMini && (
          <div className="mx-3 my-3">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-text)] pointer-events-none" />
              <input
                ref={searchRef}
                type="text"
                placeholder={zh ? '搜索或跳转...' : 'Search or jump...'}
                className="w-full pl-8 pr-10 py-2 rounded-lg bg-[var(--search-bg)] border border-[var(--card-border)] text-[13px] text-[var(--app-text)] placeholder:text-[var(--dim-text)] focus:outline-none focus:border-[#0078d4] focus:ring-1 focus:ring-[#0078d4]/30 transition-colors"
                onFocus={() => {
                  if (onOpenSearch) {
                    onOpenSearch();
                    searchRef.current?.blur();
                  }
                }}
                readOnly={!!onOpenSearch}
                aria-label={zh ? '搜索导航' : 'Search navigation'}
              />
              <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] border border-[var(--card-border)] rounded px-1.5 py-0.5 text-[var(--dim-text)] font-mono leading-none">
                /
              </kbd>
            </div>
          </div>
        )}

        {effectiveMini && (
          <div className="flex justify-center my-3">
            <button
              onClick={() => onOpenSearch?.()}
              className="relative p-2 rounded-lg text-[var(--muted-text)] hover:text-[var(--app-text)] hover:bg-[var(--app-hover-bg)] transition-colors group/search"
              aria-label={zh ? '搜索' : 'Search'}
            >
              <Search size={18} />
              <div
                className="absolute left-full top-1/2 -translate-y-1/2 ml-3
                  pointer-events-none opacity-0 group-hover/search:opacity-100
                  transition-opacity duration-150 z-50
                  bg-[var(--card-bg)] text-[var(--app-text)] text-[12px] font-medium
                  py-1.5 px-3 rounded-lg shadow-lg whitespace-nowrap
                  border border-[var(--card-border)]"
                role="tooltip"
              >
                {zh ? '搜索 (/)' : 'Search (/)'}
              </div>
            </button>
          </div>
        )}

        {/* ── Navigation ── */}
        {effectiveMini ? renderMini() : renderFull()}

        {/* ── Version Footer ── */}
        {!effectiveMini && (
          <div className="mt-auto px-4 py-4 border-t border-[var(--header-border)] bg-[var(--app-hover-bg)] flex flex-col gap-1.5 flex-shrink-0">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-[var(--dim-text)] tracking-wider uppercase">
                {zh ? '当前版本' : 'VERSION'}
              </span>
              <span className="px-1.5 py-0.5 rounded bg-[rgba(0,120,212,0.08)] text-[#0078d4] text-[10px] font-mono font-bold border border-[rgba(0,120,212,0.15)]">
                v{systemInfo?.version || '0.1.0'}
              </span>
            </div>
          </div>
        )}
      </aside>
    </>
  );
};

export default AppSidebar;
