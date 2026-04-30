import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'motion/react';
import { Routes, Route, useLocation, useNavigate, Navigate } from 'react-router-dom';
import * as htmlToImage from 'html-to-image';
import { Plus, Server, CheckCircle, CheckCircle2, XCircle, RotateCcw, Play, Activity, LayoutDashboard, Database, Zap, ShieldCheck, History, LogOut, Search, Bell, Settings, Download, Upload, FileText, ChevronLeft, ChevronRight, Filter, Globe, TrendingUp, PieChart as PieChartIcon, Clock, Edit2, AlertCircle, FolderOpen, Eye, EyeOff, Sun, Moon, User as UserIcon, ChevronDown, Copy, Menu, PanelLeftClose, Monitor, ExternalLink, Trash2, Wrench, Maximize2, Minimize2, BarChart3, GitCompareArrows, Cpu, Network, Pin, AlertTriangle, X } from 'lucide-react';
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
import AppLayout from './components/AppLayout';
import AppMainContent from './components/AppMainContent';
import { AppRuntimeBoundary } from './components/AppRuntimeBoundary';
import type { ToastState } from './components/ToastNotification';
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
import LoginScreen from './components/LoginScreen';
import SetupWizard from './components/SetupWizard';
import TestConnectionResultModal from './components/TestConnectionResultModal';
import SnmpTestResultModal from './components/SnmpTestResultModal';
import { buildConnectionTestMessage, buildConnectionTestHint, buildConnectionCheckStatus, connectionCheckBadgeMeta, formatConnectionCheckTime } from './utils/connectionHelpers';
import { useConfigDiff } from './hooks/useConfigDiff';
import { useTheme } from './hooks/useTheme';
import { useNotifications } from './hooks/useNotifications';
import { useAuth } from './hooks/useAuth';
import { useInventory } from './hooks/useInventory';
import { useAutomation } from './hooks/useAutomation';
import { useMonitoring } from './hooks/useMonitoring';
import { useUserManagement } from './hooks/useUserManagement';
import { useHistoryAuditCompliance } from './hooks/useHistoryAuditCompliance';
import { useInventoryPageData } from './hooks/useInventoryPageData';
import { useInventoryUiState } from './hooks/useInventoryUiState';
import { useTopologyVisibleDevices } from './hooks/useTopologyVisibleDevices';
import { useTopologySelectionSync } from './hooks/useTopologySelectionSync';
import { useResourceSignals } from './hooks/useResourceSignals';
import { useInventoryDeleteActions } from './hooks/useInventoryDeleteActions';
import { useInventoryTableActions } from './hooks/useInventoryTableActions';
import { useConfigRollbackAction } from './hooks/useConfigRollbackAction';
import { exportInventoryToExcel } from './utils/inventoryExport';
import { normalizeTopologyPort, getTopologyOperationalTone, type TopologyOperationalState } from './utils/topologyCore';
import { formatResourcePercent, formatCompactResourcePercent } from './utils/resourceFormatters';
import {
  formatTopologyPort as formatTopologyPortValue,
  formatTopologyEvidenceLabel as formatTopologyEvidenceLabelValue,
  formatTopologyOperationalState as formatTopologyOperationalStateValue,
  formatTopologyLastSeen as formatTopologyLastSeenValue,
} from './utils/topologyFormatters';
import { getRouteContext } from './utils/routeContext';

// Types imported from ./types — re-export User as UserType to avoid clash with lucide-react User icon


// Sparkline imported from ./components/Sparkline

const App: React.FC = () => {
  const { t, language, setLanguage } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
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
      return <UserIcon size={fallbackIconSize} />;
    }
    if (avatarValue) {
      return <img src={avatarValue} alt="avatar" className="w-full h-full object-cover" />;
    }
    return <UserIcon size={fallbackIconSize} />;
  };
  const { themeMode, setThemeMode, resolvedTheme } = useTheme();
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    // 自动清除
    setTimeout(() => {
      setToast(null);
    }, 5000);
  }, []);

  const [showSetupWizard, setShowSetupWizard] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const userMenuRef = React.useRef<HTMLDivElement | null>(null);
  
  const {
    isAuthenticated,
    setIsAuthenticated,
    authChecking,
    currentUser,
    setCurrentUser,
    isAuthenticating,
    loginError,
    setLoginError,
    loginForm,
    setLoginForm,
    handleLogin,
    handleLogout,
    handleLanguagePreferenceChange,
    rememberMe,
    setRememberMe,
    showLoginPwd,
    setShowLoginPwd,
  } = useAuth({
    language,
    setLanguage,
    showToast,
    setShowSetupWizard,
    setShowUserMenu,
    setShowNotifications,
  });

  const routeContext = useMemo(() => getRouteContext(location.pathname), [location.pathname]);
  const { activeTab, configPage, automationPage, inventorySubPage, changeOrderPage } = routeContext;

  const deviceFetchMode = useMemo<'light' | 'full'>(() => {
    if (activeTab === 'inventory') return 'full';
    if (activeTab === 'automation') return 'full';
    if (activeTab === 'config') return 'full';
    if (activeTab === 'topology') return 'full';
    return 'light';
  }, [activeTab]);

  const {
    devices,
    setDevices,
    selectedDevice,
    setSelectedDevice,
    devicesLastUpdatedAt,
    fetchDevicesData,
    normalizeDeviceRecord
  } = useInventory(deviceFetchMode);

  const { 
    notifications, 
    setNotifications,
    notificationReadMap,
    setNotificationReadMap,
    unreadNotifications,
    unreadCount: unreadNotificationCount, 
    markNotificationsAsRead, 
    markAllNotificationsRead 
  } = useNotifications({ currentUser, language, isAuthenticated });

  const {
    jobs, setJobs, scheduledTasks, setScheduledTasks, scenarios, platforms, playbookExecutions,
    scripts, setScripts, selectedScript, setSelectedScript, selectedAutomationTemplate, setSelectedAutomationTemplate, editedScriptContent, setEditedScriptContent,
    customCommand, setCustomCommand, onCustomCommandChange,
    scriptParams, setScriptParams, commandFavorites, setCommandFavorites, showFavorites, setShowFavorites,
    commandHistory,
    scriptVars, setScriptVars, batchMode, setBatchMode, batchDeviceIds, setBatchDeviceIds,
    batchResults, setBatchResults, isBatchRunning, setIsBatchRunning, dryRun, setDryRun,
    quickQueryOutput, setQuickQueryOutput, quickQueryRunning, setQuickQueryRunning, quickQueryLabel, setQuickQueryLabel,
    quickQueryStructured, setQuickQueryStructured, quickQueryView, setQuickQueryView, quickQueryMaximized, setQuickQueryMaximized,
    quickQueryCommands, setQuickQueryCommands, changeTicket, setChangeTicket,
    selectedJob, setSelectedJob, showCustomCommandModal, setShowCustomCommandModal, showCmdPreviewModal, setShowCmdPreviewModal,
    isAutomationTaskRunning, setIsAutomationTaskRunning, showDiff, setShowDiff, currentDiff, setCurrentDiff, customCommandVars,
    applyScriptVars, formatQuickQueryRawOutput, getQuickQueryCommands, runTask, runParsedCustomCommand, rollback, runBatchTask,
    saveFavorite, isFavorited, closeCustomCommandModal, submitCustomCommand,
    handleSelectPlaybookScenario, handlePlaybookPlatformChange, handlePlaybookVariableChange, handleTogglePlaybookDevice,
    selectedScenario, setSelectedScenario, playbookVars, setPlaybookVars, playbookDeviceIds, setPlaybookDeviceIds,
    playbookPlatform, setPlaybookPlatform, playbookDryRun, setPlaybookDryRun, playbookConcurrency, setPlaybookConcurrency,
    playbookPreview, setPlaybookPreview, quickPlaybookScenario, setQuickPlaybookScenario, quickPlaybookVars, setQuickPlaybookVars,
    quickPlaybookPlatform, setQuickPlaybookPlatform, quickPlaybookDryRun, setQuickPlaybookDryRun, quickPlaybookConcurrency, setQuickPlaybookConcurrency,
    quickPlaybookPreview, setQuickPlaybookPreview, quickRiskConfirmed, setQuickRiskConfirmed, isQuickPlaybookRunning, setIsQuickPlaybookRunning,
    quickExecutionResult, setQuickExecutionResult, wsMessages, setWsMessages, deviceStatusMap, setDeviceStatusMap,
    wsCompleteMsg, setWsCompleteMsg, activeExecutionId, setActiveExecutionId, quickQueryTable, executionStatus, setExecutionStatus,
    quickTargetDevices, quickDetectedPlatforms, quickHasMixedPlatforms, quickDetectedPlatform, quickScenarioSupportsDetectedPlatform,
    quickAutoPlatform, quickPlatformMismatch, hasQuickTargets, quickMissingRequiredFields,
    automationSearch, setAutomationSearch, handleAutomationSearch, scenarioSearch, setScenarioSearch, handleScenarioSearch, filteredScenarios,
    loadScenarios, loadPlaybookHistory, loadJobs, runPlaybook, openQuickPlaybookModal, loadQuickPlaybookPreview, previewPlaybook, executePlaybook, resetAutomationSubmenuState,
    runQuickPlaybook, runQuickQuery, handleResetQuickQuery, handleToggleBatchMode, handleToggleBatchDevice, handleSelectAutomationDevice, handleClearQuickScenario, handleResetQuickExecutionState, exportQuickQueryTable,
    extractVars, splitLines,
    saveQuickQueryModalOpen, setSaveQuickQueryModalOpen, quickQuerySaveLabel, setQuickQuerySaveLabel,
    handleSaveQuickQuery,
    savedQueries,
    handleRerun
  } = useAutomation({ currentUser, language, showToast, navigate, setSelectedDevice, devices, selectedDevice, activeTab, automationPage });

  const [globalVars, setGlobalVars] = useState<{id?: string, key: string, value: string}[]>([]);
  const [configTemplates, setConfigTemplates] = useState<ConfigTemplate[]>([]);

  const findMatchingPlatform = useCallback((devicePlatform: string, platforms: string[] | Record<string, any>) => {
    if (!devicePlatform) return undefined;
    const pList = Array.isArray(platforms) ? platforms : Object.keys(platforms);
    const dp = devicePlatform.toLowerCase();
    return pList.find(p => {
      const target = p.toLowerCase();
      return dp === target || dp.includes(target) || target.includes(dp);
    });
  }, []);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [editorContent, setEditorContent] = useState<string>('');

  const [profileAvatarPreview, setProfileAvatarPreview] = useState('');
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

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
    const tpl = configTemplates.find(t => t.id === selectedTemplateId);
    if (tpl) {
      setEditorContent(tpl.content);
    }
  }, [selectedTemplateId, configTemplates]);
  // getVendorFromPlatform, PLATFORM_LABELS, getPlatformLabel imported from ./types

  // Quick Query (read-only commands, no history saved)

  // ---------- Config Center ----------
  const [retentionDays, setRetentionDays] = useState<number>(365);
  const [configSnapshots, setConfigSnapshots] = useState<ConfigSnapshot[]>([]);
  const [configSnapshotsLoading, setConfigSnapshotsLoading] = useState(false);
  const [configCenterDevice, setConfigCenterDevice] = useState<Device | null>(null);
  const [configViewContent, setConfigViewContent] = useState<string>('');
  const [configViewSnapshot, setConfigViewSnapshot] = useState<ConfigSnapshot | null>(null);
  const [configSnapshotKeyword, setConfigSnapshotKeyword] = useState('');
  const [configSearchQuery, setConfigSearchQuery] = useState('');
  const [configSearchResults, setConfigSearchResults] = useState<any[]>([]);
  const [configSearchLoading, setConfigSearchLoading] = useState(false);
  const [isTakingSnapshot, setIsTakingSnapshot] = useState(false);
  // Schedule state
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleCron, setScheduleCron] = useState('0 2 * * *');
  const [scheduleLoading, setScheduleLoading] = useState(false);
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
    try {
      const val = JSON.parse(localStorage.getItem('netops_pinned_nav') || '[]');
      return Array.isArray(val) ? val : [];
    } catch {
      return [];
    }
  });
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const [cmdPaletteQuery, setCmdPaletteQuery] = useState('');
  // showCustomCommandModal moved to useAutomation
  // showCmdPreviewModal moved to useAutomation
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
  const [selectedExecutionDetail, setSelectedExecutionDetail] = useState<any | null>(null);
  const [selectedExecutionLoading, setSelectedExecutionLoading] = useState(false);
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

  const handleRefreshHistory = useCallback(async (
    page = playbookHistoryPage,
    statusFilter = playbookHistoryStatusFilter,
    scenarioFilter = playbookHistoryScenarioSearch,
  ) => {
    await loadPlaybookHistory(page, statusFilter, scenarioFilter);
  }, [playbookHistoryPage, playbookHistoryStatusFilter, playbookHistoryScenarioSearch, loadPlaybookHistory]);

  useEffect(() => {
    if (isAuthenticated && activeTab === 'automation' && automationPage === 'queries') {
      handleRefreshHistory(playbookHistoryPage, playbookHistoryStatusFilter, playbookHistoryScenarioSearch);
    }
  }, [isAuthenticated, activeTab, automationPage, playbookHistoryPage, playbookHistoryStatusFilter, playbookHistoryScenarioSearch, handleRefreshHistory]);

  const loadExecDevices = useCallback(async (executionId: string, page = 1, statusFilter = 'all', search = '') => {
    setSelectedExecDevicesLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: '20',
        status: statusFilter,
        ...(search ? { search } : {}),
      });
      const resp = await fetch(`/api/playbooks/${executionId}/devices?${params}`);
      if (resp.ok) {
        const data = await resp.json();
        setSelectedExecDevices(data.items || []);
        setSelectedExecDevicesTotal(data.total || 0);
      }
    } catch (e) {
      console.error('Failed to load exec devices:', e);
    } finally {
      setSelectedExecDevicesLoading(false);
    }
  }, []);
  const wsRef = React.useRef<WebSocket | null>(null);
  // selectedJob moved to useAutomation
  const [topologyLinks, setTopologyLinks] = useState<any[]>([]);
  const [topologyUnmanagedNodes, setTopologyUnmanagedNodes] = useState<any[]>([]);
  const [topologyUnmanagedLinks, setTopologyUnmanagedLinks] = useState<any[]>([]);
  const [topologySearch, setTopologySearch] = useState('');
  const [topologyStatusFilter, setTopologyStatusFilter] = useState<'all' | 'online' | 'offline' | 'pending'>('all');
  const [topologyRoleFilter, setTopologyRoleFilter] = useState('all');
  const [topologySiteFilter, setTopologySiteFilter] = useState('all');
  const [selectedTopologyDeviceId, setSelectedTopologyDeviceId] = useState<string | null>(null);
  const [selectedTopologyLinkKey, setSelectedTopologyLinkKey] = useState<string | null>(null);
  const [topologyDiscoveryRunning, setTopologyDiscoveryRunning] = useState(false);
  const topologyRef = React.useRef<HTMLDivElement>(null);

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

  // Redirect bare /automation to /automation/execute
  React.useEffect(() => {
    if (activeTab === 'automation' && !automationPage) {
      navigate('/automation/execute', { replace: true });
    }
  }, [activeTab, automationPage, navigate]);
  // Redirect bare /change-orders to /change-orders/all
  React.useEffect(() => {
    if (activeTab === 'change-orders' && !changeOrderPage) {
      navigate('/change-orders/all', { replace: true });
    }
  }, [activeTab, changeOrderPage, navigate]);
  // Load playbook scenarios & platforms once when entering change-orders tab
  React.useEffect(() => {
    if (activeTab === 'change-orders') {
      loadScenarios();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);
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
    if (path === '/dashboard') return language === 'zh' ? '功能中心' : 'Home';
    if (path === '/overview') return language === 'zh' ? '运营总览' : 'Overview';
    if (path === '/monitoring') return language === 'zh' ? '监控中心' : 'Monitoring Center';
    if (path === '/topology') return language === 'zh' ? '网络拓扑' : 'Topology';
    if (path === '/automation/inspection') return language === 'zh' ? '巡检概览' : 'Inspection Overview';
    if (path === '/automation/inspection-records') return language === 'zh' ? '巡检记录' : 'Inspection Records';
    if (path === '/automation/schedule') return language === 'zh' ? '执行计划' : 'Execution Schedules';
    if (path === '/automation/schedule-history') return language === 'zh' ? '执行历史' : 'Execution History';
    if (path === '/automation/scheduled-jobs') return language === 'zh' ? '定时作业' : 'Scheduled Jobs';
    if (path === '/automation/metrics') return language === 'zh' ? '巡检指标项' : 'Inspection Metrics';
    if (path === '/change-orders/all') return language === 'zh' ? '全部工单' : 'All Orders';
    if (path === '/change-orders/my-todo') return language === 'zh' ? '个人待办' : 'My Todo';
    if (path === '/change-orders/group-todo') return language === 'zh' ? '组内待办' : 'Group Todo';
    if (path === '/change-orders/participated') return language === 'zh' ? '我参与的' : 'My Participated';
    if (path === '/change-orders/focus') return language === 'zh' ? '我的关注' : 'My Focus';
    if (path === '/change-orders/drafts') return language === 'zh' ? '草稿箱' : 'Drafts';
    if (path === '/change-orders/new') return language === 'zh' ? '新建工单' : 'New Order';
    if (path === '/alerts') return language === 'zh' ? '告警信息' : 'Alert Desk';
    if (path === '/alert-history') return language === 'zh' ? '历史告警' : 'Alert History';
    if (path === '/alert-rules') return language === 'zh' ? '告警规则' : 'Alert Rules';
    if (path === '/maintenance') return language === 'zh' ? '维护期' : 'Maintenance';
    if (path === '/inventory/devices') return t('deviceList');
    if (path === '/inventory/servers') return language === 'zh' ? '服务器' : 'Servers';
    if (path === '/inventory/interfaces') return t('interfaceMonitoring');
    if (path === '/ipam') return language === 'zh' ? 'IP/VLAN 管理' : 'IP/VLAN Mgmt';
    if (path === '/ip-locator') return language === 'zh' ? 'IP 定位' : 'IP Locator';
    if (path === '/assets') return language === 'zh' ? '资产管理' : 'Assets';
    if (path === '/automation/execute') return t('directExecution');
    if (path === '/automation/scenarios') return t('scenarioLibrary');
    if (path === '/automation/queries') return t('executionHistory');
    if (path === '/config/backup') return t('backupHistory');
    if (path === '/config/diff') return t('diffCompare');
    if (path === '/config/search') return t('configSearchTab');
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
      { path: '/dashboard', label: zh ? '功能中心' : 'Home', group: zh ? '首页' : 'Home' },
      { path: '/overview', label: zh ? '运营总览' : 'Overview', group: zh ? '实时监控' : 'Real-time' },
      { path: '/monitoring', label: zh ? '监控中心' : 'Monitoring Center', group: zh ? '实时监控' : 'Real-time' },
      { path: '/topology', label: zh ? '网络拓扑' : 'Topology', group: zh ? '实时监控' : 'Real-time' },
      { path: '/inventory/devices', label: t('deviceList'), group: zh ? '设备清单' : 'Inventory' },
      { path: '/inventory/servers', label: zh ? '服务器' : 'Servers', group: zh ? '设备清单' : 'Inventory' },
      { path: '/inventory/interfaces', label: t('interfaceMonitoring'), group: zh ? '设备清单' : 'Inventory' },
      { path: '/ipam', label: zh ? 'IP/VLAN 管理' : 'IP/VLAN Mgmt', group: zh ? '设备清单' : 'Inventory' },
      { path: '/ip-locator', label: zh ? 'IP 定位' : 'IP Locator', group: zh ? '设备清单' : 'Inventory' },
      { path: '/assets', label: zh ? '资产管理' : 'Assets', group: zh ? '设备清单' : 'Inventory' },
      { path: '/alerts', label: zh ? '告警信息' : 'Alert Desk', group: zh ? '告警管理' : 'Alerts' },
      { path: '/alert-history', label: zh ? '历史告警' : 'Alert History', group: zh ? '告警管理' : 'Alerts' },
      { path: '/alert-rules', label: zh ? '告警规则' : 'Alert Rules', group: zh ? '告警管理' : 'Alerts' },
      { path: '/maintenance', label: zh ? '维护期' : 'Maintenance', group: zh ? '告警管理' : 'Alerts' },
      { path: '/automation/execute', label: t('directExecution'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scenarios', label: t('scenarioLibrary'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/queries', label: t('executionHistory'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/inspection', label: zh ? '巡检概览' : 'Inspection Overview', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/inspection-records', label: zh ? '巡检记录' : 'Inspection Records', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/schedule', label: zh ? '执行计划' : 'Execution Schedules', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/schedule-history', label: zh ? '执行历史' : 'Execution History', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scheduled-jobs', label: zh ? '定时作业' : 'Scheduled Jobs', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/metrics', label: zh ? '巡检指标项' : 'Inspection Metrics', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scripts', label: zh ? '脚本管理' : 'Script Management', group: zh ? '作业自动化' : 'Automation' },
      { path: '/config/backup', label: t('backupHistory'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/diff', label: t('diffCompare'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/search', label: t('configSearchTab'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/drift', label: zh ? '配置漂移' : 'Config Drift', group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/compliance', label: t('compliance'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/capacity', label: zh ? '容量规划' : 'Capacity Planning', group: zh ? '分析报告' : 'Analytics' },
      { path: '/reports', label: zh ? '报表中心' : 'Reports', group: zh ? '分析报告' : 'Analytics' },
      { path: '/history', label: t('auditLogs'), group: zh ? '平台管理' : 'Management' },
      { path: '/configuration', label: zh ? '平台设置' : 'Platform Settings', group: zh ? '平台管理' : 'Management' },
      { path: '/users', label: t('userManagement'), group: zh ? '平台管理' : 'Management' },
      { path: '/license', label: zh ? '授权管理' : 'License Management', group: zh ? '平台管理' : 'Management' },
      { path: '/change-orders/all', label: zh ? '全部工单' : 'All Orders', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/group-todo', label: zh ? '组内待办' : 'Group Todo', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/my-todo', label: zh ? '个人待办' : 'My Todo', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/participated', label: zh ? '我参与的' : 'My Participated', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/focus', label: zh ? '我的关注' : 'My Focus', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/drafts', label: zh ? '草稿箱' : 'Drafts', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/new', label: zh ? '新建工单' : 'New Order', group: zh ? '工单管理' : 'Tickets' },
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
        inspection: language === 'zh' ? '巡检概览' : 'Inspection Overview',
        'inspection-records': language === 'zh' ? '巡检记录' : 'Inspection Records',
        schedule: language === 'zh' ? '执行计划' : 'Execution Schedules',
        'schedule-history': language === 'zh' ? '执行历史' : 'Execution History',
        'scheduled-jobs': language === 'zh' ? '定时作业' : 'Scheduled Jobs',
        'metrics': language === 'zh' ? '巡检指标' : 'Inspection Metrics',
        'scripts': language === 'zh' ? '脚本管理' : 'Script Management',
      };
      return map[automationPage] || automationPage;
    }
    if (activeTab === 'config') {
      const map: Record<string, string> = {
        backup: t('backupHistory'),
        diff: t('diffCompare'),
        search: t('configSearchTab'),
        drift: language === 'zh' ? '配置漂移' : 'Config Drift',
      };
      return map[configPage] || configPage;
    }
    if (activeTab === 'inventory') {
      const map: Record<string, string> = {
        devices: t('deviceList'),
        interfaces: t('interfaceMonitoring'),
        servers: language === 'zh' ? '服务器' : 'Servers',
      };
      return map[inventorySubPage] || inventorySubPage;
    }
    if (activeTab === 'users') return t('userManagement');
    if (activeTab === 'alerts') return language === 'zh' ? '告警信息' : 'Alert Desk';
    if (activeTab === 'alert-history') return language === 'zh' ? '历史告警' : 'Alert History';
    if (activeTab === 'alert-rules') return language === 'zh' ? '告警规则' : 'Alert Rules';
    if (activeTab === 'maintenance') return language === 'zh' ? '维护期' : 'Maintenance';
    if (activeTab === 'history') return t('auditLogs');
    if (activeTab === 'configuration') return language === 'zh' ? '平台设置' : 'Platform Settings';
    if (activeTab === 'reports') return language === 'zh' ? '报表中心' : 'Reports';
    if (activeTab === 'capacity') return language === 'zh' ? '容量规划' : 'Capacity Planning';
    if (activeTab === 'ipam') return language === 'zh' ? 'IP/VLAN管理' : 'IP/VLAN Management';
    if (activeTab === 'ip-locator') return language === 'zh' ? 'IP 定位' : 'IP Locator';
    if (activeTab === 'assets') return language === 'zh' ? '资产管理' : 'Asset Management';
    if (activeTab === 'tags') return language === 'zh' ? '标签管理' : 'Tag Management';
    if (activeTab === 'racks') return language === 'zh' ? '机柜管理' : 'Rack Management';
    if (activeTab === 'credentials') return language === 'zh' ? '凭据管理' : 'Credential Management';
    if (activeTab === 'license') return language === 'zh' ? '授权管理' : 'License Management';
    if (activeTab === 'change-orders') {
      if (changeOrderPage === 'all') return language === 'zh' ? '全部工单' : 'All Orders';
      if (changeOrderPage === 'my-todo') return language === 'zh' ? '个人待办' : 'My Todo';
      if (changeOrderPage === 'group-todo') return language === 'zh' ? '组内待办' : 'Group Todo';
      if (changeOrderPage === 'participated') return language === 'zh' ? '我参与的' : 'My Participated';
      if (changeOrderPage === 'focus') return language === 'zh' ? '我的关注' : 'My Focus';
      if (changeOrderPage === 'drafts') return language === 'zh' ? '草稿箱' : 'Drafts';
      if (changeOrderPage === 'new') return language === 'zh' ? '新建工单' : 'New Order';
      return language === 'zh' ? '变更工单' : 'Change Orders';
    }
    if (activeTab === 'compliance') return t('compliance');
    if (activeTab === 'monitoring') return language === 'zh' ? '监控中心' : 'Monitoring Center';

    if (activeTab === 'topology') return language === 'zh' ? '网络拓扑' : 'Topology';
    return t('dashboard');
  }, [activeTab, automationPage, configPage, inventorySubPage, changeOrderPage, language, t]);


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
    const inventoryActive = activeTab === 'inventory' || activeTab === 'ipam' || activeTab === 'ip-locator';
    const managementActive = ['history', 'configuration', 'users', 'license'].includes(activeTab);
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
        setScheduleCron(cfg.cron || '0 2 * * *');
      }
    } catch { /* ignore */ }
  };

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
      handleResetDiffView();
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
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      link.download = `network-topology-${ts}.png`;
      link.href = dataUrl;
      link.click();
      showToast('Topology map exported successfully', 'success');
    } catch (error) {
      console.error('Export error:', error);
      showToast('Failed to export map. Please try again.', 'error');
    }
  };

  const {
    users, setUsers,
    showAddUserModal, setShowAddUserModal,
    showEditUserModal, setShowEditUserModal,
    showNewUserPwd, setShowNewUserPwd,
    showEditUserPwd, setShowEditUserPwd,
    editingUser, setEditingUser,
    editUserForm, setEditUserForm,
    newUserForm, setNewUserForm,
    createEmptyUserForm,
    handleAddUser, handleEditUser,
  } = useUserManagement({ currentUser, setCurrentUser, language, showToast });
  const [trendDays, setTrendDays] = useState<7 | 30>(7);
  const [dashBannerCollapsed, setDashBannerCollapsed] = useState(false);
  const [dashLastRefresh, setDashLastRefresh] = useState<Date>(new Date());
  const [showAddDevicePwd, setShowAddDevicePwd] = useState(false);
  const [showEditDevicePwd, setShowEditDevicePwd] = useState(false);
  const [showLifecycleConfirm, setShowLifecycleConfirm] = useState<'add' | 'edit' | null>(null);
  const [lifecycleConfirmChecked, setLifecycleConfirmChecked] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showProfilePwd, setShowProfilePwd] = useState(false);
  const [profileForm, setProfileForm] = useState({ username: '', password: '', confirmPassword: '' });
  const [notificationChannels, setNotificationChannels] = useState<{
    feishu:   { webhook_url: string; enabled: boolean; creator_username?: string };
    dingtalk: { webhook_url: string; enabled: boolean; secret: string; creator_username?: string };
    wechat:   { webhook_url: string; enabled: boolean; creator_username?: string };
  }>({
    feishu:   { webhook_url: '', enabled: false },
    dingtalk: { webhook_url: '', enabled: false, secret: '' },
    wechat:   { webhook_url: '', enabled: false },
  });
  const [notifyTestLoading, setNotifyTestLoading] = useState<string>('');
  const [configWorkspaceView, setConfigWorkspaceView] = useState<'source' | 'rendered' | 'checks'>('source');
  const [configScopePlatform, setConfigScopePlatform] = useState<string>('all');
  const [configScopeRole, setConfigScopeRole] = useState<string>('all');
  const [configScopeSite, setConfigScopeSite] = useState<string>('all');
  const [isLoading, setIsLoading] = useState(true);
  const currentUserRecord = users.find(u => u.username === currentUser.username);
  const currentUserLastLogin = currentUserRecord?.lastLogin || 'Never';
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
  // customCommandVars moved to useAutomation

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
    // customCommandMode is no longer used as the modal is now strictly query-only
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

  // handleAddUser and handleEditUser moved to useUserManagement hook


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
      feishu:   { webhook_url: savedChannels?.feishu?.webhook_url   || '', enabled: !!savedChannels?.feishu?.enabled, creator_username: savedChannels?.feishu?.creator_username || '' },
      dingtalk: { webhook_url: savedChannels?.dingtalk?.webhook_url || '', enabled: !!savedChannels?.dingtalk?.enabled, secret: savedChannels?.dingtalk?.secret || '', creator_username: savedChannels?.dingtalk?.creator_username || '' },
      wechat:   { webhook_url: savedChannels?.wechat?.webhook_url   || '', enabled: !!savedChannels?.wechat?.enabled, creator_username: savedChannels?.wechat?.creator_username || '' },
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
      if (linksRes.ok) {
        const linksPayload = await linksRes.json();
        if (linksPayload && typeof linksPayload === 'object' && !Array.isArray(linksPayload)) {
          setTopologyLinks(Array.isArray(linksPayload.links) ? linksPayload.links : []);
          setTopologyUnmanagedNodes(Array.isArray(linksPayload.unmanaged_nodes) ? linksPayload.unmanaged_nodes : []);
          setTopologyUnmanagedLinks(Array.isArray(linksPayload.unmanaged_links) ? linksPayload.unmanaged_links : []);
        } else {
          // Backward compat: plain array response
          setTopologyLinks(Array.isArray(linksPayload) ? linksPayload : []);
          setTopologyUnmanagedNodes([]);
          setTopologyUnmanagedLinks([]);
        }
      }
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



  useEffect(() => {
    if (!isAuthenticated) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    Promise.all([fetchSharedData(), fetchDevicesData()]).finally(() => setIsLoading(false));

    const sharedInterval = setInterval(fetchSharedData, 15000);
    // Reduce heavy full device refresh pressure while inventory table uses server-side paging.
    const devicePollMs = activeTab === 'inventory' && inventorySubPage === 'devices'
      ? 30000
      : activeTab === 'inventory' && inventorySubPage === 'interfaces'
        ? 10000
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

  // showDiff and currentDiff moved to useAutomation
  const [showImportModal, setShowImportModal] = useState(false);
  
  // Pagination State
  const [automationListPage, setAutomationListPage] = useState(1);
  // Monitoring Center hook
  const {
    monitorSearch, setMonitorSearch,
    monitorSearchResults, monitorSearching,
    monitorSelectedDevice, setMonitorSelectedDevice,
    monitorOverview,
    monitorRealtime, setMonitorRealtime,
    monitorTrend,
    monitorTrendInterface, setMonitorTrendInterface,
    monitorTrendResolution, setMonitorTrendResolution,
    monitorTrendStartInput, setMonitorTrendStartInput,
    monitorTrendEndInput, setMonitorTrendEndInput,
    monitorTrendRange, setMonitorTrendRange,
    monitorTrendZoom, setMonitorTrendZoom,
    monitorTrendDragStart, setMonitorTrendDragStart,
    monitorTrendDragEnd, setMonitorTrendDragEnd,
    monitorTrendMetrics, setMonitorTrendMetrics,
    monitorTrendUiMode, setMonitorTrendUiMode,
    monitorAlerts, monitorAlertTotal,
    monitorAlertsPage, setMonitorAlertsPage,
    monitorAlertsPageSize,
    monitorAlertsSeverity, setMonitorAlertsSeverity,
    monitorAlertsPhase, setMonitorAlertsPhase,
    monitorLoading, monitorPageVisible,
    monitorDashboardSiteFilter, setMonitorDashboardSiteFilter,
    monitorDashboardAlertFilter, setMonitorDashboardAlertFilter,
    hostResources,
    fetchMonitoringOverview, fetchMonitoringAlerts,
    fetchMonitoringRealtime, fetchHostResources,
  } = useMonitoring({ isAuthenticated, activeTab, language });

  const {
    historyRows, historyTotal, historyPage, setHistoryPage, historyPageSize, setHistoryPageSize,
    historyStatusFilter, setHistoryStatusFilter, historyTimeFilter, setHistoryTimeFilter, historyLoading,
    auditRows, auditTotal, auditPage, setAuditPage, auditPageSize, setAuditPageSize,
    auditCategoryFilter, setAuditCategoryFilter, auditSeverityFilter, setAuditSeverityFilter,
    auditStatusFilter, setAuditStatusFilter, auditTimeFilter, setAuditTimeFilter, auditLoading,
    selectedAuditEvent, setSelectedAuditEvent,
    complianceOverview, complianceFindings, complianceFindingTotal,
    compliancePage, setCompliancePage, compliancePageSize, setCompliancePageSize,
    complianceSeverityFilter, setComplianceSeverityFilter, complianceStatusFilter, setComplianceStatusFilter,
    complianceCategoryFilter, setComplianceCategoryFilter, complianceLoading, complianceRunLoading,
    selectedFinding, setSelectedFinding,
    runComplianceAudit, updateComplianceFinding, openAuditEventDetail, openComplianceFindingDetail,
  } = useHistoryAuditCompliance({ isAuthenticated, activeTab, language, currentUser, showToast });

  // Inventory Filters & Sorting
  const {
    inventoryPage,
    setInventoryPage,
    inventoryPageSize,
    setInventoryPageSize,
    inventorySearch,
    setInventorySearch,
    inventoryPlatformFilter,
    setInventoryPlatformFilter,
    inventoryRoleFilter,
    setInventoryRoleFilter,
    inventoryStatusFilter,
    setInventoryStatusFilter,
    inventoryLifecycleFilter,
    setInventoryLifecycleFilter,
    inventorySortConfig,
    setInventorySortConfig,
    selectedDeviceIds,
    setSelectedDeviceIds,
  } = useInventoryUiState();
  const {
    inventoryRefreshTick,
    setInventoryRefreshTick,
    inventoryRows,
    inventoryTotal,
    inventoryStatusCounts,
    inventoryLoading,
    assetsTotal,
  } = useInventoryPageData({
    isAuthenticated,
    activeTab,
    inventorySubPage,
    inventorySearch,
    inventoryPlatformFilter,
    inventoryRoleFilter,
    inventoryStatusFilter,
    inventoryPage,
    inventoryPageSize,
    inventorySortConfig,
    normalizeDeviceRecord,
  });

  useEffect(() => {
    const totalInventoryPages = Math.max(1, Math.ceil(inventoryTotal / inventoryPageSize));
    if (inventoryPage > totalInventoryPages) {
      setInventoryPage(totalInventoryPages);
    }
  }, [inventoryTotal, inventoryPage, inventoryPageSize]);

  // Monitoring functions/effects moved to useMonitoring hook

  const legacyHostResourceTone = hostResources?.status === 'critical'
    ? 'bg-red-500/15 text-red-200 border-red-400/25'
    : hostResources?.status === 'degraded'
      ? 'bg-amber-500/15 text-amber-100 border-amber-300/25'
      : 'bg-emerald-500/15 text-emerald-100 border-emerald-300/25';

  const legacyHostResourceSummary = hostResources
    ? `CPU ${formatResourcePercent(hostResources.cpu_percent)} · MEM ${formatResourcePercent(hostResources.memory_percent)} · DISK ${formatResourcePercent(hostResources.disk_percent)}`
    : (language === 'zh' ? '等待资源数据' : 'Waiting for resource data');
  const legacyAlertNavTone = unreadNotificationCount > 20
    ? 'bg-red-500/15 text-red-200 border-red-400/25'
    : unreadNotificationCount > 0
      ? 'bg-amber-500/15 text-amber-100 border-amber-300/25'
      : 'bg-emerald-500/15 text-emerald-100 border-emerald-300/25';

  const {
    hostResourceTone,
    hostResourceSummary,
    alertNavTone,
  } = useResourceSignals({
    hostResources,
    unreadNotificationCount,
    language,
  });

  const legacyFormatTopologyPort = (value?: string) => {
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

  const legacyFormatTopologyEvidenceLabel = (value: string) => {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return language === 'zh' ? '未知来源' : 'Unknown Source';
    if (normalized === 'lldp') return 'LLDP';
    if (normalized === 'cdp') return 'CDP';
    if (normalized === 'snmp') return 'SNMP';
    if (normalized === 'arp') return 'ARP';
    if (normalized === 'mac') return 'MAC';
    return normalized.toUpperCase();
  };

  const legacyFormatTopologyOperationalState = (state?: TopologyOperationalState) => {
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

  const legacyFormatTopologyLastSeen = (value?: string) => {
    if (!value) return language === 'zh' ? '未知' : 'Unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return language === 'zh' ? '未知' : 'Unknown';
    return date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false });
  };

  const formatTopologyPort = (value?: string) => formatTopologyPortValue(value, language);
  const formatTopologyEvidenceLabel = (value: string) => formatTopologyEvidenceLabelValue(value, language);
  const formatTopologyOperationalState = (state?: TopologyOperationalState) => formatTopologyOperationalStateValue(state, language);
  const formatTopologyLastSeen = (value?: string) => formatTopologyLastSeenValue(value, language);

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

  const {
    topologySiteOptions,
    topologyRoleOptions,
    topologyVisibleDevices,
  } = useTopologyVisibleDevices({
    devices,
    topologySearch,
    topologyStatusFilter,
    topologyRoleFilter,
    topologySiteFilter,
    topologyUnmanagedNodes,
  });

  const topologyVisibleDeviceIds = useMemo(
    () => new Set(topologyVisibleDevices.map((device) => device.id)),
    [topologyVisibleDevices],
  );

  const topologyVisibleLinks = useMemo(() => {
    const deviceMap = new Map<string, Device>();
    topologyVisibleDevices.forEach((device) => {
      deviceMap.set(device.id, device);
    });
    const managedDecoratedLinks = topologyLinks
      .filter((link) => topologyVisibleDeviceIds.has(link.source_device_id) && topologyVisibleDeviceIds.has(link.target_device_id))
      .map((link) => describeTopologyLink(link, deviceMap.get(link.source_device_id), deviceMap.get(link.target_device_id)));

    // Include unmanaged links where both endpoints are visible
    const unmanagedDecoratedLinks = topologyUnmanagedLinks
      .filter((link: any) => topologyVisibleDeviceIds.has(link.source_device_id) && topologyVisibleDeviceIds.has(link.target_device_id))
      .map((link: any) => ({
        ...link,
        operational_state: 'unknown' as TopologyOperationalState,
        operational_summary: '',
        evidence_sources: [link.discovery_source || 'lldp'],
        reverse_confirmed: false,
        source_interface_snapshot: null,
        target_interface_snapshot: null,
        is_unmanaged: true,
      }));

    return [...managedDecoratedLinks, ...unmanagedDecoratedLinks];
  }, [describeTopologyLink, topologyLinks, topologyUnmanagedLinks, topologyVisibleDeviceIds, topologyVisibleDevices]);

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

  useTopologySelectionSync({
    selectedTopologyDeviceId,
    setSelectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyLinkKey,
    topologyVisibleDevices,
    topologyDeviceLinks,
  });


  // History, Audit, Compliance effects/handlers moved to useHistoryAuditCompliance hook

  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deviceToDelete, setDeviceToDelete] = useState<string | null>(null);
  const [isDeletingSelected, setIsDeletingSelected] = useState(false);

  const {
    handleSort,
    handleDeleteDevice,
    handleDeleteSelected,
  } = useInventoryTableActions({
    selectedDeviceIds,
    inventorySortConfig,
    setInventorySortConfig,
    setDeviceToDelete,
    setIsDeletingSelected,
    setShowDeleteModal,
  });

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
    snmp_port: 161,
    lifecycle_status: 'staging'
  });

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
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    a.download = `${device.hostname}_config_${ts}.txt`;
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

  const { handleRollbackConfig } = useConfigRollbackAction({
    selectedDevice,
    setSelectedDevice,
    setDevices,
    setViewingConfig,
    setShowConfigModal,
    showToast,
  });

  const { confirmDeleteDevice } = useInventoryDeleteActions({
    deviceToDelete,
    isDeletingSelected,
    selectedDeviceIds,
    setDevices,
    setSelectedDeviceIds,
    setInventoryRefreshTick,
    showToast,
    setShowDeleteModal,
    setDeviceToDelete,
    setIsDeletingSelected,
  });

  const handleSaveEdit = async () => {
    if (!editingDevice) return;
    // Intercept: if lifecycle transitions to production, require explicit confirmation
    const oldLifecycle = editingDevice.lifecycle_status || 'staging';
    const newLifecycle = editForm.lifecycle_status || oldLifecycle;
    if (newLifecycle === 'production' && oldLifecycle !== 'production' && showLifecycleConfirm !== 'edit') {
      setLifecycleConfirmChecked(false);
      setShowLifecycleConfirm('edit');
      return;
    }
    try {
      const response = await fetch(`/api/devices/${editingDevice.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm)
      });
      if (response.ok) {
        // Save tags if tag_ids present in form
        if (editForm.tag_ids) {
          const token = localStorage.getItem('netops_token') || '';
          await fetch(`/api/tags/devices/${editingDevice.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ tag_ids: editForm.tag_ids })
          }).catch(() => {});
        }
        setDevices(prev => prev.map(d => d.id === editingDevice.id ? { ...d, ...editForm } as Device : d));
        setInventoryRefreshTick((v) => v + 1);
        setShowEditModal(false);
        setShowLifecycleConfirm(null);
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
    // Intercept: if lifecycle_status is production, require explicit confirmation
    if (addForm.lifecycle_status === 'production' && showLifecycleConfirm !== 'add') {
      setLifecycleConfirmChecked(false);
      setShowLifecycleConfirm('add');
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
        // Save tags if tag_ids present in form
        if (addForm.tag_ids && addForm.tag_ids.length > 0 && data.id) {
          const token = localStorage.getItem('netops_token') || '';
          await fetch(`/api/tags/devices/${data.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ tag_ids: addForm.tag_ids })
          }).catch(() => {});
        }
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
          snmp_port: 161,
          lifecycle_status: 'staging'
        });
        showToast('Device added successfully', 'success');
        setShowLifecycleConfirm(null);
      } else {
        showToast(`Failed to add device: ${data.error}`, 'error');
      }
    } catch (error) {
      showToast(`Error adding device: ${error}`, 'error');
    }
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
      // 测试成功 → 后端已启动后台同步，延迟几秒刷新设备数据
      if (data.success) {
        if (data.sys_name) {
          setDevices(prev => prev.map(d => d.id !== deviceId ? d : { ...d, hostname: d.hostname || data.sys_name }));
        }
        setTimeout(() => fetchDevicesData(), 5000);
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
              const linksPayload = await linksResponse.json();
              if (linksPayload && typeof linksPayload === 'object' && !Array.isArray(linksPayload)) {
                setTopologyLinks(Array.isArray(linksPayload.links) ? linksPayload.links : []);
                setTopologyUnmanagedNodes(Array.isArray(linksPayload.unmanaged_nodes) ? linksPayload.unmanaged_nodes : []);
                setTopologyUnmanagedLinks(Array.isArray(linksPayload.unmanaged_links) ? linksPayload.unmanaged_links : []);
              } else {
                setTopologyLinks(Array.isArray(linksPayload) ? linksPayload : []);
                setTopologyUnmanagedNodes([]);
                setTopologyUnmanagedLinks([]);
              }
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
    exportInventoryToExcel(devices);
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

  // ── Config Diff (hook) ──
  const configDiff = useConfigDiff({
    language,
    configSnapshots,
    loadSnapshotContent,
    showToast,
  });
  const {
    configDiffLeft, configDiffRight, diffPreSelectedDeviceId,
    diffOnlyChanges, setDiffOnlyChanges, diffShowFullBoth, setDiffShowFullBoth,
    diffFocusChangeIdx, diffBlockQuery, setDiffBlockQuery,
    diffLineRefs, activeDiffLines, activeChangeLineIndexes,
    renderedDiffLines, fullSideBySideRows, diffChangeBlocks, filteredDiffChangeBlocks,
    handleResetDiffView, handleNavigateToConfigDiff, handleSelectSnapshotPair,
    focusDiffChangeAt, jumpToDiff,
  } = configDiff;

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

  if (showSetupWizard) {
    return (
      <SetupWizard
        language={language}
        onComplete={() => setShowSetupWizard(false)}
        onLanguageChange={handleLanguagePreferenceChange}
        showToast={showToast}
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

  // runTask moved to useAutomation

  // Quick query helpers moved to useAutomation

  // Quick query — read-only command, no history saved
  // Automation handlers moved to useAutomation

  // ---------- Config Center helpers ----------
  const takeConfigSnapshot = async (device: Device, trigger: ConfigSnapshot['trigger'] = 'manual') => {
    const MOCK_IPS = ['127.0.0.1', '0.0.0.0', 'localhost'];
    if (MOCK_IPS.includes(device.ip_address || '')) {
      showToast(language === 'zh'
        ? `${device.hostname} (${device.ip_address}) 为模拟设备，无法备份真实配置`
        : `${device.hostname} (${device.ip_address}) is a mock device, cannot backup real config`, 'error');
      return null;
    }
    setIsTakingSnapshot(true);
    try {
      // Step 1: fetch live config from device
      let configContent = '';
      let fetchSuccess = false;
      try {
        const _p = (device.platform || '').toLowerCase();
        const _cmd = (_p.includes('cisco') || _p.includes('arista') || _p.includes('rgos'))
          ? 'show running-config'
          : (_p.includes('juniper') || _p.includes('junos'))
            ? 'show configuration'
            : 'display current-configuration';
        const _token = localStorage.getItem('netops_token');
        const execResp = await fetch('/api/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(_token ? { Authorization: `Bearer ${_token}` } : {}) },
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
          const output = execData.output || '';
          // Reject mock driver output
          if (output && !output.startsWith('[Mock ') && !output.startsWith('% ')) {
            configContent = output;
            fetchSuccess = true;
          }
        }
      } catch {
        // device unreachable
      }

      if (!fetchSuccess || !configContent.trim()) {
        showToast(language === 'zh'
          ? `${device.hostname} 配置获取失败，无法建立备份`
          : `Failed to fetch config from ${device.hostname}, backup skipped`, 'error');
        return null;
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
  // Save schedule config
  const saveScheduleConfig = async () => {
    setScheduleLoading(true);
    try {
      const resp = await fetch('/api/configs/schedule', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: scheduleEnabled, cron: scheduleCron })
      });
      if (resp.ok) showToast(t('scheduleUpdated'), 'success');
      else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || 'Invalid schedule', 'error');
      }
    } catch { /* ignore */ }
    finally { setScheduleLoading(false); }
  };

  const handleSearchConfigSnapshots = async (query = configSnapshotKeyword) => {
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true, q: query });
  };

  const handleClearConfigSnapshotSearch = async () => {
    setConfigSnapshotKeyword('');
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true, q: '' });
  };

  const handleRunBackupAllOnline = async () => {
    const MOCK_IPS = ['127.0.0.1', '0.0.0.0', 'localhost'];
    const online = devices.filter(
      (device) => device.status === 'online' && !MOCK_IPS.includes(device.ip_address || '')
    );
    if (online.length === 0) {
      showToast(language === 'zh' ? '没有可备份的真实在线设备' : 'No real online devices to backup', 'error');
      return;
    }
    showToast(`${t('backupStarted')} (${online.length} ${t('devicesOnline')})`, 'info');
    let success = 0;
    let failed = 0;
    for (const device of online) {
      const snap = await takeConfigSnapshot(device, 'manual');
      if (snap) success++;
      else failed++;
    }
    const summary = language === 'zh'
      ? `备份完成: ${success} 成功${failed > 0 ? `, ${failed} 失败` : ''}`
      : `Backup complete: ${success} succeeded${failed > 0 ? `, ${failed} failed` : ''}`;
    showToast(summary, failed > 0 ? 'error' : 'success');
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true });
  };

  const handleBackupSingleDevice = async (deviceId: string) => {
    const device = devices.find(d => d.id === deviceId);
    if (!device) return;
    await takeConfigSnapshot(device, 'manual');
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

  const handleCopyConfigSnapshot = async (snapshot: ConfigSnapshot) => {
    const content = await loadSnapshotContent(snapshot);
    const copied = await copyTextWithFallback(content);
    showToast(copied ? t('configCopied') : (language === 'zh' ? '复制失败' : 'Copy failed'), copied ? 'success' : 'error');
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

  const mainContentProps = {
    activeTab,
    inventorySubPage,
    configPage,
    automationPage,
    changeOrderPage,
    language,
    t,
    navigate,
    navTo,
    showToast,
    currentUser,
    devices,
    jobs,
    notifications,
    hostResources,
    users,
    trendDays,
    setTrendDays,
    complianceTrend,
    platformData,
    dashBannerCollapsed,
    setDashBannerCollapsed,
    dashLastRefresh,
    monitorSearch,
    setMonitorSearch,
    monitorSearchResults,
    monitorSearching,
    monitorSelectedDevice,
    setMonitorSelectedDevice,
    monitorOverview,
    monitorRealtime,
    monitorTrend,
    monitorTrendInterface,
    setMonitorTrendInterface,
    monitorTrendResolution,
    setMonitorTrendResolution,
    monitorTrendStartInput,
    setMonitorTrendStartInput,
    monitorTrendEndInput,
    setMonitorTrendEndInput,
    monitorTrendRange,
    setMonitorTrendRange,
    monitorTrendZoom,
    setMonitorTrendZoom,
    monitorTrendDragStart,
    setMonitorTrendDragStart,
    monitorTrendDragEnd,
    setMonitorTrendDragEnd,
    monitorTrendMetrics,
    setMonitorTrendMetrics,
    monitorTrendUiMode,
    setMonitorTrendUiMode,
    monitorAlerts,
    monitorAlertTotal,
    monitorAlertsPage,
    setMonitorAlertsPage,
    monitorAlertsPageSize,
    monitorAlertsSeverity,
    setMonitorAlertsSeverity,
    monitorAlertsPhase,
    setMonitorAlertsPhase,
    monitorLoading,
    monitorPageVisible,
    monitorDashboardSiteFilter,
    setMonitorDashboardSiteFilter,
    monitorDashboardAlertFilter,
    setMonitorDashboardAlertFilter,
    inventoryRows,
    inventoryTotal,
    inventoryStatusCounts,
    inventoryPage,
    setInventoryPage,
    inventoryPageSize,
    setInventoryPageSize,
    inventorySearch,
    setInventorySearch,
    inventoryPlatformFilter,
    setInventoryPlatformFilter,
    inventoryRoleFilter,
    setInventoryRoleFilter,
    inventoryStatusFilter,
    setInventoryStatusFilter,
    inventoryLifecycleFilter,
    setInventoryLifecycleFilter,
    inventorySortConfig,
    inventoryLoading,
    selectedDeviceIds,
    setSelectedDeviceIds,
    handleSort,
    handleImport,
    handleExport,
    handleDeleteDevice,
    handleDeleteSelected,
    handleShowDetails,
    handleTestConnection,
    deviceConnectionChecks,
    connectionTestingDeviceId,
    setShowAddModal,
    setShowEditModal,
    setEditingDevice,
    setEditForm,
    setSelectedDevice,
    setActiveTab,
    devicesLastUpdatedAt,
    snmpTestingId,
    snmpSyncingId,
    handleSnmpTest,
    handleSnmpSyncNow,
    sectionHeaderRowClass,
    scenarios,
    platforms,
    selectedScenario,
    scenarioSearch,
    playbookVars,
    playbookPreview,
    playbookPlatform,
    playbookDeviceIds,
    playbookConcurrency,
    playbookDryRun,
    executionStatus,
    quickPlaybookScenario,
    quickPlaybookVars,
    quickPlaybookPlatform,
    quickPlaybookDryRun,
    quickPlaybookConcurrency,
    quickPlaybookPreview,
    quickRiskConfirmed,
    filteredScenarios,
    quickMissingRequiredFields,
    quickHasMixedPlatforms,
    quickPlatformMismatch,
    isQuickPlaybookRunning,
    quickExecutionResult,
    wsCompleteMsg,
    deviceStatusMap,
    quickQueryRunning,
    quickQueryOutput,
    quickQueryLabel,
    quickQueryStructured,
    quickQueryView,
    quickQueryMaximized,
    quickQueryCommands,
    changeTicket,
    setChangeTicket,
    quickQueryTable,
    savedQueries,
    handleAutomationSearch,
    handleScenarioSearch,
    handleToggleBatchMode,
    handleToggleBatchDevice,
    handleSelectAutomationDevice,
    batchMode,
    batchDeviceIds,
    automationSearch,
    hasQuickTargets,
    openQuickPlaybookModal,
    handleClearQuickScenario,
    runQuickPlaybook,
    runQuickQuery,
    handleResetQuickQuery,
    setQuickQueryView,
    setQuickQueryMaximized,
    exportQuickQueryTable,
    copyTextWithFallback,
    handleResetQuickExecutionState,
    handlePlaybookPlatformChange,
    handlePlaybookVariableChange,
    handleSelectPlaybookScenario,
    openManualScenarioDraft,
    executePlaybook,
    complianceOverview,
    complianceFindings,
    complianceFindingTotal,
    complianceSeverityFilter,
    setComplianceSeverityFilter,
    complianceStatusFilter,
    setComplianceStatusFilter,
    complianceCategoryFilter,
    setComplianceCategoryFilter,
    compliancePage,
    setCompliancePage,
    compliancePageSize,
    setCompliancePageSize,
    complianceLoading,
    complianceRunLoading,
    runComplianceAudit,
    openComplianceFindingDetail,
    updateComplianceFinding,
    isTakingSnapshot,
    handleRunBackupAllOnline,
    handleBackupSingleDevice,
    handleNavigateToConfigDiff,
    diffPreSelectedDeviceId,
    activeDiffLines,
    activeChangeLineIndexes,
    diffFocusChangeIdx,
    diffOnlyChanges,
    diffShowFullBoth,
    renderedDiffLines,
    fullSideBySideRows,
    diffChangeBlocks,
    filteredDiffChangeBlocks,
    diffBlockQuery,
    diffLineRefs,
    focusDiffChangeAt,
    configDiffLeft,
    configDiffRight,
    handleResetDiffView,
    handleSelectSnapshotPair,
    jumpToDiff,
    setDiffOnlyChanges,
    setDiffShowFullBoth,
    setDiffBlockQuery,
    configTemplates,
    configVariableKeys,
    configMissingVariables,
    configScopedDevices,
    configScopedOnlineCount,
    configReadinessScore,
    configValidationIssues,
    configValidationWarnings,
    configWorkspaceView,
    selectedTemplateId,
    selectedConfigTemplate,
    globalVars,
    editorContent,
    configRenderedPreview,
    configScopePlatform,
    configScopeRole,
    configScopeSite,
    configPlatformOptions,
    configRoleOptions,
    configSiteOptions,
    extractVars,
    getPlatformLabel,
    handleImportVars,
    handleNewTemplate,
    handleAddVar,
    handleDeleteVar,
    handleDiscardChanges,
    setConfigWorkspaceView,
    setSelectedTemplateId,
    setEditorContent,
    setConfigTemplates,
    showAddUserModal,
    setShowAddUserModal,
    showEditUserModal,
    setShowEditUserModal,
    editingUser,
    setEditingUser,
    newUserForm,
    setNewUserForm,
    editUserForm,
    setEditUserForm,
    showNewUserPwd,
    setShowNewUserPwd,
    showEditUserPwd,
    setShowEditUserPwd,
    handleAddUser,
    handleEditUser,
    auditRows,
    auditTotal,
    auditPage,
    setAuditPage,
    auditPageSize,
    setAuditPageSize,
    auditLoading,
    auditCategoryFilter,
    setAuditCategoryFilter,
    auditSeverityFilter,
    setAuditSeverityFilter,
    auditStatusFilter,
    setAuditStatusFilter,
    auditTimeFilter,
    setAuditTimeFilter,
    assetsTotal,
    scheduledTasks,
    unreadNotificationCount,
    fetchMonitoringOverview,
    fetchMonitoringAlerts,
    fetchMonitoringRealtime,
    fetchHostResources,
    setMonitorRealtime,
    setSelectedTopologyDeviceId,
    setSelectedTopologyLinkKey,
    setInventoryRefreshTick,
    topologyDiscoveryRunning,
    topologyStats,
    topologyLinkStats,
    topologySearch,
    topologySiteFilter,
    topologyRoleFilter,
    topologyStatusFilter,
    topologySiteOptions,
    topologyRoleOptions,
    topologyVisibleDevices,
    topologyVisibleLinks,
    selectedTopologyDeviceId,
    selectedTopologyLinkKey,
    selectedTopologyDevice,
    selectedTopologyLink,
    topologyNeighborDevices,
    topologyDeviceLinks,
    topologyPriorityDevices,
    topologyOrphanDevices,
    topologyRef,
    handleTriggerDiscovery,
    handleExportMap,
    setTopologySearch,
    setTopologySiteFilter,
    setTopologyRoleFilter,
    setTopologyStatusFilter,
    formatTopologyPort,
    formatTopologyInterfaceTelemetry,
    formatTopologyLastSeen,
    formatTopologyOperationalState,
    formatTopologyEvidenceLabel,
    getTopologyOperationalTone,
    setShowCustomCommandModal,
    setQuickPlaybookVars,
    setQuickPlaybookConcurrency,
    setQuickRiskConfirmed,
    setShowCmdPreviewModal,
    handleTogglePlaybookDevice,
    setPlaybookConcurrency,
    previewPlaybook,
    playbookExecutions,
    playbookHistoryTotal,
    playbookHistoryPage,
    playbookHistoryStatusFilter,
    playbookHistoryScenarioSearch,
    activeExecutionId,
    wsMessages,
    selectedExecutionLoading,
    selectedExecutionDetail,
    selectedDeviceDetail,
    selectedDeviceDetailLoading,
    selectedExecDevices,
    selectedExecDevicesTotal,
    selectedExecDevicesPage,
    selectedExecDevicesStatusFilter,
    selectedExecDevicesLoading,
    handleRefreshHistory,
    setPlaybookHistoryScenarioSearch,
    setPlaybookHistoryPage,
    setPlaybookHistoryStatusFilter,
    handleSelectExecution,
    handleDeleteExecution,
    handleExecDevicesStatusFilterChange,
    handleExecDevicesPageChange,
    handleSelectExecDevice,
    handleValidateTemplateWorkspace,
    openAuditEventDetail,
    findMatchingPlatform,
    handleRerun,
  };

  return (
    <AppRuntimeBoundary language={language}>
      <AppLayout
        language={language}
        resolvedTheme={resolvedTheme}
        themeMode={themeMode}
        sidebarCollapsed={sidebarCollapsed}
        activeTab={activeTab}
        pageTitle={pageTitle}
        currentUser={currentUser as any}
        currentUserRole={currentUser.role || currentUserRecord?.role || 'Viewer'}
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
        onNotificationClick={(item) => {
          setShowNotifications(false);
          if (item.id.startsWith('alert-')) {
            navigate('/alerts');
          } else if (item.id.startsWith('job-')) {
            navigate('/automation/execute');
          } else if (item.id.startsWith('playbook-')) {
            navigate('/automation/execute');
          }
        }}
        onNavigate={(path) => navigate(path)}
        cmdPaletteOpen={cmdPaletteOpen}
        cmdPaletteQuery={cmdPaletteQuery}
        cmdPaletteFiltered={cmdPaletteFiltered}
        pinnedPaths={pinnedPaths}
        setCmdPaletteOpen={setCmdPaletteOpen}
        setCmdPaletteQuery={setCmdPaletteQuery}
        togglePin={togglePin}
        toast={toast}
        onCloseToast={() => setToast(null)}
      >

        <AppMainContent appProps={mainContentProps} />

      {/* ── Command Preview Modal ── */}
      {showCustomCommandModal && (
        <CustomCommandModal
          language={language}
          t={t}
          customCommand={customCommand}
          customCommandVars={customCommandVars}
          scriptVars={scriptVars}
          batchMode={batchMode}
          batchDeviceIds={batchDeviceIds}
          selectedDevice={selectedDevice}
          isBatchRunning={isBatchRunning}
          isTestingConnection={isAutomationTaskRunning}
          showFavorites={showFavorites}
          commandFavorites={commandFavorites}
          commandHistory={commandHistory}
          onClose={closeCustomCommandModal}
          onSubmit={submitCustomCommand}
          onCustomCommandChange={onCustomCommandChange}
          onScriptVarChange={(key, value) => setScriptVars((prev) => ({ ...prev, [key]: value }))}
          onToggleFavorite={saveFavorite}
          isFavorited={isFavorited}
          onSaveQuickQuery={() => setSaveQuickQueryModalOpen(true)}
          onToggleFavorites={() => setShowFavorites((prev) => !prev)}
          onUseFavorite={setCustomCommand}
        />
      )}

      {/* ── Save Quick Query Modal ── */}
      {saveQuickQueryModalOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-md flex items-center justify-center z-[100] p-4" onClick={() => setSaveQuickQueryModalOpen(false)}>
          <motion.div
            initial={{ scale: 0.9, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            className="w-full max-w-md bg-white rounded-3xl shadow-2xl border border-black/5 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-2xl bg-cyan-500 flex items-center justify-center shadow-lg shadow-cyan-500/30">
                  <Plus size={20} className="text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900">{language === 'zh' ? '保存到快捷查询' : 'Save to Quick Query'}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{language === 'zh' ? '为您的命令起一个易于识别的名称' : 'Give your command a recognizable name'}</p>
                </div>
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[11px] font-bold uppercase tracking-wider text-gray-400 ml-1">
                    {language === 'zh' ? '查询名称' : 'Query Name'}
                  </label>
                  <input
                    autoFocus
                    type="text"
                    value={quickQuerySaveLabel}
                    onChange={(e) => setQuickQuerySaveLabel(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSaveQuickQuery()}
                    placeholder={language === 'zh' ? '例如：核心交换机版本检查' : 'e.g. Core Switch Version Check'}
                    className="w-full px-4 py-3 rounded-xl border border-gray-100 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all text-sm font-medium"
                  />
                </div>

                <div className="p-3.5 rounded-2xl bg-gray-50 border border-gray-100">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">{language === 'zh' ? '命令预览' : 'Command Preview'}</p>
                  <code className="text-xs font-mono text-cyan-700 break-all line-clamp-3 leading-relaxed">
                    {customCommand}
                  </code>
                </div>
              </div>

              <div className="flex items-center gap-3 mt-8">
                <button
                  onClick={() => setSaveQuickQueryModalOpen(false)}
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-bold text-gray-500 hover:bg-gray-50 transition-all border border-transparent"
                >
                  {language === 'zh' ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={handleSaveQuickQuery}
                  disabled={!quickQuerySaveLabel.trim()}
                  className={`flex-[2] px-4 py-2.5 rounded-xl text-sm font-extrabold text-white shadow-lg transition-all ${
                    quickQuerySaveLabel.trim() 
                      ? 'bg-cyan-500 hover:bg-cyan-600 shadow-cyan-500/30' 
                      : 'bg-gray-200 cursor-not-allowed shadow-none'
                  }`}
                >
                  {language === 'zh' ? '确认保存' : 'Save Query'}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
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

      {/* Lifecycle → Production Confirmation Modal */}
      {showLifecycleConfirm && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center gap-3 border-b border-black/5 bg-amber-50 p-5 rounded-t-2xl">
              <div className="rounded-lg bg-amber-100 p-2 text-amber-600">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              </div>
              <h3 className="text-base font-semibold text-black">
                {language === 'zh' ? '投产确认' : 'Production Confirmation'}
              </h3>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-sm text-black/70 leading-relaxed">
                {language === 'zh'
                  ? '您正在将设备状态设置为「已投产」。请确认该设备的默认口令已完成上手（密码已从出厂默认修改为正式口令）。'
                  : 'You are setting this device to "Production". Please confirm that the default credentials have been changed from factory defaults to production passwords.'}
              </p>
              <label className="flex items-start gap-2.5 cursor-pointer select-none group">
                <input
                  type="checkbox"
                  checked={lifecycleConfirmChecked}
                  onChange={(e) => setLifecycleConfirmChecked(e.target.checked)}
                  className="mt-0.5 rounded border-black/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                />
                <span className="text-sm font-medium text-black/80 group-hover:text-black">
                  {language === 'zh'
                    ? '我确认该设备默认口令已上手，密码已修改为正式口令'
                    : 'I confirm the default credentials have been changed to production passwords'}
                </span>
              </label>
            </div>
            <div className="flex gap-3 border-t border-black/5 bg-black/[0.01] p-5 rounded-b-2xl">
              <button
                onClick={() => { setShowLifecycleConfirm(null); setLifecycleConfirmChecked(false); }}
                className="flex-1 rounded-xl border border-black/10 px-4 py-2.5 text-xs font-bold uppercase tracking-widest transition-all hover:bg-black/5"
              >
                {language === 'zh' ? '取消' : 'Cancel'}
              </button>
              <button
                disabled={!lifecycleConfirmChecked}
                onClick={() => {
                  if (showLifecycleConfirm === 'add') {
                    handleAddDevice();
                  } else {
                    handleSaveEdit();
                  }
                }}
                className={`flex-1 rounded-xl px-4 py-2.5 text-xs font-bold uppercase tracking-widest text-white shadow-lg transition-all
                  ${lifecycleConfirmChecked
                    ? 'bg-amber-500 shadow-amber-500/20 hover:bg-amber-600 cursor-pointer'
                    : 'bg-black/20 shadow-none cursor-not-allowed'}`}
              >
                {language === 'zh' ? '确认投产' : 'Confirm Production'}
              </button>
            </div>
          </div>
        </div>
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
        event={selectedAuditEvent as any}
        language={language}
        t={t}
        onClose={() => setSelectedAuditEvent(null)}
      />

      <ComplianceFindingDetailModal
        finding={selectedFinding as any}
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
    </AppLayout>
    </AppRuntimeBoundary>
  );
};

export default App;
