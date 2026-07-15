import React, { createContext, useContext, ReactNode } from 'react';
import type { NavigateFunction } from 'react-router-dom';
import type { Device, User as UserType, SessionUser } from '../types';
import type { Language } from '../i18n.tsx';

// ========== Core App Context ==========
interface CoreAppContextValue {
  // route + i18n
  activeTab: string;
  inventorySubPage: string;
  configPage: string;
  automationPage: string;
  changeOrderPage: string;
  ipamPage: string;
  cmdbPage: string;
  language: Language;
  t: (key: string) => string;
  navigate: NavigateFunction;
  navTo: (path: string) => void;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  setActiveTab: (tab: string) => void;
  isAuthenticated: boolean;
  
  // current user / users
  currentUser: SessionUser;
  users: UserType[];
  
  // devices
  devices: Device[];
  fetchDevicesData: () => Promise<void>;
  devicesLastUpdatedAt: number;
}

const CoreAppContext = createContext<CoreAppContextValue | null>(null);

export const useCoreApp = () => {
  const context = useContext(CoreAppContext);
  if (!context) {
    throw new Error('useCoreApp must be used within CoreAppProvider');
  }
  return context;
};

interface CoreAppProviderProps {
  children: ReactNode;
  value: CoreAppContextValue;
}

export const CoreAppProvider: React.FC<CoreAppProviderProps> = ({ children, value }) => (
  <CoreAppContext.Provider value={value}>{children}</CoreAppContext.Provider>
);

// ========== Dashboard Context ==========
interface DashboardContextValue {
  jobs: any[];
  notifications: any[];
  hostResources: any;
  trendDays: 7 | 30;
  setTrendDays: (days: 7 | 30) => void;
  complianceTrend: any;
  platformData: any;
  dashBannerCollapsed: boolean;
  setDashBannerCollapsed: (collapsed: boolean) => void;
  dashLastRefresh: Date;
  autoRefreshEnabled: boolean;
  setAutoRefreshEnabled: (enabled: boolean) => void;
  fetchSharedData: () => Promise<void>;
  fetchDevicesData: () => Promise<void>;
  scheduledTasks: any[];
  unreadNotificationCount: number;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

export const useDashboard = () => {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error('useDashboard must be used within DashboardProvider');
  }
  return context;
};

interface DashboardProviderProps {
  children: ReactNode;
  value: DashboardContextValue;
}

export const DashboardProvider: React.FC<DashboardProviderProps> = ({ children, value }) => (
  <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>
);

// ========== Inventory Context ==========
interface InventoryContextValue {
  handleImport: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleExport: () => void;
  handleShowDetails: (device: Device) => void;
  handleTestConnection: (device?: Device | null, mode?: 'quick' | 'deep') => Promise<void>;
  deviceConnectionChecks: Record<string, any>;
  connectionTestingDeviceId: string | null;
  setShowAddModal: (show: boolean) => void;
  setShowEditModal: (show: boolean) => void;
  setEditingDevice: (device: Device | null) => void;
  setEditForm: (form: Partial<Device>) => void;
  setSelectedDevice: (device: Device | null) => void;
  selectedDevice: Device | null;
  snmpTestingId: string | null;
  snmpSyncingId: string | null;
  handleSnmpTest: (deviceId: string) => Promise<void>;
  handleSnmpSyncNow: (deviceId: string) => Promise<void>;
}

const InventoryContext = createContext<InventoryContextValue | null>(null);

export const useInventory = () => {
  const context = useContext(InventoryContext);
  if (!context) {
    throw new Error('useInventory must be used within InventoryProvider');
  }
  return context;
};

interface InventoryProviderProps {
  children: ReactNode;
  value: InventoryContextValue;
}

export const InventoryProvider: React.FC<InventoryProviderProps> = ({ children, value }) => (
  <InventoryContext.Provider value={value}>{children}</InventoryContext.Provider>
);