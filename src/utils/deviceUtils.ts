import type { Device } from '../types';

export const displaySiteLabel = (raw: any): string => {
  for (const value of [raw?.site_name, raw?.site_code, raw?.site]) {
    const label = typeof value === 'string' ? value.trim() : '';
    if (label && !/^site-[a-z0-9]+$/i.test(label)) return label;
  }
  return '';
};

export const safeJsonArray = (value: any) => {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
};

export const normalizeDeviceRecord = (raw: any): Device => {
  const hostname = typeof raw?.hostname === 'string' && raw.hostname.trim()
    ? raw.hostname
    : (typeof raw?.id === 'string' ? raw.id : 'Unknown');

  return {
    ...raw,
    id: String(raw?.id || ''),
    hostname,
    ip_address: typeof raw?.ip_address === 'string' ? raw.ip_address : '',
    platform: typeof raw?.platform === 'string' ? raw.platform : 'unknown',
    status: (raw?.status === 'online' || raw?.status === 'offline' || raw?.status === 'pending') ? raw.status : 'offline',
    compliance: (raw?.compliance === 'compliant' || raw?.compliance === 'non-compliant' || raw?.compliance === 'unknown') ? raw.compliance : 'unknown',
    role: typeof raw?.role === 'string' ? raw.role : '',
    site: displaySiteLabel(raw),
    model: typeof raw?.model === 'string' ? raw.model : '',
    version: typeof raw?.version === 'string' ? raw.version : '',
    sn: typeof raw?.sn === 'string' ? raw.sn : '',
    uptime: typeof raw?.uptime === 'string' ? raw.uptime : '',
    connection_method: raw?.connection_method === 'netconf' ? 'netconf' : 'ssh',
    config_history: safeJsonArray(raw?.config_history),
    interface_data: safeJsonArray(raw?.interface_data),
    cpu_history: safeJsonArray(raw?.cpu_history),
    memory_history: safeJsonArray(raw?.memory_history),
    snmp_cpu_oid: typeof raw?.snmp_cpu_oid === 'string' ? raw.snmp_cpu_oid : '',
    snmp_memory_oid: typeof raw?.snmp_memory_oid === 'string' ? raw.snmp_memory_oid : '',
    health_status: ['healthy', 'warning', 'critical', 'unknown'].includes(String(raw?.health_status)) ? raw.health_status : 'unknown',
    health_score: typeof raw?.health_score === 'number' ? raw.health_score : Number(raw?.health_score || 0),
    health_summary: typeof raw?.health_summary === 'string' ? raw.health_summary : '',
    health_reasons: Array.isArray(raw?.health_reasons) ? raw.health_reasons : [],
    open_alert_count: typeof raw?.open_alert_count === 'number' ? raw.open_alert_count : Number(raw?.open_alert_count || 0),
    critical_open_alerts: typeof raw?.critical_open_alerts === 'number' ? raw.critical_open_alerts : Number(raw?.critical_open_alerts || 0),
    major_open_alerts: typeof raw?.major_open_alerts === 'number' ? raw.major_open_alerts : Number(raw?.major_open_alerts || 0),
    warning_open_alerts: typeof raw?.warning_open_alerts === 'number' ? raw.warning_open_alerts : Number(raw?.warning_open_alerts || 0),
    interface_down_count: typeof raw?.interface_down_count === 'number' ? raw.interface_down_count : Number(raw?.interface_down_count || 0),
    interface_flap_count: typeof raw?.interface_flap_count === 'number' ? raw.interface_flap_count : Number(raw?.interface_flap_count || 0),
    high_util_interface_count: typeof raw?.high_util_interface_count === 'number' ? raw.high_util_interface_count : Number(raw?.high_util_interface_count || 0),
    interface_error_count: typeof raw?.interface_error_count === 'number' ? raw.interface_error_count : Number(raw?.interface_error_count || 0),
  } as Device;
};
