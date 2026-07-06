import { useEffect } from 'react';
import type { Device } from '../types';

interface TopologyLinkLike {
  id?: string;
  link_key?: string;
}

interface UseTopologySelectionSyncParams {
  selectedTopologyDeviceId: string | null;
  setSelectedTopologyDeviceId: (value: string | null) => void;
  selectedTopologyLinkKey: string | null;
  setSelectedTopologyLinkKey: (value: string | null) => void;
  topologyVisibleDevices: Device[];
  topologyDeviceLinks: TopologyLinkLike[];
}

export const useTopologySelectionSync = ({
  selectedTopologyDeviceId,
  setSelectedTopologyDeviceId,
  selectedTopologyLinkKey,
  setSelectedTopologyLinkKey,
  topologyVisibleDevices,
  topologyDeviceLinks,
}: UseTopologySelectionSyncParams) => {
  useEffect(() => {
    if (topologyVisibleDevices.length === 0) {
      if (selectedTopologyDeviceId !== null) setSelectedTopologyDeviceId(null);
      if (selectedTopologyLinkKey !== null) setSelectedTopologyLinkKey(null);
      return;
    }

    if (!selectedTopologyDeviceId || !topologyVisibleDevices.some((device) => device.id === selectedTopologyDeviceId)) {
      setSelectedTopologyDeviceId(topologyVisibleDevices[0].id);
    }
  }, [
    selectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyDeviceId,
    setSelectedTopologyLinkKey,
    topologyVisibleDevices,
  ]);

  useEffect(() => {
    if (!selectedTopologyDeviceId) {
      if (selectedTopologyLinkKey !== null) setSelectedTopologyLinkKey(null);
      return;
    }

    if (topologyDeviceLinks.length === 0) {
      if (selectedTopologyLinkKey !== null) setSelectedTopologyLinkKey(null);
      return;
    }

    if (!selectedTopologyLinkKey || !topologyDeviceLinks.some((link) => (link.link_key || link.id) === selectedTopologyLinkKey)) {
      setSelectedTopologyLinkKey(topologyDeviceLinks[0].link_key || topologyDeviceLinks[0].id || null);
    }
  }, [
    selectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyLinkKey,
    topologyDeviceLinks,
  ]);
};
