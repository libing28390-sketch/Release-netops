import React, { useEffect, useState, useCallback } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Search, X, Download, RefreshCw, Eye, Repeat, ChevronDown, ChevronUp, Calendar, MapPin, Wrench, History } from 'lucide-react';
import * as XLSX from 'xlsx';
import type { AlertListResponse, AlertRecord, AlertDetailResponse } from '../types';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { severityBadgeClass, alertWorkflowBadgeClass } from '../components/shared';
import { fetchAllPaginatedItems } from '../utils/pagination';
import DateTimePicker from '../components/DateTimePicker';
import {
  alertInputClass,
  alertPanelClass,
  alertSecondaryButtonClass,
  AlertPageCommonProps,
  formatDuration,
  formatTs,
  severityLabel,
  useAlertOverlayDismiss,
  workflowLabel,
} from './alertManagementShared';

interface AlertHistoryTabProps extends AlertPageCommonProps {
  onNavigateToDevice?: (deviceId: string) => void;
  onNavigateToTopology?: (deviceId: string) => void;
}

const AlertHistoryTab: React.FC<AlertHistoryTabProps> = ({ language, showToast, onNavigateToDevice, onNavigateToTopology }) => {
  const zh = language === 'zh';

  const [rows, setRows] = useState<AlertRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [createdFrom, setCreatedFrom] = useState('');
  const [createdTo, setCreatedTo] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Detail
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<AlertDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const selectedItem = selectedDetail?.item ?? rows.find(r => r.id === selectedAlertId) ?? null;
  useAlertOverlayDismiss(!!selectedAlertId, () => setSelectedAlertId(null));

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        status: 'resolved',
        severity: severityFilter,
        site: 'all',
        assignee: 'all',
        search,
      });
      if (createdFrom) params.set('created_from', createdFrom);
      if (createdTo) params.set('created_to', createdTo);

      const resp = await fetch(`/api/alerts?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed');
      const data: AlertListResponse = await resp.json();
      const items = data.items || [];
      setRows(items);
      setTotal(data.total && data.total > 0 ? data.total : items.length);
    } catch {
      showToast(zh ? '加载历史告警失败' : 'Failed to load alert history', 'error');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, severityFilter, search, createdFrom, createdTo, zh]);

  useEffect(() => { void loadAlerts(); }, [loadAlerts]);

  const loadDetail = async (alertId: string) => {
    setDetailLoading(true);
    try {
      const resp = await fetch(`/api/alerts/${alertId}`);
      if (!resp.ok) throw new Error('Failed');
      const data: AlertDetailResponse = await resp.json();
      setSelectedDetail(data);
    } catch {
      showToast(zh ? '加载详情失败' : 'Failed to load detail', 'error');
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (selectedAlertId) {
      setSelectedDetail(null);
      void loadDetail(selectedAlertId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAlertId]);

  const closeDetail = () => {
    setSelectedAlertId(null);
    setSelectedDetail(null);
  };

  const handleExport = async () => {
    const params = new URLSearchParams({
      status: 'resolved',
      severity: severityFilter,
      site: 'all',
      assignee: 'all',
      search,
    });
    if (createdFrom) params.set('created_from', createdFrom);
    if (createdTo) params.set('created_to', createdTo);

    try {
      const allRows = await fetchAllPaginatedItems<AlertRecord>('/api/alerts', params);
      if (allRows.length === 0) return;
      const data = allRows.map(r => ({
        [zh ? '告警标题' : 'Title']: r.title,
        [zh ? '设备' : 'Device']: r.hostname || r.ip_address || '--',
        [zh ? '站点' : 'Site']: r.site || '--',
        [zh ? '级别' : 'Severity']: severityLabel(r.severity, language),
        [zh ? '状态' : 'Status']: workflowLabel(r.workflow_status, language),
        [zh ? '责任人' : 'Assignee']: r.assignee || '--',
        [zh ? '创建时间' : 'Created']: formatTs(r.created_at),
        [zh ? '恢复时间' : 'Resolved']: formatTs(r.resolved_at),
        [zh ? '持续时间' : 'Duration']: formatDuration(r.duration_seconds, language),
        [zh ? '出现次数' : 'Occurrences']: r.occurrence_count ?? 1,
        [zh ? '备注' : 'Note']: r.note || '',
      }));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data), zh ? '历史告警' : 'Alert History');
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      XLSX.writeFile(wb, `alert_history_${ts}.xlsx`);
      showToast(zh ? '导出成功' : 'Exported', 'success');
    } catch (error) {
      console.error('Failed to export alert history:', error);
      showToast(zh ? '导出失败' : 'Export failed', 'error');
    }
  };

  const clearTimeRange = () => {
    setCreatedFrom('');
    setCreatedTo('');
    setPage(1);
  };

  const applyQuickRange = (days: number) => {
    const now = new Date();
    const from = new Date(now.getTime() - days * 86400000);
    const pad2 = (n: number) => (n < 10 ? `0${n}` : String(n));
    setCreatedFrom(`${from.getFullYear()}-${pad2(from.getMonth() + 1)}-${pad2(from.getDate())}T00:00`);
    setCreatedTo(`${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}T23:59`);
    setPage(1);
  };

  return (
    <>
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={History}
        eyebrow={zh ? '告警中心 / 历史告警' : 'Alert Center / Alert History'}
        title={zh ? '历史告警' : 'Alert History'}
        subtitle={zh ? '查询并溯源历史告警，复盘故障处理生命周期与时长记录。' : 'Trace historical alerts and review incident lifecycles and resolution metrics.'}
        actions={
          <>
            <button onClick={handleExport} className={alertSecondaryButtonClass} title={zh ? '导出' : 'Export'}>
              <Download size={14} />
              {zh ? '导出' : 'Export'}
            </button>
            <button onClick={() => void loadAlerts()} className={alertSecondaryButtonClass}>
              <RefreshCw size={14} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 min-h-0">
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Search bar */}
        <div className="flex flex-col gap-3 px-5 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <label className="relative min-w-[240px] flex-1">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/40" />
              <input
                value={search}
                onChange={(e) => { setPage(1); setSearch(e.target.value); }}
                placeholder={zh ? '搜索标题、设备、接口、IP' : 'Search title, device, interface, IP'}
                className={`${alertInputClass} rounded-xl py-3 pl-9 pr-3`}
              />
            </label>

            <select
              title={zh ? '按级别筛选' : 'Filter by severity'}
              value={severityFilter}
              onChange={(e) => { setPage(1); setSeverityFilter(e.target.value); }}
              className="rounded-xl border border-black/10 bg-white px-3 py-3 text-sm text-[#164e63] outline-none"
            >
              <option value="all">{zh ? '全部级别' : 'All Severity'}</option>
              <option value="critical">{severityLabel('critical', language)}</option>
              <option value="major">{severityLabel('major', language)}</option>
              <option value="warning">{severityLabel('warning', language)}</option>
            </select>

            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className={`flex items-center gap-1.5 rounded-xl border px-3 py-3 text-sm font-medium transition-colors ${
                showAdvanced || createdFrom || createdTo
                  ? 'border-[#06b6d4]/30 bg-[#ecfeff] text-[#0e7490]'
                  : 'border-black/10 bg-white text-black/55 hover:bg-black/[0.02]'
              }`}
            >
              <Calendar size={14} />
              {zh ? '时间筛选' : 'Time Filter'}
              {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {(createdFrom || createdTo) && !showAdvanced && (
                <span className="ml-1 h-2 w-2 rounded-full bg-[#06b6d4]" />
              )}
            </button>
          </div>

          {/* Advanced: time range */}
          <AnimatePresence>
            {showAdvanced && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="rounded-2xl border border-black/5 bg-[#f8fafc] p-4">
                  <div className="flex flex-wrap items-end gap-4">
                    <div className="min-w-[200px] flex-1">
                      <p className="mb-1.5 text-xs font-semibold text-black/45">{zh ? '开始时间' : 'From'}</p>
                      <DateTimePicker value={createdFrom} onChange={(v) => { setCreatedFrom(v); setPage(1); }} language={language} placeholder={zh ? '选择开始时间' : 'Select start time'} />
                    </div>
                    <div className="min-w-[200px] flex-1">
                      <p className="mb-1.5 text-xs font-semibold text-black/45">{zh ? '结束时间' : 'To'}</p>
                      <DateTimePicker value={createdTo} onChange={(v) => { setCreatedTo(v); setPage(1); }} language={language} placeholder={zh ? '选择结束时间' : 'Select end time'} />
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex rounded-xl border border-black/10 bg-white">
                        {[
                          { label: zh ? '近7天' : '7d', days: 7 },
                          { label: zh ? '近30天' : '30d', days: 30 },
                          { label: zh ? '近90天' : '90d', days: 90 },
                        ].map(q => (
                          <button
                            key={q.days}
                            onClick={() => applyQuickRange(q.days)}
                            className="border-r border-black/5 px-3 py-2.5 text-xs font-medium text-black/55 transition-colors last:border-r-0 hover:bg-[#ecfeff] hover:text-[#0e7490]"
                          >
                            {q.label}
                          </button>
                        ))}
                      </div>
                      {(createdFrom || createdTo) && (
                        <button
                          onClick={clearTimeRange}
                          className="rounded-xl border border-black/10 p-2.5 text-black/40 hover:bg-black/[0.03] hover:text-black/60"
                          title={zh ? '清除时间范围' : 'Clear time range'}
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                  {(createdFrom || createdTo) && (
                    <p className="mt-3 text-xs text-black/40">
                      {zh ? '当前范围：' : 'Range: '}
                      {createdFrom || '∞'} — {createdTo || '∞'}
                    </p>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Summary badge */}
        <div className="flex items-center gap-2 border-b border-black/5 px-5 pb-3">
          <span className="rounded-xl bg-[#f0f9ff] px-3 py-2 text-sm font-medium text-[#164e63]">
            {zh ? `共 ${total} 条历史告警` : `${total} historical alerts`}
          </span>
        </div>

        {/* Table */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          <table className="nx-data-table text-left">
            <thead className="sticky top-0 z-10">
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="px-5 py-3">{zh ? '告警标题' : 'Alert'}</th>
                <th className="px-5 py-3">{zh ? '对象' : 'Object'}</th>
                <th className="px-5 py-3">{zh ? '级别' : 'Severity'}</th>
                <th className="px-5 py-3">{zh ? '责任人' : 'Assignee'}</th>
                <th className="px-5 py-3">{zh ? '发生时间' : 'Created'}</th>
                <th className="px-5 py-3">{zh ? '恢复时间' : 'Resolved'}</th>
                <th className="px-5 py-3">{zh ? '持续时间' : 'Duration'}</th>
                <th className="px-5 py-3">{zh ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-black/40">
                    {zh ? '正在加载...' : 'Loading...'}
                  </td>
                </tr>
              ) : rows.length > 0 ? (
                rows.map(row => (
                  <tr key={row.id} className="border-b border-black/5 hover:bg-black/[0.02]">
                    <td className="px-5 py-4 align-top">
                      <button onClick={() => setSelectedAlertId(row.id)} className="text-left" title={zh ? '查看详情' : 'View detail'}>
                        <p className="text-sm font-semibold text-[#164e63]">
                          {row.title}
                          {(row.occurrence_count ?? 1) > 1 && (
                            <span className="ml-1.5 inline-flex items-center gap-0.5 rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-bold text-indigo-600">
                              <Repeat size={9} />
                              {row.occurrence_count}
                            </span>
                          )}
                        </p>
                        <p className="mt-1 line-clamp-1 text-xs text-black/45">{row.message}</p>
                      </button>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {row.device_id ? (
                        <button
                          onClick={() => onNavigateToDevice?.(row.device_id!)}
                          className="text-left text-[#2b6b8f] hover:underline"
                        >
                          <div>{row.hostname || row.ip_address || '--'}</div>
                          <div className="mt-1 text-xs text-black/40">{row.interface_name || row.site || '--'}</div>
                        </button>
                      ) : (
                        <>
                          <div>{row.hostname || row.ip_address || '--'}</div>
                          <div className="mt-1 text-xs text-black/40">{row.interface_name || row.site || '--'}</div>
                        </>
                      )}
                    </td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-bold uppercase ${severityBadgeClass(row.severity)}`}>
                        {severityLabel(row.severity, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {row.assignee || (zh ? '未分派' : 'Unassigned')}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {formatTs(row.created_at)}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {formatTs(row.resolved_at)}
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">
                      {formatDuration(row.duration_seconds, language)}
                    </td>
                    <td className="px-5 py-4 align-top">
                      <button
                        onClick={() => setSelectedAlertId(row.id)}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-xl border border-transparent bg-white px-3 text-xs font-semibold text-[#0e7490] shadow-[0_1px_2px_rgba(6,182,212,0.08)] transition-all hover:-translate-y-0.5 hover:bg-[#ecfeff] hover:text-[#0891b2]"
                        title={zh ? '查看详情' : 'View detail'}
                      >
                        <Eye size={14} />
                        {zh ? '查看' : 'View'}
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-black/40">
                    {zh ? '当前筛选条件下没有历史告警。' : 'No historical alerts found.'}
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
            onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
            onPageChange={setPage}
            language={language}
          />
        </div>

      </div>
      </div>
    </div>

      {/* Detail Modal */}
      <AnimatePresence>
        {selectedAlertId ? (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            onMouseDown={(e) => { if (e.target === e.currentTarget) closeDetail(); }}
          >
            <motion.div
              className="relative max-h-[92vh] w-full max-w-2xl overflow-hidden rounded-[24px] bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-[0_32px_80px_rgba(11,35,64,0.22)]"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">
                    {zh ? '告警详情' : 'Alert Detail'}
                  </p>
                  <h3 className="mt-2 text-xl font-semibold text-[#164e63]">
                    {selectedItem?.title || (zh ? '加载中...' : 'Loading...')}
                    {selectedItem && (selectedItem.occurrence_count ?? 1) > 1 && (
                      <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-bold text-indigo-600">
                        <Repeat size={11} />
                        {zh ? `出现 ${selectedItem.occurrence_count} 次` : `${selectedItem.occurrence_count} occurrences`}
                      </span>
                    )}
                  </h3>
                </div>
                <button title={zh ? '关闭' : 'Close'} onClick={closeDetail} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                  <X size={16} />
                </button>
              </div>

              {detailLoading || !selectedItem ? (
                <div className="px-6 py-16 text-center text-sm text-black/40">
                  {zh ? '正在加载告警详情...' : 'Loading alert details...'}
                </div>
              ) : (
                <div className="space-y-5 px-6 py-6">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div className="rounded-2xl bg-[#f7f8fb] p-4 text-sm text-black/65">
                      <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{zh ? '基本信息' : 'Basic Info'}</p>
                      <div className="mt-3 space-y-2">
                        <p><span className="text-black/35">IP:</span> {selectedItem.ip_address || '--'}</p>
                        <p>
                          <span className="text-black/35">Hostname:</span>{' '}
                          {selectedItem.device_id ? (
                            <button onClick={() => { closeDetail(); onNavigateToDevice?.(selectedItem.device_id!); }} className="text-[#2b6b8f] hover:underline">
                              {selectedItem.hostname || '--'}
                            </button>
                          ) : (selectedItem.hostname || '--')}
                        </p>
                        <p><span className="text-black/35">Site:</span> {selectedItem.site || '--'}</p>
                        <p><span className="text-black/35">Interface:</span> {selectedItem.interface_name || '--'}</p>
                      </div>
                      {selectedItem.device_id && (
                        <button
                          onClick={() => { closeDetail(); onNavigateToTopology?.(selectedItem.device_id!); }}
                          className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-[#2b6b8f] hover:underline"
                        >
                          <MapPin size={12} />
                          {zh ? '在拓扑中定位' : 'Locate in Topology'}
                        </button>
                      )}
                    </div>

                    <div className="rounded-2xl bg-[#f7f8fb] p-4 text-sm text-black/65">
                      <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{zh ? '状态信息' : 'Status'}</p>
                      <div className="mt-3 space-y-2">
                        <p><span className="text-black/35">{zh ? '级别' : 'Severity'}:</span> {severityLabel(selectedItem.severity, language)}</p>
                        <p><span className="text-black/35">{zh ? '状态' : 'Status'}:</span> {workflowLabel(selectedItem.workflow_status, language)}</p>
                        <p><span className="text-black/35">{zh ? '创建时间' : 'Created'}:</span> {formatTs(selectedItem.created_at)}</p>
                        <p><span className="text-black/35">{zh ? '恢复时间' : 'Resolved'}:</span> {formatTs(selectedItem.resolved_at)}</p>
                        <p><span className="text-black/35">{zh ? '持续时间' : 'Duration'}:</span> {formatDuration(selectedItem.duration_seconds, language)}</p>
                        <p><span className="text-black/35">{zh ? '责任人' : 'Assignee'}:</span> {selectedItem.assignee || (zh ? '未分派' : '--')}</p>
                      </div>
                    </div>
                  </div>

                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{zh ? '告警内容' : 'Alert Message'}</p>
                    <div className="mt-2 rounded-2xl border border-black/8 bg-white p-4 text-sm leading-6 text-black/70">
                      {selectedItem.message}
                    </div>
                  </div>

                  {selectedItem.note && (
                    <div>
                      <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{zh ? '处置备注' : 'Response Note'}</p>
                      <div className="mt-2 rounded-2xl border border-black/8 bg-white p-4 text-sm leading-6 text-black/70">
                        {selectedItem.note}
                      </div>
                    </div>
                  )}

                  {selectedDetail?.timeline && selectedDetail.timeline.length > 1 && (
                    <div>
                      <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">
                        {zh ? '关联告警时间轴' : 'Related Alert Timeline'}
                        <span className="ml-1.5 text-black/25">({selectedDetail.timeline.length})</span>
                      </p>
                      <div className="mt-2 max-h-[200px] overflow-y-auto rounded-2xl border border-black/8 bg-[#fafbfc]">
                        {selectedDetail.timeline.map((tl, idx) => (
                          <div
                            key={tl.id}
                            className={`flex items-start gap-3 px-4 py-3 ${idx !== selectedDetail.timeline.length - 1 ? 'border-b border-black/5' : ''} ${tl.id === selectedItem.id ? 'bg-blue-50/50' : ''}`}
                          >
                            <div className="mt-0.5 flex-shrink-0">
                              <div className={`h-2 w-2 rounded-full ${tl.resolved_at ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate text-sm font-medium text-[#164e63]">{tl.title}</span>
                                <span className={`inline-flex rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${severityBadgeClass(tl.severity)}`}>
                                  {severityLabel(tl.severity, language)}
                                </span>
                                {tl.id === selectedItem.id && (
                                  <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[9px] font-bold text-blue-600">
                                    {zh ? '当前' : 'Current'}
                                  </span>
                                )}
                              </div>
                              <div className="mt-1 flex items-center gap-3 text-xs text-black/40">
                                <span>{formatTs(tl.created_at)}</span>
                                {tl.resolved_at && <span className="text-emerald-600">{zh ? '已恢复' : 'Resolved'}</span>}
                                {tl.ack_by && <span>{zh ? `确认人: ${tl.ack_by}` : `Ack: ${tl.ack_by}`}</span>}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
};

export default AlertHistoryTab;
