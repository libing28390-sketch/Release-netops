import { useEffect } from 'react';
import type {
  AlertMaintenanceCondition,
  AlertMaintenanceConditionLogic,
  AlertRecord,
  AlertRuleScopeMatchMode,
  AlertRuleScopeType,
  AlertRuleSettings,
} from '../types';

export type AlertSection = 'alerts' | 'alert-history' | 'alert-rules' | 'maintenance';

export interface AlertPageCommonProps {
  language: string;
  currentUsername: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  activeAlertSection: AlertSection;
  onNavigateAlertSection: (section: AlertSection) => void;
}

export interface MaintenanceFormState {
  name: string;
  target_ip: string;
  target_ips: string[];
  selection_mode: 'conditions' | 'resources';
  condition_logic: AlertMaintenanceConditionLogic;
  match_conditions: AlertMaintenanceCondition[];
  starts_at: string;
  ends_at: string;
  reason: string;
  notify_user_ids: string[];
}

export const buildEmptyMaintenanceCondition = (): AlertMaintenanceCondition => ({
  field: 'alert_description',
  operator: 'contains',
  value: '',
});

export const buildDefaultMaintenanceConditions = (selectedItem?: AlertRecord | null): AlertMaintenanceCondition[] => {
  if (!selectedItem) {
    return [buildEmptyMaintenanceCondition()];
  }

  const seeded: AlertMaintenanceCondition[] = [];
  if (selectedItem.title) {
    seeded.push({ field: 'alert_description', operator: 'contains', value: selectedItem.title });
  }
  if (selectedItem.ip_address) {
    seeded.push({ field: 'alert_ip', operator: 'equals', value: selectedItem.ip_address });
  }
  if (selectedItem.severity) {
    seeded.push({ field: 'alert_level', operator: 'equals', value: selectedItem.severity });
  }
  return seeded.length ? seeded : [buildEmptyMaintenanceCondition()];
};

export const ALERT_SEVERITY_OPTIONS = ['critical', 'major', 'warning'] as const;

export const alertHeroClass = 'overflow-hidden rounded-[28px] border border-[#07233d]/10 bg-[linear-gradient(135deg,#f4fbff_0%,#ffffff_58%,#eef6ec_100%)] shadow-[0_18px_40px_rgba(11,35,64,0.08)]';
export const alertPanelClass = 'rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)]';
export const alertPanelHeaderClass = 'border-b border-black/5 px-5 py-5 lg:px-6';
export const alertSubtleCardClass = 'rounded-2xl border border-white/70 bg-white/80 p-4 shadow-sm backdrop-blur';
export const alertPrimaryButtonClass = 'inline-flex h-10 items-center justify-center gap-2 rounded-md bg-[var(--ui-accent)] px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[var(--ui-accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertSecondaryButtonClass = 'inline-flex h-10 items-center justify-center gap-2 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface)] px-4 text-sm font-semibold text-[var(--ui-fg-muted)] transition-colors hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertAccentButtonClass = 'inline-flex h-10 items-center justify-center gap-2 rounded-md border border-[var(--ui-accent)]/25 bg-[var(--ui-accent-subtle)] px-4 text-sm font-semibold text-[var(--ui-accent)] transition-colors hover:bg-[var(--ui-accent)]/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertDangerButtonClass = 'inline-flex h-10 items-center justify-center gap-2 rounded-md border border-[var(--ui-danger)]/25 bg-[var(--ui-danger-subtle)] px-4 text-sm font-semibold text-[var(--ui-danger)] transition-colors hover:bg-[var(--ui-danger)]/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-danger)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertTableActionBarClass = 'inline-flex flex-wrap items-center gap-1 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-1';
export const alertTableActionButtonClass = 'inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-transparent bg-[var(--ui-surface)] px-3 text-xs font-semibold text-[var(--ui-fg-muted)] shadow-sm transition-colors hover:bg-[var(--ui-surface-emphasis)] hover:text-[var(--ui-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertTableActionAccentButtonClass = 'inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-[var(--ui-accent)]/25 bg-[var(--ui-accent-subtle)] px-3 text-xs font-semibold text-[var(--ui-accent)] shadow-sm transition-colors hover:bg-[var(--ui-accent)]/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertTableActionDangerButtonClass = 'inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-[var(--ui-danger)]/25 bg-[var(--ui-danger-subtle)] px-3 text-xs font-semibold text-[var(--ui-danger)] shadow-sm transition-colors hover:bg-[var(--ui-danger)]/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-danger)]/35 disabled:cursor-not-allowed disabled:opacity-45';
export const alertInputClass = 'w-full rounded-2xl border border-black/10 dark:border-white/15 bg-white dark:bg-white/[0.06] px-4 py-3 text-sm text-[#164e63] dark:text-[var(--app-text)] outline-none placeholder:text-black/30 dark:placeholder:text-white/35';
export const alertStatTileClass = 'rounded-2xl border border-white/70 bg-white/80 p-4 shadow-sm backdrop-blur';
export const alertMetricPillClass = 'rounded-full bg-[#00bceb]/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-[#0b6b83]';

export const getAlertSectionTabs = (language: string): Array<{ id: AlertSection; groupLabel: string; label: string; description: string }> => ([
  {
    id: 'alerts',
    groupLabel: language === 'zh' ? '告警中心' : 'Alert Center',
    label: language === 'zh' ? '告警信息' : 'Alert Desk',
    description: language === 'zh' ? '筛选、分派和处置活跃告警' : 'Triage, assign, and document active alerts',
  },
  {
    id: 'alert-rules',
    groupLabel: language === 'zh' ? '告警中心' : 'Alert Center',
    label: language === 'zh' ? '告警规则' : 'Alert Rules',
    description: language === 'zh' ? '管理规则作用范围与通知节奏' : 'Control rule scope and notification cadence',
  },
  {
    id: 'maintenance',
    groupLabel: language === 'zh' ? '告警中心' : 'Alert Center',
    label: language === 'zh' ? '维护期' : 'Maintenance',
    description: language === 'zh' ? '创建静默窗口并复核覆盖范围' : 'Create suppression windows and review coverage',
  },
]);

export const useAlertOverlayDismiss = (open: boolean, onClose: () => void) => {
  useEffect(() => {
    if (!open) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);
};

export const formatTs = (value?: string | null) => {
  if (!value) return '--';
  const normalized = value.includes('T') || value.endsWith('Z') ? value : value.replace(' ', 'T');
  const dt = new Date(normalized);
  if (Number.isNaN(dt.getTime())) return value;

  const year = dt.getFullYear();
  const month = String(dt.getMonth() + 1).padStart(2, '0');
  const day = String(dt.getDate()).padStart(2, '0');
  const hours = String(dt.getHours()).padStart(2, '0');
  const minutes = String(dt.getMinutes()).padStart(2, '0');
  const seconds = String(dt.getSeconds()).padStart(2, '0');

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
};

export const formatDuration = (seconds?: number | null, language = 'en') => {
  if (seconds == null || !Number.isFinite(seconds)) return '--';
  const total = Math.max(0, Math.round(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return language === 'zh' ? `${days}天 ${hours}小时` : `${days}d ${hours}h`;
  if (hours > 0) return language === 'zh' ? `${hours}小时 ${minutes}分钟` : `${hours}h ${minutes}m`;
  return language === 'zh' ? `${minutes}分钟` : `${minutes}m`;
};

export const workflowLabel = (status: string, language: string) => {
  switch (status) {
    case 'acknowledged': return language === 'zh' ? '已确认' : 'Acknowledged';
    case 'investigating': return language === 'zh' ? '处理中' : 'Investigating';
    case 'suppressed': return language === 'zh' ? '维护抑制' : 'Suppressed';
    case 'resolved': return language === 'zh' ? '已关闭/恢复' : 'Closed/Recovered';
    default: return language === 'zh' ? '待处理' : 'Open';
  }
};

export const severityLabel = (severity: string, language: string) => {
  switch (severity) {
    case 'critical': return language === 'zh' ? '严重' : 'Critical';
    case 'major': return language === 'zh' ? '主要' : 'Major';
    case 'warning': return language === 'zh' ? '次要' : 'Minor';
    case 'high': return language === 'zh' ? '高危' : 'High';
    case 'medium': return language === 'zh' ? '中等' : 'Medium';
    case 'info': return language === 'zh' ? '信息' : 'Info';
    default: return language === 'zh' ? '低' : 'Low';
  }
};

export const maintenanceStatusLabel = (status: string, language: string) => {
  switch (status) {
    case 'active': return language === 'zh' ? '生效中' : 'Active';
    case 'scheduled': return language === 'zh' ? '待生效' : 'Scheduled';
    case 'expired': return language === 'zh' ? '已结束' : 'Expired';
    case 'cancelled': return language === 'zh' ? '已取消' : 'Cancelled';
    default: return status;
  }
};

export const maintenanceBadgeClass = (status: string) => {
  switch (status) {
    case 'active': return 'bg-red-100 text-red-700';
    case 'scheduled': return 'bg-blue-100 text-blue-700';
    case 'expired': return 'bg-slate-100 text-slate-700';
    case 'cancelled': return 'bg-zinc-100 text-zinc-600';
    default: return 'bg-slate-100 text-slate-700';
  }
};

export const buildDefaultMaintenanceForm = (selectedItem?: AlertRecord | null): MaintenanceFormState => {
  const now = new Date();
  const start = new Date(now.getTime() + 5 * 60 * 1000);
  const end = new Date(now.getTime() + 65 * 60 * 1000);
  const toLocalInput = (value: Date) => {
    const offset = value.getTimezoneOffset();
    const local = new Date(value.getTime() - offset * 60 * 1000);
    return local.toISOString().slice(0, 16);
  };

  return {
    name: selectedItem ? `${selectedItem.hostname || selectedItem.ip_address || 'Alert'} Maintenance` : '',
    target_ip: selectedItem?.ip_address || '',
    target_ips: selectedItem?.ip_address ? [selectedItem.ip_address] : [],
    selection_mode: selectedItem?.ip_address ? 'resources' : 'conditions',
    condition_logic: 'all',
    match_conditions: buildDefaultMaintenanceConditions(selectedItem),
    starts_at: toLocalInput(start),
    ends_at: toLocalInput(end),
    reason: '',
    notify_user_ids: [],
  };
};

export const buildEmptyRule = (username: string): AlertRuleSettings => ({
  name: '',
  metric_type: 'cpu',
  scope_type: 'global',
  scope_match_mode: 'exact',
  scope_value: '',
  severity: 'major',
  threshold: 90,
  for_duration_seconds: 0,
  enabled: true,
  aggregation_mode: 'dedupe_key',
  notification_repeat_window_seconds: 120,
  notify_on_active: true,
  notify_on_recovery: true,
  notify_on_reopen_after_maintenance: true,
  created_by: username,
  updated_by: username,
});

export const metricTypeLabel = (metricType: AlertRuleSettings['metric_type'], language: string) => {
  switch (metricType) {
    case 'cpu': return language === 'zh' ? 'CPU 利用率' : 'CPU Usage';
    case 'memory': return language === 'zh' ? '内存利用率' : 'Memory Usage';
    case 'interface_util': return language === 'zh' ? '接口利用率' : 'Interface Utilization';
    case 'interface_down': return language === 'zh' ? '接口 DOWN' : 'Interface Down';
    case 'interconnect_down': return language === 'zh' ? '互联口 DOWN' : 'Interconnect Down';
    case 'temperature_high': return language === 'zh' ? '设备温度过高' : 'Temperature High';
    case 'snmp_unreachable': return language === 'zh' ? 'SNMP 不可达' : 'SNMP Unreachable';
    case 'lldp_neighbor_lost': return language === 'zh' ? 'LLDP 邻居丢失' : 'LLDP Neighbor Lost';
    case 'fan_failure': return language === 'zh' ? '风扇故障' : 'Fan Failure';
    case 'power_supply_failure': return language === 'zh' ? '电源故障' : 'Power Supply Failure';
    case 'interface_error_rate_high': return language === 'zh' ? '接口错误率过高' : 'Interface Error Rate High';
    case 'interface_flap': return language === 'zh' ? '接口震荡' : 'Interface Flapping';
    case 'bgp_neighbor_down': return language === 'zh' ? 'BGP 邻居 DOWN' : 'BGP Neighbor Down';
    case 'ospf_neighbor_down': return language === 'zh' ? 'OSPF 邻居异常' : 'OSPF Neighbor Down';
    case 'bfd_session_down': return language === 'zh' ? 'BFD 会话 DOWN' : 'BFD Session Down';
    case 'ping_unreachable': return language === 'zh' ? 'Ping 不可达' : 'Ping Unreachable';
    case 'host_cpu': return language === 'zh' ? '宿主机 CPU' : 'Host CPU';
    case 'host_memory': return language === 'zh' ? '宿主机内存' : 'Host Memory';
    case 'host_disk': return language === 'zh' ? '宿主机磁盘' : 'Host Disk';
    case 'srv_cpu_load': return language === 'zh' ? '服务器负载' : 'Server CPU Load';
    case 'srv_cpu_util': return language === 'zh' ? '服务器 CPU' : 'Server CPU Util';
    case 'srv_iowait': return language === 'zh' ? 'IO 等待' : 'IO Wait';
    case 'srv_mem_avail': return language === 'zh' ? '可用内存' : 'Mem Available';
    case 'srv_swap': return language === 'zh' ? '交换分区' : 'Swap Usage';
    case 'srv_disk_util': return language === 'zh' ? '磁盘利用率' : 'Disk Utilization';
    case 'srv_disk_inode': return language === 'zh' ? 'Inode 利用率' : 'Inode Utilization';
    case 'srv_io_latency': return language === 'zh' ? '磁盘延迟' : 'Disk IO Latency';
    case 'srv_tcp_retrans': return language === 'zh' ? 'TCP 重传' : 'TCP Retransmission';
    case 'srv_tcp_conns': return language === 'zh' ? '并发连接' : 'TCP Connections';
    case 'srv_process_health': return language === 'zh' ? '进程状态' : 'Process Health';
    default: return metricType;
  }
};

export const scopeTypeLabel = (scopeType: AlertRuleScopeType, language: string) => {
  switch (scopeType) {
    case 'site': return language === 'zh' ? '站点' : 'Site';
    case 'device': return language === 'zh' ? '设备' : 'Device';
    case 'interface': return language === 'zh' ? '接口' : 'Interface';
    default: return language === 'zh' ? '全局' : 'Global';
  }
};

export const scopeMatchModeLabel = (matchMode: AlertRuleScopeMatchMode, language: string) => {
  switch (matchMode) {
    case 'contains': return language === 'zh' ? '包含' : 'Contains';
    case 'prefix': return language === 'zh' ? '前缀' : 'Prefix';
    case 'glob': return language === 'zh' ? '通配' : 'Wildcard';
    default: return language === 'zh' ? '精确' : 'Exact';
  }
};
