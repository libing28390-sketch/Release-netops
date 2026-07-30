import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, ChevronRight, Copy, Edit3, Plus, Power, PowerOff, RefreshCw, Save, SlidersHorizontal, Trash2, X, Search, Check, Shield } from 'lucide-react';
import type { AlertRuleHistoryItem, AlertRuleListResponse, AlertRulePreview, AlertRuleSettings } from '../types';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
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
  formatTs,
  metricTypeLabel,
  scopeMatchModeLabel,
  scopeTypeLabel,
  severityLabel,
  useAlertOverlayDismiss,
} from './alertManagementShared';

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
  const [ruleDraft, setRuleDraft] = useState<AlertRuleSettings | null>(null);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());
  const [previewData, setPreviewData] = useState<AlertRulePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
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

  const loadAlertRules = async () => {
    setLoading(true);
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
      if (!resp.ok) throw new Error('Failed to load alert rules');
      const data: AlertRuleListResponse & { category_counts?: Record<string, number> } = await resp.json();
      const items = data.items || [];
      setAlertRules(items);
      setTotal(data.total && data.total > 0 ? data.total : items.length);
      if (data.category_counts) {
        setCategoryCounts(data.category_counts);
      }
      setSelectedIds(new Set());
      if (editingRuleId && !items.some((item) => item.id === editingRuleId)) {
        setEditingRuleId(null);
        setRuleDraft(null);
      }
    } catch (error) {
      console.error(error);
      showToast(language === 'zh' ? '加载告警规则失败' : 'Failed to load alert rules', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAlertRules();
  }, [page, pageSize, search, enabledFilter, metricFilter, categoryFilter]);

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

  const openCreate = () => {
    setEditingRuleId(null);
    setRuleDraft(buildEmptyRule(currentUsername));
  };

  const openEdit = (rule: AlertRuleSettings) => {
    setEditingRuleId(rule.id || null);
    setRuleDraft({ ...rule });
    setHistoryExpanded(false);
    setPreviewData(null);
    setRuleHistory([]);
  };

  const closeEditor = () => {
    setEditingRuleId(null);
    setRuleDraft(null);
    setPreviewData(null);
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

  /* ---------- Preview: alert stats overview ---------- */
  const fetchPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const resp = await fetch('/api/alerts/rules/preview', {
        headers: getHeaders(false),
      });
      if (resp.ok) {
        setPreviewData(await resp.json());
      }
    } catch { /* silent */ } finally {
      setPreviewLoading(false);
    }
  }, []);

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

  /* Fetch preview + history when modal opens */
  useEffect(() => {
    if (!ruleDraft) return;
    void fetchPreview();
  }, [ruleDraft?.metric_type]);

  useEffect(() => {
    if (editingRuleId) {
      void fetchHistory(editingRuleId);
    }
  }, [editingRuleId]);

  useAlertOverlayDismiss(Boolean(ruleDraft), closeEditor);

  const originalRule = useMemo(
    () => alertRules.find((item) => item.id === editingRuleId) || null,
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
    setRuleDraft((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [key]: value } as AlertRuleSettings;
      if (key === 'metric_type') {
        const metricValue = value as AlertRuleSettings['metric_type'];
        next.threshold = thresholdMetrics.has(metricValue) ? defaultThresholdForMetric(metricValue) : null;
        next.severity = defaultSeverityForMetric(metricValue);
      }
      if (key === 'scope_type' && value === 'global') {
        next.scope_value = '';
        next.scope_match_mode = 'exact';
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!ruleDraft) return;
    if (!skipApproval && approvalStatus !== 'verified') {
      showToast(language === 'zh' ? '请先完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    setSaving(true);
    try {
      const isCreate = !editingRuleId;
      const resp = await fetch(isCreate ? '/api/alerts/rules' : `/api/alerts/rules/${editingRuleId}`, {
        method: isCreate ? 'POST' : 'PUT',
        headers: getHeaders(true),
        body: JSON.stringify({
          ...ruleDraft,
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
    const cloned: AlertRuleSettings = {
      ...rule,
      id: undefined,
      name: `${rule.name} (${language === 'zh' ? '副本' : 'Copy'})`,
      created_by: currentUsername,
      updated_by: currentUsername,
      created_at: undefined,
      updated_at: undefined,
    };
    setEditingRuleId(null);
    setRuleDraft(cloned);
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
            <button onClick={() => void handleBatchDelete()} className={alertDangerButtonClass + ' !h-9 !text-xs'}>
              <Trash2 size={13} />
              {language === 'zh' ? '批量删除' : 'Delete'}
            </button>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-xs text-black/40 hover:text-black/60">
              {language === 'zh' ? '取消选择' : 'Clear'}
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          <table className="nx-data-table text-left">
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
                <th className="px-5 py-3">{language === 'zh' ? '规则名称' : 'Rule'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '监控类型' : 'Metric'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '范围' : 'Scope'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '阈值' : 'Threshold'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '级别' : 'Severity'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '状态' : 'Status'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '更新时间' : 'Updated'} </th>
                <th className="px-5 py-3">{language === 'zh' ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '正在加载规则...' : 'Loading rules...'}
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
                          <button
                            onClick={(e) => { e.stopPropagation(); copyToClipboard(rule.name, `${rule.id}-name`); }}
                            className={`opacity-0 group-hover/copy-name:opacity-100 transition-opacity p-0.5 rounded hover:bg-black/5 ${copiedId === `${rule.id}-name` ? 'opacity-100' : ''}`}
                            title={language === 'zh' ? '复制名称' : 'Copy Name'}
                          >
                            {copiedId === `${rule.id}-name` ? <Check size={11} className="text-green-500" /> : <Copy size={11} className="text-black/30" />}
                          </button>
                        </div>
                        <div className="mt-1 flex items-center gap-1.5 group/copy-id">
                          <p className="text-[10px] font-mono text-black/30">{rule.id}</p>
                          <button
                            onClick={(e) => { e.stopPropagation(); copyToClipboard(rule.id || '', `${rule.id}-id`); }}
                            className={`opacity-0 group-hover/copy-id:opacity-100 transition-opacity p-0.5 rounded hover:bg-black/5 ${copiedId === `${rule.id}-id` ? 'opacity-100' : ''}`}
                            title={language === 'zh' ? '复制 ID' : 'Copy ID'}
                          >
                            {copiedId === `${rule.id}-id` ? <Check size={9} className="text-green-500" /> : <Copy size={9} className="text-black/20" />}
                          </button>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{metricTypeLabel(rule.metric_type, language)}</td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {scopeTypeLabel(rule.scope_type, language)}
                      {rule.scope_value ? ` / ${rule.scope_value}` : ''}
                    </td>
                    <td className="px-5 py-4 align-top text-sm">
                      {rule.threshold != null ? (
                        <span className="font-mono text-black/70">&gt;&nbsp;{rule.threshold}%</span>
                      ) : (
                        <span className="inline-flex rounded-full bg-black/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-black/40">
                          {language === 'zh' ? '状态型' : 'State'}
                        </span>
                      )}
                      {rule.for_duration_seconds > 0 && (
                        <span className="ml-1.5 text-[10px] text-black/35" title={language === 'zh' ? '持续时间' : 'Duration'}>
                          {rule.for_duration_seconds >= 60 ? `${Math.floor(rule.for_duration_seconds / 60)}m` : `${rule.for_duration_seconds}s`}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-bold uppercase ${severityBadgeClass(rule.severity)}`}>
                        {severityLabel(rule.severity, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top">
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
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{formatTs(rule.updated_at || rule.created_at)}</td>
                    <td className="px-5 py-4 align-top">
                      <div className="flex items-center gap-1">
                        <button
                          title={language === 'zh' ? '编辑' : 'Edit'}
                          onClick={() => openEdit(rule)}
                          className={alertTableActionButtonClass}
                        >
                          <Edit3 size={13} />
                        </button>
                        <button
                          title={language === 'zh' ? '复制规则' : 'Clone rule'}
                          onClick={() => handleCloneRule(rule)}
                          className={alertTableActionButtonClass}
                        >
                          <Copy size={13} />
                        </button>
                        <button
                          title={language === 'zh' ? '删除' : 'Delete'}
                          onClick={() => void handleInlineDelete(rule)}
                          className={alertTableActionDangerButtonClass}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '当前没有规则。' : 'No rules found.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
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
                        {METRIC_OPTIONS_LIST.filter(m => m.category === 'network').map(m => (
                          <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                        ))}
                      </optgroup>
                      <optgroup label={language === 'zh' ? '宿主机' : 'Host'}>
                        {METRIC_OPTIONS_LIST.filter(m => m.category === 'host').map(m => (
                          <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                        ))}
                      </optgroup>
                      <optgroup label={language === 'zh' ? '服务器' : 'Server'}>
                        {METRIC_OPTIONS_LIST.filter(m => m.category === 'server').map(m => (
                          <option key={m.value} value={m.value}>{language === 'zh' ? m.labelZh : m.labelEn}</option>
                        ))}
                      </optgroup>
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

                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '作用范围' : 'Scope'}</span>
                    <select value={ruleDraft.scope_type} onChange={(e) => updateRuleField('scope_type', e.target.value as AlertRuleSettings['scope_type'])} className="mt-2 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none">
                      <option value="global">{scopeTypeLabel('global', language)}</option>
                      <option value="site">{scopeTypeLabel('site', language)}</option>
                      <option value="device">{scopeTypeLabel('device', language)}</option>
                      <option value="interface">{scopeTypeLabel('interface', language)}</option>
                    </select>
                  </label>
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '匹配方式' : 'Match Mode'}</span>
                    <select value={ruleDraft.scope_match_mode} onChange={(e) => updateRuleField('scope_match_mode', e.target.value as AlertRuleSettings['scope_match_mode'])} disabled={ruleDraft.scope_type === 'global'} className="mt-2 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none disabled:bg-black/[0.03]">
                      <option value="exact">{scopeMatchModeLabel('exact', language)}</option>
                      <option value="contains">{scopeMatchModeLabel('contains', language)}</option>
                      <option value="prefix">{scopeMatchModeLabel('prefix', language)}</option>
                      <option value="glob">{scopeMatchModeLabel('glob', language)}</option>
                    </select>
                  </label>
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '范围值' : 'Scope Value'}</span>
                    <input value={ruleDraft.scope_value} onChange={(e) => updateRuleField('scope_value', e.target.value)} disabled={ruleDraft.scope_type === 'global'} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2 disabled:bg-black/[0.03]`} />
                  </label>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
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
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '持续时间(秒)' : 'Duration (sec)'}</span>
                    <input type="number" min="0" max="3600" value={ruleDraft.for_duration_seconds} onChange={(e) => updateRuleField('for_duration_seconds', Number(e.target.value))} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2`} placeholder={language === 'zh' ? '0=立即触发' : '0=immediate'} />
                  </label>
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '重复通知窗口(秒)' : 'Quiet Window (sec)'}</span>
                    <input type="number" min="0" max="86400" value={ruleDraft.notification_repeat_window_seconds} onChange={(e) => updateRuleField('notification_repeat_window_seconds', Number(e.target.value))} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2`} />
                  </label>
                </div>

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

                {/* ---------- Preview: 24h alert stats ---------- */}
                {previewData && (
                  <div className="rounded-2xl border border-blue-100 bg-blue-50/50 px-4 py-3 text-sm text-blue-800">
                    <div className="flex flex-wrap gap-4">
                      <span>
                        <span className="font-semibold">{previewData.alerts_24h}</span>{' '}
                        {language === 'zh' ? '条告警 (24h)' : 'alerts (24h)'}
                      </span>
                      <span>
                        <span className="font-semibold">{previewData.resolved_24h}</span>{' '}
                        {language === 'zh' ? '已恢复' : 'resolved'}
                      </span>
                      {previewData.repeated_key_count > 0 && (
                        <span className="text-amber-700">
                          <span className="font-semibold">{previewData.repeated_key_count}</span>{' '}
                          {language === 'zh' ? '重复键' : 'repeated keys'}
                        </span>
                      )}
                    </div>
                    {previewLoading && <span className="ml-2 text-xs text-blue-400">…</span>}
                  </div>
                )}

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
                    <button onClick={handleDelete} className={alertDangerButtonClass}>
                      <Trash2 size={14} />
                      {language === 'zh' ? '删除' : 'Delete'}
                    </button>
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
