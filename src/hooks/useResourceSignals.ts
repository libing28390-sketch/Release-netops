import { useMemo } from 'react';
import type { HostResourceSnapshot } from '../types';
import { formatResourcePercent } from '../utils/resourceFormatters';

interface UseResourceSignalsParams {
  hostResources: HostResourceSnapshot | null | undefined;
  unreadNotificationCount: number;
  language: string;
}

export const useResourceSignals = ({
  hostResources,
  unreadNotificationCount,
  language,
}: UseResourceSignalsParams) => {
  const hostResourceTone = useMemo(() => (
    hostResources?.status === 'critical'
      ? 'bg-red-500/15 text-red-200 border-red-400/25'
      : hostResources?.status === 'degraded'
        ? 'bg-amber-500/15 text-amber-100 border-amber-300/25'
        : 'bg-emerald-500/15 text-emerald-100 border-emerald-300/25'
  ), [hostResources?.status]);

  const hostResourceSummary = useMemo(() => (
    hostResources
      ? `CPU ${formatResourcePercent(hostResources.cpu_percent)} / MEM ${formatResourcePercent(hostResources.memory_percent)} / DISK ${formatResourcePercent(hostResources.disk_percent)}`
      : (language === 'zh' ? '等待资源数据' : 'Waiting for resource data')
  ), [hostResources, language]);

  const alertNavTone = useMemo(() => (
    unreadNotificationCount > 20
      ? 'bg-red-500/15 text-red-200 border-red-400/25'
      : unreadNotificationCount > 0
        ? 'bg-amber-500/15 text-amber-100 border-amber-300/25'
        : 'bg-emerald-500/15 text-emerald-100 border-emerald-300/25'
  ), [unreadNotificationCount]);

  return {
    hostResourceTone,
    hostResourceSummary,
    alertNavTone,
  };
};
