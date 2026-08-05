import React, { useState, useRef, useEffect, useMemo } from 'react';
import { motion } from 'motion/react';
import {
  Activity,
  BarChart2,
  Bell,
  ChevronDown,
  ClipboardList,
  Clock,
  FileCode2,
  Globe,
  Grid3X3,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  User,
  Zap,
  ArrowLeftRight,
  PlusCircle,
  ChevronLeft as BackIcon,
  Database,
} from 'lucide-react';
import { useSystem } from '../hooks/useSystem';
import type { NotificationItem, SessionUser, ThemeMode } from '../types';

interface TopHeaderProps {
  language: string;
  resolvedTheme: 'light' | 'dark';
  themeMode: ThemeMode;
  sidebarCollapsed: boolean;
  isHomePage?: boolean;
  pageTitle: string;
  currentUser: SessionUser;
  currentAvatar: string;
  currentUserLastLogin: string;
  unreadNotificationCount: number;
  unreadNotifications: NotificationItem[];
  showNotifications: boolean;
  showUserMenu: boolean;
  userMenuRef: React.RefObject<HTMLDivElement | null>;
  renderAvatarContent: (avatarValue: string, fallbackIconSize: number) => React.ReactNode;
  onToggleSidebar: () => void;
  onToggleNotifications: () => void;
  onToggleUserMenu: () => void;
  onOpenProfile: () => void;
  onOpenDashboard: () => void;
  onOpenMonitoring: () => void;
  onOpenHealth: () => void;
  onOpenHistory: () => void;
  onThemeModeChange: (mode: ThemeMode) => void;
  onLanguageChange: (language: 'en' | 'zh') => void;
  onSwitchUser?: (username: string) => void;
  availableUsers?: any[];
  onLogout: () => void;
  onMarkAllNotificationsRead: () => void;
  onMarkNotificationRead: (id: string) => void;
  onNotificationClick: (item: NotificationItem) => void;
  onNavigate?: (path: string) => void;
}

const TopHeader: React.FC<TopHeaderProps> = ({
  language,
  resolvedTheme,
  themeMode,
  sidebarCollapsed,
  isHomePage = false,
  pageTitle,
  currentUser,
  currentAvatar,
  currentUserLastLogin,
  unreadNotificationCount,
  unreadNotifications,
  showNotifications,
  showUserMenu,
  userMenuRef,
  renderAvatarContent,
  onToggleSidebar,
  onToggleNotifications,
  onToggleUserMenu,
  onOpenProfile,
  onOpenDashboard,
  onOpenMonitoring,
  onOpenHealth,
  onOpenHistory,
  onThemeModeChange,
  onLanguageChange,
  onSwitchUser,
  availableUsers,
  onLogout,
  onMarkAllNotificationsRead,
  onMarkNotificationRead,
  onNotificationClick,
  onNavigate,
}) => {
  /* ── App switcher dropdown state ── */
  const [appSwitcherOpen, setAppSwitcherOpen] = useState(false);
  const [menuView, setMenuView] = useState<'main' | 'switch'>('main');
  const [appSearch, setAppSearch] = useState('');
  const appSwitcherRef = useRef<HTMLDivElement>(null);
  const appSearchRef = useRef<HTMLInputElement>(null);
  const { systemInfo } = useSystem();

const ROLE_LEVEL: Record<string, number> = { Administrator: 3, Operator: 2, Viewer: 1 };

  const appEntries = useMemo(() => [
    { id: 'dashboard',  label: '首页',       labelEn: 'Dashboard',    icon: LayoutDashboard, path: '/dashboard',          accent: '#0078d4', minRole: 'Viewer' },
    { id: 'access',     label: '操作工作台', labelEn: 'Operation Workspace', icon: Globe,           path: '/access/workspace',    accent: '#13c2c2', minRole: 'Viewer' },
    { id: 'monitor',    label: '实时监控',   labelEn: 'Monitoring',   icon: Activity,          path: '/monitor/overview',   accent: '#1677ff', minRole: 'Viewer' },
    { id: 'alerts',     label: '告警管理',   labelEn: 'Alerts',       icon: Bell,              path: '/alerts/desk',        accent: '#fa8c16', minRole: 'Viewer' },
    { id: 'assets',     label: '资产与配置', labelEn: 'Assets',       icon: Server,            path: '/assets/dashboard',   accent: '#1677ff', minRole: 'Viewer' },
    { id: 'ipam',       label: 'IPAM地址管理', labelEn: 'IPAM',        icon: Globe,             path: '/ipam/locate',        accent: '#0078d4', minRole: 'Viewer' },
    { id: 'cmdb',       label: 'CMDB基础数据', labelEn: 'CMDB Core',    icon: Database,          path: '/cmdb/credentials',   accent: '#6366f1', minRole: 'Operator' },
    { id: 'config',     label: '配置管理',   labelEn: 'Config',       icon: FileCode2,         path: '/config/backup',      accent: '#722ed1', minRole: 'Viewer' },
    { id: 'automation', label: '自动化',     labelEn: 'Automation',   icon: Zap,               path: '/automation/tasks',   accent: '#0891b2', minRole: 'Viewer' },
    { id: 'tickets',    label: '工单管理',   labelEn: 'Tickets',      icon: ClipboardList,     path: '/change-orders/all',  accent: '#1677ff', minRole: 'Viewer' },
    { id: 'capacity',   label: '容量与报表', labelEn: 'Reports',      icon: BarChart2,         path: '/capacity/analysis',  accent: '#13c2c2', minRole: 'Viewer' },
    { id: 'platform',   label: '平台管理',   labelEn: 'Platform',     icon: SlidersHorizontal, path: '/management/audit',   accent: '#8c8c8c', minRole: 'Administrator' },
  ], []);

  const userRoleLvl = ROLE_LEVEL[currentUser?.role || 'Viewer'] || 1;

  const filteredApps = useMemo(() => {
    const validApps = appEntries.filter(a => userRoleLvl >= (ROLE_LEVEL[a.minRole || 'Viewer'] || 1));
    const q = appSearch.trim().toLowerCase();
    if (!q) return validApps;
    return validApps.filter(a =>
      a.label.toLowerCase().includes(q) ||
      a.labelEn.toLowerCase().includes(q) ||
      a.id.toLowerCase().includes(q)
    );
  }, [appSearch, appEntries, userRoleLvl]);

  // Close app switcher on outside click
  useEffect(() => {
    if (!appSwitcherOpen) return;
    const handler = (e: MouseEvent) => {
      if (appSwitcherRef.current && !appSwitcherRef.current.contains(e.target as Node)) {
        setAppSwitcherOpen(false);
        setAppSearch('');
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [appSwitcherOpen]);

  useEffect(() => {
    if (!showUserMenu) {
      setMenuView('main');
    }
  }, [showUserMenu]);

  // Auto-focus search when opened
  useEffect(() => {
    if (appSwitcherOpen) {
      setTimeout(() => appSearchRef.current?.focus(), 60);
    }
  }, [appSwitcherOpen]);

  return (
    <header className="theme-header h-14 md:h-16 shadow-sm px-3 md:px-8 flex items-center justify-between z-[40]">
      <div className="flex items-center gap-2 md:gap-4 flex-1 min-w-0">
        {isHomePage ? (
          /* Home page: Grid icon + Nexora branding */
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(0,120,212,0.08)' }}
            >
              <Grid3X3 size={19} strokeWidth={1.8} style={{ color: '#0078d4' }} />
            </div>
            <div>
              <h2 style={{ color: 'var(--heading-text)' }} className="text-base md:text-lg font-bold tracking-tight leading-none">
                {systemInfo?.system_name || 'Nexora'}
              </h2>
              <p style={{ color: 'var(--dim-text)' }} className="text-[11px] hidden sm:block mt-0.5 leading-none">
                {language === 'zh' ? '智能网络中枢' : 'Smart Net Hub'}
              </p>
            </div>
          </div>
        ) : (
          /* Normal pages: home grid + sidebar toggle + page title */
          <div className="flex items-center gap-2 md:gap-3">
            <button
              onClick={onOpenDashboard}
              title={language === 'zh' ? '返回功能中心' : 'Back to Home'}
              className={`p-2 rounded-lg transition-all ${resolvedTheme === 'dark' ? 'text-blue-400 hover:bg-white/10' : 'text-blue-600 hover:bg-blue-50/50'}`}
            >
              <Grid3X3 size={18} strokeWidth={1.8} />
            </button>
            <div className={`w-px h-5 ${resolvedTheme === 'dark' ? 'bg-white/10' : 'bg-black/10'}`} />
            <button
              onClick={onToggleSidebar}
              title={language === 'zh' ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar')}
              className={`p-2 rounded-lg transition-all ${resolvedTheme === 'dark' ? 'text-white/55 hover:text-white hover:bg-white/10' : 'text-black/45 hover:text-black hover:bg-black/5'}`}
            >
              <span className="md:hidden"><Menu size={20} /></span>
              <span className="hidden md:inline">{sidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</span>
            </button>
            <div className="relative" ref={appSwitcherRef}>
              <button
                onClick={() => { setAppSwitcherOpen(v => !v); setAppSearch(''); }}
                className={`flex items-center gap-1 rounded-lg px-1.5 py-1 transition-all ${resolvedTheme === 'dark' ? 'hover:bg-white/10' : 'hover:bg-black/[0.04]'}`}
              >
                <div>
                  <h2 className={`text-base md:text-lg font-semibold tracking-tight truncate text-left ${resolvedTheme === 'dark' ? 'text-white/92' : 'text-black/85'}`}>
                    {pageTitle}
                  </h2>
                  <p className={`text-[11px] hidden sm:block text-left ${resolvedTheme === 'dark' ? 'text-white/45' : 'text-black/40'}`}>
                    {new Date().toLocaleDateString()} · {systemInfo?.system_name || 'Nexora'} Control Plane
                  </p>
                </div>
                <ChevronDown size={14} className={`flex-shrink-0 ml-1 transition-transform ${appSwitcherOpen ? 'rotate-180' : ''} ${resolvedTheme === 'dark' ? 'text-white/45' : 'text-black/35'}`} />
              </button>

              {appSwitcherOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ duration: 0.15, ease: 'easeOut' }}
                  className={`absolute top-full left-0 mt-1.5 w-64 rounded-xl shadow-2xl z-50 overflow-hidden ${resolvedTheme === 'dark' ? 'bg-[#121c2d] border border-white/10' : 'bg-white border border-black/10'}`}
                >
                  {/* Search */}
                  <div className={`px-3 py-2.5 border-b ${resolvedTheme === 'dark' ? 'border-white/10' : 'border-black/[0.06]'}`}>
                    <div className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 ${resolvedTheme === 'dark' ? 'bg-white/[0.06]' : 'bg-black/[0.03]'}`}>
                      <Search size={14} className={resolvedTheme === 'dark' ? 'text-white/40' : 'text-black/35'} />
                      <input
                        ref={appSearchRef}
                        value={appSearch}
                        onChange={e => setAppSearch(e.target.value)}
                        placeholder={language === 'zh' ? '搜索应用...' : 'Search apps...'}
                        className={`flex-1 bg-transparent text-[13px] outline-none placeholder:opacity-50 ${resolvedTheme === 'dark' ? 'text-white/90 placeholder:text-white/35' : 'text-black/80 placeholder:text-black/35'}`}
                      />
                    </div>
                  </div>
                  {/* App list */}
                  <div className="max-h-[400px] overflow-auto py-1">
                    {filteredApps.length === 0 ? (
                      <p className={`text-center text-xs py-4 ${resolvedTheme === 'dark' ? 'text-white/40' : 'text-black/40'}`}>
                        {language === 'zh' ? '无匹配结果' : 'No results'}
                      </p>
                    ) : filteredApps.map(app => {
                      const Icon = app.icon;
                      return (
                        <button
                          key={app.id}
                          onClick={() => {
                            setAppSwitcherOpen(false);
                            setAppSearch('');
                            if (onNavigate) onNavigate(app.path);
                          }}
                          className={`w-full flex items-center gap-3 px-3.5 py-2 text-left transition-colors ${resolvedTheme === 'dark' ? 'hover:bg-white/[0.06]' : 'hover:bg-black/[0.03]'}`}
                        >
                          <div
                            className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                            style={{ background: app.accent + '18' }}
                          >
                            <Icon size={15} style={{ color: app.accent }} />
                          </div>
                          <span className={`text-[13px] font-medium truncate ${resolvedTheme === 'dark' ? 'text-white/85' : 'text-black/75'}`}>
                            {language === 'zh' ? app.label : app.labelEn}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </motion.div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="relative flex items-center gap-3" ref={userMenuRef}>
        <div className="relative">
          <button
            onClick={onToggleNotifications}
            className={`p-2 relative rounded-lg transition-colors ${resolvedTheme === 'dark' ? 'text-white/55 hover:text-white hover:bg-white/10' : 'text-black/40 hover:text-black hover:bg-black/5'}`}
            title="Notifications"
          >
            <Bell size={20} />
            {unreadNotificationCount > 0 && (
              <span className={`absolute top-1.5 right-1.5 min-w-2 h-2 px-0.5 bg-red-500 rounded-full border-2 text-[9px] leading-none flex items-center justify-center text-white ${resolvedTheme === 'dark' ? 'border-[#2b2b2b]' : 'border-white'}`} />
            )}
          </button>

          {showNotifications && (
            <motion.div
              initial={{ opacity: 0, y: -6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.16, ease: 'easeOut' }}
              className={`absolute top-12 right-0 w-[calc(100vw-2rem)] sm:w-80 max-w-80 rounded-xl shadow-2xl z-50 overflow-hidden ${resolvedTheme === 'dark' ? 'bg-[#2d2d2d] border border-white/10' : 'bg-white border border-black/10'}`}
            >
              <div className={`px-4 py-3 border-b flex items-center justify-between ${resolvedTheme === 'dark' ? 'border-white/10 bg-white/5' : 'border-black/5 bg-black/[0.02]'}`}>
                <p className={`text-sm font-semibold ${resolvedTheme === 'dark' ? 'text-white/90' : 'text-black/80'}`}>Notifications</p>
                <button
                  onClick={onMarkAllNotificationsRead}
                  className={`text-[11px] font-semibold ${resolvedTheme === 'dark' ? 'text-[#0078d4] hover:text-[#106ebe]' : 'text-[#008bb0] hover:text-[#006c8a]'}`}
                >
                  Mark all read
                </button>
              </div>
              <div className="max-h-80 overflow-auto">
                {unreadNotifications.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => {
                      onMarkNotificationRead(item.id);
                      onNotificationClick(item);
                    }}
                    className={`w-full text-left px-4 py-3 border-b transition-all ${resolvedTheme === 'dark' ? 'border-white/5 hover:bg-white/5' : 'border-black/5 hover:bg-black/[0.02]'}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${item.read ? 'bg-transparent border border-transparent' : 'bg-[#0078d4]'}`} />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.14em] ${
                            item.source === 'system_resource'
                              ? 'bg-red-100 text-red-700'
                              : item.source === 'network_monitor'
                                ? 'bg-cyan-100 text-cyan-700'
                                : 'bg-black/5 text-black/45'
                          }`}>
                            {item.source === 'system_resource'
                              ? (language === 'zh' ? '平台资源' : 'Platform')
                              : item.source === 'network_monitor'
                                ? (language === 'zh' ? '网络监控' : 'Network')
                                : (item.source || (language === 'zh' ? '通知' : 'Notice'))}
                          </span>
                          {item.severity && <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.14em] ${
                            item.severity === 'critical' || item.severity === 'high'
                              ? 'bg-red-100 text-red-700'
                              : item.severity === 'major' || item.severity === 'medium'
                                ? 'bg-amber-100 text-amber-700'
                                : 'bg-emerald-100 text-emerald-700'
                          }`}>
                            {item.severity === 'critical'
                              ? (language === 'zh' ? '严重' : 'Critical')
                              : item.severity === 'major'
                                ? (language === 'zh' ? '主要' : 'Major')
                                : item.severity === 'warning'
                                  ? (language === 'zh' ? '次要' : 'Minor')
                                  : item.severity === 'high'
                                    ? (language === 'zh' ? '高' : 'High')
                                    : item.severity === 'medium'
                                      ? (language === 'zh' ? '中' : 'Medium')
                                      : (language === 'zh' ? '低' : 'Low')}
                          </span>}
                        </div>
                        <p className={`text-sm font-semibold truncate ${resolvedTheme === 'dark' ? 'text-white/90' : 'text-black/80'}`}>{item.title}</p>
                        <p className={`text-xs mt-0.5 ${resolvedTheme === 'dark' ? 'text-white/55' : 'text-black/50'}`}>{item.message}</p>
                        <p className={`text-[10px] mt-1 ${resolvedTheme === 'dark' ? 'text-white/40' : 'text-black/40'}`}>{item.time ? new Date(item.time).toLocaleString() : ''}</p>
                      </div>
                    </div>
                  </button>
                ))}
                {unreadNotifications.length === 0 && (
                  <p className={`px-4 py-6 text-center text-xs ${resolvedTheme === 'dark' ? 'text-white/50' : 'text-black/45'}`}>
                    {language === 'zh' ? '暂无通知' : 'No notifications.'}
                  </p>
                )}
              </div>
            </motion.div>
          )}
        </div>

        <button
          onClick={onToggleUserMenu}
          className={`flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all ${resolvedTheme === 'dark' ? 'hover:bg-white/10' : 'hover:bg-black/[0.04]'}`}
        >
          <div className={`w-7 h-7 rounded-full border overflow-hidden flex items-center justify-center ${resolvedTheme === 'dark' ? 'bg-white/10 border-white/10 text-white/70' : 'bg-black/10 border-black/5 text-black/60'}`}>
            {renderAvatarContent(currentAvatar, 15)}
          </div>
          <span className={`text-xs font-semibold max-w-24 truncate ${resolvedTheme === 'dark' ? 'text-white/85' : 'text-black/70'}`}>{currentUser.username}</span>
          <ChevronDown size={14} className={resolvedTheme === 'dark' ? 'text-white/45' : 'text-black/35'} />
        </button>

        {showUserMenu && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.16, ease: 'easeOut' }}
            className={`absolute top-14 right-0 w-[calc(100vw-2rem)] sm:w-[300px] max-w-[300px] rounded-xl shadow-2xl z-50 overflow-hidden ${resolvedTheme === 'dark' ? 'bg-[#2d2d2d] border border-white/[0.12]' : 'bg-white border border-black/[0.12] shadow-lg'}`}
          >
            {menuView === 'main' ? (
              <>
                <div className={`flex items-center justify-between px-4 py-3 border-b ${resolvedTheme === 'dark' ? 'border-white/[0.08]' : 'border-black/[0.06]'}`}>
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-9 h-9 rounded-full border overflow-hidden flex-shrink-0 flex items-center justify-center ${resolvedTheme === 'dark' ? 'bg-white/10 border-white/10 text-white/70' : 'bg-black/10 border-black/5 text-black/60'}`}>
                      {renderAvatarContent(currentAvatar, 18)}
                    </div>
                    <div className="min-w-0">
                      <p className={`text-[13px] font-semibold truncate leading-tight ${resolvedTheme === 'dark' ? 'text-white/90' : 'text-black/85'}`}>{currentUser.username}</p>
                      <p className={`text-[11px] truncate ${resolvedTheme === 'dark' ? 'text-white/45' : 'text-black/45'}`}>{language === 'zh' ? (currentUser.role === 'Administrator' ? '管理员' : currentUser.role === 'Operator' ? '操作员' : currentUser.role === 'Viewer' ? '只读用户' : (currentUser.role || '管理员')) : (currentUser.role || 'Administrator')}</p>
                    </div>
                  </div>
                  {currentUser?.role === 'Administrator' && (
                    <button 
                      onClick={() => setMenuView('switch')}
                      title={language === 'zh' ? '切换账户' : 'Switch account'}
                      className={`p-1.5 rounded-lg transition-colors ${resolvedTheme === 'dark' ? 'bg-white/5 hover:bg-white/10 text-white/60' : 'bg-black/[0.04] hover:bg-black/[0.08] text-black/50'}`}
                    >
                      <ArrowLeftRight size={14} />
                    </button>
                  )}
                </div>

                <div className={`py-1 border-b ${resolvedTheme === 'dark' ? 'border-white/[0.08]' : 'border-black/[0.06]'}`}>
                  <button onClick={onOpenProfile} className={`w-full flex items-center gap-3 px-4 py-[7px] text-[13px] transition-colors ${resolvedTheme === 'dark' ? 'text-white/80 hover:bg-white/[0.06]' : 'text-black/70 hover:bg-black/[0.03]'}`}>
                    <User size={16} className="flex-shrink-0 opacity-70 text-blue-500" />
                    {language === 'zh' ? '个人设置' : 'Account Settings'}
                  </button>
                  
                  {currentUser.role === 'Administrator' && (
                    <>
                      <button onClick={() => onNavigate && onNavigate('/users')} className={`w-full flex items-center gap-3 px-4 py-[7px] text-[13px] transition-colors ${resolvedTheme === 'dark' ? 'text-white/80 hover:bg-white/[0.06]' : 'text-black/70 hover:bg-black/[0.03]'}`}>
                        <SlidersHorizontal size={16} className="flex-shrink-0 opacity-70 text-indigo-500" />
                        {language === 'zh' ? '用户管理' : 'User Management'}
                      </button>
                    </>
                  )}
                </div>
              </>
            ) : (
              /* GitHub-style Switch Account View */
              <div className="flex flex-col max-h-[480px]">
                <div className={`flex items-center gap-2 px-3 py-3 border-b ${resolvedTheme === 'dark' ? 'border-white/[0.08]' : 'border-black/[0.06]'}`}>
                  <button 
                    onClick={() => setMenuView('main')}
                    className={`p-1 rounded-md transition-colors ${resolvedTheme === 'dark' ? 'hover:bg-white/10 text-white/60' : 'hover:bg-black/5 text-black/50'}`}
                  >
                    <BackIcon size={16} />
                  </button>
                  <span className={`text-[13px] font-bold ${resolvedTheme === 'dark' ? 'text-white/90' : 'text-black/80'}`}>
                    {language === 'zh' ? '切换账户' : 'Switch account'}
                  </span>
                </div>
                
                <div className="overflow-y-auto py-1 flex-1">
                  {(availableUsers || [])
                    .filter(u => u.username !== currentUser.username)
                    .map((acc, idx) => {
                      const colors = ['bg-rose-500', 'bg-purple-500', 'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-indigo-500', 'bg-cyan-500', 'bg-slate-500'];
                      const colorClass = colors[idx % colors.length];
                      return (
                        <button 
                          key={acc.id || acc.username}
                          onClick={() => onSwitchUser?.(acc.username)}
                          className={`w-full flex items-center gap-3 px-4 py-2 text-[13px] transition-colors ${resolvedTheme === 'dark' ? 'text-white/80 hover:bg-white/[0.06]' : 'text-black/70 hover:bg-black/[0.03]'}`}
                        >
                          <div className={`w-6 h-6 rounded-md ${colorClass} flex items-center justify-center text-[10px] font-bold text-white uppercase`}>
                            {acc.username.substring(0, 2)}
                          </div>
                          <span className="truncate flex-1 text-left">{acc.username}</span>
                        </button>
                      );
                    })}
                </div>

                <div className={`py-1 border-t ${resolvedTheme === 'dark' ? 'border-white/[0.08]' : 'border-black/[0.06]'}`}>
                  <button className={`w-full flex items-center gap-3 px-4 py-2 text-[13px] transition-colors ${resolvedTheme === 'dark' ? 'text-white/80 hover:bg-white/[0.06]' : 'text-black/70 hover:bg-black/[0.03]'}`}>
                    <PlusCircle size={15} className="text-slate-400" />
                    {language === 'zh' ? '添加账户' : 'Add account'}
                  </button>
                  <button 
                    onClick={onLogout}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-[13px] transition-colors ${resolvedTheme === 'dark' ? 'text-white/80 hover:bg-white/[0.06]' : 'text-black/70 hover:bg-black/[0.03]'}`}
                  >
                    <LogOut size={15} className="text-slate-400" />
                    {language === 'zh' ? '退出登录' : 'Sign out'}
                  </button>
                </div>
              </div>
            )}

            <div className={`py-1 border-b ${resolvedTheme === 'dark' ? 'border-white/[0.08]' : 'border-black/[0.06]'}`}>
              <div className={`w-full flex items-center justify-between px-4 py-[7px] text-[13px] ${resolvedTheme === 'dark' ? 'text-white/80' : 'text-black/70'}`}>
                <div className="flex items-center gap-3">
                  {resolvedTheme === 'dark' ? <Moon size={16} className="flex-shrink-0 opacity-70" /> : <Sun size={16} className="flex-shrink-0 opacity-70" />}
                  <span>{language === 'zh' ? '外观' : 'Appearance'}</span>
                </div>
                <div className={`flex items-center rounded-md border p-0.5 ${resolvedTheme === 'dark' ? 'border-white/10 bg-white/5' : 'border-black/10 bg-black/[0.03]'}`}>
                  <button onClick={() => onThemeModeChange('light')} title="Light" className={`p-1 rounded transition-all ${themeMode === 'light' ? 'bg-[#0078d4]/15 text-[#0078d4]' : (resolvedTheme === 'dark' ? 'text-white/45 hover:text-white' : 'text-black/40 hover:text-black')}`}>
                    <Sun size={13} />
                  </button>
                  <button onClick={() => onThemeModeChange('dark')} title="Dark" className={`p-1 rounded transition-all ${themeMode === 'dark' ? 'bg-[#0078d4]/15 text-[#0078d4]' : (resolvedTheme === 'dark' ? 'text-white/45 hover:text-white' : 'text-black/40 hover:text-black')}`}>
                    <Moon size={13} />
                  </button>
                </div>
              </div>
              <div className={`w-full flex items-center justify-between px-4 py-[7px] text-[13px] ${resolvedTheme === 'dark' ? 'text-white/80' : 'text-black/70'}`}>
                <div className="flex items-center gap-3">
                  <Globe size={16} className="flex-shrink-0 opacity-70" />
                  <span>{language === 'zh' ? '语言' : 'Language'}</span>
                </div>
                <div className={`flex items-center rounded-md border p-0.5 ${resolvedTheme === 'dark' ? 'border-white/10 bg-white/5' : 'border-black/10 bg-black/[0.03]'}`}>
                  <button onClick={() => onLanguageChange('en')} className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-all ${language === 'en' ? 'bg-[#0078d4]/15 text-[#0078d4]' : (resolvedTheme === 'dark' ? 'text-white/45 hover:text-white' : 'text-black/40 hover:text-black')}`}>
                    EN
                  </button>
                  <button onClick={() => onLanguageChange('zh')} className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-all ${language === 'zh' ? 'bg-[#0078d4]/15 text-[#0078d4]' : (resolvedTheme === 'dark' ? 'text-white/45 hover:text-white' : 'text-black/40 hover:text-black')}`}>
                    中文
                  </button>
                </div>
              </div>
            </div>

            <div className={`px-4 py-2 border-b ${resolvedTheme === 'dark' ? 'border-white/[0.08]' : 'border-black/[0.06]'}`}>
              <p className={`text-[11px] flex items-center gap-2 ${resolvedTheme === 'dark' ? 'text-white/35' : 'text-black/35'}`}>
                <Clock size={12} className="flex-shrink-0" />
                {language === 'zh' ? '上次登录' : 'Last login'}: {currentUserLastLogin}
              </p>
            </div>

            <div className="py-1">
              <button onClick={onLogout} className={`w-full flex items-center gap-3 px-4 py-[7px] text-[13px] transition-colors ${resolvedTheme === 'dark' ? 'text-white/80 hover:bg-white/[0.06]' : 'text-black/70 hover:bg-black/[0.03]'}`}>
                <LogOut size={16} className="flex-shrink-0 opacity-70" />
                {language === 'zh' ? '退出登录' : 'Logout'}
              </button>
            </div>
          </motion.div>
        )}
      </div>
    </header>
  );
};

export default TopHeader;
