import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'motion/react';
import { Routes, Route, useLocation, useNavigate, Navigate } from 'react-router-dom';
import { Plus, Server, CheckCircle, CheckCircle2, XCircle, RotateCcw, Play, Activity, LayoutDashboard, Database, Zap, ShieldCheck, History, LogOut, Search, Bell, Settings, Download, Upload, FileText, ChevronLeft, ChevronRight, Filter, Globe, TrendingUp, PieChart as PieChartIcon, Clock, Edit2, AlertCircle, FolderOpen, Eye, EyeOff, Sun, Moon, User as UserIcon, ChevronDown, Copy, Menu, PanelLeftClose, Monitor, ExternalLink, Trash2, Wrench, Maximize2, Minimize2, BarChart3, GitCompareArrows, Cpu, Network, Pin, AlertTriangle, X } from 'lucide-react';
import { useUiStore } from './store/uiStore';
import { useConfigStore } from './store/configStore';
import { useAutomationStore } from './store/automationStore';
import { useI18n } from './i18n.tsx';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell } from 'recharts';
import type { ConfigVersion, Device, Job, AuditEvent, ComplianceFinding, ComplianceRunPoint, ComplianceOverview, ScheduledTask, Script, ConfigTemplate, ConfigSnapshot, DiffLine, User as UserType, ThemeMode, SessionUser, NotificationItem, HostResourceSnapshot, DeviceHealthAlertItem, DeviceHealthDetailResponse, DeviceHealthTrendResponse, DeviceConnectionCheckSummary } from './types';
import { PLATFORM_LABELS, getPlatformLabel, getVendorFromPlatform } from './types';
import { sectionHeaderRowClass, sectionToolbarClass, primaryActionBtnClass, secondaryActionBtnClass, darkActionBtnClass, severityBadgeClass, complianceStatusBadgeClass, auditStatusBadgeClass } from './components/shared';
import Pagination from './components/Pagination';
import DeviceFormModal from './components/DeviceFormModal';
import DeviceDetailModal from './components/DeviceDetailModal';
import CustomCommandModal from './components/CustomCommandModal';
import AddScenarioModal from './components/AddScenarioModal';
import AppLayout from './components/AppLayout';
import AppMainContent from './components/AppMainContent';
import { AppRuntimeBoundary } from './components/AppRuntimeBoundary';
import type { ToastState } from './components/ToastNotification';
import ProfileModal, { ProfileFormState } from './components/ProfileModal';
import CommandPreviewModal from './components/CommandPreviewModal';
import TerminalWindow from './components/access/TerminalWindow';
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
import { AppModals } from './components/modals/AppModals';
import { buildConnectionTestMessage, buildConnectionTestHint, buildConnectionCheckStatus, connectionCheckBadgeMeta, formatConnectionCheckTime } from './utils/connectionHelpers';
import { useConfigDiff } from './hooks/useConfigDiff';
import { useTheme } from './hooks/useTheme';
import { useNotifications } from './hooks/useNotifications';
import { useAuth } from './hooks/useAuth';
import { useInventory } from './hooks/useInventory';
import { useInventoryStore } from './store/inventoryStore';
import { useInventoryDeleteActions } from './hooks/useInventoryDeleteActions';
import { useAutomation } from './hooks/useAutomation';
import { useMonitoring } from './hooks/useMonitoring';
import { useUserManagement } from './hooks/useUserManagement';
import { useHistoryAuditCompliance } from './hooks/useHistoryAuditCompliance';
import { useTopologyVisibleDevices } from './hooks/useTopologyVisibleDevices';
import { useTopologySelectionSync } from './hooks/useTopologySelectionSync';
import { useResourceSignals } from './hooks/useResourceSignals';
import { useConfigRollbackAction } from './hooks/useConfigRollbackAction';
import { exportInventoryToExcel } from './utils/inventoryExport';
import { copyTextWithFallback } from './utils/clipboard';
import { getTopologyOperationalTone, type TopologyOperationalState } from './utils/topologyCore';
import { formatResourcePercent, formatCompactResourcePercent } from './utils/resourceFormatters';
import {
  formatTopologyPort as formatTopologyPortValue,
  formatTopologyEvidenceLabel as formatTopologyEvidenceLabelValue,
  formatTopologyOperationalState as formatTopologyOperationalStateValue,
  formatTopologyLastSeen as formatTopologyLastSeenValue,
} from './utils/topologyFormatters';
import { getRouteContext } from './utils/routeContext';
import { avatarPresets, renderAvatarContent } from './utils/avatarPresets';
import { usePageTitle } from './hooks/usePageTitle';
import { useCommandPalette } from './hooks/useCommandPalette';
import { useUserProfile } from './hooks/useUserProfile';
import { useScenarioDraft } from './hooks/useScenarioDraft';
import { useTopology } from './hooks/useTopology';
import { useConfigWorkspace } from './hooks/useConfigWorkspace';
import { useConfigSnapshots } from './hooks/useConfigSnapshots';
import { useDeviceFormActions } from './hooks/useDeviceFormActions';
import { useDeviceConnectionAndSnmp } from './hooks/useDeviceConnectionAndSnmp';
import { useDeviceDetail } from './hooks/useDeviceDetail';
import { useInventoryImportExport } from './hooks/useInventoryImportExport';
import { AppProviders } from './contexts/AppProviders';

// Types imported from ./types — re-export User as UserType to avoid clash with lucide-react User icon


// Sparkline imported from ./components/Sparkline

const App: React.FC = () => {

  const {
    sidebarCollapsed, setSidebarCollapsed,
    showSetupWizard, setShowSetupWizard,
    showUserMenu, setShowUserMenu,
    showNotifications, setShowNotifications,
    cmdPaletteOpen, setCmdPaletteOpen,
    isMobile, setIsMobile,
    showAddScenarioModal, setShowAddScenarioModal
  } = useUiStore();

  const {
    retentionDays, setRetentionDays,
    configSnapshots, setConfigSnapshots,
    configSnapshotsLoading, setConfigSnapshotsLoading,
    configCenterDevice, setConfigCenterDevice,
    configViewContent, setConfigViewContent,
    configViewSnapshot, setConfigViewSnapshot,
    configSnapshotKeyword, setConfigSnapshotKeyword,
    configSearchQuery, setConfigSearchQuery,
    configSearchResults, setConfigSearchResults,
    configSearchLoading, setConfigSearchLoading,
    isTakingSnapshot, setIsTakingSnapshot,
    activeBackupRunId, setActiveBackupRunId,
    scheduleEnabled, setScheduleEnabled,
    scheduleCron, setScheduleCron,
    scheduleLoading, setScheduleLoading
  } = useConfigStore();

  const {
    playbookHistoryPage, setPlaybookHistoryPage,
    playbookHistoryTotal, setPlaybookHistoryTotal,
    playbookHistoryStatusFilter, setPlaybookHistoryStatusFilter,
    playbookHistoryScenarioSearch, setPlaybookHistoryScenarioSearch,
    selectedExecDevices, setSelectedExecDevices,
    selectedExecDevicesTotal, setSelectedExecDevicesTotal,
    selectedExecDevicesPage, setSelectedExecDevicesPage,
    selectedExecDevicesStatusFilter, setSelectedExecDevicesStatusFilter,
    selectedExecDevicesLoading, setSelectedExecDevicesLoading,
    selectedExecutionDetail, setSelectedExecutionDetail,
    selectedExecutionLoading, setSelectedExecutionLoading,
    selectedDeviceDetail, setSelectedDeviceDetail,
    selectedDeviceDetailLoading, setSelectedDeviceDetailLoading,
    newScenarioForm, setNewScenarioForm,
    newScenarioVariables, setNewScenarioVariables,
    scenarioDraftOrigin, setScenarioDraftOrigin,
    isSavingScenario, setIsSavingScenario
  } = useAutomationStore();
  const { t, language, setLanguage } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const { themeMode, setThemeMode, resolvedTheme } = useTheme();
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    // 自动清除
    setTimeout(() => {
      setToast(null);
    }, 5000);
  }, []);

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
    handleSwitchUser,
    rememberMe,
    setRememberMe,
    showLoginPwd,
    setShowLoginPwd,
    mfaRequired,
    setMfaRequired,
    handleMfaVerify,
  } = useAuth({
    language,
    setLanguage,
    showToast,
    setShowSetupWizard,
    setShowUserMenu,
    setShowNotifications,
  });

  const routeContext = useMemo(() => getRouteContext(location.pathname), [location.pathname]);
  const { activeTab, configPage, automationPage, inventorySubPage, changeOrderPage, ipamPage, cmdbPage } = routeContext;



  const deviceFetchMode = useMemo<'light' | 'full'>(() => {
    if (activeTab === 'inventory') return 'full';
    if (activeTab === 'automation') return 'full';
    if (activeTab === 'config') return 'full';
    if (activeTab === 'topology') return 'full';
    if (activeTab === 'access') return 'full';
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
    loadScenarios, loadPlaybookHistory, loadJobs, loadUpcomingTasks, runPlaybook, openQuickPlaybookModal, loadQuickPlaybookPreview, previewPlaybook, executePlaybook, resetAutomationSubmenuState,
    runQuickPlaybook, runQuickQuery, handleResetQuickQuery, handleToggleBatchMode, handleToggleBatchDevice, handleSelectAutomationDevice, handleClearQuickScenario, handleResetQuickExecutionState, exportQuickQueryTable,
    extractVars, splitLines,
    saveQuickQueryModalOpen, setSaveQuickQueryModalOpen, quickQuerySaveLabel, setQuickQuerySaveLabel,
    handleSaveQuickQuery,
    savedQueries,
    handleRerun,
    handleClearSelection
  } = useAutomation({ currentUser, language, showToast, navigate, setSelectedDevice, devices, selectedDevice, activeTab, automationPage });

  const {
    globalVars,
    setGlobalVars,
    configTemplates,
    setConfigTemplates,
    selectedTemplateId,
    setSelectedTemplateId,
    editorContent,
    setEditorContent,
    configWorkspaceView,
    setConfigWorkspaceView,
    configScopePlatform,
    setConfigScopePlatform,
    configScopeRole,
    setConfigScopeRole,
    configScopeSite,
    setConfigScopeSite,
    selectedConfigTemplate,
    configVariableKeys,
    configVariableMap,
    configMissingVariables,
    configRenderedPreview,
    configPlatformOptions,
    configRoleOptions,
    configSiteOptions,
    configScopedDevices,
    configScopedOnlineCount,
    configValidationIssues,
    configValidationWarnings,
    configReadinessScore,
    refreshConfigWorkspace,
    handleImportVars,
    handleNewTemplate,
    handleAddVar,
    handleDeleteVar,
    handleDiscardChanges,
    handleValidateTemplateWorkspace,
    handleSaveTemplate,
  } = useConfigWorkspace({ devices, language, showToast, currentUser, extractVars });

  const findMatchingPlatform = useCallback((devicePlatform: string, platforms: string[] | Record<string, any>) => {
    if (!devicePlatform) return undefined;
    const pList = Array.isArray(platforms) ? platforms : Object.keys(platforms);
    const dp = devicePlatform.toLowerCase();
    return pList.find(p => {
      const target = p.toLowerCase();
      return dp === target || dp.includes(target) || target.includes(dp);
    });
  }, []);

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

  // getVendorFromPlatform, PLATFORM_LABELS, getPlatformLabel imported from ./types

  // Quick Query (read-only commands, no history saved)

  // ---------- Config Center ----------
  // Schedule state
  const {
    pinnedPaths,
    togglePin,
    cmdPaletteQuery,
    setCmdPaletteQuery,
    cmdPaletteFiltered,
  } = useCommandPalette({ language, t });
  // showCustomCommandModal moved to useAutomation
  // showCmdPreviewModal moved to useAutomation
  // History pagination & lazy device loading

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

  const {
    setTopologyLinks,
    setTopologyUnmanagedNodes,
    setTopologyUnmanagedLinks,
    topologySearch,
    setTopologySearch,
    topologyStatusFilter,
    setTopologyStatusFilter,
    topologyRoleFilter,
    setTopologyRoleFilter,
    topologySiteFilter,
    setTopologySiteFilter,
    selectedTopologyDeviceId,
    setSelectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyLinkKey,
    topologyDiscoveryRunning,
    topologyRef,
    hideStaleLinks,
    setHideStaleLinks,
    hideOrphanDevices,
    setHideOrphanDevices,
    topologySiteOptions,
    topologyRoleOptions,
    topologyVisibleDevices,
    topologyVisibleLinks,
    topologyDeviceLinks,
    topologyStats,
    topologyLinkStats,
    selectedTopologyDevice,
    selectedTopologyLink,
    topologyNeighborDevices,
    topologyOrphanDevices,
    topologyPriorityDevices,
    formatTopologyInterfaceTelemetry,
    handleExportMap,
    handleTriggerDiscovery,
  } = useTopology({ devices, language, showToast });

  // Redirect bare paths and legacy paths to standardized hierarchical paths
  React.useEffect(() => {
    const p = location.pathname;
    const redirects: Record<string, string> = {
      '/monitor': '/monitor/overview',
      '/access': '/access/workspace',
      '/alerts': '/alerts/desk',
      '/assets': '/assets/dashboard',
      '/config': '/config/backup',
      '/automation': '/automation/tasks',
      '/change-orders': '/change-orders/all',
      '/capacity': '/capacity/analysis',
      '/management': '/management/audit',
      '/overview': '/monitor/overview',
      '/monitoring': '/monitor/telemetry',
      '/topology': '/monitor/topology',
      '/pam-audit': '/access/pam-audit',
      '/alert-history': '/alerts/history',
      '/alert-rules': '/alerts/rules',
      '/maintenance': '/alerts/maintenance',
      '/inventory/devices': '/assets/devices',
      '/inventory/servers': '/assets/servers',
      '/ip-locator': '/assets/toolbox',
      '/path-diagnose': '/assets/diagnose',
      '/nsot': '/assets/nsot',
      '/tags': '/assets/tags',
      '/racks': '/cmdb/racks',
      '/assets/racks': '/cmdb/racks',
      '/audit': '/management/audit',
      '/users': '/management/users',
      '/credentials': '/management/credentials',
    };
    if (p === '/ipam') {
      navigate('/ipam/prefixes', { replace: true });
    } else if (p === '/cmdb') {
      navigate('/cmdb/credentials', { replace: true });
    } else if (redirects[p]) {
      navigate(redirects[p], { replace: true });
    }
  }, [location.pathname, navigate]);
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

  const pageTitle = usePageTitle({
    activeTab,
    automationPage,
    configPage,
    inventorySubPage,
    changeOrderPage,
    ipamPage,
    cmdbPage,
    language,
    t,
  });


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

  const {
    resetScenarioDraft,
    openManualScenarioDraft,
    createScenario,
    inferScenarioVariableType,
    formatScenarioVariableLabel,
  } = useScenarioDraft({
    showToast,
    splitLines,
    loadScenarios,
    openQuickPlaybookModal,
    navigate,
  });

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


  // When entering config_center tab, refresh snapshots + schedule (handled by useConfigSnapshots)

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

  // Fetch actual users for account switching AFTER setUsers is initialized
  useEffect(() => {
    if (isAuthenticated) {
      const token = localStorage.getItem('netops_token');
      fetch('/api/users', { 
        headers: token ? { Authorization: `Bearer ${token}` } : {} 
      })
        .then(r => r.json())
        .then(data => {
          if (Array.isArray(data)) setUsers(data);
        })
        .catch(() => {});
    }
  }, [isAuthenticated, setUsers]);
  const [trendDays, setTrendDays] = useState<7 | 30>(7);
  const [dashBannerCollapsed, setDashBannerCollapsed] = useState(false);
  const [dashLastRefresh, setDashLastRefresh] = useState<Date>(new Date());
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const currentUserRecord = users.find(u => u.username === currentUser.username);
  const currentUserLastLogin = currentUserRecord?.lastLogin || 'Never';
  const currentAvatar = currentUser.avatar_url || currentUserRecord?.avatar_url || '';

  const {
    showProfileModal, setShowProfileModal,
    showProfilePwd, setShowProfilePwd,
    profileForm, setProfileForm,
    profileAvatarPreview, setProfileAvatarPreview,
    notificationChannels, setNotificationChannels,
    notifyTestLoading, setNotifyTestLoading,
    openProfileModal,
    handleProfileAvatarChange,
    handleSaveProfile,
  } = useUserProfile({
    currentUser,
    currentUserRecord,
    currentAvatar,
    language,
    t,
    showToast,
    setCurrentUser,
    setUsers,
    setShowNotifications,
    setShowUserMenu,
  });

  const {
    loadConfigSnapshots,
    loadSnapshotContent,
    saveScheduleConfig,
    handleSearchConfigSnapshots,
    handleClearConfigSnapshotSearch,
    handleRunBackupAllOnline,
    handleBackupSingleDevice,
    handleCopyConfigContent,
    handleFetchLiveConfig,
    handleOpenConfigSnapshot,
    handleCopyConfigSnapshot,
    handleRunScheduledBackupNow,
  } = useConfigSnapshots({
    devices,
    language,
    t,
    showToast,
    currentUser,
    currentUserRecord,
    copyTextWithFallback,
    isAuthenticated,
    activeTab,
    configPage,
  });
  const automationBridgeState = (location.state as { configAutomationBridge?: {
    source?: string;
    mode?: 'query' | 'config';
    command?: string;
    templateName?: string;
    targetDeviceIds?: string[];
    primaryTargetId?: string;
    variableValues?: Record<string, string>;
  } } | null)?.configAutomationBridge;
  // customCommandVars moved to useAutomation

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


  /**
   * Fetch the rarely-changing shared lookup tables. These power dropdowns
   * and page-level metadata; they don't need to be polled aggressively.
   * Was previously fired every 15 s along with the other shared data,
   * which amplified backend load proportional to the user count, script
   * count and topology link count.
   */
  const fetchSharedLookups = useCallback(async () => {
    try {
      const [scriptsRes, usersRes, templatesRes, varsRes, linksRes] = await Promise.all([
        fetch('/api/scripts'),
        fetch('/api/users'),
        fetch('/api/templates'),
        fetch('/api/vars'),
        fetch('/api/topology/links')
      ]);

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
          setTopologyLinks(Array.isArray(linksPayload) ? linksPayload : []);
          setTopologyUnmanagedNodes([]);
          setTopologyUnmanagedLinks([]);
        }
      }
    } catch (error) {
      console.error('Failed to fetch shared lookups:', error);
    }
  }, [selectedTemplateId]);

  /**
   * Fetch only the data that genuinely changes often (recent jobs, upcoming
   * tasks). Used by the short-cadence interval. The Dashboard manual
   * refresh button still calls `fetchSharedData` for a full refresh.
   */
  const fetchHotData = useCallback(async () => {
    try {
      loadJobs();
      loadUpcomingTasks();
      setDashLastRefresh(new Date());
    } catch (error) {
      console.error('Failed to fetch hot data:', error);
    }
  }, [loadUpcomingTasks, loadJobs]);

  /**
   * Full shared-data refresh: lookups + hot data. Used on initial load,
   * on route change, and when the user clicks the Dashboard refresh button.
   * Polling intervals do NOT call this (see fetchHotData / fetchSharedLookups).
   */
  const fetchSharedData = useCallback(async () => {
    await Promise.all([fetchSharedLookups(), fetchHotData()]);
  }, [fetchSharedLookups, fetchHotData]);

  const handleOpenTemplateDeploy = () => {
    setConfigWorkspaceView('checks');
    if (configValidationIssues.length > 0) {
      showToast(configValidationIssues[0], 'error');
      return;
    }

    const targetDevices = configScopedDevices.map((device) => ({
      id: device.id,
      hostname: device.hostname,
      ip_address: device.ip_address,
      platform: device.platform,
    }));

    const scenarioId = selectedTemplateId ? `cfgtpl:${selectedTemplateId}` : '';
    const platform = configScopePlatform !== 'all' ? configScopePlatform : '';

    navigate('/change-orders/new', {
      state: {
        scenarioId,
        platform,
        variables: configVariableMap,
        targetDevices,
      },
    });
  };



  useEffect(() => {
    if (!isAuthenticated) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    // Initial load: lookups (rarely change) + hot data (recent activity) + devices.
    Promise.all([fetchSharedLookups(), fetchHotData(), fetchDevicesData()])
      .finally(() => setIsLoading(false));

    let hotInterval: any;
    let lookupsInterval: any;
    let devicesInterval: any;

    if (autoRefreshEnabled) {
      // Recent activity / upcoming tasks — light, refresh frequently.
      hotInterval = setInterval(fetchHotData, 30000);
      // Heavy lookup tables (users / scripts / templates / vars / topology
      // links) — slow-changing, refresh on a long cadence. Page-level
      // forms still trigger their own fetches when they need fresh data.
      lookupsInterval = setInterval(fetchSharedLookups, 120000);
      // Reduce heavy full device refresh pressure while inventory table uses server-side paging.
      const devicePollMs = activeTab === 'inventory' && inventorySubPage === 'devices'
        ? 30000
        : 15000;
      devicesInterval = setInterval(fetchDevicesData, devicePollMs);
    }

    return () => {
      if (hotInterval) clearInterval(hotInterval);
      if (lookupsInterval) clearInterval(lookupsInterval);
      if (devicesInterval) clearInterval(devicesInterval);
    };
  }, [isAuthenticated, fetchSharedLookups, fetchHotData, fetchDevicesData, activeTab, inventorySubPage, autoRefreshEnabled]);

  // Force refresh when switching between submenus so returning pages always
  // show latest data. Only refresh shared lookups on explicit route changes
  // (not on each polling tick) to avoid the prior amplification.
  useEffect(() => {
    if (!isAuthenticated) return;
    fetchSharedLookups();
    fetchHotData();
    if (!(activeTab === 'inventory' && inventorySubPage === 'devices')) {
      fetchDevicesData();
    }
  }, [isAuthenticated, location.pathname, fetchSharedLookups, fetchHotData, fetchDevicesData, activeTab, inventorySubPage]);

  // 合规趋势：基于过去N天任务执行成功率
  const complianceTrend = useMemo(() => {
    const daysEn = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const daysZh = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    const monthsEn = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
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
      const label = trendDays <= 7
        ? (language === 'zh' ? daysZh[d.getDay()] : daysEn[d.getDay()])
        : (language === 'zh' ? `${d.getMonth() + 1}月${d.getDate()}日` : `${monthsEn[d.getMonth()]} ${d.getDate()}`);
      return { name: label, rate };
    });
  }, [jobs, devices, trendDays, language]);

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
      platform,
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


  // State pulled from inventory store
  const {
    inventoryTotal, inventoryPage, inventoryPageSize, setInventoryPage,
    setInventorySearch, setInventoryPlatformFilter, setInventoryRoleFilter, setInventoryStatusFilter,
    setInventorySortConfig, selectedDeviceIds, setSelectedDeviceIds, setInventoryRefreshTick
  } = useInventoryStore();

  const { confirmDeleteDevice } = useInventoryDeleteActions(showToast);

  // 全局快捷键处理 (ESC / Ctrl+K)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setCmdPaletteOpen((v) => !v);
        setCmdPaletteQuery('');
        return;
      }

      if (e.key === 'Escape') {
        // Order of precedence for closing global modals
        if (cmdPaletteOpen) {
          setCmdPaletteOpen(false);
          return;
        }
        if (showCustomCommandModal) {
          setShowCustomCommandModal(false);
          return;
        }
        if (showCmdPreviewModal) {
          setShowCmdPreviewModal(false);
          return;
        }
        if (showAddScenarioModal) {
          setShowAddScenarioModal(false);
          return;
        }
        if (saveQuickQueryModalOpen) {
          setSaveQuickQueryModalOpen(false);
          return;
        }
        if (showProfileModal) {
          setShowProfileModal(false);
          return;
        }
        if (showNotifications) {
          setShowNotifications(false);
          return;
        }
        if (showUserMenu) {
          setShowUserMenu(false);
          return;
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    cmdPaletteOpen, showCustomCommandModal, showCmdPreviewModal, showAddScenarioModal, 
    saveQuickQueryModalOpen, showProfileModal, showNotifications, showUserMenu,
    setShowCustomCommandModal, setShowCmdPreviewModal, setSaveQuickQueryModalOpen,
    setShowAddScenarioModal, setShowProfileModal, setShowNotifications, setShowUserMenu
  ]);

  useEffect(() => {
    const totalInventoryPages = Math.max(1, Math.ceil(inventoryTotal / inventoryPageSize));
    if (inventoryPage > totalInventoryPages) {
      setInventoryPage(totalInventoryPages);
    }
  }, [inventoryTotal, inventoryPage, inventoryPageSize]);

  // Monitoring functions/effects moved to useMonitoring hook

  const {
    hostResourceTone,
    hostResourceSummary,
    alertNavTone,
  } = useResourceSignals({
    hostResources,
    unreadNotificationCount,
    language,
  });

  const formatTopologyPort = (value?: string) => formatTopologyPortValue(value, language);
  const formatTopologyEvidenceLabel = (value: string) => formatTopologyEvidenceLabelValue(value, language);
  const formatTopologyOperationalState = (state?: TopologyOperationalState) => formatTopologyOperationalStateValue(state, language);
  const formatTopologyLastSeen = (value?: string) => formatTopologyLastSeenValue(value, language);


  // History, Audit, Compliance effects/handlers moved to useHistoryAuditCompliance hook

  const {
    showDeleteModal,
    setShowDeleteModal,
    deviceToDelete,
    setDeviceToDelete,
    isDeletingSelected,
    setIsDeletingSelected,
  } = useInventoryStore();
  const {
    isTestingConnection,
    connectionTestDevice,
    connectionTestMode,
    connectionTestingDeviceId,
    deviceConnectionChecks,
    snmpTestingId,
    snmpSyncingId,
    snmpTestResult,
    showSnmpTestResult, setShowSnmpTestResult,
    showTestResult, setShowTestResult,
    testResult,
    handleTestConnection,
    handleSnmpTest,
    handleSnmpSyncNow,
  } = useDeviceConnectionAndSnmp({
    language,
    showToast,
    selectedDevice,
    setDevices,
    fetchDevicesData,
  });
  const {
    showDetailsModal, setShowDetailsModal,
    viewingDevice, setViewingDevice,
    viewingDeviceAlerts,
    deviceDetailLoading,
    deviceTrendRangeHours, setDeviceTrendRangeHours,
    deviceHealthTrend,
    deviceHealthTrendLoading,
    deviceOperationalData,
    deviceOperationalDataLoading,
    handleShowDetails,
    loadDeviceOperationalData,
  } = useDeviceDetail({ language, showToast, normalizeDeviceRecord });

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

  const {
    showAddModal, setShowAddModal,
    showEditModal, setShowEditModal,
    editingDevice, setEditingDevice,
    editForm, setEditForm,
    addForm, setAddForm,
    showAddDevicePwd, setShowAddDevicePwd,
    showEditDevicePwd, setShowEditDevicePwd,
    showLifecycleConfirm, setShowLifecycleConfirm,
    lifecycleConfirmChecked, setLifecycleConfirmChecked,
    handleSaveEdit,
    handleAddDevice,
  } = useDeviceFormActions({ devices, setDevices, showToast });

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

  // Deleted hook for delete actions
  // handleSaveEdit / handleAddDevice moved to useDeviceFormActions
  // handleTestConnection / handleSnmpTest / handleSnmpSyncNow moved to useDeviceConnectionAndSnmp

  const { handleImport, handleExport } = useInventoryImportExport({ devices, setDevices, showToast, t });

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
        mfaRequired={mfaRequired}
        onMfaSubmit={handleMfaVerify}
        onCancelMfa={() => {
          setMfaRequired(false);
          setLoginError(null);
        }}
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

  // ---------- Config Center helpers moved to useConfigSnapshots ----------

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

  if (activeTab === 'terminal') {
    const params = new URLSearchParams(location.search);
    const sessionToken = params.get('session') || '';
    const hostname = params.get('hostname') || 'Terminal';

    return (
      <div className="w-screen h-screen bg-black overflow-hidden">
        <TerminalWindow 
          sessionToken={sessionToken} 
          hostname={hostname} 
          language={language}
        />
      </div>
    );
  }

  // Create Context values
  const coreAppValue = {
    activeTab, inventorySubPage, configPage, automationPage, changeOrderPage, ipamPage, cmdbPage, language, t, navigate, navTo, showToast, setActiveTab, isAuthenticated,
    currentUser, users,
    devices, fetchDevicesData, devicesLastUpdatedAt,
  };

  const dashboardValue = {
    jobs, notifications, hostResources, trendDays, setTrendDays, complianceTrend, platformData,
    dashBannerCollapsed, setDashBannerCollapsed, dashLastRefresh, autoRefreshEnabled, setAutoRefreshEnabled, fetchSharedData, fetchDevicesData,
    scheduledTasks, unreadNotificationCount,
  };

  const inventoryValue = {
    handleImport, handleExport, handleShowDetails, handleTestConnection, deviceConnectionChecks, connectionTestingDeviceId,
    setShowAddModal, setShowEditModal, setEditingDevice, setEditForm, setSelectedDevice, selectedDevice,
    snmpTestingId, snmpSyncingId, handleSnmpTest, handleSnmpSyncNow,
  };

  const automationValue = {
    scenarios, platforms, selectedScenario, scenarioSearch, playbookVars, playbookPreview, playbookPlatform, playbookDeviceIds,
    playbookConcurrency, playbookDryRun, executionStatus,
    quickPlaybookScenario, quickPlaybookVars, quickPlaybookPlatform, quickPlaybookDryRun, quickPlaybookConcurrency, quickPlaybookPreview, quickRiskConfirmed,
    filteredScenarios, quickMissingRequiredFields, quickHasMixedPlatforms, quickPlatformMismatch, isQuickPlaybookRunning,
    quickExecutionResult, wsCompleteMsg, deviceStatusMap,
    quickQueryRunning, quickQueryOutput, quickQueryLabel, quickQueryStructured, quickQueryView, quickQueryMaximized, quickQueryCommands,
    changeTicket, setChangeTicket, quickQueryTable, savedQueries,
    handleAutomationSearch, handleScenarioSearch, handleToggleBatchMode, handleToggleBatchDevice, handleSelectAutomationDevice,
    batchMode, batchDeviceIds, automationSearch, hasQuickTargets, openQuickPlaybookModal, handleClearQuickScenario,
    runQuickPlaybook, runQuickQuery, handleResetQuickQuery, setQuickQueryView, setQuickQueryMaximized, exportQuickQueryTable,
    copyTextWithFallback, handleResetQuickExecutionState, handlePlaybookPlatformChange, handlePlaybookVariableChange,
    handleSelectPlaybookScenario, openManualScenarioDraft, executePlaybook,
    setShowCustomCommandModal, setQuickPlaybookVars, setQuickPlaybookConcurrency, setQuickRiskConfirmed, setShowCmdPreviewModal,
    handleTogglePlaybookDevice, setPlaybookConcurrency, previewPlaybook,
    playbookExecutions, playbookHistoryTotal, playbookHistoryPage, playbookHistoryStatusFilter, playbookHistoryScenarioSearch,
    activeExecutionId, wsMessages,
    selectedExecutionLoading, selectedExecutionDetail, selectedDeviceDetail, selectedDeviceDetailLoading,
    selectedExecDevices, selectedExecDevicesTotal, selectedExecDevicesPage, selectedExecDevicesStatusFilter, selectedExecDevicesLoading,
    handleRefreshHistory, setPlaybookHistoryScenarioSearch, setPlaybookHistoryPage, setPlaybookHistoryStatusFilter,
    handleSelectExecution, handleDeleteExecution, handleExecDevicesStatusFilterChange, handleExecDevicesPageChange, handleSelectExecDevice,
    findMatchingPlatform, handleRerun, selectedJob, setSelectedJob,
    selectedDevice, handleClearSelection,
  };

  const configValue = {
    isTakingSnapshot, activeBackupRunId,
    scheduleEnabled, setScheduleEnabled, scheduleCron, setScheduleCron, scheduleLoading,
    retentionDays, setRetentionDays, saveScheduleConfig, configSnapshots,
    handleRunBackupAllOnline, handleBackupSingleDevice,
    handleNavigateToConfigDiff, diffPreSelectedDeviceId, activeDiffLines, activeChangeLineIndexes, diffFocusChangeIdx,
    diffOnlyChanges, diffShowFullBoth, renderedDiffLines, fullSideBySideRows, diffChangeBlocks, filteredDiffChangeBlocks,
    diffBlockQuery, diffLineRefs, focusDiffChangeAt, configDiffLeft, configDiffRight,
    handleResetDiffView, handleSelectSnapshotPair, jumpToDiff,
    setDiffOnlyChanges, setDiffShowFullBoth, setDiffBlockQuery,
    configTemplates, configVariableKeys, configMissingVariables, configScopedDevices, configScopedOnlineCount, configReadinessScore,
    configValidationIssues, configValidationWarnings, configWorkspaceView,
    selectedTemplateId, selectedConfigTemplate, globalVars, editorContent, configRenderedPreview,
    configScopePlatform, configScopeRole, configScopeSite, configPlatformOptions, configRoleOptions, configSiteOptions,
    extractVars, getPlatformLabel,
    handleImportVars, handleNewTemplate, handleAddVar, handleDeleteVar, handleDiscardChanges, handleValidateTemplateWorkspace,
    handleSaveTemplate, handleCreateScenarioDraftFromTemplate, handleOpenTemplateDeploy,
    setConfigWorkspaceView, setSelectedTemplateId, setEditorContent, setConfigTemplates,
    setConfigScopePlatform, setConfigScopeRole, setConfigScopeSite,
  };

  const managementValue = {
    showAddUserModal, setShowAddUserModal, showEditUserModal, setShowEditUserModal, editingUser, setEditingUser,
    newUserForm, setNewUserForm, editUserForm, setEditUserForm,
    showNewUserPwd, setShowNewUserPwd, showEditUserPwd, setShowEditUserPwd,
    handleAddUser, handleEditUser,
    auditRows, auditTotal, auditPage, setAuditPage, auditPageSize, setAuditPageSize, auditLoading,
    auditCategoryFilter, setAuditCategoryFilter, auditSeverityFilter, setAuditSeverityFilter,
    auditStatusFilter, setAuditStatusFilter, auditTimeFilter, setAuditTimeFilter,
    openAuditEventDetail,
    complianceOverview, complianceFindings, complianceFindingTotal,
    complianceSeverityFilter, setComplianceSeverityFilter, complianceStatusFilter, setComplianceStatusFilter,
    complianceCategoryFilter, setComplianceCategoryFilter,
    compliancePage, setCompliancePage, compliancePageSize, setCompliancePageSize, complianceLoading, complianceRunLoading,
    runComplianceAudit, openComplianceFindingDetail, updateComplianceFinding,
  };

  const topologyValue = {
    setSelectedTopologyDeviceId, setSelectedTopologyLinkKey, topologyDiscoveryRunning,
    topologyStats, topologyLinkStats,
    topologySearch, topologySiteFilter, topologyRoleFilter, topologyStatusFilter,
    topologySiteOptions, topologyRoleOptions, topologyVisibleDevices, topologyVisibleLinks,
    selectedTopologyDeviceId, selectedTopologyLinkKey, selectedTopologyDevice, selectedTopologyLink,
    topologyNeighborDevices, topologyDeviceLinks, topologyPriorityDevices, topologyOrphanDevices, topologyRef,
    hideStaleLinks, setHideStaleLinks, hideOrphanDevices, setHideOrphanDevices,
    handleTriggerDiscovery, handleExportMap,
    setTopologySearch, setTopologySiteFilter, setTopologyRoleFilter, setTopologyStatusFilter,
    formatTopologyPort, formatTopologyInterfaceTelemetry, formatTopologyLastSeen, formatTopologyOperationalState, formatTopologyEvidenceLabel,
    getTopologyOperationalTone,
  };

  return (
    <AppRuntimeBoundary language={language}>
      <AppProviders
        coreApp={coreAppValue}
        dashboard={dashboardValue}
        inventory={inventoryValue}
        automation={automationValue}
        config={configValue}
        management={managementValue}
        topology={topologyValue}
      >
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
          setActiveTab('audit');
          setShowUserMenu(false);
        }}
        onThemeModeChange={setThemeMode}
        onLanguageChange={handleLanguagePreferenceChange}
        onSwitchUser={handleSwitchUser}
        availableUsers={users}
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
        <AppMainContent />

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

      <AppModals
        {...{
          showProfileModal, language, resolvedTheme, currentUser, currentUserRecord,
          currentUserLastLogin, profileAvatarPreview, avatarPresets, profileForm,
          showProfilePwd, notificationChannels, notifyTestLoading, renderAvatarContent,
          setShowProfileModal, handleSaveProfile, handleProfileAvatarChange,
          setProfileAvatarPreview, setProfileForm, setShowProfilePwd, setNotificationChannels,
          setNotifyTestLoading, showToast, setCurrentUser,
          showTestResult, isTestingConnection, connectionTestMode, connectionTestDevice,
          selectedDevice, testResult, setShowTestResult, handleTestConnection,
          showImportModal, t, setShowImportModal,
          showDiff, currentDiff, setShowDiff, runTask,
          showConfigModal, viewingConfig, setShowConfigModal, handleRollbackConfig,
          showScheduleModal, schedulingTask, scheduleForm, setScheduleForm, setShowScheduleModal, handleScheduleTask,
          showRemediationModal, remediatingDevice, setShowRemediationModal, confirmRemediation,
          showDeleteModal, isDeletingSelected, selectedDeviceIds, setShowDeleteModal,
          setDeviceToDelete, setIsDeletingSelected, confirmDeleteDevice,
          showAddModal, addForm, showAddDevicePwd, setAddForm, setShowAddDevicePwd, setShowAddModal, handleAddDevice,
          showEditModal, editingDevice, editForm, showEditDevicePwd, setEditForm, setShowEditDevicePwd, setShowEditModal, handleSaveEdit,
          showLifecycleConfirm, lifecycleConfirmChecked, setLifecycleConfirmChecked, setShowLifecycleConfirm,
          showDetailsModal, viewingDevice, viewingDeviceAlerts, deviceDetailLoading, deviceConnectionChecks,
          connectionTestingDeviceId, deviceTrendRangeHours, setDeviceTrendRangeHours, deviceHealthTrend, deviceHealthTrendLoading,
          deviceOperationalData, deviceOperationalDataLoading, loadDeviceOperationalData,
          handleSnmpTest, snmpTestingId, handleSnmpSyncNow, snmpSyncingId,
          setSelectedDevice, setShowDetailsModal,
          showSnmpTestResult, snmpTestResult, setShowSnmpTestResult,
          selectedAuditEvent, setSelectedAuditEvent,
          selectedFinding, setSelectedFinding, updateComplianceFinding,
          selectedJob, setSelectedJob, copyTextWithFallback,
          navigate,
        }}
      />

      {/* Toast Notification */}
        </AppLayout>
      </AppProviders>
    </AppRuntimeBoundary>
  );
};

export default App;
