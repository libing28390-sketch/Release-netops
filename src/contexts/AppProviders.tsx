import React, { ReactNode, useRef } from 'react';
import { CoreAppProvider, DashboardProvider, InventoryProvider } from './AppDomainContext';
import { AutomationProvider } from './AutomationContext';
import { ConfigProvider } from './ConfigContext';
import { ManagementProvider } from './ManagementContext';
import { TopologyProvider } from './TopologyContext';

/**
 * Returns the previous object reference whenever all enumerable own properties
 * are identical under Object.is. Prevents inline provider object literals in
 * App.tsx from cascading re-renders across unrelated domain consumers.
 */
export function useShallowStableObject<T extends object>(next: T): T {
  const ref = useRef<T>(next);
  const prev = ref.current;
  if (prev === next) return prev;

  const prevRecord = prev as Record<string, unknown>;
  const nextRecord = next as Record<string, unknown>;
  const nextKeys = Object.keys(nextRecord);
  const prevKeys = Object.keys(prevRecord);

  let isSame = nextKeys.length === prevKeys.length;
  if (isSame) {
    for (let i = 0; i < nextKeys.length; i += 1) {
      const key = nextKeys[i];
      if (!Object.is(prevRecord[key], nextRecord[key])) {
        isSame = false;
        break;
      }
    }
  }
  if (!isSame) {
    ref.current = next;
  }
  return ref.current;
}

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
}) => {
  const stableCoreApp = useShallowStableObject(coreApp);
  const stableDashboard = useShallowStableObject(dashboard);
  const stableInventory = useShallowStableObject(inventory);
  const stableAutomation = useShallowStableObject(automation);
  const stableConfig = useShallowStableObject(config);
  const stableManagement = useShallowStableObject(management);
  const stableTopology = useShallowStableObject(topology);

  return (
    <CoreAppProvider value={stableCoreApp}>
      <DashboardProvider value={stableDashboard}>
        <InventoryProvider value={stableInventory}>
          <AutomationProvider value={stableAutomation}>
            <ConfigProvider value={stableConfig}>
              <ManagementProvider value={stableManagement}>
                <TopologyProvider value={stableTopology}>
                  {children}
                </TopologyProvider>
              </ManagementProvider>
            </ConfigProvider>
          </AutomationProvider>
        </InventoryProvider>
      </DashboardProvider>
    </CoreAppProvider>
  );
};
