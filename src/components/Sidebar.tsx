import React from 'react';
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
  History,
  LayoutDashboard,
  Monitor,
  Network,
  PanelLeftClose,
  Pin,
  Search,
  Server,
  Settings,
  HardDrive,
  ShieldCheck,
  TrendingUp,
  User,
  Wrench,
  X,
  Zap,
  Tags,
  Shield,
  Lock,
} from 'lucide-react';
import type { HostResourceSnapshot } from '../types';
import { useSystem } from '../hooks/useSystem';

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
  removeRecentPath: (path: string) => void;
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

const Sidebar: React.FC<SidebarProps> = ({
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
  realtimeSectionOpen,
  alertsSectionOpen,
  assetsSectionOpen,
  automationSectionOpen,
  capacitySectionOpen,
  managementSectionOpen,
  monitoringGroupOpen,
  alertGroupOpen,
  inventoryGroupOpen,
  automationGroupOpen,
  configGroupOpen,
  managementGroupOpen,
  t,
  getSidebarRecentLabel,
  navTo,
  setActiveTab,
  togglePin,
  removeRecentPath,
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
}) => {
  const { isFeatureEnabled, systemInfo } = useSystem();
  const navLabelClass = isMobile
    ? 'min-w-0 flex-1 text-left whitespace-normal break-words leading-[1.18rem] pr-1 text-[12.25px] font-medium tracking-[0.008em]'
    : 'min-w-0 flex-1 text-left whitespace-normal break-words leading-[1.12rem] pr-1 text-[12px] font-medium tracking-[0.01em]';
  const chipLabelClass = isMobile
    ? 'block max-w-[132px] whitespace-normal break-words leading-4 text-left'
    : 'block truncate max-w-[112px]';
  const subItemLabelClass = isMobile
    ? 'min-w-0 flex-1 text-left text-[12px] whitespace-normal break-words leading-[1.28rem] font-normal text-slate-300/86'
    : 'min-w-0 flex-1 text-left text-[11.5px] whitespace-normal break-words leading-[1.12rem] font-normal text-slate-300/84';
  const navButtonClass = isMobile
    ? 'relative w-full flex items-start gap-2.5 px-4 py-2.75 rounded-xl text-[12.25px] font-medium transition-all border border-transparent'
    : 'relative w-full flex items-start gap-2.5 px-3.5 py-2.5 rounded-xl text-[12px] font-medium transition-all border border-transparent';
  const navButtonGroupClass = isMobile
    ? 'relative w-full flex items-start gap-2.5 px-4 py-2.75 rounded-xl text-[12.25px] font-medium transition-all group border border-transparent'
    : 'relative w-full flex items-start gap-2.5 px-3.5 py-2.5 rounded-xl text-[12px] font-medium transition-all group border border-transparent';
  const subItemButtonClass = isMobile
    ? 'w-full flex items-start gap-2 pl-5 pr-3 py-2 rounded-lg text-[12.5px] transition-all'
    : 'w-full flex items-start gap-2 pl-5 pr-3 py-1.75 rounded-lg text-[11.5px] transition-all';
  const groupChevronWrapClass = isMobile
    ? 'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all duration-200 self-center'
    : 'flex h-6 w-6 shrink-0 items-center justify-center rounded-md border transition-all duration-200';
  const groupChevronIconSize = isMobile ? 12 : 14;
  const plainChevronClass = isMobile ? 'text-white/30 transition-transform duration-200 self-center shrink-0' : 'text-white/30 transition-transform duration-200';
  const metricBadgeClass = isMobile
    ? 'hidden'
    : `shrink-0 whitespace-nowrap rounded-full border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.14em] mr-1 shadow-sm ${hostResourceTone}`;
  const alertBadgeClass = isMobile
    ? `shrink-0 whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[8px] font-bold leading-none ${alertNavTone}`
    : `shrink-0 whitespace-nowrap rounded-full border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.14em] mr-1 shadow-sm ${alertNavTone}`;
  const activePrimaryNavClass = 'border-cyan-400/12 bg-[linear-gradient(90deg,rgba(8,145,178,0.12),rgba(15,23,42,0.93)_18%,rgba(30,41,59,0.86)_100%)] text-white shadow-[inset_2px_0_0_0_rgba(34,211,238,0.78),inset_0_0_0_1px_rgba(56,189,248,0.07),0_8px_18px_rgba(2,8,23,0.14)]';
  const inactivePrimaryNavClass = 'bg-white/[0.016] text-slate-300/92 hover:bg-white/[0.045] hover:text-slate-50 hover:border-white/7';
  const sectionToggleClass = isMobile
    ? 'w-full mt-3 px-3.5 py-2.25 flex items-center gap-2 rounded-xl border border-cyan-300/10 bg-[linear-gradient(90deg,rgba(34,211,238,0.08),rgba(255,255,255,0.028))] text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition-all hover:border-cyan-300/16 hover:bg-[linear-gradient(90deg,rgba(34,211,238,0.1),rgba(255,255,255,0.04))]'
    : 'w-full mt-3 px-3.5 py-2 flex items-center gap-2 rounded-xl border border-cyan-300/10 bg-[linear-gradient(90deg,rgba(34,211,238,0.07),rgba(255,255,255,0.024))] text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition-all hover:border-cyan-300/16 hover:bg-[linear-gradient(90deg,rgba(34,211,238,0.09),rgba(255,255,255,0.036))]';
  const sectionLabelClass = language === 'zh'
    ? 'flex-1 text-[12.5px] font-bold tracking-[0.16em] text-slate-100/92'
    : 'flex-1 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-100/82';
  const sectionMetaLabelClass = language === 'zh'
    ? 'text-[10.5px] font-semibold tracking-[0.06em] text-slate-400/74'
    : 'text-[9.5px] font-semibold uppercase tracking-[0.18em] text-slate-400/68';
  const chipButtonClass = isMobile
    ? 'max-w-full px-2.5 py-1.5 rounded-lg text-[10px] transition-all border pr-5'
    : 'max-w-full px-2.5 py-1.5 rounded-lg text-[10.5px] transition-all border pr-5';
  const mutedChipClass = 'border-white/7 text-white/46 bg-white/[0.028] hover:text-white/72 hover:bg-white/[0.05] hover:border-white/10';
  const activeChipClass = 'border-cyan-400/24 text-cyan-200 bg-cyan-400/[0.09] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]';
  const subNavRailClass = isMobile
    ? 'ml-4 rounded-xl border border-white/4 bg-slate-950/18 pl-2.5 pr-1.5 pt-1.5 pb-1.5 space-y-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.015)]'
    : 'ml-5 rounded-xl border border-white/4 bg-slate-950/18 pl-2.5 pr-1.5 pt-1.5 pb-1.5 space-y-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.015)]';
  const activeSubItemClass = 'bg-white/[0.055] text-sky-50 shadow-[inset_2px_0_0_0_rgba(34,211,238,0.82)]';
  const inactiveSubItemClass = 'text-slate-300/92 hover:bg-white/[0.04] hover:text-slate-100';
  const shelfClass = 'mx-2 rounded-xl border border-white/5 bg-white/[0.022] px-3 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]';
  const sectionDividerClass = 'hidden';
  const shellToneLabel = language === 'zh' ? '智能网络中枢' : 'SMART NET HUB';

  return (
    <>
      {isMobile && !sidebarCollapsed && (
        <div className="fixed inset-0 z-[25] bg-black/50 md:hidden" onClick={() => setSidebarCollapsed(true)} />
      )}

      <aside className={`theme-sidebar relative overflow-hidden flex flex-col flex-shrink-0 shadow-2xl transition-all duration-300 ease-in-out border-r border-white/6 ${
        isMobile
          ? `fixed inset-y-0 left-0 w-[20rem] z-30 ${sidebarCollapsed ? '-translate-x-full' : 'translate-x-0'}`
          : `z-20 ${sidebarCollapsed ? 'w-0 min-w-0 overflow-hidden opacity-0' : 'w-72 min-w-72'}`
      }`}>
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -top-16 left-[-3rem] h-36 w-36 rounded-full bg-cyan-400/8 blur-3xl" />
          <div className="absolute top-56 -right-10 h-28 w-28 rounded-full bg-sky-500/8 blur-3xl" />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.015),rgba(255,255,255,0)_20%,rgba(2,8,23,0.1)_100%)]" />
        </div>

        <div className="relative px-5 pt-5 pb-4 border-b border-white/5 bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.008))] flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl border border-cyan-300/14 bg-[linear-gradient(180deg,rgba(34,211,238,0.14),rgba(14,165,233,0.05))] flex items-center justify-center text-white shadow-[0_8px_18px_rgba(14,165,233,0.12)]">
              <Activity size={18} />
            </div>
            <div className="min-w-0">
              <h1 className="font-semibold text-[1.05rem] tracking-[0.01em] text-white whitespace-nowrap">{systemInfo?.system_name || 'Nexora'}</h1>
              <p className="mt-0.5 text-[9.5px] font-medium tracking-[0.16em] text-cyan-100/48 whitespace-nowrap">{shellToneLabel}</p>
            </div>
          </div>
          <button
            onClick={() => setSidebarCollapsed(true)}
            title={language === 'zh' ? '收起侧栏' : 'Collapse sidebar'}
            className="mt-0.5 p-2 rounded-lg border border-white/5 bg-white/[0.025] text-white/42 hover:text-white hover:bg-white/[0.06] hover:border-white/10 transition-all"
          >
            <PanelLeftClose size={16} />
          </button>
        </div>

        <nav className="sidebar-nav-scroll relative min-h-0 flex flex-col flex-1 px-3 py-4 pr-3 pb-6 space-y-1.5 mt-2 overflow-y-scroll overscroll-contain">
          <div className="pointer-events-none absolute right-1 top-4 bottom-4 w-[3px] rounded-full bg-white/6" />
          {pinnedPaths.length > 0 && (
            <div className={shelfClass}>
              <p className={`${sectionMetaLabelClass} flex items-center gap-1.5`}>
                <Pin size={10} className="opacity-65" />
                {language === 'zh' ? '固定入口' : 'Pinned'}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5 opacity-82">
                {pinnedPaths.map((path) => {
                  const label = getSidebarRecentLabel(path);
                  const active = currentPath === path;
                  return (
                    <div key={path} className="relative group/pin">
                      <button
                        onClick={() => navTo(path)}
                        className={`${chipButtonClass} ${active ? activeChipClass : mutedChipClass}`}
                        title={label}
                      >
                        <span className={chipLabelClass}>{label}</span>
                      </button>
                      <button
                        onClick={(event) => { event.stopPropagation(); togglePin(path); }}
                        title={language === 'zh' ? '取消固定' : 'Unpin'}
                        className="absolute right-0.5 top-1/2 -translate-y-1/2 opacity-0 group-hover/pin:opacity-100 text-white/40 hover:text-white transition-opacity p-0.5 rounded"
                      >
                        <X size={9} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {recentSidebarItems.length > 0 && (
            <div className={shelfClass}>
              <p className={sectionMetaLabelClass}>{language === 'zh' ? '最近访问' : 'Recent'}</p>
              <div className="mt-2 flex flex-wrap gap-1.5 opacity-76">
                {recentSidebarItems.map((item) => {
                  const isPinned = pinnedPaths.includes(item.path);
                  const active = currentPath === item.path;
                  return (
                    <div key={item.path} className="relative group/recent">
                      <button
                        onClick={() => navTo(item.path)}
                        className={`${chipButtonClass} ${active ? activeChipClass : mutedChipClass}`}
                        title={item.label}
                      >
                        <span className={chipLabelClass}>{item.label}</span>
                      </button>
                      <button
                        onClick={(event) => { event.stopPropagation(); removeRecentPath(item.path); }}
                        title={language === 'zh' ? '移除' : 'Remove'}
                        className="absolute -right-1 -top-1 opacity-0 group-hover/recent:opacity-100 transition-opacity p-0.5 rounded-full bg-gray-700/80 hover:bg-red-600/80 text-white/50 hover:text-white"
                      >
                        <X size={10} />
                      </button>
                      <button
                        onClick={(event) => { event.stopPropagation(); togglePin(item.path); }}
                        title={isPinned ? (language === 'zh' ? '取消固定' : 'Unpin') : (language === 'zh' ? '固定' : 'Pin')}
                        className={`absolute right-0.5 top-1/2 -translate-y-1/2 transition-opacity p-0.5 rounded ${isPinned ? 'opacity-70 text-[#00bceb]' : 'opacity-0 group-hover/recent:opacity-100 text-white/40 hover:text-white'}`}
                      >
                        <Pin size={9} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <button
            onClick={() => setRealtimeSectionOpen((value) => !value)}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <ChevronRight size={10} className={`text-white/34 transition-transform duration-150 shrink-0 ${realtimeSectionOpen ? 'rotate-90' : ''}`} />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '实时监控' : 'Real-time'}</p>
          </button>
          <div className={sectionDividerClass} />
          <div className={realtimeSectionOpen ? 'space-y-1' : 'hidden'}>
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`${navButtonClass} ${
                activeTab === 'dashboard'
                  ? activePrimaryNavClass
                  : inactivePrimaryNavClass
              }`}
            >
              <LayoutDashboard size={17} className={`shrink-0 ${activeTab === 'dashboard' ? 'text-[#5fe6ff]' : 'text-white/72'}`} />
              <span className={navLabelClass}>{t('dashboard')}</span>
            </button>

            <div>
              <button
                onClick={() => {
                  const next = !monitoringGroupOpen;
                  setMonitoringGroupOpen(next);
                  if (next && activeTab !== 'monitoring') {
                    setActiveTab('monitoring');
                  }
                }}
                className={`${navButtonGroupClass} ${
                  activeTab === 'monitoring'
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <TrendingUp size={17} className={activeTab === 'monitoring' ? 'text-[#5fe6ff]' : 'text-white/72'} />
                <span className={navLabelClass}>{language === 'zh' ? '监控中心' : 'Monitoring'}</span>
                <span className={metricBadgeClass} title={hostResourceSummary}>
                  {hostResources
                    ? `${formatCompactResourcePercent(hostResources.cpu_percent)}/${formatCompactResourcePercent(hostResources.memory_percent)}`
                    : '--/--'}
                </span>
                <span className={`${groupChevronWrapClass} ${
                  monitoringGroupOpen
                    ? 'border-[#00bceb]/35 bg-[#00bceb]/12 text-[#7ddfff]'
                    : 'border-white/10 bg-white/[0.04] text-white/45 group-hover:border-white/20 group-hover:text-white/70'
                }`}>
                  <ChevronRight size={groupChevronIconSize} className={`transition-transform duration-200 ${monitoringGroupOpen ? 'rotate-90' : ''}`} />
                </span>
              </button>
              <div className={monitoringGroupOpen ? 'mt-1' : 'hidden'}>
                <div className={subNavRailClass}>
                  {([
                    { id: 'monitoring', path: null, icon: Monitor, label: language === 'zh' ? '平台资源' : 'Host Resources' },
                  ] as const).map((item) => {
                    const isActive = item.path ? currentPath === item.path : activeTab === 'monitoring';
                    return (
                      <button
                        key={item.id}
                        onClick={() => item.path ? navTo(item.path) : setActiveTab('monitoring')}
                        className={`${subItemButtonClass} ${
                          isActive
                            ? `${activeSubItemClass} font-semibold`
                            : `${inactiveSubItemClass} font-medium`
                        }`}
                      >
                        {isActive ? <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[#38e8ff] flex-shrink-0" /> : <span className="mt-2 h-1.5 w-1.5 rounded-full bg-white/10 flex-shrink-0" />}
                        <item.icon size={14} className={isActive ? 'text-[#74ecff]' : 'text-white/55'} />
                        <span className={subItemLabelClass}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {[
              { id: 'topology', icon: Globe, label: language === 'zh' ? '网络拓扑' : 'Topology' },
              { id: 'health', icon: Activity, label: language === 'zh' ? '健康检测' : 'Health Detection' },
            ].map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`${navButtonClass} ${
                  activeTab === item.id
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <item.icon size={17} className={`shrink-0 ${activeTab === item.id ? 'text-[#5fe6ff]' : 'text-white/72'}`} />
                <span className={navLabelClass}>{item.label}</span>
              </button>
            ))}
          </div>

          <button
            onClick={() => setAlertsSectionOpen((value) => !value)}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <ChevronRight size={10} className={`text-white/34 transition-transform duration-150 shrink-0 ${alertsSectionOpen ? 'rotate-90' : ''}`} />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '告警处置' : 'Alerts'}</p>
          </button>
          <div className={sectionDividerClass} />
          <div className={alertsSectionOpen ? 'space-y-1' : 'hidden'}>
            <div>
              <button
                onClick={() => {
                  const next = !alertGroupOpen;
                  setAlertGroupOpen(next);
                  if (next && !['alerts', 'alert-rules', 'maintenance'].includes(activeTab)) {
                    setActiveTab('alerts');
                  }
                }}
                className={`${navButtonGroupClass} ${
                  ['alerts', 'alert-rules', 'maintenance'].includes(activeTab)
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <AlertTriangle size={17} className={['alerts', 'alert-rules', 'maintenance'].includes(activeTab) ? 'text-[#5fe6ff]' : 'text-white/72'} />
                <span className={navLabelClass}>{language === 'zh' ? '告警中心' : 'Alert Center'}</span>
                <span className={alertBadgeClass} title={language === 'zh' ? '未读通知' : 'Unread notifications'}>
                  {unreadNotificationCount > 99 ? '99+' : unreadNotificationCount}
                </span>
                <ChevronRight size={groupChevronIconSize} className={`${plainChevronClass} ${alertGroupOpen ? 'rotate-90 text-white/55' : ''}`} />
              </button>
              <div className={alertGroupOpen ? 'mt-1' : 'hidden'}>
                <div className={subNavRailClass}>
                  {([
                    { id: 'alerts', icon: AlertTriangle, label: language === 'zh' ? '告警信息' : 'Alert Desk' },
                    { id: 'alert-rules', icon: Settings, label: language === 'zh' ? '告警规则' : 'Alert Rules' },
                    { id: 'maintenance', icon: Wrench, label: language === 'zh' ? '维护期' : 'Maintenance' },
                  ] as const).map((item) => {
                    const isActive = activeTab === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => setActiveTab(item.id)}
                        className={`${subItemButtonClass} ${
                          isActive
                            ? `${activeSubItemClass} font-semibold`
                            : `${inactiveSubItemClass} font-medium`
                        }`}
                      >
                        {isActive ? <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[#38e8ff] flex-shrink-0" /> : <span className="mt-2 h-1.5 w-1.5 rounded-full bg-white/10 flex-shrink-0" />}
                        <item.icon size={14} className={isActive ? 'text-[#74ecff]' : 'text-white/55'} />
                        <span className={subItemLabelClass}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <button
            onClick={() => setAssetsSectionOpen((value) => !value)}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <ChevronRight size={10} className={`text-white/34 transition-transform duration-150 shrink-0 ${assetsSectionOpen ? 'rotate-90' : ''}`} />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '资产与配置' : 'Assets & Config'}</p>
          </button>
          <div className={sectionDividerClass} />
          <div className={assetsSectionOpen ? 'space-y-1' : 'hidden'}>
            <div>
              <button
                onClick={() => {
                  const next = !inventoryGroupOpen;
                  setInventoryGroupOpen(next);
                  if (next && !(currentPath.startsWith('/inventory') || activeTab === 'ipam' || activeTab === 'assets' || activeTab === 'tags')) navTo('/inventory/devices');
                }}
                className={`${navButtonGroupClass} ${
                  activeTab === 'inventory' || activeTab === 'ipam' || activeTab === 'assets' || activeTab === 'tags'
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <Database size={17} className={activeTab === 'inventory' || activeTab === 'ipam' || activeTab === 'assets' || activeTab === 'tags' ? 'text-[#5fe6ff]' : 'text-white/72'} />
                <span className={navLabelClass}>{t('inventory')}</span>
                <span className={`${groupChevronWrapClass} ${
                  inventoryGroupOpen
                    ? 'border-[#00bceb]/35 bg-[#00bceb]/12 text-[#7ddfff]'
                    : 'border-white/10 bg-white/[0.04] text-white/45 group-hover:border-white/20 group-hover:text-white/70'
                }`}>
                  <ChevronRight size={groupChevronIconSize} className={`transition-transform duration-200 ${inventoryGroupOpen ? 'rotate-90' : ''}`} />
                </span>
              </button>
              <div className={inventoryGroupOpen ? 'mt-1' : 'hidden'}>
                <div className={subNavRailClass}>
                  {([
                    { path: 'inventory/devices', icon: Server, label: t('deviceList') },
                    { path: 'ipam', icon: Network, label: language === 'zh' ? 'IP/VLAN管理' : 'IP/VLAN Mgmt' },
                    isFeatureEnabled('assets') && { path: 'assets', icon: HardDrive, label: language === 'zh' ? '资产管理' : 'Assets' },
                    { path: 'tags', icon: Tags, label: language === 'zh' ? '标签管理' : 'Tags' },
                  ].filter(Boolean) as any[]).map((item) => {
                    const isActive = item.path === 'ipam' ? activeTab === 'ipam' : item.path === 'assets' ? activeTab === 'assets' : item.path === 'tags' ? activeTab === 'tags' : currentPath === `/${item.path}`;
                    return (
                      <button
                        key={item.path}
                        onClick={() => (item.path === 'ipam' || item.path === 'assets' || item.path === 'tags') ? setActiveTab(item.path) : navTo(`/${item.path}`)}
                        className={`${subItemButtonClass} ${
                          isActive
                            ? `${activeSubItemClass} font-semibold`
                            : `${inactiveSubItemClass} font-medium`
                        }`}
                      >
                        {isActive ? <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[#38e8ff] flex-shrink-0" /> : <span className="mt-2 h-1.5 w-1.5 rounded-full bg-white/10 flex-shrink-0" />}
                        <item.icon size={14} className={isActive ? 'text-[#74ecff]' : 'text-white/55'} />
                        <span className={subItemLabelClass}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <button
            onClick={() => setAutomationSectionOpen((value) => !value)}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <ChevronRight size={10} className={`text-white/34 transition-transform duration-150 shrink-0 ${automationSectionOpen ? 'rotate-90' : ''}`} />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '自动化与合规' : 'Automation'}</p>
          </button>
          <div className={sectionDividerClass} />
          <div className={automationSectionOpen ? 'space-y-1' : 'hidden'}>
            <div>
              <button
                onClick={() => {
                  const next = !automationGroupOpen;
                  setAutomationGroupOpen(next);
                  if (next && !currentPath.startsWith('/automation')) navTo('/automation/execute');
                }}
                className={`${navButtonGroupClass} ${
                  activeTab === 'automation'
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <Zap size={17} className={activeTab === 'automation' ? 'text-[#5fe6ff]' : 'text-white/72'} />
                <span className={navLabelClass}>{t('automation')}</span>
                <span className={`${groupChevronWrapClass} ${
                  automationGroupOpen
                    ? 'border-[#00bceb]/35 bg-[#00bceb]/12 text-[#7ddfff]'
                    : 'border-white/10 bg-white/[0.04] text-white/45 group-hover:border-white/20 group-hover:text-white/70'
                }`}>
                  <ChevronRight size={groupChevronIconSize} className={`transition-transform duration-200 ${automationGroupOpen ? 'rotate-90' : ''}`} />
                </span>
              </button>
              <div className={automationGroupOpen ? 'mt-1' : 'hidden'}>
                <div className={subNavRailClass}>
                  {([
                    { path: 'automation/execute', icon: Zap, label: t('directExecution') },
                    { path: 'automation/scenarios', icon: FolderOpen, label: t('scenarioLibrary') },
                    { path: 'automation/queries', icon: History, label: t('executionHistory') },
                  ] as const).map((item) => {
                    const isActive = currentPath === `/${item.path}`;
                    return (
                      <button
                        key={item.path}
                        onClick={() => navTo(`/${item.path}`)}
                        className={`${subItemButtonClass} ${
                          isActive
                            ? `${activeSubItemClass} font-semibold`
                            : `${inactiveSubItemClass} font-medium`
                        }`}
                      >
                        {isActive ? <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[#38e8ff] flex-shrink-0" /> : <span className="mt-2 h-1.5 w-1.5 rounded-full bg-white/10 flex-shrink-0" />}
                        <item.icon size={14} className={isActive ? 'text-[#74ecff]' : 'text-white/55'} />
                        <span className={subItemLabelClass}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            <div>
              <button
                onClick={() => {
                  const next = !configGroupOpen;
                  setConfigGroupOpen(next);
                  if (next && !currentPath.startsWith('/config')) navTo('/config/backup');
                }}
                className={`${navButtonGroupClass} ${
                  activeTab === 'config' || activeTab === 'compliance'
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <FolderOpen size={17} className={activeTab === 'config' || activeTab === 'compliance' ? 'text-[#5fe6ff]' : 'text-white/72'} />
                <span className={navLabelClass}>{language === 'zh' ? '配置与合规' : 'Config & Compliance'}</span>
                <span className={`${groupChevronWrapClass} ${
                  configGroupOpen
                    ? 'border-[#00bceb]/35 bg-[#00bceb]/12 text-[#7ddfff]'
                    : 'border-white/10 bg-white/[0.04] text-white/45 group-hover:border-white/20 group-hover:text-white/70'
                }`}>
                  <ChevronRight size={groupChevronIconSize} className={`transition-transform duration-200 ${configGroupOpen ? 'rotate-90' : ''}`} />
                </span>
              </button>
              <div className={configGroupOpen ? 'mt-1' : 'hidden'}>
                <div className={subNavRailClass}>
                  {([
                    { path: 'config/templates', icon: Settings, label: language === 'zh' ? '配置管理' : 'Config Management' },
                    { path: 'config/backup', icon: Download, label: t('backupHistory') },
                    { path: 'config/diff', icon: FileText, label: t('diffCompare') },
                    { path: 'config/search', icon: Search, label: t('configSearchTab') },
                    { path: 'config/schedule', icon: Clock, label: language === 'zh' ? '备份计划' : 'Backup Schedule' },
                    { path: 'config/drift', icon: GitCompareArrows, label: language === 'zh' ? '配置漂移' : 'Config Drift' },
                    isFeatureEnabled('compliance') && { path: 'compliance', icon: ShieldCheck, label: t('compliance') },
                  ].filter(Boolean) as any[]).map((item) => {
                    const isActive = item.path === 'compliance'
                      ? activeTab === 'compliance'
                      : currentPath === `/${item.path}`;
                    return (
                      <button
                        key={item.path}
                        onClick={() => {
                          if (item.path === 'compliance') setActiveTab('compliance');
                          else navTo(`/${item.path}`);
                        }}
                        className={`${subItemButtonClass} ${
                          isActive
                            ? `${activeSubItemClass} font-semibold`
                            : `${inactiveSubItemClass} font-medium`
                        }`}
                      >
                        {isActive ? <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[#38e8ff] flex-shrink-0" /> : <span className="mt-2 h-1.5 w-1.5 rounded-full bg-white/10 flex-shrink-0" />}
                        <item.icon size={14} className={isActive ? 'text-[#74ecff]' : 'text-white/55'} />
                        <span className={subItemLabelClass}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* ── PAM / Access Control section ── */}
          <button
            onClick={() => setActiveTab('access')}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <Lock size={10} className="text-white/34 shrink-0" />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '特权访问管理' : 'Privileged Access'}</p>
          </button>
          <div className="space-y-1">
            {([
              { id: 'access',    icon: Lock,        label: language === 'zh' ? '操作工作台' : 'Workspace' },
              { id: 'pam-audit', icon: ShieldCheck,  label: language === 'zh' ? '受控审计'   : 'Session Audit' },
            ] as const).map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`${navButtonClass} ${
                  activeTab === item.id
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <item.icon size={17} className={`shrink-0 ${activeTab === item.id ? 'text-[#5fe6ff]' : 'text-white/72'}`} />
                <span className={navLabelClass}>{item.label}</span>
              </button>
            ))}
          </div>

          <button
            onClick={() => setCapacitySectionOpen((value) => !value)}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <ChevronRight size={10} className={`text-white/34 transition-transform duration-150 shrink-0 ${capacitySectionOpen ? 'rotate-90' : ''}`} />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '容量与报表' : 'Capacity & Reports'}</p>
          </button>
          <div className={capacitySectionOpen ? 'space-y-1' : 'hidden'}>
            <button
              onClick={() => setActiveTab('capacity')}
              className={`${navButtonClass} ${
                activeTab === 'capacity'
                  ? activePrimaryNavClass
                  : inactivePrimaryNavClass
              }`}
            >
              <Cpu size={17} className={`shrink-0 ${activeTab === 'capacity' ? 'text-[#5fe6ff]' : 'text-white/72'}`} />
              <span className={navLabelClass}>{language === 'zh' ? '容量规划' : 'Capacity'}</span>
            </button>

            <button
              onClick={() => setActiveTab('reports')}
              className={`${navButtonClass} ${
                activeTab === 'reports'
                  ? activePrimaryNavClass
                  : inactivePrimaryNavClass
              }`}
            >
              <BarChart3 size={17} className={`shrink-0 ${activeTab === 'reports' ? 'text-[#5fe6ff]' : 'text-white/72'}`} />
              <span className={navLabelClass}>{language === 'zh' ? '报表中心' : 'Reports'}</span>
            </button>
          </div>

          <button
            onClick={() => setManagementSectionOpen((value) => !value)}
            className={sectionToggleClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-md border border-cyan-300/12 bg-slate-950/24 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <ChevronRight size={10} className={`text-white/34 transition-transform duration-150 shrink-0 ${managementSectionOpen ? 'rotate-90' : ''}`} />
            </span>
            <p className={sectionLabelClass}>{language === 'zh' ? '平台管理' : 'Management'}</p>
          </button>
          <div className={sectionDividerClass} />
          <div className={managementSectionOpen ? 'space-y-1' : 'hidden'}>
            <div>
              <button
                onClick={() => {
                  const next = !managementGroupOpen;
                  setManagementGroupOpen(next);
                  if (next && !['audit', 'users'].includes(activeTab)) {
                    setActiveTab('audit');
                  }
                }}
                className={`${navButtonGroupClass} ${
                  ['audit', 'users'].includes(activeTab)
                    ? activePrimaryNavClass
                    : inactivePrimaryNavClass
                }`}
              >
                <Settings size={17} className={['audit', 'users'].includes(activeTab) ? 'text-[#5fe6ff]' : 'text-white/72'} />
                <span className={navLabelClass}>{language === 'zh' ? '平台管理' : 'Management'}</span>
                <ChevronRight size={groupChevronIconSize} className={`${plainChevronClass} ${managementGroupOpen ? 'rotate-90 text-white/55' : ''}`} />
              </button>
              <div className={managementGroupOpen ? 'mt-1' : 'hidden'}>
                <div className={subNavRailClass}>
                  {([
                    isFeatureEnabled('audit_logs') && { id: 'audit', icon: History, label: t('auditLogs') },
                    isFeatureEnabled('user_management') && { id: 'users', icon: User, label: t('userManagement') },
                    isFeatureEnabled('password_rotation') && { id: 'credentials', icon: Lock, label: language === 'zh' ? '凭据轮换' : 'Password Rotation' },
                  ].filter(Boolean) as any[]).map((item) => {
                    const isActive = activeTab === item.id || (item.id === 'audit' && activeTab === 'history');
                    return (
                      <button
                        key={item.id}
                        onClick={() => setActiveTab(item.id)}
                        className={`${subItemButtonClass} ${
                          isActive
                            ? `${activeSubItemClass} font-semibold`
                            : `${inactiveSubItemClass} font-medium`
                        }`}
                      >
                        {isActive ? <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[#38e8ff] flex-shrink-0" /> : <span className="mt-2 h-1.5 w-1.5 rounded-full bg-white/10 flex-shrink-0" />}
                        <item.icon size={14} className={isActive ? 'text-[#74ecff]' : 'text-white/55'} />
                        <span className={subItemLabelClass}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </nav>

        {/* Sidebar Footer with Version Information */}
        {!sidebarCollapsed && (
          <div className="px-5 py-4 border-t border-white/5 bg-black/10 flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-slate-500 tracking-wider uppercase">
                {language === 'zh' ? '当前版本' : 'VERSION'}
              </span>
              <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-[10px] font-mono font-bold border border-cyan-500/20 shadow-[0_0_8px_rgba(34,211,238,0.1)]">
                v{systemInfo?.version || '0.1.0'}
              </span>
            </div>
          </div>
        )}
      </aside>
    </>
  );
};

export default Sidebar;
