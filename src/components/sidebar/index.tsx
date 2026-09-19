import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  Download,
  FileText,
  FolderOpen,
  GitCompareArrows,
  Globe,
  History,
  LayoutDashboard,
  Monitor,
  Network,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Star,
  TrendingUp,
  User,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import type { HostResourceSnapshot } from '../../types';
import type { NavSection, NavItem, NavChild } from './types';
import { SectionHeader, NavMenuItem, NavGroupItem, QuickAccessChip } from './MenuItem';
import { useSystem } from '../../hooks/useSystem';

/* ════════════════════════════════════════════════════════════════
   Props — 完全保持与 App.tsx 外部调用兼容
   ════════════════════════════════════════════════════════════════ */

interface RecentSidebarItem {
  path: string;
  label: string;
}

interface SidebarProps {
  isMobile: boolean;
  sidebarCollapsed: boolean;
  language: string;
  currentPath: string;
  activeTab: string;
  pinnedPaths: string[];
  recentSidebarItems: RecentSidebarItem[];
  hostResourceTone: string;
  hostResourceSummary: string;
  hostResources: HostResourceSnapshot | null;
  alertNavTone: string;
  unreadNotificationCount: number;
  realtimeSectionOpen: boolean;
  alertsSectionOpen: boolean;
  assetsSectionOpen: boolean;
  automationSectionOpen: boolean;
  capacitySectionOpen: boolean;
  managementSectionOpen: boolean;
  monitoringGroupOpen: boolean;
  alertGroupOpen: boolean;
  inventoryGroupOpen: boolean;
  automationGroupOpen: boolean;
  configGroupOpen: boolean;
  managementGroupOpen: boolean;
  t: (key: string) => string;
  getSidebarRecentLabel: (path: string) => string;
  navTo: (path: string) => void;
  setActiveTab: (tab: string) => void;
  togglePin: (path: string) => void;
  formatCompactResourcePercent: (value: number | null | undefined) => string;
  setSidebarCollapsed: React.Dispatch<React.SetStateAction<boolean>>;
  setRealtimeSectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setAlertsSectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setAssetsSectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setAutomationSectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setCapacitySectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setManagementSectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setMonitoringGroupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setAlertGroupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setInventoryGroupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setAutomationGroupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setConfigGroupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setManagementGroupOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

/* ════════════════════════════════════════════════════════════════
   Sidebar 主组件
   ════════════════════════════════════════════════════════════════ */

const Sidebar: React.FC<SidebarProps> = (props) => {
  const { systemInfo } = useSystem();
  const {
    isMobile,
    sidebarCollapsed,
    language,
    currentPath,
    activeTab,
    pinnedPaths,
    recentSidebarItems,
    hostResourceTone,
    hostResourceSummary,
    hostResources,
    alertNavTone,
    unreadNotificationCount,
    t,
    getSidebarRecentLabel,
    navTo,
    setActiveTab,
    togglePin,
    formatCompactResourcePercent,
    setSidebarCollapsed,
    setRealtimeSectionOpen,
    setAlertsSectionOpen,
    setAssetsSectionOpen,
    setAutomationSectionOpen,
    setCapacitySectionOpen,
    setManagementSectionOpen,
    setMonitoringGroupOpen,
    setAlertGroupOpen,
    setInventoryGroupOpen,
    setAutomationGroupOpen,
    setConfigGroupOpen,
    setManagementGroupOpen,
  } = props;

  /* ── mini sidebar state (desktop only) ── */
  const isMini = !isMobile && sidebarCollapsed;

  /* ── cmd+K 搜索 ── */
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
      if (e.key === 'Escape') setSearchOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    if (searchOpen) {
      setSearchQuery('');
      requestAnimationFrame(() => searchInputRef.current?.focus());
    }
  }, [searchOpen]);

  /* ── 构建菜单数据 ── */
  const metricSlot = useMemo(() => {
    if (isMini) return undefined;
    return (
      <span className={`shrink-0 text-[10px] font-mono tabular-nums px-1.5 py-0.5 rounded border ${hostResourceTone}`} title={hostResourceSummary}>
        {hostResources
          ? `${formatCompactResourcePercent(hostResources.cpu_percent)}/${formatCompactResourcePercent(hostResources.memory_percent)}`
          : '--/--'}
      </span>
    );
  }, [hostResources, hostResourceTone, hostResourceSummary, formatCompactResourcePercent, isMini]);

  const sections: NavSection[] = useMemo(() => [
    {
      id: 'realtime',
      labelZh: '实时监控',
      labelEn: 'MONITORING',
      items: [
        { id: 'dashboard', tabKey: 'dashboard', icon: LayoutDashboard, labelZh: '仪表盘', labelEn: 'Dashboard' },
        {
          id: 'monitoring-group', tabKey: 'monitoring', icon: TrendingUp, labelZh: '监控中心', labelEn: 'Monitoring',
          metricSlot,
          children: [
            { id: 'monitoring', path: null, icon: Monitor, labelZh: '平台资源', labelEn: 'Host Resources' },
          ],
        },
        { id: 'topology', tabKey: 'topology', icon: Globe, labelZh: '网络拓扑', labelEn: 'Topology' },
        { id: 'health', tabKey: 'health', icon: Activity, labelZh: '健康检测', labelEn: 'Health Check' },
      ],
    },
    {
      id: 'alerts',
      labelZh: '告警处置',
      labelEn: 'ALERTS',
      items: [
        {
          id: 'alert-group', icon: AlertTriangle, labelZh: '告警中心', labelEn: 'Alert Center',
          badge: unreadNotificationCount,
          badgeTone: alertNavTone,
          children: [
            { id: 'alerts', path: null, icon: AlertTriangle, labelZh: '告警信息', labelEn: 'Alert Desk' },
            { id: 'alert-rules', path: null, icon: Settings, labelZh: '告警规则', labelEn: 'Alert Rules' },
            { id: 'maintenance', path: null, icon: Wrench, labelZh: '维护期', labelEn: 'Maintenance' },
          ],
        },
      ],
    },
    {
      id: 'assets',
      labelZh: '资产配置',
      labelEn: 'ASSETS',
      items: [
        {
          id: 'inventory-group', icon: Database, labelZh: '资产清单', labelEn: 'Inventory',
          children: [
            { id: 'devices', path: '/inventory/devices', icon: Server, labelZh: '设备列表', labelEn: 'Devices' },
            { id: 'ipam', path: null, icon: Network, labelZh: 'IP/VLAN管理', labelEn: 'IP/VLAN' },
          ],
        },
      ],
    },
    {
      id: 'automation',
      labelZh: '自动化',
      labelEn: 'AUTOMATION',
      items: [
        {
          id: 'automation-group', icon: Zap, labelZh: '作业管理', labelEn: 'Jobs',
          children: [
            { id: 'auto-execute', path: '/automation/execute', icon: Zap, labelZh: '直接执行', labelEn: 'Execute' },
            { id: 'auto-scenarios', path: '/automation/scenarios', icon: FolderOpen, labelZh: '场景库', labelEn: 'Scenarios' },
            { id: 'auto-execution-plan', path: '/automation/schedule', icon: Clock, labelZh: '执行计划', labelEn: 'Execution Plan' },
            { id: 'auto-scheduled-jobs', path: '/automation/scheduled-jobs', icon: CalendarClock, labelZh: '定时作业', labelEn: 'Scheduled Jobs' },
            { id: 'auto-history', path: '/automation/schedule-history', icon: History, labelZh: '执行历史', labelEn: 'Execution History' },
          ],
        },
        {
          id: 'config-group', icon: FolderOpen, labelZh: '配置中心', labelEn: 'Config Center',
          children: [
            { id: 'configuration', path: '/config/templates', icon: FileText, labelZh: '配置管理', labelEn: 'Templates' },
            { id: 'config-backup', path: '/config/backup', icon: Download, labelZh: '备份历史', labelEn: 'Backups' },
            { id: 'config-diff', path: '/config/diff', icon: FileText, labelZh: '差异对比', labelEn: 'Diff' },
            { id: 'config-search', path: '/config/search', icon: Search, labelZh: '配置搜索', labelEn: 'Search' },
            { id: 'config-drift', path: '/config/drift', icon: GitCompareArrows, labelZh: '配置漂移', labelEn: 'Drift' },
            { id: 'compliance', path: null, icon: ShieldCheck, labelZh: '合规检查', labelEn: 'Compliance' },
          ],
        },
      ],
    },
    {
      id: 'capacity',
      labelZh: '分析报表',
      labelEn: 'ANALYTICS',
      items: [
        { id: 'capacity', tabKey: 'capacity', icon: Cpu, labelZh: '容量规划', labelEn: 'Capacity' },
        { id: 'reports', tabKey: 'reports', icon: BarChart3, labelZh: '报表中心', labelEn: 'Reports' },
      ],
    },
  ], [unreadNotificationCount, alertNavTone, metricSlot]);

  /* ── 展开状态映射 ── */
  const groupOpenMap: Record<string, boolean> = {
    'monitoring-group': props.monitoringGroupOpen,
    'alert-group': props.alertGroupOpen,
    'inventory-group': props.inventoryGroupOpen,
    'automation-group': props.automationGroupOpen,
    'config-group': props.configGroupOpen,
  };

  const groupToggleMap: Record<string, () => void> = {
    'monitoring-group': () => {
      const next = !props.monitoringGroupOpen;
      setMonitoringGroupOpen(next);
      if (next && activeTab !== 'monitoring') setActiveTab('monitoring');
    },
    'alert-group': () => {
      const next = !props.alertGroupOpen;
      setAlertGroupOpen(next);
      if (next && !['alerts', 'alert-rules', 'maintenance'].includes(activeTab)) setActiveTab('alerts');
    },
    'inventory-group': () => {
      const next = !props.inventoryGroupOpen;
      setInventoryGroupOpen(next);
      if (next && !(currentPath.startsWith('/inventory') || activeTab === 'ipam')) navTo('/inventory/devices');
    },
    'automation-group': () => {
      const next = !props.automationGroupOpen;
      setAutomationGroupOpen(next);
      if (next && !currentPath.startsWith('/automation')) navTo('/automation/execute');
    },
    'config-group': () => {
      const next = !props.configGroupOpen;
      setConfigGroupOpen(next);
      if (next && !currentPath.startsWith('/config')) navTo('/config/backup');
    },
  };

  /* ── 激活状态判断 ── */
  const isItemActive = useCallback((item: NavItem): boolean => {
    if (item.tabKey && activeTab === item.tabKey) return true;
    if (item.children) {
      return item.children.some((c) => {
        if (c.path) return currentPath === c.path;
        return activeTab === c.id;
      });
    }
    return false;
  }, [activeTab, currentPath]);

  const isChildActive = useCallback((child: NavChild): boolean => {
    if (child.path) return currentPath === child.path;
    return activeTab === child.id;
  }, [activeTab, currentPath]);

  /* ── 子项点击 ── */
  const handleChildClick = useCallback((child: NavChild) => {
    if (child.path) {
      navTo(child.path);
    } else {
      setActiveTab(child.id);
    }
  }, [navTo, setActiveTab]);

  /* ── 一级项点击 ── */
  const handleItemClick = useCallback((item: NavItem) => {
    if (item.children) {
      groupToggleMap[item.id]?.();
    } else if (item.tabKey) {
      setActiveTab(item.tabKey);
    } else if (item.path) {
      navTo(item.path);
    }
  }, [activeTab, currentPath, props.monitoringGroupOpen, props.alertGroupOpen, props.inventoryGroupOpen, props.automationGroupOpen, props.configGroupOpen]);

  /* ── 搜索匹配 ── */
  const flatItems = useMemo(() => {
    const result: { label: string; action: () => void }[] = [];
    for (const section of sections) {
      for (const item of section.items) {
        const lbl = language === 'zh' ? item.labelZh : item.labelEn;
        if (item.children) {
          for (const child of item.children) {
            const childLbl = language === 'zh' ? child.labelZh : child.labelEn;
            result.push({ label: `${lbl} / ${childLbl}`, action: () => handleChildClick(child) });
          }
        } else {
          result.push({ label: lbl, action: () => handleItemClick(item) });
        }
      }
    }
    return result;
  }, [sections, language, handleChildClick, handleItemClick]);

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return flatItems.slice(0, 8);
    const q = searchQuery.toLowerCase();
    return flatItems.filter((i) => i.label.toLowerCase().includes(q)).slice(0, 10);
  }, [flatItems, searchQuery]);

  /* ── section open state mappings ── */
  const sectionOpenMap: Record<string, boolean> = {
    realtime: props.realtimeSectionOpen,
    alerts: props.alertsSectionOpen,
    assets: props.assetsSectionOpen,
    automation: props.automationSectionOpen,
    capacity: props.capacitySectionOpen,
  };

  const sectionToggleMap: Record<string, () => void> = {
    realtime: () => setRealtimeSectionOpen((v) => !v),
    alerts: () => setAlertsSectionOpen((v) => !v),
    assets: () => setAssetsSectionOpen((v) => !v),
    automation: () => setAutomationSectionOpen((v) => !v),
    capacity: () => setCapacitySectionOpen((v) => !v),
  };

  /* ── 底部：管理菜单 ── */
  const managementItems: NavChild[] = useMemo(() => [
    { id: 'history', path: null, icon: History, labelZh: '审计日志', labelEn: 'Audit Logs' },
    { id: 'users', path: null, icon: User, labelZh: '用户管理', labelEn: 'Users' },
  ], []);

  /* ════════════════════════════════════════════════════════════════
     Render
     ════════════════════════════════════════════════════════════════ */

  return (
    <>
      {/* ── 移动端遮罩 ── */}
      {isMobile && !sidebarCollapsed && (
        <div className="fixed inset-0 z-[25] bg-black/60 backdrop-blur-[2px]" onClick={() => setSidebarCollapsed(true)} />
      )}

      {/* ── Cmd+K 搜索面板 ── */}
      {searchOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[16vh]" onClick={() => setSearchOpen(false)}>
          <div
            className="w-[440px] max-w-[90vw] rounded-xl border border-white/[0.08] bg-[#0d1117] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.06]">
              <Search size={15} className="text-[#4a5568] shrink-0" />
              <input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={language === 'zh' ? '搜索功能…' : 'Search...'}
                className="flex-1 bg-transparent text-[13px] text-white placeholder:text-[#4a5568] outline-none"
              />
              <kbd className="px-1.5 py-0.5 text-[10px] text-[#4a5568] border border-white/[0.08] rounded bg-white/[0.03]">ESC</kbd>
            </div>
            <div className="max-h-[320px] overflow-y-auto py-1">
              {searchResults.map((item, i) => (
                <button
                  key={i}
                  onClick={() => { item.action(); setSearchOpen(false); }}
                  className="w-full text-left px-4 py-2 text-[13px] text-[#8b9cb6] hover:bg-white/[0.04] hover:text-white transition-colors"
                >
                  {item.label}
                </button>
              ))}
              {searchResults.length === 0 && (
                <p className="px-4 py-6 text-center text-[12px] text-[#4a5568]">
                  {language === 'zh' ? '无匹配结果' : 'No results'}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── 主体 sidebar ── */}
      <aside
        className={`sidebar-shell relative flex flex-col flex-shrink-0 transition-all duration-200 ease-out border-r border-white/[0.06] ${
          isMobile
            ? `fixed inset-y-0 left-0 z-30 w-[17rem] ${sidebarCollapsed ? '-translate-x-full' : 'translate-x-0'}`
            : `z-20 ${isMini ? 'w-16 min-w-16' : 'w-[15.5rem] min-w-[15.5rem]'}`
        }`}
      >
        {/* ═══ 顶部: Logo ═══ */}
        <div className="relative flex items-center gap-3 px-4 h-14 shrink-0 border-b border-white/[0.06]">
          <div className="w-8 h-8 rounded-lg bg-[#58a6ff]/[0.12] border border-[#58a6ff]/20 flex items-center justify-center">
            <Activity size={16} className="text-[#58a6ff]" />
          </div>
          {!isMini && (
            <div className="sidebar-logo-text min-w-0 flex-1">
              <h1 className="text-[14px] font-semibold text-white tracking-[-0.01em] truncate">{systemInfo?.system_name || 'Nexora'}</h1>
              <p className="text-[10px] text-[#4a5568] tracking-[0.06em] font-medium">
                {language === 'zh' ? '智能网络中枢' : 'SMART NET HUB'}
              </p>
            </div>
          )}
          {!isMini && (
            <button
              onClick={() => setSidebarCollapsed(true)}
              title={language === 'zh' ? '收起' : 'Collapse'}
              className="sidebar-collapse-btn p-1.5 rounded-md text-[#4a5568] hover:text-[#8b9cb6] hover:bg-white/[0.04] transition-colors"
            >
              <ChevronLeft size={16} />
            </button>
          )}
          {isMini && (
            <button
              onClick={() => setSidebarCollapsed(false)}
              title={language === 'zh' ? '展开' : 'Expand'}
              className="absolute right-[-12px] top-1/2 -translate-y-1/2 w-6 h-6 rounded-full border border-white/[0.08] bg-[#0d1117] flex items-center justify-center text-[#4a5568] hover:text-white hover:border-[#58a6ff]/30 transition-all z-10"
            >
              <ChevronRight size={12} />
            </button>
          )}
        </div>

        {/* ═══ 搜索入口 ═══ */}
        {!isMini && (
          <button
            onClick={() => setSearchOpen(true)}
            className="mx-3 mt-3 mb-1 flex items-center gap-2 px-3 py-[6px] rounded-md border border-white/[0.06] bg-white/[0.02] text-[12px] text-[#4a5568] hover:text-[#8b9cb6] hover:bg-white/[0.04] hover:border-white/[0.1] transition-all"
          >
            <Search size={13} />
            <span className="flex-1 text-left truncate">{language === 'zh' ? '搜索…' : 'Search...'}</span>
            <kbd className="px-1 py-px text-[10px] border border-white/[0.08] rounded bg-white/[0.03]">⌘K</kbd>
          </button>
        )}

        {/* ═══ 中部: 主导航（可滚动） ═══ */}
        <nav className="sidebar-nav-scroll flex-1 min-h-0 overflow-y-auto overscroll-contain px-2 py-2 space-y-0.5">

          {/* 收藏 */}
          {!isMini && pinnedPaths.length > 0 && (
            <div className="px-1 mb-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#4a5568] mb-1.5 flex items-center gap-1">
                <Star size={9} className="opacity-70" />
                {language === 'zh' ? '收藏' : 'STARRED'}
              </p>
              <div className="flex flex-wrap gap-1">
                {pinnedPaths.map((path) => (
                  <QuickAccessChip
                    key={path}
                    label={getSidebarRecentLabel(path)}
                    isActive={currentPath === path}
                    isPinned
                    onNavigate={() => navTo(path)}
                    onTogglePin={() => togglePin(path)}
                    language={language}
                  />
                ))}
              </div>
            </div>
          )}

          {/* 最近访问 */}
          {!isMini && recentSidebarItems.length > 0 && (
            <div className="px-1 mb-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#4a5568] mb-1.5">
                {language === 'zh' ? '最近' : 'RECENT'}
              </p>
              <div className="flex flex-wrap gap-1">
                {recentSidebarItems.map((item) => (
                  <QuickAccessChip
                    key={item.path}
                    label={item.label}
                    isActive={currentPath === item.path}
                    isPinned={pinnedPaths.includes(item.path)}
                    onNavigate={() => navTo(item.path)}
                    onTogglePin={() => togglePin(item.path)}
                    language={language}
                  />
                ))}
              </div>
            </div>
          )}

          {/* 导航分区 */}
          {sections.map((section) => {
            const isOpen = sectionOpenMap[section.id] ?? true;
            return (
              <div key={section.id}>
                {isMini ? (
                  <div className="mt-3 mb-1 mx-1 h-px bg-white/[0.06]" />
                ) : (
                  <button
                    onClick={sectionToggleMap[section.id]}
                    className="w-full mt-4 mb-1 px-3 flex items-center gap-1.5 group/sec"
                  >
                    <ChevronRight
                      size={10}
                      className={`text-[#3d4f65] transition-transform duration-150 ${isOpen ? 'rotate-90' : ''}`}
                    />
                    <span className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-[#3d4f65] group-hover/sec:text-[#6b7c93] transition-colors">
                      {language === 'zh' ? section.labelZh : section.labelEn}
                    </span>
                  </button>
                )}

                <div className={!isMini && !isOpen ? 'hidden' : 'space-y-px'}>
                  {section.items.map((item) => {
                    const active = isItemActive(item);
                    if (item.children) {
                      return (
                        <NavGroupItem
                          key={item.id}
                          item={item}
                          isActive={active}
                          isOpen={groupOpenMap[item.id] ?? false}
                          language={language}
                          isMini={isMini}
                          activeTab={activeTab}
                          currentPath={currentPath}
                          onClick={() => handleItemClick(item)}
                          onChildClick={handleChildClick}
                          isChildActive={isChildActive}
                        />
                      );
                    }
                    return (
                      <NavMenuItem
                        key={item.id}
                        item={item}
                        isActive={active}
                        language={language}
                        isMini={isMini}
                        onClick={() => handleItemClick(item)}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        {/* ═══ 底部: 系统管理（固定） ═══ */}
        <div className="shrink-0 border-t border-white/[0.06] px-2 py-2 space-y-px">
          {isMini ? (
            /* mini 模式只显示图标 */
            managementItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                title={language === 'zh' ? item.labelZh : item.labelEn}
                className={`sidebar-nav-item w-full flex items-center justify-center py-[7px] rounded-md transition-colors ${
                  activeTab === item.id
                    ? 'text-white bg-white/[0.07] sidebar-active-indicator'
                    : 'text-[#4a5568] hover:text-[#8b9cb6] hover:bg-white/[0.035]'
                }`}
              >
                <item.icon size={17} strokeWidth={1.8} />
              </button>
            ))
          ) : (
            /* 展开模式 */
            <>
              <button
                onClick={() => {
                  const next = !props.managementGroupOpen;
                  setManagementGroupOpen(next);
                  if (next && !['history', 'users'].includes(activeTab)) setActiveTab('history');
                }}
                className={`sidebar-nav-item group/nav w-full flex items-center gap-2.5 px-3 py-[7px] rounded-md text-[13px] font-medium transition-colors duration-100 ${
                  ['history', 'users'].includes(activeTab)
                    ? 'text-white bg-white/[0.07] sidebar-active-indicator'
                    : 'text-[#8b9cb6] hover:text-[#c8d6e5] hover:bg-white/[0.035]'
                }`}
              >
                <Settings size={17} strokeWidth={1.8} className={`shrink-0 ${['history', 'users'].includes(activeTab) ? 'text-[#58a6ff]' : 'text-[#4a5568]'}`} />
                <span className="sidebar-nav-label flex-1 truncate text-left">{language === 'zh' ? '平台管理' : 'Management'}</span>
                <ChevronRight
                  size={14}
                  className={`sidebar-nav-chevron shrink-0 text-[#4a5568] transition-transform duration-150 ${props.managementGroupOpen ? 'rotate-90' : ''}`}
                />
              </button>
              {props.managementGroupOpen && (
                <div className="space-y-px">
                  {managementItems.map((item) => {
                    const active = activeTab === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => setActiveTab(item.id)}
                        className={`sidebar-sub-item w-full flex items-center gap-2 pl-9 pr-3 py-[5px] text-[12.5px] rounded-md transition-colors duration-100 ${
                          active
                            ? 'text-white bg-white/[0.06] sidebar-active-indicator'
                            : 'text-[#8b9cb6] hover:text-[#c8d6e5] hover:bg-white/[0.03]'
                        }`}
                      >
                        <item.icon size={14} className={active ? 'text-[#58a6ff]' : 'text-[#4a5568]'} />
                        <span className="truncate">{language === 'zh' ? item.labelZh : item.labelEn}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
