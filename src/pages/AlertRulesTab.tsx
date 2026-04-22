import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, ChevronRight, Copy, Edit3, Plus, Power, PowerOff, RefreshCw, Save, Trash2, X, Search } from 'lucide-react';
import type { AlertRuleHistoryItem, AlertRuleListResponse, AlertRulePreview, AlertRuleSettings } from '../types';
import Pagination from '../components/Pagination';
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

const AlertRulesTab: React.FC<AlertPageCommonProps> = ({ language, currentUsername, showToast }) => {
  const thresholdMetrics = new Set<AlertRuleSettings['metric_type']>(['cpu', 'memory', 'interface_util', 'temperature_high', 'interface_error_rate_high', 'host_cpu', 'host_memory', 'host_disk']);

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
        return 'major';
      case 'fan_failure':
      case 'power_supply_failure':
      case 'bgp_neighbor_down':
      case 'ospf_neighbor_down':
      case 'bfd_session_down':
      case 'ping_unreachable':
        return 'critical';
      default:
        return 'major';
    }
  };

  const defaultThresholdForMetric = (metricType: AlertRuleSettings['metric_type']) => {
    switch (metricType) {
      case 'temperature_high':
      case 'host_cpu':
        return 75;
      case 'interface_error_rate_high':
        return 2;
      case 'host_memory':
      case 'host_disk':
        return 80;
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
  const [ruleDraft, setRuleDraft] = useState<AlertRuleSettings | null>(null);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());
  const [previewData, setPreviewData] = useState<AlertRulePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [ruleHistory, setRuleHistory] = useState<AlertRuleHistoryItem[]>([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  const loadAlertRules = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        search,
        enabled: enabledFilter,
      });
      if (metricFilter !== 'all') {
        params.set('metric_type', metricFilter);
      }
      const resp = await fetch(`/api/alerts/rules?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed to load alert rules');
      const data: AlertRuleListResponse = await resp.json();
      const items = data.items || [];
      setAlertRules(items);
      setTotal(data.total || 0);
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
  }, [page, pageSize, search, enabledFilter, metricFilter]);

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
  };

  /* ---------- Preview: alert stats overview ---------- */
  const fetchPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const resp = await fetch('/api/alerts/rules/preview');
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
      const resp = await fetch(`/api/alerts/rules/history?rule_id=${encodeURIComponent(ruleId)}`);
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
    setSaving(true);
    try {
      const isCreate = !editingRuleId;
      const resp = await fetch(isCreate ? '/api/alerts/rules' : `/api/alerts/rules/${editingRuleId}`, {
        method: isCreate ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...ruleDraft,
          created_by: ruleDraft.created_by || currentUsername,
          updated_by: currentUsername,
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

  const handleDelete = async () => {
    if (!editingRuleId) return;
    setSaving(true);
    try {
      const resp = await fetch(`/api/alerts/rules/${editingRuleId}?actor_username=${encodeURIComponent(currentUsername)}`, {
        method: 'DELETE',
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to delete alert rule');
      showToast(language === 'zh' ? '告警规则已删除' : 'Alert rule deleted', 'success');
      closeEditor();
      await loadAlertRules();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '删除告警规则失败' : 'Failed to delete alert rule'), 'error');
    } finally {
      setSaving(false);
    }
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
    setTogglingIds((prev) => new Set(prev).add(ruleId));
    try {
      const resp = await fetch('/api/alerts/rules/batch-toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_ids: [ruleId], enabled: !rule.enabled, actor_username: currentUsername }),
      });
      if (!resp.ok) throw new Error('Failed to toggle rule');
      setAlertRules((prev) => prev.map((r) => r.id === ruleId ? { ...r, enabled: !r.enabled } : r));
    } catch {
      showToast(language === 'zh' ? '切换规则状态失败' : 'Failed to toggle rule', 'error');
    } finally {
      setTogglingIds((prev) => { const next = new Set(prev); next.delete(ruleId); return next; });
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

  const handleInlineDelete = async (rule: AlertRuleSettings) => {
    if (!rule.id) return;
    const msg = language === 'zh' ? `确定删除规则「${rule.name}」？` : `Delete rule "${rule.name}"?`;
    if (!window.confirm(msg)) return;
    try {
      const resp = await fetch(`/api/alerts/rules/${rule.id}?actor_username=${encodeURIComponent(currentUsername)}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('Failed to delete');
      showToast(language === 'zh' ? '告警规则已删除' : 'Alert rule deleted', 'success');
      await loadAlertRules();
    } catch {
      showToast(language === 'zh' ? '删除告警规则失败' : 'Failed to delete alert rule', 'error');
    }
  };

  const handleBatchToggle = async (enabled: boolean) => {
    if (selectedIds.size === 0) return;
    try {
      const resp = await fetch('/api/alerts/rules/batch-toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_ids: Array.from(selectedIds), enabled, actor_username: currentUsername }),
      });
      if (!resp.ok) throw new Error('Failed to batch toggle');
      const data = await resp.json();
      showToast(language === 'zh' ? `已${enabled ? '启用' : '停用'} ${data.updated_count} 条规则` : `${enabled ? 'Enabled' : 'Disabled'} ${data.updated_count} rules`, 'success');
      setSelectedIds(new Set());
      await loadAlertRules();
    } catch {
      showToast(language === 'zh' ? '批量操作失败' : 'Batch operation failed', 'error');
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    const msg = language === 'zh' ? `确定删除选中的 ${selectedIds.size} 条规则？` : `Delete ${selectedIds.size} selected rules?`;
    if (!window.confirm(msg)) return;
    try {
      const resp = await fetch('/api/alerts/rules/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_ids: Array.from(selectedIds), actor_username: currentUsername }),
      });
      if (!resp.ok) throw new Error('Failed to batch delete');
      const data = await resp.json();
      showToast(language === 'zh' ? `已删除 ${data.deleted_count} 条规则` : `Deleted ${data.deleted_count} rules`, 'success');
      setSelectedIds(new Set());
      await loadAlertRules();
    } catch {
      showToast(language === 'zh' ? '批量删除失败' : 'Batch delete failed', 'error');
    }
  };

  const allSelected = alertRules.length > 0 && alertRules.every((r) => r.id && selectedIds.has(r.id));
  const someSelected = selectedIds.size > 0;

  return (
    <div className="space-y-4">
      <div className={alertPanelClass}>
        <div className="flex flex-col gap-4 border-b border-black/5 px-5 py-5 lg:flex-row lg:items-end lg:justify-between bg-[linear-gradient(to_right,#f4fbfc_0%,#ffffff_100%)] rounded-t-[28px]">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">
              {language === 'zh' ? '告警中心 / 告警规则' : 'Alert Center / Alert Rules'}
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-[#164e63]">
              {language === 'zh' ? '当前规则' : 'Current Rules'}
            </h2>
            <p className="mt-2 text-sm text-black/50">
              {language === 'zh' ? '灵活配置多维度监控指标的触发阈值，精细管理全生命周期的告警策略。' : 'Configure multi-dimensional trigger thresholds and manage full-lifecycle alerting policies.'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => void loadAlertRules()} className={alertSecondaryButtonClass}>
              <RefreshCw size={14} />
              {language === 'zh' ? '刷新' : 'Refresh'}
            </button>
            <button onClick={openCreate} className={alertPrimaryButtonClass}>
              <Plus size={14} />
              {language === 'zh' ? '新增规则' : 'New Rule'}
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
            <option value="cpu">{metricTypeLabel('cpu', language)}</option>
            <option value="memory">{metricTypeLabel('memory', language)}</option>
            <option value="interface_util">{metricTypeLabel('interface_util', language)}</option>
            <option value="interface_down">{metricTypeLabel('interface_down', language)}</option>
            <option value="interconnect_down">{metricTypeLabel('interconnect_down', language)}</option>
            <option value="snmp_unreachable">{metricTypeLabel('snmp_unreachable', language)}</option>
            <option value="lldp_neighbor_lost">{metricTypeLabel('lldp_neighbor_lost', language)}</option>
            <option value="temperature_high">{metricTypeLabel('temperature_high', language)}</option>
            <option value="fan_failure">{metricTypeLabel('fan_failure', language)}</option>
            <option value="power_supply_failure">{metricTypeLabel('power_supply_failure', language)}</option>
            <option value="interface_error_rate_high">{metricTypeLabel('interface_error_rate_high', language)}</option>
            <option value="interface_flap">{metricTypeLabel('interface_flap', language)}</option>
            <option value="bgp_neighbor_down">{metricTypeLabel('bgp_neighbor_down', language)}</option>
            <option value="ospf_neighbor_down">{metricTypeLabel('ospf_neighbor_down', language)}</option>
            <option value="bfd_session_down">{metricTypeLabel('bfd_session_down', language)}</option>
            <option value="ping_unreachable">{metricTypeLabel('ping_unreachable', language)}</option>
            <option disabled>─── {language === 'zh' ? '宿主机' : 'Host'} ───</option>
            <option value="host_cpu">{metricTypeLabel('host_cpu', language)}</option>
            <option value="host_memory">{metricTypeLabel('host_memory', language)}</option>
            <option value="host_disk">{metricTypeLabel('host_disk', language)}</option>
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

        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left">
            <thead>
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
                      <div>
                        <p className="text-sm font-semibold text-[#164e63]">{rule.name}</p>
                        <p className="mt-1 text-xs text-black/40">{rule.id}</p>
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

      <AnimatePresence>
        {ruleDraft ? (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
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
              className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-3xl bg-white shadow-2xl"
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
                    <select value={ruleDraft.metric_type} onChange={(e) => updateRuleField('metric_type', e.target.value as AlertRuleSettings['metric_type'])} className="mt-2 w-full rounded-xl border border-black/10 px-3 py-2 text-[#164e63] outline-none">
                      <option value="cpu">{metricTypeLabel('cpu', language)}</option>
                      <option value="memory">{metricTypeLabel('memory', language)}</option>
                      <option value="interface_util">{metricTypeLabel('interface_util', language)}</option>
                      <option value="interface_down">{metricTypeLabel('interface_down', language)}</option>
                      <option value="interconnect_down">{metricTypeLabel('interconnect_down', language)}</option>
                      <option value="snmp_unreachable">{metricTypeLabel('snmp_unreachable', language)}</option>
                      <option value="lldp_neighbor_lost">{metricTypeLabel('lldp_neighbor_lost', language)}</option>
                      <option value="temperature_high">{metricTypeLabel('temperature_high', language)}</option>
                      <option value="fan_failure">{metricTypeLabel('fan_failure', language)}</option>
                      <option value="power_supply_failure">{metricTypeLabel('power_supply_failure', language)}</option>
                      <option value="interface_error_rate_high">{metricTypeLabel('interface_error_rate_high', language)}</option>
                      <option value="interface_flap">{metricTypeLabel('interface_flap', language)}</option>
                      <option value="bgp_neighbor_down">{metricTypeLabel('bgp_neighbor_down', language)}</option>
                      <option value="ospf_neighbor_down">{metricTypeLabel('ospf_neighbor_down', language)}</option>
                      <option value="bfd_session_down">{metricTypeLabel('bfd_session_down', language)}</option>
                      <option value="ping_unreachable">{metricTypeLabel('ping_unreachable', language)}</option>
                      <option disabled>─── {language === 'zh' ? '宿主机' : 'Host'} ───</option>
                      <option value="host_cpu">{metricTypeLabel('host_cpu', language)}</option>
                      <option value="host_memory">{metricTypeLabel('host_memory', language)}</option>
                      <option value="host_disk">{metricTypeLabel('host_disk', language)}</option>
                    </select>
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
                    <button onClick={() => void handleDelete()} className={alertDangerButtonClass}>
                      <Trash2 size={14} />
                      {language === 'zh' ? '删除' : 'Delete'}
                    </button>
                  ) : null}
                  <button disabled={saving || !isDirty} onClick={() => void handleSave()} className={alertPrimaryButtonClass}>
                    <Save size={14} />
                    {saving ? (language === 'zh' ? '保存中...' : 'Saving...') : (language === 'zh' ? '保存' : 'Save')}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
};

export default AlertRulesTab;
