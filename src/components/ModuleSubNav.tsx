/**
 * ModuleSubNav — Left sidebar that shows only the current module's sub-items.
 * Detects the current module group from navConfig and renders sibling items vertically.
 * Supports collapsing to a thin rail.
 */
import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  Archive,
  BarChart2,
  BarChart3,
  Bell,
  Building2,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  Clock,
  Code2,
  Columns3,
  Database,
  FileCode2,
  FileEdit,
  FileSearch,
  FileText,
  GitCompare,
  Globe,
  History,
  Inbox,
  Key,
  Layers,
  LayoutDashboard,
  MapPin,
  Network,
  Package,
  PlusCircle,
  Router,
  Search,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  Tag,
  Terminal,
  Timer,
  TrendingUp,
  User,
  UserCheck,
  Users,
  Wrench,
  Zap,
} from 'lucide-react';
import { navConfig } from './AppSidebar/navConfig';
import { useSystem } from '../hooks/useSystem';

interface ModuleSubNavProps {
  language: string;
  userRole?: string;
  currentUser?: any;
}

const ROLE_LEVEL: Record<string, number> = { Administrator: 3, Operator: 2, Viewer: 1 };

const LS_KEY = 'nexora_module_nav';

/** Map icon string keys (from navConfig) → lucide component */
const iconMap: Record<string, React.ElementType> = {
  Activity, Archive, BarChart2, BarChart3, Bell, Building2, CalendarClock,
  ClipboardCheck, ClipboardList, Clock, Code2, Columns3, Database,
  FileCode2, FileEdit, FileSearch, FileText, GitCompare, Globe,
  History, Inbox, Key, Layers, LayoutDashboard, MapPin, Network, Package,
  PlusCircle, Router, Search, Server, Shield, ShieldAlert, ShieldCheck,
  SlidersHorizontal, Star, Tag, Terminal, Timer, TrendingUp,
  User, UserCheck, Users, Wrench, Zap,
};

const ACCENT = '#0078d4';

const ModuleSubNav: React.FC<ModuleSubNavProps> = ({ language, userRole, currentUser }) => {
  const { systemInfo } = useSystem();
  const location = useLocation();
  const navigate = useNavigate();
  const zh = language === 'zh';
  const pathname = location.pathname;

  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(LS_KEY) === 'collapsed'; } catch { return false; }
  });

  const [todoCounts, setTodoCounts] = useState<{ my: number; group: number; focus: number }>({ my: 0, group: 0, focus: 0 });

  const toggleCollapsed = () => {
    setCollapsed(prev => {
      const next = !prev;
      try { localStorage.setItem(LS_KEY, next ? 'collapsed' : 'expanded'); } catch { /* noop */ }
      return next;
    });
  };

  // Find group that owns the current path
  const currentGroup = navConfig.find(group =>
    group.children.some(child => {
      if (child.activeMatch && pathname.startsWith(child.activeMatch)) return true;
      return pathname === child.path || pathname.startsWith(child.path + '/');
    })
  );

  useEffect(() => {
    if (currentGroup?.id !== 'tickets' || !currentUser) return;

    let isMounted = true;
    const fetchCounts = async () => {
      try {
        const token = localStorage.getItem('netops_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : undefined;

        if (currentUser.username) {
          const respMy = await fetch(`/api/change-orders?page=1&page_size=1&my_todo=${encodeURIComponent(currentUser.username)}`, { headers });
          const dataMy = await respMy.json();
          if (dataMy.success && isMounted) {
            setTodoCounts(prev => ({ ...prev, my: dataMy.total || 0 }));
          }
        }

        if (Array.isArray(currentUser.change_groups) && currentUser.change_groups.length > 0) {
          const respGrp = await fetch(`/api/change-orders?page=1&page_size=1&group_todo=${encodeURIComponent(currentUser.change_groups.join(','))}`, { headers });
          const dataGrp = await respGrp.json();
          if (dataGrp.success && isMounted) {
            setTodoCounts(prev => ({ ...prev, group: dataGrp.total || 0 }));
          }
        }

        if (currentUser.id) {
          const respFoc = await fetch(`/api/change-orders?page=1&page_size=1&bookmarked=${encodeURIComponent(currentUser.id)}`, { headers });
          const dataFoc = await respFoc.json();
          if (dataFoc.success && isMounted) {
            setTodoCounts(prev => ({ ...prev, focus: dataFoc.total || 0 }));
          }
        }
      } catch (e) {
        console.error('Failed to fetch todo counts', e);
      }
    };

    fetchCounts();

    const handleRefresh = () => {
      fetchCounts();
    };
    window.addEventListener('refresh-todo-badge', handleRefresh);

    return () => {
      isMounted = false;
      window.removeEventListener('refresh-todo-badge', handleRefresh);
    };
  }, [currentGroup?.id, currentUser?.id, currentUser?.username, currentUser?.change_groups, pathname]);

  if (!currentGroup) return null;

  const userLvl = ROLE_LEVEL[userRole ?? ''] ?? 0;
  const visibleChildren = currentGroup.children.filter(c => {
    if (!c.requiredRole) return true;
    return userLvl >= (ROLE_LEVEL[c.requiredRole] ?? 99);
  });

  if (visibleChildren.length === 0) return null;

  const isActive = (child: typeof visibleChildren[0]) => {
    if (child.activeMatch && pathname.startsWith(child.activeMatch)) return true;
    return pathname === child.path || pathname.startsWith(child.path + '/');
  };

  const groupLabel = zh ? currentGroup.label : (currentGroup.labelEn || currentGroup.label);
  const GroupIcon = currentGroup.icon ? iconMap[currentGroup.icon] : undefined;

  return (
    <aside
      className="flex-shrink-0 flex flex-col h-full border-r transition-all duration-200 select-none animate-[fadeIn_0.2s_ease-out]"
      style={{
        width: collapsed ? 48 : 200,
        background: 'var(--sidebar-bg)',
        borderColor: 'var(--header-border)',
      }}
    >
      {/* Group title */}
      {!collapsed ? (
        <div className="px-3 pt-4 pb-2 flex items-center gap-2">
          {GroupIcon && (
            <span
              className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
              style={{ background: `${ACCENT}14`, color: ACCENT }}
            >
              <GroupIcon size={13} strokeWidth={1.8} />
            </span>
          )}
          <span
            className="text-[11px] font-semibold tracking-[0.12em] uppercase truncate"
            style={{ color: 'var(--muted-text)' }}
          >
            {groupLabel}
          </span>
        </div>
      ) : (
        GroupIcon && (
          <div className="pt-3 pb-2 flex justify-center">
            <span
              className="flex items-center justify-center w-7 h-7 rounded-md"
              style={{ background: `${ACCENT}14`, color: ACCENT }}
              title={groupLabel}
            >
              <GroupIcon size={14} strokeWidth={1.8} />
            </span>
          </div>
        )
      )}

      {/* Nav items */}
      <nav className={`flex-1 overflow-y-auto ${collapsed ? 'px-1.5 pt-2' : 'px-2'}`}>
        {visibleChildren.map(child => {
          const active = isActive(child);
          const label = zh ? child.label : (child.labelEn || child.label);
          const Icon = child.icon ? iconMap[child.icon] : undefined;

          if (collapsed) {
            return (
              <button
                key={child.id}
                onClick={() => navigate(child.path)}
                title={label}
                className="w-full flex items-center justify-center rounded-lg mb-1 transition-all relative"
                style={{
                  height: 36,
                  color: active ? ACCENT : 'var(--body-text)',
                  background: active ? 'rgba(0,120,212,0.08)' : 'transparent',
                }}
                onMouseEnter={e => {
                  if (!active) e.currentTarget.style.background = 'var(--app-hover-bg)';
                }}
                onMouseLeave={e => {
                  if (!active) e.currentTarget.style.background = 'transparent';
                }}
              >
                {Icon ? (
                  <Icon size={16} strokeWidth={active ? 2 : 1.7} />
                ) : (
                  <span className="text-[11px] font-semibold">{label.slice(0, 2)}</span>
                )}
                {child.id === 'my-todo' && todoCounts.my > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                )}
                {child.id === 'group-todo' && todoCounts.group > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                )}
                {child.id === 'my-focus' && todoCounts.focus > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
                )}
              </button>
            );
          }

          return (
            <button
              key={child.id}
              onClick={() => navigate(child.path)}
              className="group relative w-full flex items-center gap-2.5 pl-3 pr-2.5 py-2 rounded-lg text-[13px] transition-all mb-0.5"
              style={{
                color: active ? ACCENT : 'var(--body-text)',
                background: active ? 'rgba(0,120,212,0.08)' : 'transparent',
                fontWeight: active ? 600 : 400,
              }}
              onMouseEnter={e => {
                if (!active) e.currentTarget.style.background = 'var(--app-hover-bg)';
              }}
              onMouseLeave={e => {
                if (!active) e.currentTarget.style.background = 'transparent';
              }}
            >
              {/* Left active bar */}
              <span
                aria-hidden
                className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full transition-opacity"
                style={{ background: ACCENT, opacity: active ? 1 : 0 }}
              />
              {Icon && (
                <Icon
                  size={15}
                  strokeWidth={active ? 2 : 1.7}
                  className="flex-shrink-0"
                  style={{
                    color: active ? ACCENT : 'var(--muted-text)',
                  }}
                />
              )}
              <span className="truncate flex-1 text-left">{label}</span>
              {child.id === 'my-todo' && todoCounts.my > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-rose-500 text-white leading-none min-w-[16px] text-center">
                  {todoCounts.my}
                </span>
              )}
              {child.id === 'group-todo' && todoCounts.group > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-amber-500 text-white leading-none min-w-[16px] text-center">
                  {todoCounts.group}
                </span>
              )}
              {child.id === 'my-focus' && todoCounts.focus > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-indigo-500 text-white leading-none min-w-[16px] text-center">
                  {todoCounts.focus}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="flex-shrink-0 border-t px-2 py-2" style={{ borderColor: 'var(--header-border)' }}>
        <button
          onClick={toggleCollapsed}
          className="w-full flex items-center justify-center rounded-lg p-1.5 transition-colors"
          style={{ color: 'var(--dim-text)' }}
          title={zh ? (collapsed ? '展开导航' : '收起导航') : (collapsed ? 'Expand' : 'Collapse')}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--app-hover-bg)'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Version Info Footer */}
      {!collapsed && (
        <div className="px-3 py-3 border-t flex flex-col gap-1 flex-shrink-0" style={{ borderColor: 'var(--header-border)', background: 'var(--app-hover-bg)' }}>
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--dim-text)' }}>
              {zh ? '版本' : 'VER'}
            </span>
            <span className="text-[10px] font-mono font-bold" style={{ color: ACCENT }}>
              v{systemInfo?.version || '0.1.0'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--dim-text)' }}>
              {zh ? '授权' : 'ED'}
            </span>
            <span className="text-[10px] font-bold" style={{ color: 'var(--muted-text)' }}>
              {systemInfo?.edition || 'Standard'}
            </span>
          </div>
        </div>
      )}
    </aside>
  );
};

export default ModuleSubNav;
