import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Activity, AlertTriangle, Bell, CheckCircle2, CheckSquare, Clock, Download, Eye, ExternalLink, MapPin, Network, RefreshCw, Repeat, Search, Square, UserCheck, Wrench, X } from 'lucide-react';
import * as XLSX from 'xlsx';
import type { AlertDetailResponse, AlertListResponse, AlertRecord } from '../types';
import Pagination from '../components/Pagination';
import { DataTable } from '../components/DataTable';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import { alertWorkflowBadgeClass, severityBadgeClass } from '../components/shared';
import { fetchAllPaginatedItems } from '../utils/pagination';
import {
  alertInputClass,
  alertPanelClass,
  alertSecondaryButtonClass,
  alertTableActionButtonClass,
  AlertPageCommonProps,
  formatDuration,
  formatTs,
  severityLabel,
  useAlertOverlayDismiss,
  workflowLabel,
} from './alertManagementShared';

interface AlertDeskTabProps extends AlertPageCommonProps {
  onOpenMaintenanceForAlert?: (alert: AlertRecord | null) => void;
  onNavigateToDevice?: (deviceId: string) => void;
  onNavigateToTopology?: (deviceId: string) => void;
}

interface AlertActivityItem {
  id: string;
  event_type: string;
  from_state?: string | null;
  to_state?: string | null;
  actor_id?: string | null;
  created_at: string;
  metadata?: Record<string, unknown>;
}

const AlertDeskTab: React.FC<AlertDeskTabProps> = ({ language, currentUsername, showToast, onOpenMaintenanceForAlert, onNavigateToDevice, onNavigateToTopology }) => {
  const [rows, setRows] = useState<AlertRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState('open');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<AlertDetailResponse | null>(null);
  const [activity, setActivity] = useState<AlertActivityItem[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailNote, setDetailNote] = useState('');
  const [assignValue, setAssignValue] = useState('');
  const [actionLoading, setActionLoading] = useState<'ack' | 'assign' | 'note' | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});
  const [autoRefresh, setAutoRefresh] = useState(false);

  const loadAlerts = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        status: statusFilter,
        severity: severityFilter,
        site: 'all',
        assignee: 'all',
        search,
      });
      const resp = await fetch(`/api/alerts?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed to load alerts');
      const data: AlertListResponse = await resp.json();
      const items = data.items || [];
      setRows(items);
      setTotal(data.total && data.total > 0 ? data.total : items.length);
      if (data.status_counts) setStatusCounts(data.status_counts);
      setSelectedIds(new Set());
      if (selectedAlertId && !items.some((item) => item.id === selectedAlertId)) {
        setSelectedAlertId(null);
        setSelectedDetail(null);
      }
    } catch (error) {
      console.error(error);
      showToast(language === 'zh' ? '加载告警列表失败' : 'Failed to load alerts', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (alertId: string) => {
    setDetailLoading(true);
    try {
      const resp = await fetch(`/api/alerts/${alertId}`);
      if (!resp.ok) throw new Error('Failed to load alert detail');
      const data: AlertDetailResponse = await resp.json();
      setSelectedDetail(data);
      setDetailNote(data.item.note || '');
      setAssignValue(data.item.assignee || currentUsername || '');
    } catch (error) {
      console.error(error);
      showToast(language === 'zh' ? '加载告警详情失败' : 'Failed to load alert detail', 'error');
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    void loadAlerts();
  }, [page, pageSize, search, severityFilter, statusFilter]);

  useEffect(() => {
    if (!selectedAlertId) return;
    void loadDetail(selectedAlertId);
    setActivityLoading(true);
    fetch(`/api/alerts/${encodeURIComponent(selectedAlertId)}/activity?limit=100`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((payload: { items?: AlertActivityItem[] }) => setActivity(Array.isArray(payload.items) ? payload.items : []))
      .catch(() => setActivity([]))
      .finally(() => setActivityLoading(false));
  }, [selectedAlertId]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(() => { void loadAlerts(); }, 30000);
    return () => clearInterval(timer);
  }, [autoRefresh, page, pageSize, search, severityFilter, statusFilter]);

  const closeDetail = () => {
    setSelectedAlertId(null);
    setSelectedDetail(null);
    setActivity([]);
  };

  useAlertOverlayDismiss(Boolean(selectedAlertId), closeDetail);

  const refreshAll = async () => {
    await loadAlerts();
    if (selectedAlertId) {
      await loadDetail(selectedAlertId);
    }
  };

  const handleAck = async (nextStatus: 'acknowledged' | 'investigating') => {
    if (!selectedDetail?.item) return;
    setActionLoading('ack');
    try {
      const resp = await fetch(`/api/alerts/${selectedDetail.item.id}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_username: currentUsername, status: nextStatus }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to acknowledge alert');
      showToast(language === 'zh' ? '告警状态已更新' : 'Alert status updated', 'success');
      closeDetail();
      await loadAlerts();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '更新告警状态失败' : 'Failed to update alert status'), 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const handleAssign = async () => {
    if (!selectedDetail?.item || !assignValue.trim()) return;
    setActionLoading('assign');
    try {
      const resp = await fetch(`/api/alerts/${selectedDetail.item.id}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_username: currentUsername, assignee: assignValue.trim() }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to assign alert');
      showToast(language === 'zh' ? '告警已分派' : 'Alert assigned', 'success');
      await refreshAll();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '分派告警失败' : 'Failed to assign alert'), 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const handleSaveNote = async () => {
    if (!selectedDetail?.item) return;
    setActionLoading('note');
    try {
      const resp = await fetch(`/api/alerts/${selectedDetail.item.id}/note`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_username: currentUsername, note: detailNote }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to update note');
      showToast(language === 'zh' ? '处置备注已保存' : 'Alert note saved', 'success');
      await refreshAll();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '保存备注失败' : 'Failed to save note'), 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const selectedItem = selectedDetail?.item || null;

  const handleExportAlerts = async () => {
    const params = new URLSearchParams({
      status: statusFilter,
      severity: severityFilter,
      site: 'all',
      assignee: 'all',
      search,
    });

    try {
      const allAlerts = await fetchAllPaginatedItems<AlertRecord>('/api/alerts', params);
      if (allAlerts.length === 0) return;
      const exportData = allAlerts.map(r => ({
        Title: r.title,
        Severity: r.severity,
        Status: r.workflow_status,
        Hostname: r.hostname || '',
        IP: r.ip_address || '',
        Interface: r.interface_name || '',
        Site: r.site || '',
        Assignee: r.assignee || '',
        'Ack By': r.ack_by || '',
        Occurrences: r.occurrence_count ?? 1,
        'Created At': r.created_at ? new Date(r.created_at).toLocaleString() : '',
        'Resolved At': r.resolved_at ? new Date(r.resolved_at).toLocaleString() : '',
        Message: r.message,
      }));
      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Alerts');
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      XLSX.writeFile(wb, `alerts_export_${ts}.xlsx`);
      showToast(language === 'zh' ? '导出成功' : 'Exported', 'success');
    } catch (error) {
      console.error('Failed to export alerts:', error);
      showToast(language === 'zh' ? '导出失败' : 'Export failed', 'error');
    }
  };

  const handleBatchAck = async (nextStatus: 'acknowledged' | 'investigating') => {
    if (selectedIds.size === 0) return;
    setActionLoading('ack');
    try {
      const resp = await fetch('/api/alerts/batch-ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alert_ids: Array.from(selectedIds), actor_username: currentUsername, status: nextStatus }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed');
      showToast(language === 'zh' ? `已批量确认 ${data.updated_count || 0} 条告警` : `Batch acknowledged ${data.updated_count || 0} alerts`, 'success');
      setSelectedIds(new Set());
      await loadAlerts();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '批量确认失败' : 'Batch acknowledge failed'), 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const handleBatchAssign = async () => {
    if (selectedIds.size === 0) return;
    setActionLoading('assign');
    try {
      const resp = await fetch('/api/alerts/batch-assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alert_ids: Array.from(selectedIds), actor_username: currentUsername, assignee: currentUsername }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed');
      showToast(language === 'zh' ? `已批量分派 ${data.updated_count || 0} 条告警` : `Batch assigned ${data.updated_count || 0} alerts`, 'success');
      setSelectedIds(new Set());
      await loadAlerts();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '批量分派失败' : 'Batch assign failed'), 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const handleInlineAck = async (alertId: string) => {
    try {
      const resp = await fetch(`/api/alerts/${alertId}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_username: currentUsername, status: 'acknowledged' }),
      });
      if (!resp.ok) throw new Error('Failed');
      showToast(language === 'zh' ? '告警已确认' : 'Alert acknowledged', 'success');
      await loadAlerts();
    } catch {
      showToast(language === 'zh' ? '确认失败' : 'Acknowledge failed', 'error');
    }
  };

  const handleInlineAssignToMe = async (alertId: string) => {
    try {
      const resp = await fetch(`/api/alerts/${alertId}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_username: currentUsername, assignee: currentUsername }),
      });
      if (!resp.ok) throw new Error('Failed');
      showToast(language === 'zh' ? '已分派给我' : 'Assigned to me', 'success');
      await loadAlerts();
    } catch {
      showToast(language === 'zh' ? '分派失败' : 'Assign failed', 'error');
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (rows.length > 0 && rows.every(r => selectedIds.has(r.id))) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(rows.map(r => r.id)));
    }
  };

  const STATUS_TABS: Array<{ value: string; zh: string; en: string }> = [
    { value: 'open', zh: '待处理', en: 'Open' },
    { value: 'acknowledged', zh: '已确认', en: 'Acknowledged' },
    { value: 'investigating', zh: '处理中', en: 'Investigating' },
    { value: 'suppressed', zh: '维护抑制', en: 'Suppressed' },
    { value: 'all_active', zh: '全部', en: 'All' },
  ];

  return (
    <>
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={Bell}
        eyebrow={language === 'zh' ? '告警中心 / 告警信息' : 'Alert Center / Alert Desk'}
        title={language === 'zh' ? '当前告警' : 'Current Alerts'}
        subtitle={language === 'zh' ? '实时监控全网设备与业务异常，快速进行故障确认、分派和处置。' : 'Real-time monitoring of network anomalies, facilitating quick triage and response.'}
        actions={
          <>
            <ActionButton icon={Download} variant="accent" size="md" onClick={handleExportAlerts} title={language === 'zh' ? '导出告警' : 'Export Alerts'}>
              {language === 'zh' ? '导出' : 'Export'}
            </ActionButton>
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`${alertSecondaryButtonClass} ${autoRefresh ? '!border-green-400 !bg-green-50 !text-green-700' : ''}`}
              title={language === 'zh' ? (autoRefresh ? '关闭自动刷新' : '开启自动刷新(30秒)') : (autoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh (30s)')}
            >
              <RefreshCw size={14} className={autoRefresh ? 'animate-spin' : ''} style={autoRefresh ? { animationDuration: '3s' } : undefined} />
              {language === 'zh' ? (autoRefresh ? '自动刷新中' : '自动刷新') : (autoRefresh ? 'Auto On' : 'Auto')}
            </button>
            <ActionButton icon={RefreshCw} variant="default" size="md" onClick={() => void loadAlerts()}>
              {language === 'zh' ? '刷新列表' : 'Refresh'}
            </ActionButton>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 min-h-0">
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center">
          <label className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/40" />
            <input
              value={search}
              onChange={(e) => {
                setPage(1);
                setSearch(e.target.value);
              }}
              placeholder={language === 'zh' ? '搜索标题、设备、接口、IP' : 'Search title, device, interface, IP'}
              className={`${alertInputClass} rounded-xl py-3 pl-9 pr-3`}
            />
          </label>

          <select
            title={language === 'zh' ? '按级别筛选告警' : 'Filter alerts by severity'}
            value={severityFilter}
            onChange={(e) => {
              setPage(1);
              setSeverityFilter(e.target.value);
            }}
            className="rounded-xl border border-black/10 bg-white px-3 py-3 text-sm text-[#164e63] outline-none"
          >
            <option value="all">{language === 'zh' ? '全部级别' : 'All Severity'}</option>
            <option value="critical">{severityLabel('critical', language)}</option>
            <option value="major">{severityLabel('major', language)}</option>
            <option value="warning">{severityLabel('warning', language)}</option>
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 border-b border-black/5 px-5 pb-3">
          {STATUS_TABS.map(tab => (
            <button
              key={tab.value}
              onClick={() => { setPage(1); setStatusFilter(tab.value); setSelectedIds(new Set()); }}
              className={`rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
                statusFilter === tab.value
                  ? 'bg-[#06b6d4] text-white shadow-sm'
                  : 'text-black/55 hover:bg-black/[0.04] hover:text-black/75'
              }`}
            >
              {language === 'zh' ? tab.zh : tab.en}
              {statusCounts[tab.value] != null && (
                <span className={`ml-1.5 inline-flex min-w-[18px] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                  statusFilter === tab.value ? 'bg-white/25 text-white' : 'bg-black/[0.06] text-black/45'
                }`}>
                  {statusCounts[tab.value]}
                </span>
              )}
            </button>
          ))}
        </div>

        {selectedIds.size > 0 && (
          <div className="flex items-center gap-3 border-b border-blue-100 bg-blue-50/60 px-5 py-3">
            <span className="text-sm font-medium text-[#164e63]">
              {language === 'zh' ? `已选 ${selectedIds.size} 条` : `${selectedIds.size} selected`}
            </span>
            <button onClick={() => void handleBatchAck('acknowledged')} className={alertTableActionButtonClass} disabled={actionLoading != null}>
              <CheckCircle2 size={14} />
              {language === 'zh' ? '批量确认' : 'Batch Ack'}
            </button>
            <button onClick={() => void handleBatchAssign()} className={alertTableActionButtonClass} disabled={actionLoading != null}>
              <UserCheck size={14} />
              {language === 'zh' ? '批量分派给我' : 'Assign to Me'}
            </button>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-sm text-black/40 hover:text-black/60">
              {language === 'zh' ? '取消选择' : 'Clear'}
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          <DataTable className="text-left">
            <thead className="sticky top-0 z-10">
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="w-10 px-3 py-3">
                  <button onClick={toggleSelectAll} className="text-black/40 hover:text-black/70" title={language === 'zh' ? '全选' : 'Select all'}>
                    {rows.length > 0 && rows.every(r => selectedIds.has(r.id)) ? <CheckSquare size={16} /> : <Square size={16} />}
                  </button>
                </th>
                <th className="px-5 py-3">{language === 'zh' ? '告警标题' : 'Alert'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '对象' : 'Object'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '级别' : 'Severity'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '状态' : 'Status'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '责任人' : 'Assignee'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '时间' : 'Time'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '正在加载告警...' : 'Loading alerts...'}
                  </td>
                </tr>
              ) : rows.length > 0 ? (
                rows.map((row) => (
                  <tr
                    key={row.id}
                    className={`border-b border-black/5 hover:bg-black/[0.02] ${
                      selectedIds.has(row.id) ? 'bg-blue-50/40' : ''
                    } ${(row.duration_seconds ?? 0) > 86400 && !row.resolved_at ? 'border-l-2 border-l-amber-400' : ''}`}
                  >
                    <td className="w-10 px-3 py-4 align-top">
                      <button onClick={() => toggleSelect(row.id)} className="text-black/40 hover:text-black/70">
                        {selectedIds.has(row.id) ? <CheckSquare size={16} /> : <Square size={16} />}
                      </button>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <button
                        onClick={() => setSelectedAlertId(row.id)}
                        className="text-left"
                        title={language === 'zh' ? `查看告警 ${row.title}` : `View alert ${row.title}`}
                      >
                        <p className="text-sm font-semibold text-[#164e63]">
                          {row.title}
                          {(row.occurrence_count ?? 1) > 1 && (
                            <span className="ml-1.5 inline-flex items-center gap-0.5 rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-bold text-indigo-600" title={language === 'zh' ? `出现 ${row.occurrence_count} 次` : `${row.occurrence_count} occurrences`}>
                              <Repeat size={9} />
                              {row.occurrence_count}
                            </span>
                          )}
                        </p>
                        <p className="mt-1 line-clamp-1 text-xs text-black/45">{row.message}</p>
                      </button>
                    </td>
                     <td className="px-5 py-4 align-top text-sm text-black/60">
                      <div className="flex flex-col">
                        <div className="flex items-center gap-1.5 font-semibold text-[#164e63]">
                          <span>{row.hostname || row.ip_address || '--'}</span>
                          {row.device_id && (
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => onNavigateToDevice?.(row.device_id!)}
                                className="text-cyan-500 hover:text-cyan-700 transition-colors p-0.5"
                                title={language === 'zh' ? '跳转设备详情' : 'Jump to device details'}
                              >
                                <ExternalLink size={12} />
                              </button>
                              <button
                                onClick={() => onNavigateToTopology?.(row.device_id!)}
                                className="text-indigo-500 hover:text-indigo-700 transition-colors p-0.5"
                                title={language === 'zh' ? '在拓扑图上定位' : 'Locate on topology'}
                              >
                                <Network size={12} />
                              </button>
                            </div>
                          )}
                        </div>
                        <div className="mt-1 text-xs text-black/40">{row.interface_name || row.site || '--'}</div>
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-extrabold uppercase shadow-sm ${
                        row.severity === 'critical'
                          ? 'bg-rose-50 text-rose-700 border border-rose-200/50 shadow-rose-100'
                          : row.severity === 'major'
                          ? 'bg-amber-50 text-amber-700 border border-amber-200/50 shadow-amber-100'
                          : 'bg-blue-50 text-blue-700 border border-blue-200/50 shadow-blue-100'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${
                          row.severity === 'critical'
                            ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e]'
                            : row.severity === 'major'
                            ? 'bg-amber-500 shadow-[0_0_8px_#f59e0b]'
                            : 'bg-blue-500 shadow-[0_0_8px_#3b82f6]'
                        }`} />
                        {severityLabel(row.severity, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase ${alertWorkflowBadgeClass(row.workflow_status)}`}>
                        {workflowLabel(row.workflow_status, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {row.assignee || (language === 'zh' ? '未分派' : 'Unassigned')}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      <div>{formatTs(row.created_at)}</div>
                      <div className={`mt-1 flex items-center gap-1 text-xs ${
                        !row.resolved_at && (row.duration_seconds ?? 0) > 86400
                          ? 'font-semibold text-red-600'
                          : !row.resolved_at && (row.duration_seconds ?? 0) > 14400
                            ? 'font-medium text-amber-600'
                            : !row.resolved_at && (row.duration_seconds ?? 0) > 3600
                              ? 'text-amber-500'
                              : 'text-black/40'
                      }`}>
                        {!row.resolved_at && (row.duration_seconds ?? 0) > 3600 && <Clock size={11} />}
                        {formatDuration(row.duration_seconds, language)}
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <ActionIconGroup label={language === 'zh' ? '告警操作' : 'Alert actions'}>
                        <ActionIconButton
                          icon={Eye}
                          label={language === 'zh' ? `查看告警 ${row.title}` : `View alert ${row.title}`}
                          onClick={() => setSelectedAlertId(row.id)}
                        />
                        {!row.resolved_at && row.workflow_status !== 'acknowledged' && row.workflow_status !== 'investigating' && row.workflow_status !== 'suppressed' && (
                          <ActionIconButton
                            icon={CheckCircle2}
                            label={language === 'zh' ? '快速确认' : 'Quick Ack'}
                            variant="success"
                            onClick={() => void handleInlineAck(row.id)}
                          />
                        )}
                        {!row.resolved_at && row.assignee !== currentUsername && (
                          <ActionIconButton
                            icon={UserCheck}
                            label={language === 'zh' ? '分派给我' : 'Assign to me'}
                            variant="accent"
                            onClick={() => void handleInlineAssignToMe(row.id)}
                          />
                        )}
                      </ActionIconGroup>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '当前筛选条件下没有告警。' : 'No alerts found for the current filter.'}
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
        {selectedAlertId ? (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px] p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeDetail();
              }
            }}
          >
            <motion.div
              className="relative max-h-[92vh] w-full max-w-2xl overflow-hidden rounded-[24px] bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-[0_32px_80px_rgba(11,35,64,0.22)]"
              initial={{ y: 24, opacity: 0, scale: 0.97 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 24, opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            >
              {/* Severity accent top bar */}
              <div className={`h-1.5 w-full ${
                selectedItem?.severity === 'critical' ? 'bg-gradient-to-r from-red-500 via-red-400 to-rose-400' :
                selectedItem?.severity === 'major' ? 'bg-gradient-to-r from-orange-500 via-orange-400 to-amber-400' :
                selectedItem?.severity === 'warning' ? 'bg-gradient-to-r from-amber-500 via-amber-400 to-yellow-400' :
                'bg-gradient-to-r from-slate-400 via-slate-300 to-slate-400'
              }`} />

              <div className="max-h-[calc(92vh-4px)] overflow-y-auto">
                {detailLoading || !selectedItem ? (
                  <div className="flex items-center justify-center py-24">
                    <div className="flex flex-col items-center gap-3">
                      <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-200 border-t-cyan-500" />
                      <span className="text-sm text-black/40">{language === 'zh' ? '正在加载告警详情...' : 'Loading alert details...'}</span>
                    </div>
                  </div>
                ) : (
                  <>
                    {/* Header */}
                    <div className={`relative px-6 pt-6 pb-4 ${
                      selectedItem.severity === 'critical' ? 'bg-gradient-to-b from-red-50/60 to-transparent' :
                      selectedItem.severity === 'major' ? 'bg-gradient-to-b from-orange-50/60 to-transparent' :
                      selectedItem.severity === 'warning' ? 'bg-gradient-to-b from-amber-50/60 to-transparent' :
                      'bg-gradient-to-b from-slate-50/60 to-transparent'
                    }`}>
                      <button
                        title={language === 'zh' ? '关闭详情' : 'Close detail'}
                        onClick={closeDetail}
                        className="absolute right-4 top-4 rounded-lg p-1.5 text-black/30 transition-colors hover:bg-black/5 hover:text-black/60"
                      >
                        <X size={18} />
                      </button>

                      <div className="flex items-start gap-3.5 pr-10">
                        <div className={`mt-1 flex-shrink-0 rounded-xl p-2 ${
                          selectedItem.severity === 'critical' ? 'bg-red-50 ring-1 ring-red-200/60' :
                          selectedItem.severity === 'major' ? 'bg-orange-50 ring-1 ring-orange-200/60' :
                          selectedItem.severity === 'warning' ? 'bg-amber-50 ring-1 ring-amber-200/60' :
                          'bg-slate-50 ring-1 ring-slate-200/60'
                        }`}>
                          <AlertTriangle size={18} className={
                            selectedItem.severity === 'critical' ? 'text-red-500' :
                            selectedItem.severity === 'major' ? 'text-orange-500' :
                            selectedItem.severity === 'warning' ? 'text-amber-500' : 'text-slate-500'
                          } />
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${severityBadgeClass(selectedItem.severity)}`}>
                              {severityLabel(selectedItem.severity, language)}
                            </span>
                            <span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold ${alertWorkflowBadgeClass(selectedItem.workflow_status)}`}>
                              {workflowLabel(selectedItem.workflow_status, language)}
                            </span>
                            {(selectedItem.occurrence_count ?? 1) > 1 && (
                              <span className="inline-flex items-center gap-1 rounded-md bg-violet-50 px-2 py-0.5 text-[10px] font-bold text-violet-600 ring-1 ring-violet-200/80">
                                <Repeat size={10} />
                                ×{selectedItem.occurrence_count}
                              </span>
                            )}
                          </div>
                          <h3 className="mt-2 text-[17px] font-semibold leading-snug text-[#0f2b35]">
                            {selectedItem.title}
                          </h3>
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-black/38">
                            <span className="inline-flex items-center gap-1">
                              <Clock size={11} />
                              {formatTs(selectedItem.created_at)}
                            </span>
                            {selectedItem.duration_seconds != null && (
                              <span className="inline-flex items-center gap-1">
                                <Activity size={11} />
                                {formatDuration(selectedItem.duration_seconds, language)}
                              </span>
                            )}
                            {selectedItem.assignee && (
                              <span className="inline-flex items-center gap-1">
                                <UserCheck size={11} />
                                {selectedItem.assignee}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="mx-6 border-t border-black/[0.06]" />

                    {/* Content */}
                    <div className="space-y-4 px-6 py-5">
                      {/* Metric pills */}
                      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                        <div className="rounded-xl bg-gradient-to-b from-[#f8f9fb] to-[#f4f5f8] px-3 py-2.5 ring-1 ring-black/[0.04]">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? 'IP 地址' : 'IP Address'}</p>
                          <p className="mt-0.5 truncate text-sm font-semibold tabular-nums text-[#164e63]">{selectedItem.ip_address || '--'}</p>
                        </div>
                        <div className="rounded-xl bg-gradient-to-b from-[#f8f9fb] to-[#f4f5f8] px-3 py-2.5 ring-1 ring-black/[0.04]">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '主机名' : 'Hostname'}</p>
                          <p className="mt-0.5 truncate text-sm font-semibold text-[#164e63]">
                            {selectedItem.device_id ? (
                              <button onClick={() => { closeDetail(); onNavigateToDevice?.(selectedItem.device_id!); }} className="text-[#0e7490] hover:underline">
                                {selectedItem.hostname || '--'}
                              </button>
                            ) : (selectedItem.hostname || '--')}
                          </p>
                        </div>
                        <div className="rounded-xl bg-gradient-to-b from-[#f8f9fb] to-[#f4f5f8] px-3 py-2.5 ring-1 ring-black/[0.04]">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '站点' : 'Site'}</p>
                          <p className="mt-0.5 truncate text-sm font-semibold text-[#164e63]">{selectedItem.site || '--'}</p>
                        </div>
                        <div className="rounded-xl bg-gradient-to-b from-[#f8f9fb] to-[#f4f5f8] px-3 py-2.5 ring-1 ring-black/[0.04]">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '接口' : 'Interface'}</p>
                          <p className="mt-0.5 truncate text-sm font-semibold text-[#164e63]">{selectedItem.interface_name || '--'}</p>
                        </div>
                      </div>

                      {/* Topology link */}
                      {selectedItem.device_id && (
                        <button
                          onClick={() => { closeDetail(); onNavigateToTopology?.(selectedItem.device_id!); }}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-[#0e7490] ring-1 ring-cyan-200/60 transition-all hover:bg-cyan-100 hover:ring-cyan-300/60"
                        >
                          <MapPin size={12} />
                          {language === 'zh' ? '在拓扑中定位' : 'Locate in Topology'}
                        </button>
                      )}

                      {/* Alert message */}
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '告警内容' : 'Alert Message'}</p>
                        <div className="mt-1.5 rounded-xl border border-black/[0.06] bg-[#fafbfc] p-3.5 text-[13px] leading-relaxed text-black/65">
                          {selectedItem.message}
                        </div>
                      </div>

                      {/* Workflow Actions */}
                      {!selectedItem.resolved_at && selectedItem.workflow_status !== 'suppressed' && (
                        <div className="grid grid-cols-3 gap-2">
                          <button
                            disabled={actionLoading === 'ack'}
                            onClick={() => void handleAck('acknowledged')}
                            className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-bold text-white shadow-sm transition-all hover:bg-emerald-600 hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <CheckCircle2 size={15} />
                            {language === 'zh' ? '确认告警' : 'Acknowledge'}
                          </button>
                          <button
                            disabled={actionLoading === 'ack'}
                            onClick={() => void handleAck('investigating')}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-700 transition-all hover:border-amber-300 hover:bg-amber-100 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <Search size={15} />
                            {language === 'zh' ? '介入调查' : 'Investigate'}
                          </button>
                          <button
                            onClick={() => onOpenMaintenanceForAlert?.(selectedItem)}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-black/8 bg-white px-4 py-2.5 text-sm font-semibold text-[#164e63] transition-all hover:border-black/15 hover:bg-black/[0.03] active:scale-[0.98]"
                          >
                            <Wrench size={15} />
                            {language === 'zh' ? '维护抑制' : 'Suppress'}
                          </button>
                        </div>
                      )}

                      {/* Assignee */}
                      <div className="rounded-xl border border-black/[0.06] bg-[#fafbfc] p-4">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '责任人' : 'Assignee'}</p>
                        <div className="mt-2 flex gap-2">
                          <input
                            value={assignValue}
                            onChange={(e) => setAssignValue(e.target.value)}
                            placeholder={language === 'zh' ? '输入用户名' : 'Enter username'}
                            className="flex-1 rounded-lg border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none placeholder:text-black/25 focus:border-cyan-300 focus:ring-2 focus:ring-cyan-100 transition-shadow"
                          />
                          <button
                            disabled={actionLoading === 'assign' || !assignValue.trim()}
                            onClick={() => void handleAssign()}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-[#0e7490] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#0a5e75] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <UserCheck size={14} />
                            {language === 'zh' ? '分派' : 'Assign'}
                          </button>
                        </div>
                      </div>

                      {/* Response note */}
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '处置备注' : 'Response Note'}</p>
                        <textarea
                          value={detailNote}
                          onChange={(e) => setDetailNote(e.target.value)}
                          rows={3}
                          className="mt-1.5 w-full resize-y rounded-xl border border-black/[0.08] bg-white px-3.5 py-2.5 text-sm text-[#164e63] outline-none placeholder:text-black/25 focus:border-cyan-300 focus:ring-2 focus:ring-cyan-100 transition-shadow"
                          placeholder={language === 'zh' ? '记录处理动作和结论…' : 'Capture actions and conclusion…'}
                        />
                        <div className="mt-2 flex justify-end">
                          <button
                            disabled={actionLoading === 'note'}
                            onClick={() => void handleSaveNote()}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-[#06b6d4] px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#0891b2] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            {language === 'zh' ? '保存备注' : 'Save Note'}
                          </button>
                        </div>
                      </div>

                      {/* Timeline */}
                      {selectedDetail?.timeline && selectedDetail.timeline.length > 1 && (
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">
                            {language === 'zh' ? '关联告警时间轴' : 'Related Alert Timeline'}
                            <span className="ml-1 text-black/20">({selectedDetail.timeline.length})</span>
                          </p>
                          <div className="relative mt-2 max-h-[200px] overflow-y-auto rounded-xl border border-black/[0.06] bg-[#fafbfc]">
                            {selectedDetail.timeline.map((tl, idx) => {
                              const isCurrent = tl.id === selectedItem.id;
                              return (
                                <div
                                  key={tl.id}
                                  className={`relative flex items-start gap-3 px-4 py-3 ${idx !== selectedDetail.timeline.length - 1 ? 'border-b border-black/[0.04]' : ''} ${isCurrent ? 'bg-cyan-50/40' : ''}`}
                                >
                                  {/* Vertical connector */}
                                  {idx !== selectedDetail.timeline.length - 1 && (
                                    <div className="absolute left-[22px] top-[26px] bottom-0 w-px bg-black/[0.06]" />
                                  )}
                                  <div className="relative z-10 mt-1 flex-shrink-0">
                                    <div className={`h-3 w-3 rounded-full ring-2 ring-white ${
                                      isCurrent ? 'bg-cyan-500 shadow-[0_0_0_3px_rgba(6,182,212,0.15)]' :
                                      tl.resolved_at ? 'bg-emerald-400' : 'bg-black/15'
                                    }`} />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-1.5">
                                      <span className="truncate text-[13px] font-medium text-[#164e63]">{tl.title}</span>
                                      <span className={`inline-flex flex-shrink-0 rounded-md px-1.5 py-0.5 text-[9px] font-bold uppercase ${severityBadgeClass(tl.severity)}`}>
                                        {severityLabel(tl.severity, language)}
                                      </span>
                                      {isCurrent && (
                                        <span className="flex-shrink-0 rounded bg-cyan-100 px-1.5 py-0.5 text-[9px] font-bold text-cyan-700">
                                          {language === 'zh' ? '当前' : 'Current'}
                                        </span>
                                      )}
                                    </div>
                                    <div className="mt-0.5 flex items-center gap-3 text-[11px] text-black/35">
                                      <span>{formatTs(tl.created_at)}</span>
                                      {tl.resolved_at && <span className="text-emerald-600">{language === 'zh' ? '已恢复' : 'Resolved'}</span>}
                                      {tl.ack_by && <span>{language === 'zh' ? `确认: ${tl.ack_by}` : `Ack: ${tl.ack_by}`}</span>}
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-black/30">{language === 'zh' ? '状态活动审计' : 'State activity audit'}</p>
                        {activityLoading ? <p className="mt-2 text-xs text-black/35">{language === 'zh' ? '加载中...' : 'Loading...'}</p> : activity.length === 0 ? <p className="mt-2 text-xs text-black/35">{language === 'zh' ? '暂无活动记录（旧数据可能尚未迁移）' : 'No activity events yet.'}</p> : <div className="mt-2 max-h-40 overflow-y-auto rounded-xl border border-black/[0.06] bg-[#fafbfc]">{activity.map((event) => <div key={event.id} className="flex items-center justify-between gap-3 border-b border-black/[0.04] px-4 py-2.5 text-xs last:border-b-0"><span className="font-medium text-[#164e63]">{event.event_type}</span><span className="text-black/35">{event.from_state || '—'} → {event.to_state || '—'} · {formatTs(event.created_at)}</span></div>)}</div>}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
};

export default AlertDeskTab;
