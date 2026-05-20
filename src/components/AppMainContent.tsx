import React, { Suspense, lazy, useMemo } from 'react';
import { useSystem } from '../hooks/useSystem';

const MonitoringCenter = lazy(() => import('./MonitoringCenter.tsx'));
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
const IPVlanTab = lazy(() => import('../pages/IPVlanTab'));
const IPLocatorPage = lazy(() => import('../pages/IPLocatorPage'));
const AssetManagementTab = lazy(() => import('../pages/AssetManagementTab'));
const CredentialManagementTab = lazy(() => import('../components/PasswordRotationPanel'));
const ChangeOrderTab = lazy(() => import('../pages/ChangeOrderTab'));
const InterfaceMonitoringTab = lazy(() => import('../pages/InterfaceMonitoringTab'));
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
const RackManagementTab = lazy(() => import('../pages/RackManagementTab'));
const TagManagementTab = lazy(() => import('../pages/TagManagementTab'));
const LicenseAdminTab = lazy(() => import('../pages/LicenseAdminTab'));
const ScriptManagementTab = lazy(() => import('../pages/ScriptManagementTab'));
const ConfigScheduleTab = lazy(() => import('../pages/ConfigScheduleTab'));
const AccessCenterTab = lazy(() => import('../pages/AccessCenterTab'));
const PAMAuditTab = lazy(() => import('../pages/PAMAuditTab'));

const lazyPanelFallback = (
  <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-black/5 bg-white/70 text-sm text-black/40">
    Loading...
  </div>
);

const AppMainContent: React.FC<{ appProps: any }> = ({ appProps }) => {
  const { isFeatureEnabled } = useSystem();
  const props = appProps as any;
  const {
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
    handleAutomationSearch,
    handleScenarioSearch,
    handleToggleBatchMode,
    handleToggleBatchDevice,
    handleSelectAutomationDevice,
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
    activeBackupRunId,
    scheduleEnabled,
    setScheduleEnabled,
    scheduleCron,
    setScheduleCron,
    scheduleLoading,
    retentionDays,
    setRetentionDays,
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
    setInventoryRefreshTick,
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
    playbookHistoryPageSize,
    setPlaybookHistoryPageSize,
    autoRefreshEnabled,
    setAutoRefreshEnabled,
    fetchSharedData,
    fetchDevicesData,
    selectedJob,
    setSelectedJob,
  } = props;

  const isStandaloneScrollTab = 
    activeTab === 'alerts' || 
    activeTab === 'alert-rules' || 
    activeTab === 'alert-history' || 
    activeTab === 'maintenance' || 
    (activeTab === 'automation' && automationPage === 'metrics');

  const getDeviceFetchMode = () => {
    if (activeTab === 'inventory') return 'full';
    if (activeTab === 'automation') return 'full';
    if (activeTab === 'config') return 'full';
    if (activeTab === 'topology') return 'full';
    if (activeTab === 'access') return 'full';
    return 'light';
  };

  const mainClassName = `relative flex-1 min-w-0 flex flex-col min-h-0 ${isStandaloneScrollTab ? 'overflow-hidden' : 'overflow-y-auto'}`;

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
            scheduledTasks={props.scheduledTasks}
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
            unreadNotificationCount={props.unreadNotificationCount}
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
            fetchMonitoringOverview={() => props.fetchMonitoringOverview(true)}
            fetchMonitoringAlerts={props.fetchMonitoringAlerts}
            fetchMonitoringRealtime={props.fetchMonitoringRealtime}
            fetchHostResources={props.fetchHostResources}
            setMonitorRealtime={props.setMonitorRealtime}
            showToast={showToast}
          />
        </Suspense>
      )}

      {activeTab === 'access' && (
        <Suspense fallback={lazyPanelFallback}>
          <AccessCenterTab devices={devices} language={language} showToast={showToast} />
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
              props.setSelectedTopologyDeviceId(deviceId);
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
              props.setSelectedTopologyDeviceId(deviceId);
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
            inventoryRows={inventoryRows}
            inventoryTotal={inventoryTotal}
            inventoryStatusCounts={inventoryStatusCounts}
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
            inventoryLifecycleFilter={inventoryLifecycleFilter}
            setInventoryLifecycleFilter={setInventoryLifecycleFilter}
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
            onRefresh={() => props.setInventoryRefreshTick((v: number) => v + 1)}
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

      {activeTab === 'topology' && (
        <Suspense fallback={lazyPanelFallback}>
          <TopologyPage
            language={language}
            topologyDiscoveryRunning={props.topologyDiscoveryRunning}
            topologyStats={props.topologyStats}
            topologyLinkStats={props.topologyLinkStats}
            topologySearch={props.topologySearch}
            topologySiteFilter={props.topologySiteFilter}
            topologyRoleFilter={props.topologyRoleFilter}
            topologyStatusFilter={props.topologyStatusFilter}
            topologySiteOptions={props.topologySiteOptions}
            topologyRoleOptions={props.topologyRoleOptions}
            topologyVisibleDevices={props.topologyVisibleDevices}
            topologyVisibleLinks={props.topologyVisibleLinks}
            selectedTopologyDeviceId={props.selectedTopologyDeviceId}
            selectedTopologyLinkKey={props.selectedTopologyLinkKey}
            selectedTopologyDevice={props.selectedTopologyDevice}
            selectedTopologyLink={props.selectedTopologyLink}
            topologyNeighborDevices={props.topologyNeighborDevices}
            topologyDeviceLinks={props.topologyDeviceLinks}
            topologyPriorityDevices={props.topologyPriorityDevices}
            topologyOrphanDevices={props.topologyOrphanDevices}
            topologyCanvasRef={props.topologyRef}
            onTriggerDiscovery={props.handleTriggerDiscovery}
            onExportMap={props.handleExportMap}
            onTopologySearchChange={props.setTopologySearch}
            onTopologySiteFilterChange={props.setTopologySiteFilter}
            onTopologyRoleFilterChange={props.setTopologyRoleFilter}
            onTopologyStatusFilterChange={props.setTopologyStatusFilter}
            onSelectTopologyDevice={props.setSelectedTopologyDeviceId}
            onSelectTopologyLink={props.setSelectedTopologyLinkKey}
            onOpenDeviceDetail={handleShowDetails}
            onOpenMonitoring={() => navTo('/monitoring')}
            formatTopologyPort={props.formatTopologyPort}
            formatTopologyInterfaceTelemetry={props.formatTopologyInterfaceTelemetry}
            formatTopologyLastSeen={props.formatTopologyLastSeen}
            formatTopologyOperationalState={props.formatTopologyOperationalState}
            formatTopologyEvidenceLabel={props.formatTopologyEvidenceLabel}
            getTopologyOperationalTone={props.getTopologyOperationalTone}
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
            selectedDevice={props.selectedDevice}
            batchMode={props.batchMode}
            batchDeviceIds={props.batchDeviceIds}
            automationSearch={props.automationSearch}
            scenarioSearch={props.scenarioSearch}
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
            hasQuickTargets={props.hasQuickTargets}
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
            savedQueries={props.savedQueries}
            onNavigate={navigate}
            onAutomationSearchChange={props.handleAutomationSearch}
            onScenarioSearchChange={props.handleScenarioSearch}
            onToggleBatchMode={handleToggleBatchMode}
            onToggleBatchDevice={handleToggleBatchDevice}
            onSelectDevice={handleSelectAutomationDevice}
            onOpenCustomCommandModal={() => props.setShowCustomCommandModal(true)}
            onOpenScenario={openQuickPlaybookModal}
            onClearScenario={handleClearQuickScenario}
            onQuickPlaybookVarChange={(key: string, value: any) => props.setQuickPlaybookVars((current: any) => ({ ...current, [key]: value }))}
            onQuickPlaybookConcurrencyChange={props.setQuickPlaybookConcurrency}
            onQuickRiskConfirmedChange={props.setQuickRiskConfirmed}
            onRunValidation={(changeTicket?: string) => runQuickPlaybook(true, changeTicket)}
            onRunApply={(changeTicket?: string) => runQuickPlaybook(false, changeTicket)}
            onRunQuickQuery={runQuickQuery}
            onResetQuickQuery={handleResetQuickQuery}
            onQuickQueryViewChange={setQuickQueryView}
            onQuickQueryMaximizedChange={setQuickQueryMaximized}
            onOpenCommandPreview={() => props.setShowCmdPreviewModal(true)}
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
            onToggleDevice={props.handleTogglePlaybookDevice}
            onConcurrencyChange={props.setPlaybookConcurrency}
            onPreview={props.previewPlaybook}
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
            onRerun={props.handleRerun}
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
            onRerun={props.handleRerun}
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
            activeDiffLines={props.activeDiffLines}
            activeChangeLineIndexes={props.activeChangeLineIndexes}
            diffFocusChangeIdx={props.diffFocusChangeIdx}
            diffOnlyChanges={props.diffOnlyChanges}
            diffShowFullBoth={props.diffShowFullBoth}
            renderedDiffLines={props.renderedDiffLines}
            fullSideBySideRows={props.fullSideBySideRows}
            diffChangeBlocks={props.diffChangeBlocks}
            filteredDiffChangeBlocks={props.filteredDiffChangeBlocks}
            diffBlockQuery={props.diffBlockQuery}
            diffLineRefs={props.diffLineRefs}
            configDiffLeft={props.configDiffLeft}
            configDiffRight={props.configDiffRight}
            onToggleOnlyChanges={() => props.setDiffOnlyChanges((prev: boolean) => !prev)}
            onToggleFullBoth={() => props.setDiffShowFullBoth((prev: boolean) => !prev)}
            onDiffBlockQueryChange={props.setDiffBlockQuery}
            onReset={handleResetDiffView}
            onSelectSnapshotPair={props.handleSelectSnapshotPair}
            onJumpToDiff={props.jumpToDiff}
            onToggleQuickKeyword={(keyword: string) => props.setDiffBlockQuery((prev: string) => (prev.toLowerCase() === keyword ? '' : keyword))}
            onFocusDiffChangeAt={props.focusDiffChangeAt}
            preSelectedDeviceId={diffPreSelectedDeviceId}
          />
        </Suspense>
      )}

      {activeTab === 'config' && configPage === 'search' && (
        <Suspense fallback={lazyPanelFallback}>
          <ConfigSearchTab t={t} />
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
            onValidate={props.handleValidateTemplateWorkspace}
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
            openAuditEventDetail={props.openAuditEventDetail}
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

      {activeTab === 'ip-locator' && (
        <Suspense fallback={lazyPanelFallback}>
          <IPLocatorPage language={language} t={t} />
        </Suspense>
      )}

      {activeTab === 'assets' && isFeatureEnabled('assets') && (
        <Suspense fallback={lazyPanelFallback}>
          <AssetManagementTab language={language} t={t} setActiveTab={setActiveTab} />
        </Suspense>
      )}

      {activeTab === 'tags' && (
        <Suspense fallback={lazyPanelFallback}>
          <TagManagementTab language={language} t={t} />
        </Suspense>
      )}

      {activeTab === 'credentials' && (
        <Suspense fallback={lazyPanelFallback}>
          <CredentialManagementTab language={language} />
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
            findMatchingPlatform={props.findMatchingPlatform}
            initialView={changeOrderPage === 'my-todo' ? 'my_todo' : changeOrderPage === 'group-todo' ? 'group_todo' : changeOrderPage === 'participated' ? 'my_participated' : changeOrderPage === 'focus' ? 'my_focus' : changeOrderPage === 'drafts' ? 'my_drafts' : changeOrderPage === 'new' ? 'create' : 'all'}
          />
        </Suspense>
      )}

      {activeTab === 'license' && (
        <Suspense fallback={lazyPanelFallback}>
          <LicenseAdminTab language={language} t={t} onLicenseUpdate={props.checkLicenseStatus} />
        </Suspense>
      )}
    </main>
  );
};

export default AppMainContent;
