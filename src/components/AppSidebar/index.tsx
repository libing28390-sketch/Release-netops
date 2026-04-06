/**
 * AppSidebar — Main navigation sidebar for NetPilot.
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
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Server,
  Settings,
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

/** Map icon string keys (from navConfig) → lucide component */
const iconMap: Record<string, React.ElementType> = {
  Activity, BarChart2, Bell, ClipboardList, Clock, FileText, Server, Settings, User, Zap,
};

const LS_KEY = 'netpilot_sidebar';

const AppSidebar: React.FC<AppSidebarProps> = ({
  alertCounts = {},
  isP1Critical = false,
  className,
  onNavigate,
  onOpenSearch,
  language = 'zh',
  mobileOpen,
  onMobileClose,
}) => {
  const zh = language === 'zh';
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);

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
      // Don't match if another sibling has this exact path
      return pathname.startsWith(item.activeMatch) &&
        !navConfig.some(g => g.children.some(c => c !== item && c.path === pathname));
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

  /* ═══════════════════════════════════════
     RENDER — Mini mode
     ═══════════════════════════════════════ */
  const renderMini = () => (
    <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3 space-y-1">
      {navConfig.map((group, gi) => {
        const GIcon = group.icon ? iconMap[group.icon] : undefined;
        const hasActive = sectionHasActive(group.children);
        const badgeVal = getBadgeCount(group.badge);

        return (
          <React.Fragment key={group.id}>
            {gi > 0 && <div className="border-t border-slate-800/50 my-2" />}

            {group.section ? (
              /* Section group: individual child icons */
              group.children.map(child => {
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
      })}
    </div>
  );

  /* ═══════════════════════════════════════
     RENDER — Full (expanded) mode
     ═══════════════════════════════════════ */
  const renderFull = () => (
    <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 pb-4" aria-label="Navigation">
      {navConfig.map(group => {
        const GIcon = group.icon ? iconMap[group.icon] : undefined;
        const groupLabel = L(group.label, group.labelEn);
        const hasActive = sectionHasActive(group.children);
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
              defaultOpen
              hasActiveChild={hasActive}
            >
              {group.children.map(child => {
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
            defaultOpen
            hasActiveChild={hasActive}
            badge={groupBadge}
          >
            {group.children.map(child => (
              <NavItem
                key={child.id}
                label={L(child.label, child.labelEn)}
                active={isActive(child)}
                indent
                onClick={() => handleNav(child.path)}
              />
            ))}
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
          'flex flex-col flex-shrink-0 bg-[#0c1929] transition-all duration-300 overflow-hidden',
          isMobile
            ? cn(
                'fixed inset-y-0 left-0 z-30 shadow-2xl shadow-black/40 w-[260px]',
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
            'flex items-center border-b border-slate-800/60 flex-shrink-0',
            effectiveMini ? 'justify-center px-2 py-3.5' : 'justify-between px-4 py-3'
          )}
        >
          {!effectiveMini && (
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/15 to-cyan-600/5 border border-cyan-500/10 flex items-center justify-center flex-shrink-0">
                <Activity size={16} className="text-cyan-400" />
              </div>
              <div className="min-w-0">
                <h1 className="text-base font-bold text-white tracking-tight leading-none">Nexora</h1>
                <p className="text-xs text-slate-500 mt-0.5 leading-none">
                  {zh ? '智能网络中枢' : 'SMART NET HUB'}
                </p>
              </div>
            </div>
          )}

          {effectiveMini && (
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/15 to-cyan-600/5 border border-cyan-500/10 flex items-center justify-center">
              <Activity size={16} className="text-cyan-400" />
            </div>
          )}

          {/* Mini toggle button (desktop only) */}
          {!isMobile && (
            <button
              onClick={toggleMini}
              className="p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors flex-shrink-0"
              aria-label={effectiveMini ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {effectiveMini ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          )}

          {/* Close button (mobile only) */}
          {isMobile && (
            <button
              onClick={onMobileClose}
              className="p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-white/5"
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
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
              <input
                ref={searchRef}
                type="text"
                placeholder={zh ? '搜索或跳转...' : 'Search or jump...'}
                className="w-full pl-8 pr-10 py-2 rounded-lg bg-slate-800/60 border border-slate-700/80 text-[13px] text-slate-300 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/30 transition-colors"
                onFocus={() => {
                  if (onOpenSearch) {
                    onOpenSearch();
                    searchRef.current?.blur();
                  }
                }}
                readOnly={!!onOpenSearch}
                aria-label={zh ? '搜索导航' : 'Search navigation'}
              />
              <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] border border-slate-600 rounded px-1.5 py-0.5 text-slate-500 font-mono leading-none">
                /
              </kbd>
            </div>
          </div>
        )}

        {effectiveMini && (
          <div className="flex justify-center my-3">
            <button
              onClick={() => onOpenSearch?.()}
              className="relative p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors group/search"
              aria-label={zh ? '搜索' : 'Search'}
            >
              <Search size={18} />
              <div
                className="absolute left-full top-1/2 -translate-y-1/2 ml-3
                  pointer-events-none opacity-0 group-hover/search:opacity-100
                  transition-opacity duration-150 z-50
                  bg-slate-800 text-slate-100 text-[12px] font-medium
                  py-1.5 px-3 rounded-lg shadow-lg shadow-black/40 whitespace-nowrap
                  border border-slate-700"
                role="tooltip"
              >
                {zh ? '搜索 (/)' : 'Search (/)'}
              </div>
            </button>
          </div>
        )}

        {/* ── Navigation ── */}
        {effectiveMini ? renderMini() : renderFull()}
      </aside>
    </>
  );
};

export default AppSidebar;
