/**
 * Presentation of a device interface address's liveness.
 *
 * Loopback, point-to-point and management addresses rarely appear in ARP
 * tables, so the backend judges them by the owning interface's last collected
 * state (``interface_liveness``). This module only formats that fact.
 */

export interface InterfaceLiveness {
  state: 'up' | 'down' | 'admin_down' | 'unknown';
  freshness: 'recent' | 'historical' | 'unknown';
  observed_at?: string;
  source?: 'snmp' | 'cli_snapshot' | string;
  age_minutes?: number | null;
  window_minutes?: number;
  alive?: boolean;
}

export type InterfaceLivenessTone = 'current' | 'stale' | 'down';

export interface InterfaceLivenessBadge {
  label: string;
  ageText: string;
  tone: InterfaceLivenessTone;
  title: string;
}

/** Relative age such as "5 分钟前" / "3 小时前" / "11 天前"; empty when unknown. */
export function formatLivenessAge(minutes: number | null | undefined, zh: boolean): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes) || minutes < 0) return '';
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  if (minutes < 2880) {
    const hours = Math.floor(minutes / 60);
    return zh ? `${hours} 小时前` : `${hours}h ago`;
  }
  const days = Math.floor(minutes / 1440);
  return zh ? `${days} 天前` : `${days}d ago`;
}

/** Window length such as "1 天" / "6 小时" for the "older than" hint. */
export function formatLivenessWindow(minutes: number | null | undefined, zh: boolean): string {
  const value = minutes && minutes > 0 ? minutes : 1440;
  if (value % 1440 === 0) return zh ? `${value / 1440} 天` : `${value / 1440} d`;
  if (value % 60 === 0) return zh ? `${value / 60} 小时` : `${value / 60} h`;
  return zh ? `${value} 分钟` : `${value} min`;
}

export function interfaceLivenessSourceLabel(source: string | undefined, zh: boolean): string {
  if (source === 'snmp') return zh ? 'SNMP 接口表' : 'SNMP IF-MIB';
  if (source === 'cli_snapshot') return zh ? 'CLI 接口采集' : 'CLI interface snapshot';
  return zh ? '未知来源' : 'unknown source';
}

/** Compact badge shown under the status column; ``null`` when there is nothing to show. */
export function describeInterfaceLiveness(
  live: InterfaceLiveness | null | undefined,
  zh: boolean,
): InterfaceLivenessBadge | null {
  if (!live || live.state === 'unknown') return null;
  const ageText = formatLivenessAge(live.age_minutes, zh);
  const label = live.state === 'up'
    ? (zh ? '接口 up' : 'Intf up')
    : live.state === 'admin_down'
      ? (zh ? '接口已关闭' : 'Intf shut')
      : (zh ? '接口 down' : 'Intf down');
  const tone: InterfaceLivenessTone = live.state !== 'up'
    ? 'down'
    : live.freshness === 'recent' ? 'current' : 'stale';
  const source = interfaceLivenessSourceLabel(live.source, zh);
  const windowText = formatLivenessWindow(live.window_minutes, zh);
  const title = zh
    ? `设备接口地址，存活以接口状态为准（来源：${source}${ageText ? `，${ageText}采集` : ''}${live.freshness === 'historical' ? `，已超过 ${windowText}，可能不是当前状态` : ''}）`
    : `Device interface address; liveness from interface state (${source}${ageText ? `, collected ${ageText}` : ''}${live.freshness === 'historical' ? `, older than ${windowText}` : ''})`;
  return { label, ageText, tone, title };
}
