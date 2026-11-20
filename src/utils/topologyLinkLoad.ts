export const TOPOLOGY_LINK_LOAD_TIERS = [
  { color: '#16a34a', label: '<70%', labelZh: '<70%' },
  { color: '#d97706', label: '70–<85%', labelZh: '70–<85%' },
  { color: '#dc2626', label: '≥85%', labelZh: '≥85%' },
  { color: '#64748b', label: 'No data', labelZh: '无数据' },
] as const;

export function getTopologyLinkUtilization(link: {
  operational_state?: string;
  source_interface_snapshot?: unknown;
  target_interface_snapshot?: unknown;
}): number | null {
  if (link.operational_state === 'stale' || link.operational_state === 'down') return null;
  const values = [link.source_interface_snapshot, link.target_interface_snapshot]
    .map((snapshot) => {
      if (!snapshot || typeof snapshot !== 'object') return undefined;
      const endpoint = snapshot as { status?: string; maxUtilizationPct?: unknown };
      return endpoint.status === 'down' ? undefined : endpoint.maxUtilizationPct;
    })
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0);
  return values.length ? Math.max(...values) : null;
}

export function getTopologyLinkLoadTier(utilization: number | null) {
  if (utilization === null) return TOPOLOGY_LINK_LOAD_TIERS[3];
  if (utilization >= 85) return TOPOLOGY_LINK_LOAD_TIERS[2];
  if (utilization >= 70) return TOPOLOGY_LINK_LOAD_TIERS[1];
  return TOPOLOGY_LINK_LOAD_TIERS[0];
}

export function formatTopologyLinkUtilization(utilization: number) {
  if (utilization > 0 && utilization < 0.1) return '<0.1%';
  return `${Math.floor(utilization * 10) / 10}%`;
}
