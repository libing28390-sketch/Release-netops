import React, { ReactNode } from 'react';
import { CoreAppProvider, DashboardProvider, InventoryProvider } from './AppDomainContext';
import { AutomationProvider } from './AutomationContext';
import { ConfigProvider } from './ConfigContext';
import { ManagementProvider } from './ManagementContext';
import { TopologyProvider } from './TopologyContext';

interface AppProvidersProps {
  children: ReactNode;
  coreApp: Parameters<typeof CoreAppProvider>[0]['value'];
  dashboard: Parameters<typeof DashboardProvider>[0]['value'];
  inventory: Parameters<typeof InventoryProvider>[0]['value'];
  automation: Parameters<typeof AutomationProvider>[0]['value'];
  config: Parameters<typeof ConfigProvider>[0]['value'];
  management: Parameters<typeof ManagementProvider>[0]['value'];
  topology: Parameters<typeof TopologyProvider>[0]['value'];
}

export const AppProviders: React.FC<AppProvidersProps> = ({
  children,
  coreApp,
  dashboard,
  inventory,
  automation,
  config,
  management,
  topology,
}) => (
  <CoreAppProvider value={coreApp}>
    <DashboardProvider value={dashboard}>
      <InventoryProvider value={inventory}>
        <AutomationProvider value={automation}>
          <ConfigProvider value={config}>
            <ManagementProvider value={management}>
              <TopologyProvider value={topology}>
                {children}
              </TopologyProvider>
            </ManagementProvider>
          </ConfigProvider>
        </AutomationProvider>
      </InventoryProvider>
    </DashboardProvider>
  </CoreAppProvider>
);