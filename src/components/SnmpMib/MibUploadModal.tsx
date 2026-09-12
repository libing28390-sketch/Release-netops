import React, { useState, useEffect, useMemo, useRef } from 'react';
import { X, Trash2, Database, FileText, Search, RefreshCw, Upload, Layers, CheckCircle2, AlertCircle, ChevronDown, ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react';
import { apiRequest } from '../../api/http';
import { ALL_VENDOR_NAMES, NETWORK_VENDOR_GROUPS } from '../../pages/AssetManagement/constants';
import type { MibNodeItem } from './OidPickerModal';
import { ActionIconButton } from '../ui/ActionIconButton';

const MIB_PAGE_SIZE = 40;
type MibStatusFilter = '' | 'parsed' | 'zero_node' | 'unresolved_oid' | 'failed';

const TEMPLATE_METRIC_OPTIONS = [
  { key: 'cpu', labelZh: 'CPU', labelEn: 'CPU' },
  { key: 'memory', labelZh: '内存', labelEn: 'Memory' },
  { key: 'temperature', labelZh: '温度', labelEn: 'Temperature' },
  { key: 'fan', labelZh: '风扇状态', labelEn: 'Fan status' },
  { key: 'power_supply', labelZh: '电源状态', labelEn: 'Power supply status' },
  { key: 'storage', labelZh: '存储使用率', labelEn: 'Storage usage' },
  { key: 'voltage', labelZh: '电压', labelEn: 'Voltage' },
  { key: 'power', labelZh: '功耗', labelEn: 'Power consumption' },
] as const;

export interface MibItem {
  id: string;
  name: string;
  vendor: string;
  filename: string;
  file_size: number;
  node_count: number;
  source_type: 'builtin' | 'user_upload' | string;
  description?: string;
  created_at: string;
  updated_at: string;
  relative_path?: string;
  source_commit?: string;
  parse_status?: string;
  parse_error?: string;
  parser_version?: string;
  resolved_node_count?: number;
  unresolved_node_count?: number;
}

interface MibRepositoryStats {
  module_count: number;
  parsed_module_count: number;
  zero_node_module_count: number;
  failed_module_count: number;
  unresolved_oid_node_count?: number;
  status_counts?: Record<string, number>;
  vendor_counts?: Record<string, number>;
  latest_import?: {
    status?: string;
    source_commit?: string;
    total_files?: number;
    processed_files?: number;
    imported_files?: number;
    updated_files?: number;
    skipped_files?: number;
    failed_files?: number;
    duplicate_files?: number;
    zero_node_files?: number;
    total_nodes?: number;
    started_at?: string;
    completed_at?: string;
  } | null;
}

interface MibUploadModalProps {
  open: boolean;
  onClose: () => void;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onMapNodeToTemplate?: (node: MibNodeItem, metricKey: string) => void;
}

const MibUploadModal: React.FC<MibUploadModalProps> = ({
  open,
  onClose,
  language,
  showToast,
  onMapNodeToTemplate,
}) => {
  const zh = language === 'zh';
  const [mibs, setMibs] = useState<MibItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [vendorFilter, setVendorFilter] = useState('');
  const [vendorDropdownOpen, setVendorDropdownOpen] = useState(false);
  const [vendorSearch, setVendorSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<MibStatusFilter>('');
  const [mibPage, setMibPage] = useState(1);
  const [mibTotal, setMibTotal] = useState(0);
  const [selectedMibId, setSelectedMibId] = useState<string | null>(null);
  const [mibDetail, setMibDetail] = useState<any | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [repositoryStats, setRepositoryStats] = useState<MibRepositoryStats | null>(null);
  const [nodeSearchInput, setNodeSearchInput] = useState('');
  const [nodeSearch, setNodeSearch] = useState('');
  const [nodeSearchResults, setNodeSearchResults] = useState<MibNodeItem[] | null>(null);
  const [nodeSearchLoading, setNodeSearchLoading] = useState(false);
  const [mappingMetricKey, setMappingMetricKey] = useState('cpu');
  const [uploading, setUploading] = useState(false);

  const uploadInputRef = useRef<HTMLInputElement>(null);
  const prevSyncRunningRef = useRef(false);
  const vendorDropdownRef = useRef<HTMLDivElement>(null);
  const listAbortRef = useRef<AbortController | null>(null);
  const listRequestSeqRef = useRef(0);
  const detailAbortRef = useRef<AbortController | null>(null);
  const nodeSearchAbortRef = useRef<AbortController | null>(null);

  const extraMibVendors = useMemo(() => {
    const knownVendors = new Set((ALL_VENDOR_NAMES as readonly string[]).map(vendor => vendor.toLowerCase()));
    return Object.keys(repositoryStats?.vendor_counts || {})
      .filter(vendor => vendor.trim() && !knownVendors.has(vendor.trim().toLowerCase()))
      .sort((left, right) => left.localeCompare(right));
  }, [repositoryStats]);

  const normalizedVendorSearch = vendorSearch.trim().toLowerCase();
  const matchesVendorSearch = (vendor: string) => (
    !normalizedVendorSearch || vendor.toLowerCase().includes(normalizedVendorSearch)
  );
  const visibleVendorGroups = NETWORK_VENDOR_GROUPS
    .map(group => ({
      ...group,
      vendors: group.vendors.filter(matchesVendorSearch),
    }))
    .filter(group => group.vendors.length > 0);
  const visibleExtraMibVendors = extraMibVendors.filter(matchesVendorSearch);

  const chooseVendor = (nextVendor: string) => {
    setMibPage(1);
    setVendorFilter(nextVendor);
    setVendorDropdownOpen(false);
    setVendorSearch('');
  };

  const toggleStatusFilter = (nextStatus: MibStatusFilter) => {
    setMibPage(1);
    setStatusFilter(currentStatus => currentStatus === nextStatus ? '' : nextStatus);
  };

  const loadMibs = async (requestedPage = mibPage, requestedSearch = searchQuery) => {
    const requestId = listRequestSeqRef.current + 1;
    listRequestSeqRef.current = requestId;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;
    const isCurrentRequest = () => !controller.signal.aborted && listRequestSeqRef.current === requestId;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('page', String(requestedPage));
      params.set('page_size', String(MIB_PAGE_SIZE));
      if (requestedSearch.trim()) params.set('search', requestedSearch.trim());
      if (vendorFilter.trim()) params.set('vendor', vendorFilter.trim());
      if (statusFilter) params.set('status', statusFilter);
      const res = await apiRequest<{
        success: boolean;
        data: MibItem[];
        total?: number;
        page?: number;
        stats?: MibRepositoryStats;
      }>(
        `/api/platform-registry/mibs?${params.toString()}`,
        { signal: controller.signal },
      );
      if (!isCurrentRequest()) return;
      setMibs(Array.isArray(res.data) ? res.data : []);
      setMibTotal(typeof res.total === 'number' ? res.total : (Array.isArray(res.data) ? res.data.length : 0));
      setMibPage(typeof res.page === 'number' ? res.page : requestedPage);
      if (res.stats) setRepositoryStats(res.stats);
    } catch (err) {
      if (!isCurrentRequest() || (err instanceof DOMException && err.name === 'AbortError')) return;
      showToast(err instanceof Error ? err.message : (zh ? '加载 MIB 列表失败' : 'Failed to load MIB list'), 'error');
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  };

  const loadDetail = async (id: string) => {
    detailAbortRef.current?.abort();
    nodeSearchAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;
    setSelectedMibId(id);
    setNodeSearchInput('');
    setNodeSearch('');
    setNodeSearchResults(null);
    setNodeSearchLoading(false);
    setLoadingDetail(true);
    try {
      const res = await apiRequest<{ success: boolean; data: any }>(
        `/api/platform-registry/mibs/${id}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setMibDetail(res.data);
    } catch (err) {
      if (controller.signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) return;
      setMibDetail(null);
    } finally {
      if (!controller.signal.aborted) setLoadingDetail(false);
    }
  };

  const searchDetailNodes = async (event: React.FormEvent) => {
    event.preventDefault();
    const query = nodeSearchInput.trim();
    setNodeSearch(query);
    nodeSearchAbortRef.current?.abort();
    if (!query || !selectedMibId) {
      setNodeSearchResults(null);
      setNodeSearchLoading(false);
      return;
    }

    const controller = new AbortController();
    nodeSearchAbortRef.current = controller;
    setNodeSearchLoading(true);
    try {
      const params = new URLSearchParams({
        query,
        mib_id: selectedMibId,
        limit: '200',
        scope: 'node',
      });
      const res = await apiRequest<{ success: boolean; data: MibNodeItem[] }>(
        `/api/platform-registry/mibs/nodes/search?${params.toString()}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setNodeSearchResults(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      if (controller.signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) return;
      setNodeSearchResults([]);
      showToast(err instanceof Error ? err.message : (zh ? '节点搜索失败' : 'Node search failed'), 'error');
    } finally {
      if (!controller.signal.aborted) setNodeSearchLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setMibPage(1);
      setSearchQuery(search.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (open) void loadMibs(mibPage, searchQuery);
    return () => listAbortRef.current?.abort();
  }, [open, searchQuery, vendorFilter, statusFilter, mibPage]);

  useEffect(() => {
    if (!vendorDropdownOpen) return undefined;
    const handleOutsideClick = (event: MouseEvent) => {
      if (vendorDropdownRef.current && !vendorDropdownRef.current.contains(event.target as Node)) {
        setVendorDropdownOpen(false);
        setVendorSearch('');
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [vendorDropdownOpen]);

  useEffect(() => () => {
    listAbortRef.current?.abort();
    detailAbortRef.current?.abort();
    nodeSearchAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!open) {
      detailAbortRef.current?.abort();
      nodeSearchAbortRef.current?.abort();
      setNodeSearchLoading(false);
    }
  }, [open]);

  const [syncState, setSyncState] = useState<{
    running: boolean;
    progress: string;
    last_result?: any;
    repository?: MibRepositoryStats;
  }>({
    running: false,
    progress: 'idle',
  });

  const checkSyncStatus = async () => {
    try {
      const res = await apiRequest<{ success: boolean; data: any }>('/api/platform-registry/mibs/sync-librenms/status');
      if (res.data) {
        setSyncState(res.data);
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (open) {
      void checkSyncStatus();
      timer = setInterval(() => {
        void checkSyncStatus();
      }, 3000);
    }
    return () => clearInterval(timer);
  }, [open]);

  useEffect(() => {
    if (prevSyncRunningRef.current && !syncState.running) {
      void loadMibs(1, searchQuery);
      if (syncState.last_result?.success) {
        showToast(
          zh
            ? `MIB 全量同步完成：成功导入 ${syncState.last_result.imported ?? 0} 个 MIB 模块，共 ${syncState.last_result.nodes ?? 0} 个 OID 节点`
            : `MIB sync complete: ${syncState.last_result.imported ?? 0} MIBs imported, ${syncState.last_result.nodes ?? 0} OID nodes`,
          'success',
        );
      }
    }
    prevSyncRunningRef.current = syncState.running;
  }, [syncState.running]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    const supported = /\.(zip|mib|my|txt|asn|smi)$/i.test(file.name);
    if (!supported) {
      showToast(
        zh ? '仅支持 ZIP、MIB、MY、TXT、ASN 或 SMI 文件' : 'Only ZIP, MIB, MY, TXT, ASN, or SMI files are supported',
        'error',
      );
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (vendorFilter.trim()) params.set('vendor', vendorFilter.trim());

    setUploading(true);
    try {
      const result = await apiRequest<{
        success: boolean;
        async?: boolean;
        message?: string;
        data?: MibItem[];
        imported?: number;
        failed?: number;
        extracted?: number;
        errors?: Array<{ filename: string; error: string }>;
      }>(`/api/platform-registry/mibs/upload${params.toString() ? `?${params.toString()}` : ''}`, {
        method: 'POST',
        body: formData,
      });

      if (result.async) {
        showToast(
          result.message || (zh ? 'MIB 压缩包已接收，已自动启动后台全量解析与索引…' : 'MIB archive received; indexing started in background…'),
          'info',
        );
        void checkSyncStatus();
        return;
      }

      const imported = typeof result.imported === 'number'
        ? result.imported
        : (Array.isArray(result.data) ? result.data.length : 0);
      const failed = typeof result.failed === 'number'
        ? result.failed
        : (Array.isArray(result.errors) ? result.errors.length : 0);
      showToast(
        zh
          ? `MIB 导入完成：成功 ${imported} 个${failed ? `，失败 ${failed} 个` : ''}`
          : `MIB import complete: ${imported} succeeded${failed ? `, ${failed} failed` : ''}`,
        failed ? 'info' : 'success',
      );
      setSelectedMibId(null);
      setMibDetail(null);
      setMibPage(1);
      await loadMibs(1, searchQuery);
      void checkSyncStatus();
    } catch (err) {
      showToast(err instanceof Error ? err.message : (zh ? 'MIB/ZIP 导入失败' : 'MIB/ZIP import failed'), 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleSyncLibreNMS = async () => {
    if (!window.confirm(zh ? '确定从 LibreNMS 官方仓库拉取并解析全量厂商 MIB 库吗？这将在后台异步执行。' : 'Fetch and index full multi-vendor MIB library from LibreNMS repository? This runs in the background.')) {
      return;
    }
    try {
      const res = await apiRequest<{ success: boolean; message: string }>('/api/platform-registry/mibs/sync-librenms', { method: 'POST' });
      showToast(res.message || (zh ? 'LibreNMS MIB 同步任务已在后台启动' : 'LibreNMS MIB sync started'), 'info');
      void checkSyncStatus();
    } catch (err) {
      showToast(err instanceof Error ? err.message : (zh ? '启动同步失败' : 'Failed to start sync'), 'error');
    }
  };

  const handleResetBuiltin = async () => {
    if (!window.confirm(zh ? '确定重新同步并更新所有内置厂商 MIB 知识库吗？此操作只处理系统内置核心 MIB。' : 'Refresh and update all built-in core vendor MIBs? This only touches the built-in core catalog.')) {
      return;
    }
    setLoading(true);
    try {
      const res = await apiRequest<{ success: boolean; message: string; count: number }>(
        '/api/platform-registry/mibs/reset-builtin',
        { method: 'POST' }
      );
      showToast(res.message || (zh ? '内置 MIB 库同步完成' : 'Built-in MIBs reloaded'), 'success');
      await loadMibs(mibPage, searchQuery);
    } catch (err) {
      showToast(err instanceof Error ? err.message : (zh ? '同步失败' : 'Failed to reload built-in MIBs'), 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteMib = async (mib: MibItem) => {
    if (!window.confirm(zh ? `确定删除 MIB 模块 [${mib.name}] 吗？` : `Delete MIB module [${mib.name}]?`)) {
      return;
    }
    try {
      await apiRequest(`/api/platform-registry/mibs/${mib.id}`, { method: 'DELETE' });
      showToast(zh ? 'MIB 模块已删除' : 'MIB module deleted', 'success');
      if (selectedMibId === mib.id) {
        setSelectedMibId(null);
        setMibDetail(null);
      }
      await loadMibs(mibPage, searchQuery);
    } catch (err) {
      showToast(err instanceof Error ? err.message : (zh ? '删除失败' : 'Delete failed'), 'error');
    }
  };

  const detailNodes = Array.isArray(mibDetail?.nodes) ? mibDetail.nodes : [];
  const visibleNodes = nodeSearch.trim() ? (nodeSearchResults || []) : detailNodes;
  const toMibNodeItem = (node: any): MibNodeItem => ({
    id: String(node.id || ''),
    mib_id: String(mibDetail?.id || selectedMibId || ''),
    mib_name: String(mibDetail?.name || ''),
    vendor: String(mibDetail?.vendor || ''),
    node_name: String(node.node_name || ''),
    oid: String(node.oid || ''),
    syntax_type: String(node.syntax_type || ''),
    access_type: String(node.access_type || ''),
    status: String(node.status || ''),
    description: String(node.description || ''),
    recommended_mode: node.recommended_mode,
    recommended_counter_bits: node.recommended_counter_bits,
  });
  const resolvedNodeCount = typeof mibDetail?.resolved_node_count === 'number'
    ? mibDetail.resolved_node_count
    : detailNodes.filter((node: any) => String(node.oid || '').trim()).length;
  const unresolvedNodeCount = typeof mibDetail?.unresolved_node_count === 'number'
    ? mibDetail.unresolved_node_count
    : Math.max(0, detailNodes.length - resolvedNodeCount);
  const statDisplay = (value: number | undefined) => (
    typeof value === 'number' ? value : (loading ? '…' : '—')
  );
  const moduleCountDisplay = typeof repositoryStats?.module_count === 'number'
    ? repositoryStats.module_count
    : (loading ? '…' : (mibTotal > 0 ? mibTotal : '—'));

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-[1100px] flex-col overflow-hidden rounded-2xl border border-black/10 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
        onMouseDown={e => e.stopPropagation()}
      >
        <input
          ref={uploadInputRef}
          type="file"
          accept=".zip,.mib,.my,.txt,.asn,.smi"
          className="hidden"
          aria-label={zh ? '选择 MIB 或 ZIP 文件' : 'Choose MIB or ZIP file'}
          onChange={handleUpload}
        />
        {/* Header */}
        <div className="flex items-center justify-between border-b border-black/8 px-5 py-4 dark:border-white/8">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#00bceb]/10 text-[#008aad] dark:text-[#00bceb]">
              <Database size={18} />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/85 dark:text-white/90">
                {zh ? 'SNMP MIB 知识库管理' : 'SNMP MIB Repository Management'}
              </div>
              <div className="mt-0.5 text-[11px] text-black/45 dark:text-white/45">
                {zh
                  ? '已内置 Standard RFC、Cisco、Huawei、H3C、Arista、Ruijie、Juniper、Fortinet 核心 MIB；支持上传 ZIP/MIB 自动索引或通过 LibreNMS 官方目录统一同步'
                  : 'Pre-loaded with Standard RFC, Cisco, Huawei, H3C, Arista, Ruijie, Juniper, Fortinet MIBs. Supports ZIP/MIB uploads or official LibreNMS sync.'}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => uploadInputRef.current?.click()}
              disabled={uploading || loading || syncState.running}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/25 bg-violet-500/10 px-3 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-500/20 disabled:opacity-50 dark:text-violet-300"
              title={zh ? '上传 MIB 文件或全量 ZIP 压缩包' : 'Upload MIB file or full ZIP archive'}
            >
              <Upload size={12} className={uploading ? 'animate-pulse' : ''} />
              {uploading ? (zh ? '导入中…' : 'Importing…') : (zh ? '上传 MIB / ZIP' : 'Upload MIB / ZIP')}
            </button>
            <button
              type="button"
              onClick={() => void handleSyncLibreNMS()}
              disabled={syncState.running || loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#00bceb]/30 bg-[#00bceb]/10 px-3 py-1.5 text-xs font-medium text-[#008aad] hover:bg-[#00bceb]/20 disabled:opacity-50 dark:text-[#00bceb]"
              title={zh ? '从 LibreNMS 官方仓库拉取并解析全量 MIB' : 'Fetch all MIBs from LibreNMS'}
            >
              <RefreshCw size={12} className={syncState.running ? 'animate-spin' : ''} />
              {syncState.running ? (zh ? 'LibreNMS 同步中…' : 'Syncing LibreNMS…') : (zh ? '同步 LibreNMS 全量 MIB' : 'Sync LibreNMS MIBs')}
            </button>
            <button
              type="button"
              onClick={() => void handleResetBuiltin()}
              disabled={loading || syncState.running}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-500/20 disabled:opacity-50 dark:text-emerald-400"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              {zh ? '重载核心 MIB' : 'Reload Core MIBs'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
            >
              <X size={17} />
            </button>
          </div>
        </div>

        {/* Sync Progress Alert */}
        {syncState.running && (
          <div className="flex items-center justify-between border-b border-[#00bceb]/20 bg-[#00bceb]/[0.06] px-5 py-2 text-xs text-[#008aad] dark:text-[#00bceb]">
            <div className="flex items-center gap-2">
              <RefreshCw size={13} className="animate-spin shrink-0" />
              <span>{syncState.progress || (zh ? '正在从 LibreNMS 仓库拉取全量 MIB 并在后台解析入库…' : 'Syncing and indexing LibreNMS MIBs in background…')}</span>
            </div>
          </div>
        )}

        {/* List Filters / Repository Source Bar */}
        <div className="grid grid-cols-1 border-b border-black/6 dark:border-white/6 lg:grid-cols-12">
          <div className="flex min-w-0 flex-wrap items-center gap-2 px-4 py-3 lg:col-span-6 lg:border-r lg:border-black/6 dark:border-white/6">
            <div ref={vendorDropdownRef} className="relative w-[180px] shrink-0">
              <button
                type="button"
                role="combobox"
                aria-label={zh ? '\u5382\u5546\u5206\u7c7b' : 'Vendor filter'}
                aria-expanded={vendorDropdownOpen}
                aria-haspopup="listbox"
                onClick={() => {
                  setVendorDropdownOpen(current => !current);
                  setVendorSearch('');
                }}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-black/10 bg-transparent px-2.5 py-1.5 text-left text-xs text-black/70 outline-none transition hover:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/20 dark:border-white/10 dark:text-white/75"
              >
                <span className="min-w-0 truncate">
                  {vendorFilter || (zh ? '\u5168\u90e8\u5382\u5546' : 'All vendors')}
                </span>
                <ChevronDown size={13} className={`shrink-0 text-black/35 transition-transform dark:text-white/35 ${vendorDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              {vendorDropdownOpen && (
                <div className="absolute left-0 top-full z-50 mt-1 w-[260px] overflow-hidden rounded-xl border border-black/10 bg-white shadow-xl dark:border-white/12 dark:bg-[#111b2d]">
                  <div className="relative border-b border-black/6 p-1.5 dark:border-white/8">
                    <Search size={12} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/30" />
                    <input
                      autoFocus
                      value={vendorSearch}
                      onChange={event => setVendorSearch(event.target.value)}
                      placeholder={zh ? '\u641c\u7d22\u5382\u5546\u2026' : 'Search vendors…'}
                      aria-label={zh ? '\u641c\u7d22\u5382\u5546' : 'Search vendors'}
                      className="w-full rounded-lg bg-black/[.03] py-1.5 pl-7 pr-2 text-[11px] outline-none focus:bg-[#00bceb]/[.06] dark:bg-white/[.05]"
                    />
                  </div>
                  <div role="listbox" aria-label={zh ? '\u5382\u5546\u5217\u8868' : 'Vendor options'} className="max-h-64 overflow-y-auto p-1">
                    <button
                      type="button"
                      role="option"
                      aria-selected={!vendorFilter}
                      onClick={() => chooseVendor('')}
                      className={`flex w-full items-center rounded-lg px-2 py-1.5 text-left text-[11px] ${!vendorFilter ? 'bg-[#00bceb]/10 text-[#008aad] dark:text-[#00bceb]' : 'text-black/65 hover:bg-black/[.04] dark:text-white/65 dark:hover:bg-white/[.06]'}`}
                    >
                      {zh ? '\u5168\u90e8\u5382\u5546' : 'All vendors'}
                    </button>
                    {visibleVendorGroups.map(group => (
                      <div key={group.key}>
                        <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-black/30 dark:text-white/25">
                          {zh ? group.labelZh : group.labelEn}
                        </div>
                        {group.vendors.map(vendor => (
                          <button
                            key={vendor}
                            type="button"
                            role="option"
                            aria-selected={vendorFilter.toLowerCase() === vendor.toLowerCase()}
                            onClick={() => chooseVendor(vendor)}
                            className={`flex w-full items-center rounded-lg px-2 py-1.5 text-left text-[11px] ${vendorFilter.toLowerCase() === vendor.toLowerCase() ? 'bg-[#00bceb]/10 text-[#008aad] dark:text-[#00bceb]' : 'text-black/65 hover:bg-black/[.04] dark:text-white/65 dark:hover:bg-white/[.06]'}`}
                          >
                            <span className="truncate">{vendor}</span>
                          </button>
                        ))}
                      </div>
                    ))}
                    {visibleExtraMibVendors.length > 0 && (
                      <div>
                        <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-black/30 dark:text-white/25">
                          {zh ? '\u5df2\u5bfc\u5165 MIB \u4e2d\u7684\u5176\u4ed6\u5382\u5546' : 'Other vendors in MIB repository'}
                        </div>
                        {visibleExtraMibVendors.map(vendor => (
                          <button
                            key={vendor}
                            type="button"
                            role="option"
                            aria-selected={vendorFilter.toLowerCase() === vendor.toLowerCase()}
                            onClick={() => chooseVendor(vendor)}
                            className={`flex w-full items-center rounded-lg px-2 py-1.5 text-left text-[11px] ${vendorFilter.toLowerCase() === vendor.toLowerCase() ? 'bg-[#00bceb]/10 text-[#008aad] dark:text-[#00bceb]' : 'text-black/65 hover:bg-black/[.04] dark:text-white/65 dark:hover:bg-white/[.06]'}`}
                          >
                            <span className="truncate">{vendor}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {!visibleVendorGroups.length && !visibleExtraMibVendors.length && (
                      <div className="px-2 py-4 text-center text-[11px] text-black/35 dark:text-white/30">
                        {zh ? '\u6ca1\u6709\u5339\u914d\u7684\u5382\u5546' : 'No matching vendors'}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
            <div className="relative min-w-[160px] flex-1">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder={zh ? '搜索 MIB 名称…' : 'Search MIB name…'}
                className="w-full rounded-lg border border-black/10 bg-transparent py-1.5 pl-7 pr-2 text-xs outline-none dark:border-white/10"
              />
            </div>
            <button
              type="button"
              onClick={() => void loadMibs(mibPage, searchQuery)}
              disabled={loading}
              className="rounded-lg border border-black/10 p-1.5 text-black/45 hover:bg-black/5 dark:border-white/10 dark:text-white/45"
              aria-label={zh ? '刷新 MIB 列表' : 'Refresh MIB list'}
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>

          <div className="flex items-center justify-end bg-black/[.02] px-4 py-3 dark:bg-white/[.02] lg:col-span-6">
            <span className="text-[11px] text-black/45 dark:text-white/45">
              {zh ? '支持直接上传 MIB/ZIP 自动解压索引，或一键同步 LibreNMS 官方全量库' : 'Supports uploading MIB/ZIP archives with auto-indexing, or syncing the official LibreNMS library'}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-black/6 px-4 py-2 text-[10px] dark:border-white/6" aria-busy={loading}>
          <button
            type="button"
            onClick={() => toggleStatusFilter('')}
            aria-pressed={statusFilter === ''}
            title={zh ? '显示全部 MIB 模块' : 'Show all MIB modules'}
            className={`cursor-pointer rounded bg-black/[.04] px-2 py-1 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bceb]/40 dark:bg-white/[.06] ${statusFilter === '' ? 'ring-2 ring-inset ring-[#008aad]/35 dark:ring-[#00bceb]/40' : 'hover:shadow-sm'}`}
          >
            {zh ? `模块 ${moduleCountDisplay}` : `Modules ${moduleCountDisplay}`}
          </button>
          <button
            type="button"
            onClick={() => toggleStatusFilter('parsed')}
            aria-pressed={statusFilter === 'parsed'}
            title={zh ? '只显示含节点的 MIB 模块' : 'Show only MIB modules with parsed nodes'}
            className={`cursor-pointer rounded bg-emerald-500/10 px-2 py-1 text-emerald-700 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bceb]/40 dark:text-emerald-400 ${statusFilter === 'parsed' ? 'ring-2 ring-inset ring-emerald-600/35 dark:ring-emerald-400/40' : 'hover:shadow-sm'}`}
          >
            {zh ? `含节点模块 ${statDisplay(repositoryStats?.parsed_module_count)}` : `Modules with nodes ${statDisplay(repositoryStats?.parsed_module_count)}`}
          </button>
          <button
            type="button"
            onClick={() => toggleStatusFilter('zero_node')}
            aria-pressed={statusFilter === 'zero_node'}
            title={zh ? '只显示无可直接采集对象的模块' : 'Show only modules with no directly pollable objects'}
            className={`cursor-pointer rounded bg-amber-500/10 px-2 py-1 text-amber-700 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bceb]/40 dark:text-amber-400 ${statusFilter === 'zero_node' ? 'ring-2 ring-inset ring-amber-600/35 dark:ring-amber-400/40' : 'hover:shadow-sm'}`}
          >
            {zh ? `无可采集对象 ${statDisplay(repositoryStats?.zero_node_module_count)}` : `No pollable objects ${statDisplay(repositoryStats?.zero_node_module_count)}`}
          </button>
          <button
            type="button"
            onClick={() => toggleStatusFilter('unresolved_oid')}
            aria-pressed={statusFilter === 'unresolved_oid'}
            title={zh ? '只显示包含未解析 OID 节点的模块（数量为节点数）' : 'Show modules containing unresolved OID nodes (count is nodes)'}
            className={`cursor-pointer rounded bg-orange-500/10 px-2 py-1 text-orange-700 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bceb]/40 dark:text-orange-400 ${statusFilter === 'unresolved_oid' ? 'ring-2 ring-inset ring-orange-600/35 dark:ring-orange-400/40' : 'hover:shadow-sm'}`}
          >
            {zh ? `OID 待解析节点 ${statDisplay(repositoryStats?.unresolved_oid_node_count)}` : `Unresolved OID nodes ${statDisplay(repositoryStats?.unresolved_oid_node_count)}`}
          </button>
          <button
            type="button"
            onClick={() => toggleStatusFilter('failed')}
            aria-pressed={statusFilter === 'failed'}
            title={zh ? '只显示解析失败的模块' : 'Show only failed MIB modules'}
            className={`cursor-pointer rounded bg-red-500/10 px-2 py-1 text-red-700 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bceb]/40 dark:text-red-400 ${statusFilter === 'failed' ? 'ring-2 ring-inset ring-red-600/35 dark:ring-red-400/40' : 'hover:shadow-sm'}`}
          >
            {zh ? `失败 ${statDisplay(repositoryStats?.failed_module_count)}` : `Failed ${statDisplay(repositoryStats?.failed_module_count)}`}
          </button>
          {repositoryStats?.latest_import && (
            <span className="ml-auto text-black/45 dark:text-white/45">
              {zh
                ? `最近导入：${repositoryStats.latest_import.status || 'unknown'} · ${repositoryStats.latest_import.processed_files || 0}/${repositoryStats.latest_import.total_files || 0}`
                : `Latest import: ${repositoryStats.latest_import.status || 'unknown'} · ${repositoryStats.latest_import.processed_files || 0}/${repositoryStats.latest_import.total_files || 0}`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 border-b border-black/6 px-4 pb-2 text-[10px] text-black/45 dark:border-white/6 dark:text-white/45">
          <AlertCircle size={12} className="shrink-0 text-amber-600 dark:text-amber-400" />
          {zh
            ? '“无可采集对象”通常表示 SMI、TC 或模块依赖定义，不代表 MIB 导入失败。'
            : '“No pollable objects” usually means an SMI, TC, or dependency module; it is not an import failure.'}
        </div>

        {/* Content: Master / Detail */}
        <div className="grid min-h-[420px] flex-1 grid-cols-1 overflow-hidden lg:grid-cols-12">
          {/* MIB List */}
          <div className="relative min-h-0 overflow-y-auto [scrollbar-gutter:stable] border-b border-black/6 p-3 dark:border-white/6 lg:col-span-6 lg:border-b-0 lg:border-r">
            {loading && mibs.length > 0 && (
              <div className="pointer-events-none absolute right-4 top-3 z-10 inline-flex items-center gap-1.5 rounded-full bg-[var(--card-bg)] px-2.5 py-1 text-[10px] text-[#008aad] shadow-sm dark:text-[#00bceb]">
                <RefreshCw size={11} className="animate-spin" />
                {zh ? '正在更新列表…' : 'Updating list…'}
              </div>
            )}
            {loading && mibs.length === 0 ? (
              <div className="py-16 text-center text-xs text-black/40 dark:text-white/40">
                {zh ? '正在加载 MIB 知识库…' : 'Loading MIBs…'}
              </div>
            ) : mibs.length === 0 ? (
              <div className="py-16 text-center text-xs text-black/40 dark:text-white/40">
                {zh ? '暂无 MIB 模块，请先同步 LibreNMS 官方 MIB。' : 'No MIB files found. Sync the official LibreNMS MIB catalog first.'}
              </div>
            ) : (
              <div className={`space-y-2 transition-opacity ${loading ? 'opacity-60' : ''}`}>
                {mibs.map(mib => {
                  const isSelected = selectedMibId === mib.id;
                  return (
                    <div
                      key={mib.id}
                      onClick={() => void loadDetail(mib.id)}
                      className={`cursor-pointer rounded-xl border p-3 transition-colors ${
                        isSelected
                          ? 'border-[#00bceb] bg-[#00bceb]/10 dark:bg-[#00bceb]/15'
                          : 'border-black/6 hover:border-black/15 hover:bg-black/[.02] dark:border-white/6 dark:hover:border-white/15 dark:hover:bg-white/[.03]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 font-mono text-xs font-semibold text-black/85 dark:text-white/90">
                          <FileText size={13} className="text-[#008aad] dark:text-[#00bceb]" />
                          {mib.name}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <span className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] text-black/60 dark:bg-white/[.06] dark:text-white/60">
                            {mib.vendor}
                          </span>
                          {mib.source_type === 'builtin' || mib.source_type === 'librenms' ? (
                            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[9px] text-emerald-600 dark:text-emerald-400">
                              {mib.source_type === 'librenms' ? 'LibreNMS' : (zh ? '系统内置' : 'Built-in')}
                            </span>
                          ) : (
                            <ActionIconButton
                              icon={Trash2}
                              label={zh ? '删除 MIB' : 'Delete MIB'}
                              size="xs"
                              variant="danger"
                              onClick={e => {
                                e.stopPropagation();
                                void handleDeleteMib(mib);
                              }}
                            />
                          )}
                        </div>
                      </div>

                      <div className="mt-2 flex items-center justify-between text-[10px] text-black/45 dark:text-white/45">
                        <span className="flex items-center gap-2">
                          <span>{zh ? `识别节点: ${mib.node_count} 个` : `${mib.node_count} nodes`}</span>
                          {mib.parse_status === 'zero_node' && (
                            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">
                              {zh ? '无可采集对象' : 'No pollable objects'}
                            </span>
                          )}
                          {mib.parse_status === 'failed' && (
                            <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-red-700 dark:text-red-400">
                              {zh ? '解析失败' : 'Failed'}
                            </span>
                          )}
                        </span>
                        <span>{Math.round(mib.file_size / 1024)} KB</span>
                        <span title={mib.relative_path || mib.filename}>{mib.relative_path || mib.filename}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {mibTotal > 0 && (
              <div className="sticky bottom-0 flex items-center justify-between border-t border-black/6 bg-[var(--card-bg)] px-1 py-2 text-[10px] text-black/50 dark:border-white/6 dark:text-white/50">
                <span>
                  {`Page ${mibPage} / ${Math.max(1, Math.ceil(mibTotal / MIB_PAGE_SIZE))} · ${mibTotal} total`}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setMibPage(page => Math.max(1, page - 1))}
                    disabled={loading || mibPage <= 1}
                    className="rounded border border-black/10 p-1 hover:bg-black/5 disabled:opacity-30 dark:border-white/10 dark:hover:bg-white/5"
                    aria-label="Previous page"
                  >
                    <ChevronLeft size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setMibPage(page => Math.min(Math.ceil(mibTotal / MIB_PAGE_SIZE), page + 1))}
                    disabled={loading || mibPage >= Math.ceil(mibTotal / MIB_PAGE_SIZE)}
                    className="rounded border border-black/10 p-1 hover:bg-black/5 disabled:opacity-30 dark:border-white/10 dark:hover:bg-white/5"
                    aria-label="Next page"
                  >
                    <ChevronRight size={13} />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Node Tree Details */}
          <div className="relative flex min-h-0 flex-col overflow-y-auto [scrollbar-gutter:stable] bg-black/[.01] p-4 dark:bg-white/[.01] lg:col-span-6">
            {loadingDetail && mibDetail && (
              <div className="pointer-events-none absolute right-4 top-3 z-10 inline-flex items-center gap-1.5 rounded-full bg-[var(--card-bg)] px-2.5 py-1 text-[10px] text-[#008aad] shadow-sm dark:text-[#00bceb]">
                <RefreshCw size={11} className="animate-spin" />
                {zh ? '正在加载节点符号树…' : 'Loading node tree…'}
              </div>
            )}
            {loadingDetail && !mibDetail ? (
              <div className="flex flex-1 items-center justify-center text-xs text-black/40 dark:text-white/40">
                {zh ? '正在加载节点符号树…' : 'Loading node tree…'}
              </div>
            ) : mibDetail ? (
              <div className={`space-y-3 transition-opacity ${loadingDetail ? 'opacity-60' : ''}`}>
                <div className="border-b border-black/8 pb-2 dark:border-white/8">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-black/85 dark:text-white/90">
                      {mibDetail.name}
                    </span>
                    <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[10px] text-black/60 dark:bg-white/[.06] dark:text-white/60">
                      {mibDetail.vendor}
                    </span>
                  </div>
                  {mibDetail.description && (
                    <p className="mt-1 text-[11px] text-black/50 dark:text-white/50">
                      {mibDetail.description}
                    </p>
                  )}
                </div>

                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-medium text-black/60 dark:text-white/60">
                    <span>
                      {zh
                        ? `OID 节点 (${resolvedNodeCount}/${detailNodes.length} 已解析)`
                        : `OID Nodes (${resolvedNodeCount}/${detailNodes.length} resolved)`}
                    </span>
                    {nodeSearch.trim() && (
                      <span className="font-normal text-black/40 dark:text-white/40">
                        {zh ? `搜索结果 ${visibleNodes.length} 个` : `${visibleNodes.length} matches`}
                      </span>
                    )}
                  </div>
                  <form onSubmit={searchDetailNodes} className="mt-2 flex flex-wrap items-center gap-2">
                    <div className="relative min-w-[180px] flex-1">
                      <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
                      <input
                        value={nodeSearchInput}
                        onChange={event => setNodeSearchInput(event.target.value)}
                        placeholder={zh ? '搜索节点名称 / OID…' : 'Search node name / OID…'}
                        className="w-full rounded-lg border border-black/10 bg-transparent py-1.5 pl-7 pr-2 text-[10px] outline-none focus:border-[#00bceb]/60 dark:border-white/10"
                      />
                    </div>
                    {onMapNodeToTemplate && (
                      <select
                        value={mappingMetricKey}
                        onChange={event => setMappingMetricKey(event.target.value)}
                        className="rounded-lg border border-black/10 bg-transparent px-2 py-1.5 text-[10px] outline-none dark:border-white/10"
                        aria-label={zh ? '映射目标指标' : 'Mapping target metric'}
                      >
                        {TEMPLATE_METRIC_OPTIONS.map(option => (
                          <option key={option.key} value={option.key}>
                            {zh ? `映射到 ${option.labelZh}` : `Map to ${option.labelEn}`}
                          </option>
                        ))}
                      </select>
                    )}
                    <button
                      type="submit"
                      disabled={nodeSearchLoading || !selectedMibId}
                      className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-2.5 py-1.5 text-[10px] font-medium text-white hover:bg-[#008fb1] disabled:opacity-50"
                    >
                      <Search size={11} />
                      {nodeSearchLoading ? (zh ? '搜索中…' : 'Searching…') : (zh ? '搜索' : 'Search')}
                    </button>
                    {nodeSearch.trim() && (
                      <button
                        type="button"
                        onClick={() => {
                          setNodeSearchInput('');
                          setNodeSearch('');
                          setNodeSearchResults(null);
                        }}
                        className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-black/55 hover:bg-black/5 dark:border-white/10 dark:text-white/55 dark:hover:bg-white/5"
                      >
                        <X size={11} />
                        {zh ? '清除' : 'Clear'}
                      </button>
                    )}
                  </form>
                  {detailNodes.length === 0 && (
                    <div className="mt-2 flex gap-2 rounded-lg border border-amber-500/20 bg-amber-500/8 p-3 text-[11px] leading-5 text-amber-800 dark:text-amber-300">
                      <AlertCircle size={14} className="mt-0.5 shrink-0" />
                      <span>
                        {zh
                          ? '此 MIB 不包含可直接采集的 OBJECT-TYPE 节点，通常是 SMI、TC 或其他模块依赖定义；它仍可能被其他 MIB 引用。'
                          : 'This MIB has no directly pollable OBJECT-TYPE nodes. It is usually an SMI, TC, or dependency module that other MIBs may reference.'}
                      </span>
                    </div>
                  )}
                  {unresolvedNodeCount > 0 && (
                    <div className="mt-2 flex gap-2 rounded-lg border border-amber-500/20 bg-amber-500/8 p-3 text-[11px] leading-5 text-amber-800 dark:text-amber-300">
                      <AlertCircle size={14} className="mt-0.5 shrink-0" />
                      <span>
                        {zh
                          ? `有 ${unresolvedNodeCount} 个节点已识别但 OID 尚未解析，通常是依赖 MIB 未建立完成；重新同步后会自动尝试补全。`
                          : `${unresolvedNodeCount} nodes were detected but their OIDs are unresolved, usually because a dependency MIB was not indexed yet. A resync will retry them.`}
                      </span>
                    </div>
                  )}
                  {nodeSearch.trim() && !nodeSearchLoading && visibleNodes.length === 0 && (
                    <div className="mt-2 rounded-lg border border-black/8 bg-black/[.02] p-3 text-[11px] text-black/45 dark:border-white/8 dark:bg-white/[.03] dark:text-white/45">
                      {zh ? '没有匹配的节点，请尝试节点名称或 OID 前缀。' : 'No matching nodes. Try a node name or OID prefix.'}
                    </div>
                  )}
                  <div className="mt-2 max-h-[300px] space-y-1 overflow-y-auto pr-1">
                    {visibleNodes.map((node: any) => (
                      <div
                        key={node.id}
                        className="rounded-lg border border-black/5 bg-white/40 p-2 text-xs dark:border-white/5 dark:bg-white/[.03]"
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="font-mono font-medium text-black/80 dark:text-white/85">
                            {node.node_name}
                          </span>
                          <span className="text-[9px] text-black/40 dark:text-white/40">
                            {node.syntax_type}
                          </span>
                        </div>
                        <div className={`mt-0.5 select-all font-mono text-[10px] ${node.oid ? 'text-[#008aad] dark:text-[#00bceb]' : 'text-amber-700 dark:text-amber-400'}`}>
                          {node.oid || (zh ? 'OID 未解析（依赖符号未找到）' : 'OID unresolved (dependency symbol not found)')}
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-2 text-[9px] text-black/40 dark:text-white/40">
                          <span>{node.access_type || node.status || ''}</span>
                          {onMapNodeToTemplate && node.oid && (
                            <button
                              type="button"
                              onClick={() => onMapNodeToTemplate(toMibNodeItem(node), mappingMetricKey)}
                              className="inline-flex items-center gap-0.5 rounded bg-[#00bceb]/10 px-1.5 py-0.5 font-medium text-[#008aad] hover:bg-[#00bceb]/20 dark:text-[#00bceb]"
                              title={zh ? '打开新建模板并填入此 OID' : 'Open a new template and fill this OID'}
                            >
                              <ArrowRight size={10} />
                              {zh ? '映射到新建模板' : 'Map to new template'}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center text-center text-xs text-black/40 dark:text-white/40">
                <Layers size={28} className="mb-2 opacity-40" />
                {zh ? '在左侧点击一个 MIB 模块查看其解析出的 OID 节点' : 'Select a MIB to view its parsed OID nodes'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default MibUploadModal;
