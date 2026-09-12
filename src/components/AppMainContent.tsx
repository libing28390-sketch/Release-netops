import React, { Suspense, lazy, useMemo } from 'react';
import { useSystem } from '../hooks/useSystem';
import { useInventoryStore } from '../store/inventoryStore';
import { useMonitoringStore } from '../store/monitoringStore';
import { useCoreApp, useDashboard, useInventory } from '../contexts/AppDomainContext';
import { useAutomationContext } from '../contexts/AutomationContext';
import { useConfigContext } from '../contexts/ConfigContext';
import { useManagementContext } from '../contexts/ManagementContext';
import { useTopologyContext } from '../contexts/TopologyContext';
import { useAccessFavorites } from '../hooks/useAccessFavorites';
import { sectionHeaderRowClass } from './shared';

const MonitoringCenter = lazy(() => import('./MonitoringCenter.tsx'));
const OutboundHealthPage = lazy(() => import('../pages/OutboundHealthPage'));
const ServerMonitoring = lazy(() => import('./ServerMonitoring.tsx'));
const NetworkMonitoring = lazy(() => import('./NetworkMonitoring.tsx'));
const DeviceHealthTab = lazy(() => import('../pages/DeviceHealthTab'));
const DashboardTab = lazy(() => import('../pages/DashboardTab'));
const HomePage = lazy(() => import('../pages/HomePage'));
const ComplianceTab = lazy(() => import('../pages/ComplianceTab'));
const AuditTab = lazy(() => import('../pages/AuditTab'));
const UsersTab = lazy(() => import('../pages/UsersTab'));
const TopologyPage = lazy(() => import('../pages/TopologyPage'));
const InventoryDevicesTab = lazy(() => import('../pages/InventoryDevicesTab'));
const InventoryServersTab = lazy(() => import('../pages/InventoryServersTab'));
const AlertDeskTab = lazy(() => import('../pages/AlertDeskTab'));
const AlertRulesTab = lazy(() => import('../pages/AlertRulesTab'));
const AlertMaintenanceTab = lazy(() => import('../pages/AlertMaintenanceTab'));
const AlertHistoryTab = lazy(() => import('../pages/AlertHistoryTab'));
const ReportsTab = lazy(() => import('../pages/ReportsTab'));
const ConfigDriftTab = lazy(() => import('../pages/ConfigDriftTab'));
const ConfigBackupTab = lazy(() => import('../pages/ConfigBackupTab'));
const ConfigDiffViewTab = lazy(() => import('../pages/ConfigDiffViewTab'));
const ConfigSearchTab = lazy(() => import('../pages/ConfigSearchTab'));
const CapacityPlanningTab = lazy(() => import('../pages/CapacityPlanningTab'));
const IPAMManagementTab = lazy(() => import('../pages/IPAMManagementTab'));
const IPLocatorPage = lazy(() => import('../pages/IPLocatorPage'));
const AssetManagementTab = lazy(() => import('../pages/AssetManagementTab'));
const CredentialManagementTab = lazy(() => import('../components/PasswordRotationPanel'));
const ChangeOrderTab = lazy(() => import('../pages/ChangeOrderTab'));
const AutomationExecuteTab = lazy(() => import('../pages/AutomationExecuteTab'));
const AutomationPlaybooksTab = lazy(() => import('../pages/AutomationPlaybooksTab'));
const AutomationScenariosTab = lazy(() => import('../pages/AutomationScenariosTab'));
const AutomationHistoryTab = lazy(() => import('../pages/AutomationHistoryTab'));
const InspectionTab = lazy(() => import('../pages/InspectionTab'));
const ExecutionScheduleTab = lazy(() => import('../pages/ExecutionScheduleTab'));
const InspectionItemsTab = lazy(() => import('../pages/InspectionItemsTab'));
const TextFSMTemplatesTab = lazy(() => import('../pages/TextFSMTemplatesTab'));
const ScheduledJobsTab = lazy(() => import('../pages/ScheduledJobsTab'));
const PlatformSettingsTab = lazy(() => import('../pages/PlatformSettingsTab'));
const PlatformRegistryTab = lazy(() => import('../pages/PlatformRegistryTab'));
const SnmpMetricTemplatesTab = lazy(() => import('../pages/SnmpMetricTemplatesTab'));
const RackManagementTab = lazy(() => import('../pages/RackManagementTab'));
const CmdbManagementTab = lazy(() => import('../pages/CmdbManagementTab'));
const CmdbAssetManagementTab = lazy(() => import('../pages/CmdbAssetManagementTab'));
const CmdbResourceSearchTab = lazy(() => import('../pages/CmdbResourceSearchTab'));
const TagManagementTab = lazy(() => import('../pages/TagManagementTab'));
const ScriptManagementTab = lazy(() => import('../pages/ScriptManagementTab'));
const ConfigScheduleTab = lazy(() => import('../pages/ConfigScheduleTab'));
const AccessCenterTab = lazy(() => import('../pages/AccessCenterTab'));
const AccessFavoritesTab = lazy(() => import('../pages/AccessFavoritesTab'));
const PAMAuditTab = lazy(() => import('../pages/PAMAuditTab'));
const AiCenterPage = lazy(() => import('../pages/ai/AiCenterPage'));


const lazyPanelFallback = (
  <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-black/5 bg-white/70 text-sm text-black/40">
    Loading...
  </div>
);

const AppMainContent: React.FC = () => {
  // Context hooks
  const coreApp = useCoreApp();
  const dashboard = useDashboard();
  const inventory = useInventory();
  const automation = useAutomationContext();
  const config = useConfigContext();
  const management = useManagementContext();
  const topology = useTopologyContext();

  const { isFeatureEnabled } = useSystem();
  const { assetsTotal } = useInventoryStore();
  const { monitorOverview, setMonitorSelectedDevice } = useMonitoringStore();
  
  const {
    activeTab,
    inventorySubPage,
    configPage,
    automationPage,
    changeOrderPage,
    ipamPage,
    cmdbPage,
    language,
    t,
    navigate,
    navTo,
    showToast,
    setActiveTab,
    isAuthenticated,
    currentUser,
    devices,
  } = coreApp;

  const { favoriteDeviceIds, toggleFavorite } = useAccessFavorites(currentUser?.username);
  const handleFavoriteToggle = (device: { id: string }) => toggleFavorite(device.id);
  const openAccessWorkspace = (device?: { hostname?: string }) => {
    const query = device?.hostname ? `?q=${encodeURIComponent(device.hostname)}` : '';
    navigate(`/access/workspace${query}`);
  };
  
  const {
    jobs,
    notifications,
    hostResources,
    trendDays,
    setTrendDays,
    complianceTrend,
    platformData,
    dashBannerCollapsed,
    setDashBannerCollapsed,
    dashLastRefresh,
    scheduledTasks,
    unreadNotificationCount,
  } = dashboard;
  
  const {
    handleImport,
    handleExport,
    handleShowDetails,
    handleTestConnection,
    deviceConnectionChecks,
    connectionTestingDeviceId,
    setShowAddModal,
    setShowEditModal,
    setEditingDevice,
    setEditForm,
    setSelectedDevice,
    selectedDevice,
    snmpTestingId,
    snmpSyncingId,
    handleSnmpTest,
    handleSnmpSyncNow,
  } = inventory;
  
  const {
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
    setShowCustomCommandModal,
    setQuickPlaybookVars,
    setQuickPlaybookConcurrency,
    setQuickRiskConfirmed,
    setShowCmdPreviewModal,
    handleTogglePlaybookDevice,
    setPlaybookConcurrency,
    previewPlaybook,
    handleRerun,
    selectedJob,
    setSelectedJob,
    findMatchingPlatform,
    handleClearSelection,
  } = automation;
  
  const {
    isTakingSnapshot,
    activeBackupRunId,
    scheduleEnabled,
    setScheduleEnabled,
    scheduleCron,
    setScheduleCron,
    scheduleLoading,
    retentionDays,
    setRetentionDays,
    retentionMaxPerDevice,
    setRetentionMaxPerDevice,
    saveScheduleConfig,
    configSnapshots,
    handleRunBackupAllOnline,
    handleBackupSingleDevice,
    handleNavigateToConfigDiff,
    diffPreSelectedDeviceId,
    activeDiffLines,
    activeChangeLineIndexes,
    diffFocusChangeIdx,
    diffOnlyChanges,
    diffShowFullBoth,
    diffMode,
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
    setDiffMode,
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
    setSelectedTemplateId,
    setEditorContent,
    setConfigTemplates,
    handleAddVar,
    handleDeleteVar,
    handleDiscardChanges,
    setConfigWorkspaceView,
    setConfigScopePlatform,
    setConfigScopeRole,
    setConfigScopeSite,
    handleSaveTemplate,
    handleCreateScenarioDraftFromTemplate,
    handleOpenTemplateDeploy,
    handleValidateTemplateWorkspace,
  } = config;
  
  const {
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
    openAuditEventDetail,
  } = management;
  
  // Legacy props that need to be moved to appropriate contexts
  const {
    autoRefreshEnabled,
    setAutoRefreshEnabled,
    fetchSharedData,
    fetchDevicesData,
  } = dashboard; // These should be in dashboard context
  
  // Additional context destructuring for missing props
  const { users, devicesLastUpdatedAt } = coreApp;
  
  // Topology context destructuring
  const {
    topologyDiscoveryRunning,
    topologyDiscoveryProgress,
    topologyDiscoveryDevices,
    topologySites,
    topologyDataError,
    topologyStats,
    topologyLinkStats,
    topologySearch,
    topologySiteFilter,
    topologyGraphView,
    topologyTagFilter,
    topologyRoleFilter,
    topologyStatusFilter,
    topologyLinkStatusFilter,
    topologyProtocolFilter,
    topologySiteOptions,
    topologyTagOptions,
    topologyTagCandidateDevices,
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
    hideStaleLinks,
    setHideStaleLinks,
    hideOrphanDevices,
    setHideOrphanDevices,
    handleTriggerDiscovery,
    handleCancelDiscovery,
    handleExportMap,
    handleConfirmTopologyRelation,
    loadTopologyHistory,
    setTopologySearch,
    setTopologySiteFilter,
    setTopologyGraphView,
    setTopologyTagFilter,
    setTopologyRoleFilter,
    setTopologyStatusFilter,
    setTopologyLinkStatusFilter,
    setTopologyProtocolFilter,
    setSelectedTopologyDeviceId,
    setSelectedTopologyLinkKey,
    formatTopologyPort,
    formatTopologyInterfaceTelemetry,
    formatTopologyLastSeen,
    formatTopologyOperationalState,
    formatTopologyEvidenceLabel,
    getTopologyOperationalTone,
  } = topology;

  const isStandaloneScrollTab = 
    activeTab === 'alerts' || 
    activeTab === 'alert-rules' || 
    activeTab === 'alert-history' || 
    activeTab === 'maintenance' || 
    activeTab === 'platform-registry' ||
    activeTab === 'snmp-metric-templates' ||
    activeTab === 'access' ||
    activeTab === 'access-favorites' ||
    activeTab === 'access-history' ||
    (activeTab === 'automation' && automationPage === 'metrics');
  const isAiTab = activeTab === 'ai-center' || activeTab.startsWith('ai-');

  const getDeviceFetchMode = () => {
    if (activeTab === 'inventory') return 'full';
    if (activeTab === 'automation') return 'full';
    if (activeTab === 'config') return 'full';
    if (activeTab === 'topology') return 'full';
    if (activeTab === 'access' || activeTab === 'access-favorites' || activeTab === 'access-history') return 'full';
    return 'light';
  };

  const mainClassName = `relative flex-1 min-w-0 flex flex-col min-h-0 ${isStandaloneScrollTab || isAiTab ? 'overflow-hidden' : 'overflow-y-auto'}`;

  return (
    <main className={mainClassName}>
      {activeTab === 'dashboard' && (
        <Suspense fallback={lazyPanelFallback}>
          <HomePage
            language={language}
            navigate={navigate}
            userRole={currentUser?.role}
            devices={devices}
            jobs={jobs}
            notifications={notifications}
            hostResources={hostResources}
            userCount={users?.length}
          />
        </Suspense>
      )}

      {activeTab === 'overview' && (
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
            autoRefreshEnabled={autoRefreshEnabled}
            setAutoRefreshEnabled={setAutoRefreshEnabled}
            fetchSharedData={fetchSharedData}
            fetchDevicesData={fetchDevicesData}
            selectedJob={selectedJob}
            setSelectedJob={setSelectedJob}
            hostResources={hostResources}
            unreadNotificationCount={unreadNotificationCount}
            notifications={notifications}
            language={language}
            t={t}
            setActiveTab={setActiveTab}
            navigate={navigate}
            assetsTotal={assetsTotal}
          />
        </Suspense>
      )}

      {activeTab === 'monitoring' && (
        <Suspense fallback={lazyPanelFallback}>
          <MonitoringCenter
            devices={devices}
            language={language}
            showToast={showToast}
            isAuthenticated={isAuthenticated}
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
            onOpenMonitoring={() => navTo('/monitor/telemetry')}
          />
        </Suspense>
      )}

      {activeTab === 'outbound-monitoring' && (
        <Suspense fallback={lazyPanelFallback}>
          <OutboundHealthPage />
        </Suspense>
      )}

      {activeTab === 'server-monitoring' && (
        <Suspense fallback={lazyPanelFallback}>
          <ServerMonitoring
            devices={devices}
            hostResources={hostResources}
            language={language}
            showToast={showToast}
            isAuthenticated={isAuthenticated}
          />
        </Suspense>
      )}

      {activeTab === 'network-monitoring' && (
        <Suspense fallback={lazyPanelFallback}>
          <NetworkMonitoring
            devices={devices}
            language={language}
            showToast={showToast}
            isAuthenticated={isAuthenticated}
          />
        </Suspense>
      )}

      {activeTab === 'access' && (
        <Suspense fallback={lazyPanelFallback}>
          <AccessCenterTab
            devices={devices}
            language={language}
            showToast={showToast}
            favoriteDeviceIds={favoriteDeviceIds}
            onToggleFavorite={handleFavoriteToggle}
          />
        </Suspense>
      )}

      {activeTab === 'access-favorites' && (
        <Suspense fallback={lazyPanelFallback}>
          <AccessFavoritesTab
            devices={devices}
            language={language}
            favoriteDeviceIds={favoriteDeviceIds}
            onToggleFavorite={handleFavoriteToggle}
            onOpenWorkspace={openAccessWorkspace}
            showToast={showToast}
          />
        </Suspense>
      )}

      {activeTab === 'access-history' && (
        <Suspense fallback={lazyPanelFallback}>
          <PAMAuditTab
            language={language}
            showToast={showToast}
            scope="mine"
            currentUsername={currentUser?.username}
          />
        </Suspense>
      )}

      {activeTab === 'pam-audit' && (
        <Suspense fallback={lazyPanelFallback}>
          <PAMAuditTab language={language} showToast={showToast} />
        </Suspense>
      )}

      {activeTab === 'alerts' && (
        <Suspense fallback={lazyPanelFallback}>
          <AlertDeskTab
            language={language}
            currentUsername={currentUser?.username}
            showToast={showToast}
            activeAlertSection="alerts"
            onNavigateAlertSection={(section: string) => setActiveTab(section)}
            onOpenMaintenanceForAlert={(alert: any) => {
              const params = new URLSearchParams({
                open: '1',
                name: alert ? `${alert.hostname || alert.ip_address || 'Alert'} Maintenance` : '',
                target_ip: alert?.ip_address || '',
              });
              navigate(`/maintenance?${params.toString()}`);
            }}
            onNavigateToDevice={(deviceId: string) => {
              const device = devices.find((d: any) => d.id === deviceId);
              if (device) handleShowDetails(device);
            }}
            onNavigateToTopology={(deviceId: string) => {
              setSelectedTopologyDeviceId(deviceId);
              setActiveTab('topology');
            }}
          />
        </Suspense>
      )}

      {activeTab === 'alert-rules' && (
        <Suspense fallback={lazyPanelFallback}>
          <AlertRulesTab
            language={language}
            currentUsername={currentUser?.username}
            showToast={showToast}
            activeAlertSection="alert-rules"
            onNavigateAlertSection={(section: string) => setActiveTab(section)}
          />
        </Suspense>
      )}

      {activeTab === 'alert-history' && (
        <Suspense fallback={lazyPanelFallback}>
          <AlertHistoryTab
            language={language}
            currentUsername={currentUser?.username}
            showToast={showToast}
            activeAlertSection="alert-history"
            onNavigateAlertSection={(section: string) => setActiveTab(section)}
            onNavigateToDevice={(deviceId: string) => {
              const device = devices.find((d: any) => d.id === deviceId);
              if (device) handleShowDetails(device);
            }}
            onNavigateToTopology={(deviceId: string) => {
              setSelectedTopologyDeviceId(deviceId);
              setActiveTab('topology');
            }}
          />
        </Suspense>
      )}

      {activeTab === 'maintenance' && (
        <Suspense fallback={lazyPanelFallback}>
          <AlertMaintenanceTab
            language={language}
            currentUsername={currentUser?.username}
            showToast={showToast}
            activeAlertSection="maintenance"
            onNavigateAlertSection={(section: string) => setActiveTab(section)}
          />
        </Suspense>
      )}

      {activeTab === 'inventory' && inventorySubPage === 'devices' && (
        <Suspense fallback={lazyPanelFallback}>
          <InventoryDevicesTab
            handleImport={handleImport}
            handleExport={handleExport}
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
            onRefresh={() => {/* TODO: implement inventory refresh */}}
            language={language}
            t={t}
          />
        </Suspense>
      )}

      {activeTab === 'inventory' && inventorySubPage === 'servers' && (
        <Suspense fallback={lazyPanelFallback}>
          <InventoryServersTab language={language} t={t} setActiveTab={setActiveTab} setSelectedDevice={setSelectedDevice} />
        </Suspense>
      )}

      {activeTab === 'racks' && (
        <Suspense fallback={lazyPanelFallback}>
          <RackManagementTab language={language} t={t} />
        </Suspense>
      )}

      {activeTab === 'cmdb' && (
        <Suspense fallback={lazyPanelFallback}>
          {cmdbPage === 'racks' ? (
            <RackManagementTab language={language} t={t} />
          ) : cmdbPage === 'assets' ? (
            <CmdbAssetManagementTab language={language} currentUser={currentUser} />
          ) : cmdbPage === 'resources' ? (
            <CmdbResourceSearchTab language={language} />
          ) : (
            <CmdbManagementTab language={language} cmdbPage={cmdbPage} currentUser={currentUser} />
          )}
        </Suspense>
      )}

      {activeTab === 'topology' && (
        <Suspense fallback={lazyPanelFallback}>
          <TopologyPage
            language={language}
            topologyDiscoveryRunning={topologyDiscoveryRunning}
            topologyDiscoveryProgress={topologyDiscoveryProgress}
            topologyDiscoveryDevices={topologyDiscoveryDevices}
            topologySites={topologySites}
            topologyDataError={topologyDataError}
            topologyStats={topologyStats}
            topologyLinkStats={topologyLinkStats}
            topologySearch={topologySearch}
            topologySiteFilter={topologySiteFilter}
            topologyGraphView={topologyGraphView}
            topologyTagFilter={topologyTagFilter}
            topologyRoleFilter={topologyRoleFilter}
            topologyStatusFilter={topologyStatusFilter}
            topologyLinkStatusFilter={topologyLinkStatusFilter}
            topologyProtocolFilter={topologyProtocolFilter}
            topologySiteOptions={topologySiteOptions}
            topologyTagOptions={topologyTagOptions}
            topologyTagCandidateDevices={topologyTagCandidateDevices}
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
            hideStaleLinks={hideStaleLinks}
            onHideStaleLinksChange={setHideStaleLinks}
            hideOrphanDevices={hideOrphanDevices}
            onHideOrphanDevicesChange={setHideOrphanDevices}
            onTriggerDiscovery={handleTriggerDiscovery}
            onCancelDiscovery={handleCancelDiscovery}
            onExportMap={handleExportMap}
            onTopologySearchChange={setTopologySearch}
            onTopologySiteFilterChange={setTopologySiteFilter}
            onTopologyGraphViewChange={setTopologyGraphView}
            onTopologyTagFilterChange={setTopologyTagFilter}
            onTopologyRoleFilterChange={setTopologyRoleFilter}
            onTopologyStatusFilterChange={setTopologyStatusFilter}
            onTopologyLinkStatusFilterChange={setTopologyLinkStatusFilter}
            onTopologyProtocolFilterChange={setTopologyProtocolFilter}
             onSelectTopologyDevice={setSelectedTopologyDeviceId}
            onSelectTopologyLink={setSelectedTopologyLinkKey}
            onConfirmTopologyRelation={handleConfirmTopologyRelation}
            loadTopologyHistory={loadTopologyHistory}
             onOpenWorkspace={(device) => {
               const workspaceUrl = `/access/workspace?device_id=${encodeURIComponent(device.id)}&auto=normal`;
               const workspaceWindow = window.open(workspaceUrl, '_blank', 'noopener,noreferrer');
               if (workspaceWindow) {
                 workspaceWindow.focus();
               } else {
                 if (String(language) === 'zh') {
                   showToast('浏览器阻止了新窗口，请允许本站弹出窗口后重试', 'info');
                   return;
                 }
                 // Never replace the topology page when a popup is blocked.
                 // Reusing the current tab made the topology view itself start
                 // the terminal session and could result in two sessions.
                 showToast(
                   language === 'zh' ? '浏览器阻止了新窗口，请允许本站弹出窗口后重试' : 'The browser blocked the new window. Allow pop-ups for this site and retry.',
                   'info',
                 );
               }
             }}
             onOpenDeviceDetail={handleShowDetails}
             onOpenMonitoring={() => {
              if (selectedTopologyDevice) {
                setMonitorSelectedDevice(selectedTopologyDevice);
                const p = (selectedTopologyDevice.platform || '').toLowerCase();
                const serverKeywords = ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rocky', 'alma', 'windows', 'winrm', 'server'];
                const isServer = serverKeywords.some((kw) => p.includes(kw)) ||
                                 (selectedTopologyDevice.device_category || '').toLowerCase().includes('server') ||
                                 (selectedTopologyDevice.role || '').toLowerCase().includes('server') ||
                                 ((selectedTopologyDevice as any).asset_type || '').toLowerCase().includes('server');
                if (isServer) {
                  navTo('/monitor/servers');
                } else {
                  navTo('/monitor/networks');
                }
              } else {
                navTo('/monitor/networks');
              }
            }}
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
            changeTicket={changeTicket}
            setChangeTicket={setChangeTicket}
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
            savedQueries={savedQueries}
            onNavigate={navigate}
            onAutomationSearchChange={handleAutomationSearch}
            onScenarioSearchChange={handleScenarioSearch}
            onToggleBatchMode={handleToggleBatchMode}
            onToggleBatchDevice={handleToggleBatchDevice}
            onSelectDevice={handleSelectAutomationDevice}
            handleClearSelection={handleClearSelection}
            onOpenCustomCommandModal={() => setShowCustomCommandModal(true)}
            onOpenScenario={openQuickPlaybookModal}
            onClearScenario={handleClearQuickScenario}
            onQuickPlaybookVarChange={(key: string, value: any) => setQuickPlaybookVars((current: any) => ({ ...current, [key]: value }))}
            onQuickPlaybookConcurrencyChange={setQuickPlaybookConcurrency}
            onQuickRiskConfirmedChange={setQuickRiskConfirmed}
            onRunValidation={(changeTicket?: string) => runQuickPlaybook(true, changeTicket)}
            onRunApply={(changeTicket?: string) => runQuickPlaybook(false, changeTicket)}
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

      {activeTab === 'automation' && automationPage === 'scripts' && (
        <Suspense fallback={lazyPanelFallback}>
          <ScriptManagementTab language={language} showToast={showToast} />
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
            onScenarioSearchChange={handleScenarioSearch}
            onSelectScenario={handleSelectPlaybookScenario}
            onPlatformChange={handlePlaybookPlatformChange}
            onVariableChange={handlePlaybookVariableChange}
            onToggleDevice={handleTogglePlaybookDevice}
            onConcurrencyChange={setPlaybookConcurrency}
            onPreview={() => previewPlaybook(selectedScenario, playbookPlatform, playbookVars)}
            onExecuteValidation={() => executePlaybook(true)}
            onExecuteApply={() => executePlaybook(false)}
            currentUser={currentUser}
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
            onScenarioSearchChange={handleScenarioSearch}
            onOpenManualScenarioDraft={openManualScenarioDraft}
            onUseScenario={(scenario: any) => {
              // Redirect to Change Order creation with the scenario pre-selected
              navigate('/change-orders/new', { state: { scenarioId: scenario.id } });
            }}
          />
        </Suspense>
      )}

      {activeTab === 'automation' && (automationPage === 'history' || automationPage === 'schedule-history' || automationPage === 'queries') && (
        <Suspense fallback={lazyPanelFallback}>
          <ExecutionScheduleTab 
            t={t} 
            language={language} 
            showToast={showToast} 
            initialTab="history" 
            devices={devices}
            onRerun={handleRerun}
          />
        </Suspense>
      )}

      {activeTab === 'automation' && automationPage === 'inspection' && (
        <Suspense fallback={lazyPanelFallback}>
          <InspectionTab
            t={t}
            language={language}
            devices={devices}
            overview={monitorOverview?.device_health_summary || null}
            onShowDetails={handleShowDetails}
            initialView="overview"
          />
        </Suspense>
      )}

      {activeTab === 'automation' && automationPage === 'inspection-records' && (
        <Suspense fallback={lazyPanelFallback}>
          <InspectionTab
            t={t}
            language={language}
            devices={devices}
            overview={monitorOverview?.device_health_summary || null}
            onShowDetails={handleShowDetails}
            initialView="records"
          />
        </Suspense>
      )}

      {activeTab === 'automation' && automationPage === 'schedule' && (
        <Suspense fallback={lazyPanelFallback}>
          <ExecutionScheduleTab 
            t={t} 
            language={language} 
            showToast={showToast} 
            initialTab="schedules" 
            devices={devices}
            onRerun={handleRerun}
          />
        </Suspense>
      )}

      {/* Consolidated with automationPage === 'history' above */}

      {activeTab === 'automation' && automationPage === 'scheduled-jobs' && (
        <Suspense fallback={lazyPanelFallback}>
          <ScheduledJobsTab t={t} language={language} showToast={showToast} />
        </Suspense>
      )}

      {activeTab === 'automation' && automationPage === 'metrics' && (
        <Suspense fallback={lazyPanelFallback}>
          <InspectionItemsTab t={t} language={language} showToast={showToast} />
        </Suspense>
      )}

      {activeTab === 'automation' && automationPage === 'textfsm-templates' && (
        <Suspense fallback={lazyPanelFallback}>
          <TextFSMTemplatesTab t={t} language={language} />
        </Suspense>
      )}

      {activeTab === 'compliance' && isFeatureEnabled('compliance') && (
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

      {activeTab === 'config' && configPage === 'backup' && (
        <Suspense fallback={lazyPanelFallback}>
          <ConfigBackupTab
            t={t}
            language={language}
            isTakingSnapshot={isTakingSnapshot}
            onBackupAllOnline={handleRunBackupAllOnline}
            activeRunId={activeBackupRunId}
            onBackupDevice={handleBackupSingleDevice}
            onNavigateToDiff={handleNavigateToConfigDiff}
            showToast={showToast}
          />
        </Suspense>
      )}

      {activeTab === 'config' && configPage === 'schedule' && (
        <Suspense fallback={lazyPanelFallback}>
          <ConfigScheduleTab
            t={t}
            language={language}
            devices={devices}
            configSnapshots={configSnapshots || []}
            isTakingSnapshot={isTakingSnapshot}
            scheduleEnabled={scheduleEnabled}
            scheduleCron={scheduleCron}
            scheduleLoading={scheduleLoading}
            retentionDays={retentionDays}
            retentionMaxPerDevice={retentionMaxPerDevice}
            getVendorFromPlatform={(platform?: string) => {
              const p = (platform || '').toLowerCase();
              if (p.includes('cisco')) return 'Cisco';
              if (p.includes('juniper') || p.includes('junos')) return 'Juniper';
              if (p.includes('huawei')) return 'Huawei';
              if (p.includes('h3c')) return 'H3C';
              if (p.includes('arista')) return 'Arista';
              return 'Other';
            }}
            onToggleScheduleEnabled={() => setScheduleEnabled((v: boolean) => !v)}
            onCronChange={setScheduleCron}
            onRetentionDaysChange={setRetentionDays}
            onRetentionMaxPerDeviceChange={setRetentionMaxPerDevice}
            onSaveSchedule={saveScheduleConfig}
            onRunBackupNow={handleRunBackupAllOnline}
            showToast={showToast}
          />
        </Suspense>
      )}

      {activeTab === 'config' && configPage === 'diff' && (
        <Suspense fallback={lazyPanelFallback}>
          <ConfigDiffViewTab
            t={t}
            language={language}
            activeDiffLines={activeDiffLines}
            activeChangeLineIndexes={activeChangeLineIndexes}
            diffFocusChangeIdx={diffFocusChangeIdx}
            diffOnlyChanges={diffOnlyChanges}
            diffShowFullBoth={diffShowFullBoth}
            diffMode={diffMode}
            renderedDiffLines={renderedDiffLines}
            fullSideBySideRows={fullSideBySideRows}
            diffChangeBlocks={diffChangeBlocks}
            filteredDiffChangeBlocks={filteredDiffChangeBlocks}
            diffBlockQuery={diffBlockQuery}
            diffLineRefs={diffLineRefs}
            configDiffLeft={configDiffLeft}
            configDiffRight={configDiffRight}
            onToggleOnlyChanges={() => setDiffOnlyChanges((prev: boolean) => !prev)}
            onToggleFullBoth={() => setDiffShowFullBoth((prev: boolean) => !prev)}
            onDiffModeChange={setDiffMode}
            onDiffBlockQueryChange={setDiffBlockQuery}
            onReset={handleResetDiffView}
            onSelectSnapshotPair={handleSelectSnapshotPair}
            onJumpToDiff={jumpToDiff}
            onToggleQuickKeyword={(keyword: string) => setDiffBlockQuery((prev: string) => (prev.toLowerCase() === keyword ? '' : keyword))}
            onFocusDiffChangeAt={focusDiffChangeAt}
            preSelectedDeviceId={diffPreSelectedDeviceId}
          />
        </Suspense>
      )}

      {activeTab === 'config' && configPage === 'search' && (
        <Suspense fallback={lazyPanelFallback}>
          <ConfigSearchTab t={t} language={language} />
        </Suspense>
      )}
      {activeTab === 'config' && configPage === 'templates' && (
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
            onSelectTemplateIdChange={(templateId: string) => {
              setSelectedTemplateId(templateId);
              const template = configTemplates.find((item: any) => item.id === templateId);
              setEditorContent(template?.content || '');
            }}
            onAddVar={handleAddVar}
            onDeleteVar={handleDeleteVar}
            onSelectedTemplateNameChange={(value: string) => {
              setConfigTemplates((prev: any) => prev.map((template: any) => (
                template.id === selectedTemplateId ? { ...template, name: value } : template
              )));
            }}
            onSelectedTemplateVendorChange={(value: string) => {
              setConfigTemplates((prev: any) => prev.map((template: any) => (
                template.id === selectedTemplateId ? { ...template, vendor: value } : template
              )));
            }}
            onSelectedTemplateTypeChange={(value: string) => {
              setConfigTemplates((prev: any) => prev.map((template: any) => (
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

      {activeTab === 'platform-registry' && (
        <Suspense fallback={lazyPanelFallback}>
          <PlatformRegistryTab language={language} currentUser={currentUser} />
        </Suspense>
      )}

      {activeTab === 'snmp-metric-templates' && (
        <Suspense fallback={lazyPanelFallback}>
          <SnmpMetricTemplatesTab language={language} showToast={showToast} />
        </Suspense>
      )}

      {activeTab === 'users' && isFeatureEnabled('user_management') && (
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

      {activeTab === 'audit' && isFeatureEnabled('audit_logs') && (
        <Suspense fallback={lazyPanelFallback}>
          <AuditTab
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
          {ipamPage === 'locate' ? (
            <IPLocatorPage language={language} t={t} mode="toolbox" />
          ) : (
            <IPAMManagementTab language={language} t={t} ipamPage={ipamPage} />
          )}
        </Suspense>
      )}

      {activeTab === 'path-diagnose' && (
        <Suspense fallback={lazyPanelFallback}>
          <IPLocatorPage language={language} t={t} mode="diagnose-only" />
        </Suspense>
      )}

      {activeTab === 'nsot' && (
        <Suspense fallback={lazyPanelFallback}>
          <IPLocatorPage language={language} t={t} mode="nsot-only" />
        </Suspense>
      )}

      {activeTab === 'ip-locator' && (
        <Suspense fallback={lazyPanelFallback}>
          <IPLocatorPage language={language} t={t} mode="toolbox" />
        </Suspense>
      )}

      {activeTab === 'assets' && isFeatureEnabled('assets') && (
        <Suspense fallback={lazyPanelFallback}>
          <AssetManagementTab language={language} t={t} setActiveTab={setActiveTab} currentUser={currentUser} />
        </Suspense>
      )}

      {activeTab === 'tags' && (
        <Suspense fallback={lazyPanelFallback}>
          <TagManagementTab language={language} t={t} currentUser={currentUser} />
        </Suspense>
      )}

      {activeTab === 'credentials' && (
        <Suspense fallback={lazyPanelFallback}>
          <CredentialManagementTab language={language} currentUser={currentUser} />
        </Suspense>
      )}

      {activeTab === 'change-orders' && (
        <Suspense fallback={lazyPanelFallback}>
          <ChangeOrderTab
            language={language}
            t={t}
            users={users}
            scenarios={scenarios}
            configTemplates={configTemplates}
            platforms={platforms}
            currentUser={currentUser}
            findMatchingPlatform={findMatchingPlatform}
            initialView={changeOrderPage === 'my-todo' ? 'my_todo' : changeOrderPage === 'group-todo' ? 'group_todo' : changeOrderPage === 'participated' ? 'my_participated' : changeOrderPage === 'focus' ? 'my_focus' : changeOrderPage === 'drafts' ? 'my_drafts' : changeOrderPage === 'new' ? 'create' : 'all'}
          />
        </Suspense>
      )}

      {(activeTab === 'ai-center' || activeTab.startsWith('ai-')) && (
        <Suspense fallback={lazyPanelFallback}>
          <AiCenterPage activeSubTab={activeTab.startsWith('ai-') && activeTab !== 'ai-center' ? activeTab.replace('ai-', '') : 'providers'} />
        </Suspense>
      )}



    </main>
  );
};

export default AppMainContent;
