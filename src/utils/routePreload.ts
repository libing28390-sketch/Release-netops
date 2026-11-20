const prefetchedKeys = new Set<string>();

type ChunkLoader = () => Promise<unknown>;

const ROUTE_PRELOADERS: Array<[RegExp, string, ChunkLoader]> = [
  [/^\/(dashboard)?$/, 'home', () => import('../pages/HomePage')],
  [/^\/monitor\/overview/, 'dashboard', () => import('../pages/DashboardTab')],
  [/^\/monitor\/telemetry/, 'monitoring', () => import('../components/MonitoringCenter.tsx')],
  [/^\/monitor\/topology/, 'topology', () => import('../pages/TopologyPage')],
  [/^\/monitor\/servers/, 'server-monitoring', () => import('../components/ServerMonitoring.tsx')],
  [/^\/monitor\/networks/, 'inventory-devices', () => import('../pages/InventoryDevicesTab')],
  [/^\/monitor\/outbound/, 'outbound', () => import('../pages/OutboundHealthPage')],
  [/^\/monitor\/circuits/, 'wan-circuits', () => import('../pages/WanCircuitsPage')],
  [/^\/monitor\/reports/, 'monitor-reports', () => import('../pages/MonitoringReportsPage')],
  [/^\/monitor\/dashboards/, 'grafana', () => import('../pages/GrafanaDashboardPage')],
  [/^\/monitor\/snmp-walk/, 'snmp-walk', () => import('../pages/SnmpWalkPage')],
  [/^\/assets\/(assets|dashboard|network-devices|servers)/, 'assets', () => import('../pages/AssetManagementTab')],
  [/^\/assets\/racks|^\/cmdb\/racks/, 'racks', () => import('../pages/RackManagementTab')],
  [/^\/ipam\/locate/, 'ip-locator', () => import('../pages/IPLocatorPage')],
  [/^\/ipam\//, 'ipam', () => import('../pages/IPAMManagementTab')],
  [/^\/cmdb\/credentials/, 'credentials', () => import('../components/PasswordRotationPanel')],
  [/^\/cmdb\//, 'cmdb', () => import('../pages/CmdbManagementTab')],
  [/^\/alerts\/desk/, 'alert-desk', () => import('../pages/AlertDeskTab')],
  [/^\/alerts\/rules/, 'alert-rules', () => import('../pages/AlertRulesTab')],
  [/^\/alerts\/history/, 'alert-history', () => import('../pages/AlertHistoryTab')],
  [/^\/config\/backup/, 'config-backup', () => import('../pages/ConfigBackupTab')],
  [/^\/config\/diff/, 'config-diff', () => import('../pages/ConfigDiffViewTab')],
  [/^\/config\/search/, 'config-search', () => import('../pages/ConfigSearchTab')],
  [/^\/config\/schedule/, 'config-schedule', () => import('../pages/ConfigScheduleTab')],
  [/^\/automation\/quick-ops|^\/automation\/execute/, 'auto-exec', () => import('../pages/AutomationExecuteTab')],
  [/^\/automation\/history/, 'auto-history', () => import('../pages/AutomationHistoryTab')],
  [/^\/automation\/inspections/, 'inspection', () => import('../pages/InspectionTab')],
  [/^\/automation\/scheduled-jobs/, 'scheduled-jobs', () => import('../pages/ScheduledJobsTab')],
  [/^\/change-orders\//, 'change-orders', () => import('../pages/ChangeOrderTab')],
  [/^\/access\/workspace/, 'access', () => import('../pages/AccessCenterTab')],
  [/^\/access\/pam-audit/, 'pam-audit', () => import('../pages/PAMAuditTab')],
  [/^\/capacity\//, 'capacity', () => import('../pages/CapacityPlanningTab')],
  [/^\/management\/audit/, 'audit', () => import('../pages/AuditTab')],
  [/^\/management\/users/, 'users', () => import('../pages/UsersTab')],
  [/^\/management\/settings/, 'settings', () => import('../pages/PlatformSettingsTab')],
  [/^\/ai\//, 'ai-center', () => import('../pages/ai/AiCenterPage')],
  [/^\/tickets/, 'tickets', () => import('../pages/Tickets')],
];

export function preloadRouteChunk(pathname: string): void {
  const cleanPath = String(pathname || '/').split('?')[0].split('#')[0] || '/';
  for (const [pattern, key, loader] of ROUTE_PRELOADERS) {
    if (pattern.test(cleanPath)) {
      if (!prefetchedKeys.has(key)) {
        prefetchedKeys.add(key);
        void loader().catch(() => {
          prefetchedKeys.delete(key);
        });
      }
      return;
    }
  }
}

export function resetRoutePreloadRegistry(): void {
  prefetchedKeys.clear();
}
