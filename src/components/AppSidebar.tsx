/**
 * AppSidebar — NetPilot Navigation Sidebar
 * ─────────────────────────────────────────
 * Structure:
 *   Logo header
 *   ├─ FAVORITES (pinned items, right-click to manage)
 *   ├─ REAL-TIME     : Dashboard / Monitoring / Topology / Health Detection
 *   ├─ ALERTS        : Alert Center (with sub-items)
 *   ├─ ASSETS & CONFIG : Assets / Device List / IP·VLAN / Config & Compliance
 *   ├─ AUTOMATION    : Automation / Scheduled Tasks
 *   ├─ CAPACITY      : Capacity / Reports
 *   └─ MANAGEMENT    : Audit / Settings / Users
 *
 * Sub-components: SidebarSection, NavItem, BadgeCount
 * Features:
 *   - Collapsible mini mode (280px ↔ 64px) with tooltips
 *   - Drag-to-resize right edge (220px–360px)
 *   - "/" keyboard shortcut to call onOpenSearch()
 *   - Right-click "Pin to Favorites"
 *   - All state persisted to localStorage
 *   - Mobile drawer with backdrop
 *   - Single consistent active style
 */

import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  Download,
  FileText,
  FolderOpen,
  GitCompareArrows,
  Globe,
  HardDrive,
  History,
  LayoutDashboard,
  Monitor,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  Search,
  Server,
  Settings,
  ShieldCheck,
  TrendingUp,
  User,
  Wrench,
  X,
  Zap,
} from 'lucide-react';

/* ═══════════════════════════════════════
   Types
   ═══════════════════════════════════════ */

export interface AppSidebarProps {
  /** Current active route key, e.g. "dashboard", "monitoring", "alerts" */
  activeRoute: string;
  /** Current path from location.pathname for sub-route matching */
  currentPath: string;
  /** Navigate to a route */
  onNavigate: (route: string) => void;
  /** Navigate to a full path */
  onNavigatePath: (path: string) => void;
  /** Alert badge counts */
  alertCounts: { monitoring: number; alertCenter: number };
  /** Whether any P1 Critical alert exists */
  isP1Critical: boolean;
  /** UI language */
  language: string;
  /** Is mobile breakpoint */
  isMobile: boolean;
  /** External collapsed state (for mobile overlay control) */
  collapsed: boolean;
  /** Toggle collapsed state */
  onToggleCollapse: () => void;
  /** Open command palette / quick search */
  onOpenSearch?: () => void;
  /** i18n helper */
  t: (key: string) => string;
}

interface NavItemDef {
  id: string;
  icon: React.FC<{ size?: number; className?: string }>;
  label: string;
  /** If set, this is a path-based nav (use onNavigatePath) */
  path?: string;
  /** Badge count */
  badge?: number;
  /** Force red badge */
  badgeRed?: boolean;
  /** Children for expandable group */
  children?: NavItemDef[];
}

/* ═══════════════════════════════════════
   localStorage helpers
   ═══════════════════════════════════════ */

const LS_KEYS = {
  mini: 'np_sidebar_mini',
  width: 'np_sidebar_width',
  sections: 'np_sidebar_sections',
  pins: 'np_sidebar_pins',
} as const;

function lsGet<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}
function lsSet(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota */ }
}

/* ═══════════════════════════════════════
   Constants
   ═══════════════════════════════════════ */

const MIN_W = 220;
const MAX_W = 360;
const DEFAULT_W = 260;
const MINI_W = 64;

/* ═══════════════════════════════════════
   BadgeCount Sub-component
   ═══════════════════════════════════════ */

function BadgeCount({ count, red, mini }: { count: number; red?: boolean; mini?: boolean }) {
  if (count <= 0) return null;
  const display = count > 99 ? '99+' : String(count);
  const base = 'inline-flex items-center justify-center rounded-full font-bold tabular-nums leading-none flex-shrink-0';
  const size = mini ? 'min-w-[16px] h-4 text-[8px] px-1' : 'min-w-[18px] h-[18px] text-[9px] px-1.5';
  const color = red
    ? 'bg-red-500/90 text-white'
    : 'bg-[#2d3748] text-[#a0aec0]';
  return <span className={`${base} ${size} ${color}`} aria-label={`${count} items`}>{display}</span>;
}

/* ═══════════════════════════════════════
   SidebarSection Sub-component
   ═══════════════════════════════════════ */

function SidebarSection({ label, open, onToggle, mini, children }: {
  label: string; open: boolean; onToggle: () => void; mini: boolean; children: React.ReactNode;
}) {
  if (mini) return <>{open ? children : null}</>;
  return (
    <div>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-1.5 mt-3 mb-0.5 group/sec"
        aria-expanded={open}
        aria-label={label}
      >
        <ChevronRight
          size={10}
          className={`text-[#4a5568] transition-transform duration-150 ease-out flex-shrink-0 ${open ? 'rotate-90' : ''}`}
        />
        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#4a5568] select-none">
          {label}
        </span>
      </button>
      <div
        className={`overflow-hidden transition-all duration-150 ease-out ${open ? 'max-h-[800px] opacity-100' : 'max-h-0 opacity-0'}`}
        role="group"
        aria-label={label}
      >
        <div className="space-y-px px-2 pb-0.5">
          {children}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════
   NavItem Sub-component
   ═══════════════════════════════════════ */

function NavItem({
  icon: Icon, label, active, badge, badgeRed, mini, onClick, onContextMenu, hasChildren, expanded, depth = 0,
}: {
  icon: React.ElementType;
  label: string;
  active: boolean;
  badge?: number;
  badgeRed?: boolean;
  mini: boolean;
  onClick: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  hasChildren?: boolean;
  expanded?: boolean;
  depth?: number;
}) {
  return (
    <div className="relative group/navitem">
      <button
        onClick={onClick}
        onContextMenu={onContextMenu}
        className={`w-full flex items-center gap-2 rounded-lg transition-all duration-100 ease-out
          ${mini ? 'justify-center px-0 py-2.5 mx-auto' : `py-[7px] ${depth > 0 ? 'pl-9 pr-2.5' : 'pl-3 pr-2.5'}`}
          ${active
            ? 'bg-[rgba(6,182,212,0.08)] text-white'
            : 'text-[#a0aec0] hover:text-[#e2e8f0] hover:bg-white/[0.04]'
          }
        `}
        title={mini ? label : undefined}
        aria-label={label}
        aria-current={active ? 'page' : undefined}
      >
        <Icon
          size={mini ? 20 : depth > 0 ? 14 : 16}
          className={`flex-shrink-0 transition-colors duration-100 ${
            active ? 'text-[#06b6d4]' : 'text-[#718096]'
          }`}
        />
        {!mini && (
          <>
            <span className={`flex-1 text-left truncate ${depth > 0 ? 'text-[12px]' : 'text-[13px]'} ${active ? 'font-semibold' : 'font-medium'}`}>
              {label}
            </span>
            {(badge != null && badge > 0) && <BadgeCount count={badge} red={badgeRed} />}
            {hasChildren && (
              <ChevronRight
                size={12}
                className={`flex-shrink-0 text-[#4a5568] transition-transform duration-150 ease-out ${expanded ? 'rotate-90' : ''}`}
              />
            )}
          </>
        )}
      </button>
      {/* Tooltip in mini mode */}
      {mini && (
        <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2.5
          pointer-events-none opacity-0 group-hover/navitem:opacity-100
          transition-opacity duration-100 z-50
          bg-[#1a202c] text-[#e2e8f0] text-[11px] font-medium
          py-1.5 px-2.5 rounded-md shadow-lg shadow-black/30 whitespace-nowrap
          border border-white/5"
        >
          {label}
          {(badge != null && badge > 0) && <BadgeCount count={badge} red={badgeRed} mini />}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   Main Component
   ═══════════════════════════════════════ */

const AppSidebar: React.FC<AppSidebarProps> = ({
  activeRoute,
  currentPath,
  onNavigate,
  onNavigatePath,
  alertCounts,
  isP1Critical,
  language,
  isMobile,
  collapsed,
  onToggleCollapse,
  onOpenSearch,
  t,
}) => {
  const zh = language === 'zh';

  /* ─── Mini mode & width ─── */
  const [mini, setMini] = useState(() => lsGet(LS_KEYS.mini, false));
  const [width, setWidth] = useState(() => lsGet(LS_KEYS.width, DEFAULT_W));
  const [dragging, setDragging] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const toggleMini = useCallback(() => {
    setMini(p => { const next = !p; lsSet(LS_KEYS.mini, next); return next; });
  }, []);

  /* ─── Drag to resize ─── */
  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startW: width };
    setDragging(true);
  }, [width]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const newW = Math.min(MAX_W, Math.max(MIN_W, dragRef.current.startW + (e.clientX - dragRef.current.startX)));
      setWidth(newW);
    };
    const onUp = () => {
      setDragging(false);
      lsSet(LS_KEYS.width, width);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
  }, [dragging, width]);

  /* ─── Section open/close state ─── */
  const defaultSections: Record<string, boolean> = {
    realtime: true, alerts: true, assets: true, automation: true, capacity: true, management: true,
  };
  const [sections, setSections] = useState<Record<string, boolean>>(() => lsGet(LS_KEYS.sections, defaultSections));
  const toggleSection = useCallback((key: string) => {
    setSections(prev => {
      const next = { ...prev, [key]: !prev[key] };
      lsSet(LS_KEYS.sections, next);
      return next;
    });
  }, []);

  /* ─── Expandable group state ─── */
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    const s = new Set<string>();
    // auto-expand matching groups based on current route
    if (['monitoring', 'inventory-interfaces'].some(r => activeRoute === r || currentPath.includes(r.replace('-', '/')))) s.add('monitoring');
    if (['alerts', 'alert-rules', 'maintenance'].includes(activeRoute)) s.add('alert-center');
    if (currentPath.startsWith('/inventory') || activeRoute === 'ipam' || activeRoute === 'assets') s.add('inventory');
    if (currentPath.startsWith('/automation')) s.add('automation');
    if (currentPath.startsWith('/config') || activeRoute === 'compliance') s.add('config');
    if (['history', 'configuration', 'users'].includes(activeRoute)) s.add('management');
    return s;
  });
  const toggleGroup = useCallback((key: string) => {
    setExpandedGroups(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  }, []);

  /* ─── Pinned favorites ─── */
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => lsGet(LS_KEYS.pins, []));
  const togglePin = useCallback((id: string) => {
    setPinnedIds(prev => {
      const next = prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id].slice(0, 8);
      lsSet(LS_KEYS.pins, next);
      return next;
    });
  }, []);

  /* ─── Context menu for pinning ─── */
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; id: string; label: string } | null>(null);
  const handleCtx = useCallback((e: React.MouseEvent, id: string, label: string) => {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY, id, label });
  }, []);
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    document.addEventListener('click', close);
    document.addEventListener('contextmenu', close);
    return () => { document.removeEventListener('click', close); document.removeEventListener('contextmenu', close); };
  }, [ctxMenu]);

  /* ─── Keyboard shortcut "/" ─── */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
        e.preventDefault();
        onOpenSearch?.();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onOpenSearch]);

  /* ─── Navigation helpers ─── */
  const go = useCallback((id: string) => {
    // some ids map to paths, others to setActiveTab routes
    const pathMap: Record<string, string> = {
      'inventory-devices': '/inventory/devices',
      'inventory-interfaces': '/inventory/interfaces',
      'automation-execute': '/automation/execute',
      'automation-scenarios': '/automation/scenarios',
      'automation-history': '/automation/history',
      'config-backup': '/config/backup',
      'config-diff': '/config/diff',
      'config-search': '/config/search',
      'config-schedule': '/config/schedule',
      'config-drift': '/config/drift',
    };
    if (pathMap[id]) {
      onNavigatePath(pathMap[id]);
    } else {
      onNavigate(id);
    }
  }, [onNavigate, onNavigatePath]);

  const isActive = useCallback((id: string): boolean => {
    const pathMap: Record<string, string> = {
      'inventory-devices': '/inventory/devices',
      'inventory-interfaces': '/inventory/interfaces',
      'automation-execute': '/automation/execute',
      'automation-scenarios': '/automation/scenarios',
      'automation-history': '/automation/history',
      'config-backup': '/config/backup',
      'config-diff': '/config/diff',
      'config-search': '/config/search',
      'config-schedule': '/config/schedule',
      'config-drift': '/config/drift',
    };
    if (pathMap[id]) return currentPath === pathMap[id];
    return activeRoute === id;
  }, [activeRoute, currentPath]);

  /* ─── Build nav label map ─── */
  const labelOf = useCallback((id: string): string => {
    const map: Record<string, string> = {
      'dashboard':              zh ? '仪表盘' : 'Dashboard',
      'monitoring':             zh ? '平台资源' : 'Host Resources',
      'monitoring-group':       zh ? '监控中心' : 'Monitoring',
      'inventory-interfaces':   zh ? '接口监控' : 'Interface Monitor',
      'topology':               zh ? '网络拓扑' : 'Topology',
      'health':                 zh ? '健康检测' : 'Health Detection',
      'alerts':                 zh ? '告警信息' : 'Alert Desk',
      'alert-rules':            zh ? '告警规则' : 'Alert Rules',
      'maintenance':            zh ? '维护期'   : 'Maintenance',
      'alert-center':           zh ? '告警中心' : 'Alert Center',
      'assets':                 zh ? '资产管理' : 'Assets',
      'inventory-devices':      zh ? '设备列表' : 'Device List',
      'ipam':                   zh ? 'IP/VLAN管理' : 'IP/VLAN Mgmt',
      'config-group':           zh ? '配置与合规' : 'Config & Compliance',
      'config-backup':          zh ? '备份历史' : 'Backup History',
      'config-diff':            zh ? '对比查看' : 'Diff Compare',
      'config-search':          zh ? '配置搜索' : 'Config Search',
      'config-schedule':        zh ? '定时备份' : 'Scheduled Backup',
      'config-drift':           zh ? '配置漂移' : 'Config Drift',
      'compliance':             zh ? '合规检查' : 'Compliance',
      'automation-group':       zh ? '作业自动化' : 'Automation',
      'automation-execute':     zh ? '直接执行' : 'Direct Execute',
      'automation-scenarios':   zh ? '场景库'   : 'Scenarios',
      'automation-history':     zh ? '执行历史' : 'Exec History',
      'capacity':               zh ? '容量规划' : 'Capacity Planning',
      'reports':                zh ? '报表中心' : 'Reports',
      'history':                zh ? '审计日志' : 'Audit Logs',
      'configuration':          zh ? '平台设置' : 'Settings',
      'users':                  zh ? '用户管理' : 'User Mgmt',
    };
    return map[id] || id;
  }, [zh]);

  /* ─── Is any child of a group active ─── */
  const isGroupActive = useCallback((ids: string[]): boolean => ids.some(id => isActive(id)), [isActive]);

  /* ─── Actual sidebar width ─── */
  const effectiveMini = !isMobile && mini;
  const sidebarWidth = isMobile ? 280 : effectiveMini ? MINI_W : width;

  /* ─── Pinned items derived ─── */
  const pinnedItems = useMemo(() =>
    pinnedIds.map(id => ({ id, label: labelOf(id) })).filter(p => p.label !== p.id),
  [pinnedIds, labelOf]);

  /* ═══════════════════════════════════════
     RENDER
     ═══════════════════════════════════════ */
  return (
    <>
      {/* Mobile backdrop */}
      {isMobile && !collapsed && (
        <div
          className="fixed inset-0 z-[25] bg-black/60 backdrop-blur-[2px] md:hidden"
          onClick={onToggleCollapse}
          aria-hidden="true"
        />
      )}

      <aside
        ref={sidebarRef}
        className={`flex flex-col flex-shrink-0 bg-[#0f1117] transition-all duration-200 ease-out border-r border-white/[0.06] overflow-hidden select-none
          ${isMobile
            ? `fixed inset-y-0 left-0 z-30 shadow-2xl shadow-black/40 ${collapsed ? '-translate-x-full' : 'translate-x-0'}`
            : `relative z-20 ${collapsed && !effectiveMini ? 'w-0 min-w-0 opacity-0 pointer-events-none' : ''}`
          }
        `}
        style={{ width: collapsed && !isMobile && !effectiveMini ? 0 : sidebarWidth }}
        role="navigation"
        aria-label="Main navigation"
      >
        {/* ── Logo header ── */}
        <div className={`flex items-center border-b border-white/[0.06] flex-shrink-0 ${effectiveMini ? 'justify-center px-2 py-3.5' : 'justify-between px-4 py-3'}`}>
          {!effectiveMini && (
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#06b6d4]/20 to-[#0891b2]/10 border border-[#06b6d4]/15 flex items-center justify-center flex-shrink-0">
                <Activity size={16} className="text-[#06b6d4]" />
              </div>
              <div className="min-w-0">
                <h1 className="text-[15px] font-bold text-white tracking-tight leading-none">NetPilot</h1>
                <p className="text-[8px] font-semibold uppercase tracking-[0.14em] text-[#4a5568] mt-0.5 leading-none">
                  {zh ? '网络运维中枢' : 'NETWORK OPS'}
                </p>
              </div>
            </div>
          )}
          {effectiveMini && (
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#06b6d4]/20 to-[#0891b2]/10 border border-[#06b6d4]/15 flex items-center justify-center">
              <Activity size={16} className="text-[#06b6d4]" />
            </div>
          )}
          {!isMobile && (
            <button
              onClick={toggleMini}
              className={`p-1.5 rounded-md text-[#4a5568] hover:text-[#a0aec0] hover:bg-white/[0.04] transition-colors flex-shrink-0 ${effectiveMini ? 'mt-2' : ''}`}
              title={effectiveMini ? (zh ? '展开侧栏' : 'Expand sidebar') : (zh ? '收起侧栏' : 'Collapse sidebar')}
              aria-label={effectiveMini ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {effectiveMini ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          )}
          {isMobile && (
            <button
              onClick={onToggleCollapse}
              className="p-1.5 rounded-md text-[#4a5568] hover:text-[#a0aec0] hover:bg-white/[0.04]"
              title={zh ? '关闭' : 'Close'}
              aria-label="Close sidebar"
            >
              <X size={16} />
            </button>
          )}
        </div>

        {/* ── Searchable shortcut hint ── */}
        {!effectiveMini && (
          <button
            onClick={() => onOpenSearch?.()}
            className="mx-3 mt-2.5 flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[#4a5568] hover:text-[#a0aec0] hover:border-white/10 hover:bg-white/[0.05] transition-all"
            aria-label={zh ? '搜索导航' : 'Search navigation'}
          >
            <Search size={13} className="flex-shrink-0" />
            <span className="flex-1 text-left text-[11px]">{zh ? '搜索或跳转...' : 'Search or jump...'}</span>
            <kbd className="text-[9px] font-mono text-[#4a5568] bg-white/[0.04] border border-white/[0.06] rounded px-1 py-px">/</kbd>
          </button>
        )}
        {effectiveMini && (
          <button
            onClick={() => onOpenSearch?.()}
            className="mx-auto mt-2.5 p-2 rounded-lg text-[#4a5568] hover:text-[#a0aec0] hover:bg-white/[0.04] transition-colors group/search relative"
            title={zh ? '搜索 (/)' : 'Search (/)'}
            aria-label="Search"
          >
            <Search size={18} />
            <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2.5 pointer-events-none opacity-0 group-hover/search:opacity-100 transition-opacity z-50 bg-[#1a202c] text-[#e2e8f0] text-[11px] font-medium py-1.5 px-2.5 rounded-md shadow-lg shadow-black/30 whitespace-nowrap border border-white/5">
              {zh ? '搜索 (/)' : 'Search (/)'}
            </div>
          </button>
        )}

        {/* ── Scrollable nav ── */}
        <nav className="flex-1 overflow-y-auto overflow-x-hidden py-1 sidebar-nav-scroll" aria-label="Navigation">

          {/* ── FAVORITES ── */}
          {pinnedItems.length > 0 && !effectiveMini && (
            <SidebarSection label={zh ? '收藏' : 'FAVORITES'} open={sections.favorites !== false} onToggle={() => toggleSection('favorites')} mini={effectiveMini}>
              {pinnedItems.map(p => (
                <NavItem
                  key={p.id}
                  icon={Pin}
                  label={p.label}
                  active={isActive(p.id)}
                  mini={effectiveMini}
                  onClick={() => go(p.id)}
                  onContextMenu={e => handleCtx(e, p.id, p.label)}
                />
              ))}
            </SidebarSection>
          )}

          {/* ── REAL-TIME ── */}
          <SidebarSection label={zh ? '实时监控' : 'REAL-TIME'} open={sections.realtime !== false} onToggle={() => toggleSection('realtime')} mini={effectiveMini}>
            <NavItem icon={LayoutDashboard} label={labelOf('dashboard')} active={isActive('dashboard')} mini={effectiveMini}
              onClick={() => go('dashboard')} onContextMenu={e => handleCtx(e, 'dashboard', labelOf('dashboard'))} />

            {/* Monitoring group */}
            <NavItem
              icon={TrendingUp}
              label={labelOf('monitoring-group')}
              active={isGroupActive(['monitoring', 'inventory-interfaces'])}
              mini={effectiveMini}
              onClick={() => { toggleGroup('monitoring'); if (!expandedGroups.has('monitoring')) go('monitoring'); }}
              onContextMenu={e => handleCtx(e, 'monitoring', labelOf('monitoring-group'))}
              hasChildren
              expanded={expandedGroups.has('monitoring')}
              badge={alertCounts.monitoring > 0 ? alertCounts.monitoring : undefined}
            />
            {expandedGroups.has('monitoring') && !effectiveMini && (
              <div className="space-y-px">
                <NavItem icon={Monitor} label={labelOf('monitoring')} active={isActive('monitoring')} mini={false} depth={1}
                  onClick={() => go('monitoring')} onContextMenu={e => handleCtx(e, 'monitoring', labelOf('monitoring'))} />
                <NavItem icon={Activity} label={labelOf('inventory-interfaces')} active={isActive('inventory-interfaces')} mini={false} depth={1}
                  onClick={() => go('inventory-interfaces')} onContextMenu={e => handleCtx(e, 'inventory-interfaces', labelOf('inventory-interfaces'))} />
              </div>
            )}

            <NavItem icon={Globe} label={labelOf('topology')} active={isActive('topology')} mini={effectiveMini}
              onClick={() => go('topology')} onContextMenu={e => handleCtx(e, 'topology', labelOf('topology'))} />
            <NavItem icon={Activity} label={labelOf('health')} active={isActive('health')} mini={effectiveMini}
              onClick={() => go('health')} onContextMenu={e => handleCtx(e, 'health', labelOf('health'))} />
          </SidebarSection>

          {/* ── ALERTS ── */}
          <SidebarSection label={zh ? '告警处置' : 'ALERTS'} open={sections.alerts !== false} onToggle={() => toggleSection('alerts')} mini={effectiveMini}>
            <NavItem
              icon={AlertTriangle}
              label={labelOf('alert-center')}
              active={isGroupActive(['alerts', 'alert-rules', 'maintenance'])}
              mini={effectiveMini}
              onClick={() => { toggleGroup('alert-center'); if (!expandedGroups.has('alert-center')) go('alerts'); }}
              onContextMenu={e => handleCtx(e, 'alerts', labelOf('alert-center'))}
              hasChildren
              expanded={expandedGroups.has('alert-center')}
              badge={alertCounts.alertCenter}
              badgeRed={isP1Critical}
            />
            {expandedGroups.has('alert-center') && !effectiveMini && (
              <div className="space-y-px">
                <NavItem icon={AlertTriangle} label={labelOf('alerts')} active={isActive('alerts')} mini={false} depth={1}
                  onClick={() => go('alerts')} onContextMenu={e => handleCtx(e, 'alerts', labelOf('alerts'))} />
                <NavItem icon={Settings} label={labelOf('alert-rules')} active={isActive('alert-rules')} mini={false} depth={1}
                  onClick={() => go('alert-rules')} onContextMenu={e => handleCtx(e, 'alert-rules', labelOf('alert-rules'))} />
                <NavItem icon={Wrench} label={labelOf('maintenance')} active={isActive('maintenance')} mini={false} depth={1}
                  onClick={() => go('maintenance')} onContextMenu={e => handleCtx(e, 'maintenance', labelOf('maintenance'))} />
              </div>
            )}
          </SidebarSection>

          {/* ── ASSETS & CONFIG ── */}
          <SidebarSection label={zh ? '资产与配置' : 'ASSETS & CONFIG'} open={sections.assets !== false} onToggle={() => toggleSection('assets')} mini={effectiveMini}>
            <NavItem icon={HardDrive} label={labelOf('assets')} active={isActive('assets')} mini={effectiveMini}
              onClick={() => go('assets')} onContextMenu={e => handleCtx(e, 'assets', labelOf('assets'))} />
            <NavItem icon={Server} label={labelOf('inventory-devices')} active={isActive('inventory-devices')} mini={effectiveMini}
              onClick={() => go('inventory-devices')} onContextMenu={e => handleCtx(e, 'inventory-devices', labelOf('inventory-devices'))} />
            <NavItem icon={Network} label={labelOf('ipam')} active={isActive('ipam')} mini={effectiveMini}
              onClick={() => go('ipam')} onContextMenu={e => handleCtx(e, 'ipam', labelOf('ipam'))} />

            {/* Config & Compliance group */}
            <NavItem
              icon={FolderOpen}
              label={labelOf('config-group')}
              active={isGroupActive(['config-backup', 'config-diff', 'config-search', 'config-schedule', 'config-drift', 'compliance'])}
              mini={effectiveMini}
              onClick={() => { toggleGroup('config'); if (!expandedGroups.has('config')) go('config-backup'); }}
              onContextMenu={e => handleCtx(e, 'config-backup', labelOf('config-group'))}
              hasChildren
              expanded={expandedGroups.has('config')}
            />
            {expandedGroups.has('config') && !effectiveMini && (
              <div className="space-y-px">
                <NavItem icon={Download} label={labelOf('config-backup')} active={isActive('config-backup')} mini={false} depth={1}
                  onClick={() => go('config-backup')} onContextMenu={e => handleCtx(e, 'config-backup', labelOf('config-backup'))} />
                <NavItem icon={FileText} label={labelOf('config-diff')} active={isActive('config-diff')} mini={false} depth={1}
                  onClick={() => go('config-diff')} onContextMenu={e => handleCtx(e, 'config-diff', labelOf('config-diff'))} />
                <NavItem icon={Search} label={labelOf('config-search')} active={isActive('config-search')} mini={false} depth={1}
                  onClick={() => go('config-search')} onContextMenu={e => handleCtx(e, 'config-search', labelOf('config-search'))} />
                <NavItem icon={Clock} label={labelOf('config-schedule')} active={isActive('config-schedule')} mini={false} depth={1}
                  onClick={() => go('config-schedule')} onContextMenu={e => handleCtx(e, 'config-schedule', labelOf('config-schedule'))} />
                <NavItem icon={GitCompareArrows} label={labelOf('config-drift')} active={isActive('config-drift')} mini={false} depth={1}
                  onClick={() => go('config-drift')} onContextMenu={e => handleCtx(e, 'config-drift', labelOf('config-drift'))} />
                <NavItem icon={ShieldCheck} label={labelOf('compliance')} active={isActive('compliance')} mini={false} depth={1}
                  onClick={() => go('compliance')} onContextMenu={e => handleCtx(e, 'compliance', labelOf('compliance'))} />
              </div>
            )}
          </SidebarSection>

          {/* ── AUTOMATION ── */}
          <SidebarSection label={zh ? '自动化' : 'AUTOMATION'} open={sections.automation !== false} onToggle={() => toggleSection('automation')} mini={effectiveMini}>
            <NavItem
              icon={Zap}
              label={labelOf('automation-group')}
              active={isGroupActive(['automation-execute', 'automation-scenarios', 'automation-history'])}
              mini={effectiveMini}
              onClick={() => { toggleGroup('automation'); if (!expandedGroups.has('automation')) go('automation-execute'); }}
              onContextMenu={e => handleCtx(e, 'automation-execute', labelOf('automation-group'))}
              hasChildren
              expanded={expandedGroups.has('automation')}
            />
            {expandedGroups.has('automation') && !effectiveMini && (
              <div className="space-y-px">
                <NavItem icon={Zap} label={labelOf('automation-execute')} active={isActive('automation-execute')} mini={false} depth={1}
                  onClick={() => go('automation-execute')} onContextMenu={e => handleCtx(e, 'automation-execute', labelOf('automation-execute'))} />
                <NavItem icon={FolderOpen} label={labelOf('automation-scenarios')} active={isActive('automation-scenarios')} mini={false} depth={1}
                  onClick={() => go('automation-scenarios')} onContextMenu={e => handleCtx(e, 'automation-scenarios', labelOf('automation-scenarios'))} />
                <NavItem icon={History} label={labelOf('automation-history')} active={isActive('automation-history')} mini={false} depth={1}
                  onClick={() => go('automation-history')} onContextMenu={e => handleCtx(e, 'automation-history', labelOf('automation-history'))} />
              </div>
            )}
          </SidebarSection>

          {/* ── CAPACITY & REPORTS ── */}
          <SidebarSection label={zh ? '容量与报表' : 'CAPACITY'} open={sections.capacity !== false} onToggle={() => toggleSection('capacity')} mini={effectiveMini}>
            <NavItem icon={Cpu} label={labelOf('capacity')} active={isActive('capacity')} mini={effectiveMini}
              onClick={() => go('capacity')} onContextMenu={e => handleCtx(e, 'capacity', labelOf('capacity'))} />
            <NavItem icon={BarChart3} label={labelOf('reports')} active={isActive('reports')} mini={effectiveMini}
              onClick={() => go('reports')} onContextMenu={e => handleCtx(e, 'reports', labelOf('reports'))} />
          </SidebarSection>

          {/* ── MANAGEMENT ── */}
          <SidebarSection label={zh ? '平台管理' : 'MANAGEMENT'} open={sections.management !== false} onToggle={() => toggleSection('management')} mini={effectiveMini}>
            <NavItem icon={History} label={labelOf('history')} active={isActive('history')} mini={effectiveMini}
              onClick={() => go('history')} onContextMenu={e => handleCtx(e, 'history', labelOf('history'))} />
            <NavItem icon={Settings} label={labelOf('configuration')} active={isActive('configuration')} mini={effectiveMini}
              onClick={() => go('configuration')} onContextMenu={e => handleCtx(e, 'configuration', labelOf('configuration'))} />
            <NavItem icon={User} label={labelOf('users')} active={isActive('users')} mini={effectiveMini}
              onClick={() => go('users')} onContextMenu={e => handleCtx(e, 'users', labelOf('users'))} />
          </SidebarSection>

        </nav>

        {/* ── Resize handle (desktop non-mini only) ── */}
        {!isMobile && !effectiveMini && (
          <div
            onMouseDown={onDragStart}
            className={`absolute top-0 right-0 w-1 h-full cursor-col-resize z-10 transition-colors
              ${dragging ? 'bg-[#06b6d4]/40' : 'bg-transparent hover:bg-[#06b6d4]/20'}
            `}
            role="separator"
            aria-label="Resize sidebar"
          />
        )}
      </aside>

      {/* ── Context menu (pin/unpin) ── */}
      {ctxMenu && (
        <div
          className="fixed z-[60] bg-[#1a202c] rounded-lg border border-white/10 shadow-xl shadow-black/40 py-1 min-w-[160px]"
          style={{ top: ctxMenu.y, left: ctxMenu.x }}
        >
          <button
            onClick={() => { togglePin(ctxMenu.id); setCtxMenu(null); }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-[#a0aec0] hover:text-white hover:bg-white/[0.06] transition-colors"
          >
            <Pin size={12} />
            {pinnedIds.includes(ctxMenu.id)
              ? (zh ? '取消收藏' : 'Remove from Favorites')
              : (zh ? '添加到收藏' : 'Pin to Favorites')
            }
          </button>
        </div>
      )}
    </>
  );
};

export default AppSidebar;
