import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  FileSpreadsheet,
  Download,
  Activity,
  Server,
  Globe,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  BarChart2,
  Layers,
  RefreshCw,
  Search,
  Filter,
  SlidersHorizontal,
  RotateCcw,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Sparkles,
  Cpu,
  HardDrive,
  Check,
} from 'lucide-react';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';

interface MonitoringReportsPageProps {
  language: 'zh' | 'en';
}

type ReportTab = 'interfaces' | 'devices' | 'outbound';

interface ReportFilterState {
  keyword: string;
  vendor: string;
  site: string;
  role: string;
  status: string;
  minUtil: string;
  hasErrors: boolean;
  highLoadOnly: boolean;
  isp: string;
}

const INITIAL_FILTERS: ReportFilterState = {
  keyword: '',
  vendor: 'all',
  site: 'all',
  role: 'all',
  status: 'all',
  minUtil: '',
  hasErrors: false,
  highLoadOnly: false,
  isp: 'all',
};

const UNAVAILABLE_VALUE = '—';

const toNullableNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const formatMetric = (value: unknown, suffix = '', decimals = 1): string => {
  const number = toNullableNumber(value);
  return number === null ? UNAVAILABLE_VALUE : `${number.toFixed(decimals)}${suffix}`;
};

const formatSampleTime = (value: unknown, language: 'zh' | 'en'): string => {
  if (typeof value !== 'string' || !value) return UNAVAILABLE_VALUE;
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return timestamp.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US');
};

export const MonitoringReportsPage: React.FC<MonitoringReportsPageProps> = ({ language }) => {
  const zh = language === 'zh';
  const location = useLocation();
  const navigate = useNavigate();

  // Active Report Tab mapped from route /monitor/reports/:subPage
  const tabFromPath = useMemo((): ReportTab => {
    const parts = location.pathname.split('/').filter(Boolean);
    const sub = parts[2];
    if (sub === 'devices') return 'devices';
    if (sub === 'outbound') return 'outbound';
    return 'interfaces';
  }, [location.pathname]);

  const [activeTab, setActiveTab] = useState<ReportTab>(tabFromPath);

  // Sync tab with URL
  useEffect(() => {
    setActiveTab(tabFromPath);
  }, [tabFromPath]);

  // Filters State
  const [filters, setFilters] = useState<ReportFilterState>(INITIAL_FILTERS);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Loading & Data State
  const [loading, setLoading] = useState(false);
  const [reportData, setReportData] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [exportErrorMessage, setExportErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const [showFullExportMenu, setShowFullExportMenu] = useState(false);
  const reportRequestSequenceRef = useRef(0);
  const reportAbortControllerRef = useRef<AbortController | null>(null);

  // Table Sorting & Pagination State
  const [sortKey, setSortKey] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Count active advanced filter criteria
  const activeAdvancedFilterCount = useMemo(() => {
    let count = 0;
    if (filters.vendor !== 'all') count++;
    if (filters.site !== 'all') count++;
    if (filters.role !== 'all') count++;
    if (filters.status !== 'all') count++;
    if (filters.minUtil !== '') count++;
    if (filters.hasErrors) count++;
    if (filters.highLoadOnly) count++;
    if (filters.isp !== 'all') count++;
    return count;
  }, [filters]);

  // Fetch Report Tabular Data from Backend
  const fetchData = useCallback(async () => {
    reportAbortControllerRef.current?.abort();
    const controller = new AbortController();
    reportAbortControllerRef.current = controller;
    const requestSequence = ++reportRequestSequenceRef.current;
    setLoading(true);
    setReportData(null);
    setErrorMessage(null);

    try {
      const token = localStorage.getItem('netops_token') || localStorage.getItem('sessionToken') || '';
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const params = new URLSearchParams({
        report_type: activeTab,
      });

      if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim());
      if (filters.vendor !== 'all') params.set('vendor', filters.vendor);
      if (filters.site !== 'all') params.set('site', filters.site);
      if (filters.role !== 'all') params.set('role', filters.role);
      if (filters.status !== 'all') params.set('status', filters.status);
      if (filters.minUtil) params.set('min_util', filters.minUtil);
      if (filters.hasErrors) params.set('has_errors', 'true');
      if (filters.highLoadOnly) params.set('high_load_only', 'true');
      if (filters.isp !== 'all') params.set('isp', filters.isp);

      const res = await fetch(`/api/monitoring/reports/data?${params.toString()}`, {
        headers,
        credentials: 'same-origin',
        signal: controller.signal,
      });

      if (!res.ok) {
        const message = res.status === 403
          ? (zh ? '你没有权限查看监控报表' : 'You do not have permission to view monitoring reports')
          : res.status === 401
            ? (zh ? '登录状态已失效，请重新登录' : 'Your session has expired. Please sign in again.')
            : `Failed to load report data (HTTP ${res.status})`;
        throw new Error(message);
      }

      const data = await res.json();
      if (requestSequence !== reportRequestSequenceRef.current) return;
      setReportData(data);
      setCurrentPage(1); // reset to page 1 on new query
    } catch (err: any) {
      if (requestSequence !== reportRequestSequenceRef.current || err?.name === 'AbortError') return;
      setReportData(null);
      setErrorMessage(err?.message || (zh ? '获取报表数据异常' : 'Error loading report data'));
    } finally {
      if (requestSequence === reportRequestSequenceRef.current) {
        setLoading(false);
        reportAbortControllerRef.current = null;
      }
    }
  }, [activeTab, filters, zh]);

  // Re-fetch when tab or applied filters change
  useEffect(() => {
    void fetchData();
    return () => {
      reportRequestSequenceRef.current += 1;
      reportAbortControllerRef.current?.abort();
      reportAbortControllerRef.current = null;
    };
  }, [fetchData]);

  // Handle Download (either current filtered or authoritative full)
  const handleExport = async (format: 'xlsx' | 'csv', isFiltered: boolean = true) => {
    const key = `${activeTab}-${format}-${isFiltered ? 'filtered' : 'full'}`;
    setDownloadingKey(key);
    setSuccessMessage(null);
    setExportErrorMessage(null);
    setShowFullExportMenu(false);

    try {
      const token = localStorage.getItem('netops_token') || localStorage.getItem('sessionToken') || '';
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const params = new URLSearchParams({ format });
      if (isFiltered) {
        if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim());
        if (filters.vendor !== 'all') params.set('vendor', filters.vendor);
        if (filters.site !== 'all') params.set('site', filters.site);
        if (filters.role !== 'all') params.set('role', filters.role);
        if (filters.status !== 'all') params.set('status', filters.status);
        if (filters.minUtil) params.set('min_util', filters.minUtil);
        if (filters.hasErrors) params.set('has_errors', 'true');
        if (filters.highLoadOnly) params.set('high_load_only', 'true');
        if (filters.isp !== 'all') params.set('isp', filters.isp);
      }

      const endpoint = `/api/monitoring/export/${activeTab}?${params.toString()}`;
      const response = await fetch(endpoint, {
        headers,
        credentials: 'same-origin',
      });

      if (!response.ok) {
        const message = response.status === 403
          ? (zh ? '你没有权限导出此监控报表' : 'You do not have permission to export this monitoring report')
          : response.status === 401
            ? (zh ? '登录状态已失效，请重新登录' : 'Your session has expired. Please sign in again.')
            : `Export failed with HTTP status ${response.status}`;
        throw new Error(message);
      }

      const blob = await response.blob();
      const contentDisposition = response.headers.get('Content-Disposition') || '';
      let filename = `nexora_${activeTab}_${new Date().toISOString().slice(0, 10)}.${format}`;
      const match = contentDisposition.match(/filename="?([^"]+)"?/);
      if (match && match[1]) {
        filename = match[1];
      }

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setSuccessMessage(
        zh
          ? `已成功生成并下载报表：${filename}`
          : `Successfully exported and downloaded: ${filename}`
      );
    } catch (err: any) {
      setExportErrorMessage(
        zh
          ? `导出失败：${err?.message || '网络连接或服务端异常'}`
          : `Export error: ${err?.message || 'Network or server failure'}`
      );
    } finally {
      setDownloadingKey(null);
    }
  };

  // Reset Filters
  const handleResetFilters = () => {
    setFilters(INITIAL_FILTERS);
  };

  // Sort Handler
  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortOrder('desc');
    }
  };

  // Processed Items (Sorted & Paginated)
  const items = useMemo(() => {
    const rawItems: any[] = reportData?.items || [];
    if (!sortKey) return rawItems;

    return [...rawItems].sort((a, b) => {
      let valA = a[sortKey];
      let valB = b[sortKey];

      if (valA == null || valB == null) {
        if (valA == null && valB == null) return 0;
        return valA == null ? 1 : -1;
      }

      if (typeof valA === 'string') {
        const cmp = valA.localeCompare(String(valB), 'zh-CN');
        return sortOrder === 'asc' ? cmp : -cmp;
      }
      return sortOrder === 'asc' ? valA - valB : valB - valA;
    });
  }, [reportData?.items, sortKey, sortOrder]);

  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, currentPage, pageSize]);

  // Options from backend
  const options = reportData?.options || { vendors: [], sites: [], roles: [], isps: [] };
  const summary = reportData?.summary || {};
  const summaryHasNoData = String(summary.sample_quality || '').toUpperCase() === 'NO_DATA';

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50 dark:bg-zinc-950">
      {/* Top Header */}
      <PageHero
        icon={FileSpreadsheet}
        title={zh ? '监控报表' : 'Monitoring Reports'}
        subtitle={
          zh
            ? '全网接口流量利用率、网络设备运行负荷与互联网出口链路多维度报表分析与数据检索'
            : 'Interactive multi-dimensional reports for interfaces, devices, and outbound WAN links'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <a
              href="/monitor/dashboards"
              className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-3.5 py-2 text-xs font-bold text-cyan-700 hover:bg-cyan-500/20 dark:text-cyan-300 transition-colors cursor-pointer shadow-2xs"
              title={zh ? '前往 Grafana 查看实时可视化时序大盘' : 'Go to Grafana real-time monitoring dashboards'}
            >
              <BarChart2 size={14} />
              <span>{zh ? 'Grafana 监控大盘' : 'Grafana Dashboards'}</span>
            </a>

            <button
              type="button"
              onClick={() => void fetchData()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-semibold text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50 cursor-pointer shadow-2xs"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin text-cyan-600' : ''} />
              <span>{zh ? '刷新数据' : 'Refresh'}</span>
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
        {/* Toast / Notification Banner */}
        {successMessage && (
          <div className="flex items-center justify-between gap-2 rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/50 p-3.5 text-xs text-emerald-800 dark:text-emerald-300 shadow-2xs animate-in fade-in">
            <div className="flex items-center gap-2">
              <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
              <span className="font-semibold text-sm">{successMessage}</span>
            </div>
            <button
              onClick={() => setSuccessMessage(null)}
              className="text-emerald-600 hover:text-emerald-800 text-xs cursor-pointer font-bold"
            >
              ✕
            </button>
          </div>
        )}
        {errorMessage && (
          <div role="alert" className="flex items-center justify-between gap-2 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/50 p-3.5 text-xs text-rose-800 dark:text-rose-300 shadow-2xs animate-in fade-in">
            <div className="flex items-center gap-2">
              <AlertCircle size={18} className="text-rose-600 shrink-0" />
              <span className="font-semibold text-sm">{errorMessage}</span>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-rose-600 hover:text-rose-800 text-xs cursor-pointer font-bold"
            >
              ✕
            </button>
          </div>
        )}
        {exportErrorMessage && (
          <div role="alert" className="flex items-center justify-between gap-2 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/50 p-3.5 text-xs text-rose-800 dark:text-rose-300 shadow-2xs animate-in fade-in">
            <div className="flex items-center gap-2">
              <AlertCircle size={18} className="text-rose-600 shrink-0" />
              <span className="font-semibold text-sm">{exportErrorMessage}</span>
            </div>
            <button type="button" onClick={() => setExportErrorMessage(null)} className="text-rose-600 hover:text-rose-800 text-xs cursor-pointer font-bold" aria-label={zh ? '关闭导出错误' : 'Dismiss export error'}>✕</button>
          </div>
        )}

        {/* Active Report Header & Quick Actions */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 dark:border-zinc-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-700 dark:text-cyan-400 font-bold text-sm">
              {activeTab === 'interfaces' && <Activity size={17} />}
              {activeTab === 'devices' && <Server size={17} />}
              {activeTab === 'outbound' && <Globe size={17} />}
              <span>
                {activeTab === 'interfaces'
                  ? (zh ? '全网接口流量与利用率报表' : 'Interface Traffic & Utilization Report')
                  : activeTab === 'devices'
                  ? (zh ? '网络设备运行与资源报表' : 'Device Performance & Health Report')
                  : (zh ? '互联网出口与 WAN 链路报表' : 'Outbound WAN Probes Report')}
              </span>
            </div>
            <span className="hidden sm:inline text-xs text-slate-400 dark:text-zinc-500">
              {zh ? '（已迁移至左侧【监控报表】子菜单，可随时切换并自动折叠）' : '(Switch report types in the left sidebar menu)'}
            </span>
          </div>

          {/* Export Buttons */}
          <div className="flex items-center gap-2 relative">
            <button
              type="button"
              onClick={() => void handleExport('xlsx', true)}
              disabled={Boolean(downloadingKey)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white px-3.5 py-2 text-xs font-bold shadow-xs hover:shadow-sm transition-all disabled:opacity-50 cursor-pointer active:scale-98"
              title={activeTab === 'devices' && filters.highLoadOnly
                ? (zh ? '仅导出有效采样且达到 CPU / 内存阈值的设备' : 'Export only devices with valid CPU or memory samples above the thresholds')
                : (zh ? '导出当前表格筛选结果 (Excel .xlsx)' : 'Export current filtered table to Excel')}
            >
              <FileSpreadsheet size={14} className={downloadingKey?.includes('xlsx') ? 'animate-spin' : ''} />
              <span>{zh ? '导出当前筛选 (Excel)' : 'Export Filtered (.xlsx)'}</span>
            </button>

            <button
              type="button"
              onClick={() => void handleExport('csv', true)}
              disabled={Boolean(downloadingKey)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-700 dark:text-zinc-200 px-3 py-2 text-xs font-semibold shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
              title={activeTab === 'devices' && filters.highLoadOnly
                ? (zh ? '仅导出有效采样且达到 CPU / 内存阈值的设备' : 'Export only devices with valid CPU or memory samples above the thresholds')
                : undefined}
              aria-label={zh ? '导出带 UTF-8 BOM 的通用 CSV 文本' : 'Export CSV with UTF-8 BOM'}
            >
              <Download size={13} className={downloadingKey?.includes('csv') ? 'animate-spin' : ''} />
              <span>CSV</span>
            </button>

            {/* Authoritative multi-sheet export dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowFullExportMenu(!showFullExportMenu)}
                className="inline-flex items-center gap-1 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 px-2.5 py-2 text-xs font-semibold hover:bg-slate-200 dark:hover:bg-zinc-700 cursor-pointer"
                title={zh ? '下载包含多工作表的权威完整报告' : 'Download multi-sheet full workbook'}
              >
                <Layers size={13} />
                <ChevronDown size={13} />
              </button>

              {showFullExportMenu && (
                <div className="absolute right-0 top-full mt-1.5 w-64 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-xl p-2 z-50 animate-in fade-in">
                  <div className="text-[11px] font-bold text-slate-400 dark:text-zinc-400 px-2 py-1 uppercase tracking-wider">
                    {zh ? '官方权威多工作表导出' : 'Authoritative Multi-Sheet'}
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleExport('xlsx', false)}
                    className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs font-medium text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 text-left cursor-pointer"
                  >
                    <span className="flex items-center gap-2">
                      <FileSpreadsheet size={14} className="text-emerald-600" />
                      <span>{zh ? '导出全量多工作表 Excel' : 'Full Multi-Sheet XLSX'}</span>
                    </span>
                    <span className="text-[10px] bg-slate-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-slate-500">
                      {activeTab === 'interfaces' ? '4 Sheets' : activeTab === 'devices' ? '2 Sheets' : '1 Sheet'}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleExport('csv', false)}
                    className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-xs font-medium text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 text-left cursor-pointer"
                  >
                    <Download size={14} className="text-blue-600" />
                    <span>{zh ? '导出全量合并 CSV' : 'Full Combined CSV'}</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Top KPI Metrics Cards */}
        {activeTab === 'interfaces' && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <div className="rounded-2xl border border-slate-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-slate-500 dark:text-zinc-400">
                {zh ? '接口总数' : 'Total Ports'}
              </div>
              <div className="text-2xl font-black text-slate-900 dark:text-zinc-100 mt-1">
                {summary.total_interfaces ?? '--'}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 flex items-center gap-1">
                <span>{zh ? '当前筛选总条数' : 'Total matching'}</span>
              </div>
            </div>

            <div className="rounded-2xl border border-emerald-500/20 dark:border-emerald-500/20 bg-emerald-50/40 dark:bg-emerald-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-emerald-700 dark:text-emerald-400">
                {zh ? '运行状态 UP' : 'Ports Oper UP'}
              </div>
              <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1">
                {summary.up_interfaces ?? '--'}
              </div>
              <div className="text-[11px] text-emerald-600/70 mt-0.5">
                {summary.down_interfaces == null ? (zh ? '采样数据不可用' : 'Sample unavailable') : summary.down_interfaces > 0 ? `${summary.down_interfaces} DOWN` : (zh ? '无异常离线端口' : 'All UP')}
              </div>
            </div>

            <div className="rounded-2xl border border-amber-500/20 dark:border-amber-500/20 bg-amber-50/40 dark:bg-amber-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-amber-700 dark:text-amber-400">
                {zh ? '高负荷预警 (>70%)' : 'High Load Ports'}
              </div>
              <div className="text-2xl font-black text-amber-600 dark:text-amber-400 mt-1">
                {summaryHasNoData ? UNAVAILABLE_VALUE : (summary.high_util_count ?? UNAVAILABLE_VALUE)}
              </div>
              <div className="text-[11px] text-amber-600/70 mt-0.5">
                {summaryHasNoData || summary.critical_util_count == null ? (zh ? '采样数据不可用' : 'Sample unavailable') : summary.critical_util_count > 0 ? `${summary.critical_util_count} ${zh ? '项严重告警 (>85%)' : 'critical (>85%)'}` : (zh ? '无严重瓶颈' : 'No Critical')}
              </div>
            </div>

            <div className="rounded-2xl border border-rose-500/20 dark:border-rose-500/20 bg-rose-50/40 dark:bg-rose-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-rose-700 dark:text-rose-400">
                {zh ? '物理错包/丢包端口' : 'Error / Discard Ports'}
              </div>
              <div className="text-2xl font-black text-rose-600 dark:text-rose-400 mt-1">
                {summary.error_interfaces_count ?? UNAVAILABLE_VALUE}
              </div>
              <div className="text-[11px] text-rose-600/70 mt-0.5">
                {summary.error_interfaces_count == null ? (zh ? '计数数据不可用' : 'Count unavailable') : summary.error_interfaces_count > 0 ? (zh ? '需排查光模块与线缆' : 'Check optic cables') : (zh ? '物理层健康' : 'Normal')}
              </div>
            </div>

            <div className="rounded-2xl border border-cyan-500/20 dark:border-cyan-500/20 bg-cyan-50/40 dark:bg-cyan-950/20 p-4 shadow-2xs col-span-2 sm:col-span-1">
              <div className="text-[11px] font-bold text-cyan-700 dark:text-cyan-400">
                {zh ? '全网平均利用率' : 'Avg Utilization'}
              </div>
              <div className="text-2xl font-black text-cyan-600 dark:text-cyan-400 mt-1">
                {formatMetric(summary.avg_utilization, '%')}
              </div>
              <div className="text-[11px] text-cyan-600/70 mt-0.5">
                {summaryHasNoData
                  ? (zh ? 'NO_DATA · 无有效采样' : 'NO_DATA · No valid sample')
                  : `${zh ? '基于 5m 时序均值' : '5m sliding rate'} · ${formatSampleTime(summary.sample_time, language)}`}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'devices' && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-2xl border border-slate-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-slate-500 dark:text-zinc-400">{zh ? '纳管设备总数' : 'Total Devices'}</div>
              <div className="text-2xl font-black text-slate-900 dark:text-zinc-100 mt-1">{summary.total_devices ?? '--'}</div>
              <div className="text-[11px] text-slate-400 mt-0.5">{zh ? '全网设备资产' : 'Managed CMDB'}</div>
            </div>

            <div className="rounded-2xl border border-emerald-500/20 dark:border-emerald-500/20 bg-emerald-50/40 dark:bg-emerald-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-emerald-700 dark:text-emerald-400">{zh ? '在线运行设备' : 'Online Devices'}</div>
              <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1">{summary.online_devices ?? '--'}</div>
              <div className="text-[11px] text-emerald-600/70 mt-0.5">
                {summary.offline_devices == null ? (zh ? '状态数据不可用' : 'Status unavailable') : summary.offline_devices > 0 ? `${summary.offline_devices} ${zh ? '离线' : 'offline'}` : (zh ? '全员在线' : '100% Online')}
              </div>
            </div>

            <div className="rounded-2xl border border-amber-500/20 dark:border-amber-500/20 bg-amber-50/40 dark:bg-amber-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-amber-700 dark:text-amber-400">{zh ? 'CPU 负荷高 (>70%)' : 'High CPU Devices'}</div>
              <div className="text-2xl font-black text-amber-600 dark:text-amber-400 mt-1">{summaryHasNoData ? UNAVAILABLE_VALUE : (summary.high_cpu_count ?? UNAVAILABLE_VALUE)}</div>
              <div className="text-[11px] text-amber-600/70 mt-0.5">{zh ? '平均 CPU' : 'Avg CPU'}: {formatMetric(summary.avg_cpu, '%')}</div>
              <div className="text-[10px] text-slate-400 mt-1">{String(summary.sample_quality || UNAVAILABLE_VALUE).toUpperCase()} · {formatSampleTime(summary.sample_time, language)}</div>
            </div>

            <div className="rounded-2xl border border-rose-500/20 dark:border-rose-500/20 bg-rose-50/40 dark:bg-rose-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-rose-700 dark:text-rose-400">{zh ? '内存负荷高 (>75%)' : 'High Mem Devices'}</div>
              <div className="text-2xl font-black text-rose-600 dark:text-rose-400 mt-1">{summaryHasNoData ? UNAVAILABLE_VALUE : (summary.high_mem_count ?? UNAVAILABLE_VALUE)}</div>
              <div className="text-[11px] text-rose-600/70 mt-0.5">{zh ? '平均内存' : 'Avg Mem'}: {formatMetric(summary.avg_mem, '%')}</div>
              <div className="text-[10px] text-slate-400 mt-1">{String(summary.sample_quality || UNAVAILABLE_VALUE).toUpperCase()} · {formatSampleTime(summary.sample_time, language)}</div>
            </div>
          </div>
        )}

        {activeTab === 'outbound' && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-2xl border border-slate-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-slate-500 dark:text-zinc-400">{zh ? '探测目标总数' : 'Total Probes'}</div>
              <div className="text-2xl font-black text-slate-900 dark:text-zinc-100 mt-1">{summary.total_probes ?? '--'}</div>
              <div className="text-[11px] text-slate-400 mt-0.5">{zh ? '全网出口探针' : 'WAN Targets'}</div>
            </div>

            <div className="rounded-2xl border border-emerald-500/20 dark:border-emerald-500/20 bg-emerald-50/40 dark:bg-emerald-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-emerald-700 dark:text-emerald-400">{zh ? '活跃启用探针' : 'Active Probes'}</div>
              <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1">{summary.active_probes ?? '--'}</div>
              <div className="text-[11px] text-emerald-600/70 mt-0.5">{zh ? '持续轮询中' : 'Polling Active'}</div>
            </div>

            <div className="rounded-2xl border border-cyan-500/20 dark:border-cyan-500/20 bg-cyan-50/40 dark:bg-cyan-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-cyan-700 dark:text-cyan-400">{zh ? '平均网络延迟' : 'Avg Latency'}</div>
              <div className="text-2xl font-black text-cyan-600 dark:text-cyan-400 mt-1">{formatMetric(summary.avg_latency_ms, ' ms')}</div>
              <div className="text-[11px] text-cyan-600/70 mt-0.5">{zh ? '出口公网响应' : 'WAN RTT'}</div>
            </div>

            <div className="rounded-2xl border border-blue-500/20 dark:border-blue-500/20 bg-blue-50/40 dark:bg-blue-950/20 p-4 shadow-2xs">
              <div className="text-[11px] font-bold text-blue-700 dark:text-blue-400">{zh ? '平均丢包率' : 'Avg Packet Loss'}</div>
              <div className="text-2xl font-black text-blue-600 dark:text-blue-400 mt-1">{formatMetric(summary.avg_packet_loss, '%')}</div>
              <div className="text-[11px] text-blue-600/70 mt-0.5">{zh ? '链路传输平稳' : 'Smooth Loss'}</div>
            </div>
          </div>
        )}

        {/* Search & Advanced Filters Container */}
        <div className="rounded-3xl border border-slate-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-4 shadow-2xs space-y-3">
          {/* Main Search Row */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Search Input */}
            <div className="relative flex-1 min-w-[220px]">
              <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={filters.keyword}
                onChange={(e) => setFilters({ ...filters, keyword: e.target.value })}
                onKeyDown={(e) => e.key === 'Enter' && void fetchData()}
                placeholder={
                  activeTab === 'interfaces'
                    ? (zh ? '搜索设备名、管理IP、接口名、描述...' : 'Search device, IP, interface, description...')
                    : activeTab === 'devices'
                    ? (zh ? '搜索设备名、IP、平台、厂商...' : 'Search hostname, IP, platform, vendor...')
                    : (zh ? '搜索探针名称、目标地址、运营商...' : 'Search probe name, target, ISP...')
                }
                className="w-full rounded-2xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 pl-9 pr-4 py-2 text-xs text-slate-900 dark:text-zinc-100 placeholder-slate-400 focus:border-cyan-500 focus:outline-hidden focus:ring-2 focus:ring-cyan-500/20 transition-all"
              />
            </div>

            {/* Quick Status Selector */}
            {activeTab === 'interfaces' && (
              <select
                value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                className="rounded-2xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-2 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
              >
                <option value="all">{zh ? '全部接口状态' : 'All Status'}</option>
                <option value="UP">{zh ? '🟢 仅看 UP 状态' : '🟢 Oper UP Only'}</option>
                <option value="DOWN">{zh ? '🔴 仅看 DOWN 状态' : '🔴 Oper DOWN Only'}</option>
              </select>
            )}

            {activeTab === 'devices' && (
              <select
                value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                className="rounded-2xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-2 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
              >
                <option value="all">{zh ? '全部在线状态' : 'All Online Status'}</option>
                <option value="ONLINE">{zh ? '🟢 在线 (Online)' : '🟢 Online'}</option>
                <option value="OFFLINE">{zh ? '🔴 离线 (Offline)' : '🔴 Offline'}</option>
              </select>
            )}

            {/* Quick Utilization Selector */}
            {activeTab === 'interfaces' && (
              <select
                value={filters.minUtil}
                onChange={(e) => setFilters({ ...filters, minUtil: e.target.value })}
                title={zh ? '无有效采样值的接口不会匹配利用率阈值' : 'Interfaces without valid samples do not match utilization thresholds'}
                className="rounded-2xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-2 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
              >
                <option value="">{zh ? '全部利用率区间' : 'All Utilization'}</option>
                <option value="50">{zh ? '⚠️ 利用率 ≥ 50%' : '⚠️ Util ≥ 50%'}</option>
                <option value="70">{zh ? '🚨 利用率 ≥ 70%' : '🚨 Util ≥ 70%'}</option>
                <option value="85">{zh ? '🔥 严重过载 ≥ 85%' : '🔥 Critical ≥ 85%'}</option>
              </select>
            )}

            {/* Toggle Advanced Filters Button */}
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className={`inline-flex items-center gap-1.5 rounded-2xl border px-3.5 py-2 text-xs font-bold transition-all cursor-pointer ${
                showAdvanced || activeAdvancedFilterCount > 0
                  ? 'border-cyan-500 bg-cyan-50 dark:bg-cyan-950/40 text-cyan-700 dark:text-cyan-300'
                  : 'border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-700'
              }`}
            >
              <SlidersHorizontal size={13} />
              <span>{zh ? '高级筛选选项' : 'Advanced Filters'}</span>
              {activeAdvancedFilterCount > 0 && (
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-cyan-600 text-[10px] text-white font-black">
                  {activeAdvancedFilterCount}
                </span>
              )}
              {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>

            {/* Reset Button */}
            {activeAdvancedFilterCount > 0 || filters.keyword ? (
              <button
                type="button"
                onClick={handleResetFilters}
                className="inline-flex items-center gap-1 rounded-2xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200 transition-colors cursor-pointer"
                title={zh ? '重置清空所有筛选条件' : 'Clear all filters'}
              >
                <RotateCcw size={12} />
                <span>{zh ? '清空' : 'Reset'}</span>
              </button>
            ) : null}
          </div>

          {/* Collapsible Advanced Filters Section */}
          {showAdvanced && (
            <div className="pt-3 border-t border-slate-200/70 dark:border-zinc-800/80 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 animate-in fade-in">
              {/* Vendor Filter */}
              <div>
                <label className="block text-[11px] font-bold text-slate-500 dark:text-zinc-400 mb-1">
                  {zh ? '设备厂商 (Vendor)' : 'Vendor'}
                </label>
                <select
                  value={filters.vendor}
                  onChange={(e) => setFilters({ ...filters, vendor: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-1.5 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
                >
                  <option value="all">{zh ? '全部厂商' : 'All Vendors'}</option>
                  {(options.vendors || []).map((v: string) => (
                    <option key={v} value={v}>
                      {v.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>

              {/* Site Filter */}
              <div>
                <label className="block text-[11px] font-bold text-slate-500 dark:text-zinc-400 mb-1">
                  {zh ? '所属站点 (Site)' : 'Site'}
                </label>
                <select
                  value={filters.site}
                  onChange={(e) => setFilters({ ...filters, site: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-1.5 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
                >
                  <option value="all">{zh ? '全部站点' : 'All Sites'}</option>
                  {(options.sites || []).map((s: string) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>

              {/* Role Filter */}
              <div>
                <label className="block text-[11px] font-bold text-slate-500 dark:text-zinc-400 mb-1">
                  {zh ? '设备角色 (Device Role)' : 'Role'}
                </label>
                <select
                  value={filters.role}
                  onChange={(e) => setFilters({ ...filters, role: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-1.5 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
                >
                  <option value="all">{zh ? '全部角色' : 'All Roles'}</option>
                  {(options.roles || []).map((r: string) => (
                    <option key={r} value={r}>
                      {r.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>

              {/* Checkboxes / Specific Switches */}
              <div className="flex flex-col justify-end gap-2 pb-0.5">
                {activeTab === 'interfaces' && (
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-zinc-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={filters.hasErrors}
                      onChange={(e) => setFilters({ ...filters, hasErrors: e.target.checked })}
                      className="rounded text-cyan-600 focus:ring-cyan-500"
                    />
                    <span>{zh ? '仅显示存在物理错包/丢包的端口' : 'Only ports with CRC/discards'}</span>
                  </label>
                )}

                {activeTab === 'devices' && (
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-zinc-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={filters.highLoadOnly}
                      onChange={(e) => setFilters({ ...filters, highLoadOnly: e.target.checked })}
                      className="rounded text-cyan-600 focus:ring-cyan-500"
                    />
                    <span title={zh ? '无有效 VM 采样的设备不会按 0% 或正常负荷匹配；筛选导出也使用此规则。' : 'Devices without valid VM samples are not treated as 0% or normal; filtered exports use the same rule.'}>
                      {zh ? '仅显示有效采样的高负荷设备 (CPU>70% 或 内存>75%)' : 'Only sampled high-load devices (CPU >70% or memory >75%)'}
                    </span>
                  </label>
                )}

                {activeTab === 'outbound' && (
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 dark:text-zinc-400 mb-1">
                      {zh ? '所属运营商 (ISP)' : 'ISP'}
                    </label>
                    <select
                      value={filters.isp}
                      onChange={(e) => setFilters({ ...filters, isp: e.target.value })}
                      className="w-full rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 px-3 py-1.5 text-xs text-slate-700 dark:text-zinc-200 focus:border-cyan-500 focus:outline-hidden cursor-pointer"
                    >
                      <option value="all">{zh ? '全部运营商' : 'All ISPs'}</option>
                      {(options.isps || []).map((isp: string) => (
                        <option key={isp} value={isp}>
                          {isp}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Data Table Container */}
        <div className="rounded-3xl border border-slate-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden flex flex-col">
          {/* Table Toolbar Header */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 border-b border-slate-200/70 dark:border-zinc-800/80 bg-slate-50/50 dark:bg-zinc-800/30">
            <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-zinc-300">
              <span className="font-bold text-slate-900 dark:text-zinc-100">
                {activeTab === 'interfaces'
                  ? (zh ? '全网接口流量与健康明细表' : 'Interfaces Traffic & Health Table')
                  : activeTab === 'devices'
                  ? (zh ? '网络设备运行与资源负荷清单' : 'Devices Performance & Load Table')
                  : (zh ? '互联网出口与 WAN 链路运行清单' : 'Outbound Links & Probes Table')}
              </span>
              <span className="text-slate-400">|</span>
              <span>
                {zh ? `共找到 ${items.length} 条记录` : `${items.length} records found`}
              </span>
            </div>

          </div>

          {/* Table Wrapper */}
          <div className="overflow-x-auto min-h-[300px]">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-24 text-slate-400 gap-3">
                <RefreshCw size={24} className="animate-spin text-cyan-600" />
                <span className="text-xs font-semibold">{zh ? '正在加载最新时序与CMDB元数据…' : 'Loading live telemetry and CMDB metadata…'}</span>
              </div>
            ) : paginatedItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-2 text-center">
                <Filter size={32} className="text-slate-300 dark:text-zinc-700 stroke-1" />
                <div className="text-sm font-bold text-slate-700 dark:text-zinc-300">
                  {zh ? '未检索到匹配的监控数据' : 'No matching records found'}
                </div>
                <p className="text-xs text-slate-400 max-w-sm">
                  {zh
                    ? '请尝试调整搜索关键词、扩大厂商/站点筛选范围或清空筛选条件'
                    : 'Try modifying search keywords or clearing advanced filter options'}
                </p>
                {activeAdvancedFilterCount > 0 || filters.keyword ? (
                  <button
                    onClick={handleResetFilters}
                    className="mt-2 text-xs font-bold text-cyan-600 hover:text-cyan-700 underline cursor-pointer"
                  >
                    {zh ? '立即清空所有筛选' : 'Clear all filters'}
                  </button>
                ) : null}
              </div>
            ) : (
              <table className="w-full text-left text-xs border-collapse">
                {/* Table Header */}
                <thead>
                  <tr className="border-b border-slate-200 dark:border-zinc-800 bg-slate-100/70 dark:bg-zinc-800/60 text-slate-600 dark:text-zinc-300 font-bold">
                    {activeTab === 'interfaces' && (
                      <>
                        <th
                          className="py-3 px-4 cursor-pointer hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition-colors"
                          onClick={() => handleSort('hostname')}
                        >
                          <div className="flex items-center gap-1.5">
                            <span>{zh ? '设备 / 管理 IP' : 'Device / IP'}</span>
                            {sortKey === 'hostname' ? (
                              sortOrder === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                            ) : (
                              <ArrowUpDown size={11} className="text-slate-400" />
                            )}
                          </div>
                        </th>
                        <th className="py-3 px-3">{zh ? '站点 / 角色' : 'Site / Role'}</th>
                        <th
                          className="py-3 px-3 cursor-pointer hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition-colors"
                          onClick={() => handleSort('interface_name')}
                        >
                          <div className="flex items-center gap-1.5">
                            <span>{zh ? '接口名称 / 描述' : 'Interface / Desc'}</span>
                            {sortKey === 'interface_name' ? (
                              sortOrder === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                            ) : (
                              <ArrowUpDown size={11} className="text-slate-400" />
                            )}
                          </div>
                        </th>
                        <th className="py-3 px-3 text-center">{zh ? '运行状态' : 'Oper Status'}</th>
                        <th className="py-3 px-3 text-right">{zh ? '物理速率' : 'Speed'}</th>
                        <th className="py-3 px-3 text-right">{zh ? '实时流量 (入/出)' : 'In / Out Traffic'}</th>
                        <th
                          className="py-3 px-4 text-right cursor-pointer hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition-colors"
                          onClick={() => handleSort('max_util')}
                        >
                          <div className="flex items-center justify-end gap-1.5">
                            <span>{zh ? '带宽利用率 (峰值)' : 'Bandwidth Util'}</span>
                            {sortKey === 'max_util' ? (
                              sortOrder === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                            ) : (
                              <ArrowUpDown size={11} className="text-slate-400" />
                            )}
                          </div>
                        </th>
                        <th className="py-3 px-3 text-center">{zh ? '错包 / 丢包' : 'Errors / Discards'}</th>
                        <th className="py-3 px-4">{zh ? '预警评级与处置建议' : 'Alert & Advice'}</th>
                      </>
                    )}

                    {activeTab === 'devices' && (
                      <>
                        <th
                          className="py-3 px-4 cursor-pointer hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition-colors"
                          onClick={() => handleSort('hostname')}
                        >
                          <div className="flex items-center gap-1.5">
                            <span>{zh ? '设备名称 / 管理 IP' : 'Hostname / IP'}</span>
                            {sortKey === 'hostname' ? (
                              sortOrder === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                            ) : (
                              <ArrowUpDown size={11} className="text-slate-400" />
                            )}
                          </div>
                        </th>
                        <th className="py-3 px-3">{zh ? '厂商 / 平台' : 'Vendor / Platform'}</th>
                        <th className="py-3 px-3">{zh ? '站点 / 角色' : 'Site / Role'}</th>
                        <th className="py-3 px-3 text-center">{zh ? '在线状态' : 'Status'}</th>
                        <th
                          className="py-3 px-4 text-right cursor-pointer hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition-colors"
                          onClick={() => handleSort('cpu_usage')}
                        >
                          <div className="flex items-center justify-end gap-1.5">
                            <span>{zh ? 'CPU 使用率' : 'CPU Load'}</span>
                            {sortKey === 'cpu_usage' ? (
                              sortOrder === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                            ) : (
                              <ArrowUpDown size={11} className="text-slate-400" />
                            )}
                          </div>
                        </th>
                        <th
                          className="py-3 px-4 text-right cursor-pointer hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition-colors"
                          onClick={() => handleSort('memory_usage')}
                        >
                          <div className="flex items-center justify-end gap-1.5">
                            <span>{zh ? '内存利用率' : 'Memory Load'}</span>
                            {sortKey === 'memory_usage' ? (
                              sortOrder === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                            ) : (
                              <ArrowUpDown size={11} className="text-slate-400" />
                            )}
                          </div>
                        </th>
                        <th className="py-3 px-3 text-right">{zh ? '运行温度' : 'Temp'}</th>
                        <th className="py-3 px-4">{zh ? '运行评估与采样信息' : 'Assessment & sample'}</th>
                      </>
                    )}

                    {activeTab === 'outbound' && (
                      <>
                        <th className="py-3 px-4">{zh ? '探针目标名称' : 'Probe Name'}</th>
                        <th className="py-3 px-3">{zh ? '运营商 / 线路' : 'ISP'}</th>
                        <th className="py-3 px-3">{zh ? '探测地址 / 协议' : 'Target / Type'}</th>
                        <th className="py-3 px-3 text-center">{zh ? '启用状态' : 'Active'}</th>
                        <th className="py-3 px-3 text-right">{zh ? '实时延迟 (ms)' : 'Latency'}</th>
                        <th className="py-3 px-3 text-right">{zh ? '丢包率 (%)' : 'Loss'}</th>
                        <th className="py-3 px-4">{zh ? '链路综合健康' : 'Health Rating'}</th>
                      </>
                    )}
                  </tr>
                </thead>

                {/* Table Body */}
                <tbody className="divide-y divide-slate-200/70 dark:divide-zinc-800/70">
                  {activeTab === 'interfaces' &&
                    paginatedItems.map((item: any, idx: number) => {
                      const maxUtil = toNullableNumber(item.max_util);
                      const sampleQuality = String(item.sample_quality || '').toUpperCase();
                      const noValidSample = sampleQuality === 'NO_DATA' || String(item.risk_level || '').toUpperCase() === 'NO_DATA' || maxUtil === null;
                      const isHigh = maxUtil !== null && maxUtil >= 70.0;
                      const isCritical = maxUtil !== null && maxUtil >= 85.0;
                      const hasErr = (item.total_errors || 0) > 0;

                      return (
                        <tr
                          key={item.id || idx}
                          className="hover:bg-cyan-50/30 dark:hover:bg-cyan-950/20 transition-colors text-slate-700 dark:text-zinc-200"
                        >
                          {/* Device & IP */}
                          <td className="py-3 px-4">
                            <div className="font-bold text-slate-900 dark:text-zinc-100 flex items-center gap-1.5">
                              <span>{item.hostname}</span>
                              <span className="rounded bg-slate-100 dark:bg-zinc-800 px-1 py-0.2 text-[10px] font-mono text-slate-500 uppercase">
                                {item.vendor}
                              </span>
                            </div>
                            <div className="text-[11px] font-mono text-slate-400 mt-0.5">{item.ip_address}</div>
                          </td>

                          {/* Site & Role */}
                          <td className="py-3 px-3">
                            <div className="font-medium text-slate-700 dark:text-zinc-300">{item.site_name}</div>
                            <div className="text-[10px] text-slate-400 uppercase tracking-wider">{item.role}</div>
                          </td>

                          {/* Interface & Desc */}
                          <td className="py-3 px-3">
                            <div className="font-mono font-semibold text-cyan-700 dark:text-cyan-400">
                              {item.interface_name}
                            </div>
                            {item.description && (
                              <div className="text-[11px] text-slate-400 truncate max-w-[200px]" title={item.description}>
                                {item.description}
                              </div>
                            )}
                          </td>

                          {/* Oper Status */}
                          <td className="py-3 px-3 text-center">
                            {item.oper_status === 'UP' ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-950/70 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-400">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                                <span>UP</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 dark:bg-rose-950/70 px-2 py-0.5 text-[10px] font-bold text-rose-700 dark:text-rose-400">
                                <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                                <span>{item.oper_status}</span>
                              </span>
                            )}
                          </td>

                          {/* Physical Speed */}
                          <td className="py-3 px-3 text-right font-mono font-medium text-slate-600 dark:text-zinc-400">
                            {item.speed_str ?? UNAVAILABLE_VALUE}
                          </td>

                          {/* In / Out bps */}
                          <td className="py-3 px-3 text-right font-mono">
                            <div className="text-slate-800 dark:text-zinc-200">↓ {item.in_bps_str ?? UNAVAILABLE_VALUE}</div>
                            <div className="text-[11px] text-slate-400">↑ {item.out_bps_str ?? UNAVAILABLE_VALUE}</div>
                          </td>

                          {/* Bandwidth Utilization */}
                          <td className="py-3 px-4 text-right">
                            <div className="font-mono font-bold text-xs">
                              <span
                                className={
                                  isCritical
                                    ? 'text-rose-600 dark:text-rose-400'
                                    : isHigh
                                    ? 'text-amber-600 dark:text-amber-400'
                                    : 'text-slate-700 dark:text-zinc-200'
                                }
                              >
                                {maxUtil === null ? UNAVAILABLE_VALUE : `${maxUtil.toFixed(1)}%`}
                              </span>
                            </div>
                            {/* Visual Progress Bar */}
                            <div className="mt-1 h-1.5 w-24 ml-auto rounded-full bg-slate-100 dark:bg-zinc-800 overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all ${
                                  isCritical
                                    ? 'bg-rose-500'
                                    : isHigh
                                    ? 'bg-amber-500'
                                    : maxUtil > 30
                                    ? 'bg-cyan-500'
                                    : 'bg-emerald-500'
                                }`}
                                style={{ width: `${maxUtil === null ? 0 : Math.min(maxUtil, 100)}%` }}
                              />
                            </div>
                          </td>

                          {/* Errors / Discards */}
                          <td className="py-3 px-3 text-center font-mono">
                            {hasErr ? (
                              <span className="inline-flex items-center gap-1 rounded bg-rose-100 dark:bg-rose-950/60 px-1.5 py-0.5 text-[11px] font-bold text-rose-700 dark:text-rose-400">
                                <AlertTriangle size={11} />
                                <span>{item.total_errors.toFixed(0)}</span>
                              </span>
                            ) : (
                              <span className="text-slate-400 text-[11px]">0</span>
                            )}
                          </td>

                          {/* Alert Level & Advice */}
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-1.5">
                              {noValidSample ? (
                                <span className="rounded bg-slate-100 dark:bg-zinc-800 px-1.5 py-0.2 text-[10px] font-bold text-slate-600 dark:text-zinc-300 shrink-0">NO_DATA</span>
                              ) : item.alert_level === 'CRITICAL' && (
                                <span className="rounded bg-rose-100 dark:bg-rose-950 px-1.5 py-0.2 text-[10px] font-bold text-rose-700 dark:text-rose-300 shrink-0">
                                  {zh ? '严重' : 'Critical'}
                                </span>
                              )}
                              {!noValidSample && item.alert_level === 'WARNING' && (
                                <span className="rounded bg-amber-100 dark:bg-amber-950 px-1.5 py-0.2 text-[10px] font-bold text-amber-700 dark:text-amber-300 shrink-0">
                                  {zh ? '预警' : 'Warning'}
                                </span>
                              )}
                              <span className="text-[11px] text-slate-500 dark:text-zinc-400 truncate max-w-xs">
                                {noValidSample ? (zh ? '无有效采样，暂不可评估' : 'No valid sample; assessment unavailable') : item.advice}
                              </span>
                            </div>
                            <div className="mt-1 text-[10px] text-slate-400" title={item.sample_time || ''}>
                              {sampleQuality || (noValidSample ? 'NO_DATA' : (zh ? '采样质量未知' : 'Sample quality unknown'))}
                              {' · '}{formatSampleTime(item.sample_time, language)}
                            </div>
                          </td>
                        </tr>
                      );
                    })}

                  {activeTab === 'devices' &&
                    paginatedItems.map((item: any, idx: number) => {
                      const cpu = toNullableNumber(item.cpu_usage);
                      const mem = toNullableNumber(item.memory_usage);
                      const sampleQuality = String(item.sample_quality || '').toUpperCase();
                      const noValidSample = sampleQuality === 'NO_DATA' || String(item.risk_level || '').toUpperCase() === 'NO_DATA' || (cpu === null && mem === null);

                      return (
                        <tr
                          key={item.id || idx}
                          className="hover:bg-cyan-50/30 dark:hover:bg-cyan-950/20 transition-colors text-slate-700 dark:text-zinc-200"
                        >
                          <td className="py-3 px-4">
                            <div className="font-bold text-slate-900 dark:text-zinc-100">{item.hostname}</div>
                            <div className="text-[11px] font-mono text-slate-400 mt-0.5">{item.ip_address}</div>
                          </td>

                          <td className="py-3 px-3">
                            <div className="font-medium text-slate-700 dark:text-zinc-300 uppercase">{item.vendor}</div>
                            <div className="text-[10px] font-mono text-slate-400">{item.platform}</div>
                          </td>

                          <td className="py-3 px-3">
                            <div className="text-slate-700 dark:text-zinc-300">{item.site_name}</div>
                            <div className="text-[10px] text-slate-400 uppercase tracking-wider">{item.role}</div>
                          </td>

                          <td className="py-3 px-3 text-center">
                            {item.status === 'ONLINE' ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-950/70 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-400">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                <span>ONLINE</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 dark:bg-rose-950/70 px-2 py-0.5 text-[10px] font-bold text-rose-700 dark:text-rose-400">
                                <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                                <span>{item.status}</span>
                              </span>
                            )}
                          </td>

                          {/* CPU Load */}
                          <td className="py-3 px-4 text-right">
                            <div className="font-mono font-bold text-xs">
                              <span className={cpu !== null && cpu >= 85 ? 'text-rose-600' : cpu !== null && cpu >= 70 ? 'text-amber-600' : cpu === null ? 'text-slate-400' : ''}>
                                {formatMetric(cpu, '%')}
                              </span>
                            </div>
                            <div className="mt-1 h-1.5 w-20 ml-auto rounded-full bg-slate-100 dark:bg-zinc-800 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  cpu === null ? '' : cpu >= 85 ? 'bg-rose-500' : cpu >= 70 ? 'bg-amber-500' : 'bg-cyan-500'
                                }`}
                                style={{ width: `${cpu === null ? 0 : Math.min(cpu, 100)}%` }}
                              />
                            </div>
                          </td>

                          {/* Memory Load */}
                          <td className="py-3 px-4 text-right">
                            <div className="font-mono font-bold text-xs">
                              <span className={mem !== null && mem >= 90 ? 'text-rose-600' : mem !== null && mem >= 75 ? 'text-amber-600' : mem === null ? 'text-slate-400' : ''}>
                                {formatMetric(mem, '%')}
                              </span>
                            </div>
                            <div className="mt-1 h-1.5 w-20 ml-auto rounded-full bg-slate-100 dark:bg-zinc-800 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  mem === null ? '' : mem >= 90 ? 'bg-rose-500' : mem >= 75 ? 'bg-amber-500' : 'bg-emerald-500'
                                }`}
                                style={{ width: `${mem === null ? 0 : Math.min(mem, 100)}%` }}
                              />
                            </div>
                          </td>

                          <td className="py-3 px-3 text-right font-mono text-slate-600 dark:text-zinc-400">
                            {item.temperature_str ?? UNAVAILABLE_VALUE}
                          </td>

                          <td className="py-3 px-4">
                            <div className="flex items-center gap-1.5">
                              {noValidSample ? (
                                <span className="rounded bg-slate-100 dark:bg-zinc-800 px-1.5 py-0.2 text-[10px] font-bold text-slate-600 dark:text-zinc-300 shrink-0">NO_DATA</span>
                              ) : item.risk_level && item.risk_level !== 'NORMAL' && (
                                <span
                                  className={`rounded px-1.5 py-0.2 text-[10px] font-bold shrink-0 ${
                                    item.risk_level === 'CRITICAL'
                                      ? 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300'
                                      : 'bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300'
                                  }`}
                                >
                                  {item.risk_level}
                                </span>
                              )}
                              <span className="text-[11px] text-slate-500 dark:text-zinc-400 truncate max-w-xs">
                                {noValidSample ? (zh ? '无有效采样，暂不可评估' : 'No valid sample; assessment unavailable') : item.advice}
                              </span>
                            </div>
                            <div className="mt-1 text-[10px] text-slate-400" title={item.sample_time || ''}>
                              {sampleQuality || (noValidSample ? 'NO_DATA' : (zh ? '采样质量未知' : 'Sample quality unknown'))}
                              {' · '}{formatSampleTime(item.sample_time, language)}
                            </div>
                          </td>
                        </tr>
                      );
                    })}

                  {activeTab === 'outbound' &&
                    paginatedItems.map((item: any, idx: number) => (
                      <tr
                        key={item.id || idx}
                        className="hover:bg-cyan-50/30 dark:hover:bg-cyan-950/20 transition-colors text-slate-700 dark:text-zinc-200"
                      >
                        <td className="py-3 px-4 font-bold text-slate-900 dark:text-zinc-100">{item.name}</td>
                        <td className="py-3 px-3 font-medium text-slate-700 dark:text-zinc-300">{item.isp}</td>
                        <td className="py-3 px-3 font-mono text-cyan-700 dark:text-cyan-400">
                          {item.target} ({item.target_type})
                        </td>
                        <td className="py-3 px-3 text-center">
                          <span className="rounded-full bg-emerald-100 dark:bg-emerald-950 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-400">
                            {item.active_str}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right font-mono font-bold text-emerald-600">
                          {formatMetric(item.latency_ms, ' ms')}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-slate-600 dark:text-zinc-400">
                          {formatMetric(item.packet_loss, '%')}
                        </td>
                        <td className="py-3 px-4">
                          <span className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800/60 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                            <CheckCircle2 size={12} />
                            <span>{item.health_grade ?? UNAVAILABLE_VALUE}</span>
                          </span>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Table Pagination Footer */}
          {items.length > 0 && (
            <Pagination
              currentPage={currentPage}
              totalItems={items.length}
              itemsPerPage={pageSize}
              onPageChange={setCurrentPage}
              onItemsPerPageChange={(size) => {
                setPageSize(size);
                setCurrentPage(1);
              }}
              language={language}
              itemLabel={zh ? '条报表记录' : 'records'}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default MonitoringReportsPage;
