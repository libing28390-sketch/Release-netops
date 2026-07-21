import React, { createContext, useContext, ReactNode } from 'react';
import type { Device } from '../types';

interface TopologyContextValue {
  setSelectedTopologyDeviceId: (id: string | null) => void;
  setSelectedTopologyLinkKey: (key: string | null) => void;
  topologyDiscoveryRunning: boolean;
  topologyStats: {
    nodeCount: number;
    linkCount: number;
    siteCount: number;
    atRiskCount: number;
    orphanCount: number;
  };
  topologyLinkStats: {
    up: number;
    degraded: number;
    down: number;
    stale: number;
    multiSource: number;
  };
  topologySearch: string;
  topologySiteFilter: string;
  topologyRoleFilter: string;
  topologyStatusFilter: 'all' | 'online' | 'offline' | 'pending';
  topologyLinkStatusFilter: 'all' | 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
  topologyProtocolFilter: 'all' | 'lldp' | 'cdp';
  topologySiteOptions: Array<{ id: string; name: string }>;
  topologyDiscoveryProgress: {
    id: string;
    status: string;
    total_devices: number;
    processed_devices: number;
    success_devices: number;
    failed_devices: number;
    progress_percent: number;
  } | null;
  topologyDiscoveryDevices: any[];
  topologySites: any[];
  topologyDataError: string;
  topologyRoleOptions: string[];
  topologyVisibleDevices: Device[];
  topologyVisibleLinks: any[];
  selectedTopologyDeviceId: string | null;
  selectedTopologyLinkKey: string | null;
  selectedTopologyDevice: Device | null;
  selectedTopologyLink: any | null;
  topologyNeighborDevices: Device[];
  topologyDeviceLinks: any[];
  topologyPriorityDevices: Device[];
  topologyOrphanDevices: Device[];
  topologyRef: React.RefObject<HTMLDivElement>;
  hideStaleLinks: boolean;
  setHideStaleLinks: (value: boolean) => void;
  hideOrphanDevices: boolean;
  setHideOrphanDevices: (value: boolean) => void;
  handleTriggerDiscovery: () => Promise<void>;
  handleCancelDiscovery: () => Promise<void>;
  handleExportMap: () => Promise<void>;
  setTopologySearch: (search: string) => void;
  setTopologySiteFilter: (site: string) => void;
  setTopologyRoleFilter: (role: string) => void;
  setTopologyStatusFilter: (status: "pending" | "offline" | "online" | "all") => void;
  setTopologyLinkStatusFilter: (status: "all" | "up" | "degraded" | "down" | "stale" | "unknown") => void;
  setTopologyProtocolFilter: (protocol: "all" | "lldp" | "cdp") => void;
  formatTopologyPort: (value?: string) => string;
  formatTopologyInterfaceTelemetry: (snapshot: any) => string;
  formatTopologyLastSeen: (value?: string) => string;
  formatTopologyOperationalState: (state?: string) => string;
  formatTopologyEvidenceLabel: (value: string) => string;
  getTopologyOperationalTone: (state?: string) => any;
}

const TopologyContext = createContext<TopologyContextValue | null>(null);

export const useTopologyContext = () => {
  const context = useContext(TopologyContext);
  if (!context) {
    throw new Error('useTopologyContext must be used within TopologyProvider');
  }
  return context;
};

interface TopologyProviderProps {
  children: ReactNode;
  value: TopologyContextValue;
}

export const TopologyProvider: React.FC<TopologyProviderProps> = ({ children, value }) => (
  <TopologyContext.Provider value={value}>{children}</TopologyContext.Provider>
);
