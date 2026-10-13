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
  const onlineStatus = a.online_status || (a.status === 'active' ? 'online' : a.status === 'inactive' ? 'offline' : 'pending');

  // 1. Critical (严重故障/离线/已退役)
  if (onlineStatus === 'offline' || a.status === 'inactive' || a.status === 'decommissioned' || a.lifecycle_status === 'decommissioned') {
    return 'critical';
  }

  // 2. Major (重要问题/维护中)
  if (a.status === 'maintenance' || a.lifecycle_status === 'maintenance') {
    return 'major';
  }

  // 3. Warning (需要关注 / 临期保修 90 天内 / 库存中 / 待投产)
  if (a.warranty_expiry) {
    const exp = new Date(a.warranty_expiry).getTime();
    const now = Date.now();
    // Only future dates within 90 days are "expiring soon", matching backend warranty_expiring_soon
    if (!Number.isNaN(exp) && exp >= now && exp <= now + 90 * 86400000) {
      return 'warning';
    }
  }
  if (a.status === 'in_storage' || a.lifecycle_status === 'staging') {
    return 'warning';
  }

  // 4. Healthy (正常运行)
  return 'healthy';
};
