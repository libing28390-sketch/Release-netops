import React, { Suspense, lazy, useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'motion/react';
import { Routes, Route, useLocation, useNavigate, Navigate } from 'react-router-dom';
import * as htmlToImage from 'html-to-image';
import { Plus, Server, CheckCircle, CheckCircle2, XCircle, RotateCcw, Play, Activity, LayoutDashboard, Database, Zap, ShieldCheck, History, LogOut, Search, Bell, Settings, Download, Upload, FileText, ChevronLeft, ChevronRight, Filter, Globe, TrendingUp, PieChart as PieChartIcon, Clock, Edit2, AlertCircle, FolderOpen, Eye, EyeOff, Sun, Moon, User, ChevronDown, Copy, Menu, PanelLeftClose, Monitor, ExternalLink, Trash2, Wrench, Maximize2, Minimize2, BarChart3, GitCompareArrows, Cpu, Network, Pin, AlertTriangle, X } from 'lucide-react';
import { useI18n } from './i18n.tsx';
import * as XLSX from 'xlsx';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell } from 'recharts';
import type { ConfigVersion, Device, Job, AuditEvent, ComplianceFinding, ComplianceRunPoint, ComplianceOverview, ScheduledTask, Script, ConfigTemplate, ConfigSnapshot, DiffLine, User as UserType, ThemeMode, SessionUser, NotificationItem, HostResourceSnapshot, DeviceHealthAlertItem, DeviceHealthDetailResponse, DeviceHealthTrendResponse, DeviceConnectionCheckSummary } from './types';
import { PLATFORM_LABELS, getPlatformLabel, getVendorFromPlatform } from './types';
import { sectionHeaderRowClass, sectionToolbarClass, primaryActionBtnClass, secondaryActionBtnClass, darkActionBtnClass, severityBadgeClass, complianceStatusBadgeClass, auditStatusBadgeClass, parseJsonObject } from './components/shared';
import Pagination from './components/Pagination';
import DeviceFormModal from './components/DeviceFormModal';
import DeviceDetailModal from './components/DeviceDetailModal';
import CustomCommandModal from './components/CustomCommandModal';
import AddScenarioModal from './components/AddScenarioModal';
import CommandPalette from './components/CommandPalette';
import AppSidebar from './components/AppSidebar';
import TopHeader from './components/TopHeader';
import ProfileModal from './components/ProfileModal';
import CommandPreviewModal from './components/CommandPreviewModal';
import ImportInventoryModal from './components/ImportInventoryModal';
import HistoricalConfigModal from './components/HistoricalConfigModal';
import ScheduleTaskModal from './components/ScheduleTaskModal';
import RemediationModal from './components/RemediationModal';
import DeleteConfirmModal from './components/DeleteConfirmModal';
import AuditEventDetailModal from './components/AuditEventDetailModal';
import ComplianceFindingDetailModal from './components/ComplianceFindingDetailModal';
import JobOutputModal from './components/JobOutputModal';
import ConfigDiffModal from './components/ConfigDiffModal';
import ToastNotification, { type ToastState } from './components/ToastNotification';
import LoginScreen from './components/LoginScreen';
import TestConnectionResultModal from './components/TestConnectionResultModal';
import SnmpTestResultModal from './components/SnmpTestResultModal';
import { buildConnectionTestMessage, buildConnectionTestHint, buildConnectionCheckStatus, connectionCheckBadgeMeta, formatConnectionCheckTime } from './utils/connectionHelpers';

const MonitoringCenter = lazy(() => import('./components/MonitoringCenter.tsx'));
const DeviceHealthTab = lazy(() => import('./pages/DeviceHealthTab'));
const DashboardTab = lazy(() => import('./pages/DashboardTab'));
const ComplianceTab = lazy(() => import('./pages/ComplianceTab'));
const HistoryTab = lazy(() => import('./pages/HistoryTab'));
const UsersTab = lazy(() => import('./pages/UsersTab'));
const TopologyPage = lazy(() => import('./pages/TopologyPage'));
const InventoryDevicesTab = lazy(() => import('./pages/InventoryDevicesTab'));
const AlertDeskTab = lazy(() => import('./pages/AlertDeskTab'));
const AlertRulesTab = lazy(() => import('./pages/AlertRulesTab'));
const AlertMaintenanceTab = lazy(() => import('./pages/AlertMaintenanceTab'));
const ReportsTab = lazy(() => import('./pages/ReportsTab'));
const ConfigDriftTab = lazy(() => import('./pages/ConfigDriftTab'));
const ConfigBackupTab = lazy(() => import('./pages/ConfigBackupTab'));
const ConfigDiffViewTab = lazy(() => import('./pages/ConfigDiffViewTab'));
const ConfigScheduleTab = lazy(() => import('./pages/ConfigScheduleTab'));
const ConfigSearchTab = lazy(() => import('./pages/ConfigSearchTab'));
const CapacityPlanningTab = lazy(() => import('./pages/CapacityPlanningTab'));
const IPVlanTab = lazy(() => import('./pages/IPVlanTab'));
const AssetManagementTab = lazy(() => import('./pages/AssetManagementTab'));
const InterfaceMonitoringTab = lazy(() => import('./pages/InterfaceMonitoringTab'));
const AutomationExecuteTab = lazy(() => import('./pages/AutomationExecuteTab'));
const AutomationPlaybooksTab = lazy(() => import('./pages/AutomationPlaybooksTab'));
const AutomationScenariosTab = lazy(() => import('./pages/AutomationScenariosTab'));
const AutomationHistoryTab = lazy(() => import('./pages/AutomationHistoryTab'));
const PlatformSettingsTab = lazy(() => import('./pages/PlatformSettingsTab'));

// Types imported from ./types — re-export User as UserType to avoid clash with lucide-react User icon

interface AppRuntimeBoundaryProps {
  children: React.ReactNode;
  language: string;
}

interface AppRuntimeBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

class AppRuntimeBoundary extends React.Component<AppRuntimeBoundaryProps, AppRuntimeBoundaryState> {
  declare props: Readonly<AppRuntimeBoundaryProps>;
  state: AppRuntimeBoundaryState = { hasError: false, errorMessage: '' };

  static getDerivedStateFromError(error: Error): AppRuntimeBoundaryState {
    return { hasError: true, errorMessage: error?.message || 'Unknown runtime error' };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    // Keep details in console for fast diagnosis while avoiding a blank screen for users.
    console.error('Runtime error in authenticated app shell:', error, errorInfo);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const isZh = this.props.language === 'zh';
    return (
      <div className="min-h-screen bg-[#061324] text-white flex items-center justify-center p-6">
        <div className="max-w-xl w-full rounded-2xl border border-white/15 bg-white/5 backdrop-blur-sm p-6">
          <h2 className="text-xl font-bold">
            {isZh ? '页面运行异常，已阻止白屏' : 'Runtime issue detected, white screen prevented'}
          </h2>
          <p className="mt-3 text-sm text-white/75">
            {isZh
              ? '应用捕获到前端运行时错误。请点击“重新加载”恢复；若仍复现，请把此错误信息发给我继续定位。'
              : 'The app caught a frontend runtime error. Click Reload to recover. If it happens again, share this message for quick diagnosis.'}
          </p>
          <pre className="mt-4 rounded-xl bg-black/35 border border-white/10 p-3 text-xs text-red-200 whitespace-pre-wrap break-all">
            {this.state.errorMessage}
          </pre>
          <div className="mt-5 flex items-center gap-2">
            <button
              onClick={this.handleReload}
              className="px-4 py-2 rounded-lg bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#0096bd] transition-colors"
            >
              {isZh ? '重新加载' : 'Reload'}
            </button>
          </div>
        </div>
      </div>
    );
  }
}

// Sparkline imported from ./components/Sparkline

const App: React.FC = () => {
  const { t, language, setLanguage } = useI18n();
  const avatarPresets = [
    { id: 'preset:fox', emoji: '🦊', label: 'Fox', bgClass: 'bg-gradient-to-br from-orange-400 to-amber-600' },
    { id: 'preset:panda', emoji: '🐼', label: 'Panda', bgClass: 'bg-gradient-to-br from-slate-500 to-slate-700' },
    { id: 'preset:tiger', emoji: '🐯', label: 'Tiger', bgClass: 'bg-gradient-to-br from-amber-500 to-orange-600' },
    { id: 'preset:wolf', emoji: '🐺', label: 'Wolf', bgClass: 'bg-gradient-to-br from-zinc-500 to-zinc-700' },
    { id: 'preset:lion', emoji: '🦁', label: 'Lion', bgClass: 'bg-gradient-to-br from-yellow-500 to-amber-700' },
    { id: 'preset:koala', emoji: '🐨', label: 'Koala', bgClass: 'bg-gradient-to-br from-sky-400 to-blue-600' },
    { id: 'preset:owl', emoji: '🦉', label: 'Owl', bgClass: 'bg-gradient-to-br from-violet-500 to-indigo-700' },
    { id: 'preset:penguin', emoji: '🐧', label: 'Penguin', bgClass: 'bg-gradient-to-br from-cyan-500 to-blue-700' },
    { id: 'preset:rabbit', emoji: '🐰', label: 'Rabbit', bgClass: 'bg-gradient-to-br from-pink-400 to-fuchsia-600' },
    { id: 'preset:cat', emoji: '🐱', label: 'Cat', bgClass: 'bg-gradient-to-br from-rose-400 to-red-600' },
    { id: 'preset:dog', emoji: '🐶', label: 'Dog', bgClass: 'bg-gradient-to-br from-emerald-500 to-teal-700' },
    { id: 'preset:whale', emoji: '🐳', label: 'Whale', bgClass: 'bg-gradient-to-br from-cyan-400 to-indigo-600' },
  ] as const;
  const resolvePreset = (avatarValue?: string) => avatarPresets.find(p => p.id === avatarValue);
  const renderAvatarContent = (avatarValue: string, fallbackIconSize: number) => {
    const preset = resolvePreset(avatarValue);
    if (preset) {
      const emojiSizeClass = fallbackIconSize <= 15 ? 'text-sm' : fallbackIconSize <= 18 ? 'text-base' : 'text-xl';
      return (
        <div className={`w-full h-full ${preset.bgClass} flex items-center justify-center`}>
          <span className={`${emojiSizeClass} leading-none`}>{preset.emoji}</span>
        </div>
      );
    }
    if (avatarValue?.startsWith('preset:')) {
      return <User size={fallbackIconSize} />;
    }
    if (avatarValue) {
      return <img src={avatarValue} alt="avatar" className="w-full h-full object-cover" />;
    }
    return <User size={fallbackIconSize} />;
  };
  const getResolvedTheme = (mode: ThemeMode): 'light' | 'dark' => {
    return mode;
  };
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem('netops_theme_mode') as ThemeMode | null;
    if (!saved || (saved !== 'light' && saved !== 'dark')) {
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return saved;
  });
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() => getResolvedTheme(((localStorage.getItem('netops_theme_mode') as ThemeMode | null) || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) as ThemeMode));
  const [currentUser, setCurrentUser] = useState<SessionUser>({ username: 'admin' });
  const [showUserMenu, setShowUserMenu] = useState(false);
  const userMenuRef = React.useRef<HTMLDivElement | null>(null);
  const [showNotifications, setShowNotifications] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationReadMap, setNotificationReadMap] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem('netops_notification_reads');
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });
  const [profileAvatarPreview, setProfileAvatarPreview] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [loginForm, setLoginForm] = useState(() => {
    const saved = localStorage.getItem('netops_user');
    return { username: saved || '', password: '' };
  });
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [globalVars, setGlobalVars] = useState<{id?: string, key: string, value: string}[]>([]);
  const [configTemplates, setConfigTemplates] = useState<ConfigTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [editorContent, setEditorContent] = useState<string>('');

  // Check session token on mount
  useEffect(() => {
    const token = localStorage.getItem('netops_token');
    if (!token) { setAuthChecking(false); return; }
    fetch('/api/session', { headers: { 'Authorization': `Bearer ${token}` } })
      .then(async r => {
        if (r.ok) {
          const data = await r.json();
          setIsAuthenticated(true);
          if (data?.user?.username) {
            setCurrentUser(data.user);
            if (data.user.preferred_language === 'en' || data.user.preferred_language === 'zh') {
              setLanguage(data.user.preferred_language);
            }
          }
        } else {
          localStorage.removeItem('netops_token');
        }
      })
      .catch(() => { localStorage.removeItem('netops_token'); })
      .finally(() => setAuthChecking(false));
  }, []);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
        setShowNotifications(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  useEffect(() => {
    localStorage.setItem('netops_notification_reads', JSON.stringify(notificationReadMap));
  }, [notificationReadMap]);

  useEffect(() => {
    const tpl = configTemplates.find(t => t.id === selectedTemplateId);
    if (tpl) {
      setEditorContent(tpl.content);
    }
  }, [selectedTemplateId, configTemplates]);
  // getVendorFromPlatform, PLATFORM_LABELS, getPlatformLabel imported from ./types

  const [scripts, setScripts] = useState<Script[]>([]);
  const [selectedScript, setSelectedScript] = useState<Script | null>(null);
  const [selectedAutomationTemplate, setSelectedAutomationTemplate] = useState<ConfigTemplate | null>(null);
  const [editedScriptContent, setEditedScriptContent] = useState<string>('');
  const [customCommand, setCustomCommand] = useState('');
  const [customCommandMode, setCustomCommandMode] = useState<'query' | 'config'>('query');
  const [scriptParams, setScriptParams] = useState<Record<string, string>>({});
  // Batch execution
  const [batchMode, setBatchMode] = useState(false);
  const [batchDeviceIds, setBatchDeviceIds] = useState<string[]>([]);
  const [batchResults, setBatchResults] = useState<{deviceId: string; hostname: string; status: 'pending'|'running'|'success'|'failed'; output?: string}[]>([]);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  // Dry-run mode
  const [dryRun, setDryRun] = useState(false);
  // Command favorites
  const [commandFavorites, setCommandFavorites] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('cmdFavorites') || '[]'); } catch { return []; }
  });
  const [showFavorites, setShowFavorites] = useState(false);
  // Script variable substitution 閳?parsed from {{VAR}} in script content
  const [scriptVars, setScriptVars] = useState<Record<string, string>>({});

  // Quick Query (read-only commands, no history saved)
  const [quickQueryOutput, setQuickQueryOutput] = useState<string>('');
  const [quickQueryRunning, setQuickQueryRunning] = useState(false);
  const [quickQueryLabel, setQuickQueryLabel] = useState('');
  const [quickQueryStructured, setQuickQueryStructured] = useState<any | null>(null);
  const [quickQueryView, setQuickQueryView] = useState<'terminal' | 'table'>('terminal');
  const [quickQueryMaximized, setQuickQueryMaximized] = useState(false);
  const [quickQueryCommands, setQuickQueryCommands] = useState<string[]>([]);

  // ---------- Config Center ----------
  const [retentionDays, setRetentionDays] = useState<number>(365);
  const [configSnapshots, setConfigSnapshots] = useState<ConfigSnapshot[]>([]);
  const [configSnapshotsLoading, setConfigSnapshotsLoading] = useState(false);
  const [configCenterDevice, setConfigCenterDevice] = useState<Device | null>(null);
  const [configViewContent, setConfigViewContent] = useState<string>('');
  const [configViewSnapshot, setConfigViewSnapshot] = useState<ConfigSnapshot | null>(null);
  const [configDiffLeft, setConfigDiffLeft] = useState<ConfigSnapshot | null>(null);
  const [configDiffRight, setConfigDiffRight] = useState<ConfigSnapshot | null>(null);
  const [diffOnlyChanges, setDiffOnlyChanges] = useState(false);
  const [diffShowFullBoth, setDiffShowFullBoth] = useState(false);
  const [diffFocusChangeIdx, setDiffFocusChangeIdx] = useState(0);
  const [diffBlockQuery, setDiffBlockQuery] = useState('');
  const [configSnapshotKeyword, setConfigSnapshotKeyword] = useState('');
  const [configSearchQuery, setConfigSearchQuery] = useState('');
  const [configSearchResults, setConfigSearchResults] = useState<any[]>([]);
  const [configSearchLoading, setConfigSearchLoading] = useState(false);
  const [isTakingSnapshot, setIsTakingSnapshot] = useState(false);
  const diffLineRefs = React.useRef<Record<number, HTMLDivElement | null>>({});
  // Schedule state
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleHour, setScheduleHour] = useState(2);
  const [scheduleMinute, setScheduleMinute] = useState(0);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const [configGroupOpen, setConfigGroupOpen] = useState(() => location.pathname.startsWith('/config'));
  const [automationGroupOpen, setAutomationGroupOpen] = useState(() => location.pathname.startsWith('/automation'));
  const [inventoryGroupOpen, setInventoryGroupOpen] = useState(() => location.pathname.startsWith('/inventory'));
  const [alertGroupOpen, setAlertGroupOpen] = useState(() => ['alerts', 'alert-rules', 'maintenance'].includes(location.pathname.split('/')[1] || 'dashboard'));
  const [monitoringGroupOpen, setMonitoringGroupOpen] = useState(() => location.pathname === '/monitoring' || location.pathname === '/inventory/interfaces');
  const [managementGroupOpen, setManagementGroupOpen] = useState(() => ['history', 'configuration', 'users'].includes(location.pathname.split('/')[1] || 'dashboard'));
  const [realtimeSectionOpen, setRealtimeSectionOpen] = useState(true);
  const [alertsSectionOpen, setAlertsSectionOpen] = useState(true);
  const [assetsSectionOpen, setAssetsSectionOpen] = useState(true);
  const [automationSectionOpen, setAutomationSectionOpen] = useState(true);
  const [capacitySectionOpen, setCapacitySectionOpen] = useState(true);
  const [managementSectionOpen, setManagementSectionOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 768);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  const [recentSidebarPaths, setRecentSidebarPaths] = useState<string[]>([]);
  const [pinnedPaths, setPinnedPaths] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('netops_pinned_nav') || '[]'); } catch { return []; }
  });
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const [cmdPaletteQuery, setCmdPaletteQuery] = useState('');
  // Playbook state
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [platforms, setPlatforms] = useState<Record<string, any>>({});
  const [playbookPlatform, setPlaybookPlatform] = useState<string>('cisco_ios');
  const [playbookExecutions, setPlaybookExecutions] = useState<any[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<any>(null);
  const [playbookVars, setPlaybookVars] = useState<Record<string, string>>({});
  const [playbookDeviceIds, setPlaybookDeviceIds] = useState<string[]>([]);
  const [playbookDryRun, setPlaybookDryRun] = useState(true);
  const [playbookConcurrency, setPlaybookConcurrency] = useState(1);
  const [playbookPreview, setPlaybookPreview] = useState<any>(null);
  const [quickPlaybookScenario, setQuickPlaybookScenario] = useState<any>(null);
  const [quickPlaybookVars, setQuickPlaybookVars] = useState<Record<string, string>>({});
  const [quickPlaybookPlatform, setQuickPlaybookPlatform] = useState<string>('cisco_ios');
  const [quickPlaybookDryRun, setQuickPlaybookDryRun] = useState(true);
  const [quickPlaybookConcurrency, setQuickPlaybookConcurrency] = useState(1);
  const [quickPlaybookPreview, setQuickPlaybookPreview] = useState<any>(null);
  const [quickRiskConfirmed, setQuickRiskConfirmed] = useState(false);
  const [isQuickPlaybookRunning, setIsQuickPlaybookRunning] = useState(false);
  const [quickExecutionResult, setQuickExecutionResult] = useState<{ executionId: string; deviceCount: number; dryRun: boolean; scenarioName: string; scenarioNameZh: string; timestamp: number } | null>(null);
  const [showCustomCommandModal, setShowCustomCommandModal] = useState(false);
  const [showCmdPreviewModal, setShowCmdPreviewModal] = useState(false);
  const [scenarioSearch, setScenarioSearch] = useState('');
  const [showAddScenarioModal, setShowAddScenarioModal] = useState(false);
  const [newScenarioForm, setNewScenarioForm] = useState({
    name: '',
    name_zh: '',
    description: '',
    description_zh: '',
    category: 'Custom',
    icon: '🧩',
    risk: 'medium',
    platform: 'cisco_ios',
    pre_check: '',
    execute: '',
    post_check: '',
    rollback: '',
  });
  const [newScenarioVariables, setNewScenarioVariables] = useState<Array<{ key: string; label: string; type: string; required: boolean; placeholder?: string }>>([]);
  const [scenarioDraftOrigin, setScenarioDraftOrigin] = useState<{ kind: 'manual' | 'template'; templateName?: string; variableKeys: string[] }>({
    kind: 'manual',
    variableKeys: [],
  });
  const [isSavingScenario, setIsSavingScenario] = useState(false);
  const [wsMessages, setWsMessages] = useState<any[]>([]);
  const [deviceStatusMap, setDeviceStatusMap] = useState<Record<string, { hostname: string; status: string; currentPhase?: string; phases: Record<string, { success: boolean; output?: string }>; error?: string }>>({});
  const [wsCompleteMsg, setWsCompleteMsg] = useState<any>(null);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [selectedExecutionDetail, setSelectedExecutionDetail] = useState<any | null>(null);
  const [selectedExecutionLoading, setSelectedExecutionLoading] = useState(false);
  const [executionStatus, setExecutionStatus] = useState<string>('idle');
  // History pagination & lazy device loading
  const [playbookHistoryPage, setPlaybookHistoryPage] = useState(1);
  const [playbookHistoryTotal, setPlaybookHistoryTotal] = useState(0);
  const [playbookHistoryStatusFilter, setPlaybookHistoryStatusFilter] = useState('all');
  const [playbookHistoryScenarioSearch, setPlaybookHistoryScenarioSearch] = useState('');
  const [selectedExecDevices, setSelectedExecDevices] = useState<any[]>([]);
  const [selectedExecDevicesTotal, setSelectedExecDevicesTotal] = useState(0);
  const [selectedExecDevicesPage, setSelectedExecDevicesPage] = useState(1);
  const [selectedExecDevicesStatusFilter, setSelectedExecDevicesStatusFilter] = useState('all');
  const [selectedExecDevicesLoading, setSelectedExecDevicesLoading] = useState(false);
  const [selectedDeviceDetail, setSelectedDeviceDetail] = useState<any | null>(null);
  const [selectedDeviceDetailLoading, setSelectedDeviceDetailLoading] = useState(false);
  const wsRef = React.useRef<WebSocket | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [topologyLinks, setTopologyLinks] = useState<any[]>([]);
  const [topologySearch, setTopologySearch] = useState('');
  const [topologyStatusFilter, setTopologyStatusFilter] = useState<'all' | 'online' | 'offline' | 'pending'>('all');
  const [topologyRoleFilter, setTopologyRoleFilter] = useState('all');
  const [topologySiteFilter, setTopologySiteFilter] = useState('all');
  const [selectedTopologyDeviceId, setSelectedTopologyDeviceId] = useState<string | null>(null);
  const [selectedTopologyLinkKey, setSelectedTopologyLinkKey] = useState<string | null>(null);
  const [topologyDiscoveryRunning, setTopologyDiscoveryRunning] = useState(false);
  const topologyRef = React.useRef<HTMLDivElement>(null);

  type TopologyOperationalState = 'up' | 'degraded' | 'down' | 'stale' | 'unknown';

  type TopologyInterfaceSnapshot = {
    name: string;
    status: string;
    maxUtilizationPct: number | null;
    errorCount: number;
    discardCount: number;
    flapping: boolean;
    operationalState: TopologyOperationalState;
  };

  type TopologyDecoratedLink = {
    id?: string;
    link_key?: string;
    source_device_id: string;
    target_device_id: string;
    source_port?: string;
    source_port_normalized?: string;
    target_port?: string;
    target_port_normalized?: string;
    source_hostname?: string;
    target_hostname?: string;
    source_hostname_resolved?: string;
    target_hostname_resolved?: string;
    discovery_source?: string;
    evidence_count?: number;
    metadata_json?: string;
    last_seen?: string;
    inferred?: boolean;
    status?: string;
    operational_state: TopologyOperationalState;
    operational_summary: string;
    evidence_sources: string[];
    reverse_confirmed: boolean;
    source_interface_snapshot: TopologyInterfaceSnapshot | null;
    target_interface_snapshot: TopologyInterfaceSnapshot | null;
  };

  const activeTab = location.pathname.split('/')[1] || 'dashboard';
  const configPage = location.pathname.split('/')[2] || 'backup';
  const automationPage = location.pathname.split('/')[2] || 'execute';
  const inventorySubPage = location.pathname.split('/')[2] || 'devices';
  const setActiveTab = (tab: string) => {
    navigate(`/${tab}`);
    if (isMobile) setSidebarCollapsed(true);
  };
  const navTo = (path: string) => {
    navigate(path);
    if (isMobile) setSidebarCollapsed(true);
  };

  const togglePin = useCallback((path: string) => {
    setPinnedPaths((prev) => {
      const next = prev.includes(path)
        ? prev.filter((p) => p !== path)
        : [...prev, path].slice(0, 6);
      localStorage.setItem('netops_pinned_nav', JSON.stringify(next));
      return next;
    });
  }, []);

  const getSidebarRecentLabel = useCallback((path: string): string => {
    if (path === '/dashboard') return t('dashboard');
    if (path === '/monitoring') return language === 'zh' ? '监控中心' : 'Monitoring Center';
    if (path === '/topology') return language === 'zh' ? '网络拓扑' : 'Topology';
    if (path === '/health') return language === 'zh' ? '健康检测' : 'Health Detection';
    if (path === '/alerts') return language === 'zh' ? '告警信息' : 'Alert Desk';
    if (path === '/alert-rules') return language === 'zh' ? '告警规则' : 'Alert Rules';
    if (path === '/maintenance') return language === 'zh' ? '维护期' : 'Maintenance';
    if (path === '/inventory/devices') return t('deviceList');
    if (path === '/inventory/interfaces') return t('interfaceMonitoring');
    if (path === '/ipam') return language === 'zh' ? 'IP/VLAN 管理' : 'IP/VLAN Mgmt';
    if (path === '/assets') return language === 'zh' ? '资产管理' : 'Assets';
    if (path === '/automation/execute') return t('directExecution');
    if (path === '/automation/scenarios') return t('scenarioLibrary');
    if (path === '/automation/history') return t('executionHistory');
    if (path === '/config/backup') return t('backupHistory');
    if (path === '/config/diff') return t('diffCompare');
    if (path === '/config/search') return t('configSearchTab');
    if (path === '/config/schedule') return t('scheduledBackup');
    if (path === '/config/drift') return language === 'zh' ? '配置漂移' : 'Config Drift';
    if (path === '/compliance') return t('compliance');
    if (path === '/capacity') return language === 'zh' ? '容量规划' : 'Capacity Planning';
    if (path === '/reports') return language === 'zh' ? '报表中心' : 'Reports';
    if (path === '/history') return t('auditLogs');
    if (path === '/configuration') return language === 'zh' ? '平台设置' : 'Platform Settings';
    if (path === '/users') return t('userManagement');
    return path.replace('/', '');
  }, [language, t]);

  const recentSidebarItems = useMemo(() => {
    return recentSidebarPaths
      .filter((path) => path && path !== '/')
      .slice(0, 3)
      .map((path) => ({ path, label: getSidebarRecentLabel(path) }));
  }, [getSidebarRecentLabel, recentSidebarPaths]);

  const removeRecentPath = useCallback((path: string) => {
    setRecentSidebarPaths((prev) => prev.filter((p) => p !== path));
  }, []);

  // 命令面板全量导航条目
  const allNavItems = useMemo<{ path: string; label: string; group: string }[]>(() => {
    const zh = language === 'zh';
    return [
      { path: '/dashboard', label: t('dashboard'), group: zh ? '实时监控' : 'Real-time' },
      { path: '/monitoring', label: zh ? '监控中心' : 'Monitoring Center', group: zh ? '实时监控' : 'Real-time' },
      { path: '/topology', label: zh ? '网络拓扑' : 'Topology', group: zh ? '实时监控' : 'Real-time' },
      { path: '/health', label: zh ? '健康检测' : 'Health Detection', group: zh ? '实时监控' : 'Real-time' },
      { path: '/inventory/devices', label: t('deviceList'), group: zh ? '设备清单' : 'Inventory' },
      { path: '/inventory/interfaces', label: t('interfaceMonitoring'), group: zh ? '设备清单' : 'Inventory' },
      { path: '/ipam', label: zh ? 'IP/VLAN 管理' : 'IP/VLAN Mgmt', group: zh ? '设备清单' : 'Inventory' },
      { path: '/assets', label: zh ? '资产管理' : 'Assets', group: zh ? '设备清单' : 'Inventory' },
      { path: '/alerts', label: zh ? '告警信息' : 'Alert Desk', group: zh ? '告警管理' : 'Alerts' },
      { path: '/alert-rules', label: zh ? '告警规则' : 'Alert Rules', group: zh ? '告警管理' : 'Alerts' },
      { path: '/maintenance', label: zh ? '维护期' : 'Maintenance', group: zh ? '告警管理' : 'Alerts' },
      { path: '/automation/execute', label: t('directExecution'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scenarios', label: t('scenarioLibrary'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/history', label: t('executionHistory'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/config/backup', label: t('backupHistory'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/diff', label: t('diffCompare'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/search', label: t('configSearchTab'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/schedule', label: t('scheduledBackup'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/drift', label: zh ? '配置漂移' : 'Config Drift', group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/compliance', label: t('compliance'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/capacity', label: zh ? '容量规划' : 'Capacity Planning', group: zh ? '分析报告' : 'Analytics' },
      { path: '/reports', label: zh ? '报表中心' : 'Reports', group: zh ? '分析报告' : 'Analytics' },
      { path: '/history', label: t('auditLogs'), group: zh ? '平台管理' : 'Management' },
      { path: '/configuration', label: zh ? '平台设置' : 'Platform Settings', group: zh ? '平台管理' : 'Management' },
      { path: '/users', label: t('userManagement'), group: zh ? '平台管理' : 'Management' },
    ];
  }, [language, t]);

  const cmdPaletteFiltered = useMemo(() => {
    const q = cmdPaletteQuery.trim().toLowerCase();
    if (!q) return allNavItems;
    return allNavItems.filter(
      (item) => item.label.toLowerCase().includes(q) || item.group.toLowerCase().includes(q) || item.path.toLowerCase().includes(q)
    );
  }, [allNavItems, cmdPaletteQuery]);

  // Ctrl+K 全局快捷键
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setCmdPaletteOpen((v) => !v);
        setCmdPaletteQuery('');
      }
      if (e.key === 'Escape') setCmdPaletteOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const pageTitle = useMemo(() => {
    if (activeTab === 'automation') {
      const map: Record<string, string> = {
        execute: t('directExecution'),
        scenarios: t('scenarioLibrary'),
        history: t('executionHistory'),
      };
      return map[automationPage] || automationPage;
    }
    if (activeTab === 'config') {
      const map: Record<string, string> = {
        backup: t('backupHistory'),
        diff: t('diffCompare'),
        search: t('configSearchTab'),
        schedule: t('scheduledBackup'),
        drift: language === 'zh' ? '配置漂移' : 'Config Drift',
      };
      return map[configPage] || configPage;
    }
    if (activeTab === 'inventory') {
      const map: Record<string, string> = {
        devices: t('deviceList'),
        interfaces: t('interfaceMonitoring'),
      };
      return map[inventorySubPage] || inventorySubPage;
    }
    if (activeTab === 'users') return t('userManagement');
    if (activeTab === 'alerts') return language === 'zh' ? '告警信息' : 'Alert Desk';
    if (activeTab === 'alert-rules') return language === 'zh' ? '告警规则' : 'Alert Rules';
    if (activeTab === 'maintenance') return language === 'zh' ? '维护期' : 'Maintenance';
    if (activeTab === 'history') return t('auditLogs');
    if (activeTab === 'configuration') return language === 'zh' ? '平台设置' : 'Platform Settings';
    if (activeTab === 'reports') return language === 'zh' ? '报表中心' : 'Reports';
    if (activeTab === 'capacity') return language === 'zh' ? '容量规划' : 'Capacity Planning';
    if (activeTab === 'ipam') return language === 'zh' ? 'IP/VLAN管理' : 'IP/VLAN Management';
    if (activeTab === 'assets') return language === 'zh' ? '资产管理' : 'Asset Management';
    if (activeTab === 'compliance') return t('compliance');
    if (activeTab === 'monitoring') return language === 'zh' ? '监控中心' : 'Monitoring Center';
    if (activeTab === 'health') return language === 'zh' ? '健康检测' : 'Health Detection';
    if (activeTab === 'topology') return language === 'zh' ? '网络拓扑' : 'Topology';
    return t('dashboard');
  }, [activeTab, automationPage, configPage, inventorySubPage, language, t]);

  const filteredScenarios = useMemo(() => {
    const q = scenarioSearch.trim().toLowerCase();
    if (!q) return scenarios;

    return scenarios.filter((sc: any) => {
      const textParts: string[] = [
        sc.id,
        sc.name,
        sc.name_zh,
        sc.description,
        sc.description_zh,
        sc.category,
        sc.risk,
      ].filter(Boolean);

      (sc.variables || []).forEach((v: any) => {
        textParts.push(v.key || '', v.label || '', v.placeholder || '');
      });

      Object.values(sc.platform_phases || {}).forEach((phase: any) => {
        ['pre_check', 'execute', 'post_check', 'rollback'].forEach((key) => {
          (phase?.[key] || []).forEach((cmd: string) => textParts.push(cmd));
        });
      });

      const blob = textParts.join(' ').toLowerCase();
      return blob.includes(q);
    });
  }, [scenarios, scenarioSearch]);

  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (mobile) setSidebarCollapsed(true);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (isAuthenticated && location.pathname === '/') {
      navigate('/dashboard', { replace: true });
    }
  }, [isAuthenticated, location.pathname, navigate]);

  useEffect(() => {
    if (!isAuthenticated) {
      setRecentSidebarPaths([]);
      return;
    }

    const path = location.pathname;
    if (!path || path === '/') return;

    setRecentSidebarPaths((prev) => {
      const next = [path, ...prev.filter((item) => item !== path)].slice(0, 3);
      return next;
    });
  }, [isAuthenticated, location.pathname]);

  useEffect(() => {
    const monitoringActive = activeTab === 'monitoring' || location.pathname === '/inventory/interfaces';
    const alertActive = ['alerts', 'alert-rules', 'maintenance'].includes(activeTab);
    const configActive = activeTab === 'config' || activeTab === 'compliance' || location.pathname.startsWith('/config');
    const automationActive = activeTab === 'automation' || location.pathname.startsWith('/automation');
    const inventoryActive = activeTab === 'inventory' || activeTab === 'ipam';
    const managementActive = ['history', 'configuration', 'users'].includes(activeTab);
    setMonitoringGroupOpen(monitoringActive);
    setAlertGroupOpen(alertActive);
    setConfigGroupOpen(configActive);
    setAutomationGroupOpen(automationActive);
    setInventoryGroupOpen(inventoryActive);
    setManagementGroupOpen(managementActive);
    // Auto-expand parent section when navigating into it
    if (['dashboard', 'monitoring', 'topology', 'health'].includes(activeTab) || location.pathname === '/inventory/interfaces') setRealtimeSectionOpen(true);
    if (alertActive) setAlertsSectionOpen(true);
    if (inventoryActive) setAssetsSectionOpen(true);
    if (automationActive || configActive) setAutomationSectionOpen(true);
    if (['capacity', 'reports'].includes(activeTab)) setCapacitySectionOpen(true);
    if (managementActive) setManagementSectionOpen(true);
  }, [activeTab, location.pathname]);

  // Load config snapshots from backend when entering Config Center tab
  const loadConfigSnapshots = async (
    deviceId?: string,
    options?: { requireFilter?: boolean; q?: string }
  ) => {
    const q = (options?.q ?? configSnapshotKeyword).trim();
    const requireFilter = options?.requireFilter ?? false;
    const hasAnyFilter = Boolean(deviceId || q);

    if (requireFilter && !hasAnyFilter) {
      setConfigSnapshots([]);
      setConfigSnapshotsLoading(false);
      return;
    }

    setConfigSnapshotsLoading(true);
    try {
      const params = new URLSearchParams();
      if (deviceId) params.set('device_id', deviceId);
      if (q) params.set('q', q);
      const qs = params.toString();
      const url = qs ? `/api/configs/snapshots?${qs}` : '/api/configs/snapshots';
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json() as ConfigSnapshot[];
        setConfigSnapshots(data);
      }
    } catch { /* network error */ }
    finally { setConfigSnapshotsLoading(false); }
  };

  // Load schedule settings from backend
  const loadScheduleConfig = async () => {
    try {
      const resp = await fetch('/api/configs/schedule');
      if (resp.ok) {
        const cfg = await resp.json();
        setScheduleEnabled(cfg.enabled ?? true);
        setScheduleHour(cfg.hour ?? 2);
        setScheduleMinute(cfg.minute ?? 0);
      }
    } catch { /* ignore */ }
  };

  // 閳光偓閳光偓 Playbook helpers 閳光偓閳光偓
  const loadScenarios = async () => {
    try {
      const [scenResp, platResp] = await Promise.all([
        fetch('/api/playbooks/scenarios'),
        fetch('/api/playbooks/platforms'),
      ]);
      if (scenResp.ok) setScenarios(await scenResp.json());
      if (platResp.ok) setPlatforms(await platResp.json());
    } catch { /* ignore */ }
  };

  const loadPlaybookHistory = async (
    page = playbookHistoryPage,
    statusFilter = playbookHistoryStatusFilter,
    scenarioFilter = playbookHistoryScenarioSearch,
  ) => {
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: '20',
        status: statusFilter,
        scenario: scenarioFilter,
      });
      const playbookResp = await fetch(`/api/playbooks?${params}`);
      let playbookItems: any[] = [];
      let playbookTotal = 0;
      if (playbookResp.ok) {
        const d = await playbookResp.json();
        playbookItems = (d.items || []).map((e: any) => ({ ...e, _type: 'playbook' }));
        playbookTotal = d.total || 0;
      }
      setPlaybookExecutions(playbookItems);
      setPlaybookHistoryTotal(playbookTotal);
    } catch { /* ignore */ }
  };

  const loadExecDevices = async (
    execId: string,
    page = 1,
    statusFilter = 'all',
    search = '',
  ) => {
    setSelectedExecDevicesLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: '20',
        status: statusFilter,
        search,
      });
      const r = await fetch(`/api/playbooks/${execId}/devices?${params}`);
      if (r.ok) {
        const data = await r.json();
        setSelectedExecDevices(data.items || []);
        setSelectedExecDevicesTotal(data.total || 0);
      }
    } finally {
      setSelectedExecDevicesLoading(false);
    }
  };

  const loadNotifications = useCallback(async () => {
    try {
      const userId = currentUser.id ? encodeURIComponent(String(currentUser.id)) : '';
      const url = userId ? `/api/notifications?limit=40&user_id=${userId}` : '/api/notifications?limit=40';
      const resp = await fetch(url);
      if (!resp.ok) return;
      const data = await resp.json();
      setNotifications((data || []).map((n: any) => ({
        id: String(n.id),
        title: n.source === 'system_resource'
          ? (language === 'zh' ? `平台资源告警: ${n.title}` : `Platform Resource Alert: ${n.title}`)
          : n.title,
        message: n.message,
        time: n.time,
        source: n.source,
        severity: n.severity,
        read: !!n.read || !!notificationReadMap[String(n.id)],
      })));
    } catch {
      // ignore polling errors
    }
  }, [currentUser.id, language, notificationReadMap]);

  const markNotificationsAsRead = useCallback(async (ids: string[]) => {
    if (!ids.length || !currentUser.id) return;
    try {
      await fetch('/api/notifications/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: String(currentUser.id), notification_ids: ids }),
      });
    } catch {
      // keep optimistic local UI state even on transient API errors
    }
  }, [currentUser.id]);

  const openQuickPlaybookModal = (scenario: any) => {
    const platform = scenario.default_platform || scenario.supported_platforms?.[0] || 'cisco_ios';
    setQuickPlaybookScenario(scenario);
    setQuickPlaybookPlatform(platform);
    setQuickPlaybookVars({});
    setQuickPlaybookDryRun(true);
    setQuickPlaybookConcurrency(1);
    setQuickPlaybookPreview(null);
    setQuickRiskConfirmed(false);
    setQuickExecutionResult(null);
  };

  const loadQuickPlaybookPreview = useCallback(async (scenario: any, platform: string, variables: Record<string, string>) => {
    if (!scenario?.id || !platform) {
      setQuickPlaybookPreview(null);
      return;
    }
    try {
      const resp = await fetch('/api/playbooks/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenario.id, platform, variables }),
      });
      if (!resp.ok) {
        setQuickPlaybookPreview(null);
        return;
      }
      setQuickPlaybookPreview(await resp.json());
    } catch {
      setQuickPlaybookPreview(null);
    }
  }, []);

  const runQuickPlaybook = async (dryRunOverride?: boolean) => {
    if (!quickPlaybookScenario) return;
    const targetDeviceIds = batchMode
      ? batchDeviceIds
      : (selectedDevice?.id ? [selectedDevice.id] : []);

    if (targetDeviceIds.length === 0) {
      showToast('Select target device(s) first in Direct Execution', 'error');
      return;
    }
    if (quickHasMixedPlatforms) {
      showToast(language === 'zh' ? '批量目标包含多个平台，请按平台分组执行。' : 'Batch targets contain multiple platforms. Execute one platform group at a time.', 'error');
      return;
    }
    if (quickPlatformMismatch) {
      showToast(language === 'zh' ? '当前场景不支持所选设备平台。' : 'Current scenario does not support selected device platform.', 'error');
      return;
    }

    const effectiveDryRun = dryRunOverride !== undefined ? dryRunOverride : quickPlaybookDryRun;
    if (dryRunOverride !== undefined) setQuickPlaybookDryRun(dryRunOverride);

    setWsMessages([]);
    setDeviceStatusMap({});
    setWsCompleteMsg(null);
    setIsQuickPlaybookRunning(true);
    try {
      const resp = await fetch('/api/playbooks/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: quickPlaybookScenario.id,
          platform: quickPlaybookPlatform,
          device_ids: targetDeviceIds,
          variables: quickPlaybookVars,
          dry_run: effectiveDryRun,
          concurrency: quickPlaybookConcurrency,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showToast(`Execution failed: ${data.detail || resp.statusText}`, 'error');
        setIsQuickPlaybookRunning(false);
        return;
      }

      showToast(language === 'zh' ? `执行任务已提交，目标设备 ${targetDeviceIds.length} 台` : `Execution submitted for ${targetDeviceIds.length} device(s)`, 'success');
      setSelectedScenario(quickPlaybookScenario);
      setPlaybookPlatform(quickPlaybookPlatform);
      setPlaybookVars(quickPlaybookVars);
      setPlaybookDryRun(effectiveDryRun);
      setPlaybookConcurrency(quickPlaybookConcurrency);
      setPlaybookDeviceIds(targetDeviceIds);
      setActiveExecutionId(data.execution_id || null);
      setExecutionStatus('running');
      setQuickExecutionResult({
        executionId: data.execution_id || '',
        deviceCount: targetDeviceIds.length,
        dryRun: effectiveDryRun,
        scenarioName: quickPlaybookScenario.name,
        scenarioNameZh: quickPlaybookScenario.name_zh,
        timestamp: Date.now(),
      });
      // Open WebSocket for live per-device output in Panel 3
      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const wsUrl = `${wsProtocol}://${window.location.host}/api/ws/playbook/${data.execution_id}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          setWsMessages(prev => [...prev, msg]);
          // Aggregate into deviceStatusMap for Panel 3
          if (msg.type === 'device_start') {
            setDeviceStatusMap(prev => ({ ...prev, [msg.device_id]: { hostname: msg.hostname || String(msg.device_id), status: 'running', phases: {} } }));
          } else if (msg.type === 'phase_done') {
            setDeviceStatusMap(prev => {
              const dev = prev[msg.device_id];
              if (!dev) return prev;
              return { ...prev, [msg.device_id]: { ...dev, phases: { ...dev.phases, [msg.phase]: { success: msg.output?.success ?? true, output: msg.output?.output } } } };
            });
          } else if (msg.type === 'device_done') {
            setDeviceStatusMap(prev => {
              const dev = prev[msg.device_id];
              return dev ? { ...prev, [msg.device_id]: { ...dev, status: msg.status || 'success', currentPhase: undefined } } : prev;
            });
          } else if (msg.type === 'device_error') {
            setDeviceStatusMap(prev => ({ ...prev, [msg.device_id]: { hostname: String(msg.device_id), status: 'error', phases: {}, error: msg.error || 'Unknown error' } }));
          } else if (msg.type === 'complete') {
            setWsCompleteMsg(msg);
            setExecutionStatus(msg.status);
            setIsQuickPlaybookRunning(false);
            ws.close();
            loadPlaybookHistory();
          }
        } catch { /* ignore */ }
      };
      ws.onerror = () => { setExecutionStatus('ws_error'); setIsQuickPlaybookRunning(false); };
      ws.onclose = () => { wsRef.current = null; };
      loadPlaybookHistory();
    } catch {
      showToast('Connection error', 'error');
      setIsQuickPlaybookRunning(false);
    }
  };

  useEffect(() => {
    if (!quickPlaybookScenario) return;
    const timer = window.setTimeout(() => {
      loadQuickPlaybookPreview(quickPlaybookScenario, quickPlaybookPlatform, quickPlaybookVars);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [quickPlaybookScenario, quickPlaybookPlatform, quickPlaybookVars, loadQuickPlaybookPreview]);

  const splitLines = (text: string) => text.split('\n').map(s => s.trim()).filter(Boolean);

  const quickTargetDevices = useMemo(() => {
    if (batchMode) {
      const selectedIds = new Set(batchDeviceIds);
      return devices.filter((d) => selectedIds.has(d.id));
    }
    return selectedDevice ? [selectedDevice] : [];
  }, [batchMode, batchDeviceIds, devices, selectedDevice]);

  const quickDetectedPlatforms = useMemo(() => {
    return Array.from(new Set(quickTargetDevices.map((d) => d.platform).filter(Boolean)));
  }, [quickTargetDevices]);

  const quickHasMixedPlatforms = quickDetectedPlatforms.length > 1;
  const quickDetectedPlatform = quickDetectedPlatforms.length === 1 ? quickDetectedPlatforms[0] : '';
  const quickScenarioSupportsDetectedPlatform = !!(
    quickPlaybookScenario &&
    quickDetectedPlatform &&
    (quickPlaybookScenario.supported_platforms || []).includes(quickDetectedPlatform)
  );
  const quickAutoPlatform = quickDetectedPlatform
    || quickPlaybookScenario?.default_platform
    || quickPlaybookScenario?.supported_platforms?.[0]
    || 'cisco_ios';

  const quickPlatformMismatch = !!(
    quickPlaybookScenario &&
    quickDetectedPlatform &&
    !quickScenarioSupportsDetectedPlatform
  );

  useEffect(() => {
    if (!quickPlaybookScenario) return;
    if (quickPlaybookPlatform !== quickAutoPlatform) {
      setQuickPlaybookPlatform(quickAutoPlatform);
    }
  }, [quickPlaybookScenario, quickAutoPlatform, quickPlaybookPlatform]);
  const resetScenarioDraft = useCallback(() => {
    setShowAddScenarioModal(false);
    setNewScenarioForm({
      name: '',
      name_zh: '',
      description: '',
      description_zh: '',
      category: 'Custom',
      icon: '🧩',
      risk: 'medium',
      platform: 'cisco_ios',
      pre_check: '',
      execute: '',
      post_check: '',
      rollback: '',
    });
    setNewScenarioVariables([]);
    setScenarioDraftOrigin({ kind: 'manual', variableKeys: [] });
  }, []);

  const inferScenarioVariableType = (key: string): 'text' | 'number' => {
    const normalized = key.toLowerCase();
    if (/(id|vlan|asn|metric|count|port|timeout|mtu|weight|preference|cost|bandwidth|delay)$/.test(normalized)) {
      return 'number';
    }
    return 'text';
  };

  const formatScenarioVariableLabel = (key: string) => key
    .replace(/[._-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());

  const handleCreateScenarioDraftFromTemplate = () => {
    if (!selectedConfigTemplate) {
      showToast(language === 'zh' ? '请先选择模板资产' : 'Select a template asset first', 'error');
      return;
    }

    if (!editorContent.trim()) {
      showToast(language === 'zh' ? '模板内容为空，无法转换为场景草稿。' : 'Template content is empty and cannot be converted into a scenario draft', 'error');
      return;
    }

    const platformFromScope = configScopePlatform !== 'all'
      ? configScopePlatform
      : (configPlatformOptions[0]
        || ({
          Cisco: 'cisco_ios',
          Juniper: 'juniper_junos',
          Huawei: 'huawei_vrp',
          H3C: 'h3c_comware',
          Arista: 'arista_eos',
        } as Record<string, string>)[selectedConfigTemplate.vendor || '']
        || 'cisco_ios');

    const detectedVariables = extractVars(editorContent);
    const variableDrafts = detectedVariables.map((key) => ({
      key,
      label: formatScenarioVariableLabel(key),
      type: inferScenarioVariableType(key),
      required: true,
      placeholder: configVariableMap[key] || key,
    }));

    setNewScenarioForm({
      name: `${selectedConfigTemplate.name} Draft`,
      name_zh: `${selectedConfigTemplate.name} 草稿`,
      description: `Imported from configuration template ${selectedConfigTemplate.name}`,
      description_zh: `从配置模板 ${selectedConfigTemplate.name} 导入`,
      category: 'Config Template',
      icon: '🧩',
      risk: configScopedDevices.length > 10 ? 'high' : configScopedDevices.length > 1 ? 'medium' : 'low',
      platform: platformFromScope,
      pre_check: '',
      execute: editorContent,
      post_check: '',
      rollback: '',
    });
    setNewScenarioVariables(variableDrafts);
    setScenarioDraftOrigin({
      kind: 'template',
      templateName: selectedConfigTemplate.name,
      variableKeys: detectedVariables,
    });
    setShowAddScenarioModal(true);
  };

  const openManualScenarioDraft = () => {
    resetScenarioDraft();
    setShowAddScenarioModal(true);
  };

  const createScenario = async () => {
    if (!newScenarioForm.name.trim()) {
      showToast('Scenario name is required', 'error');
      return;
    }
    if (!newScenarioForm.execute.trim()) {
      showToast('Execute commands cannot be empty', 'error');
      return;
    }

    const platform = newScenarioForm.platform;
    const payload = {
      name: newScenarioForm.name.trim(),
      name_zh: newScenarioForm.name_zh.trim() || newScenarioForm.name.trim(),
      description: newScenarioForm.description.trim(),
      description_zh: newScenarioForm.description_zh.trim() || newScenarioForm.description.trim(),
      category: newScenarioForm.category.trim() || 'Custom',
      icon: newScenarioForm.icon.trim() || '🧩',
      risk: newScenarioForm.risk,
      supported_platforms: [platform],
      default_platform: platform,
      variables: newScenarioVariables,
      platform_phases: {
        [platform]: {
          pre_check: splitLines(newScenarioForm.pre_check),
          execute: splitLines(newScenarioForm.execute),
          post_check: splitLines(newScenarioForm.post_check),
          rollback: splitLines(newScenarioForm.rollback),
        },
      },
    };

    setIsSavingScenario(true);
    try {
      const resp = await fetch('/api/playbooks/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showToast(`Error: ${data.detail || resp.statusText}`, 'error');
        return;
      }

      resetScenarioDraft();
      showToast('Custom scenario created', 'success');
      await loadScenarios();
      openQuickPlaybookModal(data);
      navigate('/automation/execute');
    } catch {
      showToast('Connection error', 'error');
    } finally {
      setIsSavingScenario(false);
    }
  };

  const previewPlaybook = async () => {
    if (!selectedScenario) {
        showToast(language === 'zh' ? '请先选择场景' : 'Please select a scenario first', 'error');
      return;
    }
    const missingRequired = (selectedScenario.variables || [])
      .filter((v: any) => v.required && !String(playbookVars[v.key] ?? '').trim())
      .map((v: any) => v.label || v.key);
    if (missingRequired.length > 0) {
      showToast(
        language === 'zh'
          ? `缂傚搫鐨箛鍛綖鐎涙顔? ${missingRequired.join(', ')}`
          : `Missing required fields: ${missingRequired.join(', ')}`,
        'error'
      );
      setPlaybookPreview(null);
      return;
    }
    try {
      const resp = await fetch('/api/playbooks/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: selectedScenario.id, platform: playbookPlatform, variables: playbookVars }),
      });
      if (resp.ok) {
        setPlaybookPreview(await resp.json());
        showToast(language === 'zh' ? '命令预览已生成' : 'Command preview generated', 'success');
      } else {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        showToast(`Preview failed: ${err.detail || 'Unknown error'}`, 'error');
      }
    } catch {
        showToast(language === 'zh' ? '预览请求失败，请检查网络连接' : 'Preview request failed. Please check your network.', 'error');
    }
  };

  const executePlaybook = async (dryRunOverride?: boolean) => {
    if (!selectedScenario) {
        showToast(language === 'zh' ? '请先选择场景' : 'Please select a scenario first', 'error');
      return;
    }
    if (playbookDeviceIds.length === 0) {
      showToast(language === 'zh' ? '请先选择目标设备' : 'Please select target devices first', 'error');
      return;
    }
    const missingRequired = (selectedScenario.variables || [])
      .filter((v: any) => v.required && !String(playbookVars[v.key] ?? '').trim())
      .map((v: any) => v.label || v.key);
    if (missingRequired.length > 0) {
      showToast(
        language === 'zh'
          ? `缂傚搫鐨箛鍛綖鐎涙顔? ${missingRequired.join(', ')}`
          : `Missing required fields: ${missingRequired.join(', ')}`,
        'error'
      );
      return;
    }
    const effectiveDryRun = dryRunOverride !== undefined ? dryRunOverride : playbookDryRun;
    setPlaybookDryRun(effectiveDryRun);
    setExecutionStatus('starting');
    setWsMessages([]);
    setDeviceStatusMap({});
    setWsCompleteMsg(null);
    try {
      const resp = await fetch('/api/playbooks/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedScenario.id,
          platform: playbookPlatform,
          device_ids: playbookDeviceIds,
          variables: playbookVars,
          dry_run: effectiveDryRun,
          concurrency: playbookConcurrency,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        showToast(`閹笛嗩攽婢惰精瑙? ${errData.detail || resp.statusText}`, 'error');
        setExecutionStatus('idle');
        return;
      }
      if (resp.ok) {
        const { execution_id } = await resp.json();
        setActiveExecutionId(execution_id);
        setExecutionStatus('running');
          showToast(effectiveDryRun ? (language === 'zh' ? 'Dry-Run 已启动' : 'Dry-Run started') : (language === 'zh' ? '执行已启动' : 'Execution started'), 'success');
        // Optimistic: add new execution to the list immediately
        setPlaybookExecutions(prev => [{
          id: execution_id,
          scenario_id: selectedScenario.id,
          scenario_name: selectedScenario.name,
          platform: playbookPlatform,
          device_ids: JSON.stringify(playbookDeviceIds),
          variables: JSON.stringify(playbookVars),
          status: 'running',
          dry_run: effectiveDryRun ? 1 : 0,
          author: 'admin',
          concurrency: playbookConcurrency,
          results_json: '{}',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }, ...prev]);
        // Connect WebSocket via Vite proxy (same origin)
        const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsProtocol}://${window.location.host}/api/ws/playbook/${execution_id}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            setWsMessages(prev => [...prev, msg]);
            // Aggregate into deviceStatusMap
            if (msg.type === 'device_start') {
              setDeviceStatusMap(prev => ({ ...prev, [msg.device_id]: { hostname: msg.hostname || String(msg.device_id), status: 'running', phases: {} } }));
            } else if (msg.type === 'phase_done') {
              setDeviceStatusMap(prev => {
                const dev = prev[msg.device_id];
                if (!dev) return prev;
                return { ...prev, [msg.device_id]: { ...dev, phases: { ...dev.phases, [msg.phase]: { success: msg.output?.success ?? true, output: msg.output?.output } } } };
              });
            } else if (msg.type === 'device_done') {
              setDeviceStatusMap(prev => {
                const dev = prev[msg.device_id];
                return dev ? { ...prev, [msg.device_id]: { ...dev, status: msg.status || 'success', currentPhase: undefined } } : prev;
              });
            } else if (msg.type === 'device_error') {
              setDeviceStatusMap(prev => ({ ...prev, [msg.device_id]: { hostname: String(msg.device_id), status: 'error', phases: {}, error: msg.error || 'Unknown error' } }));
            } else if (msg.type === 'complete') {
              setWsCompleteMsg(msg);
              setExecutionStatus(msg.status);
              ws.close();
              // Refresh to get final results
              loadPlaybookHistory();
            }
          } catch { /* ignore */ }
        };
        ws.onerror = () => setExecutionStatus('ws_error');
        ws.onclose = () => { wsRef.current = null; };
        // Navigate to history to watch
        navigate('/automation/history');
      } else {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        showToast(`Execution failed: ${err.detail || 'Unknown error'}`, 'error');
        setExecutionStatus('idle');
      }
    } catch (e: any) {
      showToast(`Execution error: ${e.message || 'Network error'}`, 'error');
      setExecutionStatus('idle');
    }
  };

  useEffect(() => {
    if (activeTab === 'automation') {
      if (automationPage === 'playbooks') { navigate('/automation/execute'); return; }
      loadScenarios();
      if (automationPage === 'execute' || automationPage === 'scenarios' || automationPage === 'history') {
        loadPlaybookHistory();
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, automationPage]);

  const resetAutomationSubmenuState = useCallback((page: string) => {
    if (page === 'execute') {
      setAutomationSearch('');
      setBatchMode(false);
      setBatchDeviceIds([]);
      setSelectedDevice(null);
      setQuickPlaybookScenario(null);
      setQuickPlaybookVars({});
      setQuickPlaybookPlatform('cisco_ios');
      setQuickPlaybookDryRun(true);
      setQuickPlaybookConcurrency(1);
      setQuickPlaybookPreview(null);
      setQuickRiskConfirmed(false);
      setShowCustomCommandModal(false);
      setShowCmdPreviewModal(false);
      setQuickQueryOutput('');
      setQuickQueryLabel('');
      setQuickQueryStructured(null);
      setQuickQueryView('terminal');
      setQuickQueryMaximized(false);
      setQuickQueryCommands([]);
      return;
    }

    if (page === 'playbooks') {
      setSelectedScenario(null);
      setPlaybookVars({});
      setPlaybookDeviceIds([]);
      setPlaybookDryRun(true);
      setPlaybookConcurrency(1);
      setPlaybookPreview(null);
      return;
    }

    if (page === 'scenarios') {
      setShowAddScenarioModal(false);
      setScenarioSearch('');
    }

    if (page === 'history') {
      setPlaybookHistoryPage(1);
      setPlaybookHistoryStatusFilter('');
      setPlaybookHistoryScenarioSearch('');
    }
  }, []);

  const resetConfigSubmenuState = useCallback((page: string) => {
    if (page === 'backup') {
      setConfigCenterDevice(null);
      setConfigViewSnapshot(null);
      setConfigViewContent('');
      setConfigSnapshots([]);
      setConfigSnapshotsLoading(false);
      setIsTakingSnapshot(false);
      return;
    }

    if (page === 'diff') {
      setConfigDiffLeft(null);
      setConfigDiffRight(null);
      return;
    }

    if (page === 'search') {
      setConfigSearchQuery('');
      setConfigSearchResults([]);
      setConfigSearchLoading(false);
      return;
    }

    if (page === 'schedule') {
      setShowScheduleModal(false);
      setSchedulingTask(null);
      setScheduleForm({
        type: 'once',
        interval: 'daily',
        time: '',
        timezone: 'UTC',
      });
    }
  }, []);

  const resetInventorySubmenuState = useCallback((page: string) => {
    if (page === 'devices') {
      setInventorySearch('');
      setInventoryPlatformFilter('all');
      setInventoryRoleFilter('all');
      setInventoryStatusFilter('all');
      setInventorySortConfig(null);
      setSelectedDeviceIds([]);
      setInventoryPage(1);
      return;
    }

    if (page === 'interfaces') {
      return;
    }
  }, []);

  type SubmenuTab = 'automation' | 'config' | 'inventory';

  const submenuPageByTab = useMemo<Record<SubmenuTab, string>>(() => ({
    automation: automationPage,
    config: configPage,
    inventory: inventorySubPage,
  }), [automationPage, configPage, inventorySubPage]);

  const submenuResetByTab = useMemo<Record<SubmenuTab, (page: string) => void>>(() => ({
    automation: resetAutomationSubmenuState,
    config: resetConfigSubmenuState,
    inventory: resetInventorySubmenuState,
  }), [resetAutomationSubmenuState, resetConfigSubmenuState, resetInventorySubmenuState]);

  const prevSubmenuPageRef = React.useRef<Record<SubmenuTab, string>>({
    automation: automationPage,
    config: configPage,
    inventory: inventorySubPage,
  });

  useEffect(() => {
    if (!(activeTab === 'automation' || activeTab === 'config' || activeTab === 'inventory')) return;

    const tab = activeTab as SubmenuTab;
    const currentPage = submenuPageByTab[tab];
    const prevPage = prevSubmenuPageRef.current[tab];
    if (prevPage === currentPage) return;

    submenuResetByTab[tab](prevPage);
    prevSubmenuPageRef.current[tab] = currentPage;
  }, [activeTab, submenuPageByTab, submenuResetByTab]);

  useEffect(() => {
    if (!isAuthenticated) return;
    loadNotifications();
    const timer = window.setInterval(loadNotifications, 15000);
    return () => window.clearInterval(timer);
  }, [isAuthenticated, loadNotifications]);

  // When entering config_center tab, refresh snapshots + schedule
  useEffect(() => {
    if (activeTab === 'config') {
      if (configPage === 'backup') {
        loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true });
      }
      if (configPage === 'diff') {
        loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true });
      }
      if (configPage === 'search') {
        loadConfigSnapshots(configCenterDevice?.id);
      }
      if (configPage === 'schedule') {
        loadScheduleConfig();
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, configPage, configCenterDevice?.id]);

  const handleExportMap = async () => {
    if (!topologyRef.current) return;
    showToast('Preparing topology map for export...', 'info');
    try {
      // Wait a bit for any animations to settle
      await new Promise(resolve => setTimeout(resolve, 500));
      
      const dataUrl = await htmlToImage.toPng(topologyRef.current, {
        backgroundColor: '#ffffff',
        pixelRatio: 2,
        style: {
          transform: 'scale(1)',
          transformOrigin: 'top left'
        }
      });
      
      const link = document.createElement('a');
      link.download = `network-topology-${new Date().toISOString().slice(0, 10)}.png`;
      link.href = dataUrl;
      link.click();
      showToast('Topology map exported successfully', 'success');
    } catch (error) {
      console.error('Export error:', error);
      showToast('Failed to export map. Please try again.', 'error');
    }
  };

  const [users, setUsers] = useState<UserType[]>([]);
  const [showAddUserModal, setShowAddUserModal] = useState(false);
  const [showEditUserModal, setShowEditUserModal] = useState(false);
  // 密码显示/隐藏 state
  const [showLoginPwd, setShowLoginPwd] = useState(false);
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem('netops_remember') === 'true');
  const [trendDays, setTrendDays] = useState<7 | 30>(7);
  const [dashBannerCollapsed, setDashBannerCollapsed] = useState(false);
  const [dashLastRefresh, setDashLastRefresh] = useState<Date>(new Date());
  const [showNewUserPwd, setShowNewUserPwd] = useState(false);
  const [showEditUserPwd, setShowEditUserPwd] = useState(false);
  const [showAddDevicePwd, setShowAddDevicePwd] = useState(false);
  const [showEditDevicePwd, setShowEditDevicePwd] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showProfilePwd, setShowProfilePwd] = useState(false);
  const [profileForm, setProfileForm] = useState({ username: '', password: '', confirmPassword: '' });
  const [notificationChannels, setNotificationChannels] = useState<{
    feishu:   { webhook_url: string; enabled: boolean };
    dingtalk: { webhook_url: string; enabled: boolean; secret: string };
    wechat:   { webhook_url: string; enabled: boolean };
  }>({
    feishu:   { webhook_url: '', enabled: false },
    dingtalk: { webhook_url: '', enabled: false, secret: '' },
    wechat:   { webhook_url: '', enabled: false },
  });
  const [notifyTestLoading, setNotifyTestLoading] = useState<string>(''); // platform name being tested
  const [editingUser, setEditingUser] = useState<UserType | null>(null);
  const [editUserForm, setEditUserForm] = useState({ username: '', password: '', role: 'Operator' });
  const [configWorkspaceView, setConfigWorkspaceView] = useState<'source' | 'rendered' | 'checks'>('source');
  const [configScopePlatform, setConfigScopePlatform] = useState<string>('all');
  const [configScopeRole, setConfigScopeRole] = useState<string>('all');
  const [configScopeSite, setConfigScopeSite] = useState<string>('all');
  const [newUserForm, setNewUserForm] = useState({ username: '', password: '', role: 'Operator' });
  const [isLoading, setIsLoading] = useState(true);
  const currentUserRecord = users.find(u => u.username === currentUser.username);
  const currentUserLastLogin = currentUserRecord?.lastLogin || 'Never';
  const unreadNotifications = notifications.filter(n => !n.read);
  const unreadNotificationCount = notifications.filter(n => !n.read).length;
  const currentAvatar = currentUser.avatar_url || currentUserRecord?.avatar_url || '';
  const automationBridgeState = (location.state as { configAutomationBridge?: {
    source?: string;
    mode?: 'query' | 'config';
    command?: string;
    templateName?: string;
    targetDeviceIds?: string[];
    primaryTargetId?: string;
    variableValues?: Record<string, string>;
  } } | null)?.configAutomationBridge;
  const selectedConfigTemplate = useMemo(
    () => configTemplates.find((template) => template.id === selectedTemplateId) || null,
    [configTemplates, selectedTemplateId]
  );
  const configVariableKeys = useMemo(() => extractVars(editorContent), [editorContent]);
  const configVariableMap = useMemo(
    () => globalVars.reduce((acc, item) => {
      acc[item.key] = String(item.value ?? '');
      return acc;
    }, {} as Record<string, string>),
    [globalVars]
  );
  const configMissingVariables = useMemo(
    () => configVariableKeys.filter((key) => !String(configVariableMap[key] ?? '').trim()),
    [configVariableKeys, configVariableMap]
  );
  const configRenderedPreview = useMemo(
    () => editorContent.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (_, key: string) => configVariableMap[key] ?? `{{ ${key} }}`),
    [editorContent, configVariableMap]
  );
  const configVendorScopedDevices = useMemo(() => {
    const vendor = (selectedConfigTemplate?.vendor || '').trim();
    if (!vendor || vendor.toLowerCase() === 'custom') return devices;
    return devices.filter((device) => getVendorFromPlatform(device.platform).toLowerCase() === vendor.toLowerCase());
  }, [devices, selectedConfigTemplate]);
  const configPlatformOptions = useMemo(
    () => Array.from(new Set(configVendorScopedDevices.map((device) => device.platform).filter(Boolean))).sort(),
    [configVendorScopedDevices]
  );
  const configRoleOptions = useMemo(
    () => Array.from(new Set(configVendorScopedDevices.map((device) => device.role).filter(Boolean))).sort(),
    [configVendorScopedDevices]
  );
  const configSiteOptions = useMemo(
    () => Array.from(new Set(configVendorScopedDevices.map((device) => device.site).filter(Boolean))).sort(),
    [configVendorScopedDevices]
  );
  const configScopedDevices = useMemo(() => configVendorScopedDevices.filter((device) => {
    if (configScopePlatform !== 'all' && device.platform !== configScopePlatform) return false;
    if (configScopeRole !== 'all' && device.role !== configScopeRole) return false;
    if (configScopeSite !== 'all' && device.site !== configScopeSite) return false;
    return true;
  }), [configVendorScopedDevices, configScopePlatform, configScopeRole, configScopeSite]);
  const configScopedOnlineCount = useMemo(
    () => configScopedDevices.filter((device) => device.status === 'online').length,
    [configScopedDevices]
  );
  const configValidationIssues = useMemo(() => {
    const issues: string[] = [];
    if (!selectedConfigTemplate) {
      issues.push(language === 'zh' ? '尚未选择模板资产' : 'No template asset selected');
    }
    if (!editorContent.trim()) {
      issues.push(language === 'zh' ? '模板内容为空' : 'Template content is empty');
    }
    if (configMissingVariables.length > 0) {
      issues.push(
        language === 'zh'
          ? `仍有未赋值变量: ${configMissingVariables.join('、')}`
          : `Missing variable values: ${configMissingVariables.join(', ')}`
      );
    }
    if (configScopedDevices.length === 0) {
      issues.push(language === 'zh' ? '当前发布范围内没有匹配设备' : 'No devices match the current release scope');
    }
    return issues;
  }, [selectedConfigTemplate, editorContent, configMissingVariables, configScopedDevices, language]);
  const configValidationWarnings = useMemo(() => {
    const warnings: string[] = [];
    const offlineCount = configScopedDevices.filter((device) => device.status !== 'online').length;
    if (offlineCount > 0) {
      warnings.push(
        language === 'zh'
          ? `${offlineCount} 台目标设备当前不在线，建议先做连接性确认`
          : `${offlineCount} target devices are not online; verify reachability before release`
      );
    }
    if (configScopedDevices.length > 20) {
      warnings.push(
        language === 'zh'
          ? '当前发布范围较大，建议先小范围灰度'
          : 'Release scope is large; consider a staged rollout first'
      );
    }
    return warnings;
  }, [configScopedDevices, language]);
  const configReadinessScore = useMemo(() => {
    let score = 100;
    if (!editorContent.trim()) score -= 45;
    score -= Math.min(30, configMissingVariables.length * 15);
    if (configScopedDevices.length === 0) score -= 30;
    score -= Math.min(20, configScopedDevices.filter((device) => device.status !== 'online').length * 5);
    return Math.max(0, score);
  }, [editorContent, configMissingVariables, configScopedDevices]);
  const hasQuickTargets = batchMode ? batchDeviceIds.length > 0 : !!selectedDevice;
  const quickMissingRequiredFields = useMemo(() => {
    const vars = quickPlaybookScenario?.variables || [];
    return vars
      .filter((v: any) => v.required && !String(quickPlaybookVars[v.key] ?? '').trim())
      .map((v: any) => (language === 'zh' ? (v.label_zh || v.label || v.key) : (v.label || v.key)));
  }, [quickPlaybookScenario, quickPlaybookVars, language]);
  const customCommandVars = useMemo(() => extractVars(customCommand), [customCommand]);

  useEffect(() => {
    setConfigWorkspaceView('source');
    setConfigScopePlatform('all');
    setConfigScopeRole('all');
    setConfigScopeSite('all');
  }, [selectedTemplateId]);

  useEffect(() => {
    if (!selectedTemplateId) {
      setEditorContent('');
      return;
    }
    const template = configTemplates.find((item) => item.id === selectedTemplateId);
    if (template) {
      setEditorContent(template.content || '');
    }
  }, [selectedTemplateId]);

  useEffect(() => {
    if (activeTab !== 'automation' || automationPage !== 'execute' || !automationBridgeState) return;

    const targetDeviceIds = Array.isArray(automationBridgeState.targetDeviceIds) ? automationBridgeState.targetDeviceIds : [];
    const primaryTargetId = automationBridgeState.primaryTargetId;
    const primaryDevice = devices.find((device) => device.id === primaryTargetId)
      || devices.find((device) => targetDeviceIds.includes(device.id))
      || null;

    setAutomationSearch('');
    setQuickPlaybookScenario(null);
    setQuickPlaybookPreview(null);
    setQuickPlaybookVars({});
    setQuickRiskConfirmed(false);
    setQuickQueryOutput('');
    setQuickQueryLabel('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryMaximized(false);
    setQuickQueryCommands([]);
    setCustomCommand(automationBridgeState.command || '');
    setCustomCommandMode(automationBridgeState.mode === 'query' ? 'query' : 'config');
    setScriptVars(automationBridgeState.variableValues || {});

    if (targetDeviceIds.length > 1) {
      setBatchMode(true);
      setBatchDeviceIds(targetDeviceIds);
      setSelectedDevice(primaryDevice);
    } else {
      setBatchMode(false);
      setBatchDeviceIds([]);
      setSelectedDevice(primaryDevice);
    }

    setShowCustomCommandModal(true);

    navigate('/automation/execute', { replace: true, state: null });
  }, [activeTab, automationPage, automationBridgeState, devices, navigate]);

  const handleLogout = () => {
    localStorage.removeItem('netops_token');
    setShowUserMenu(false);
    setShowNotifications(false);
    setIsAuthenticated(false);
  };

  const handleLanguagePreferenceChange = useCallback((nextLanguage: 'en' | 'zh') => {
    setLanguage(nextLanguage as never);
    if (currentUser.id) {
      const token = localStorage.getItem('netops_token');
      fetch(`/api/users/${currentUser.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
        body: JSON.stringify({ preferred_language: nextLanguage }),
      }).catch(() => {});
    }
  }, [currentUser.id, setLanguage]);

  const handleLogin = async () => {
    if (!loginForm.username.trim() || !loginForm.password.trim()) {
      setLoginError(language === 'zh' ? '请输入用户名和密码' : 'Enter username and password');
      return;
    }

    setIsAuthenticating(true);
    setLoginError(null);
    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: loginForm.username.trim(),
          password: loginForm.password,
        }),
      });
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        setLoginError(data.detail || (language === 'zh' ? '登录失败' : 'Login failed'));
        return;
      }

      localStorage.setItem('netops_token', data.token);
      if (rememberMe) {
        localStorage.setItem('netops_user', data.user?.username || loginForm.username.trim());
        localStorage.setItem('netops_remember', 'true');
      } else {
        localStorage.removeItem('netops_user');
        localStorage.setItem('netops_remember', 'false');
      }

      setCurrentUser(data.user || { username: loginForm.username.trim() });
      setIsAuthenticated(true);
      setLoginForm((prev) => ({ ...prev, password: '' }));
      showToast(language === 'zh' ? '登录成功' : 'Login successful', 'success');
    } catch {
      setLoginError(language === 'zh' ? '连接失败，请稍后重试' : 'Connection failed, please try again later');
    } finally {
      setIsAuthenticating(false);
    }
  };

  const handleAddUser = async () => {
    if (!newUserForm.username.trim() || !newUserForm.password.trim()) {
      showToast(language === 'zh' ? '请填写用户名和密码' : 'Username and password are required', 'error');
      return;
    }

    try {
      const response = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...newUserForm,
          actor_username: currentUser.username || 'admin',
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }

      setUsers((prev) => [...prev, data]);
      setShowAddUserModal(false);
      setNewUserForm({ username: '', password: '', role: 'Operator' });
      setShowNewUserPwd(false);
      showToast(language === 'zh' ? '用户已创建' : 'User created', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `创建用户失败: ${message}` : `Failed to create user: ${message}`, 'error');
    }
  };

  const handleEditUser = async () => {
    if (!editingUser) return;
    if (!editUserForm.username.trim()) {
      showToast(language === 'zh' ? '请输入用户名' : 'Username is required', 'error');
      return;
    }

    try {
      const response = await fetch(`/api/users/${editingUser.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: editUserForm.username.trim(),
          password: editUserForm.password,
          role: editUserForm.role,
          actor_username: currentUser.username || 'admin',
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }

      setUsers((prev) => prev.map((user) => (String(user.id) === String(editingUser.id) ? { ...user, ...data } : user)));
      if (String(currentUser.id) === String(editingUser.id)) {
        setCurrentUser((prev) => ({ ...prev, ...data }));
      }
      setShowEditUserModal(false);
      setEditingUser(null);
      setEditUserForm({ username: '', password: '', role: 'Operator' });
      setShowEditUserPwd(false);
      showToast(language === 'zh' ? '用户已更新' : 'User updated', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `更新用户失败: ${message}` : `Failed to update user: ${message}`, 'error');
    }
  };

  const openProfileModal = () => {
    setProfileForm({
      username: currentUser.username || currentUserRecord?.username || '',
      password: '',
      confirmPassword: '',
    });
    setProfileAvatarPreview(currentAvatar);
    setShowProfilePwd(false);
    setShowNotifications(false);
    setShowUserMenu(false);
    // 加载通知渠道配置
    const savedChannels = currentUserRecord?.notification_channels as any;
    setNotificationChannels({
      feishu:   { webhook_url: savedChannels?.feishu?.webhook_url   || '', enabled: !!savedChannels?.feishu?.enabled   },
      dingtalk: { webhook_url: savedChannels?.dingtalk?.webhook_url || '', enabled: !!savedChannels?.dingtalk?.enabled, secret: savedChannels?.dingtalk?.secret || '' },
      wechat:   { webhook_url: savedChannels?.wechat?.webhook_url   || '', enabled: !!savedChannels?.wechat?.enabled   },
    });
    setNotifyTestLoading('');
    setShowProfileModal(true);
  };

  const handleProfileAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      showToast('Please select an image file', 'error');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      showToast('Image must be 2MB or smaller', 'error');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        setProfileAvatarPreview(reader.result);
      }
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  const markAllNotificationsRead = () => {
    const ids = unreadNotifications.map(n => n.id);
    if (ids.length === 0) return;
    setNotificationReadMap(prev => {
      const next = { ...prev };
      unreadNotifications.forEach(item => { next[item.id] = true; });
      return next;
    });
    setNotifications(prev => prev.map(item => ({ ...item, read: true })));
    markNotificationsAsRead(ids);
  };

  const handleSaveProfile = async () => {
    const profileUserId = currentUser.id ?? currentUserRecord?.id;
    if (!profileUserId) {
      showToast('Unable to identify current user', 'error');
      return;
    }
    if (!profileForm.username.trim()) {
      showToast(t('fillAllFields'), 'error');
      return;
    }
    if (profileForm.password && profileForm.password !== profileForm.confirmPassword) {
      showToast('Passwords do not match', 'error');
      return;
    }

    try {
      const payload: Record<string, any> = {
        username: profileForm.username.trim(),
        role: (currentUserRecord?.role || currentUser.role || 'Operator') as string,
        avatar_url: profileAvatarPreview,
        notification_channels: notificationChannels,
      };
      if (profileForm.password) payload.password = profileForm.password;

      const response = await fetch(`/api/users/${profileUserId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (response.ok) {
        setCurrentUser(prev => ({ ...prev, username: data.username, role: data.role, avatar_url: data.avatar_url || '' }));
        setUsers(prev => prev.map(u => String(u.id) === String(profileUserId) ? { ...u, ...data } : u));
        setShowProfileModal(false);
        showToast('Profile updated', 'success');
      } else {
        showToast(`Error: ${data.detail || data.error}`, 'error');
      }
    } catch (error) {
      showToast('Connection error', 'error');
    }
  };

  useEffect(() => {
    localStorage.setItem('netops_theme_mode', themeMode);
    const next = getResolvedTheme(themeMode);
    setResolvedTheme(next);
    document.documentElement.setAttribute('data-theme', next);
  }, [themeMode]);

  const fetchSharedData = useCallback(async () => {
    try {
      const [jobsRes, scriptsRes, usersRes, templatesRes, varsRes, linksRes] = await Promise.all([
        fetch('/api/jobs'),
        fetch('/api/scripts'),
        fetch('/api/users'),
        fetch('/api/templates'),
        fetch('/api/vars'),
        fetch('/api/topology/links')
      ]);

      if (jobsRes.ok) setJobs(await jobsRes.json());
      if (scriptsRes.ok) setScripts(await scriptsRes.json());
      if (usersRes.ok) setUsers(await usersRes.json());
      if (templatesRes.ok) {
        const tpls = await templatesRes.json();
        setConfigTemplates(tpls);
        if (tpls.length > 0 && !selectedTemplateId) {
          setSelectedTemplateId(tpls[0].id);
        }
      }
      if (varsRes.ok) setGlobalVars(await varsRes.json());
      if (linksRes.ok) setTopologyLinks(await linksRes.json());
      setDashLastRefresh(new Date());
    } catch (error) {
      console.error('Failed to fetch shared data:', error);
    }
  }, [selectedTemplateId]);

  const refreshConfigWorkspace = useCallback(async () => {
    const [templatesRes, varsRes] = await Promise.all([
      fetch('/api/templates'),
      fetch('/api/vars'),
    ]);

    let nextTemplates: ConfigTemplate[] = [];
    if (templatesRes.ok) {
      nextTemplates = await templatesRes.json();
      setConfigTemplates(nextTemplates);
    }

    if (varsRes.ok) {
      setGlobalVars(await varsRes.json());
    }

    const nextSelectedId = nextTemplates.some((template) => template.id === selectedTemplateId)
      ? selectedTemplateId
      : (nextTemplates[0]?.id || '');

    setSelectedTemplateId(nextSelectedId);
    setEditorContent(nextTemplates.find((template) => template.id === nextSelectedId)?.content || '');
  }, [selectedTemplateId]);

  const handleImportVars = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const data = await file.arrayBuffer();
      const workbook = XLSX.read(data, { type: 'array' });
      const worksheet = workbook.Sheets[workbook.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(worksheet, { defval: '' });
      const importedVars = rows
        .map((row) => ({
          key: String(row.key ?? row.Key ?? row.name ?? row.Name ?? '').trim(),
          value: String(row.value ?? row.Value ?? row.val ?? '').trim(),
        }))
        .filter((item) => item.key);

      if (importedVars.length === 0) {
        showToast(language === 'zh' ? '文件中没有可导入的变量' : 'No importable variables found in the file', 'info');
        return;
      }

      const existingByKey = new Map<string, { id?: string; key: string; value: string }>(
        globalVars.map((item) => [item.key, item])
      );
      for (const item of importedVars) {
        const existing = existingByKey.get(item.key);
        const response = await fetch(existing?.id ? `/api/vars/${existing.id}` : '/api/vars', {
          method: existing?.id ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...item,
            actor_username: currentUser.username || 'admin',
            actor_role: currentUser.role || 'Administrator',
          }),
        });

        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || response.statusText);
        }
      }

      await refreshConfigWorkspace();
      showToast(
        language === 'zh' ? `已导入 ${importedVars.length} 个变量` : `Imported ${importedVars.length} variables`,
        'success'
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `导入变量失败: ${message}` : `Failed to import variables: ${message}`, 'error');
    } finally {
      event.target.value = '';
    }
  };

  const handleNewTemplate = () => {
    const templateId = `draft-${Date.now()}`;
    const now = new Date().toISOString().slice(0, 16).replace('T', ' ');
    const nextTemplate: ConfigTemplate = {
      id: templateId,
      name: language === 'zh' ? '未命名模板' : 'Untitled Template',
      type: 'Jinja2',
      category: 'custom',
      vendor: 'Custom',
      content: '',
      lastUsed: now,
    };

    setConfigTemplates((prev) => [nextTemplate, ...prev]);
    setSelectedTemplateId(templateId);
    setEditorContent('');
  };

  const handleAddVar = async () => {
    const key = window.prompt(language === 'zh' ? '输入变量名' : 'Enter variable name', '');
    if (!key || !key.trim()) return;
    const value = window.prompt(language === 'zh' ? '输入变量值' : 'Enter variable value', '');
    if (value === null) return;

    try {
      const response = await fetch('/api/vars', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: key.trim(),
          value,
          actor_username: currentUser.username || 'admin',
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }
      setGlobalVars((prev) => [...prev, data]);
      showToast(language === 'zh' ? '已新增全局变量' : 'Global variable added', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `新增变量失败: ${message}` : `Failed to add variable: ${message}`, 'error');
    }
  };

  const handleDeleteVar = async (id: string) => {
    try {
      const response = await fetch(`/api/vars/${id}`, { method: 'DELETE' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }
      setGlobalVars((prev) => prev.filter((item) => item.id !== id));
      showToast(language === 'zh' ? '已删除全局变量' : 'Global variable deleted', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `删除变量失败: ${message}` : `Failed to delete variable: ${message}`, 'error');
    }
  };

  const handleDiscardChanges = async () => {
    try {
      await refreshConfigWorkspace();
      setConfigWorkspaceView('source');
      showToast(language === 'zh' ? '已恢复到最近保存版本' : 'Reverted to the latest saved version', 'success');
    } catch {
      showToast(language === 'zh' ? '恢复模板失败' : 'Failed to restore template', 'error');
    }
  };

  const handleValidateTemplateWorkspace = () => {
    setConfigWorkspaceView('checks');
    if (configValidationIssues.length > 0) {
      showToast(configValidationIssues[0], 'error');
      return;
    }
    showToast(language === 'zh' ? '发布前检查通过' : 'Preflight checks passed', 'success');
  };

  const handleSaveTemplate = async () => {
    if (!selectedConfigTemplate) {
      showToast(language === 'zh' ? '请先选择模板资产' : 'Select a template asset first', 'error');
      return;
    }

    const payload = {
      ...selectedConfigTemplate,
      content: editorContent,
      lastUsed: new Date().toISOString().slice(0, 16).replace('T', ' '),
      actor_username: currentUser.username || 'admin',
      actor_role: currentUser.role || 'Administrator',
    };

    try {
      const isDraft = selectedConfigTemplate.id.startsWith('draft-');
      const response = await fetch(isDraft ? '/api/templates' : `/api/templates/${selectedConfigTemplate.id}`, {
        method: isDraft ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }
      await refreshConfigWorkspace();
      showToast(language === 'zh' ? '模板已保存' : 'Template saved', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `保存模板失败: ${message}` : `Failed to save template: ${message}`, 'error');
    }
  };

  const handleOpenTemplateDeploy = () => {
    setConfigWorkspaceView('checks');
    if (configValidationIssues.length > 0) {
      showToast(configValidationIssues[0], 'error');
      return;
    }

    const targetDeviceIds = configScopedDevices.map((device) => device.id);
    const primaryTargetId = configScopedDevices.find((device) => device.status === 'online')?.id || configScopedDevices[0]?.id;

    navigate('/automation/execute', {
      state: {
        configAutomationBridge: {
          source: 'configuration',
          mode: 'config',
          command: editorContent,
          templateName: selectedConfigTemplate?.name,
          targetDeviceIds,
          primaryTargetId,
          variableValues: configVariableMap,
        },
      },
    });
  };

  const deviceFetchMode = useMemo<'light' | 'full'>(() => {
    // Keep full payload where deep device fields are actively used.
    if (activeTab === 'inventory') return 'full';
    if (activeTab === 'automation') return 'full';
    if (activeTab === 'config') return 'full';
    if (activeTab === 'topology') return 'full';
    return 'light';
  }, [activeTab]);

  const safeJsonArray = (value: any) => {
    if (Array.isArray(value)) return value;
    if (typeof value !== 'string' || !value.trim()) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const normalizeDeviceRecord = (raw: any): Device => {
    const hostname = typeof raw?.hostname === 'string' && raw.hostname.trim()
      ? raw.hostname
      : (typeof raw?.id === 'string' ? raw.id : 'Unknown');

    return {
      ...raw,
      id: String(raw?.id || ''),
      hostname,
      ip_address: typeof raw?.ip_address === 'string' ? raw.ip_address : '',
      platform: typeof raw?.platform === 'string' ? raw.platform : 'unknown',
      status: (raw?.status === 'online' || raw?.status === 'offline' || raw?.status === 'pending') ? raw.status : 'offline',
      compliance: (raw?.compliance === 'compliant' || raw?.compliance === 'non-compliant' || raw?.compliance === 'unknown') ? raw.compliance : 'unknown',
      role: typeof raw?.role === 'string' ? raw.role : '',
      site: typeof raw?.site === 'string' ? raw.site : '',
      model: typeof raw?.model === 'string' ? raw.model : '',
      version: typeof raw?.version === 'string' ? raw.version : '',
      sn: typeof raw?.sn === 'string' ? raw.sn : '',
      uptime: typeof raw?.uptime === 'string' ? raw.uptime : '',
      connection_method: raw?.connection_method === 'netconf' ? 'netconf' : 'ssh',
      config_history: safeJsonArray(raw?.config_history),
      interface_data: safeJsonArray(raw?.interface_data),
      cpu_history: safeJsonArray(raw?.cpu_history),
      memory_history: safeJsonArray(raw?.memory_history),
      health_status: ['healthy', 'warning', 'critical', 'unknown'].includes(String(raw?.health_status)) ? raw.health_status : 'unknown',
      health_score: typeof raw?.health_score === 'number' ? raw.health_score : Number(raw?.health_score || 0),
      health_summary: typeof raw?.health_summary === 'string' ? raw.health_summary : '',
      health_reasons: Array.isArray(raw?.health_reasons) ? raw.health_reasons : [],
      open_alert_count: typeof raw?.open_alert_count === 'number' ? raw.open_alert_count : Number(raw?.open_alert_count || 0),
      critical_open_alerts: typeof raw?.critical_open_alerts === 'number' ? raw.critical_open_alerts : Number(raw?.critical_open_alerts || 0),
      major_open_alerts: typeof raw?.major_open_alerts === 'number' ? raw.major_open_alerts : Number(raw?.major_open_alerts || 0),
      warning_open_alerts: typeof raw?.warning_open_alerts === 'number' ? raw.warning_open_alerts : Number(raw?.warning_open_alerts || 0),
      interface_down_count: typeof raw?.interface_down_count === 'number' ? raw.interface_down_count : Number(raw?.interface_down_count || 0),
      interface_flap_count: typeof raw?.interface_flap_count === 'number' ? raw.interface_flap_count : Number(raw?.interface_flap_count || 0),
      high_util_interface_count: typeof raw?.high_util_interface_count === 'number' ? raw.high_util_interface_count : Number(raw?.high_util_interface_count || 0),
      interface_error_count: typeof raw?.interface_error_count === 'number' ? raw.interface_error_count : Number(raw?.interface_error_count || 0),
    } as Device;
  };

  const fetchDevicesData = useCallback(async () => {
    try {
      const params = new URLSearchParams({ mode: deviceFetchMode });
      const devicesRes = await fetch(`/api/devices?${params.toString()}`);
      if (!devicesRes.ok) return;
      const devs = await devicesRes.json();
      setDevices((Array.isArray(devs) ? devs : []).map((d: any) => {
        const normalized = normalizeDeviceRecord(d);
        if (deviceFetchMode === 'light') {
          return {
            ...normalized,
            config_history: [],
          };
        }
        return normalized;
      }));
      setDevicesLastUpdatedAt(Date.now());
    } catch (error) {
      console.error('Failed to fetch devices data:', error);
    }
  }, [deviceFetchMode]);

  useEffect(() => {
    if (!isAuthenticated) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    Promise.all([fetchSharedData(), fetchDevicesData()]).finally(() => setIsLoading(false));

    const sharedInterval = setInterval(fetchSharedData, 5000);
    // Reduce heavy full device refresh pressure while inventory table uses server-side paging.
    const devicePollMs = activeTab === 'inventory' && inventorySubPage === 'devices'
      ? 30000
      : activeTab === 'inventory' && inventorySubPage === 'interfaces'
        ? 5000
        : 15000;
    const devicesInterval = setInterval(fetchDevicesData, devicePollMs);

    return () => {
      clearInterval(sharedInterval);
      clearInterval(devicesInterval);
    };
  }, [isAuthenticated, fetchSharedData, fetchDevicesData, activeTab, inventorySubPage]);

  // Force refresh when switching between submenus so returning pages always show latest data.
  useEffect(() => {
    if (!isAuthenticated) return;
    fetchSharedData();
    if (!(activeTab === 'inventory' && inventorySubPage === 'devices')) {
      fetchDevicesData();
    }
  }, [isAuthenticated, location.pathname, fetchSharedData, fetchDevicesData, activeTab, inventorySubPage]);

  // 合规趋势：基于过去N天任务执行成功率
  const complianceTrend = useMemo(() => {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return Array.from({ length: trendDays }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (trendDays - 1 - i));
      const dateStr = d.toISOString().slice(0, 10);
      const dayJobs = jobs.filter(j => j.created_at && j.created_at.startsWith(dateStr));
      let rate: number;
      if (dayJobs.length === 0) {
        const total = devices.length;
        rate = total > 0 ? Math.round((devices.filter(dv => dv.compliance === 'compliant').length / total) * 100) : 100;
      } else {
        const success = dayJobs.filter(j => j.status === 'success').length;
        rate = Math.round((success / dayJobs.length) * 100);
      }
      const label = trendDays <= 7 ? days[d.getDay()] : `${months[d.getMonth()]} ${d.getDate()}`;
      return { name: label, rate };
    });
  }, [jobs, devices, trendDays]);

  // 平台分布：基于真实设备数据
  const platformData = useMemo(() => {
    const PLATFORM_COLORS: Record<string, string> = {
      cisco_ios: '#0ea5e9',
      cisco_nxos: '#0369a1',
      cisco_iosxr: '#7c3aed',
      huawei_vrp: '#f59e0b',
      h3c_comware: '#f97316',
      arista_eos: '#6366f1',
      juniper_junos: '#10b981',
    };
    const total = devices.length;
    if (total === 0) return [];
    const counts: Record<string, number> = {};
    devices.forEach(d => { counts[d.platform] = (counts[d.platform] || 0) + 1; });
    return Object.entries(counts).map(([platform, count]) => ({
      name: PLATFORM_LABELS[platform] || platform,
      value: Math.round((count / total) * 100),
      color: PLATFORM_COLORS[platform] || '#94a3b8',
    }));
  }, [devices]);

  const [showDiff, setShowDiff] = useState(false);
  const [currentDiff, setCurrentDiff] = useState({ before: '', after: '' });
  const [showImportModal, setShowImportModal] = useState(false);
  
  // Pagination State
  const [inventoryPage, setInventoryPage] = useState(1);
  const [historyPage, setHistoryPage] = useState(1);
  const [automationListPage, setAutomationListPage] = useState(1);
  const [compliancePage, setCompliancePage] = useState(1);
  const [inventoryPageSize, setInventoryPageSize] = useState(10);
  const [historyPageSize, setHistoryPageSize] = useState(10);
  const [historyStatusFilter, setHistoryStatusFilter] = useState<'all' | Job['status']>('all');
  const [historyTimeFilter, setHistoryTimeFilter] = useState<'all' | '24h' | '7d' | '30d'>('all');
  const [historyRows, setHistoryRows] = useState<Job[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(10);
  const [auditRows, setAuditRows] = useState<AuditEvent[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditCategoryFilter, setAuditCategoryFilter] = useState('all');
  const [auditSeverityFilter, setAuditSeverityFilter] = useState('all');
  const [auditStatusFilter, setAuditStatusFilter] = useState('all');
  const [auditTimeFilter, setAuditTimeFilter] = useState<'all' | '24h' | '7d' | '30d'>('7d');
  const [selectedAuditEvent, setSelectedAuditEvent] = useState<AuditEvent | null>(null);
  const [complianceOverview, setComplianceOverview] = useState<ComplianceOverview | null>(null);
  const [complianceFindings, setComplianceFindings] = useState<ComplianceFinding[]>([]);
  const [complianceFindingTotal, setComplianceFindingTotal] = useState(0);
  const [complianceLoading, setComplianceLoading] = useState(false);
  const [complianceRunLoading, setComplianceRunLoading] = useState(false);
  const [complianceSeverityFilter, setComplianceSeverityFilter] = useState('all');
  const [complianceStatusFilter, setComplianceStatusFilter] = useState('open');
  const [complianceCategoryFilter, setComplianceCategoryFilter] = useState('all');
  const [compliancePageSize, setCompliancePageSize] = useState(10);
  const [complianceRefreshTick, setComplianceRefreshTick] = useState(0);
  const [selectedFinding, setSelectedFinding] = useState<ComplianceFinding | null>(null);
  const [inventoryRows, setInventoryRows] = useState<Device[]>([]);
  const [inventoryTotal, setInventoryTotal] = useState(0);
  const [inventoryLoading, setInventoryLoading] = useState(false);
  const [inventoryRefreshTick, setInventoryRefreshTick] = useState(0);
  const [devicesLastUpdatedAt, setDevicesLastUpdatedAt] = useState<number | null>(null);
  const [hostResources, setHostResources] = useState<HostResourceSnapshot | null>(null);

  // Monitoring Center state (search-first, no full device listing)
  const [monitorSearch, setMonitorSearch] = useState('');
  const [monitorSearchResults, setMonitorSearchResults] = useState<any[]>([]);
  const [monitorSearching, setMonitorSearching] = useState(false);
  const [monitorSelectedDevice, setMonitorSelectedDevice] = useState<any | null>(null);
  const [monitorOverview, setMonitorOverview] = useState<any | null>(null);
  const [monitorRealtime, setMonitorRealtime] = useState<any | null>(null);
  const [monitorTrend, setMonitorTrend] = useState<any | null>(null);
  const [monitorTrendInterface, setMonitorTrendInterface] = useState('');
  const [monitorTrendResolution, setMonitorTrendResolution] = useState<'1m' | '5m'>('1m');
  const [monitorTrendStartInput, setMonitorTrendStartInput] = useState('');
  const [monitorTrendEndInput, setMonitorTrendEndInput] = useState('');
  const [monitorTrendRange, setMonitorTrendRange] = useState<{ start_time?: string; end_time?: string }>({});
  const [monitorTrendZoom, setMonitorTrendZoom] = useState<{ startIndex: number; endIndex: number } | null>(null);
  const [monitorTrendDragStart, setMonitorTrendDragStart] = useState<number | null>(null);
  const [monitorTrendDragEnd, setMonitorTrendDragEnd] = useState<number | null>(null);
  const [monitorTrendMetrics, setMonitorTrendMetrics] = useState<string[]>(['in_bps', 'out_bps']);
  const [monitorTrendUiMode, setMonitorTrendUiMode] = useState<'pro' | 'compact'>(() => {
    const saved = localStorage.getItem('netops_monitor_trend_ui_mode');
    return saved === 'pro' ? 'pro' : 'compact';
  });
  const [monitorAlerts, setMonitorAlerts] = useState<any[]>([]);
  const [monitorAlertTotal, setMonitorAlertTotal] = useState(0);
  const [monitorAlertsPage, setMonitorAlertsPage] = useState(1);
  const [monitorAlertsPageSize] = useState(10);
  const [monitorAlertsSeverity, setMonitorAlertsSeverity] = useState('all');
  const [monitorAlertsPhase, setMonitorAlertsPhase] = useState('all');
  const [monitorLoading, setMonitorLoading] = useState(false);
  const [monitorPageVisible, setMonitorPageVisible] = useState(() => typeof document === 'undefined' ? true : document.visibilityState === 'visible');
  const [monitorDashboardSiteFilter, setMonitorDashboardSiteFilter] = useState('all');
  const [monitorDashboardAlertFilter, setMonitorDashboardAlertFilter] = useState<'all' | 'critical' | 'major' | 'warning'>('all');
  const monitorRequestEpochRef = React.useRef(0);

  const isAbortError = (error: unknown) => {
    if (!error) return false;
    if (error instanceof DOMException && error.name === 'AbortError') return true;
    return typeof error === 'object' && (error as { name?: string }).name === 'AbortError';
  };

  // Inventory Filters & Sorting
  const [inventorySearch, setInventorySearch] = useState('');
  const [inventoryPlatformFilter, setInventoryPlatformFilter] = useState('all');
  const [inventoryRoleFilter, setInventoryRoleFilter] = useState('all');
  const [inventoryStatusFilter, setInventoryStatusFilter] = useState('all');
  const [inventorySortConfig, setInventorySortConfig] = useState<{ key: keyof Device, direction: 'asc' | 'desc' } | null>(null);
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>([]);

  useEffect(() => {
    setInventoryPage(1);
  }, [inventorySearch, inventoryPlatformFilter, inventoryRoleFilter, inventoryStatusFilter, inventoryPageSize]);

  useEffect(() => {
    setSelectedDeviceIds([]);
  }, [inventorySearch, inventoryPlatformFilter, inventoryRoleFilter, inventoryStatusFilter, inventorySortConfig, inventoryPage]);

  useEffect(() => {
    const totalInventoryPages = Math.max(1, Math.ceil(inventoryTotal / inventoryPageSize));
    if (inventoryPage > totalInventoryPages) {
      setInventoryPage(totalInventoryPages);
    }
  }, [inventoryTotal, inventoryPage, inventoryPageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'inventory' || inventorySubPage !== 'devices') return;

    let cancelled = false;
    const fetchInventoryPage = async () => {
      setInventoryLoading(true);
      try {
        const params = new URLSearchParams({
          search: inventorySearch,
          platform: inventoryPlatformFilter,
          role: inventoryRoleFilter,
          status: inventoryStatusFilter,
          page: String(inventoryPage),
          page_size: String(inventoryPageSize),
          sort_key: inventorySortConfig?.key || 'hostname',
          sort_direction: inventorySortConfig?.direction || 'asc',
        });

        const resp = await fetch(`/api/devices?${params.toString()}`);
        if (!resp.ok) throw new Error('Failed to fetch inventory data');
        const data = await resp.json();
        if (cancelled) return;

        if (Array.isArray(data)) {
          setInventoryRows(data.map((item: any) => normalizeDeviceRecord(item)));
          setInventoryTotal(data.length);
        } else {
          setInventoryRows(Array.isArray(data.items) ? data.items.map((item: any) => normalizeDeviceRecord(item)) : []);
          setInventoryTotal(typeof data.total === 'number' ? data.total : 0);
        }
      } catch {
        if (cancelled) return;
        setInventoryRows([]);
        setInventoryTotal(0);
      } finally {
        if (!cancelled) setInventoryLoading(false);
      }
    };

    fetchInventoryPage();
    return () => {
      cancelled = true;
    };
  }, [
    isAuthenticated,
    activeTab,
    inventorySubPage,
    inventorySearch,
    inventoryPlatformFilter,
    inventoryRoleFilter,
    inventoryStatusFilter,
    inventorySortConfig,
    inventoryPage,
    inventoryPageSize,
    inventoryRefreshTick,
  ]);

  const fetchMonitoringOverview = useCallback(async (forceRefresh = false, signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    try {
      const suffix = forceRefresh ? '?force_refresh=1' : '';
      const resp = await fetch(`/api/monitoring/overview${suffix}`, { signal });
      if (!resp.ok) return;
      const payload = await resp.json();
      if (reqEpoch !== monitorRequestEpochRef.current) return;
      setMonitorOverview(payload);
    } catch (error) {
      if (isAbortError(error)) return;
      // ignore transient errors
    }
  }, []);

  const fetchHostResources = useCallback(async (signal?: AbortSignal) => {
    try {
      const resp = await fetch('/api/health/resources', { signal });
      if (!resp.ok) return;
      const payload = await resp.json() as HostResourceSnapshot;
      setHostResources(payload);
    } catch (error) {
      if (isAbortError(error)) return;
      // ignore transient errors
    }
  }, []);

  const fetchMonitoringAlerts = useCallback(async (signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    try {
      const params = new URLSearchParams({
        page: String(monitorAlertsPage),
        page_size: String(monitorAlertsPageSize),
        severity: monitorAlertsSeverity,
        phase: monitorAlertsPhase,
      });
      if (monitorSelectedDevice?.id) params.set('device_id', monitorSelectedDevice.id);
      const resp = await fetch(`/api/monitoring/alerts?${params.toString()}`, { signal });
      if (!resp.ok) return;
      const data = await resp.json();
      if (reqEpoch !== monitorRequestEpochRef.current) return;
      setMonitorAlerts(Array.isArray(data.items) ? data.items : []);
      setMonitorAlertTotal(typeof data.total === 'number' ? data.total : 0);
    } catch (error) {
      if (isAbortError(error)) return;
      // ignore transient errors
    }
  }, [monitorAlertsPage, monitorAlertsPageSize, monitorAlertsSeverity, monitorAlertsPhase, monitorSelectedDevice?.id]);

  const fetchMonitoringRealtime = useCallback(async (deviceId: string, signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    const resp = await fetch(`/api/monitoring/device/${deviceId}/realtime?window_minutes=15&limit=1000`, { signal });
    if (!resp.ok) throw new Error('realtime fetch failed');
    const payload = await resp.json();
    if (reqEpoch !== monitorRequestEpochRef.current) throw new Error('stale monitoring realtime response');
    return payload;
  }, []);

  const fetchMonitoringTrend = useCallback(async (
    deviceId: string,
    interfaceName?: string,
    resolution: '1m' | '5m' = '1m',
    range?: { start_time?: string; end_time?: string },
    signal?: AbortSignal,
  ) => {
    const reqEpoch = monitorRequestEpochRef.current;
    const params = new URLSearchParams({ range_hours: '24', resolution });
    const name = (interfaceName || '').trim();
    if (name) params.set('interface_name', name);
    if (range?.start_time) params.set('start_time', range.start_time);
    if (range?.end_time) params.set('end_time', range.end_time);
    const resp = await fetch(`/api/monitoring/device/${deviceId}/trend?${params.toString()}`, { signal });
    if (!resp.ok) throw new Error('trend fetch failed');
    const payload = await resp.json();
    if (reqEpoch !== monitorRequestEpochRef.current) throw new Error('stale monitoring trend response');
    return payload;
  }, []);

  useEffect(() => {
    monitorRequestEpochRef.current += 1;
    if (activeTab === 'monitoring' || activeTab === 'health') return;
    setMonitorSearch('');
    setMonitorSearchResults([]);
    setMonitorSearching(false);
    setMonitorSelectedDevice(null);
    setMonitorOverview(null);
    setMonitorRealtime(null);
    setMonitorTrend(null);
    setMonitorTrendInterface('');
    setMonitorTrendResolution('1m');
    setMonitorTrendStartInput('');
    setMonitorTrendEndInput('');
    setMonitorTrendRange({});
    setMonitorTrendZoom(null);
    setMonitorTrendDragStart(null);
    setMonitorTrendDragEnd(null);
    setMonitorTrendMetrics(['in_bps', 'out_bps']);
    setMonitorAlerts([]);
    setMonitorAlertTotal(0);
    setMonitorAlertsPage(1);
    setMonitorAlertsSeverity('all');
    setMonitorAlertsPhase('all');
    setMonitorLoading(false);
    setMonitorDashboardSiteFilter('all');
    setMonitorDashboardAlertFilter('all');
  }, [activeTab]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      setMonitorPageVisible(document.visibilityState === 'visible');
    };

    handleVisibilityChange();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    let currentController: AbortController | null = null;
    const runResources = () => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchHostResources(currentController.signal);
    };

    runResources();
    if (!monitorPageVisible) return;
    const timer = window.setInterval(runResources, 15000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, fetchHostResources, monitorPageVisible]);

  useEffect(() => {
    if (!isAuthenticated || !['monitoring', 'health'].includes(activeTab)) return;
    let currentController: AbortController | null = null;
    const runOverview = (forceRefresh = false) => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchMonitoringOverview(forceRefresh, currentController.signal);
    };

    runOverview(true);
    if (!monitorPageVisible) return;
    const timer = window.setInterval(() => runOverview(false), 5000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, activeTab, fetchMonitoringOverview, monitorPageVisible]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring') return;
    let currentController: AbortController | null = null;
    const runAlerts = () => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchMonitoringAlerts(currentController.signal);
    };

    runAlerts();
    if (!monitorPageVisible) return;
    const timer = window.setInterval(runAlerts, 10000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, activeTab, fetchMonitoringAlerts, monitorPageVisible]);

  const formatResourcePercent = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return '--';
    return `${Math.round(value)}%`;
  };

  const formatCompactResourcePercent = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return '--';
    return String(Math.round(value));
  };

  const hostResourceTone = hostResources?.status === 'critical'
    ? 'bg-red-500/15 text-red-200 border-red-400/25'
    : hostResources?.status === 'degraded'
      ? 'bg-amber-500/15 text-amber-100 border-amber-300/25'
      : 'bg-emerald-500/15 text-emerald-100 border-emerald-300/25';

  const hostResourceSummary = hostResources
    ? `CPU ${formatResourcePercent(hostResources.cpu_percent)} · MEM ${formatResourcePercent(hostResources.memory_percent)} · DISK ${formatResourcePercent(hostResources.disk_percent)}`
    : (language === 'zh' ? '等待资源数据' : 'Waiting for resource data');
  const alertNavTone = unreadNotificationCount > 20
    ? 'bg-red-500/15 text-red-200 border-red-400/25'
    : unreadNotificationCount > 0
      ? 'bg-amber-500/15 text-amber-100 border-amber-300/25'
      : 'bg-emerald-500/15 text-emerald-100 border-emerald-300/25';

  const formatTopologyPort = (value?: string) => {
    const raw = String(value || '').trim();
    if (!raw) return language === 'zh' ? '未识别接口' : 'Unknown Port';
    return raw
      .replace(/^GigabitEthernet/i, 'Gi')
      .replace(/^TenGigabitEthernet/i, 'Te')
      .replace(/^TwentyFiveGigE/i, 'Tw')
      .replace(/^FortyGigabitEthernet/i, 'Fo')
      .replace(/^HundredGigabitEthernet/i, 'Hu')
      .replace(/^Ethernet/i, 'Eth')
      .replace(/^Port-channel/i, 'Po')
      .replace(/^Loopback/i, 'Lo');
  };

  const normalizeTopologyPort = (value?: string) => String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/^gigabitethernet/, 'gi')
    .replace(/^tengigabitethernet/, 'te')
    .replace(/^twentyfivegige/, 'tw')
    .replace(/^fortygigabitethernet/, 'fo')
    .replace(/^hundredgigabitethernet/, 'hu')
    .replace(/^ethernet/, 'eth')
    .replace(/^port-channel/, 'po')
    .replace(/^loopback/, 'lo');

  const formatTopologyEvidenceLabel = (value: string) => {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return language === 'zh' ? '未知来源' : 'Unknown Source';
    if (normalized === 'lldp') return 'LLDP';
    if (normalized === 'cdp') return 'CDP';
    if (normalized === 'snmp') return 'SNMP';
    if (normalized === 'arp') return 'ARP';
    if (normalized === 'mac') return 'MAC';
    return normalized.toUpperCase();
  };

  const getTopologyOperationalTone = (state?: TopologyOperationalState) => {
    switch (state) {
      case 'up':
        return {
          badge: 'border-emerald-200 bg-emerald-100 text-emerald-700',
          panel: 'border-emerald-200/70 bg-emerald-50',
          dot: 'bg-emerald-500',
        };
      case 'degraded':
        return {
          badge: 'border-amber-200 bg-amber-100 text-amber-700',
          panel: 'border-amber-200/70 bg-amber-50',
          dot: 'bg-amber-500',
        };
      case 'down':
        return {
          badge: 'border-rose-200 bg-rose-100 text-rose-700',
          panel: 'border-rose-200/70 bg-rose-50',
          dot: 'bg-rose-500',
        };
      case 'stale':
        return {
          badge: 'border-sky-200 bg-sky-100 text-sky-700',
          panel: 'border-sky-200/70 bg-sky-50',
          dot: 'bg-sky-500',
        };
      default:
        return {
          badge: 'border-slate-200 bg-slate-100 text-slate-700',
          panel: 'border-slate-200/70 bg-slate-50',
          dot: 'bg-slate-400',
        };
    }
  };

  const formatTopologyOperationalState = (state?: TopologyOperationalState) => {
    if (language === 'zh') {
      if (state === 'up') return '正常';
      if (state === 'degraded') return '退化';
      if (state === 'down') return '中断';
      if (state === 'stale') return '陈旧';
      return '未知';
    }
    if (state === 'up') return 'Up';
    if (state === 'degraded') return 'Degraded';
    if (state === 'down') return 'Down';
    if (state === 'stale') return 'Stale';
    return 'Unknown';
  };

  const formatTopologyLastSeen = (value?: string) => {
    if (!value) return language === 'zh' ? '未知' : 'Unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return language === 'zh' ? '未知' : 'Unknown';
    return date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false });
  };

  const evaluateTopologyInterfaceSnapshot = (device: Device | null | undefined, port?: string): TopologyInterfaceSnapshot | null => {
    if (!device || !port) return null;
    const normalizedPort = normalizeTopologyPort(port);
    if (!normalizedPort) return null;

    const match = (device.interface_data || []).find((item) => {
      const names = [item?.name, item?.description].map((entry) => normalizeTopologyPort(entry));
      return names.includes(normalizedPort);
    });
    if (!match) return null;

    const maxUtilizationPct = [match.bw_in_pct, match.bw_out_pct]
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
      .reduce<number | null>((current, next) => (current == null ? next : Math.max(current, next)), null);

    const errorCount = Number(match.in_errors || 0) + Number(match.out_errors || 0);
    const discardCount = Number(match.in_discards || 0) + Number(match.out_discards || 0);
    const status = String(match.status || 'unknown').toLowerCase();

    let operationalState: TopologyOperationalState = 'unknown';
    if (status === 'down') {
      operationalState = 'down';
    } else if (match.flapping || errorCount > 0 || discardCount > 0 || (maxUtilizationPct != null && maxUtilizationPct >= 85)) {
      operationalState = 'degraded';
    } else if (status === 'up') {
      operationalState = 'up';
    }

    return {
      name: String(match.name || port),
      status,
      maxUtilizationPct,
      errorCount,
      discardCount,
      flapping: Boolean(match.flapping),
      operationalState,
    };
  };

  const describeTopologyLink = (link: any, sourceDevice?: Device, targetDevice?: Device): TopologyDecoratedLink => {
    const metadata = parseJsonObject(link.metadata_json);
    const metadataProtocols = Array.isArray(metadata.protocols) ? metadata.protocols : [];
    const discoverySources = String(link.discovery_source || '')
      .split('+')
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);
    const evidenceSources = Array.from(new Set([...metadataProtocols, ...discoverySources]));
    const sourceInterfaceSnapshot = evaluateTopologyInterfaceSnapshot(sourceDevice, link.source_port_normalized || link.source_port);
    const targetInterfaceSnapshot = evaluateTopologyInterfaceSnapshot(targetDevice, link.target_port_normalized || link.target_port);
    const sourceDeviceStatus = String(sourceDevice?.status || 'unknown').toLowerCase();
    const targetDeviceStatus = String(targetDevice?.status || 'unknown').toLowerCase();
    const lastSeenTime = link.last_seen ? new Date(link.last_seen).getTime() : NaN;
    const staleThresholdMs = 30 * 60 * 1000;
    const isStale = Number.isFinite(lastSeenTime) && (Date.now() - lastSeenTime > staleThresholdMs);

    let operationalState: TopologyOperationalState = 'unknown';
    let operationalSummary = language === 'zh' ? '缺少接口遥测，链路状态未知。' : 'Link state is unknown because interface telemetry is unavailable.';

    if (link.inferred) {
      operationalState = 'unknown';
      operationalSummary = language === 'zh' ? '这是推断链路，需要等待真实邻居证据确认。' : 'This is an inferred adjacency and needs direct neighbor evidence.';
    } else if (sourceDeviceStatus === 'offline' || targetDeviceStatus === 'offline') {
      operationalState = 'down';
      operationalSummary = language === 'zh' ? '至少一端设备离线，链路视为中断。' : 'At least one endpoint device is offline, so the link is treated as down.';
    } else if (isStale) {
      operationalState = 'stale';
      operationalSummary = language === 'zh' ? '这条链路在最近 30 分钟内没有被新的邻居发现刷新，建议重新触发发现确认当前连通性。' : 'This adjacency has not been refreshed by recent discovery within the last 30 minutes. Run discovery again to confirm current connectivity.';
    } else if (sourceInterfaceSnapshot?.operationalState === 'down' || targetInterfaceSnapshot?.operationalState === 'down') {
      operationalState = 'down';
      operationalSummary = language === 'zh' ? '本端或对端接口处于 down。' : 'One side of the adjacency reports the interface as down.';
    } else if (
      sourceDeviceStatus === 'pending'
      || targetDeviceStatus === 'pending'
      || sourceInterfaceSnapshot?.operationalState === 'degraded'
      || targetInterfaceSnapshot?.operationalState === 'degraded'
    ) {
      operationalState = 'degraded';
      operationalSummary = language === 'zh' ? '链路可达，但接口存在高利用率、抖动或错误计数。' : 'The link is reachable but shows utilization, flapping, or error signals.';
    } else if (
      sourceInterfaceSnapshot?.operationalState === 'up'
      && targetInterfaceSnapshot?.operationalState === 'up'
      && sourceDeviceStatus === 'online'
      && targetDeviceStatus === 'online'
    ) {
      operationalState = 'up';
      operationalSummary = language === 'zh' ? '双端接口均为 up，且未发现明显退化信号。' : 'Both interfaces are up and no degradation signals were detected.';
    }

    return {
      ...link,
      operational_state: operationalState,
      operational_summary: operationalSummary,
      evidence_sources: evidenceSources,
      reverse_confirmed: Boolean(metadata.reverse_seen),
      source_interface_snapshot: sourceInterfaceSnapshot,
      target_interface_snapshot: targetInterfaceSnapshot,
    };
  };

  const formatTopologyInterfaceTelemetry = (snapshot: TopologyInterfaceSnapshot | null) => {
    if (!snapshot) return language === 'zh' ? '暂无接口遥测' : 'No interface telemetry';
    const segments: string[] = [];
    if (snapshot.status) segments.push(snapshot.status.toUpperCase());
    if (snapshot.maxUtilizationPct != null) segments.push(`${language === 'zh' ? '利用率' : 'Util'} ${Math.round(snapshot.maxUtilizationPct)}%`);
    if (snapshot.errorCount > 0) segments.push(`${language === 'zh' ? '错误' : 'Err'} ${snapshot.errorCount}`);
    if (snapshot.discardCount > 0) segments.push(`${language === 'zh' ? '丢弃' : 'Drop'} ${snapshot.discardCount}`);
    if (snapshot.flapping) segments.push(language === 'zh' ? '抖动' : 'Flap');
    return segments.join(' · ') || (language === 'zh' ? '暂无接口遥测' : 'No interface telemetry');
  };

  const topologySiteOptions = useMemo(() => {
    const siteValues: string[] = devices
      .map((device) => String(device.site || '').trim())
      .filter((value): value is string => Boolean(value));
    const uniqueSites: string[] = [...new Set<string>(siteValues)];
    uniqueSites.sort((left: string, right: string) => left.localeCompare(right));
    return uniqueSites;
  }, [devices]);

  const topologyRoleOptions = useMemo(() => {
    const roleValues: string[] = devices
      .map((device) => String(device.role || '').trim())
      .filter((value): value is string => Boolean(value));
    const uniqueRoles: string[] = [...new Set<string>(roleValues)];
    uniqueRoles.sort((left: string, right: string) => left.localeCompare(right));
    return uniqueRoles;
  }, [devices]);

  const topologyVisibleDevices = useMemo(() => {
    const query = topologySearch.trim().toLowerCase();
    return devices.filter((device) => {
      const matchesQuery = !query || [device.hostname, device.ip_address, device.site, device.role].some((value) => String(value || '').toLowerCase().includes(query));
      const matchesStatus = topologyStatusFilter === 'all' || device.status === topologyStatusFilter;
      const matchesRole = topologyRoleFilter === 'all' || String(device.role || '') === topologyRoleFilter;
      const matchesSite = topologySiteFilter === 'all' || String(device.site || '') === topologySiteFilter;
      return matchesQuery && matchesStatus && matchesRole && matchesSite;
    });
  }, [devices, topologyRoleFilter, topologySearch, topologySiteFilter, topologyStatusFilter]);

  const topologyVisibleDeviceIds = useMemo(
    () => new Set(topologyVisibleDevices.map((device) => device.id)),
    [topologyVisibleDevices],
  );

  const topologyVisibleLinks = useMemo(() => {
    const deviceMap = new Map<string, Device>();
    topologyVisibleDevices.forEach((device) => {
      deviceMap.set(device.id, device);
    });
    return topologyLinks
      .filter((link) => topologyVisibleDeviceIds.has(link.source_device_id) && topologyVisibleDeviceIds.has(link.target_device_id))
      .map((link) => describeTopologyLink(link, deviceMap.get(link.source_device_id), deviceMap.get(link.target_device_id)));
  }, [describeTopologyLink, topologyLinks, topologyVisibleDeviceIds, topologyVisibleDevices]);

  const topologyDeviceLinks = useMemo(() => {
    if (!selectedTopologyDeviceId) return [] as any[];
    return topologyVisibleLinks
      .filter((link) => link.source_device_id === selectedTopologyDeviceId || link.target_device_id === selectedTopologyDeviceId)
      .sort((left, right) => {
        const leftPeer = left.source_device_id === selectedTopologyDeviceId ? String(left.target_hostname || '') : String(left.source_hostname || '');
        const rightPeer = right.source_device_id === selectedTopologyDeviceId ? String(right.target_hostname || '') : String(right.source_hostname || '');
        return leftPeer.localeCompare(rightPeer);
      });
  }, [selectedTopologyDeviceId, topologyVisibleLinks]);

  const topologyConnectedDeviceIds = useMemo(() => {
    const connected = new Set<string>();
    topologyVisibleLinks.forEach((link) => {
      if (link.source_device_id) connected.add(link.source_device_id);
      if (link.target_device_id) connected.add(link.target_device_id);
    });
    return connected;
  }, [topologyVisibleLinks]);

  const topologyStats = useMemo(() => ({
    nodeCount: topologyVisibleDevices.length,
    linkCount: topologyVisibleLinks.length,
    siteCount: new Set(topologyVisibleDevices.map((device) => String(device.site || '').trim()).filter(Boolean)).size,
    atRiskCount: topologyVisibleDevices.filter((device) => device.status !== 'online' || device.health_status === 'critical' || (device.open_alert_count || 0) > 0).length,
    orphanCount: topologyVisibleDevices.filter((device) => !topologyConnectedDeviceIds.has(device.id)).length,
  }), [topologyConnectedDeviceIds, topologyVisibleDevices, topologyVisibleLinks.length]);

  const topologyLinkStats = useMemo(() => ({
    up: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'up').length,
    degraded: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'degraded').length,
    down: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'down').length,
    stale: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'stale').length,
    multiSource: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.evidence_sources.length > 1 || link.reverse_confirmed || Number(link.evidence_count || 0) > 1).length,
  }), [topologyVisibleLinks]);

  const selectedTopologyDevice = useMemo(
    () => topologyVisibleDevices.find((device) => device.id === selectedTopologyDeviceId) || null,
    [selectedTopologyDeviceId, topologyVisibleDevices],
  );

  const selectedTopologyLink = useMemo<TopologyDecoratedLink | null>(
    () => topologyVisibleLinks.find((link) => (link.link_key || link.id) === selectedTopologyLinkKey) || null,
    [selectedTopologyLinkKey, topologyVisibleLinks],
  );

  const topologyNeighborIds = useMemo(() => {
    if (!selectedTopologyDeviceId) return new Set<string>();
    const neighbors = new Set<string>();
    topologyVisibleLinks.forEach((link) => {
      if (link.source_device_id === selectedTopologyDeviceId && link.target_device_id) neighbors.add(link.target_device_id);
      if (link.target_device_id === selectedTopologyDeviceId && link.source_device_id) neighbors.add(link.source_device_id);
    });
    return neighbors;
  }, [selectedTopologyDeviceId, topologyVisibleLinks]);

  const topologyNeighborDevices = useMemo(
    () => topologyVisibleDevices.filter((device) => topologyNeighborIds.has(device.id)).sort((left, right) => left.hostname.localeCompare(right.hostname)),
    [topologyNeighborIds, topologyVisibleDevices],
  );

  const topologyOrphanDevices = useMemo(
    () => topologyVisibleDevices.filter((device) => !topologyConnectedDeviceIds.has(device.id)).sort((left, right) => left.hostname.localeCompare(right.hostname)),
    [topologyConnectedDeviceIds, topologyVisibleDevices],
  );

  const topologyPriorityDevices = useMemo(
    () => [...topologyVisibleDevices]
      .sort((left, right) => {
        const leftScore = (left.status !== 'online' ? 100 : 0) + (left.critical_open_alerts || 0) * 10 + (left.open_alert_count || 0);
        const rightScore = (right.status !== 'online' ? 100 : 0) + (right.critical_open_alerts || 0) * 10 + (right.open_alert_count || 0);
        return rightScore - leftScore;
      })
      .slice(0, 5),
    [topologyVisibleDevices],
  );

  useEffect(() => {
    if (topologyVisibleDevices.length === 0) {
      if (selectedTopologyDeviceId !== null) setSelectedTopologyDeviceId(null);
      if (selectedTopologyLinkKey !== null) setSelectedTopologyLinkKey(null);
      return;
    }

    if (!selectedTopologyDeviceId || !topologyVisibleDevices.some((device) => device.id === selectedTopologyDeviceId)) {
      setSelectedTopologyDeviceId(topologyVisibleDevices[0].id);
    }
  }, [selectedTopologyDeviceId, selectedTopologyLinkKey, topologyVisibleDevices]);

  useEffect(() => {
    if (!selectedTopologyDeviceId) {
      if (selectedTopologyLinkKey !== null) setSelectedTopologyLinkKey(null);
      return;
    }

    if (topologyDeviceLinks.length === 0) {
      if (selectedTopologyLinkKey !== null) setSelectedTopologyLinkKey(null);
      return;
    }

    if (!selectedTopologyLinkKey || !topologyDeviceLinks.some((link) => (link.link_key || link.id) === selectedTopologyLinkKey)) {
      setSelectedTopologyLinkKey(topologyDeviceLinks[0].link_key || topologyDeviceLinks[0].id || null);
    }
  }, [selectedTopologyDeviceId, selectedTopologyLinkKey, topologyDeviceLinks]);

  useEffect(() => {
    setMonitorAlertsPage(1);
  }, [monitorAlertsSeverity, monitorAlertsPhase, monitorSelectedDevice?.id]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring') return;
    const q = monitorSearch.trim();
    if (!q) {
      setMonitorSearchResults([]);
      setMonitorSearching(false);
      return;
    }

    let cancelled = false;
    let searchController: AbortController | null = null;
    setMonitorSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        searchController = new AbortController();
        const resp = await fetch(`/api/monitoring/search-devices?q=${encodeURIComponent(q)}&limit=20`, { signal: searchController.signal });
        if (!resp.ok) return;
        const data = await resp.json();
        if (!cancelled) {
          setMonitorSearchResults(Array.isArray(data.items) ? data.items : []);
        }
      } catch (error) {
        if (isAbortError(error)) return;
        if (!cancelled) setMonitorSearchResults([]);
      } finally {
        if (!cancelled) setMonitorSearching(false);
      }
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (searchController) searchController.abort();
    };
  }, [isAuthenticated, activeTab, monitorSearch]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring' || !monitorSelectedDevice?.id) {
      setMonitorRealtime(null);
      setMonitorTrend(null);
      return;
    }

    let cancelled = false;
    let realtimeController: AbortController | null = null;
    let trendController: AbortController | null = null;

    const loadRealtime = async () => {
      if (realtimeController) realtimeController.abort();
      realtimeController = new AbortController();
      return fetchMonitoringRealtime(monitorSelectedDevice.id, realtimeController.signal);
    };

    const loadTrend = async () => {
      if (trendController) trendController.abort();
      trendController = new AbortController();
      return fetchMonitoringTrend(
        monitorSelectedDevice.id,
        monitorTrendInterface,
        monitorTrendResolution,
        monitorTrendRange,
        trendController.signal,
      );
    };

    const load = async () => {
      setMonitorLoading(true);
      try {
        const [rt, tr] = await Promise.all([
          loadRealtime(),
          loadTrend(),
        ]);
        if (!cancelled) {
          setMonitorRealtime(rt);
          setMonitorTrend(tr);
        }
      } catch (error) {
        if (isAbortError(error)) return;
        if (!cancelled) {
          setMonitorRealtime(null);
          setMonitorTrend(null);
        }
      } finally {
        if (!cancelled) setMonitorLoading(false);
      }
    };

    load();
    if (!monitorPageVisible) {
      return () => {
        cancelled = true;
        if (realtimeController) realtimeController.abort();
        if (trendController) trendController.abort();
      };
    }
    const realtimeTimer = window.setInterval(async () => {
      try {
        const rt = await loadRealtime();
        if (!cancelled) setMonitorRealtime(rt);
      } catch (error) {
        if (isAbortError(error)) return;
        // ignore transient errors
      }
    }, 5000);
    const trendTimer = window.setInterval(async () => {
      try {
        const tr = await loadTrend();
        if (!cancelled) setMonitorTrend(tr);
      } catch (error) {
        if (isAbortError(error)) return;
        // ignore transient errors
      }
    }, 60000);

    return () => {
      cancelled = true;
      window.clearInterval(realtimeTimer);
      window.clearInterval(trendTimer);
      if (realtimeController) realtimeController.abort();
      if (trendController) trendController.abort();
    };
  }, [isAuthenticated, activeTab, monitorSelectedDevice?.id, monitorTrendInterface, monitorTrendResolution, monitorTrendRange.start_time, monitorTrendRange.end_time, fetchMonitoringRealtime, fetchMonitoringTrend, monitorPageVisible]);

  useEffect(() => {
    setMonitorTrendInterface('');
    setMonitorTrendStartInput('');
    setMonitorTrendEndInput('');
    setMonitorTrendRange({});
  }, [monitorSelectedDevice?.id]);

  useEffect(() => {
    setMonitorTrendZoom(null);
    setMonitorTrendDragStart(null);
    setMonitorTrendDragEnd(null);
  }, [monitorSelectedDevice?.id, monitorTrendInterface, monitorTrendResolution]);

  useEffect(() => {
    localStorage.setItem('netops_monitor_trend_ui_mode', monitorTrendUiMode);
  }, [monitorTrendUiMode]);

  useEffect(() => {
    setHistoryPage(1);
  }, [historyStatusFilter, historyTimeFilter, historyPageSize]);

  useEffect(() => {
    const totalHistoryPages = Math.max(1, Math.ceil(historyTotal / historyPageSize));
    if (historyPage > totalHistoryPages) {
      setHistoryPage(totalHistoryPages);
    }
  }, [historyTotal, historyPage, historyPageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'history') return;

    let cancelled = false;
    const fetchHistoryPage = async () => {
      setHistoryLoading(true);
      try {
        const params = new URLSearchParams({
          status: historyStatusFilter,
          time_range: historyTimeFilter,
          page: String(historyPage),
          page_size: String(historyPageSize),
        });
        const resp = await fetch(`/api/jobs?${params.toString()}`);
        if (!resp.ok) throw new Error('Failed to fetch history data');

        const data = await resp.json();
        if (cancelled) return;

        if (Array.isArray(data)) {
          setHistoryRows(data);
          setHistoryTotal(data.length);
        } else {
          setHistoryRows(Array.isArray(data.items) ? data.items : []);
          setHistoryTotal(typeof data.total === 'number' ? data.total : 0);
        }
      } catch {
        if (cancelled) return;
        setHistoryRows([]);
        setHistoryTotal(0);
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    };

    fetchHistoryPage();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, activeTab, historyStatusFilter, historyTimeFilter, historyPage, historyPageSize]);

  useEffect(() => {
    setAuditPage(1);
  }, [auditCategoryFilter, auditSeverityFilter, auditStatusFilter, auditTimeFilter, auditPageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'history') return;

    let cancelled = false;
    const loadAuditEvents = async () => {
      setAuditLoading(true);
      try {
        const params = new URLSearchParams({
          category: auditCategoryFilter,
          severity: auditSeverityFilter,
          status: auditStatusFilter,
          time_range: auditTimeFilter,
          page: String(auditPage),
          page_size: String(auditPageSize),
        });
        const resp = await fetch(`/api/audit/events?${params.toString()}`);
        if (!resp.ok) throw new Error('Failed to fetch audit events');
        const data = await resp.json();
        if (cancelled) return;
        setAuditRows(Array.isArray(data.items) ? data.items : []);
        setAuditTotal(typeof data.total === 'number' ? data.total : 0);
      } catch {
        if (cancelled) return;
        setAuditRows([]);
        setAuditTotal(0);
      } finally {
        if (!cancelled) setAuditLoading(false);
      }
    };

    loadAuditEvents();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, activeTab, auditCategoryFilter, auditSeverityFilter, auditStatusFilter, auditTimeFilter, auditPage, auditPageSize]);

  useEffect(() => {
    setCompliancePage(1);
  }, [complianceSeverityFilter, complianceStatusFilter, complianceCategoryFilter, compliancePageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'compliance') return;

    let cancelled = false;
    const loadCompliance = async () => {
      setComplianceLoading(true);
      try {
        const params = new URLSearchParams({
          severity: complianceSeverityFilter,
          status: complianceStatusFilter,
          category: complianceCategoryFilter,
          page: String(compliancePage),
          page_size: String(compliancePageSize),
        });
        const [overviewResp, findingsResp] = await Promise.all([
          fetch('/api/compliance/overview'),
          fetch(`/api/compliance/findings?${params.toString()}`),
        ]);
        if (!overviewResp.ok || !findingsResp.ok) throw new Error('Failed to fetch compliance data');
        const overviewData = await overviewResp.json();
        const findingsData = await findingsResp.json();
        if (cancelled) return;
        setComplianceOverview(overviewData);
        setComplianceFindings(Array.isArray(findingsData.items) ? findingsData.items : []);
        setComplianceFindingTotal(typeof findingsData.total === 'number' ? findingsData.total : 0);
      } catch {
        if (cancelled) return;
        setComplianceOverview(null);
        setComplianceFindings([]);
        setComplianceFindingTotal(0);
      } finally {
        if (!cancelled) setComplianceLoading(false);
      }
    };

    loadCompliance();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, activeTab, complianceSeverityFilter, complianceStatusFilter, complianceCategoryFilter, compliancePage, compliancePageSize, complianceRefreshTick]);

  const runComplianceAudit = async () => {
    setComplianceRunLoading(true);
    try {
      const resp = await fetch('/api/compliance/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showToast(`Compliance audit failed: ${data.detail || resp.statusText}`, 'error');
        return;
      }
      showToast(language === 'zh' ? `审计完成，合规得分 ${data.score}%` : `Audit completed. Score ${data.score}%`, 'success');
      setComplianceRefreshTick((v) => v + 1);
    } catch {
      showToast(language === 'zh' ? '审计执行失败' : 'Compliance audit request failed', 'error');
    } finally {
      setComplianceRunLoading(false);
    }
  };

  const updateComplianceFinding = async (findingId: string, patch: { status?: string; owner?: string; note?: string }) => {
    try {
      const resp = await fetch(`/api/compliance/findings/${findingId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showToast(`Update failed: ${data.detail || resp.statusText}`, 'error');
        return;
      }
      setSelectedFinding(data);
      setComplianceRefreshTick((v) => v + 1);
      showToast(language === 'zh' ? '审计问题已更新' : 'Finding updated', 'success');
    } catch {
      showToast(language === 'zh' ? '更新失败' : 'Update failed', 'error');
    }
  };

  const openAuditEventDetail = async (event: AuditEvent) => {
    try {
      const resp = await fetch(`/api/audit/events/${event.id}`);
      const data = await resp.json().catch(() => event);
      if (!resp.ok) throw new Error('Failed to fetch audit event detail');
      setSelectedAuditEvent(data);
    } catch {
      setSelectedAuditEvent(event);
      showToast(language === 'zh' ? '无法加载完整审计详情，已显示当前记录。' : 'Unable to load full audit details, showing current row.', 'info');
    }
  };

  const openComplianceFindingDetail = async (finding: ComplianceFinding) => {
    try {
      const resp = await fetch(`/api/compliance/findings/${finding.id}`);
      const data = await resp.json().catch(() => finding);
      if (!resp.ok) throw new Error('Failed to fetch compliance finding detail');
      setSelectedFinding(data);
    } catch {
      setSelectedFinding(finding);
      showToast(language === 'zh' ? '无法加载完整问题详情，已显示当前记录。' : 'Unable to load full finding details, showing current row.', 'info');
    }
  };

  const handleSort = (key: keyof Device) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (inventorySortConfig && inventorySortConfig.key === key && inventorySortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setInventorySortConfig({ key, direction });
  };

  const [automationSearch, setAutomationSearch] = useState('');
  const [automationPlatformFilter, setAutomationPlatformFilter] = useState('all');
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [connectionTestDevice, setConnectionTestDevice] = useState<Device | null>(null);
  const [connectionTestMode, setConnectionTestMode] = useState<'quick' | 'deep'>('quick');
  const [connectionTestingDeviceId, setConnectionTestingDeviceId] = useState<string | null>(null);
  const [deviceConnectionChecks, setDeviceConnectionChecks] = useState<Record<string, DeviceConnectionCheckSummary>>({});
  // SNMP test state
  const [snmpTestingId, setSnmpTestingId] = useState<string | null>(null);
  const [snmpSyncingId, setSnmpSyncingId] = useState<string | null>(null);
  const [snmpTestResult, setSnmpTestResult] = useState<any>(null);
  const [showSnmpTestResult, setShowSnmpTestResult] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [viewingConfig, setViewingConfig] = useState<ConfigVersion | null>(null);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [schedulingTask, setSchedulingTask] = useState<string | null>(null);
  const [scheduleForm, setScheduleForm] = useState({
    type: 'once' as 'once' | 'recurring',
    interval: 'daily' as 'daily' | 'weekly' | 'monthly',
    time: '',
    timezone: 'UTC'
  });
  const [showRemediationModal, setShowRemediationModal] = useState(false);
  const [remediatingDevice, setRemediatingDevice] = useState<Device | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [viewingDevice, setViewingDevice] = useState<Device | null>(null);
  const [viewingDeviceAlerts, setViewingDeviceAlerts] = useState<DeviceHealthAlertItem[]>([]);
  const [deviceDetailLoading, setDeviceDetailLoading] = useState(false);
  const [deviceTrendRangeHours, setDeviceTrendRangeHours] = useState(24);
  const [deviceHealthTrend, setDeviceHealthTrend] = useState<DeviceHealthTrendResponse | null>(null);
  const [deviceHealthTrendLoading, setDeviceHealthTrendLoading] = useState(false);
  const [deviceOperationalData, setDeviceOperationalData] = useState<any | null>(null);
  const [deviceOperationalDataLoading, setDeviceOperationalDataLoading] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);
  const [editForm, setEditForm] = useState<Partial<Device>>({});
  const [addForm, setAddForm] = useState<Partial<Device>>({
    hostname: '',
    ip_address: '',
    platform: 'cisco_ios',
    role: 'Access',
    site: '',
    connection_method: 'ssh',
    username: '',
    password: '',
    snmp_community: 'public',
    snmp_port: 161
  });
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deviceToDelete, setDeviceToDelete] = useState<string | null>(null);
  const [isDeletingSelected, setIsDeletingSelected] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const copyTextWithFallback = async (text: string): Promise<boolean> => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // Fall back to legacy copy approach below.
    }

    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', 'true');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '0';
      document.body.appendChild(textarea);
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      const copied = document.execCommand('copy');
      document.body.removeChild(textarea);
      return copied;
    } catch {
      return false;
    }
  };

  const handleShowDetails = (device: Device) => {
    setViewingDevice(device);
    setViewingDeviceAlerts([]);
    setDeviceTrendRangeHours(24);
    setDeviceHealthTrend(null);
    setDeviceOperationalData(null);
    setShowDetailsModal(true);
    setDeviceDetailLoading(true);

    fetch(`/api/device-health/device/${device.id}`)
      .then(async (resp) => {
        if (!resp.ok) throw new Error('Failed to load device health detail');
        const data = await resp.json() as DeviceHealthDetailResponse;
        setViewingDevice(normalizeDeviceRecord(data.device));
        setViewingDeviceAlerts(Array.isArray(data.recent_open_alerts) ? data.recent_open_alerts : []);
      })
      .catch(() => {
        showToast(language === 'zh' ? '无法加载完整健康详情，已显示当前设备快照。' : 'Unable to load full health details, showing the current device snapshot.', 'info');
      })
      .finally(() => setDeviceDetailLoading(false));
  };

  useEffect(() => {
    if (!showDetailsModal || !viewingDevice?.id) return;

    let cancelled = false;
    const loadDeviceTrend = async () => {
      setDeviceHealthTrendLoading(true);
      try {
        const resp = await fetch(`/api/device-health/device/${viewingDevice.id}/trend?range_hours=${deviceTrendRangeHours}`);
        if (!resp.ok) throw new Error('Failed to load device trend');
        const data = await resp.json() as DeviceHealthTrendResponse;
        if (!cancelled) setDeviceHealthTrend(data);
      } catch {
        if (!cancelled) setDeviceHealthTrend(null);
      } finally {
        if (!cancelled) setDeviceHealthTrendLoading(false);
      }
    };

    loadDeviceTrend();
    return () => {
      cancelled = true;
    };
  }, [deviceTrendRangeHours, showDetailsModal, viewingDevice?.id]);

  const loadDeviceOperationalData = async (deviceId: string) => {
    setDeviceOperationalDataLoading(true);
    try {
      const resp = await fetch(`/api/devices/${deviceId}/operational-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          categories: ['interfaces', 'neighbors', 'arp', 'mac_table', 'routing_table', 'bgp', 'ospf'],
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || 'Failed to collect operational data');
      }
      setDeviceOperationalData(data);
      showToast(language === 'zh' ? '已完成设备运行数据采集' : 'Operational data collected', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to collect operational data';
      showToast(language === 'zh' ? `采集失败：${message}` : message, 'error');
    } finally {
      setDeviceOperationalDataLoading(false);
    }
  };

  const handleRemediate = (device: Device) => {
    setRemediatingDevice(device);
    setShowRemediationModal(true);
  };

  const confirmRemediation = () => {
    if (!remediatingDevice) return;
    
    // Create a remediation job
    const newJob: Job = {
      id: String(Date.now()),
      device_id: remediatingDevice.id,
      task_name: 'Auto-Remediation: Golden Config',
      status: 'running',
      created_at: new Date().toISOString(),
    };
    setJobs([newJob, ...jobs]);
    setShowRemediationModal(false);
    setActiveTab('automation');
    setSelectedDevice(remediatingDevice);
    
    // Simulate task completion and compliance update
    setTimeout(() => {
      setJobs(prev => prev.map(j => j.id === newJob.id ? { ...j, status: 'success' } : j));
      setDevices(prev => prev.map(d => d.id === remediatingDevice.id ? { ...d, compliance: 'compliant' } : d));
      
      // Add new config version
      const newVersion: ConfigVersion = {
        id: `v${Date.now()}`,
        timestamp: new Date().toISOString().replace('T', ' ').substring(0, 16),
        content: remediatingDevice.current_config + '\n! Remediated to Golden Config',
        author: 'system',
        description: 'Auto-Remediation'
      };
      setDevices(prev => prev.map(d => {
        if (d.id === remediatingDevice.id) {
          return {
            ...d,
            current_config: newVersion.content,
            config_history: [newVersion, ...d.config_history]
          };
        }
        return d;
      }));
    }, 3000);
  };

  const handleScheduleTask = () => {
    if (!selectedDevice || !schedulingTask) return;
    
    const newTask: ScheduledTask = {
      id: Date.now(),
      device_id: selectedDevice.id,
      task_name: schedulingTask,
      schedule_type: scheduleForm.type,
      interval: scheduleForm.type === 'recurring' ? scheduleForm.interval : undefined,
      scheduled_time: scheduleForm.time,
      timezone: scheduleForm.timezone,
      status: 'active'
    };
    
    setScheduledTasks([...scheduledTasks, newTask]);
    setShowScheduleModal(false);
    setSchedulingTask(null);
    alert(`Task "${schedulingTask}" scheduled successfully.`);
  };

  const handleExportConfig = (device: Device) => {
    if (!device.current_config) return;
    const blob = new Blob([device.current_config], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${device.hostname}_config.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImportConfig = (e: React.ChangeEvent<HTMLInputElement>, device: Device) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const newVersion: ConfigVersion = {
        id: `v${Date.now()}`,
        timestamp: new Date().toISOString().replace('T', ' ').substring(0, 16),
        content: device.current_config || '',
        author: 'admin',
        description: 'Backup before import'
      };
      
      const updatedDevices = devices.map(d => {
        if (d.id === device.id) {
          return {
            ...d,
            current_config: content,
            config_history: [newVersion, ...d.config_history]
          };
        }
        return d;
      });
      setDevices(updatedDevices);
      if (selectedDevice?.id === device.id) {
        setSelectedDevice(updatedDevices.find(d => d.id === device.id) || null);
      }
      alert('Configuration imported successfully.');
    };
    reader.readAsText(file);
  };

  const handleRollbackConfig = async (device: Device, version: ConfigVersion) => {
    const newVersion: ConfigVersion = {
      id: `v${Date.now()}`,
      timestamp: new Date().toISOString().replace('T', ' ').substring(0, 16),
      content: device.current_config || '',
      author: 'admin',
      description: `Rollback to ${version.id}`
    };

    const updatedHistory = [newVersion, ...device.config_history];
    
    try {
      // 1. Execute the rollback on the device
      const execRes = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: device.id,
          command: version.content
        })
      });

      if (!execRes.ok) {
        showToast('Failed to execute rollback on device', 'error');
        return;
      }

      // 2. Persist the new state in the DB
      const dbRes = await fetch(`/api/devices/${device.id}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_config: version.content,
          config_history: updatedHistory
        })
      });

      if (dbRes.ok) {
        const updatedDevice = {
          ...device,
          current_config: version.content,
          config_history: updatedHistory
        };

        setDevices(prev => prev.map(d => d.id === device.id ? updatedDevice : d));
        
        if (selectedDevice?.id === device.id) {
          setSelectedDevice(updatedDevice);
        }
        
        setViewingConfig(null);
        setShowConfigModal(false);
        showToast(`Rolled back to version ${version.id}`, 'success');
      } else {
        showToast('Failed to update configuration history', 'error');
      }
    } catch (error) {
      showToast('Connection error during rollback', 'error');
    }
  };

  const confirmDeleteDevice = async () => {
    if (!deviceToDelete && !isDeletingSelected) return;
    
    if (isDeletingSelected) {
      if (selectedDeviceIds.length === 0) return;
      
      let successCount = 0;
      let failCount = 0;
      
      for (const id of selectedDeviceIds) {
        try {
          const response = await fetch(`/api/devices/${id}`, { method: 'DELETE' });
          if (response.ok) {
            successCount++;
            setDevices(prev => prev.filter(d => d.id !== id));
          } else {
            failCount++;
          }
        } catch (error) {
          failCount++;
        }
      }
      
      setSelectedDeviceIds([]);
      setInventoryRefreshTick((v) => v + 1);
      if (failCount === 0) {
        showToast(`Successfully deleted ${successCount} devices`, 'success');
      } else {
        showToast(`Deleted ${successCount} devices, failed to delete ${failCount} devices`, 'error');
      }
    } else if (deviceToDelete) {
      try {
        const response = await fetch(`/api/devices/${deviceToDelete}`, { method: 'DELETE' });
        if (response.ok) {
          setDevices(prev => prev.filter(d => d.id !== deviceToDelete));
          setSelectedDeviceIds(prev => prev.filter(selectedId => selectedId !== deviceToDelete));
          setInventoryRefreshTick((v) => v + 1);
          showToast('Device deleted successfully', 'success');
        } else {
          const data = await response.json();
          showToast(`Failed to delete device: ${data.error}`, 'error');
        }
      } catch (error) {
        showToast(`Error deleting device: ${error}`, 'error');
      }
    }
    
    setShowDeleteModal(false);
    setDeviceToDelete(null);
    setIsDeletingSelected(false);
  };

  const handleSaveEdit = async () => {
    if (!editingDevice) return;
    try {
      const response = await fetch(`/api/devices/${editingDevice.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm)
      });
      if (response.ok) {
        setDevices(prev => prev.map(d => d.id === editingDevice.id ? { ...d, ...editForm } as Device : d));
        setInventoryRefreshTick((v) => v + 1);
        setShowEditModal(false);
        showToast('Device updated successfully', 'success');
      } else {
        const data = await response.json();
        showToast(`Failed to update device: ${data.detail || data.error || response.statusText}`, 'error');
      }
    } catch (error) {
      showToast(`Error updating device: ${error}`, 'error');
    }
  };

  const handleAddDevice = async () => {
    if (!addForm.hostname || !addForm.ip_address) {
      showToast('Hostname and IP Address are required', 'error');
      return;
    }
    try {
      const response = await fetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(addForm)
      });
      const data = await response.json();
      if (response.ok) {
        setDevices([...devices, data]);
        setInventoryRefreshTick((v) => v + 1);
        setInventoryPage(1);
        setShowAddModal(false);
        setAddForm({
          hostname: '',
          ip_address: '',
          platform: 'cisco_ios',
          role: 'Access',
          site: '',
          connection_method: 'ssh',
          username: '',
          password: '',
          snmp_community: 'public',
          snmp_port: 161
        });
        showToast('Device added successfully', 'success');
      } else {
        showToast(`Failed to add device: ${data.error}`, 'error');
      }
    } catch (error) {
      showToast(`Error adding device: ${error}`, 'error');
    }
  };

  const handleDeleteDevice = (id: string) => {
    setDeviceToDelete(id);
    setIsDeletingSelected(false);
    setShowDeleteModal(true);
  };

  const handleDeleteSelected = () => {
    if (selectedDeviceIds.length === 0) return;
    setIsDeletingSelected(true);
    setDeviceToDelete(null);
    setShowDeleteModal(true);
  };

  const [showTestResult, setShowTestResult] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; output?: string; rawError?: string; errorCode?: string; checkMode?: string; stages?: Array<{ stage: string; ok: boolean; summary: string; detail: string; latency_ms?: number | null }> } | null>(null);

  const handleTestConnection = async (deviceToTest: Device | null = selectedDevice, mode: 'quick' | 'deep' = 'quick') => {
    if (!deviceToTest) return;
    setIsTestingConnection(true);
    setTestResult(null);
    setConnectionTestDevice(deviceToTest);
    setConnectionTestMode(mode);
    setConnectionTestingDeviceId(deviceToTest.id);
    setShowTestResult(true);
    try {
      const response = await fetch('/api/devices/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: deviceToTest.id,
          hostname: deviceToTest.hostname,
          ip_address: deviceToTest.ip_address,
          username: deviceToTest.username,
          password: deviceToTest.password,
          method: deviceToTest.connection_method,
          platform: deviceToTest.platform,
          check_mode: mode,
        })
      });
      const data = await response.json();
      if (response.ok) {
        const stages = Array.isArray(data.stages) ? data.stages : [];
        const summary: DeviceConnectionCheckSummary = {
          status: buildConnectionCheckStatus(true, mode, undefined, stages),
          mode,
          checked_at: new Date().toISOString(),
        };
        setDeviceConnectionChecks((prev) => ({ ...prev, [deviceToTest.id]: summary }));
        setTestResult({ success: true, message: data.message, output: data.output, checkMode: data.check_mode, stages });
      } else {
        const stages = Array.isArray(data.stages) ? data.stages : [];
        const summary: DeviceConnectionCheckSummary = {
          status: buildConnectionCheckStatus(false, mode, data.error_code, stages),
          mode,
          checked_at: new Date().toISOString(),
          error_code: data.error_code,
        };
        setDeviceConnectionChecks((prev) => ({ ...prev, [deviceToTest.id]: summary }));
        setTestResult({
          success: false,
          message: buildConnectionTestMessage(data.detail || data.error, data.error_code),
          output: data.output,
          rawError: data.raw_error,
          errorCode: data.error_code,
          checkMode: data.check_mode,
          stages,
        });
      }
    } catch (error: any) {
      setDeviceConnectionChecks((prev) => ({
        ...prev,
        [deviceToTest.id]: {
          status: 'fail',
          mode,
          checked_at: new Date().toISOString(),
        },
      }));
      setTestResult({ success: false, message: error.message || 'Network error' });
    } finally {
      setIsTestingConnection(false);
      setConnectionTestingDeviceId(null);
    }
  };

  const handleSnmpTest = async (deviceId: string) => {
    setSnmpTestingId(deviceId);
    setSnmpTestResult(null);
    setShowSnmpTestResult(true);
    try {
      const resp = await fetch(`/api/devices/${deviceId}/snmp-test`, { method: 'POST' });
      const data = await resp.json();
      setSnmpTestResult(data);
      // 测试成功且后端已同步数据 → 立刻用返回值更新本地 state，无需等待轮询
      if (data.success && data.synced) {
        setDevices(prev => prev.map(d => {
          if (d.id !== deviceId) return d;
          return {
            ...d,
            ...(data.sys_name   ? { hostname: d.hostname || data.sys_name } : {}),
            ...(data.sys_descr  ? { model: d.model || data.sys_descr.split('\n')[0].slice(0, 80) } : {}),
          };
        }));
        // 触发一次完整刷新，把接口/CPU/内存等新数据也拉回来
        await fetchDevicesData();
      }
    } catch (err: any) {
      setSnmpTestResult({ success: false, error: err.message || 'Network error' });
    } finally {
      setSnmpTestingId(null);
    }
  };

  const handleSnmpSyncNow = async (deviceId: string) => {
    setSnmpSyncingId(deviceId);
    try {
      const resp = await fetch(`/api/devices/${deviceId}/snmp-test`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        showToast(language === 'zh' ? 'SNMP 立即同步失败' : 'SNMP sync failed', 'error');
        return;
      }
      await fetchDevicesData();
      showToast(language === 'zh' ? 'SNMP 信息已更新' : 'SNMP data refreshed', 'success');
    } catch (err) {
      showToast(language === 'zh' ? 'SNMP 立即同步失败' : 'SNMP sync failed', 'error');
    } finally {
      setSnmpSyncingId(null);
    }
  };

  const handleTriggerDiscovery = async () => {
    setTopologyDiscoveryRunning(true);
    try {
      const response = await fetch('/api/topology/discover', { method: 'POST' });
      if (response.ok) {
        showToast(language === 'zh' ? '已启动一次手动拓扑刷新，稍后自动更新链路状态' : 'Manual topology refresh started. Link state will update shortly.', 'success');
        window.setTimeout(async () => {
          try {
            const linksResponse = await fetch('/api/topology/links');
            if (linksResponse.ok) {
              const nextLinks = await linksResponse.json();
              setTopologyLinks(Array.isArray(nextLinks) ? nextLinks : []);
            }
          } catch {
            // Ignore delayed refresh errors. The next shared data refresh will reconcile state.
          }
        }, 2500);
      } else {
        showToast(language === 'zh' ? '拓扑发现启动失败' : 'Failed to start topology discovery', 'error');
      }
    } catch (error) {
      showToast(language === 'zh' ? '连接失败，无法触发拓扑发现' : 'Connection error', 'error');
    } finally {
      setTopologyDiscoveryRunning(false);
    }
  };

  const handleExport = () => {
    // Exclude current_config and config_history for a cleaner export
    const exportData = devices.map(({ current_config, config_history, ...rest }) => rest);
    const worksheet = XLSX.utils.json_to_sheet(exportData);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Inventory");
    XLSX.writeFile(workbook, "network_inventory.xlsx");
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const data = new Uint8Array(event.target?.result as ArrayBuffer);
        const workbook = XLSX.read(data, { type: 'array' });
        const firstSheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[firstSheetName];
        const jsonData = XLSX.utils.sheet_to_json<any>(worksheet);

        if (jsonData && jsonData.length > 0) {
          const existingHostnames = new Set(devices.map(d => d.hostname));
          const existingIps = new Set(devices.map(d => d.ip_address));
          
          const newDevices: Device[] = [];
          let skippedCount = 0;

          jsonData.forEach((item, index) => {
            const hostname = item.hostname || item['Device Info'] || item['主机名'] || `Unknown-${index}`;
            const ip_address = item.ip_address || item['IP Address'] || item['IP地址'] || '0.0.0.0';

            if (existingHostnames.has(hostname) || existingIps.has(ip_address)) {
              skippedCount++;
              return;
            }

            newDevices.push({
              id: String(Date.now() + index),
              hostname,
              ip_address,
              platform: item.platform || item['Platform'] || item['平台'] || 'unknown',
              status: item.status || item['Status'] || item['状态'] || 'pending',
              compliance: item.compliance || item['Compliance'] || item['合规性'] || 'unknown',
              sn: item.sn || item['SN'] || item['序列号'] || '',
              model: item.model || item['Model'] || item['型号'] || '',
              version: item.version || item['Version'] || item['版本'] || '',
              role: item.role || item['Role'] || item['角色'] || '',
              site: item.site || item['Site'] || item['站点'] || '',
              uptime: item.uptime || item['Uptime'] || item['运行时间'] || '0d 0h',
              connection_method: item.connection_method || item['Method'] || item['连接方式'] || 'ssh',
              config_history: []
            });
            
            existingHostnames.add(hostname);
            existingIps.add(ip_address);
          });
          
          if (newDevices.length > 0) {
            fetch('/api/devices/import', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ devices: newDevices })
            })
            .then(res => res.json())
            .then(data => {
              if (data.status === 'success') {
                setDevices(prev => [...prev, ...newDevices]);
                setInventoryRefreshTick((v) => v + 1);
                setInventoryPage(1);
                const msg = t('importSuccess').replace('{{count}}', newDevices.length.toString()) + 
                            (skippedCount > 0 ? t('importSkipped').replace('{{count}}', skippedCount.toString()) : '');
                showToast(msg, 'success');
              } else {
                showToast(`Import failed: ${data.error}`, 'error');
              }
            })
            .catch(err => {
              showToast(`Import error: ${err}`, 'error');
            });
          } else if (skippedCount > 0) {
            showToast(t('importNoNew').replace('{{count}}', skippedCount.toString()), 'info');
          }
        }
      } catch (error) {
        showToast(t('importError'), 'error');
      }
    };
    reader.readAsArrayBuffer(file);
    // Reset input
    e.target.value = '';
  };

  if (authChecking) {
    return (
      <div className="min-h-screen bg-[#00172D] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#00bceb] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    const isDark = resolvedTheme === 'dark';
    return (
      <LoginScreen
        isDark={isDark}
        t={t}
        loginForm={loginForm}
        loginError={loginError}
        showLoginPwd={showLoginPwd}
        rememberMe={rememberMe}
        isAuthenticating={isAuthenticating}
        onUsernameChange={(value) => {
          setLoginForm({ ...loginForm, username: value });
          setLoginError(null);
        }}
        onPasswordChange={(value) => {
          setLoginForm({ ...loginForm, password: value });
          setLoginError(null);
        }}
        onTogglePassword={() => setShowLoginPwd((value) => !value)}
        onRememberMeChange={setRememberMe}
        onSubmit={handleLogin}
      />
    );
  }

  const previewDiff = () => {
    if (!selectedDevice) return;
    
    const currentConfig = selectedDevice.current_config || 'No configuration available.';
    // Simulate a proposed change by adding a VLAN config
    const proposedConfig = currentConfig + '\n\n! Proposed Change\ninterface Vlan100\n description Added by NetOps\n ip address 10.100.0.1 255.255.255.0\n no shutdown\n!';
    
    setCurrentDiff({
      before: currentConfig,
      after: proposedConfig
    });
    setShowDiff(true);
  };

  const runTask = async (taskName: string) => {
    if (!selectedDevice) return false;
    
    setShowDiff(false);
    setIsTestingConnection(true); // Reuse testing state for loading
    
    try {
      let commandPayload = undefined;
      if (taskName === 'Compliance Audit') {
        commandPayload = 'show version';
      } else if (taskName === 'VLAN Update') {
        commandPayload = 'system-view\nvlan 100\ndescription Added by NetOps\nquit\ninterface Vlan-interface100\nip address 10.100.0.1 255.255.255.0\nquit';
      } else if (taskName === 'Custom Command') {
        commandPayload = customCommand;
      }

      const response = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: selectedDevice.id,
          script_id: (taskName === 'VLAN Update' || taskName === 'Compliance Audit' || taskName === 'Custom Command') 
            ? undefined 
            : (selectedScript?.id || selectedAutomationTemplate?.id),
          command: (taskName === 'VLAN Update' || taskName === 'Compliance Audit' || taskName === 'Custom Command') ? commandPayload : editedScriptContent,
          // Custom Command 的 isConfig 由后端按命令内容自动判断，前端不强制设定
          isConfig: taskName === 'VLAN Update'
            ? true
            : taskName === 'Custom Command'
              ? customCommandMode === 'config'
              : (!!selectedScript || !!selectedAutomationTemplate),
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        })
      });
      
      const data = await response.json();
      if (response.ok) {
        showToast(`Task "${taskName}" completed on ${selectedDevice.hostname}`, 'success');
        // 执行成功后清空 Custom Command 输入框
        if (taskName === 'Custom Command') setCustomCommand('');
        // Fetch updated jobs
        const jobsRes = await fetch('/api/jobs');
        if (jobsRes.ok) {
          const updatedJobs = await jobsRes.json();
          setJobs(updatedJobs);
          // Automatically show the output of the new job
          const newJob = updatedJobs.find((j: any) => j.id === data.jobId);
          if (newJob) setSelectedJob(newJob);
        }
        return true;
      } else {
        showToast(`Task failed: ${data.error}`, 'error');
        return false;
      }
    } catch (error) {
      showToast(`Execution error: ${error}`, 'error');
      return false;
    } finally {
      setIsTestingConnection(false);
    }
  };

  const formatQuickQueryRawOutput = (payload: any, language: string) => {
    const category = Array.isArray(payload?.categories) ? payload.categories[0] : null;
    if (!category) {
      return language === 'zh' ? '没有返回可展示的数据。' : 'No displayable data returned.';
    }

    if (category?.error) {
      return `Error: ${category.error}`;
    }

    const rawOutputs = Array.isArray(category?.raw_outputs) ? category.raw_outputs : [];
    if (rawOutputs.length > 0) {
      const lines: string[] = [];
      for (const item of rawOutputs) {
        lines.push(`[${item.command}]`);
        lines.push(String(item.output || ''));
        lines.push('');
      }
      return lines.join('\n').trim();
    }

    return language === 'zh' ? '命令已执行，但没有返回原始回显。' : 'Command executed, but no raw output was returned.';
  };

  const sanitizeExportName = (value: string, fallback: string) => {
    const normalized = String(value || fallback)
      .trim()
      .replace(/[<>:"/\\|?*\x00-\x1F]/g, '-')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
    return normalized || fallback;
  };

  const getQuickQueryCommands = (payload: any, fallbackCommands?: string): string[] => {
    const category = Array.isArray(payload?.categories) ? payload.categories[0] : null;
    const payloadCommands = Array.isArray(category?.commands)
      ? category.commands.map((command: any) => String(command || '').trim()).filter(Boolean)
      : [];
    if (payloadCommands.length > 0) {
      return payloadCommands;
    }
    return String(fallbackCommands || '')
      .split('\n')
      .map((command) => command.trim())
      .filter(Boolean);
  };

  const getQuickQueryStructuredTable = (payload: any): {
    category: any;
    records: Record<string, any>[];
    columns: string[];
  } => {
    const category = Array.isArray(payload?.categories) ? payload.categories[0] : null;
    const records: Record<string, any>[] = Array.isArray(category?.records) ? category.records : [];
    const columnSet = new Set<string>();
    records.forEach((item) => {
      Object.keys(item || {}).forEach((key) => columnSet.add(key));
    });
    const columns: string[] = Array.from(columnSet.values());
    return { category, records, columns };
  };

  const quickQueryTable = getQuickQueryStructuredTable(quickQueryStructured);

  const exportQuickQueryTable = (commands: string[]) => {
    if (!quickQueryTable.records.length) {
      showToast(language === 'zh' ? '当前没有可导出的表格记录' : 'No structured records to export', 'error');
      return;
    }

    const dataSheet = XLSX.utils.json_to_sheet(quickQueryTable.records, { header: quickQueryTable.columns });
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, dataSheet, 'Data');

    const metaRows = [
      { key: language === 'zh' ? '查询名称' : 'Query', value: quickQueryLabel },
      { key: language === 'zh' ? '设备' : 'Device', value: quickQueryStructured?.device?.hostname || '' },
      { key: language === 'zh' ? '平台' : 'Platform', value: quickQueryStructured?.device?.platform || '' },
      { key: language === 'zh' ? '采集时间' : 'Collected At', value: quickQueryStructured?.collected_at || '' },
      { key: language === 'zh' ? '解析器' : 'Parser', value: quickQueryTable.category?.parser || 'ntc-templates' },
      { key: language === 'zh' ? '记录数' : 'Records', value: String(quickQueryTable.records.length) },
      { key: language === 'zh' ? '实际执行命令' : 'Executed Commands', value: commands.join('\n') },
    ];
    const metaSheet = XLSX.utils.json_to_sheet(metaRows);
    XLSX.utils.book_append_sheet(workbook, metaSheet, 'Meta');

    const deviceName = sanitizeExportName(quickQueryStructured?.device?.hostname || 'device', 'device');
    const queryName = sanitizeExportName(quickQueryLabel || 'quick-query', 'quick-query');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    XLSX.writeFile(workbook, `${deviceName}_${queryName}_${timestamp}.xlsx`);
    showToast(language === 'zh' ? '已导出 Excel' : 'Excel exported', 'success');
  };

  // Quick query — read-only command, no history saved
  const runQuickQuery = async (label: string, commands: string, operationalCategory?: string) => {
    const device = selectedDevice || (batchMode && batchDeviceIds.length === 1 ? devices.find(d => d.id === batchDeviceIds[0]) : null);
    if (!device) {
      showToast(language === 'zh' ? '请先选择一台设备' : 'Select a device first', 'error');
      return;
    }
    const fallbackCommands = commands
      .split('\n')
      .map((command) => command.trim())
      .filter(Boolean);
    setQuickQueryLabel(label);
    setQuickQueryOutput('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryCommands(fallbackCommands);
    setQuickQueryRunning(true);
    try {
      if (operationalCategory) {
        const resp = await fetch(`/api/devices/${device.id}/operational-data`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ categories: [operationalCategory] }),
        });
        const data = await resp.json();
        if (resp.ok) {
          const firstCategory = Array.isArray(data?.categories) ? data.categories[0] : null;
          const hasStructuredRecords = Array.isArray(firstCategory?.records) && firstCategory.records.length > 0;
          setQuickQueryCommands(getQuickQueryCommands(data, commands));
          setQuickQueryStructured(data);
          setQuickQueryOutput(formatQuickQueryRawOutput(data, language));
          setQuickQueryView(hasStructuredRecords ? 'table' : 'terminal');
        } else {
          setQuickQueryOutput(`Error: ${data.detail || data.error || 'Unknown error'}`);
        }
        return;
      }

      const resp = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: device.id,
          command: commands,
          isConfig: false,
          save_history: false,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setQuickQueryStructured(null);
        setQuickQueryOutput(data.output || 'No output');
      } else {
        setQuickQueryOutput(`Error: ${data.error || data.detail || 'Unknown error'}`);
      }
    } catch (e: any) {
      setQuickQueryOutput(`Error: ${e.message || e}`);
    } finally {
      setQuickQueryRunning(false);
    }
  };

  const handleToggleBatchMode = () => {
    setBatchMode((current) => !current);
    setBatchDeviceIds([]);
  };

  const handleToggleBatchDevice = (deviceId: string) => {
    setBatchDeviceIds((current) => (
      current.includes(deviceId)
        ? current.filter((id) => id !== deviceId)
        : [...current, deviceId]
    ));
  };

  const handleResetQuickQuery = () => {
    setQuickQueryOutput('');
    setQuickQueryLabel('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryMaximized(false);
    setQuickQueryCommands([]);
  };

  const handleSelectAutomationDevice = (device: Device) => {
    if (selectedDevice?.id !== device.id) {
      handleResetQuickQuery();
    }
    setSelectedDevice(device);
  };

  const handleClearQuickScenario = () => {
    setQuickPlaybookScenario(null);
    setQuickPlaybookPreview(null);
    setQuickPlaybookVars({});
    setQuickRiskConfirmed(false);
  };

  const handleResetQuickExecutionState = () => {
    setWsMessages([]);
    setDeviceStatusMap({});
    setWsCompleteMsg(null);
    setQuickExecutionResult(null);
    setExecutionStatus('idle');
    setQuickPlaybookScenario(null);
  };

  const handleSelectPlaybookScenario = (scenario: any) => {
    setSelectedScenario(scenario);
    setPlaybookVars({});
    setPlaybookPreview(null);
    setPlaybookPlatform(scenario.default_platform || scenario.supported_platforms?.[0] || 'cisco_ios');
  };

  const handlePlaybookPlatformChange = (platform: string) => {
    setPlaybookPlatform(platform);
    setPlaybookPreview(null);
  };

  const handlePlaybookVariableChange = (key: string, value: string) => {
    setPlaybookVars((current) => ({ ...current, [key]: value }));
  };

  const handleTogglePlaybookDevice = (deviceId: string) => {
    setPlaybookDeviceIds((current) => (
      current.includes(deviceId)
        ? current.filter((id) => id !== deviceId)
        : [...current, deviceId]
    ));
  };

  const runParsedCustomCommand = async (label: string, command: string) => {
    const device = selectedDevice || (batchMode && batchDeviceIds.length === 1 ? devices.find((item) => item.id === batchDeviceIds[0]) : null);
    if (!device) {
      showToast(language === 'zh' ? '请先选择一台设备' : 'Select a device first', 'error');
      return false;
    }

    const commandList = command
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean);

    setQuickQueryLabel(label);
    setQuickQueryOutput('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryCommands(commandList);
    setQuickQueryRunning(true);

    try {
      const resp = await fetch(`/api/devices/${device.id}/parsed-command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.detail || data.error || (language === 'zh' ? '执行失败' : 'Execution failed'), 'error');
        return false;
      }

      const firstCategory = Array.isArray(data?.categories) ? data.categories[0] : null;
      const hasStructuredRecords = Array.isArray(firstCategory?.records) && firstCategory.records.length > 0;
      setQuickQueryCommands(getQuickQueryCommands(data, command));
      setQuickQueryStructured(data);
      setQuickQueryOutput(formatQuickQueryRawOutput(data, language));
      setQuickQueryView(hasStructuredRecords ? 'table' : 'terminal');
      return true;
    } catch (error: any) {
      showToast(error?.message || String(error), 'error');
      return false;
    } finally {
      setQuickQueryRunning(false);
    }
  };

  const rollback = (jobId: string) => {
    setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'rolled_back' } : j));
  };

  // ---------- Batch execution ----------
  const runBatchTask = async (taskName: string) => {
    const targets = devices.filter(d => batchDeviceIds.includes(d.id));
    if (targets.length === 0) return false;
    setIsBatchRunning(true);
    setBatchResults(targets.map(d => ({ deviceId: d.id, hostname: d.hostname, status: 'pending' })));
    let failedCount = 0;

    for (const device of targets) {
      setBatchResults(prev => prev.map(r => r.deviceId === device.id ? { ...r, status: 'running' } : r));
      try {
        let commandPayload: string | undefined;
        if (taskName === 'Custom Command') commandPayload = applyScriptVars(customCommand);
        else if (taskName === 'Compliance Audit') commandPayload = 'show version';
        else commandPayload = applyScriptVars(editedScriptContent);

        if (dryRun) {
          await new Promise(r => setTimeout(r, 500));
          setBatchResults(prev => prev.map(r => r.deviceId === device.id
            ? { ...r, status: 'success', output: `[DRY-RUN] Would execute on ${device.hostname}:\n${commandPayload}` }
            : r));
          continue;
        }

        const resp = await fetch('/api/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            device_id: device.id,
            command: commandPayload,
            isConfig: taskName === 'Custom Command'
              ? customCommandMode === 'config'
              : taskName !== 'Compliance Audit',
            author: currentUser.username || 'admin',
            actor_id: currentUser.id,
            actor_role: currentUser.role || 'Administrator',
          })
        });
        const data = await resp.json();
        if (!resp.ok) failedCount += 1;
        setBatchResults(prev => prev.map(r => r.deviceId === device.id
          ? { ...r, status: resp.ok ? 'success' : 'failed', output: data.output || data.error }
          : r));
      } catch (e) {
        failedCount += 1;
        setBatchResults(prev => prev.map(r => r.deviceId === device.id
          ? { ...r, status: 'failed', output: String(e) }
          : r));
      }
    }
    const jobsRes = await fetch('/api/jobs');
    if (jobsRes.ok) setJobs(await jobsRes.json());
    setIsBatchRunning(false);
    if (failedCount > 0) {
      showToast(`Batch task "${taskName}" finished with ${failedCount} failure(s)`, 'error');
      return false;
    }
    showToast(`Batch task "${taskName}" completed on ${targets.length} devices`, 'success');
    return true;
  };

  // Apply {{VAR}} substitution to a command/script string
  function applyScriptVars(text: string) {
    return text.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (_, key) => scriptVars[key] ?? `{{${key}}}`);
  }

  // Extract variable names from {{VAR}} in a given text
  function extractVars(text: string): string[] {
    const matches = [...text.matchAll(/\{\{\s*([\w.-]+)\s*\}\}/g)];
    return [...new Set(matches.map(m => m[1]))];
  }

  // Save / remove a command favorite
  const saveFavorite = (cmd: string) => {
    if (!cmd.trim()) return;
    const updated = commandFavorites.includes(cmd) ? commandFavorites.filter(c => c !== cmd) : [cmd, ...commandFavorites].slice(0, 20);
    setCommandFavorites(updated);
    localStorage.setItem('cmdFavorites', JSON.stringify(updated));
  };

  const isFavorited = (cmd: string) => commandFavorites.includes(cmd);

  const closeCustomCommandModal = () => {
    setShowCustomCommandModal(false);
    setShowFavorites(false);
  };

  const submitCustomCommand = async () => {
    const resolvedCommand = applyScriptVars(customCommand).trim();
    if (!resolvedCommand) {
      showToast(language === 'zh' ? '请先输入命令内容' : 'Enter command content first', 'error');
      return;
    }

    const missingVars = customCommandVars.filter((key) => !String(scriptVars[key] ?? '').trim());
    if (missingVars.length > 0) {
      showToast(
        language === 'zh'
          ? `请先填写变量: ${missingVars.join('、')}`
          : `Fill variable values first: ${missingVars.join(', ')}`,
        'error'
      );
      return;
    }

    if (batchMode) {
      if (batchDeviceIds.length === 0) {
        showToast(language === 'zh' ? '请先选择目标设备' : 'Select target devices first', 'error');
        return;
      }
      const ok = await runBatchTask('Custom Command');
      if (ok) closeCustomCommandModal();
      return;
    }

    if (!selectedDevice) {
      showToast(language === 'zh' ? '请先选择目标设备' : 'Select a target device first', 'error');
      return;
    }

    if (customCommandMode === 'query') {
      const ok = await runParsedCustomCommand(language === 'zh' ? '自定义查询' : 'Custom Query', resolvedCommand);
      if (ok) closeCustomCommandModal();
      return;
    }

    const ok = await runTask('Custom Command');
    if (ok) closeCustomCommandModal();
  };

  // ---------- Config Center helpers ----------
  const takeConfigSnapshot = async (device: Device, trigger: ConfigSnapshot['trigger'] = 'manual') => {
    setIsTakingSnapshot(true);
    try {
      // Step 1: fetch live config from device
      let configContent = '% No configuration returned';
      try {
        const _p = (device.platform || '').toLowerCase();
        const _cmd = (_p.includes('cisco') || _p.includes('arista') || _p.includes('rgos'))
          ? 'show running-config'
          : (_p.includes('juniper') || _p.includes('junos'))
            ? 'show configuration'
            : 'display current-configuration';
        const execResp = await fetch('/api/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            device_id: device.id,
            command: _cmd,
            isConfig: false,
            author: currentUser.username || 'admin',
            actor_id: currentUser.id,
            actor_role: currentUser.role || currentUserRecord?.role || 'Administrator',
          })
        });
        if (execResp.ok) {
          const execData = await execResp.json();
          configContent = execData.output || device.current_config || '% No configuration returned';
        } else {
          configContent = device.current_config || '% No configuration available (device offline)';
        }
      } catch {
        configContent = device.current_config || '% Device unreachable';
      }

      // Step 2: persist to backend (filesystem + SQLite)
      const saveResp = await fetch('/api/configs/snapshots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: device.id,
          hostname: device.hostname,
          vendor: getVendorFromPlatform(device.platform),
          content: configContent,
          trigger,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || currentUserRecord?.role || 'Administrator',
        })
      });
      if (saveResp.ok) {
        const snap = await saveResp.json() as ConfigSnapshot;
        // Attach content for immediate display (not returned by list endpoint)
        snap.content = configContent;
        setConfigSnapshots(prev => [snap, ...prev]);
        showToast(`${t('snapshotSaved')} ${device.hostname}`, 'success');
        return snap;
      } else {
        showToast('Failed to persist snapshot', 'error');
      }
    } catch {
      showToast('Snapshot failed', 'error');
    } finally {
      setIsTakingSnapshot(false);
    }
    return null;
  };

  // Load content for a snapshot (lazy, from backend)
  const loadSnapshotContent = async (snap: ConfigSnapshot): Promise<string> => {
    if (snap.content) return snap.content;
    try {
      const resp = await fetch(`/api/configs/snapshots/${snap.id}/content`);
      if (resp.ok) {
        const data = await resp.json();
        return data.content as string;
      }
    } catch { /* ignore */ }
    return '';
  };

  const getSnapshotCompareKey = (snap: ConfigSnapshot | null): string => {
    if (!snap) return '';
    const ip = (snap.ip_address || '').trim();
    if (ip) return `ip:${ip}`;
    // Fallback for historical records without IP metadata.
    return `device:${snap.device_id}`;
  };

  const sameTargetSnapshots = (() => {
    const leftKey = getSnapshotCompareKey(configDiffLeft);
    if (!leftKey) return [] as ConfigSnapshot[];
    return configSnapshots.filter((snap) => {
      if (configDiffLeft && snap.id === configDiffLeft.id) return false;
      return getSnapshotCompareKey(snap) === leftKey;
    });
  })();

  // Delete a snapshot
  const deleteSnapshot = async (snapId: string) => {
    try {
      const resp = await fetch(`/api/configs/snapshots/${snapId}`, { method: 'DELETE' });
      if (resp.ok) {
        setConfigSnapshots(prev => prev.filter(s => s.id !== snapId));
        showToast(t('snapshotDeleted'), 'success');
      }
    } catch { /* ignore */ }
  };

  // Save schedule config
  const saveScheduleConfig = async () => {
    setScheduleLoading(true);
    try {
      const resp = await fetch('/api/configs/schedule', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: scheduleEnabled, hour: scheduleHour, minute: scheduleMinute })
      });
      if (resp.ok) showToast(t('scheduleUpdated'), 'success');
    } catch { /* ignore */ }
    finally { setScheduleLoading(false); }
  };



  // Simple unified diff — returns DiffLine[]
  const computeDiff = (oldText: string, newText: string): DiffLine[] => {
    const oldLines = oldText.replace(/\r\n/g, '\n').split('\n');
    const newLines = newText.replace(/\r\n/g, '\n').split('\n');
    const m = oldLines.length;
    const n = newLines.length;

    // LCS dynamic programming — O(m*n) correctness, handles any offset
    const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        if (oldLines[i - 1] === newLines[j - 1]) {
          dp[i][j] = dp[i - 1][j - 1] + 1;
        } else {
          dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
        }
      }
    }

    // Backtrack through dp table to reconstruct edit operations
    const ops: Array<{ type: 'context' | 'add' | 'remove'; oi?: number; ni?: number }> = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
        ops.push({ type: 'context', oi: i - 1, ni: j - 1 });
        i--; j--;
      } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
        ops.push({ type: 'add', ni: j - 1 });
        j--;
      } else {
        ops.push({ type: 'remove', oi: i - 1 });
        i--;
      }
    }
    ops.reverse();

    return ops.map(op => {
      if (op.type === 'context') return { type: 'context', lineA: op.oi! + 1, lineB: op.ni! + 1, content: oldLines[op.oi!] };
      if (op.type === 'add')     return { type: 'add',     lineB: op.ni! + 1, content: newLines[op.ni!] };
      return                            { type: 'remove',  lineA: op.oi! + 1, content: oldLines[op.oi!] };
    });
  };

  const activeDiffLines: DiffLine[] = configDiffLeft && configDiffRight
    ? computeDiff(configDiffLeft.content || '', configDiffRight.content || '')
    : [];

  const activeChangeLineIndexes: number[] = [];
  activeDiffLines.forEach((line, idx) => {
    if (line.type !== 'context') activeChangeLineIndexes.push(idx);
  });

  const renderedDiffLines = activeDiffLines
    .map((line, originalIndex) => ({ line, originalIndex }))
    .filter((entry) => (diffOnlyChanges ? entry.line.type !== 'context' : true));

  const fullSideBySideRows = activeDiffLines
    .map((line, originalIndex) => {
      if (line.type === 'context') {
        return {
          originalIndex,
          rowType: 'context' as const,
          leftLine: line.lineA || null,
          rightLine: line.lineB || null,
          leftContent: line.content,
          rightContent: line.content,
        };
      }

      if (line.type === 'remove') {
        return {
          originalIndex,
          rowType: 'remove' as const,
          leftLine: line.lineA || null,
          rightLine: null,
          leftContent: line.content,
          rightContent: '',
        };
      }

      return {
        originalIndex,
        rowType: 'add' as const,
        leftLine: null,
        rightLine: line.lineB || null,
        leftContent: '',
        rightContent: line.content,
      };
    })
    .filter((row) => (diffOnlyChanges ? row.rowType !== 'context' : true));

  const diffChangeBlocks: Array<{ startChangeIdx: number; endChangeIdx: number; label: string; searchText: string }> = [];
  if (activeChangeLineIndexes.length > 0) {
    let blockStart = 0;
    for (let i = 1; i < activeChangeLineIndexes.length; i++) {
      const prevLineIndex = activeChangeLineIndexes[i - 1];
      const currentLineIndex = activeChangeLineIndexes[i];
      if (currentLineIndex - prevLineIndex > 8) {
        const startLine = activeDiffLines[activeChangeLineIndexes[blockStart]];
        const labelBase = (startLine?.content || '').trim();
        const searchText = activeChangeLineIndexes
          .slice(blockStart, i)
          .map((idx) => activeDiffLines[idx]?.content || '')
          .join(' ')
          .toLowerCase();
        diffChangeBlocks.push({
          startChangeIdx: blockStart,
          endChangeIdx: i - 1,
          label: labelBase.length > 42 ? `${labelBase.slice(0, 42)}...` : (labelBase || (language === 'zh' ? '变更片段' : 'Change block')),
          searchText,
        });
        blockStart = i;
      }
    }

    const lastLine = activeDiffLines[activeChangeLineIndexes[blockStart]];
    const lastLabelBase = (lastLine?.content || '').trim();
    const lastSearchText = activeChangeLineIndexes
      .slice(blockStart)
      .map((idx) => activeDiffLines[idx]?.content || '')
      .join(' ')
      .toLowerCase();
    diffChangeBlocks.push({
      startChangeIdx: blockStart,
      endChangeIdx: activeChangeLineIndexes.length - 1,
      label: lastLabelBase.length > 42 ? `${lastLabelBase.slice(0, 42)}...` : (lastLabelBase || (language === 'zh' ? '变更片段' : 'Change block')),
      searchText: lastSearchText,
    });
  }

  const q = diffBlockQuery.trim().toLowerCase();
  const filteredDiffChangeBlocks = q
    ? diffChangeBlocks.filter((block) => block.label.toLowerCase().includes(q) || block.searchText.includes(q))
    : diffChangeBlocks;

  const focusDiffChangeAt = (changeIdx: number) => {
    if (activeChangeLineIndexes.length === 0) return;
    const safeIdx = Math.max(0, Math.min(changeIdx, activeChangeLineIndexes.length - 1));
    const targetLine = activeChangeLineIndexes[safeIdx];
    setDiffFocusChangeIdx(safeIdx);
    window.requestAnimationFrame(() => {
      diffLineRefs.current[targetLine]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  };

  const jumpToDiff = (direction: 'prev' | 'next') => {
    const total = activeChangeLineIndexes.length;
    if (total === 0) return;

    setDiffFocusChangeIdx((prev) => {
      const next = direction === 'next'
        ? (prev + 1) % total
        : (prev - 1 + total) % total;
      const targetLine = activeChangeLineIndexes[next];
      window.requestAnimationFrame(() => {
        diffLineRefs.current[targetLine]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      return next;
    });
  };

  const handleSearchConfigSnapshots = async (query = configSnapshotKeyword) => {
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true, q: query });
  };

  const handleClearConfigSnapshotSearch = async () => {
    setConfigSnapshotKeyword('');
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true, q: '' });
  };

  const handleRunBackupAllOnline = async () => {
    const online = devices.filter((device) => device.status === 'online');
    showToast(`${t('backupStarted')} (${online.length} ${t('devicesOnline')})`, 'info');
    for (const device of online) {
      await takeConfigSnapshot(device, 'manual');
    }
    showToast(t('backupComplete'), 'success');
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true });
  };

  const handleCopyConfigContent = async () => {
    const copied = await copyTextWithFallback(configViewContent);
    showToast(copied ? t('configCopied') : (language === 'zh' ? '复制失败' : 'Copy failed'), copied ? 'success' : 'error');
  };

  const handleFetchLiveConfig = async () => {
    if (!configCenterDevice) return;
    const snapshot = await takeConfigSnapshot(configCenterDevice);
    if (snapshot) {
      setConfigViewSnapshot(snapshot);
      setConfigViewContent(snapshot.content || '');
    }
  };

  const handleOpenConfigSnapshot = async (snapshot: ConfigSnapshot) => {
    const content = await loadSnapshotContent(snapshot);
    setConfigViewSnapshot({ ...snapshot, content });
    setConfigViewContent(content);
  };

  const handleOpenConfigDiff = async (snapshot: ConfigSnapshot) => {
    const content = await loadSnapshotContent(snapshot);
    setConfigSnapshotKeyword(snapshot.ip_address || snapshot.hostname || '');
    setConfigDiffLeft({ ...snapshot, content });
    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    setDiffBlockQuery('');
    diffLineRefs.current = {};
    navigate('/config/diff');
  };

  const handleCopyConfigSnapshot = async (snapshot: ConfigSnapshot) => {
    const content = await loadSnapshotContent(snapshot);
    const copied = await copyTextWithFallback(content);
    showToast(copied ? t('configCopied') : (language === 'zh' ? '复制失败' : 'Copy failed'), copied ? 'success' : 'error');
  };

  const handleResetDiffView = () => {
    setConfigDiffLeft(null);
    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    setDiffBlockQuery('');
    diffLineRefs.current = {};
  };

  const handleSelectDiffSnapshot = async (side: 'left' | 'right', snapshotId: string) => {
    const snapshotList = side === 'right' && configDiffLeft ? sameTargetSnapshots : configSnapshots;
    const snapshot = snapshotList.find((item) => item.id === snapshotId) || null;

    if (snapshot) {
      const content = await loadSnapshotContent(snapshot);
      const selected = { ...snapshot, content };

      if (side === 'left') {
        setConfigDiffLeft(selected);
        setDiffFocusChangeIdx(0);
        setDiffBlockQuery('');
        diffLineRefs.current = {};
        if (
          configDiffRight &&
          (configDiffRight.id === selected.id || getSnapshotCompareKey(configDiffRight) !== getSnapshotCompareKey(selected))
        ) {
          setConfigDiffRight(null);
        }
      } else {
        if (configDiffLeft && getSnapshotCompareKey(selected) !== getSnapshotCompareKey(configDiffLeft)) {
          setConfigDiffRight(null);
        } else {
          setConfigDiffRight(selected);
        }
        setDiffFocusChangeIdx(0);
        diffLineRefs.current = {};
      }
      return;
    }

    if (side === 'left') {
      handleResetDiffView();
      return;
    }

    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    diffLineRefs.current = {};
  };

  const handleRunScheduledBackupNow = async () => {
    const online = devices.filter((device) => device.status === 'online');
    showToast(`${t('backupStarted')} (${online.length} ${t('devicesOnline')})`, 'info');
    for (const device of online) {
      await takeConfigSnapshot(device, 'scheduled');
    }
    showToast(t('backupComplete'), 'success');
    await loadConfigSnapshots();
  };

  const handleRefreshHistory = async (
    page = playbookHistoryPage,
    statusFilter = playbookHistoryStatusFilter,
    scenarioFilter = playbookHistoryScenarioSearch,
  ) => {
    await loadPlaybookHistory(page, statusFilter, scenarioFilter);
  };

  const handleSelectExecution = async (execution: any) => {
    setActiveExecutionId(execution.id);
    setSelectedExecutionDetail(null);
    setSelectedExecDevices([]);
    setSelectedExecDevicesTotal(0);
    setSelectedExecDevicesPage(1);
    setSelectedExecDevicesStatusFilter('all');
    setSelectedDeviceDetail(null);

    if (executionStatus === 'running') return;

    if (execution._type === 'job') {
      setSelectedExecutionDetail(execution);
      return;
    }

    setSelectedExecutionLoading(true);
    try {
      const response = await fetch(`/api/playbooks/${execution.id}/summary`);
      if (response.ok) {
        setSelectedExecutionDetail(await response.json());
      }
      await loadExecDevices(execution.id, 1, 'all', '');
    } finally {
      setSelectedExecutionLoading(false);
    }
  };

  const handleDeleteExecution = async (execution: any) => {
    const confirmed = confirm(
      language === 'zh'
        ? `确定删除「${execution.scenario_name}」的执行记录？`
        : `Delete execution "${execution.scenario_name}"?`
    );
    if (!confirmed) return;

    try {
      const response = await fetch(`/api/playbooks/${execution.id}`, { method: 'DELETE' });
      if (!response.ok) {
        showToast(language === 'zh' ? '删除失败' : 'Delete failed', 'error');
        return;
      }
      showToast(language === 'zh' ? '已删除' : 'Deleted', 'success');
      if (activeExecutionId === execution.id) {
        setActiveExecutionId(null);
        setSelectedExecutionDetail(null);
      }
      await loadPlaybookHistory();
    } catch {
      showToast(language === 'zh' ? '删除失败' : 'Delete failed', 'error');
    }
  };

  const handleExecDevicesStatusFilterChange = async (value: string) => {
    setSelectedExecDevicesStatusFilter(value);
    setSelectedExecDevicesPage(1);
    if (!activeExecutionId) return;
    await loadExecDevices(activeExecutionId, 1, value, '');
  };

  const handleExecDevicesPageChange = async (page: number) => {
    setSelectedExecDevicesPage(page);
    if (!activeExecutionId) return;
    await loadExecDevices(activeExecutionId, page, selectedExecDevicesStatusFilter, '');
  };

  const handleSelectExecDevice = async (deviceId: string) => {
    if (!activeExecutionId) return;
    setSelectedDeviceDetailLoading(true);
    setSelectedDeviceDetail(null);
    try {
      const response = await fetch(`/api/playbooks/${activeExecutionId}/devices/${deviceId}`);
      if (response.ok) {
        setSelectedDeviceDetail(await response.json());
      }
    } finally {
      setSelectedDeviceDetailLoading(false);
    }
  };

  // Pagination imported from ./components/Pagination

  // CSS constants and badge helpers imported from ./components/shared

  const lazyPanelFallback = (
    <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-black/5 bg-white/70 text-sm text-black/40">
      {language === 'zh' ? '加载中...' : 'Loading...'}
    </div>
  );

  return (
    <AppRuntimeBoundary language={language}>
      <div className="app-shell flex h-screen text-[#141414] font-sans overflow-hidden">
      <AppSidebar
        activeRoute={activeTab}
        currentPath={location.pathname}
        onNavigate={setActiveTab}
        onNavigatePath={navTo}
        alertCounts={{ monitoring: 0, alertCenter: unreadNotificationCount }}
        isP1Critical={unreadNotificationCount > 20}
        language={language}
        isMobile={isMobile}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(v => !v)}
        onOpenSearch={() => setCmdPaletteOpen(true)}
        t={t}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopHeader
          language={language}
          resolvedTheme={resolvedTheme}
          themeMode={themeMode}
          sidebarCollapsed={sidebarCollapsed}
          pageTitle={pageTitle}
          currentUser={currentUser}
          currentAvatar={currentAvatar}
          currentUserLastLogin={currentUserLastLogin}
          unreadNotificationCount={unreadNotificationCount}
          unreadNotifications={unreadNotifications}
          showNotifications={showNotifications}
          showUserMenu={showUserMenu}
          userMenuRef={userMenuRef}
          renderAvatarContent={renderAvatarContent}
          onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
          onToggleNotifications={() => {
            setShowUserMenu(false);
            setShowNotifications((value) => !value);
          }}
          onToggleUserMenu={() => {
            setShowNotifications(false);
            setShowUserMenu((value) => !value);
          }}
          onOpenProfile={openProfileModal}
          onOpenDashboard={() => {
            setActiveTab('dashboard');
            setShowUserMenu(false);
          }}
          onOpenMonitoring={() => {
            setActiveTab('monitoring');
            setShowUserMenu(false);
          }}
          onOpenHealth={() => {
            setActiveTab('health');
            setShowUserMenu(false);
          }}
          onOpenHistory={() => {
            setActiveTab('history');
            setShowUserMenu(false);
          }}
          onThemeModeChange={setThemeMode}
          onLanguageChange={handleLanguagePreferenceChange}
          onLogout={handleLogout}
          onMarkAllNotificationsRead={markAllNotificationsRead}
          onMarkNotificationRead={(id) => {
            setNotificationReadMap((prev) => ({ ...prev, [id]: true }));
            setNotifications((prev) => prev.map((item) => item.id === id ? { ...item, read: true } : item));
            markNotificationsAsRead([id]);
          }}
        />

        <main className="flex-1 overflow-auto p-4 pb-8 md:p-8 md:pb-16">
          {activeTab === 'dashboard' && (
            <Suspense fallback={lazyPanelFallback}>
              <DashboardTab
                devices={devices}
                jobs={jobs}
                scheduledTasks={scheduledTasks}
                trendDays={trendDays}
                setTrendDays={setTrendDays}
                complianceTrend={complianceTrend}
                platformData={platformData}
                dashBannerCollapsed={dashBannerCollapsed}
                setDashBannerCollapsed={setDashBannerCollapsed}
                dashLastRefresh={dashLastRefresh}
                hostResources={hostResources}
                unreadNotificationCount={unreadNotificationCount}
                notifications={notifications}
                language={language}
                t={t}
                setActiveTab={setActiveTab}
                navigate={navigate}
              />
            </Suspense>
          )}

          {activeTab === 'monitoring' && (
            <Suspense fallback={lazyPanelFallback}>
              <MonitoringCenter
                devices={devices}
                language={language}
                monitorSearch={monitorSearch}
                setMonitorSearch={setMonitorSearch}
                monitorSearchResults={monitorSearchResults}
                monitorSearching={monitorSearching}
                monitorSelectedDevice={monitorSelectedDevice}
                setMonitorSelectedDevice={setMonitorSelectedDevice}
                monitorOverview={monitorOverview}
                monitorRealtime={monitorRealtime}
                monitorTrend={monitorTrend}
                monitorTrendInterface={monitorTrendInterface}
                setMonitorTrendInterface={setMonitorTrendInterface}
                monitorTrendResolution={monitorTrendResolution}
                setMonitorTrendResolution={setMonitorTrendResolution}
                monitorTrendStartInput={monitorTrendStartInput}
                setMonitorTrendStartInput={setMonitorTrendStartInput}
                monitorTrendEndInput={monitorTrendEndInput}
                setMonitorTrendEndInput={setMonitorTrendEndInput}
                monitorTrendRange={monitorTrendRange}
                setMonitorTrendRange={setMonitorTrendRange}
                monitorTrendZoom={monitorTrendZoom}
                setMonitorTrendZoom={setMonitorTrendZoom}
                monitorTrendDragStart={monitorTrendDragStart}
                setMonitorTrendDragStart={setMonitorTrendDragStart}
                monitorTrendDragEnd={monitorTrendDragEnd}
                setMonitorTrendDragEnd={setMonitorTrendDragEnd}
                monitorTrendMetrics={monitorTrendMetrics}
                setMonitorTrendMetrics={setMonitorTrendMetrics}
                monitorTrendUiMode={monitorTrendUiMode}
                setMonitorTrendUiMode={setMonitorTrendUiMode}
                monitorAlerts={monitorAlerts}
                monitorAlertTotal={monitorAlertTotal}
                monitorAlertsPage={monitorAlertsPage}
                setMonitorAlertsPage={setMonitorAlertsPage}
                monitorAlertsPageSize={monitorAlertsPageSize}
                monitorAlertsSeverity={monitorAlertsSeverity}
                setMonitorAlertsSeverity={setMonitorAlertsSeverity}
                monitorAlertsPhase={monitorAlertsPhase}
                setMonitorAlertsPhase={setMonitorAlertsPhase}
                monitorLoading={monitorLoading}
                monitorPageVisible={monitorPageVisible}
                monitorDashboardSiteFilter={monitorDashboardSiteFilter}
                setMonitorDashboardSiteFilter={setMonitorDashboardSiteFilter}
                monitorDashboardAlertFilter={monitorDashboardAlertFilter}
                setMonitorDashboardAlertFilter={setMonitorDashboardAlertFilter}
                hostResources={hostResources}
                fetchMonitoringOverview={() => fetchMonitoringOverview(true)}
                fetchMonitoringAlerts={fetchMonitoringAlerts}
                fetchMonitoringRealtime={fetchMonitoringRealtime}
                fetchHostResources={fetchHostResources}
                setMonitorRealtime={setMonitorRealtime}
                showToast={showToast}
              />
            </Suspense>
          )}

          {activeTab === 'health' && (
            <Suspense fallback={lazyPanelFallback}>
              <DeviceHealthTab
                devices={devices}
                overview={monitorOverview?.device_health_summary || null}
                language={language}
                onShowDetails={handleShowDetails}
                onOpenMonitoring={() => setActiveTab('monitoring')}
              />
            </Suspense>
          )}

          {activeTab === 'alerts' && (
            <Suspense fallback={lazyPanelFallback}>
              <AlertDeskTab
                language={language}
                currentUsername={currentUser.username}
                showToast={showToast}
                activeAlertSection="alerts"
                onNavigateAlertSection={(section) => setActiveTab(section)}
                onOpenMaintenanceForAlert={(alert) => {
                  const params = new URLSearchParams({
                    open: '1',
                    name: alert ? `${alert.hostname || alert.ip_address || 'Alert'} Maintenance` : '',
                    target_ip: alert?.ip_address || '',
                  });
                  navigate(`/maintenance?${params.toString()}`);
                }}
              />
            </Suspense>
          )}

          {activeTab === 'alert-rules' && (
            <Suspense fallback={lazyPanelFallback}>
              <AlertRulesTab
                language={language}
                currentUsername={currentUser.username}
                showToast={showToast}
                activeAlertSection="alert-rules"
                onNavigateAlertSection={(section) => setActiveTab(section)}
              />
            </Suspense>
          )}

          {activeTab === 'maintenance' && (
            <Suspense fallback={lazyPanelFallback}>
              <AlertMaintenanceTab
                language={language}
                currentUsername={currentUser.username}
                showToast={showToast}
                activeAlertSection="maintenance"
                onNavigateAlertSection={(section) => setActiveTab(section)}
              />
            </Suspense>
          )}

          {activeTab === 'inventory' && inventorySubPage === 'devices' && (
            <Suspense fallback={lazyPanelFallback}>
              <InventoryDevicesTab
                inventoryRows={inventoryRows}
                inventoryTotal={inventoryTotal}
                inventoryPage={inventoryPage}
                setInventoryPage={setInventoryPage}
                inventoryPageSize={inventoryPageSize}
                setInventoryPageSize={setInventoryPageSize}
                inventorySearch={inventorySearch}
                setInventorySearch={setInventorySearch}
                inventoryPlatformFilter={inventoryPlatformFilter}
                setInventoryPlatformFilter={setInventoryPlatformFilter}
                inventoryRoleFilter={inventoryRoleFilter}
                setInventoryRoleFilter={setInventoryRoleFilter}
                inventoryStatusFilter={inventoryStatusFilter}
                setInventoryStatusFilter={setInventoryStatusFilter}
                inventorySortConfig={inventorySortConfig}
                inventoryLoading={inventoryLoading}
                selectedDeviceIds={selectedDeviceIds}
                setSelectedDeviceIds={setSelectedDeviceIds}
                handleSort={handleSort}
                handleImport={handleImport}
                handleExport={handleExport}
                handleDeleteDevice={handleDeleteDevice}
                handleDeleteSelected={handleDeleteSelected}
                handleShowDetails={handleShowDetails}
                handleTestConnection={handleTestConnection}
                deviceConnectionChecks={deviceConnectionChecks}
                connectionTestingDeviceId={connectionTestingDeviceId}
                setShowAddModal={setShowAddModal}
                setShowEditModal={setShowEditModal}
                setEditingDevice={setEditingDevice}
                setEditForm={setEditForm}
                setSelectedDevice={setSelectedDevice}
                setActiveTab={setActiveTab}
                language={language}
                t={t}
              />
            </Suspense>
          )}

          {activeTab === 'inventory' && inventorySubPage === 'interfaces' && (
            <Suspense fallback={lazyPanelFallback}>
              <InterfaceMonitoringTab
                devices={devices}
                devicesLastUpdatedAt={devicesLastUpdatedAt}
                language={language}
                snmpTestingId={snmpTestingId}
                snmpSyncingId={snmpSyncingId}
                onSnmpTest={handleSnmpTest}
                onSnmpSyncNow={handleSnmpSyncNow}
              />
            </Suspense>
          )}

          {activeTab === 'topology' && (
            <Suspense fallback={lazyPanelFallback}>
              <TopologyPage
                language={language}
                topologyDiscoveryRunning={topologyDiscoveryRunning}
                topologyStats={topologyStats}
                topologyLinkStats={topologyLinkStats}
                topologySearch={topologySearch}
                topologySiteFilter={topologySiteFilter}
                topologyRoleFilter={topologyRoleFilter}
                topologyStatusFilter={topologyStatusFilter}
                topologySiteOptions={topologySiteOptions}
                topologyRoleOptions={topologyRoleOptions}
                topologyVisibleDevices={topologyVisibleDevices}
                topologyVisibleLinks={topologyVisibleLinks}
                selectedTopologyDeviceId={selectedTopologyDeviceId}
                selectedTopologyLinkKey={selectedTopologyLinkKey}
                selectedTopologyDevice={selectedTopologyDevice}
                selectedTopologyLink={selectedTopologyLink}
                topologyNeighborDevices={topologyNeighborDevices}
                topologyDeviceLinks={topologyDeviceLinks}
                topologyPriorityDevices={topologyPriorityDevices}
                topologyOrphanDevices={topologyOrphanDevices}
                topologyCanvasRef={topologyRef}
                onTriggerDiscovery={handleTriggerDiscovery}
                onExportMap={handleExportMap}
                onTopologySearchChange={setTopologySearch}
                onTopologySiteFilterChange={setTopologySiteFilter}
                onTopologyRoleFilterChange={setTopologyRoleFilter}
                onTopologyStatusFilterChange={setTopologyStatusFilter}
                onSelectTopologyDevice={setSelectedTopologyDeviceId}
                onSelectTopologyLink={setSelectedTopologyLinkKey}
                onOpenDeviceDetail={handleShowDetails}
                onOpenMonitoring={() => navTo('/monitoring')}
                formatTopologyPort={formatTopologyPort}
                formatTopologyInterfaceTelemetry={formatTopologyInterfaceTelemetry}
                formatTopologyLastSeen={formatTopologyLastSeen}
                formatTopologyOperationalState={formatTopologyOperationalState}
                formatTopologyEvidenceLabel={formatTopologyEvidenceLabel}
                getTopologyOperationalTone={getTopologyOperationalTone}
              />
            </Suspense>
          )}

          {activeTab === 'automation' && automationPage === 'execute' && (
            <Suspense fallback={lazyPanelFallback}>
              <AutomationExecuteTab
                t={t}
                language={language}
                sectionHeaderRowClass={sectionHeaderRowClass}
                devices={devices}
                selectedDevice={selectedDevice}
                batchMode={batchMode}
                batchDeviceIds={batchDeviceIds}
                automationSearch={automationSearch}
                scenarioSearch={scenarioSearch}
                filteredScenarios={filteredScenarios}
                quickPlaybookScenario={quickPlaybookScenario}
                quickPlaybookVars={quickPlaybookVars}
                quickPlaybookPlatform={quickPlaybookPlatform}
                quickPlaybookDryRun={quickPlaybookDryRun}
                quickPlaybookConcurrency={quickPlaybookConcurrency}
                quickPlaybookPreview={quickPlaybookPreview}
                quickRiskConfirmed={quickRiskConfirmed}
                hasQuickTargets={hasQuickTargets}
                quickMissingRequiredFields={quickMissingRequiredFields}
                quickHasMixedPlatforms={quickHasMixedPlatforms}
                quickPlatformMismatch={quickPlatformMismatch}
                isQuickPlaybookRunning={isQuickPlaybookRunning}
                quickExecutionResult={quickExecutionResult}
                executionStatus={executionStatus}
                wsCompleteMsg={wsCompleteMsg}
                deviceStatusMap={deviceStatusMap}
                quickQueryRunning={quickQueryRunning}
                quickQueryOutput={quickQueryOutput}
                quickQueryLabel={quickQueryLabel}
                quickQueryStructured={quickQueryStructured}
                quickQueryView={quickQueryView}
                quickQueryMaximized={quickQueryMaximized}
                quickQueryCommands={quickQueryCommands}
                quickQueryTable={quickQueryTable}
                onNavigate={navigate}
                onAutomationSearchChange={setAutomationSearch}
                onScenarioSearchChange={setScenarioSearch}
                onToggleBatchMode={handleToggleBatchMode}
                onToggleBatchDevice={handleToggleBatchDevice}
                onSelectDevice={handleSelectAutomationDevice}
                onOpenCustomCommandModal={() => setShowCustomCommandModal(true)}
                onOpenScenario={openQuickPlaybookModal}
                onClearScenario={handleClearQuickScenario}
                onQuickPlaybookVarChange={(key, value) => setQuickPlaybookVars((current) => ({ ...current, [key]: value }))}
                onQuickPlaybookConcurrencyChange={setQuickPlaybookConcurrency}
                onQuickRiskConfirmedChange={setQuickRiskConfirmed}
                onRunValidation={() => runQuickPlaybook(true)}
                onRunApply={() => runQuickPlaybook(false)}
                onRunQuickQuery={runQuickQuery}
                onResetQuickQuery={handleResetQuickQuery}
                onQuickQueryViewChange={setQuickQueryView}
                onQuickQueryMaximizedChange={setQuickQueryMaximized}
                onOpenCommandPreview={() => setShowCmdPreviewModal(true)}
                onExportQuickQueryTable={exportQuickQueryTable}
                copyTextWithFallback={copyTextWithFallback}
                showToast={showToast}
                onResetExecutionState={handleResetQuickExecutionState}
                getPlatformLabel={getPlatformLabel}
              />
            </Suspense>
          )}
          {activeTab === 'automation' && automationPage === 'playbooks' && (
            <Suspense fallback={lazyPanelFallback}>
              <AutomationPlaybooksTab
                t={t}
                language={language}
                scenarioSearch={scenarioSearch}
                filteredScenarios={filteredScenarios}
                selectedScenario={selectedScenario}
                playbookVars={playbookVars}
                playbookPreview={playbookPreview}
                playbookPlatform={playbookPlatform}
                playbookDeviceIds={playbookDeviceIds}
                playbookConcurrency={playbookConcurrency}
                executionStatus={executionStatus}
                playbookDryRun={playbookDryRun}
                devices={devices}
                platforms={platforms}
                onScenarioSearchChange={setScenarioSearch}
                onSelectScenario={handleSelectPlaybookScenario}
                onPlatformChange={handlePlaybookPlatformChange}
                onVariableChange={handlePlaybookVariableChange}
                onToggleDevice={handleTogglePlaybookDevice}
                onConcurrencyChange={setPlaybookConcurrency}
                onPreview={previewPlaybook}
                onExecuteValidation={() => executePlaybook(true)}
                onExecuteApply={() => executePlaybook(false)}
              />
            </Suspense>
          )}
          {activeTab === 'automation' && automationPage === 'scenarios' && (
            <Suspense fallback={lazyPanelFallback}>
              <AutomationScenariosTab
                t={t}
                language={language}
                scenarioSearch={scenarioSearch}
                filteredScenarios={filteredScenarios}
                platforms={platforms}
                onScenarioSearchChange={setScenarioSearch}
                onOpenManualScenarioDraft={openManualScenarioDraft}
                onUseScenario={(scenario) => {
                  openQuickPlaybookModal(scenario);
                  navigate('/automation/execute');
                }}
              />
            </Suspense>
          )}
          {activeTab === 'automation' && automationPage === 'history' && (
            <Suspense fallback={lazyPanelFallback}>
              <AutomationHistoryTab
                t={t}
                language={language}
                devices={devices}
                playbookExecutions={playbookExecutions}
                playbookHistoryTotal={playbookHistoryTotal}
                playbookHistoryPage={playbookHistoryPage}
                playbookHistoryStatusFilter={playbookHistoryStatusFilter}
                playbookHistoryScenarioSearch={playbookHistoryScenarioSearch}
                activeExecutionId={activeExecutionId}
                executionStatus={executionStatus}
                wsMessages={wsMessages}
                selectedExecutionLoading={selectedExecutionLoading}
                selectedExecutionDetail={selectedExecutionDetail}
                selectedExecDevices={selectedExecDevices}
                selectedExecDevicesTotal={selectedExecDevicesTotal}
                selectedExecDevicesPage={selectedExecDevicesPage}
                selectedExecDevicesStatusFilter={selectedExecDevicesStatusFilter}
                selectedExecDevicesLoading={selectedExecDevicesLoading}
                selectedDeviceDetail={selectedDeviceDetail}
                selectedDeviceDetailLoading={selectedDeviceDetailLoading}
                onRefreshHistory={handleRefreshHistory}
                onScenarioSearchChange={setPlaybookHistoryScenarioSearch}
                onHistoryPageChange={setPlaybookHistoryPage}
                onHistoryStatusFilterChange={setPlaybookHistoryStatusFilter}
                onSelectExecution={handleSelectExecution}
                onDeleteExecution={handleDeleteExecution}
                onExecDevicesStatusFilterChange={handleExecDevicesStatusFilterChange}
                onExecDevicesPageChange={handleExecDevicesPageChange}
                onSelectExecDevice={handleSelectExecDevice}
                onCloseDeviceDetail={() => setSelectedDeviceDetail(null)}
              />
            </Suspense>
          )}
          {activeTab === 'compliance' && (
            <Suspense fallback={lazyPanelFallback}>
              <ComplianceTab
                complianceOverview={complianceOverview}
                complianceFindings={complianceFindings}
                complianceFindingTotal={complianceFindingTotal}
                complianceSeverityFilter={complianceSeverityFilter}
                setComplianceSeverityFilter={setComplianceSeverityFilter}
                complianceStatusFilter={complianceStatusFilter}
                setComplianceStatusFilter={setComplianceStatusFilter}
                complianceCategoryFilter={complianceCategoryFilter}
                setComplianceCategoryFilter={setComplianceCategoryFilter}
                compliancePage={compliancePage}
                setCompliancePage={setCompliancePage}
                compliancePageSize={compliancePageSize}
                setCompliancePageSize={setCompliancePageSize}
                complianceLoading={complianceLoading}
                complianceRunLoading={complianceRunLoading}
                runComplianceAudit={runComplianceAudit}
                openComplianceFindingDetail={openComplianceFindingDetail}
                updateComplianceFinding={updateComplianceFinding}
                language={language}
                t={t}
              />
            </Suspense>
          )}

          {/* ================================================================
               /config/backup  —  备份历史
          ================================================================ */}
          {activeTab === 'config' && configPage === 'backup' && (
            <Suspense fallback={lazyPanelFallback}>
              <ConfigBackupTab
                t={t}
                language={language}
                devices={devices}
                configSnapshots={configSnapshots}
                configCenterDevice={configCenterDevice}
                configViewSnapshot={configViewSnapshot}
                configViewContent={configViewContent}
                configSnapshotKeyword={configSnapshotKeyword}
                retentionDays={retentionDays}
                configSnapshotsLoading={configSnapshotsLoading}
                isTakingSnapshot={isTakingSnapshot}
                getVendorFromPlatform={getVendorFromPlatform}
                onTakeSnapshotForCurrentDevice={async () => {
                  if (!configCenterDevice) return;
                  await takeConfigSnapshot(configCenterDevice);
                }}
                onBackupAllOnline={handleRunBackupAllOnline}
                onClearDeviceSelection={() => {
                  setConfigCenterDevice(null);
                  setConfigViewSnapshot(null);
                  setConfigViewContent('');
                }}
                onSelectDevice={(device) => {
                  setConfigCenterDevice(device);
                  setConfigViewSnapshot(null);
                  setConfigViewContent('');
                }}
                onBackToList={() => {
                  setConfigViewSnapshot(null);
                  setConfigViewContent('');
                }}
                onCopyConfigContent={() => { void handleCopyConfigContent(); }}
                onFetchLiveConfig={handleFetchLiveConfig}
                onConfigSnapshotKeywordChange={setConfigSnapshotKeyword}
                onSearchSnapshots={handleSearchConfigSnapshots}
                onClearSearch={handleClearConfigSnapshotSearch}
                onRetentionDaysChange={setRetentionDays}
                onRefreshSnapshots={handleSearchConfigSnapshots}
                onOpenSnapshot={handleOpenConfigSnapshot}
                onOpenDiff={handleOpenConfigDiff}
                onCopySnapshot={handleCopyConfigSnapshot}
                onDeleteSnapshot={deleteSnapshot}
              />
            </Suspense>
          )}
          {activeTab === 'config' && configPage === 'diff' && (
            <Suspense fallback={lazyPanelFallback}>
              <ConfigDiffViewTab
                t={t}
                language={language}
                configSnapshotKeyword={configSnapshotKeyword}
                configSnapshotsLoading={configSnapshotsLoading}
                configSnapshots={configSnapshots}
                configDiffLeft={configDiffLeft}
                configDiffRight={configDiffRight}
                sameTargetSnapshots={sameTargetSnapshots}
                activeDiffLines={activeDiffLines}
                activeChangeLineIndexes={activeChangeLineIndexes}
                diffFocusChangeIdx={diffFocusChangeIdx}
                diffOnlyChanges={diffOnlyChanges}
                diffShowFullBoth={diffShowFullBoth}
                renderedDiffLines={renderedDiffLines}
                fullSideBySideRows={fullSideBySideRows}
                diffChangeBlocks={diffChangeBlocks}
                filteredDiffChangeBlocks={filteredDiffChangeBlocks}
                diffBlockQuery={diffBlockQuery}
                diffLineRefs={diffLineRefs}
                onReset={handleResetDiffView}
                onConfigSnapshotKeywordChange={setConfigSnapshotKeyword}
                onSearchSnapshots={handleSearchConfigSnapshots}
                onClearSearch={handleClearConfigSnapshotSearch}
                onSelectSnapshot={handleSelectDiffSnapshot}
                onJumpToDiff={jumpToDiff}
                onToggleOnlyChanges={() => setDiffOnlyChanges((prev) => !prev)}
                onToggleFullBoth={() => setDiffShowFullBoth((prev) => !prev)}
                onDiffBlockQueryChange={setDiffBlockQuery}
                onToggleQuickKeyword={(keyword) => setDiffBlockQuery((prev) => (prev.toLowerCase() === keyword ? '' : keyword))}
                onFocusDiffChangeAt={focusDiffChangeAt}
              />
            </Suspense>
          )}
          {activeTab === 'config' && configPage === 'search' && (
            <Suspense fallback={lazyPanelFallback}>
              <ConfigSearchTab t={t} />
            </Suspense>
          )}
          {activeTab === 'config' && configPage === 'schedule' && (
            <Suspense fallback={lazyPanelFallback}>
              <ConfigScheduleTab
                t={t}
                language={language}
                devices={devices}
                configSnapshots={configSnapshots}
                isTakingSnapshot={isTakingSnapshot}
                scheduleEnabled={scheduleEnabled}
                scheduleHour={scheduleHour}
                scheduleMinute={scheduleMinute}
                scheduleLoading={scheduleLoading}
                retentionDays={retentionDays}
                getVendorFromPlatform={getVendorFromPlatform}
                onToggleScheduleEnabled={() => setScheduleEnabled((prev) => !prev)}
                onScheduleHourChange={setScheduleHour}
                onScheduleMinuteChange={setScheduleMinute}
                onRetentionDaysChange={setRetentionDays}
                onSaveSchedule={saveScheduleConfig}
                onRunBackupNow={handleRunScheduledBackupNow}
              />
            </Suspense>
          )}
                    {activeTab === 'configuration' && (
                      <Suspense fallback={lazyPanelFallback}>
                        <PlatformSettingsTab
                          t={t}
                          language={language}
                          sectionHeaderRowClass={sectionHeaderRowClass}
                          configTemplates={configTemplates}
                          configVariableKeys={configVariableKeys}
                          configMissingVariables={configMissingVariables}
                          configScopedDevices={configScopedDevices}
                          configScopedOnlineCount={configScopedOnlineCount}
                          configReadinessScore={configReadinessScore}
                          configValidationIssues={configValidationIssues}
                          configValidationWarnings={configValidationWarnings}
                          configWorkspaceView={configWorkspaceView}
                          selectedTemplateId={selectedTemplateId}
                          selectedConfigTemplate={selectedConfigTemplate}
                          globalVars={globalVars}
                          editorContent={editorContent}
                          configRenderedPreview={configRenderedPreview}
                          configScopePlatform={configScopePlatform}
                          configScopeRole={configScopeRole}
                          configScopeSite={configScopeSite}
                          configPlatformOptions={configPlatformOptions}
                          configRoleOptions={configRoleOptions}
                          configSiteOptions={configSiteOptions}
                          extractVars={extractVars}
                          getPlatformLabel={getPlatformLabel}
                          onImportVars={handleImportVars}
                          onCreateTemplate={handleNewTemplate}
                          onSelectTemplateIdChange={(templateId) => {
                            setSelectedTemplateId(templateId);
                            const template = configTemplates.find((item) => item.id === templateId);
                            setEditorContent(template?.content || '');
                          }}
                          onAddVar={handleAddVar}
                          onDeleteVar={handleDeleteVar}
                          onSelectedTemplateNameChange={(value) => {
                            setConfigTemplates((prev) => prev.map((template) => (
                              template.id === selectedTemplateId ? { ...template, name: value } : template
                            )));
                          }}
                          onSelectedTemplateVendorChange={(value) => {
                            setConfigTemplates((prev) => prev.map((template) => (
                              template.id === selectedTemplateId ? { ...template, vendor: value } : template
                            )));
                          }}
                          onSelectedTemplateTypeChange={(value) => {
                            setConfigTemplates((prev) => prev.map((template) => (
                              template.id === selectedTemplateId ? { ...template, type: value } : template
                            )));
                          }}
                          onDiscardChanges={handleDiscardChanges}
                          onConfigWorkspaceViewChange={setConfigWorkspaceView}
                          onValidate={handleValidateTemplateWorkspace}
                          onSaveTemplate={handleSaveTemplate}
                          onCreateScenarioDraft={handleCreateScenarioDraftFromTemplate}
                          onSendToAutomation={handleOpenTemplateDeploy}
                          onEditorContentChange={setEditorContent}
                          onConfigScopePlatformChange={setConfigScopePlatform}
                          onConfigScopeRoleChange={setConfigScopeRole}
                          onConfigScopeSiteChange={setConfigScopeSite}
                          showToast={showToast}
                        />
                      </Suspense>
                    )}

          {activeTab === 'users' && (
            <Suspense fallback={lazyPanelFallback}>
              <UsersTab
                users={users}
                showAddUserModal={showAddUserModal}
                setShowAddUserModal={setShowAddUserModal}
                showEditUserModal={showEditUserModal}
                setShowEditUserModal={setShowEditUserModal}
                editingUser={editingUser}
                setEditingUser={setEditingUser}
                newUserForm={newUserForm}
                setNewUserForm={setNewUserForm}
                editUserForm={editUserForm}
                setEditUserForm={setEditUserForm}
                showNewUserPwd={showNewUserPwd}
                setShowNewUserPwd={setShowNewUserPwd}
                showEditUserPwd={showEditUserPwd}
                setShowEditUserPwd={setShowEditUserPwd}
                handleAddUser={handleAddUser}
                handleEditUser={handleEditUser}
                language={language}
                t={t}
              />
            </Suspense>
          )}
          {activeTab === 'history' && (
            <Suspense fallback={lazyPanelFallback}>
              <HistoryTab
                auditRows={auditRows}
                auditTotal={auditTotal}
                auditPage={auditPage}
                setAuditPage={setAuditPage}
                auditPageSize={auditPageSize}
                setAuditPageSize={setAuditPageSize}
                auditLoading={auditLoading}
                auditCategoryFilter={auditCategoryFilter}
                setAuditCategoryFilter={setAuditCategoryFilter}
                auditSeverityFilter={auditSeverityFilter}
                setAuditSeverityFilter={setAuditSeverityFilter}
                auditStatusFilter={auditStatusFilter}
                setAuditStatusFilter={setAuditStatusFilter}
                auditTimeFilter={auditTimeFilter}
                setAuditTimeFilter={setAuditTimeFilter}
                openAuditEventDetail={openAuditEventDetail}
                language={language}
                t={t}
              />
            </Suspense>
          )}

          {activeTab === 'reports' && (
            <Suspense fallback={lazyPanelFallback}>
              <ReportsTab
                devices={devices}
                jobs={jobs}
                complianceOverview={complianceOverview}
                platformData={platformData}
                language={language}
                t={t}
              />
            </Suspense>
          )}

          {activeTab === 'config' && configPage === 'drift' && (
            <Suspense fallback={lazyPanelFallback}>
              <ConfigDriftTab language={language} t={t} />
            </Suspense>
          )}

          {activeTab === 'capacity' && (
            <Suspense fallback={lazyPanelFallback}>
              <CapacityPlanningTab language={language} t={t} />
            </Suspense>
          )}

          {activeTab === 'ipam' && (
            <Suspense fallback={lazyPanelFallback}>
              <IPVlanTab language={language} t={t} />
            </Suspense>
          )}

          {activeTab === 'assets' && (
            <Suspense fallback={lazyPanelFallback}>
              <AssetManagementTab language={language} t={t} setActiveTab={setActiveTab} />
            </Suspense>
          )}
        </main>
        <footer className={`h-10 px-8 border-t flex items-center justify-between text-[11px] ${resolvedTheme === 'dark' ? 'border-white/10 text-white/45 bg-[#0b1320]' : 'border-black/8 text-black/45 bg-white/70'}`}>
          <span>Copyright (c) {new Date().getFullYear()} NetPilot. All rights reserved.</span>
          <span className="font-mono">NOC v2.0</span>
        </footer>
      </div>

      {/* ── Command Preview Modal ── */}
      {showCustomCommandModal && (
        <CustomCommandModal
          language={language}
          t={t}
          customCommand={customCommand}
          customCommandMode={customCommandMode}
          customCommandVars={customCommandVars}
          scriptVars={scriptVars}
          batchMode={batchMode}
          batchDeviceIds={batchDeviceIds}
          selectedDevice={selectedDevice}
          isBatchRunning={isBatchRunning}
          isTestingConnection={isTestingConnection}
          showFavorites={showFavorites}
          commandFavorites={commandFavorites}
          onClose={closeCustomCommandModal}
          onSubmit={submitCustomCommand}
          onCustomCommandChange={setCustomCommand}
          onModeChange={setCustomCommandMode}
          onScriptVarChange={(key, value) => setScriptVars((prev) => ({ ...prev, [key]: value }))}
          onToggleFavorite={saveFavorite}
          isFavorited={isFavorited}
          onSaveQuickQuery={() => {
            const label = prompt(language === 'zh' ? '给这个查询起个名字：' : 'Name this query:', '');
            if (!label) return;
            try {
              const saved: { icon: string; label: string; labelEn: string; cmds: string }[] = JSON.parse(localStorage.getItem('quickQuerySaved') || '[]');
              saved.push({ icon: '⭐', label, labelEn: label, cmds: customCommand.trim() });
              localStorage.setItem('quickQuerySaved', JSON.stringify(saved));
              showToast(language === 'zh' ? '已保存到快捷查询' : 'Saved to Quick Query', 'success');
            } catch {
              // ignore local cache errors to avoid blocking the modal flow
            }
          }}
          onToggleFavorites={() => setShowFavorites((prev) => !prev)}
          onUseFavorite={setCustomCommand}
        />
      )}

      <CommandPreviewModal
        open={showCmdPreviewModal}
        language={language}
        scenarioName={quickPlaybookScenario?.name}
        scenarioNameZh={quickPlaybookScenario?.name_zh}
        platform={quickPlaybookPlatform}
        preview={quickPlaybookPreview}
        onClose={() => setShowCmdPreviewModal(false)}
        onCopyAll={async () => {
          const phases = ['pre_check', 'execute', 'post_check', 'rollback'] as const;
          const content = phases
            .map((phase) => {
              const commands = quickPlaybookPreview?.[phase] || [];
              if (!commands.length) return '';
              return `[${phase.toUpperCase()}]\n${commands.join('\n')}`;
            })
            .filter(Boolean)
            .join('\n\n');
          const copied = await copyTextWithFallback(content);
          showToast(copied ? (language === 'zh' ? '命令已复制' : 'Copied') : (language === 'zh' ? '复制失败' : 'Copy failed'), copied ? 'success' : 'error');
        }}
      />

      {showAddScenarioModal && (
        <AddScenarioModal
          open={showAddScenarioModal}
          language={language}
          resolvedTheme={resolvedTheme}
          platforms={platforms}
          form={newScenarioForm}
          variables={newScenarioVariables}
          draftOrigin={scenarioDraftOrigin}
          isSaving={isSavingScenario}
          onClose={resetScenarioDraft}
          onSubmit={createScenario}
          onFormChange={setNewScenarioForm}
        />
      )}

      <ProfileModal
        open={showProfileModal}
        language={language}
        resolvedTheme={resolvedTheme}
        currentRole={currentUser.role || currentUserRecord?.role || 'Administrator'}
        currentUserLastLogin={currentUserLastLogin}
        profileAvatarPreview={profileAvatarPreview}
        avatarPresets={avatarPresets}
        profileForm={profileForm}
        showProfilePwd={showProfilePwd}
        notificationChannels={notificationChannels}
        notifyTestLoading={notifyTestLoading}
        renderAvatarContent={renderAvatarContent}
        onClose={() => setShowProfileModal(false)}
        onSave={handleSaveProfile}
        onAvatarFileChange={handleProfileAvatarChange}
        onClearAvatar={() => setProfileAvatarPreview('')}
        onSelectAvatarPreset={setProfileAvatarPreview}
        onProfileFormChange={setProfileForm}
        onToggleProfilePassword={() => setShowProfilePwd((value) => !value)}
        onNotificationChannelToggle={(channel) => setNotificationChannels((prev) => ({ ...prev, [channel]: { ...prev[channel], enabled: !prev[channel].enabled } }))}
        onNotificationWebhookChange={(channel, value) => setNotificationChannels((prev) => ({ ...prev, [channel]: { ...prev[channel], webhook_url: value } }))}
        onNotificationSecretChange={(value) => setNotificationChannels((prev) => ({ ...prev, dingtalk: { ...prev.dingtalk, secret: value } }))}
        onTestNotificationChannel={async (channel) => {
          const profileUserId = currentUser.id ?? currentUserRecord?.id;
          if (!profileUserId) return;
          const currentChannel = notificationChannels[channel];
          setNotifyTestLoading(channel);
          try {
            const response = await fetch(`/api/users/${profileUserId}/notify-test`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('sessionToken') || ''}`,
              },
              body: JSON.stringify({
                platform: channel,
                webhook_url: currentChannel.webhook_url,
                secret: channel === 'dingtalk' ? notificationChannels.dingtalk.secret : '',
              }),
            });
            const data = await response.json();
            if (response.ok) showToast(`${channel === 'feishu' ? '飞书' : channel === 'dingtalk' ? '钉钉' : '企业微信'} 测试消息已发送 ✓`, 'success');
            else showToast(`发送失败: ${data.detail || data.error}`, 'error');
          } catch {
            showToast('连接错误', 'error');
          } finally {
            setNotifyTestLoading('');
          }
        }}
      />

      {/* Test Connection Result Modal */}
      {showTestResult && (
        <TestConnectionResultModal
          open={showTestResult}
          language={language}
          isTestingConnection={isTestingConnection}
          connectionTestMode={connectionTestMode}
          connectionTestDevice={connectionTestDevice}
          selectedDevice={selectedDevice}
          testResult={testResult}
          onClose={() => setShowTestResult(false)}
          onRetry={handleTestConnection}
        />
      )}

      <ImportInventoryModal
        open={showImportModal}
        language={language}
        t={t}
        onClose={() => setShowImportModal(false)}
        onImport={() => {
          alert('Import feature simulation: Data processed successfully.');
          setShowImportModal(false);
        }}
      />

      <ConfigDiffModal
        open={showDiff}
        language={language}
        t={t}
        selectedDevice={selectedDevice}
        currentDiff={currentDiff}
        onClose={() => setShowDiff(false)}
        onCommit={() => {
          void runTask('VLAN Update');
        }}
      />

      <HistoricalConfigModal
        open={showConfigModal}
        language={language}
        t={t}
        selectedDevice={selectedDevice}
        viewingConfig={viewingConfig}
        onClose={() => setShowConfigModal(false)}
        onRollback={() => {
          if (!selectedDevice || !viewingConfig) return;
          void handleRollbackConfig(selectedDevice, viewingConfig);
        }}
      />

      <ScheduleTaskModal
        open={showScheduleModal}
        language={language}
        t={t}
        selectedDevice={selectedDevice}
        schedulingTask={schedulingTask}
        scheduleForm={scheduleForm}
        onScheduleFormChange={setScheduleForm}
        onClose={() => setShowScheduleModal(false)}
        onSubmit={handleScheduleTask}
      />

      <RemediationModal
        open={showRemediationModal}
        language={language}
        t={t}
        device={remediatingDevice}
        onClose={() => setShowRemediationModal(false)}
        onConfirm={confirmRemediation}
      />

      <DeleteConfirmModal
        open={showDeleteModal}
        language={language}
        isDeletingSelected={isDeletingSelected}
        selectedDeviceCount={selectedDeviceIds.length}
        onClose={() => {
          setShowDeleteModal(false);
          setDeviceToDelete(null);
          setIsDeletingSelected(false);
        }}
        onConfirm={() => {
          void confirmDeleteDevice();
        }}
      />

      {/* Edit Device Modal */}
      {/* Add Device Modal */}
      {showAddModal && (
        <DeviceFormModal
          mode="add"
          language={language}
          form={addForm}
          passwordVisible={showAddDevicePwd}
          onFormChange={setAddForm}
          onTogglePasswordVisibility={() => setShowAddDevicePwd((value) => !value)}
          onClose={() => setShowAddModal(false)}
          onSubmit={handleAddDevice}
        />
      )}

      {showEditModal && editingDevice && (
        <DeviceFormModal
          mode="edit"
          language={language}
          form={editForm}
          passwordVisible={showEditDevicePwd}
          onFormChange={setEditForm}
          onTogglePasswordVisibility={() => setShowEditDevicePwd((value) => !value)}
          onClose={() => setShowEditModal(false)}
          onSubmit={handleSaveEdit}
        />
      )}

      {/* Device Details Modal */}
      {showDetailsModal && viewingDevice && (
        <DeviceDetailModal
          language={language}
          t={t}
          viewingDevice={viewingDevice}
          viewingDeviceAlerts={viewingDeviceAlerts}
          deviceDetailLoading={deviceDetailLoading}
          viewingDeviceConnectionSummary={viewingDevice.id ? deviceConnectionChecks[viewingDevice.id] : null}
          connectionTestingDeviceId={connectionTestingDeviceId}
          onClose={() => setShowDetailsModal(false)}
          deviceTrendRangeHours={deviceTrendRangeHours}
          onDeviceTrendRangeHoursChange={setDeviceTrendRangeHours}
          deviceHealthTrend={deviceHealthTrend}
          deviceHealthTrendLoading={deviceHealthTrendLoading}
          deviceOperationalData={deviceOperationalData}
          deviceOperationalDataLoading={deviceOperationalDataLoading}
          onLoadOperationalData={loadDeviceOperationalData}
          onTestConnection={handleTestConnection}
          isTestingConnection={isTestingConnection}
          onSnmpTest={handleSnmpTest}
          snmpTestingId={snmpTestingId}
          onSnmpSyncNow={handleSnmpSyncNow}
          snmpSyncingId={snmpSyncingId}
          onGoToAutomation={(device) => {
            setSelectedDevice(device);
            setActiveTab('automation');
            setShowDetailsModal(false);
          }}
        />
      )}

      {/* SNMP Test Result Modal */}
      {showSnmpTestResult && (
        <SnmpTestResultModal
          open={showSnmpTestResult}
          language={language}
          result={snmpTestResult}
          onClose={() => setShowSnmpTestResult(false)}
        />
      )}

      <AuditEventDetailModal
        event={selectedAuditEvent}
        language={language}
        t={t}
        onClose={() => setSelectedAuditEvent(null)}
      />

      <ComplianceFindingDetailModal
        finding={selectedFinding}
        language={language}
        t={t}
        onClose={() => setSelectedFinding(null)}
        onStatusChange={(value) => setSelectedFinding((prev) => (prev ? { ...prev, status: value } : prev))}
        onOwnerChange={(value) => setSelectedFinding((prev) => (prev ? { ...prev, owner: value } : prev))}
        onNoteChange={(value) => setSelectedFinding((prev) => (prev ? { ...prev, note: value } : prev))}
        onSave={() => {
          if (!selectedFinding) return;
          void updateComplianceFinding(selectedFinding.id, {
            status: selectedFinding.status,
            owner: selectedFinding.owner,
            note: selectedFinding.note,
          });
        }}
      />

      <JobOutputModal
        job={selectedJob}
        t={t}
        onClose={() => setSelectedJob(null)}
        onCopy={async () => {
          const copied = await copyTextWithFallback(selectedJob?.output || '');
          showToast(t('copied'), copied ? 'success' : 'error');
        }}
      />

      {/* Toast Notification */}
      <CommandPalette
        open={cmdPaletteOpen}
        language={language}
        query={cmdPaletteQuery}
        items={cmdPaletteFiltered}
        pinnedPaths={pinnedPaths}
        currentPath={location.pathname}
        onClose={() => setCmdPaletteOpen(false)}
        onQueryChange={setCmdPaletteQuery}
        onNavigate={(path) => {
          navTo(path);
          setCmdPaletteOpen(false);
        }}
        onTogglePin={togglePin}
      />

      <ToastNotification toast={toast} />
      </div>
    </AppRuntimeBoundary>
  );
};

export default App;
