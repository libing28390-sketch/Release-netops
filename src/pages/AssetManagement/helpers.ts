import { STATUSES, TYPES } from './constants';
import { Asset } from './types';

export const statusMeta = (v: string) => STATUSES.find(s => s.value === v) || STATUSES[3];
export const typeMeta   = (v: string) => TYPES.find(t => t.value === v) || TYPES[0];

export const ago = (iso: string) => {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo`;
};

export const severityOf = (a: Asset): 'critical' | 'major' | 'warning' | 'healthy' => {
  if (a.status === 'decommissioned') return 'critical';
  if (a.status === 'maintenance') return 'major';
  if (a.warranty_expiry && new Date(a.warranty_expiry) <= new Date(Date.now() + 90 * 86400000)) return 'warning';
  if (a.status === 'inactive' || a.status === 'in_storage') return 'warning';
  return 'healthy';
};
