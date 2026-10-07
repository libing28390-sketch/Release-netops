import { DataTable } from '../components/DataTable';
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, ChevronRight, Copy, Mail, Pencil, Plus, Power, PowerOff, RefreshCw, Save, SlidersHorizontal, Trash2, Webhook, X, Search, Check, Shield } from 'lucide-react';
import TagConditionPicker, { countTagFilterConditions, EMPTY_TAG_FILTER, hasTagFilterConditions, parseTagFilter, serializeTagFilter } from '../components/TagConditionPicker';
import type { AlertRuleHistoryItem, AlertRuleListResponse, AlertRuleNotificationGroup, AlertRuleScopeCatalog, AlertRuleScopeCatalogOption, AlertRuleScopeDevice, AlertRuleSettings } from '../types';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import { useSystem } from '../hooks/useSystem';
import { severityBadgeClass } from '../components/shared';
import {
  ALERT_SEVERITY_OPTIONS,
  alertDangerButtonClass,
  alertInputClass,
  alertPanelClass,
  alertPrimaryButtonClass,
  alertSecondaryButtonClass,
  alertTableActionButtonClass,
  alertTableActionDangerButtonClass,
  AlertPageCommonProps,
  buildEmptyRule,
  alertRuleScopeSummary,
  formatTs,
  metricTypeLabel,
  normalizeAlertRuleNotificationChannels,
  parseAlertCompositeScope,
  parseAlertScopeDeviceIds,
  parseAlertScopeIpValues,
  serializeAlertCompositeScope,
  serializeAlertScopeDeviceIds,
  scopeMatchModeLabel,
  scopeMatchModeDescription,
  scopeTargetDescription,
  scopeTypeLabel,
  severityLabel,
  toggleAlertNotificationChannel,
  useAlertOverlayDismiss,
} from './alertManagementShared';

import { TableActionCell, TableActionHeader } from '../components/ui/TableActionColumn';
import type { TableExportData } from '../components/ui/TableExportMenu';
import { fetchAllPaginatedItems } from '../utils/pagination';
import { buildAlertRulesExportData, getAlertRulesExportHeaders } from './alertRulesExport';
const METRIC_OPTIONS_LIST = [
  { value: 'cpu', labelZh: 'CPU 利用率', labelEn: 'CPU Usage', category: 'network' },
  { value: 'memory', labelZh: '内存利用率', labelEn: 'Memory Usage', category: 'network' },
  { value: 'interface_util', labelZh: '接口利用率', labelEn: 'Interface Utilization', category: 'network' },
  { value: 'interface_down', labelZh: '接口 DOWN', labelEn: 'Interface Down', category: 'network' },
  { value: 'interconnect_down', labelZh: '互联口 DOWN', labelEn: 'Interconnect Down', category: 'network' },
  { value: 'snmp_unreachable', labelZh: 'SNMP 不可达', labelEn: 'SNMP Unreachable', category: 'network' },
  { value: 'lldp_neighbor_lost', labelZh: 'LLDP 邻居丢失', labelEn: 'LLDP Neighbor Lost', category: 'network' },
  { value: 'temperature_high', labelZh: '设备温度过高', labelEn: 'Temperature High', category: 'network' },
  { value: 'fan_failure', labelZh: '风扇故障', labelEn: 'Fan Failure', category: 'network' },
  { value: 'power_supply_failure', labelZh: '电源故障', labelEn: 'Power Supply Failure', category: 'network' },
  { value: 'interface_error_rate_high', labelZh: '接口错误率过高', labelEn: 'Interface Error Rate High', category: 'network' },
  { value: 'interface_flap', labelZh: '接口震荡', labelEn: 'Interface Flapping', category: 'network' },
  { value: 'bgp_neighbor_down', labelZh: 'BGP 邻居 DOWN', labelEn: 'BGP Neighbor Down', category: 'network' },
  { value: 'ospf_neighbor_down', labelZh: 'OSPF 邻居异常', labelEn: 'OSPF Neighbor Down', category: 'network' },
  { value: 'bfd_session_down', labelZh: 'BFD 会话 DOWN', labelEn: 'BFD Session Down', category: 'network' },
  { value: 'ping_unreachable', labelZh: 'Ping 不可达', labelEn: 'Ping Unreachable', category: 'network' },
  { value: 'host_cpu', labelZh: '宿主机 CPU', labelEn: 'Host CPU', category: 'host' },
  { value: 'host_memory', labelZh: '宿主机内存', labelEn: 'Host Memory', category: 'host' },
  { value: 'host_disk', labelZh: '宿主机磁盘', labelEn: 'Host Disk', category: 'host' },
  { value: 'srv_cpu_load', labelZh: '服务器负载', labelEn: 'Server CPU Load', category: 'server' },
  { value: 'srv_cpu_util', labelZh: '服务器 CPU', labelEn: 'Server CPU Util', category: 'server' },
  { value: 'srv_iowait', labelZh: 'IO 等待', labelEn: 'IO Wait', category: 'server' },
  { value: 'srv_mem_avail', labelZh: '可用内存', labelEn: 'Mem Available', category: 'server' },
  { value: 'srv_swap', labelZh: '交换分区', labelEn: 'Swap Usage', category: 'server' },
  { value: 'srv_disk_util', labelZh: '磁盘利用率', labelEn: 'Disk Utilization', category: 'server' },
  { value: 'srv_disk_inode', labelZh: 'Inode 利用率', labelEn: 'Inode Utilization', category: 'server' },
  { value: 'srv_io_latency', labelZh: '磁盘延迟', labelEn: 'Disk IO Latency', category: 'server' },
  { value: 'srv_tcp_retrans', labelZh: 'TCP 重传', labelEn: 'TCP Retransmission', category: 'server' },
  { value: 'srv_tcp_conns', labelZh: '并发连接', labelEn: 'TCP Connections', category: 'server' },
  { value: 'srv_process_health', labelZh: '进程状态', labelEn: 'Process Health', category: 'server' }
] as const;

const NOTIFICATION_CHANNEL_OPTIONS = [
  { value: 'feishu' as const, labelZh: 'Webhook', labelEn: 'Webhook', icon: Webhook, titleZh: '通过已配置的 Webhook 发送告警', titleEn: 'Send alerts through the configured Webhook' },
  { value: 'email' as const, labelZh: '邮件', labelEn: 'Email', icon: Mail, titleZh: '发送到已启用 SMTP 通道配置的收件目标', titleEn: 'Send to recipients configured on enabled SMTP channels' },
] as const;

const notificationChannelLabel = (channel: string, language: string) => {
  const option = NOTIFICATION_CHANNEL_OPTIONS.find((item) => item.value === channel);
  if (option) return language === 'zh' ? option.labelZh : option.labelEn;
  return channel;
};

const isHostMetric = (metricType: string) => metricType.startsWith('host_');
const isServerMetric = (metricType: string) => metricType.startsWith('srv_');

interface ScopeCatalogComboboxProps {
  ariaLabel: string;
  language: string;
  onChange: (value: string) => void;
  options: AlertRuleScopeCatalogOption[];
  placeholder: string;
  value: string;
  wrapperClassName?: string;
}

const ScopeCatalogCombobox: React.FC<ScopeCatalogComboboxProps> = ({
  ariaLabel,
  language,
  onChange,
  options,
  placeholder,
  value,
  wrapperClassName = 'mt-1.5',
}) => {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const isZh = language === 'zh';

  const matchingOptions = useMemo(() => {
    const query = value.trim().toLocaleLowerCase();
    const matching = query
      ? options.filter((option) => option.value.toLocaleLowerCase().includes(query))
      : options;
    return { items: matching.slice(0, 8), total: matching.length };
  }, [options, value]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    };
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer);
  }, [open]);

  useEffect(() => {
    if (activeIndex >= 0) optionRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const selectOption = (option: AlertRuleScopeCatalogOption) => {
    onChange(option.value);
    setOpen(false);
    setActiveIndex(-1);
    inputRef.current?.focus();
  };

  return (
    <div ref={rootRef} className={`relative ${wrapperClassName}`}>
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open && activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined}
        value={value}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setActiveIndex(-1);
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((current) => Math.min(current + 1, matchingOptions.items.length - 1));
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((current) => current < 0 ? matchingOptions.items.length - 1 : Math.max(0, current - 1));
          } else if (event.key === 'Enter' && open && activeIndex >= 0 && matchingOptions.items[activeIndex]) {
            event.preventDefault();
            selectOption(matchingOptions.items[activeIndex]);
          } else if (event.key === 'Escape' && open) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
            setActiveIndex(-1);
          }
        }}
        className={`${alertInputClass} rounded-xl py-2.5 pl-3.5 pr-10 text-sm transition focus:border-cyan-500/60 focus:ring-4 focus:ring-cyan-500/10`}
        placeholder={placeholder}
      />
      <ChevronDown
        size={15}
        aria-hidden="true"
        className={`pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
      />

      {open && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          className="absolute left-0 right-0 top-full z-[70] mt-1.5 overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_16px_40px_rgba(15,23,42,0.16)] dark:border-white/10 dark:bg-slate-900"
        >
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-3.5 py-2.5 dark:border-white/10">
            <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-300">
              {isZh ? 'CMDB 候选' : 'CMDB options'}
            </span>
            <span className="text-[10px] text-slate-400">
              {matchingOptions.total > 8
                ? (isZh ? `显示 8 / ${matchingOptions.total} 项` : `Showing 8 of ${matchingOptions.total}`)
                : (isZh ? `${matchingOptions.total} 项` : `${matchingOptions.total} options`)}
            </span>
          </div>

          {matchingOptions.items.length > 0 ? (
            <div className="max-h-56 overflow-y-auto p-1.5">
              {matchingOptions.items.map((option, index) => {
                const selected = option.value.trim().toLocaleLowerCase() === value.trim().toLocaleLowerCase();
                const active = activeIndex === index;
                return (
                  <button
                    key={option.value}
                    ref={(element) => { optionRefs.current[index] = element; }}
                    id={`${listboxId}-option-${index}`}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    tabIndex={-1}
                    onMouseEnter={() => setActiveIndex(index)}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectOption(option)}
                    className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                      active || selected
                        ? 'bg-cyan-50 text-cyan-900 dark:bg-cyan-500/10 dark:text-cyan-100'
                        : 'text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-white/[0.06]'
                    }`}
                  >
                    <span className="min-w-0 truncate text-sm font-medium">{option.value}</span>
                    <span className="inline-flex shrink-0 items-center gap-1.5">
                      <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium tabular-nums text-slate-500 dark:bg-white/10 dark:text-slate-300">
                        {isZh ? `${option.count} 台` : `${option.count} devices`}
                      </span>
                      {selected && <Check size={14} aria-hidden="true" className="text-cyan-700 dark:text-cyan-300" />}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="px-4 py-5 text-center">
              <p className="text-xs font-medium text-slate-600 dark:text-slate-200">
                {isZh ? '没有匹配的目录选项' : 'No matching catalog options'}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">
                {isZh ? '仍可直接使用输入值作为筛选条件。' : 'You can still use this text as a filter.'}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const AlertRulesTab: React.FC<AlertPageCommonProps> = ({ language, currentUsername, showToast }) => {
  const getHeaders = (json = false) => {
    const token = localStorage.getItem('netops_token');
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    if (json) {
      headers['Content-Type'] = 'application/json';
    }
    return headers;
  };

  const thresholdMetrics = new Set<AlertRuleSettings['metric_type']>([
    'cpu', 'memory', 'interface_util', 'temperature_high', 'interface_error_rate_high',
    'host_cpu', 'host_memory', 'host_disk',
    'srv_cpu_load', 'srv_cpu_util', 'srv_iowait', 'srv_mem_avail', 'srv_swap',
    'srv_disk_util', 'srv_disk_inode', 'srv_io_latency', 'srv_tcp_retrans', 'srv_tcp_conns'
  ]);

  const [copiedId, setCopiedId] = useState<string | null>(null);

  const copyToClipboard = (text: string, id: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
      } else {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        textArea.style.top = '0';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
      showToast(language === 'zh' ? '已成功复制到剪贴板' : 'Copied to clipboard successfully', 'success');
    } catch (err) {
      console.error('Failed to copy: ', err);
      showToast(language === 'zh' ? '复制失败' : 'Failed to copy', 'error');
    }
  };

  const defaultSeverityForMetric = (metricType: AlertRuleSettings['metric_type']): AlertRuleSettings['severity'] => {
    switch (metricType) {
      case 'interface_down':
        return 'warning';
      case 'interconnect_down':
      case 'snmp_unreachable':
      case 'lldp_neighbor_lost':
      case 'temperature_high':
      case 'interface_error_rate_high':
      case 'interface_flap':
      case 'host_cpu':
      case 'host_memory':
      case 'host_disk':
      case 'srv_cpu_load':
      case 'srv_cpu_util':
      case 'srv_iowait':
      case 'srv_mem_avail':
      case 'srv_swap':
      case 'srv_disk_util':
      case 'srv_disk_inode':
      case 'srv_io_latency':
      case 'srv_tcp_retrans':
      case 'srv_tcp_conns':
        return 'major';
      case 'fan_failure':
      case 'power_supply_failure':
      case 'bgp_neighbor_down':
      case 'ospf_neighbor_down':
      case 'bfd_session_down':
      case 'ping_unreachable':
      case 'srv_process_health':
        return 'critical';
      default:
        return 'major';
    }
  };

  const defaultThresholdForMetric = (metricType: AlertRuleSettings['metric_type']) => {
    switch (metricType) {
      case 'temperature_high':
      case 'host_cpu':
      case 'srv_cpu_util':
      case 'srv_cpu_load':
        return 75;
      case 'interface_error_rate_high':
      case 'srv_tcp_retrans':
        return 2;
      case 'host_memory':
      case 'host_disk':
      case 'srv_mem_avail':
      case 'srv_disk_util':
      case 'srv_disk_inode':
      case 'srv_io_latency':
        return 80;
      case 'srv_swap':
        return 50;
      default:
        return 90;
    }
  };

  const [alertRules, setAlertRules] = useState<AlertRuleSettings[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState('');
  const [enabledFilter, setEnabledFilter] = useState('all');
  const [metricFilter, setMetricFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'network' | 'host' | 'server'>('all');
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({ all: 0, network: 0, host: 0, server: 0 });
  const [supportedMetricTypes, setSupportedMetricTypes] = useState<Set<string> | null>(null);
  const [scopeCatalog, setScopeCatalog] = useState<AlertRuleScopeCatalog | null>(null);
  const [scopeCatalogLoading, setScopeCatalogLoading] = useState(false);
  const [scopeCatalogError, setScopeCatalogError] = useState<'forbidden' | 'error' | null>(null);
  const [scopeDeviceSearchQuery, setScopeDeviceSearchQuery] = useState('');
  const [scopeDeviceCandidates, setScopeDeviceCandidates] = useState<AlertRuleScopeDevice[]>([]);
  const [selectedScopeDevices, setSelectedScopeDevices] = useState<AlertRuleScopeDevice[]>([]);
  const [scopeDevicePickerOpen, setScopeDevicePickerOpen] = useState(false);
  const [pendingScopeDeviceIds, setPendingScopeDeviceIds] = useState<string[]>([]);
  const [scopeDeviceSearchStatus, setScopeDeviceSearchStatus] = useState<'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'forbidden'>('idle');
  const [scopeDeviceSearchTotal, setScopeDeviceSearchTotal] = useState(0);
  const [missingScopeDeviceIds, setMissingScopeDeviceIds] = useState<string[]>([]);
  const scopeDeviceSearchAbortRef = useRef<AbortController | null>(null);
  const [notificationGroups, setNotificationGroups] = useState<AlertRuleNotificationGroup[]>([]);
  const [notificationGroupsLoading, setNotificationGroupsLoading] = useState(false);
  const [notificationGroupsError, setNotificationGroupsError] = useState<'forbidden' | 'error' | null>(null);
  const [rulesLoadError, setRulesLoadError] = useState<'forbidden' | 'error' | null>(null);
  const [ruleDraft, setRuleDraft] = useState<AlertRuleSettings | null>(null);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());
  const [ruleHistory, setRuleHistory] = useState<AlertRuleHistoryItem[]>([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  // Approval verification states
  const [approvers, setApprovers] = useState<{ id: string; username: string; role: string }[]>([]);
  const [approverUsername, setApproverUsername] = useState('');
  const [configReason, setConfigReason] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [approvalCountdown, setApprovalCountdown] = useState(0);
  const [approvalError, setApprovalError] = useState('');
  const { systemInfo } = useSystem();
  const isProduction = systemInfo?.environment?.toLowerCase() === 'production';
  const [skipApproval, setSkipApproval] = useState(true);

  useEffect(() => {
    if (systemInfo?.environment) {
      setSkipApproval(systemInfo.environment.toLowerCase() !== 'production');
    }
  }, [systemInfo]);

  // Deletion approval states
  const [deleteApprovalOpen, setDeleteApprovalOpen] = useState(false);
  const [deleteTargetIds, setDeleteTargetIds] = useState<string[]>([]);
  const [deleteTargetNames, setDeleteTargetNames] = useState('');
  const [deleteReason, setDeleteReason] = useState('');
  const [deleteApprover, setDeleteApprover] = useState('');
  const [deleteStatus, setDeleteStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [deleteCountdown, setDeleteCountdown] = useState(0);
  const [deleteCode, setDeleteCode] = useState('');
  const [deleteToken, setDeleteToken] = useState('');
  const [deleteError, setDeleteError] = useState('');

  useEffect(() => () => scopeDeviceSearchAbortRef.current?.abort(), []);

  // Countdown timers
  useEffect(() => {
    if (approvalCountdown <= 0) return;
    const t = setTimeout(() => setApprovalCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [approvalCountdown]);

  useEffect(() => {
    if (deleteCountdown <= 0) return;
    const t = setTimeout(() => setDeleteCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [deleteCountdown]);

  // Request approval for rule creation / updates
  const requestApproval = async () => {
    if (!approverUsername) return;
    setApprovalStatus('sending');
    setApprovalError('');
    try {
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: getHeaders(true),
        body: JSON.stringify({
          approver_username: approverUsername,
          config_reason: configReason || (language === 'zh' ? `修改告警规则: ${ruleDraft?.name}` : `Update alert rule: ${ruleDraft?.name}`),
          device_hostname: ruleDraft?.scope_value || (language === 'zh' ? '全局范围' : 'Global'),
          command_preview: '',
          approval_type: 'alert_rule',
          extra_fields: {
            action_type: language === 'zh' ? '告警规则变更' : 'Alert Rule Change',
            schedule_desc: language === 'zh' 
              ? `${ruleDraft?.metric_type} (${ruleDraft?.severity}) 阈值: ${ruleDraft?.threshold ?? '状态型'}` 
              : `${ruleDraft?.metric_type} (${ruleDraft?.severity}) threshold: ${ruleDraft?.threshold ?? 'state'}`,
            operation: editingRuleId ? 'UPDATE' : 'CREATE',
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalToken(j.approval_token);
        setApprovalStatus('sent');
        setApprovalCountdown(300);
        showToast(language === 'zh' ? '验证码已发送至审批人' : 'Code sent to approver', 'success');
      } else {
        setApprovalStatus('idle');
        setApprovalError(j.detail || j.message || 'Failed');
      }
    } catch {
      setApprovalStatus('idle');
      setApprovalError(language === 'zh' ? '发送验证码失败' : 'Failed to send code');
    }
  };

  // Verify approval code for rule creation / updates
  const verifyApproval = async () => {
    if (!approvalToken || !approvalCode) return;
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: getHeaders(true),
        body: JSON.stringify({ approval_token: approvalToken, code: approvalCode }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalStatus('verified');
        showToast(language === 'zh' ? '审批验证通过' : 'Approval verified', 'success');
      } else {
        setApprovalError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setApprovalError(language === 'zh' ? '验证失败' : 'Verification failed');
    }
  };

  // Request deletion approval
  const requestDeleteApproval = async () => {
    if (!deleteApprover || !deleteTargetIds.length) return;
    setDeleteStatus('sending');
    setDeleteError('');
    try {
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: getHeaders(true),
        body: JSON.stringify({
          approver_username: deleteApprover,
          config_reason: deleteReason || (language === 'zh' ? `删除告警规则: ${deleteTargetNames}` : `Delete alert rules: ${deleteTargetNames}`),
          device_hostname: '',
          command_preview: '',
          approval_type: 'alert_rule_delete',
          extra_fields: {
            action_type: language === 'zh' ? '告警规则删除' : 'Alert Rule Deletion',
            operation: 'DELETE',
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteToken(j.approval_token);
        setDeleteStatus('sent');
        setDeleteCountdown(300);
        showToast(language === 'zh' ? '删除验证码已发至审批人' : 'Delete code sent to approver', 'success');
      } else {
        setDeleteStatus('idle');
        setDeleteError(j.detail || j.message || 'Failed');
      }
    } catch {
      setDeleteStatus('idle');
      setDeleteError(language === 'zh' ? '发送验证码失败' : 'Failed to send code');
    }
  };

  // Verify deletion approval code
  const verifyDeleteApproval = async () => {
    if (!deleteToken || !deleteCode) return;
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: getHeaders(true),
        body: JSON.stringify({ approval_token: deleteToken, code: deleteCode }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteStatus('verified');
        showToast(language === 'zh' ? '删除审批验证通过' : 'Delete approval verified', 'success');
      } else {
        setDeleteError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setDeleteError(language === 'zh' ? '验证失败' : 'Verification failed');
    }
  };

  // Confirm and execute rule deletion(s)
  const executeDelete = async () => {
    if (!deleteTargetIds.length) return;
    if (deleteStatus !== 'verified' && !skipApproval) {
      showToast(language === 'zh' ? '请先完成删除验证' : 'Please complete deletion verification', 'error');
      return;
    }
    
    setSaving(true);
    try {
      const isBatch = deleteTargetIds.length > 1;
      let resp;
      if (isBatch) {
        resp = await fetch('/api/alerts/rules/batch-delete', {
          method: 'POST',
          headers: getHeaders(true),
          body: JSON.stringify({
            rule_ids: deleteTargetIds,
            actor_username: currentUsername,
            approval_token: skipApproval ? '' : deleteToken,
            approval_code: skipApproval ? '' : deleteCode,
            skip_approval_verification: skipApproval,
          }),
        });
      } else {
        const id = deleteTargetIds[0];
        const params = new URLSearchParams({
          actor_username: currentUsername,
          approval_token: skipApproval ? '' : deleteToken,
          approval_code: skipApproval ? '' : deleteCode,
          skip_approval: String(skipApproval),
        });
        resp = await fetch(`/api/alerts/rules/${id}?${params.toString()}`, {
          method: 'DELETE',
          headers: getHeaders(false),
        });
      }
      
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to delete');
      
      showToast(language === 'zh' ? '告警规则已成功删除' : 'Alert rule(s) deleted successfully', 'success');
      setDeleteApprovalOpen(false);
      closeEditor();
      setSelectedIds(new Set());
      await loadAlertRules();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '删除告警规则失败' : 'Failed to delete alert rule(s)'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const loadNotificationGroups = async () => {
    setNotificationGroupsLoading(true);
    setNotificationGroupsError(null);
    try {
      const resp = await fetch('/api/alerts/rules/notification-groups', { headers: getHeaders(false) });
      if (resp.status === 403) {
        setNotificationGroupsError('forbidden');
        setNotificationGroups([]);
        return;
      }
      if (!resp.ok) throw new Error('Failed to load notification groups');
      const data: { items?: AlertRuleNotificationGroup[] } = await resp.json();
      setNotificationGroups(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      console.error(error);
      setNotificationGroupsError('error');
    } finally {
      setNotificationGroupsLoading(false);
    }
  };

  const loadScopeCatalog = async () => {
    setScopeCatalogLoading(true);
    setScopeCatalogError(null);
    try {
      const resp = await fetch('/api/alerts/rules/scope-catalog', { headers: getHeaders(false) });
      if (resp.status === 403) {
        setScopeCatalogError('forbidden');
        setScopeCatalog(null);
        return;
      }
      if (!resp.ok) throw new Error('Failed to load alert rule scope catalog');
      const data = await resp.json();
      setScopeCatalog({
        sites: Array.isArray(data.sites) ? data.sites : [],
        roles: Array.isArray(data.roles) ? data.roles : [],
        categories: Array.isArray(data.categories) ? data.categories : [],
        platforms: Array.isArray(data.platforms) ? data.platforms : [],
      });
    } catch (error) {
      console.error(error);
      setScopeCatalogError('error');
    } finally {
      setScopeCatalogLoading(false);
    }
  };

  const loadAlertRules = async () => {
    setLoading(true);
    setRulesLoadError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        search,
        enabled: enabledFilter,
        category: categoryFilter,
      });
      if (metricFilter !== 'all') {
        params.set('metric_type', metricFilter);
      }
      const resp = await fetch(`/api/alerts/rules?${params.toString()}`, {
        headers: getHeaders(false),
      });
      if (resp.status === 403) {
        setRulesLoadError('forbidden');
        throw new Error('Forbidden');
      }
      if (!resp.ok) throw new Error('Failed to load alert rules');
      const data: AlertRuleListResponse & { category_counts?: Record<string, number> } = await resp.json();
      const items = data.items || [];
      setAlertRules(items);
      setTotal(data.total && data.total > 0 ? data.total : items.length);
      if (data.category_counts) {
        setCategoryCounts(data.category_counts);
      }
      if (Array.isArray(data.supported_metric_types)) {
        setSupportedMetricTypes(new Set(data.supported_metric_types));
      }
      setSelectedIds(new Set());
      if (editingRuleId && !items.some((item) => item.id === editingRuleId)) {
        setEditingRuleId(null);
        setRuleDraft(null);
      }
    } catch (error) {
      console.error(error);
      setRulesLoadError((current) => current || 'error');
      showToast(language === 'zh' ? '加载告警规则失败' : 'Failed to load alert rules', 'error');
    } finally {
      setLoading(false);
    }
  };

  const alertRuleHeaders = getAlertRulesExportHeaders(language);

  const exportAllAlertRules = async (): Promise<TableExportData> => {
    const params = new URLSearchParams({
      search,
      enabled: enabledFilter,
      category: categoryFilter,
    });
    if (metricFilter !== 'all') params.set('metric_type', metricFilter);
    const items = await fetchAllPaginatedItems<AlertRuleSettings>('/api/alerts/rules', params, 100);
    return buildAlertRulesExportData(items, language, (channel) => notificationChannelLabel(channel, language));
  };

  useEffect(() => {
    void loadAlertRules();
  }, [page, pageSize, search, enabledFilter, metricFilter, categoryFilter]);

  useEffect(() => {
    void loadNotificationGroups();
  }, []);

  useEffect(() => {
    void loadScopeCatalog();
  }, []);

  // Fetch approvers once on component load
  useEffect(() => {
    const fetchApprovers = async () => {
      try {
        const resp = await fetch('/api/users', {
          headers: getHeaders(false),
        });
        if (resp.ok) {
          const j = await resp.json();
          const users = j.data?.items || j.data || j;
          if (Array.isArray(users)) {
            setApprovers(users.filter((u: any) => u.role === 'Administrator' || u.role === 'Operator'));
          }
        }
      } catch (e) {
        console.error(e);
      }
    };
    void fetchApprovers();
  }, []);

  // Reset page and metric selection when category changes
  useEffect(() => {
    setPage(1);
    setMetricFilter('all');
  }, [categoryFilter]);

  const resetScopeDeviceLookup = () => {
    scopeDeviceSearchAbortRef.current?.abort();
    scopeDeviceSearchAbortRef.current = null;
    setScopeDeviceSearchQuery('');
    setScopeDeviceCandidates([]);
    setSelectedScopeDevices([]);
    setScopeDevicePickerOpen(false);
    setPendingScopeDeviceIds([]);
    setScopeDeviceSearchStatus('idle');
    setScopeDeviceSearchTotal(0);
    setMissingScopeDeviceIds([]);
  };

  const searchScopeDevices = async (rawQuery = scopeDeviceSearchQuery) => {
    const query = rawQuery.trim();
    if (!query) {
      setScopeDeviceCandidates([]);
      setScopeDeviceSearchTotal(0);
      setScopeDeviceSearchStatus('idle');
      setScopeDevicePickerOpen(false);
      return;
    }
    scopeDeviceSearchAbortRef.current?.abort();
    const controller = new AbortController();
    scopeDeviceSearchAbortRef.current = controller;
    setScopeDeviceSearchStatus('loading');
    setScopeDeviceCandidates([]);
    setScopeDeviceSearchTotal(0);
    try {
      const params = new URLSearchParams({ search: query });
      const resp = await fetch(`/api/alerts/rules/scope-catalog?${params.toString()}`, {
        headers: getHeaders(false),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (resp.status === 403) {
        setScopeDeviceSearchStatus('forbidden');
        return;
      }
      if (!resp.ok) throw new Error('CMDB device search failed');
      const data: AlertRuleScopeCatalog = await resp.json();
      const devices = Array.isArray(data.devices) ? data.devices : [];
      setScopeDeviceCandidates(devices);
      setScopeDeviceSearchTotal(Number(data.device_total || devices.length));
      setScopeDeviceSearchStatus(devices.length ? 'ready' : 'empty');
      if (devices.length) {
        setPendingScopeDeviceIds(parseAlertScopeDeviceIds(ruleDraft?.scope_value || '[]'));
        setScopeDevicePickerOpen(true);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      console.error(error);
      setScopeDeviceSearchStatus('error');
    }
  };

  const loadScopeDeviceSelection = async (deviceIds: string[]) => {
    if (!deviceIds.length) {
      setSelectedScopeDevices([]);
      setMissingScopeDeviceIds([]);
      return;
    }
    scopeDeviceSearchAbortRef.current?.abort();
    const controller = new AbortController();
    scopeDeviceSearchAbortRef.current = controller;
    setScopeDeviceSearchStatus('loading');
    try {
      const params = new URLSearchParams({ device_ids: deviceIds.join(',') });
      const resp = await fetch(`/api/alerts/rules/scope-catalog?${params.toString()}`, {
        headers: getHeaders(false),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!resp.ok) throw new Error(resp.status === 403 ? 'forbidden' : 'CMDB selection could not be loaded');
      const data: AlertRuleScopeCatalog = await resp.json();
      const devices = Array.isArray(data.devices) ? data.devices : [];
      const foundIds = new Set(devices.map((device) => device.id));
      setSelectedScopeDevices(devices);
      setMissingScopeDeviceIds(Array.isArray(data.missing_device_ids)
        ? data.missing_device_ids
        : deviceIds.filter((id) => !foundIds.has(id)));
      setScopeDeviceSearchStatus('idle');
    } catch (error) {
      if (controller.signal.aborted) return;
      console.error(error);
      setSelectedScopeDevices([]);
      setMissingScopeDeviceIds(deviceIds);
      setScopeDeviceSearchStatus(error instanceof Error && error.message === 'forbidden' ? 'forbidden' : 'error');
    }
  };

  const openScopeDevicePicker = () => {
    setPendingScopeDeviceIds(parseAlertScopeDeviceIds(ruleDraft?.scope_value || '[]'));
    setScopeDevicePickerOpen(true);
  };

  const closeScopeDevicePicker = () => {
    setScopeDevicePickerOpen(false);
    setPendingScopeDeviceIds([]);
  };

  const togglePendingScopeDevice = (device: AlertRuleScopeDevice) => {
    const isSelected = pendingScopeDeviceIds.includes(device.id);
    if (!isSelected && pendingScopeDeviceIds.length >= 200) {
      showToast(language === 'zh' ? '单条规则最多选择 200 台执行机器' : 'A rule can target at most 200 execution machines', 'error');
      return;
    }
    setPendingScopeDeviceIds((current) => isSelected
      ? current.filter((id) => id !== device.id)
      : current.includes(device.id) ? current : [...current, device.id]);
  };

  const toggleAllScopeDeviceCandidates = () => {
    const candidateIds = scopeDeviceCandidates.map((device) => device.id);
    const allSelected = candidateIds.length > 0 && candidateIds.every((id) => pendingScopeDeviceIds.includes(id));
    if (allSelected) {
      setPendingScopeDeviceIds((current) => current.filter((id) => !candidateIds.includes(id)));
      return;
    }
    const nextIds = Array.from(new Set([...pendingScopeDeviceIds, ...candidateIds]));
    if (nextIds.length > 200) {
      showToast(language === 'zh' ? '单条规则最多选择 200 台执行机器' : 'A rule can target at most 200 execution machines', 'error');
      return;
    }
    setPendingScopeDeviceIds(nextIds);
  };

  const confirmScopeDeviceSelection = () => {
    const nextIds = Array.from(new Set(pendingScopeDeviceIds));
    if (scopeDeviceSearchQuery.trim() && scopeDeviceSearchTotal > scopeDeviceCandidates.length) {
      showToast(language === 'zh' ? '匹配设备超过当前显示数量，请缩小搜索范围后再确认' : 'More devices matched than are shown. Refine the search before confirming.', 'error');
      return;
    }
    if (nextIds.length > 200) {
      showToast(language === 'zh' ? '单条规则最多选择 200 台执行机器' : 'A rule can target at most 200 execution machines', 'error');
      return;
    }
    const knownDevices = new Map([...selectedScopeDevices, ...scopeDeviceCandidates].map((device) => [device.id, device]));
    const nextDevices = nextIds.flatMap((id) => {
      const device = knownDevices.get(id);
      return device ? [device] : [];
    });
    const nextMissingIds = nextIds.filter((id) => !knownDevices.has(id));
    setSelectedScopeDevices(nextDevices);
    setMissingScopeDeviceIds(nextMissingIds);
    setRuleDraft((current) => current ? {
      ...current,
      scope_value: serializeAlertScopeDeviceIds(nextIds),
    } : current);
    setScopeDevicePickerOpen(false);
    setPendingScopeDeviceIds([]);
  };

  const removeMissingScopeDevices = () => {
    setRuleDraft((current) => current ? {
      ...current,
      scope_value: serializeAlertScopeDeviceIds(selectedScopeDevices.map((device) => device.id)),
    } : current);
    setMissingScopeDeviceIds([]);
  };

  const openCreate = () => {
    resetScopeDeviceLookup();
    setEditingRuleId(null);
    setRuleDraft(buildEmptyRule(currentUsername));
  };

  const openEdit = (rule: AlertRuleSettings) => {
    resetScopeDeviceLookup();
    setEditingRuleId(rule.id || null);
    setRuleDraft({
      ...rule,
      notification_channels: normalizeAlertRuleNotificationChannels(rule.notification_channels, isHostMetric(rule.metric_type)),
      notification_group_names: rule.notification_group_names || [],
    });
    if (rule.scope_type === 'devices') {
      void loadScopeDeviceSelection(parseAlertScopeDeviceIds(rule.scope_value || '[]'));
    }
    setHistoryExpanded(false);
    setRuleHistory([]);
  };

  const closeEditor = () => {
    resetScopeDeviceLookup();
    setEditingRuleId(null);
    setRuleDraft(null);
    setRuleHistory([]);
    setHistoryExpanded(false);

    // Reset approval state
    setApproverUsername('');
    setApprovalCode('');
    setApprovalToken('');
    setApprovalStatus('idle');
    setApprovalCountdown(0);
    setApprovalError('');
    setConfigReason('');
  };

  /* ---------- History: change log for an existing rule ---------- */
  const fetchHistory = useCallback(async (ruleId: string) => {
    try {
      const resp = await fetch(`/api/alerts/rules/history?rule_id=${encodeURIComponent(ruleId)}`, {
        headers: getHeaders(false),
      });
      if (resp.ok) {
        const data = await resp.json();
        setRuleHistory(Array.isArray(data) ? data : data.items || []);
      }
    } catch { /* silent */ }
  }, []);

  /* Fetch rule history when an existing rule opens. */
  useEffect(() => {
    if (editingRuleId) {
      void fetchHistory(editingRuleId);
    }
  }, [editingRuleId]);

  useAlertOverlayDismiss(Boolean(ruleDraft), closeEditor);
  useAlertOverlayDismiss(scopeDevicePickerOpen, closeScopeDevicePicker);
  useAlertOverlayDismiss(deleteApprovalOpen, () => setDeleteApprovalOpen(false));

  const originalRule = useMemo(
    () => {
      const item = alertRules.find((candidate) => candidate.id === editingRuleId);
      return item ? { ...item, notification_group_names: item.notification_group_names || [] } : null;
    },
    [alertRules, editingRuleId],
  );

  const isDirty = useMemo(() => {
    if (!ruleDraft) return false;
    if (!editingRuleId) {
      return JSON.stringify(ruleDraft) !== JSON.stringify(buildEmptyRule(currentUsername));
    }
    return JSON.stringify(ruleDraft) !== JSON.stringify(originalRule);
  }, [currentUsername, editingRuleId, originalRule, ruleDraft]);

  const updateRuleField = <K extends keyof AlertRuleSettings>(key: K, value: AlertRuleSettings[K]) => {
    if (key === 'scope_type' || (key === 'metric_type' && isHostMetric(String(value)))) {
      resetScopeDeviceLookup();
    }
    setRuleDraft((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [key]: value } as AlertRuleSettings;
      if (key === 'metric_type') {
        const metricValue = value as AlertRuleSettings['metric_type'];
        next.threshold = thresholdMetrics.has(metricValue) ? defaultThresholdForMetric(metricValue) : null;
        next.severity = defaultSeverityForMetric(metricValue);
        if (isHostMetric(metricValue)) {
          next.scope_type = 'global';
          next.scope_value = '';
          next.scope_match_mode = 'exact';
          next.notification_channels = ['workspace'];
          next.notification_group_names = [];
        } else {
          next.notification_channels = (next.notification_channels || []).filter((channel) => channel !== 'workspace');
        }
      }
      if (key === 'scope_type') {
        next.scope_value = '';
        next.scope_match_mode = 'exact';
      }
      return next;
    });
  };

  const updateCompositeFilter = (field: 'site' | 'role' | 'category' | 'platform' | 'interface', value: string) => {
    setRuleDraft((prev) => {
      if (!prev) return prev;
      const filters = parseAlertCompositeScope(prev.scope_value);
      return {
        ...prev,
        scope_value: serializeAlertCompositeScope({ ...filters, [field]: value }),
      };
    });
  };

  const toggleNotificationChannel = (channel: AlertRuleSettings['notification_channels'][number]) => {
    setRuleDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, notification_channels: toggleAlertNotificationChannel(prev.notification_channels, channel) };
    });
  };

  const toggleNotificationGroup = (groupName: string) => {
    setRuleDraft((prev) => {
      if (!prev) return prev;
      const selected = new Set(prev.notification_group_names || []);
      if (selected.has(groupName)) selected.delete(groupName); else selected.add(groupName);
      return { ...prev, notification_group_names: Array.from(selected) };
    });
  };

  const handleSave = async () => {
    if (!ruleDraft) return;
    const draftIsHostMetric = isHostMetric(ruleDraft.metric_type);
    const selectedChannels = (ruleDraft.notification_channels || []).filter((channel) => channel === 'feishu' || channel === 'email');
    if (!draftIsHostMetric && selectedChannels.length === 0) {
      showToast(language === 'zh' ? '请至少选择一种通知方式：Webhook 或邮件' : 'Select at least one notification method: Webhook or email', 'error');
      return;
    }
    if (!draftIsHostMetric) {
      const hasScopeValue = ruleDraft.scope_type === 'global'
        || (ruleDraft.scope_type === 'composite'
          ? Object.values(parseAlertCompositeScope(ruleDraft.scope_value)).some((value) => String(value || '').trim())
          : ruleDraft.scope_type === 'tag'
            ? hasTagFilterConditions(parseTagFilter(ruleDraft.scope_value))
            : ruleDraft.scope_type === 'devices'
              ? parseAlertScopeDeviceIds(ruleDraft.scope_value).length > 0
                && missingScopeDeviceIds.length === 0
                && selectedScopeDevices.length === parseAlertScopeDeviceIds(ruleDraft.scope_value).length
            : ruleDraft.scope_type === 'ip'
              ? parseAlertScopeIpValues(ruleDraft.scope_value).length > 0
              : Boolean(ruleDraft.scope_value.trim()));
      if (ruleDraft.scope_type === 'devices' && scopeDeviceSearchStatus === 'loading') {
        showToast(language === 'zh' ? '请等待 CMDB 设备确认完成' : 'Wait for the CMDB device lookup to finish', 'error');
        return;
      }
      if (!hasScopeValue) {
        showToast(language === 'zh' ? '请从 CMDB 搜索并确认至少一台执行机器' : 'Search CMDB and confirm at least one execution machine', 'error');
        return;
      }
    }
    if (!skipApproval && approvalStatus !== 'verified') {
      showToast(language === 'zh' ? '请先完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    setSaving(true);
    try {
      const isCreate = !editingRuleId;
      const { tenant_id: _tenantId, ...rulePayload } = ruleDraft as AlertRuleSettings & { tenant_id?: string };
      const resp = await fetch(isCreate ? '/api/alerts/rules' : `/api/alerts/rules/${editingRuleId}`, {
        method: isCreate ? 'POST' : 'PUT',
        headers: getHeaders(true),
        body: JSON.stringify({
          ...rulePayload,
          notification_channels: draftIsHostMetric ? ['workspace'] : selectedChannels,
          notification_group_names: draftIsHostMetric ? [] : (ruleDraft.notification_group_names || []),
          scope_type: draftIsHostMetric ? 'global' : ruleDraft.scope_type,
          scope_match_mode: draftIsHostMetric ? 'exact' : ruleDraft.scope_match_mode,
          scope_value: draftIsHostMetric ? '' : ruleDraft.scope_value,
          created_by: ruleDraft.created_by || currentUsername,
          updated_by: currentUsername,
          approval_token: skipApproval ? '' : approvalToken,
          approval_code: skipApproval ? '' : approvalCode,
          skip_approval_verification: skipApproval,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to save alert rule');
      showToast(language === 'zh' ? '告警规则已保存' : 'Alert rule saved', 'success');
      closeEditor();
      setPage(1);
      await loadAlertRules();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '保存告警规则失败' : 'Failed to save alert rule'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = () => {
    if (!ruleDraft || !editingRuleId) return;
    setDeleteTargetIds([editingRuleId]);
    setDeleteTargetNames(ruleDraft.name);
    setDeleteReason('');
    setDeleteApprover('');
    setDeleteStatus('idle');
    setDeleteCountdown(0);
    setDeleteCode('');
    setDeleteToken('');
    setDeleteError('');
    setDeleteApprovalOpen(true);
  };

  const handleReset = () => {
    if (!ruleDraft) return;
    if (!editingRuleId) {
      setRuleDraft(buildEmptyRule(currentUsername));
      return;
    }
    if (originalRule) {
      setRuleDraft({ ...originalRule });
    }
  };

  const handleToggleEnabled = async (rule: AlertRuleSettings) => {
    const ruleId = rule.id;
    if (!ruleId) return;
    if ((rule.rule_supported === false || isServerMetric(rule.metric_type)) && !rule.enabled) {
      showToast(language === 'zh' ? '该历史规则未接入告警执行器，只能保持停用或删除。' : 'This historical rule has no executor and can only remain disabled or be deleted.', 'info');
      return;
    }

    if (skipApproval) {
      setTogglingIds((prev) => new Set(prev).add(ruleId));
      try {
        const resp = await fetch('/api/alerts/rules/batch-toggle', {
          method: 'POST',
          headers: getHeaders(true),
          body: JSON.stringify({
            rule_ids: [ruleId],
            enabled: !rule.enabled,
            actor_username: currentUsername,
            skip_approval_verification: true,
          }),
        });
        if (!resp.ok) throw new Error('Failed to toggle rule');
        setAlertRules((prev) => prev.map((r) => r.id === ruleId ? { ...r, enabled: !r.enabled } : r));
        showToast(language === 'zh' ? '规则状态已更新' : 'Rule state updated', 'success');
      } catch {
        showToast(language === 'zh' ? '切换规则状态失败' : 'Failed to toggle rule', 'error');
      } finally {
        setTogglingIds((prev) => { const next = new Set(prev); next.delete(ruleId); return next; });
      }
    } else {
      showToast(
        language === 'zh'
          ? '生产环境修改规则状态需要工单审批，已为您打开规则编辑器。'
          : 'Modifying rule state in production requires approval. Editor opened.',
        'info'
      );
      const updatedRule = { ...rule, enabled: !rule.enabled };
      openEdit(updatedRule);
    }
  };

  const handleCloneRule = (rule: AlertRuleSettings) => {
    resetScopeDeviceLookup();
    const cloned: AlertRuleSettings = {
      ...rule,
      id: undefined,
      name: `${rule.name} (${language === 'zh' ? '副本' : 'Copy'})`,
      created_by: currentUsername,
      updated_by: currentUsername,
      created_at: undefined,
      updated_at: undefined,
      notification_channels: normalizeAlertRuleNotificationChannels(rule.notification_channels, isHostMetric(rule.metric_type)),
      notification_group_names: rule.notification_group_names || [],
    };
    if (isHostMetric(cloned.metric_type)) {
      cloned.scope_type = 'global';
      cloned.scope_match_mode = 'exact';
      cloned.scope_value = '';
      cloned.notification_channels = ['workspace'];
      cloned.notification_group_names = [];
    }
    setEditingRuleId(null);
    setRuleDraft(cloned);
    if (cloned.scope_type === 'devices') {
      void loadScopeDeviceSelection(parseAlertScopeDeviceIds(cloned.scope_value || '[]'));
    }
  };

  const handleInlineDelete = (rule: AlertRuleSettings) => {
    if (!rule.id) return;
    setDeleteTargetIds([rule.id]);
    setDeleteTargetNames(rule.name);
    setDeleteReason('');
    setDeleteApprover('');
    setDeleteStatus('idle');
    setDeleteCountdown(0);
    setDeleteCode('');
    setDeleteToken('');
    setDeleteError('');
    setDeleteApprovalOpen(true);
  };

  const handleBatchToggle = async (enabled: boolean) => {
    if (selectedIds.size === 0) return;

    if (enabled && alertRules.some((rule) => rule.id && selectedIds.has(rule.id) && (rule.rule_supported === false || isServerMetric(rule.metric_type)))) {
      showToast(language === 'zh' ? '未接入执行器的历史规则不能批量启用。' : 'Historical rules without an executor cannot be enabled in bulk.', 'info');
      return;
    }

    if (skipApproval) {
      try {
        const resp = await fetch('/api/alerts/rules/batch-toggle', {
          method: 'POST',
          headers: getHeaders(true),
          body: JSON.stringify({
            rule_ids: Array.from(selectedIds),
            enabled,
            actor_username: currentUsername,
            skip_approval_verification: true,
          }),
        });
        if (!resp.ok) throw new Error('Failed to batch toggle');
        setAlertRules((prev) => prev.map((r) => r.id && selectedIds.has(r.id) ? { ...r, enabled } : r));
        setSelectedIds(new Set());
        showToast(language === 'zh' ? '批量更新成功' : 'Batch update successful', 'success');
      } catch {
        showToast(language === 'zh' ? '批量更新失败' : 'Batch update failed', 'error');
      }
    } else {
      showToast(
        language === 'zh'
          ? '生产环境批量启停需要单条获取工单审批修改。'
          : 'Batch toggling requires individual approval in production.',
        'info'
      );
    }
  };

  const handleBatchDelete = () => {
    if (selectedIds.size === 0) return;
    const targets = alertRules.filter((r) => r.id && selectedIds.has(r.id));
    setDeleteTargetIds(targets.map((r) => r.id!));
    setDeleteTargetNames(targets.map((r) => r.name).join(', '));
    setDeleteReason('');
    setDeleteApprover('');
    setDeleteStatus('idle');
    setDeleteCountdown(0);
    setDeleteCode('');
    setDeleteToken('');
    setDeleteError('');
    setDeleteApprovalOpen(true);
  };

  const allSelected = alertRules.length > 0 && alertRules.every((r) => r.id && selectedIds.has(r.id));
  const someSelected = selectedIds.size > 0;
  const metricSupportedForCreate = (metricType: string) => (
    !isServerMetric(metricType) && (supportedMetricTypes === null || supportedMetricTypes.has(metricType) || (isHostMetric(metricType) && supportedMetricTypes.has('host_*')))
  );
  const draftIsHostMetric = Boolean(ruleDraft && isHostMetric(ruleDraft.metric_type));
  const scopeDevicePickerDevices = Array.from(new Map(
    [...selectedScopeDevices, ...scopeDeviceCandidates].map((device) => [device.id, device]),
  ).values());
  const collectionBadgeClass = (source?: string) => source?.startsWith('snmp')
    ? 'bg-cyan-50 text-cyan-700 border-cyan-200'
    : 'bg-slate-50 text-slate-600 border-slate-200';

  return (
    <>
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={SlidersHorizontal}
        eyebrow={language === 'zh' ? '告警中心 / 告警规则' : 'Alert Center / Rules'}
        title={language === 'zh' ? '告警规则管理' : 'Alert Rules Management'}
        subtitle={language === 'zh' ? '灵活配置监控指标阈值与告警策略' : 'Configure metric thresholds and alerting policies'}
        actions={
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40 text-xs font-semibold shadow-sm">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              {language === 'zh' ? '遥测采集守护中 (15s/60s)' : 'Telemetry Daemon Active (15s/60s)'}
            </div>
            <button onClick={() => void loadAlertRules()} className={alertSecondaryButtonClass}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {language === 'zh' ? '刷新' : 'Refresh'}
            </button>
            <button onClick={openCreate} className={alertPrimaryButtonClass}>
              <Plus size={14} />
              {language === 'zh' ? '新增规则' : 'New Rule'}
            </button>
          </div>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 min-h-0">
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Category filter tabs */}
        <div className="px-5 py-4 border-b border-black/5 bg-[linear-gradient(to_right,#f4fbfc_0%,#ffffff_100%)] rounded-t-[28px]">
          <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
            <button
              onClick={() => setCategoryFilter('all')}
              className={`px-4 py-2 rounded-2xl text-[11px] font-black tracking-widest uppercase transition-all whitespace-nowrap shadow-sm border ${
                categoryFilter === 'all'
                ? 'bg-gradient-to-br from-[#164e63] to-[#0e3f52] text-white border-[#164e63] shadow-lg shadow-cyan-900/20 scale-[1.02]'
                : 'bg-white text-slate-400 border-slate-100 hover:border-slate-200 hover:text-slate-600'
              }`}
            >
              {language === 'zh' ? '全部规则' : 'All Rules'}
              <span className={`ml-2 px-1.5 py-0.5 rounded-lg text-[9px] ${categoryFilter === 'all' ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'}`}>
                {categoryCounts.all || 0}
              </span>
            </button>
            <button
              onClick={() => setCategoryFilter('network')}
              className={`px-4 py-2 rounded-2xl text-[11px] font-black tracking-widest uppercase transition-all whitespace-nowrap shadow-sm border ${
                categoryFilter === 'network'
                ? 'bg-gradient-to-br from-cyan-600 to-cyan-700 text-white border-cyan-500 shadow-lg shadow-cyan-600/20 scale-[1.02]'
                : 'bg-white text-slate-400 border-slate-100 hover:border-slate-200 hover:text-slate-600'
              }`}
            >
              {language === 'zh' ? '网络设备' : 'Network Device'}
              <span className={`ml-2 px-1.5 py-0.5 rounded-lg text-[9px] ${categoryFilter === 'network' ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'}`}>
                {categoryCounts.network || 0}
              </span>
            </button>
            <button
              onClick={() => setCategoryFilter('host')}
              className={`px-4 py-2 rounded-2xl text-[11px] font-black tracking-widest uppercase transition-all whitespace-nowrap shadow-sm border ${
                categoryFilter === 'host'
                ? 'bg-gradient-to-br from-cyan-600 to-cyan-700 text-white border-cyan-500 shadow-lg shadow-cyan-600/20 scale-[1.02]'
                : 'bg-white text-slate-400 border-slate-100 hover:border-slate-200 hover:text-slate-600'
              }`}
            >
              {language === 'zh' ? '宿主机' : 'Host'}
              <span className={`ml-2 px-1.5 py-0.5 rounded-lg text-[9px] ${categoryFilter === 'host' ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'}`}>
                {categoryCounts.host || 0}
              </span>
            </button>
            <button
              onClick={() => setCategoryFilter('server')}
              className={`px-4 py-2 rounded-2xl text-[11px] font-black tracking-widest uppercase transition-all whitespace-nowrap shadow-sm border ${
                categoryFilter === 'server'
                ? 'bg-gradient-to-br from-cyan-600 to-cyan-700 text-white border-cyan-500 shadow-lg shadow-cyan-600/20 scale-[1.02]'
                : 'bg-white text-slate-400 border-slate-100 hover:border-slate-200 hover:text-slate-600'
              }`}
            >
              {language === 'zh' ? '服务器' : 'Server'}
              <span className={`ml-2 px-1.5 py-0.5 rounded-lg text-[9px] ${categoryFilter === 'server' ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'}`}>
                {categoryCounts.server || 0}
              </span>
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center">
          <label className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/40" />
            <input
              value={search}
              onChange={(e) => {
                setPage(1);
                setSearch(e.target.value);
              }}
              placeholder={language === 'zh' ? '搜索规则名称、类型、范围' : 'Search rule name, metric, scope'}
              className={`${alertInputClass} rounded-xl py-3 pl-9 pr-3`}
            />
          </label>
          <select
            title={language === 'zh' ? '按监控类型筛选' : 'Filter by metric type'}
            value={metricFilter}
            onChange={(e) => { setPage(1); setMetricFilter(e.target.value); }}
            className="rounded-xl border border-black/10 bg-white px-3 py-3 text-sm text-[#164e63] outline-none"
          >
            <option value="all">{language === 'zh' ? '全部类型' : 'All Metrics'}</option>
            {(categoryFilter === 'all' || categoryFilter === 'network') && (
              <optgroup label={language === 'zh' ? '网络设备' : 'Network Device'}>
                {METRIC_OPTIONS_LIST.filter(m => m.category === 'network').map(m => (
                  <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                ))}
              </optgroup>
            )}
            {(categoryFilter === 'all' || categoryFilter === 'host') && (
              <optgroup label={language === 'zh' ? '宿主机' : 'Host'}>
                {METRIC_OPTIONS_LIST.filter(m => m.category === 'host').map(m => (
                  <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                ))}
              </optgroup>
            )}
            {(categoryFilter === 'all' || categoryFilter === 'server') && (
              <optgroup label={language === 'zh' ? '服务器' : 'Server'}>
                {METRIC_OPTIONS_LIST.filter(m => m.category === 'server').map(m => (
                  <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                ))}
              </optgroup>
            )}
          </select>
          <select
            title={language === 'zh' ? '按启用状态筛选规则' : 'Filter rules by enabled state'}
            value={enabledFilter}
            onChange={(e) => {
              setPage(1);
              setEnabledFilter(e.target.value);
            }}
            className="rounded-xl border border-black/10 bg-white px-3 py-3 text-sm text-[#164e63] outline-none"
          >
            <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
            <option value="enabled">{language === 'zh' ? '已启用' : 'Enabled'}</option>
            <option value="disabled">{language === 'zh' ? '已停用' : 'Disabled'}</option>
          </select>
        </div>

        {someSelected && (
          <div className="flex flex-wrap items-center gap-2 border-b border-black/5 px-5 py-3 bg-[#f7f9fc]">
            <span className="text-xs font-semibold text-black/50">
              {language === 'zh' ? `已选 ${selectedIds.size} 条` : `${selectedIds.size} selected`}
            </span>
            <button onClick={() => void handleBatchToggle(true)} className={alertSecondaryButtonClass + ' !h-9 !text-xs'}>
              <Power size={13} />
              {language === 'zh' ? '批量启用' : 'Enable'}
            </button>
            <button onClick={() => void handleBatchToggle(false)} className={alertSecondaryButtonClass + ' !h-9 !text-xs'}>
              <PowerOff size={13} />
              {language === 'zh' ? '批量停用' : 'Disable'}
            </button>
            <ActionButton icon={Trash2} variant="danger" size="sm" onClick={() => void handleBatchDelete()}>
              {language === 'zh' ? '批量删除' : 'Delete'}
            </ActionButton>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-xs text-black/40 hover:text-black/60">
              {language === 'zh' ? '取消选择' : 'Clear'}
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          <DataTable unstyled exportConfig={{ filename: 'alert-rules', language: language === 'zh' ? 'zh' : 'en', disabled: loading || rulesLoadError !== null || alertRules.length === 0, exportData: exportAllAlertRules }} className="nx-data-table text-left">
            <thead className="sticky top-0 z-10">
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="w-10 px-3 py-3">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => {
                      if (allSelected) {
                        setSelectedIds(new Set());
                      } else {
                        setSelectedIds(new Set(alertRules.map((r) => r.id).filter(Boolean) as string[]));
                      }
                    }}
                    className="accent-[#06b6d4]"
                  />
                </th>
                {alertRuleHeaders.map((header) => <th key={header} className="px-5 py-3">{header}</th>)}
                <TableActionHeader className="px-5 py-3">{language === 'zh' ? '操作' : 'Action'}</TableActionHeader>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={alertRuleHeaders.length + 2} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '正在加载规则...' : 'Loading rules...'}
                  </td>
                </tr>
              ) : rulesLoadError ? (
                <tr>
                  <td colSpan={alertRuleHeaders.length + 2} className="px-5 py-12 text-center">
                    <p className="text-sm font-semibold text-rose-700">
                      {rulesLoadError === 'forbidden'
                        ? (language === 'zh' ? '当前账号没有查看告警规则的权限。' : 'You do not have permission to view alert rules.')
                        : (language === 'zh' ? '告警规则加载失败。' : 'Failed to load alert rules.')}
                    </p>
                    {rulesLoadError === 'error' && (
                      <button onClick={() => void loadAlertRules()} className={`${alertSecondaryButtonClass} mt-3 !h-9 !text-xs`}>
                        <RefreshCw size={13} />
                        {language === 'zh' ? '重试' : 'Retry'}
                      </button>
                    )}
                  </td>
                </tr>
              ) : alertRules.length > 0 ? (
                alertRules.map((rule) => (
                  <tr key={rule.id} className={`border-b border-black/5 hover:bg-black/[0.02] ${rule.id && selectedIds.has(rule.id) ? 'bg-[#f0f6ff]' : ''}`}>
                    <td className="w-10 px-3 py-4 align-top">
                      <input
                        type="checkbox"
                        checked={!!rule.id && selectedIds.has(rule.id)}
                        onChange={() => {
                          if (!rule.id) return;
                          setSelectedIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(rule.id!)) next.delete(rule.id!); else next.add(rule.id!);
                            return next;
                          });
                        }}
                        className="accent-[#06b6d4]"
                      />
                    </td>
                    <td className="px-5 py-4 align-top">
                      <div className="group/copy-name relative">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-semibold text-[#164e63]">{rule.name}</p>
                          <ActionIconButton
                            icon={copiedId === `${rule.id}-name` ? Check : Copy}
                            label={language === 'zh' ? '复制名称' : 'Copy Name'}
                            size="xs"
                            variant={copiedId === `${rule.id}-name` ? 'success' : 'accent'}
                            onClick={(e) => { e.stopPropagation(); copyToClipboard(rule.name, `${rule.id}-name`); }}
                            className={`opacity-0 group-hover/copy-name:opacity-100 ${copiedId === `${rule.id}-name` ? 'opacity-100' : ''}`}
                          />
                        </div>
                        <div className="mt-1 flex items-center gap-1.5 group/copy-id">
                          <p data-export-ignore className="text-[10px] font-mono text-black/30">{rule.id}</p>
                          <ActionIconButton
                            icon={copiedId === `${rule.id}-id` ? Check : Copy}
                            label={language === 'zh' ? '复制 ID' : 'Copy ID'}
                            size="xs"
                            variant={copiedId === `${rule.id}-id` ? 'success' : 'accent'}
                            onClick={(e) => { e.stopPropagation(); copyToClipboard(rule.id || '', `${rule.id}-id`); }}
                            className={`opacity-0 group-hover/copy-id:opacity-100 ${copiedId === `${rule.id}-id` ? 'opacity-100' : ''}`}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{metricTypeLabel(rule.metric_type, language)}</td>
                    <td className="px-5 py-4 align-top">
                      {rule.collection ? (
                        <div>
                          <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${collectionBadgeClass(rule.collection.collection_source)}`}>
                            {language === 'zh' ? rule.collection.collection_label : (rule.collection.collection_label_en || rule.collection.collection_label)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-black/30">{language === 'zh' ? '未定义' : 'Undefined'}</span>
                      )}
                    </td>
                    <td className="px-5 py-4 align-top text-xs text-black/55" title={rule.collection?.description}>
                      {rule.collection?.template_section || '—'}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {scopeTypeLabel(rule.scope_type, language)}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      <span className="break-words text-[11px] leading-4 text-slate-500">
                        {alertRuleScopeSummary(rule.scope_type, rule.scope_value || '', rule.scope_match_mode || 'exact', language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top text-sm">
                      {rule.threshold != null ? (
                        <span className="font-mono text-black/70">&gt;&nbsp;{rule.threshold}%</span>
                      ) : (
                        <span className="inline-flex rounded-full bg-black/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-black/40">
                          {language === 'zh' ? '状态型' : 'State'}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-4 align-top text-xs text-black/50">
                      {rule.for_duration_seconds > 0
                        ? (rule.for_duration_seconds >= 60 ? `${Math.floor(rule.for_duration_seconds / 60)}m` : `${rule.for_duration_seconds}s`)
                        : '—'}
                    </td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-bold uppercase ${severityBadgeClass(rule.severity)}`}>
                        {severityLabel(rule.severity, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <div className="flex max-w-[180px] flex-wrap gap-1">
                        {isHostMetric(rule.metric_type) ? (
                          <span className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-500">
                            {language === 'zh' ? '仅用于健康状态' : 'Health status only'}
                          </span>
                        ) : normalizeAlertRuleNotificationChannels(rule.notification_channels).map((channel) => (
                          <span key={channel} className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${channel === 'feishu' ? 'border-cyan-100 bg-cyan-50 text-cyan-800' : channel === 'email' ? 'border-slate-200 bg-slate-50 text-slate-700' : 'border-slate-200 bg-white text-slate-600'}`}>
                            {notificationChannelLabel(channel, language)}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <div className="flex max-w-[180px] flex-wrap gap-1">
                        {!isHostMetric(rule.metric_type) && (rule.notification_group_names || []).map((groupName) => (
                          <span key={groupName} className="inline-flex items-center rounded-md border border-violet-100 bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700">
                            {groupName}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <div className="flex flex-col items-start gap-1.5">
                        <button
                          title={rule.enabled
                            ? (language === 'zh' ? '点击停用' : 'Click to disable')
                            : (language === 'zh' ? '点击启用' : 'Click to enable')}
                          onClick={() => void handleToggleEnabled(rule)}
                          disabled={!rule.id || togglingIds.has(rule.id)}
                          className={`group relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${rule.enabled ? 'bg-cyan-500' : 'bg-slate-300'}`}
                        >
                          <span
                            className="inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200"
                            style={{ transform: rule.enabled ? 'translateX(22px)' : 'translateX(3px)' }}
                          />
                        </button>
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top">
                      {(rule.rule_supported === false || isServerMetric(rule.metric_type)) ? (
                        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-700">{language === 'zh' ? '未接入' : 'Unavailable'}</span>
                      ) : (
                        <span className="text-xs text-black/50">{language === 'zh' ? '已接入' : 'Available'}</span>
                      )}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{formatTs(rule.updated_at || rule.created_at)}</td>
                    <TableActionCell className="px-5 py-4 align-top">
                      <ActionIconGroup label={language === 'zh' ? '告警规则操作' : 'Alert rule actions'}>
                        {!isServerMetric(rule.metric_type) && rule.rule_supported !== false && (
                          <ActionIconButton icon={Pencil} label={language === 'zh' ? '编辑' : 'Edit'} size="sm" onClick={() => openEdit(rule)} />
                        )}
                        {!isServerMetric(rule.metric_type) && rule.rule_supported !== false && (
                          <ActionIconButton icon={Copy} label={language === 'zh' ? '复制规则' : 'Clone rule'} size="sm" variant="accent" onClick={() => handleCloneRule(rule)} />
                        )}
                        <ActionIconButton icon={Trash2} label={language === 'zh' ? '删除' : 'Delete'} size="sm" variant="danger" onClick={() => void handleInlineDelete(rule)} />
                      </ActionIconGroup>
                    </TableActionCell>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={alertRuleHeaders.length + 2} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '当前没有规则。' : 'No rules found.'}
                  </td>
                </tr>
              )}
            </tbody>
          </DataTable>
        </div>

        <div className="mt-4">
          <Pagination
            currentPage={page}
            totalItems={total}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(value) => {
              setPage(1);
              setPageSize(value);
            }}
            onPageChange={setPage}
            language={language}
          />
        </div>

      </div>
      </div>
    </div>

      <AnimatePresence>
        {ruleDraft ? (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeEditor();
              }
            }}
          >
            <motion.div
              className="relative max-h-[90vh] w-full max-w-3xl overflow-auto rounded-[24px] bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-[0_32px_80px_rgba(11,35,64,0.22)]"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">
                    {editingRuleId
                      ? (language === 'zh' ? '编辑规则' : 'Edit Rule')
                      : (language === 'zh' ? '新增规则' : 'New Rule')}
                  </p>
                  <h3 className="mt-2 text-xl font-semibold text-[#164e63]">
                    {ruleDraft.name || (language === 'zh' ? '未命名规则' : 'Untitled Rule')}
                  </h3>
                </div>
                <button title={language === 'zh' ? '关闭编辑器' : 'Close editor'} onClick={closeEditor} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-5 px-6 py-6">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '规则名称' : 'Rule Name'}</span>
                    <input value={ruleDraft.name} onChange={(e) => updateRuleField('name', e.target.value)} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2`} />
                  </label>
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '监控类型' : 'Metric Type'}</span>
                    <select
                      value={ruleDraft.metric_type}
                      onChange={(e) => updateRuleField('metric_type', e.target.value as AlertRuleSettings['metric_type'])}
                      disabled={Boolean(editingRuleId)}
                      className="mt-2 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed transition-all"
                    >
                      <optgroup label={language === 'zh' ? '网络设备' : 'Network Device'}>
                        {METRIC_OPTIONS_LIST.filter(m => m.category === 'network' && metricSupportedForCreate(m.value)).map(m => (
                          <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                        ))}
                      </optgroup>
                      <optgroup label={language === 'zh' ? '宿主机' : 'Host'}>
                        {METRIC_OPTIONS_LIST.filter(m => m.category === 'host' && metricSupportedForCreate(m.value)).map(m => (
                          <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                        ))}
                      </optgroup>
                      {editingRuleId && isServerMetric(ruleDraft.metric_type) && <optgroup label={language === 'zh' ? '历史服务器规则（未接入）' : 'Historical server rule (unsupported)'}>
                        {
                          <option value={ruleDraft.metric_type}>{metricTypeLabel(ruleDraft.metric_type, language)}（历史记录）</option>
                        }
                      </optgroup>}
                    </select>
                    {editingRuleId && (
                      <p className="mt-1 text-[11px] text-amber-600 font-medium">
                        {language === 'zh'
                          ? '提示：监控类型在编辑时不可更改。若需更换，请先取消并使用“复制规则”功能克隆。'
                          : 'Note: Metric type cannot be changed on edit. To change it, clone this rule instead.'}
                      </p>
                    )}
                  </label>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-slate-50/55 px-4 py-3">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <label className="text-sm text-black/65">
                      <span>{language === 'zh' ? '执行机器' : 'Execution machines'}</span>
                      <select value={ruleDraft.scope_type} onChange={(e) => updateRuleField('scope_type', e.target.value as AlertRuleSettings['scope_type'])} disabled={draftIsHostMetric} className="mt-1.5 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none disabled:bg-black/[0.03]">
                        <option value="global">{language === 'zh' ? '全部设备' : 'All devices'}</option>
                        {!draftIsHostMetric && <>
                          <option value="devices">{scopeTypeLabel('devices', language)}</option>
                          <option value="site">{scopeTypeLabel('site', language)}</option>
                          <option value="role">{scopeTypeLabel('role', language)}</option>
                          <option value="composite">{scopeTypeLabel('composite', language)}</option>
                          <option value="tag">{scopeTypeLabel('tag', language)}</option>
                          <option value="interface">{language === 'zh' ? '接口名（跨设备）' : 'Interface name (all devices)'}</option>
                          {ruleDraft.scope_type === 'ip' && <option value="ip">{language === 'zh' ? '指定 IP（历史规则）' : 'Specific IPs (legacy)'}</option>}
                          {ruleDraft.scope_type === 'device' && <option value="device">{language === 'zh' ? '设备标识（旧规则）' : 'Device identifier (legacy)'}</option>}
                        </>}
                      </select>
                    </label>
                    <label className="text-sm text-black/65">
                      <span>{language === 'zh' ? '匹配方式' : 'Match mode'}</span>
                      <select
                        value={ruleDraft.scope_match_mode}
                        onChange={(e) => updateRuleField('scope_match_mode', e.target.value as AlertRuleSettings['scope_match_mode'])}
                        disabled={draftIsHostMetric || ['global', 'devices', 'ip', 'tag'].includes(ruleDraft.scope_type)}
                        className="mt-1.5 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none disabled:bg-black/[0.03]"
                      >
                        <option value="exact">{language === 'zh' ? '精确匹配' : 'Exact match'}</option>
                        <option value="contains">{language === 'zh' ? '模糊匹配（包含）' : 'Fuzzy match (contains)'}</option>
                        {ruleDraft.scope_match_mode === 'prefix' && <option value="prefix">{scopeMatchModeLabel('prefix', language)} · {language === 'zh' ? '旧规则' : 'legacy'}</option>}
                        {ruleDraft.scope_match_mode === 'glob' && <option value="glob">{scopeMatchModeLabel('glob', language)} · {language === 'zh' ? '旧规则' : 'legacy'}</option>}
                      </select>
                    </label>
                  </div>
                  {!draftIsHostMetric && !['global', 'devices', 'ip', 'tag'].includes(ruleDraft.scope_type) && (
                    <p className="mt-1.5 text-[10px] leading-4 text-slate-500">{scopeMatchModeDescription(ruleDraft.scope_match_mode, language)}</p>
                  )}

                  {ruleDraft.scope_type === 'devices' && (
                    <div className="mt-3 space-y-3">
                      <label className="block text-xs font-medium text-slate-600">
                        <span>{language === 'zh' ? '搜索 CMDB 设备' : 'Search CMDB devices'}</span>
                        <div className="mt-1.5 flex gap-2">
                          <input
                            type="search"
                            value={scopeDeviceSearchQuery}
                            onChange={(event) => setScopeDeviceSearchQuery(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter') {
                                event.preventDefault();
                                void searchScopeDevices();
                              }
                            }}
                            className={`${alertInputClass} min-w-0 flex-1 rounded-xl px-3 py-2`}
                            placeholder={language === 'zh' ? '设备名称、管理 IP、序列号或资产标签，按回车查询' : 'Name, management IP, serial number, or asset tag; press Enter'}
                            aria-label={language === 'zh' ? '搜索 CMDB 设备' : 'Search CMDB devices'}
                          />
                          <button
                            type="button"
                            onClick={() => void searchScopeDevices()}
                            disabled={!scopeDeviceSearchQuery.trim() || scopeDeviceSearchStatus === 'loading'}
                            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-cyan-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            {scopeDeviceSearchStatus === 'loading' ? <RefreshCw size={13} className="animate-spin" /> : <Search size={13} />}
                            {language === 'zh' ? '查找' : 'Search'}
                          </button>
                        </div>
                      </label>
                      <p className="text-[10px] leading-4 text-slate-500">
                        {language === 'zh' ? '回车后查询当前租户 CMDB；在结果窗口勾选并确认后，设备才会加入规则。' : 'Searches this tenant’s CMDB. Devices are added to the rule after you select and confirm them in the results window.'}
                      </p>

                      {selectedScopeDevices.length > 0 && (
                        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50/70 px-3 py-2.5">
                          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-900">
                            <Check size={13} className="text-emerald-600" />
                            {language === 'zh' ? `已确认 ${selectedScopeDevices.length} 台执行机器` : `${selectedScopeDevices.length} confirmed machines`}
                            {missingScopeDeviceIds.length > 0 && (
                              <span className="font-normal text-amber-700">{language === 'zh' ? `· ${missingScopeDeviceIds.length} 台待处理` : `· ${missingScopeDeviceIds.length} unavailable`}</span>
                            )}
                          </span>
                          <button
                            type="button"
                            onClick={openScopeDevicePicker}
                            className="rounded-lg border border-emerald-200 bg-white px-2.5 py-1.5 text-[10px] font-semibold text-emerald-800 transition hover:bg-emerald-100"
                          >
                            {language === 'zh' ? '查看或调整' : 'Review or adjust'}
                          </button>
                          </div>
                      )}

                      {missingScopeDeviceIds.length > 0 && (
                        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[10px] text-amber-800">
                          <span>{language === 'zh' ? `${missingScopeDeviceIds.length} 台已选设备已不在当前租户 CMDB 中。` : `${missingScopeDeviceIds.length} selected device(s) are no longer in this tenant’s CMDB.`}</span>
                          <button type="button" onClick={removeMissingScopeDevices} className="font-semibold underline">
                            {language === 'zh' ? '移除失效设备' : 'Remove unavailable devices'}
                          </button>
                        </div>
                      )}

                      {scopeDeviceSearchStatus === 'loading' && (
                        <p className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">
                          <RefreshCw size={13} className="animate-spin" />
                          {language === 'zh' ? '正在查询或确认 CMDB 设备…' : 'Searching or resolving CMDB devices…'}
                        </p>
                      )}
                      {scopeDeviceSearchStatus === 'forbidden' && (
                        <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
                          {language === 'zh' ? '当前账号无权读取此租户的 CMDB 设备。' : 'You cannot read CMDB devices for this tenant.'}
                        </p>
                      )}
                      {scopeDeviceSearchStatus === 'error' && (
                        <div className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
                          <span>{language === 'zh' ? 'CMDB 查询失败，请重试。' : 'CMDB search failed. Please retry.'}</span>
                          <button type="button" onClick={() => void searchScopeDevices()} className="font-semibold underline">
                            {language === 'zh' ? '重试' : 'Retry'}
                          </button>
                        </div>
                      )}
                      {scopeDeviceSearchStatus === 'empty' && (
                        <p className="rounded-xl border border-dashed border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">
                          {language === 'zh' ? 'CMDB 中没有匹配设备，请检查名称或 IP。' : 'No CMDB devices match this search. Check the name or IP.'}
                        </p>
                      )}
                      {scopeDeviceSearchStatus === 'idle' && selectedScopeDevices.length === 0 && (
                        <p className="rounded-xl border border-dashed border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">
                          {language === 'zh' ? '输入关键词并按回车，在结果窗口核对 IP，确认后加入执行机器。' : 'Enter a keyword and press Enter. Review IPs in the results window, then confirm the execution machines.'}
                        </p>
                      )}
                      {scopeDeviceSearchStatus === 'ready' && (
                        <div className="flex items-center justify-between gap-3 rounded-xl border border-cyan-100 bg-white px-3.5 py-3 shadow-sm">
                          <div className="min-w-0">
                            <p className="text-xs font-semibold text-slate-800">
                              {language === 'zh' ? `匹配到 ${scopeDeviceSearchTotal} 台设备` : `${scopeDeviceSearchTotal} matching devices`}
                            </p>
                            <p className="mt-0.5 text-[10px] text-slate-500">
                              {language === 'zh' ? '请在独立列表中核对 IP 并确认执行机器。' : 'Review IPs and confirm the execution machines in the separate list.'}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={openScopeDevicePicker}
                            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-[11px] font-semibold text-cyan-800 transition hover:border-cyan-300 hover:bg-cyan-100"
                          >
                            <Search size={13} />
                            {language === 'zh' ? `查看结果 · ${scopeDeviceCandidates.length}` : `Review · ${scopeDeviceCandidates.length}`}
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {ruleDraft.scope_type === 'site' && (
                    <ScopeCatalogCombobox
                      ariaLabel={language === 'zh' ? '筛选站点' : 'Filter by site'}
                      language={language}
                      options={scopeCatalog?.sites || []}
                      placeholder={language === 'zh' ? '选择或输入站点' : 'Select or enter a site'}
                      value={ruleDraft.scope_value}
                      onChange={(value) => updateRuleField('scope_value', value)}
                      wrapperClassName="mt-3"
                    />
                  )}
                  {ruleDraft.scope_type === 'role' && (
                    <ScopeCatalogCombobox
                      ariaLabel={language === 'zh' ? '筛选设备角色' : 'Filter by device role'}
                      language={language}
                      options={scopeCatalog?.roles || []}
                      placeholder={language === 'zh' ? '选择或输入设备角色' : 'Select or enter a device role'}
                      value={ruleDraft.scope_value}
                      onChange={(value) => updateRuleField('scope_value', value)}
                      wrapperClassName="mt-3"
                    />
                  )}
                  {ruleDraft.scope_type === 'device' && (
                    <input value={ruleDraft.scope_value} onChange={(event) => updateRuleField('scope_value', event.target.value)} className={`${alertInputClass} mt-3 rounded-xl px-3 py-2`} placeholder={language === 'zh' ? '设备 ID、主机名或 IP' : 'Device ID, hostname, or IP'} />
                  )}
                  {ruleDraft.scope_type === 'interface' && (
                    <input value={ruleDraft.scope_value} onChange={(event) => updateRuleField('scope_value', event.target.value)} className={`${alertInputClass} mt-3 rounded-xl px-3 py-2`} placeholder={language === 'zh' ? '接口名称，如 GigabitEthernet0/0/1' : 'Interface name, e.g. GigabitEthernet0/0/1'} />
                  )}
                  {ruleDraft.scope_type === 'ip' && (
                    <textarea value={ruleDraft.scope_value} onChange={(event) => updateRuleField('scope_value', event.target.value)} rows={2} className={`${alertInputClass} mt-3 rounded-xl px-3 py-2 font-mono`} placeholder={language === 'zh' ? '输入设备管理 IP，多个地址用逗号或换行分隔' : 'Management IPs separated by commas or new lines'} />
                  )}
                  {ruleDraft.scope_type === 'composite' && (() => {
                    const filters = parseAlertCompositeScope(ruleDraft.scope_value);
                    const fields = [
                      { key: 'site' as const, label: language === 'zh' ? '站点' : 'Site', options: scopeCatalog?.sites || [] },
                      { key: 'role' as const, label: language === 'zh' ? '设备角色' : 'Role', options: scopeCatalog?.roles || [] },
                      { key: 'category' as const, label: language === 'zh' ? '设备类型' : 'Type', options: scopeCatalog?.categories || [] },
                      { key: 'platform' as const, label: language === 'zh' ? '平台' : 'Platform', options: scopeCatalog?.platforms || [] },
                      { key: 'interface' as const, label: language === 'zh' ? '接口名（可选）' : 'Interface (optional)', options: null },
                    ];
                    return (
                      <div className="mt-3 space-y-2">
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {fields.map((field) => (
                            <label key={field.key} className="text-xs text-slate-600">
                              <span>{field.label}</span>
                              {field.options ? (
                                <ScopeCatalogCombobox
                                  ariaLabel={field.label}
                                  language={language}
                                  options={field.options}
                                  placeholder={field.label}
                                  value={filters[field.key] || ''}
                                  onChange={(value) => updateCompositeFilter(field.key, value)}
                                  wrapperClassName="mt-1"
                                />
                              ) : (
                                <input value={filters[field.key] || ''} onChange={(event) => updateCompositeFilter(field.key, event.target.value)} className={`${alertInputClass} mt-1 rounded-xl px-3 py-2`} />
                              )}
                            </label>
                          ))}
                        </div>
                      </div>
                    );
                  })()}
                  {ruleDraft.scope_type === 'tag' && (
                    <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
                      <TagConditionPicker
                        value={parseTagFilter(ruleDraft.scope_value)}
                        onChange={(value) => updateRuleField('scope_value', serializeTagFilter(value))}
                        language={language}
                      />
                      {hasTagFilterConditions(parseTagFilter(ruleDraft.scope_value)) && (
                        <p className="mt-2 text-[10px] text-slate-500">{countTagFilterConditions(parseTagFilter(ruleDraft.scope_value))} {language === 'zh' ? '项标签条件' : 'tag conditions'}</p>
                      )}
                    </div>
                  )}

                  {ruleDraft.scope_type === 'global' ? (
                    <p className="mt-2 text-[11px] leading-5 text-slate-600">
                      {draftIsHostMetric
                        ? (language === 'zh' ? '宿主机指标由平台资源监控，范围固定为全局。' : 'Host metrics use platform resource monitoring and always match globally.')
                        : (language === 'zh' ? '匹配当前租户中所有支持该指标的设备。' : 'Matches all devices in this tenant that support the metric.')}
                    </p>
                  ) : (
                    <p className="mt-2 text-[11px] leading-5 text-slate-600">{scopeTargetDescription(ruleDraft.scope_type, language)}</p>
                  )}
                  {!draftIsHostMetric && scopeCatalogLoading && <p className="mt-1 text-[10px] text-slate-400">{language === 'zh' ? '正在读取当前租户资产选项…' : 'Loading this tenant’s asset options…'}</p>}
                  {!draftIsHostMetric && scopeCatalogError && (
                    <p className="mt-1 text-[10px] text-amber-700">
                      {scopeCatalogError === 'forbidden'
                        ? (language === 'zh' ? '当前账号无权读取资产选项，可手动输入范围值。' : 'You cannot read asset options; enter a scope value manually.')
                        : (language === 'zh' ? '资产选项加载失败，可手动输入，或重试。' : 'Asset options failed to load; enter a value or retry.')}
                      {scopeCatalogError === 'error' && <button type="button" onClick={() => void loadScopeCatalog()} className="ml-1 font-semibold underline">{language === 'zh' ? '重试' : 'Retry'}</button>}
                    </p>
                  )}
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '告警级别' : 'Severity'}</span>
                    <select value={ruleDraft.severity} onChange={(e) => updateRuleField('severity', e.target.value as AlertRuleSettings['severity'])} className="mt-2 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none">
                      {ALERT_SEVERITY_OPTIONS.map((severity) => (
                        <option key={severity} value={severity}>{severityLabel(severity, language)}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '阈值' : 'Threshold'}</span>
                    <input type="number" min="0" value={ruleDraft.threshold ?? ''} onChange={(e) => updateRuleField('threshold', e.target.value === '' ? null : Number(e.target.value))} disabled={!thresholdMetrics.has(ruleDraft.metric_type)} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2 disabled:bg-black/[0.03]`} />
                  </label>
                </div>

                <details className="rounded-2xl border border-black/[0.06] bg-white px-4 py-3">
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-[#164e63]">
                    <ChevronRight size={14} />
                    {language === 'zh' ? '高级：触发与重复控制' : 'Advanced: trigger and repeat controls'}
                  </summary>
                  <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
                    <label className="text-sm text-black/65">
                      <span>{language === 'zh' ? '持续时间(秒)' : 'Duration (sec)'}</span>
                      <input type="number" min="0" max="3600" value={ruleDraft.for_duration_seconds} onChange={(e) => updateRuleField('for_duration_seconds', Number(e.target.value))} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2`} placeholder={language === 'zh' ? '0=立即触发' : '0=immediate'} />
                    </label>
                    <label className="text-sm text-black/65">
                      <span>{language === 'zh' ? '重复通知抑制窗口(秒)' : 'Repeat suppression window (sec)'}</span>
                      <input type="number" min="0" max="86400" value={ruleDraft.notification_repeat_window_seconds} onChange={(e) => updateRuleField('notification_repeat_window_seconds', Number(e.target.value))} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2`} />
                      <span className="mt-1 block text-[10px] leading-4 text-slate-500">{language === 'zh' ? '用于抑制相同告警的重复投递，不是定时提醒。' : 'Suppresses repeated delivery of the same alert; it is not a reminder schedule.'}</span>
                    </label>
                  </div>
                </details>

                {draftIsHostMetric ? (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-xs leading-5 text-slate-600">
                    {language === 'zh'
                      ? '宿主机 CPU、内存和磁盘规则只用于计算平台健康状态，不会通过 Webhook、邮件或通知组发送告警。'
                      : 'Host CPU, memory, and disk rules only calculate platform health status. They do not send alerts through Webhook, email, or notification groups.'}
                  </div>
                ) : <fieldset className="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5">
                  <legend className="px-1 text-sm font-semibold text-slate-800">
                    {language === 'zh' ? '通知规则' : 'Notification rules'}
                  </legend>
                  <p className="text-[11px] text-slate-500">
                    {language === 'zh' ? '勾选要使用的通知方式，可同时选择 Webhook 和邮件。' : 'Choose one or both notification methods.'}
                  </p>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2" role="group" aria-label={language === 'zh' ? '告警通知规则' : 'Alert notification rules'}>
                    {NOTIFICATION_CHANNEL_OPTIONS.map((option) => {
                      const selectedChannels = (ruleDraft.notification_channels || []).filter((channel) => channel !== 'workspace');
                      const selected = selectedChannels.includes(option.value);
                      const OptionIcon = option.icon;
                      return (
                        <label
                          key={option.value}
                          title={language === 'zh' ? option.titleZh : option.titleEn}
                          className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 transition focus-within:ring-2 focus-within:ring-cyan-500/30 ${selected ? 'border-cyan-300 bg-cyan-50/80 text-cyan-900' : 'border-slate-200 bg-white text-slate-600 hover:border-cyan-200'}`}
                        >
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleNotificationChannel(option.value)}
                            aria-label={language === 'zh' ? option.labelZh : option.labelEn}
                            className="mt-0.5 h-4 w-4 shrink-0 rounded accent-cyan-700"
                          />
                          <OptionIcon size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
                          <span className="min-w-0">
                            <span className="block text-xs font-semibold">{language === 'zh' ? option.labelZh : option.labelEn}</span>
                            <span className="mt-0.5 block text-[10px] leading-4 text-slate-500">{language === 'zh' ? option.titleZh : option.titleEn}</span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                  {ruleDraft.notification_channels?.includes('email') && (
                    <p className="mt-2 text-[11px] leading-4 text-slate-500">
                      {language === 'zh' ? '邮件发送到已启用 SMTP 通道的收件目标；选择通知组后，只发送给组内成员。' : 'Email uses recipients from enabled SMTP channels; selected groups limit delivery to their members.'}
                    </p>
                  )}
                  <div className="mt-4 border-t border-slate-200 pt-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-slate-800">{language === 'zh' ? '通知组' : 'Notification groups'}</p>
                        <p className="mt-1 text-[10px] leading-4 text-slate-500">{language === 'zh' ? '仅显示当前租户中有活动成员的组；组选择会随规则保存。' : 'Only groups with active members in this tenant are shown; selections are saved with the rule.'}</p>
                      </div>
                      {notificationGroupsLoading && <RefreshCw size={14} className="animate-spin text-cyan-600" />}
                    </div>
                    {notificationGroupsError ? (
                      <div className="mt-2 rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
                        <p>{notificationGroupsError === 'forbidden'
                          ? (language === 'zh' ? '当前账号没有读取通知组目录的权限。' : 'You do not have permission to read notification groups.')
                          : (language === 'zh' ? '通知组目录加载失败。' : 'Failed to load notification groups.')}</p>
                        {notificationGroupsError === 'error' && <button type="button" onClick={() => void loadNotificationGroups()} className="mt-1 font-semibold underline">{language === 'zh' ? '重试' : 'Retry'}</button>}
                      </div>
                    ) : !notificationGroupsLoading && notificationGroups.length === 0 ? (
                      <p className="mt-2 rounded-lg border border-dashed border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">{language === 'zh' ? '暂无可选通知组，可直接使用上方通知规则。' : 'No notification groups are available; use the methods above.'}</p>
                    ) : (
                      <div className="mt-2 grid max-h-40 gap-2 overflow-y-auto sm:grid-cols-2">
                        {notificationGroups.map((group) => {
                          const selected = (ruleDraft.notification_group_names || []).includes(group.name);
                          return (
                            <label key={group.name} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition ${selected ? 'border-violet-300 bg-violet-50 text-violet-900' : 'border-slate-200 bg-white text-slate-600 hover:border-violet-200'}`}>
                              <input type="checkbox" checked={selected} onChange={() => toggleNotificationGroup(group.name)} className="h-4 w-4 accent-violet-700" />
                              <span className="min-w-0 flex-1 truncate text-xs font-semibold">{group.name}</span>
                              <span className="text-[10px] text-slate-500">{group.member_count}</span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </fieldset>}

                <label className="flex items-center gap-3 rounded-2xl bg-[#f7f8fb] px-4 py-3 text-sm text-black/65">
                  <input type="checkbox" checked={ruleDraft.enabled} onChange={(e) => updateRuleField('enabled', e.target.checked)} />
                  <span>{language === 'zh' ? '启用此规则' : 'Enable this rule'}</span>
                </label>

                {/* ---------- Config Approval Section ---------- */}
                <div className="rounded-2xl border border-black/5 overflow-hidden">
                  <div className="bg-slate-50 px-4 py-3 border-b border-black/5 flex items-center justify-between">
                    <span className="text-xs font-bold text-[#164e63] flex items-center gap-1.5">
                      <Shield size={14} className="text-cyan-600" />
                      {language === 'zh' ? '变更审批授权' : 'Approval Authorization'}
                    </span>
                    {isProduction ? (
                      <span className="text-xs text-rose-500 font-bold bg-rose-50 px-2.5 py-1 rounded-lg border border-rose-100 shadow-sm">
                        {language === 'zh' ? '生产环境 强制校验' : 'Production Enforced Check'}
                      </span>
                    ) : (
                      <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={skipApproval}
                          onChange={(e) => {
                            setSkipApproval(e.target.checked);
                            setApprovalStatus('idle');
                            setApprovalCode('');
                            setApprovalError('');
                          }}
                          className="rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                        />
                        <span>{language === 'zh' ? '仅测试/开发环境可用 - 跳过审批' : 'Dev/Test only - Skip approval'}</span>
                      </label>
                    )}
                  </div>
                  
                  {!skipApproval && approvalStatus !== 'verified' && (
                    <div className="px-5 py-4 bg-white space-y-4 text-xs">
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        <label className="block text-slate-600">
                          <span className="font-bold text-slate-700 block mb-1">{language === 'zh' ? '变更原因说明' : 'Reason for Change'}</span>
                          <input
                            value={configReason}
                            onChange={(e) => setConfigReason(e.target.value)}
                            placeholder={language === 'zh' ? '输入为什么启用/停用/修改此规则...' : 'Enter reason for this change...'}
                            className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/20 transition-all"
                          />
                        </label>
                        
                        <label className="block text-slate-600">
                          <span className="font-bold text-slate-700 block mb-1">{language === 'zh' ? '选择授权审批人' : 'Select Approver'}</span>
                          <div className="flex items-center gap-2">
                            <select
                              value={approverUsername}
                              onChange={(e) => setApproverUsername(e.target.value)}
                              disabled={approvalStatus === 'sent' || approvalStatus === 'sending'}
                              className="flex-1 rounded-xl border border-black/10 bg-white px-3 py-2 outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/20 transition-all disabled:bg-slate-50"
                            >
                              <option value="">{language === 'zh' ? '选择审批人...' : 'Select approver...'}</option>
                              {approvers.map((u) => (
                                <option key={u.id} value={u.username}>
                                  {u.username} ({u.role})
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={requestApproval}
                              disabled={!approverUsername || !configReason.trim() || approvalStatus === 'sending' || (approvalStatus === 'sent' && approvalCountdown > 0)}
                              className={`px-4 py-2 rounded-xl font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                                approverUsername && configReason.trim() && !(approvalStatus === 'sent' && approvalCountdown > 0)
                                  ? 'bg-[#164e63] text-white hover:bg-cyan-800 shadow-sm'
                                  : 'bg-black/5 text-black/35 cursor-not-allowed'
                              }`}
                            >
                              {approvalStatus === 'sending' ? (
                                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                              ) : approvalStatus === 'sent' && approvalCountdown > 0 ? (
                                `${Math.floor(approvalCountdown / 60)}:${String(approvalCountdown % 60).padStart(2, '0')}`
                              ) : (
                                language === 'zh' ? '发送验证码' : 'Send Code'
                              )}
                            </button>
                          </div>
                        </label>
                      </div>

                      {approvalStatus === 'sent' && (
                        <div className="space-y-1.5 pt-3 border-t border-slate-100">
                          <label className="text-[11px] text-slate-500 block">
                            {language === 'zh' ? '输入审批人收到的 6 位工单验证码' : 'Enter 6-digit code sent to approver'}
                          </label>
                          <div className="flex items-center gap-2">
                            <input
                              value={approvalCode}
                              onChange={(e) => {
                                setApprovalCode(e.target.value.replace(/\D/g, '').slice(0, 6));
                                setApprovalError('');
                              }}
                              placeholder="000000"
                              maxLength={6}
                              className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-black/10 py-2 text-sm outline-none focus:border-cyan-500 transition-all"
                            />
                            <button
                              type="button"
                              onClick={verifyApproval}
                              disabled={approvalCode.length !== 6}
                              className={`px-4 py-2 rounded-xl font-bold transition-all ${
                                approvalCode.length === 6
                                  ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                                  : 'bg-black/5 text-black/35 cursor-not-allowed'
                              }`}
                            >
                              {language === 'zh' ? '验证' : 'Verify'}
                            </button>
                          </div>
                        </div>
                      )}

                      {approvalError && (
                        <p className="text-rose-600 text-xs mt-1 flex items-center gap-1">
                          <span>⚠️</span>
                          {approvalError}
                        </p>
                      )}
                      
                      <p className="text-[10px] text-slate-400">
                        {language === 'zh'
                          ? '验证码将发送至审批人的飞书工作台，5 分钟内有效。'
                          : 'A verification code will be sent to the approver via Feishu. Valid for 5 mins.'}
                      </p>
                    </div>
                  )}

                  {!skipApproval && approvalStatus === 'verified' && (
                    <div className="px-5 py-4 bg-emerald-50 border-t border-emerald-100 flex items-center gap-2 text-emerald-800 text-xs font-semibold">
                      <Check size={16} className="text-emerald-600" />
                      {language === 'zh' ? '审批验证已通过，随时可保存生效' : 'Approval verified. You can save changes now.'}
                    </div>
                  )}
                </div>

                {/* ---------- Rule change history ---------- */}
                {editingRuleId && ruleHistory.length > 0 && (
                  <div className="rounded-2xl border border-black/[0.06] bg-black/[0.015]">
                    <button
                      type="button"
                      onClick={() => setHistoryExpanded((v) => !v)}
                      className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-black/55 hover:text-black/75"
                    >
                      {historyExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      {language === 'zh' ? `变更历史 (${ruleHistory.length})` : `Change history (${ruleHistory.length})`}
                    </button>
                    {historyExpanded && (
                      <div className="max-h-48 overflow-y-auto border-t border-black/5 px-4 py-2">
                        {ruleHistory.map((h) => (
                          <div key={h.id} className="flex items-start gap-3 border-b border-black/[0.03] py-2 last:border-0">
                            <span className="shrink-0 text-xs text-black/35">{formatTs(h.created_at)}</span>
                            <span className="text-xs text-black/50">{h.changed_by || 'system'}</span>
                            <span className="flex-1 truncate text-xs text-black/60" title={JSON.stringify(h.snapshot)}>
                              {h.snapshot?.name ? `${h.snapshot.name} — ${h.snapshot.severity} / ${h.snapshot.threshold ?? 'state'}` : language === 'zh' ? '快照' : 'snapshot'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-black/5 px-6 py-4">
                <div className="text-sm text-black/45">
                  {isDirty
                    ? (language === 'zh' ? '你有未保存的改动。' : 'You have unsaved changes.')
                    : (language === 'zh' ? '当前没有未保存改动。' : 'No unsaved changes.')}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button disabled={!isDirty} onClick={handleReset} className={alertSecondaryButtonClass}>
                    {language === 'zh' ? '重置' : 'Reset'}
                  </button>
                  {editingRuleId ? (
                    <ActionButton icon={Trash2} variant="danger" size="md" onClick={handleDelete}>
                      {language === 'zh' ? '删除' : 'Delete'}
                    </ActionButton>
                  ) : null}
                  <button
                    disabled={saving || !isDirty || (!skipApproval && approvalStatus !== 'verified')}
                    onClick={() => void handleSave()}
                    className={alertPrimaryButtonClass}
                  >
                    <Save size={14} />
                    {saving ? (language === 'zh' ? '保存中...' : 'Saving...') : (language === 'zh' ? '保存' : 'Save')}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {scopeDevicePickerOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) closeScopeDevicePicker();
            }}
          >
            <motion.section
              role="dialog"
              aria-modal="true"
              aria-labelledby="scope-device-picker-title"
              initial={{ opacity: 0, y: 12, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.985 }}
              transition={{ duration: 0.16, ease: 'easeOut' }}
              className="flex max-h-[82vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_28px_80px_rgba(2,6,23,0.32)] dark:border-white/10 dark:bg-slate-900"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-4 py-3.5 dark:border-white/10 sm:px-5">
                <div className="min-w-0">
                  <h2 id="scope-device-picker-title" className="text-sm font-semibold text-slate-900 dark:text-white">
                    {language === 'zh' ? '确认执行机器' : 'Confirm execution machines'}
                  </h2>
                  <p className="mt-1 truncate text-[10px] text-slate-500 dark:text-slate-400">
                    {language === 'zh'
                    ? (scopeDeviceSearchQuery
                      ? `搜索“${scopeDeviceSearchQuery}” · 命中 ${scopeDeviceSearchTotal} 台 · 列表 ${scopeDevicePickerDevices.length} 台（含已选设备）`
                      : `已确认 ${selectedScopeDevices.length} 台 · 可在此调整执行机器`)
                    : (scopeDeviceSearchQuery
                      ? `Search “${scopeDeviceSearchQuery}” · ${scopeDeviceSearchTotal} matches · ${scopeDevicePickerDevices.length} listed (including selected)`
                      : `${selectedScopeDevices.length} confirmed · review execution machines here`)}
                  </p>
                  {scopeDeviceSearchTotal > scopeDeviceCandidates.length && (
                    <p className="mt-1 text-[10px] text-amber-700 dark:text-amber-300">
                      {language === 'zh' ? '结果较多，仅显示前 50 台；请缩小搜索词后再确认。' : 'Only the first 50 results are shown; refine the query to confirm a narrower set.'}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={closeScopeDevicePicker}
                  aria-label={language === 'zh' ? '取消并关闭' : 'Cancel and close'}
                  className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-white"
                >
                  <X size={16} />
                </button>
              </header>

              <div className="flex items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-4 py-2 dark:border-white/10 dark:bg-white/[0.03] sm:px-5">
                <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                  {language === 'zh' ? `当前待确认 ${pendingScopeDeviceIds.length} 台` : `${pendingScopeDeviceIds.length} selected`}
                </span>
                <button
                  type="button"
                  onClick={toggleAllScopeDeviceCandidates}
                  className="text-[10px] font-semibold text-cyan-700 hover:text-cyan-900 dark:text-cyan-300 dark:hover:text-cyan-200"
                >
                  {scopeDeviceCandidates.length > 0 && scopeDeviceCandidates.every((device) => pendingScopeDeviceIds.includes(device.id))
                    ? (language === 'zh' ? '取消选择当前结果' : 'Clear current results')
                    : (language === 'zh' ? '选择当前结果' : 'Select current results')}
                </button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-2.5 sm:p-3">
                <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-white/10">
                  {scopeDevicePickerDevices.map((device) => {
                    const checked = pendingScopeDeviceIds.includes(device.id);
                    const ip = device.management_ip || device.ip_address || (language === 'zh' ? '无管理 IP' : 'No management IP');
                    const metadata = [
                      device.site,
                      device.role,
                      device.platform,
                      device.serial_number && `SN ${device.serial_number}`,
                      device.asset_tag && `${language === 'zh' ? '资产' : 'Asset'} ${device.asset_tag}`,
                    ].filter(Boolean).join(' · ');
                    return (
                      <label
                        key={device.id}
                        className={`grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-2.5 border-b border-slate-100 px-3 py-2 last:border-b-0 transition dark:border-white/[0.06] sm:gap-3 sm:px-3.5 ${checked ? 'bg-cyan-50/70 dark:bg-cyan-500/[0.08]' : 'bg-white hover:bg-slate-50 dark:bg-slate-900 dark:hover:bg-white/[0.04]'}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => togglePendingScopeDevice(device)}
                          className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-cyan-700"
                        />
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] leading-4">
                            <span className="max-w-full truncate font-semibold text-slate-800 dark:text-slate-100">{device.hostname || device.id}</span>
                            <span className="font-mono text-[10px] text-cyan-800 dark:text-cyan-200">{ip}</span>
                          </span>
                          {metadata && <span className="mt-0.5 block truncate text-[9px] leading-3.5 text-slate-500 dark:text-slate-400">{metadata}</span>}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-white px-4 py-3 dark:border-white/10 dark:bg-slate-900 sm:px-5">
                <span className="text-[10px] text-slate-500 dark:text-slate-400">
                  {language === 'zh' ? '确认后才会写入规则表单。' : 'Selections are applied to the rule only after confirmation.'}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={closeScopeDevicePicker}
                    className="rounded-lg border border-slate-200 px-3 py-2 text-[11px] font-medium text-slate-600 transition hover:bg-slate-50 dark:border-white/15 dark:text-slate-200 dark:hover:bg-white/[0.06]"
                  >
                    {language === 'zh' ? '取消' : 'Cancel'}
                  </button>
                  <button
                    type="button"
                    onClick={confirmScopeDeviceSelection}
                    disabled={Boolean(scopeDeviceSearchQuery.trim() && scopeDeviceSearchTotal > scopeDeviceCandidates.length)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-700 px-3.5 py-2 text-[11px] font-semibold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <Check size={13} />
                    {language === 'zh' ? `确认选择 · ${pendingScopeDeviceIds.length} 台` : `Confirm · ${pendingScopeDeviceIds.length}`}
                  </button>
                </div>
              </footer>
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ---------- Delete Approval Modal ---------- */}
      <AnimatePresence>
        {deleteApprovalOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/45 backdrop-blur-sm"
          >
            <div className="fixed inset-0" onClick={() => setDeleteApprovalOpen(false)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="relative w-full max-w-md rounded-2xl bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-2xl overflow-hidden z-10"
              onClick={e => e.stopPropagation()}
            >
              <div className="bg-rose-50 border-b border-rose-100 px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-2.5 text-rose-700">
                  <Shield className="w-5 h-5 text-rose-600" />
                  <h3 className="font-bold text-sm">{language === 'zh' ? '删除安全校验与工单授权' : 'Delete Security Verification'}</h3>
                </div>
                <button onClick={() => setDeleteApprovalOpen(false)} className="text-rose-400 hover:text-rose-600 p-1">
                  <X size={16} />
                </button>
              </div>

              <div className="p-6 space-y-4 text-xs text-slate-600">
                <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 space-y-1">
                  <span className="text-[10px] text-slate-400 font-semibold">{language === 'zh' ? '即将永久删除规则' : 'Target Rule(s) to Delete'}</span>
                  <div className="font-bold text-slate-800 text-sm truncate">{deleteTargetNames}</div>
                </div>

                <div className="flex items-center justify-between pb-2 border-b border-slate-100">
                  <span className="font-bold text-slate-700">{language === 'zh' ? '跳过审批流程' : 'Skip Approval'}</span>
                  {isProduction ? (
                    <span className="text-xs text-rose-500 font-bold bg-rose-50 px-2.5 py-1 rounded-lg border border-rose-100 shadow-sm">
                      {language === 'zh' ? '生产环境 强制校验' : 'Production Enforced Check'}
                    </span>
                  ) : (
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={skipApproval}
                        onChange={(e) => {
                          setSkipApproval(e.target.checked);
                          setDeleteStatus('idle');
                          setDeleteCode('');
                          setDeleteError('');
                        }}
                        className="rounded border-slate-300 text-rose-600 focus:ring-rose-500"
                      />
                      <span className="ml-2 text-slate-500">{language === 'zh' ? '仅测试/开发环境' : 'Dev/Test only'}</span>
                    </label>
                  )}
                </div>

                {!skipApproval && deleteStatus !== 'verified' && (
                  <>
                    <div className="space-y-1.5">
                      <label className="font-bold text-slate-700 block">{language === 'zh' ? '删除原因说明' : 'Deletion Reason'}</label>
                      <input
                        type="text"
                        value={deleteReason}
                        onChange={e => setDeleteReason(e.target.value)}
                        placeholder={language === 'zh' ? '输入删除原因...' : 'Enter reason...'}
                        className="w-full px-3 py-2 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="font-bold text-slate-700 block">{language === 'zh' ? '选择授权审批人' : 'Select Approver'}</label>
                      <div className="flex items-center gap-2">
                        <select
                          value={deleteApprover}
                          onChange={e => setDeleteApprover(e.target.value)}
                          disabled={deleteStatus === 'sending' || deleteStatus === 'sent'}
                          className="flex-1 px-3 py-2 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                        >
                          <option value="">{language === 'zh' ? '选择审批人...' : 'Select approver...'}</option>
                          {approvers.map(u => (
                            <option key={u.id} value={u.username}>{u.username} ({u.role})</option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={requestDeleteApproval}
                          disabled={!deleteApprover || !deleteReason.trim() || deleteStatus === 'sending' || (deleteStatus === 'sent' && deleteCountdown > 0)}
                          className={`px-3 py-2 rounded-xl font-bold whitespace-nowrap transition-all flex items-center gap-1 ${
                            deleteApprover && deleteReason.trim() && !(deleteStatus === 'sent' && deleteCountdown > 0)
                              ? 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm'
                              : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                          }`}
                        >
                          {deleteStatus === 'sending' ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : deleteStatus === 'sent' && deleteCountdown > 0 ? (
                            `${Math.floor(deleteCountdown / 60)}:${String(deleteCountdown % 60).padStart(2, '0')}`
                          ) : (
                            language === 'zh' ? '发验证码' : 'Send Code'
                          )}
                        </button>
                      </div>
                    </div>

                    {deleteStatus === 'sent' && (
                      <div className="space-y-1.5 pt-2 border-t border-slate-100">
                        <label className="text-[11px] text-slate-500 block">{language === 'zh' ? '输入 6 位工单验证码' : 'Enter 6-digit verification code'}</label>
                        <div className="flex items-center gap-2">
                          <input
                            value={deleteCode}
                            onChange={e => { setDeleteCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setDeleteError(''); }}
                            placeholder="000000"
                            maxLength={6}
                            className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-slate-200 py-2 text-sm outline-none focus:border-rose-500 transition-all"
                          />
                          <button
                            type="button"
                            onClick={verifyDeleteApproval}
                            disabled={deleteCode.length !== 6}
                            className={`px-4 py-2 rounded-xl font-bold transition-all ${deleteCode.length === 6 ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-slate-100 text-slate-400 cursor-not-allowed'}`}
                          >
                            {language === 'zh' ? '验证' : 'Verify'}
                          </button>
                        </div>
                      </div>
                    )}

                    {deleteError && (
                      <div className="flex items-center gap-1.5 text-rose-600 text-xs pt-1">
                        <span>⚠️</span>
                        <span>{deleteError}</span>
                      </div>
                    )}
                  </>
                )}

                {(skipApproval || deleteStatus === 'verified') && (
                  <div className="px-4 py-3 bg-emerald-50 border border-emerald-100 rounded-xl text-emerald-800 text-xs font-semibold flex items-center gap-2">
                    <Check size={14} className="text-emerald-600" />
                    {language === 'zh' ? '删除已获得安全授权，可执行永久删除。' : 'Deletion authorized. Safe to execute deletion.'}
                  </div>
                )}
              </div>

              <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDeleteApprovalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-slate-200 font-semibold text-slate-600 hover:bg-slate-100 transition-all"
                >
                  {language === 'zh' ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={executeDelete}
                  disabled={!skipApproval && deleteStatus !== 'verified'}
                  className="px-4 py-2 rounded-xl bg-rose-600 text-white font-bold hover:bg-rose-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-md shadow-rose-600/10"
                >
                  {language === 'zh' ? '确认安全删除' : 'Secure Delete'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

export default AlertRulesTab;
