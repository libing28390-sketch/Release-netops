import React, { createContext, useContext, ReactNode } from 'react';
import type { Device, TagDefinition } from '../types';
import type { TagFilterConfig } from '../components/TagConditionPicker';

type TopologyGraphView = 'all' | 'physical' | 'l2' | 'l3' | 'logical' | 'site' | 'external' | 'oob';

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
  topologyGraphView: TopologyGraphView;
  topologyTagFilter: TagFilterConfig;
  topologyRoleFilter: string;
  topologyStatusFilter: 'all' | 'online' | 'offline' | 'pending';
  topologyLinkStatusFilter: 'all' | 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
  topologyProtocolFilter: 'all' | 'lldp';
  topologySiteOptions: Array<{ id: string; name: string }>;
  topologyTagOptions: TagDefinition[];
  topologyTagCandidateDevices: Device[];
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
  setTopologyGraphView: (view: TopologyGraphView) => void;
  setTopologyTagFilter: (conditions: TagFilterConfig) => void;
  setTopologyRoleFilter: (role: string) => void;
  setTopologyStatusFilter: (status: "pending" | "offline" | "online" | "all") => void;
  setTopologyLinkStatusFilter: (status: "all" | "up" | "degraded" | "down" | "stale" | "unknown") => void;
  setTopologyProtocolFilter: (protocol: "all" | "lldp") => void;
  handleConfirmTopologyRelation: (edgeId: string, relationType: string) => Promise<void>;
  loadTopologyHistory: (edgeId: string) => Promise<Array<{
    id: string;
    entity_type: string;
    entity_id: string;
    event_type: string;
    before?: unknown;
    after?: unknown;
    source?: string;
    actor?: string;
    created_at?: string;
  }>>;
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
