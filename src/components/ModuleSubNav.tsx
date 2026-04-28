/**
 * ModuleSubNav — Left sidebar that shows only the current module's sub-items.
 * Detects the current module group from navConfig and renders sibling items vertically.
 * Supports collapsing to a thin rail.
 */
import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { navConfig } from './AppSidebar/navConfig';

interface ModuleSubNavProps {
  language: string;
  userRole?: string;
  currentUser?: any;
}

const ROLE_LEVEL: Record<string, number> = { Administrator: 3, Operator: 2, Viewer: 1 };

const LS_KEY = 'nexora_module_nav';

const ModuleSubNav: React.FC<ModuleSubNavProps> = ({ language, userRole, currentUser }) => {
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

  return (
    <aside
      className="flex-shrink-0 flex flex-col h-full border-r transition-all duration-200 select-none"
      style={{
        width: collapsed ? 44 : 192,
        background: 'var(--header-bg)',
        borderColor: 'var(--header-border)',
      }}
    >
      {/* Group title */}
      {!collapsed && (
        <div
          className="px-4 pt-4 pb-2 text-[11px] font-semibold tracking-wider uppercase"
          style={{ color: 'var(--dim-text)' }}
        >
          {groupLabel}
        </div>
      )}

      {/* Nav items */}
      <nav className={`flex-1 overflow-y-auto ${collapsed ? 'px-1 pt-3' : 'px-2'}`}>
        {visibleChildren.map(child => {
          const active = isActive(child);
          const label = zh ? child.label : (child.labelEn || child.label);

          if (collapsed) {
            // Collapsed: show first 2 chars as abbreviation
            const abbr = label.slice(0, 2);
            return (
              <button
                key={child.id}
                onClick={() => navigate(child.path)}
                title={label}
                className="w-full flex items-center justify-center rounded-lg mb-1 transition-all"
                style={{
                  height: 36,
                  color: active ? '#06b6d4' : 'var(--body-text)',
                  background: active ? 'rgba(6,182,212,0.08)' : 'transparent',
                  fontSize: 11,
                  fontWeight: active ? 600 : 500,
                }}
                onMouseEnter={e => {
                  if (!active) e.currentTarget.style.background = 'var(--app-hover-bg)';
                }}
                onMouseLeave={e => {
                  if (!active) e.currentTarget.style.background = 'transparent';
                }}
              >
                <span className="relative">
                  {abbr}
                  {child.id === 'my-todo' && todoCounts.my > 0 && (
                    <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                  )}
                  {child.id === 'group-todo' && todoCounts.group > 0 && (
                    <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                  )}
                  {child.id === 'my-focus' && todoCounts.focus > 0 && (
                    <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
                  )}
                </span>
              </button>
            );
          }

          return (
            <button
              key={child.id}
              onClick={() => navigate(child.path)}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] transition-all mb-0.5"
              style={{
                color: active ? '#06b6d4' : 'var(--body-text)',
                background: active ? 'rgba(6,182,212,0.08)' : 'transparent',
                fontWeight: active ? 600 : 400,
              }}
              onMouseEnter={e => {
                if (!active) e.currentTarget.style.background = 'var(--app-hover-bg)';
              }}
              onMouseLeave={e => {
                if (!active) e.currentTarget.style.background = 'transparent';
              }}
            >
              {active && (
                <span
                  className="w-[3px] h-4 rounded-full flex-shrink-0"
                  style={{ background: '#06b6d4' }}
                />
              )}
              <span className="truncate">{label}</span>
              {child.id === 'my-todo' && todoCounts.my > 0 && (
                <span className="ml-auto px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-rose-500 text-white leading-none min-w-[16px] text-center">
                  {todoCounts.my}
                </span>
              )}
              {child.id === 'group-todo' && todoCounts.group > 0 && (
                <span className="ml-auto px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-amber-500 text-white leading-none min-w-[16px] text-center">
                  {todoCounts.group}
                </span>
              )}
              {child.id === 'my-focus' && todoCounts.focus > 0 && (
                <span className="ml-auto px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-indigo-500 text-white leading-none min-w-[16px] text-center">
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
    </aside>
  );
};

export default ModuleSubNav;
