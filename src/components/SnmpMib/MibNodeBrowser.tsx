import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, Database, Loader2, RefreshCw, Search, ShieldAlert } from 'lucide-react';
import { ApiError, apiRequest } from '../../api/http';
import { ALL_VENDOR_NAMES, normalizeImportedVendor } from '../../pages/AssetManagement/constants';
import { DataTable, DataTableFrame } from '../DataTable';
import Pagination from '../Pagination';

export type MibNodeCategory = 'public' | 'private';

export interface MibBrowserNode {
  id: string;
  mib_id: string;
  mib_name: string;
  vendor: string;
  source_type?: string;
  node_name: string;
  oid: string;
  syntax_type: string;
  access_type: string;
  status: string;
  description: string;
  recommended_mode?: string;
  recommended_counter_bits?: number;
}

interface MibNodeListResponse {
  success: boolean;
  data?: MibBrowserNode[];
  total?: number;
  page?: number;
  page_size?: number;
  category?: MibNodeCategory;
  vendor?: string;
  query?: string;
}

export type MibVendorDetectionStatus = 'idle' | 'loading' | 'identified' | 'conflict' | 'unidentified' | 'error' | 'permission';

export interface MibVendorDetection {
  device_id: string;
  status: 'identified' | 'conflict' | 'unidentified';
  vendor?: string | null;
  asset_vendor?: string | null;
  source: 'librenms' | 'sysObjectID' | 'sysDescr' | 'none';
  platform?: string | null;
  sys_object_id?: string | null;
  model?: string | null;
  reason?: string | null;
}

interface MibVendorDetectionResponse {
  data?: MibVendorDetection;
}

export interface MibNodeBrowserProps {
  language: string;
  onSelectOid: (oid: string, node: MibBrowserNode) => void;
  className?: string;
  showHeader?: boolean;
  initialCategory?: MibNodeCategory;
  initialQuery?: string;
  pageSize?: number;
  deviceId?: string;
  assetVendor?: string;
}

const DEFAULT_PAGE_SIZE = 20;

const MibNodeBrowser: React.FC<MibNodeBrowserProps> = ({
  language,
  onSelectOid,
  className = '',
  showHeader = true,
  initialCategory = 'public',
  initialQuery = '',
  pageSize: initialPageSize = DEFAULT_PAGE_SIZE,
  deviceId,
  assetVendor,
}) => {
  const zh = language === 'zh';
  const [category, setCategory] = useState<MibNodeCategory>(initialCategory);
  const [query, setQuery] = useState(initialQuery);
  const [appliedQuery, setAppliedQuery] = useState(initialQuery);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(Math.max(10, Math.min(100, initialPageSize)));
  const [vendor, setVendor] = useState('');
  const [nodes, setNodes] = useState<MibBrowserNode[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedOid, setSelectedOid] = useState('');
  const [vendorDetection, setVendorDetection] = useState<{ status: MibVendorDetectionStatus; result?: MibVendorDetection; message?: string }>({ status: 'idle' });
  const requestId = useRef(0);
  const manualVendorSelection = useRef(false);

  const canonicalVendor = useCallback((candidate: unknown) => {
    const normalized = normalizeImportedVendor(String(candidate || '')).trim().toLowerCase();
    return ALL_VENDOR_NAMES.find(name => name.toLowerCase() === normalized) || '';
  }, []);

  const loadNodes = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({
      q: appliedQuery.trim(),
      category,
      vendor,
      page: String(page),
      page_size: String(pageSize),
    });

    try {
      const response = await apiRequest<MibNodeListResponse>(
        `/api/platform-registry/mibs/nodes?${params.toString()}`
      );
      if (currentRequest !== requestId.current) return;
      setNodes(Array.isArray(response.data) ? response.data : []);
      setTotal(Number.isFinite(response.total) ? Number(response.total) : 0);
    } catch (requestError) {
      if (currentRequest !== requestId.current) return;
      setNodes([]);
      setTotal(0);
      setError(requestError instanceof Error ? requestError.message : (zh ? 'MIB 节点加载失败' : 'Failed to load MIB nodes'));
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [appliedQuery, category, page, pageSize, vendor, zh]);

  useEffect(() => {
    void loadNodes();
  }, [loadNodes]);

  useEffect(() => {
    manualVendorSelection.current = false;
    setPage(1);
    setSelectedOid('');
    if (category !== 'private') {
      setVendorDetection({ status: 'idle' });
      return;
    }

    const fallbackVendor = canonicalVendor(assetVendor);
    setVendor(fallbackVendor);
    if (!deviceId) {
      setVendorDetection({ status: 'idle' });
      return;
    }

    const controller = new AbortController();
    setVendorDetection({ status: 'loading' });
    const applyDetectedVendor = (nextVendor: string) => {
      if (!manualVendorSelection.current) setVendor(nextVendor);
    };
    void apiRequest<MibVendorDetectionResponse>('/api/platform-registry/snmp-walk-vendor-detect', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId }),
      signal: controller.signal,
    }).then(response => {
      if (controller.signal.aborted) return;
      const result = response.data;
      if (!result) {
        setVendorDetection({ status: 'unidentified', message: zh ? '后端未返回厂商识别结果，已使用资产厂商。' : 'The backend returned no vendor result; the asset vendor is being used.' });
        return;
      }
      const detectedVendor = canonicalVendor(result.vendor);
      const resultAssetVendor = canonicalVendor(result.asset_vendor) || fallbackVendor;
      const selectedVendor = (result.status === 'identified' || result.status === 'conflict') && detectedVendor
        ? detectedVendor
        : resultAssetVendor;
      applyDetectedVendor(selectedVendor);
      if (result.status === 'conflict' || (detectedVendor && resultAssetVendor && detectedVendor !== resultAssetVendor)) {
        setVendorDetection({
          status: 'conflict',
          result,
          message: zh
            ? `自动识别为 ${detectedVendor || result.vendor || '未知厂商'}，与资产厂商 ${resultAssetVendor || result.asset_vendor || '未知'} 不一致；已保留手动筛选。`
            : `Auto-detected ${detectedVendor || result.vendor || 'an unknown vendor'}, which conflicts with asset vendor ${resultAssetVendor || result.asset_vendor || 'unknown'}; manual selection remains available.`,
        });
      } else if (result.status === 'identified' && detectedVendor) {
        setVendorDetection({ status: 'identified', result });
      } else {
        setVendorDetection({
          status: 'unidentified',
          result,
          message: zh
            ? `未能自动识别厂商，已使用资产厂商 ${selectedVendor || '（未设置）'}；仍可手动筛选。`
            : `The vendor could not be identified automatically. Using asset vendor ${selectedVendor || '(not set)'}; manual selection remains available.`,
        });
      }
    }).catch(requestError => {
      if (controller.signal.aborted) return;
      const permissionDenied = requestError instanceof ApiError && (requestError.status === 401 || requestError.status === 403);
      applyDetectedVendor(fallbackVendor);
      setVendorDetection({
        status: permissionDenied ? 'permission' : 'error',
        message: permissionDenied
          ? (zh ? '当前账号无权执行厂商自动识别；已使用资产厂商，可继续手动筛选。' : 'You are not permitted to identify the vendor automatically; the asset vendor is used and manual filtering remains available.')
          : (zh ? '厂商自动识别失败；已使用资产厂商，可继续手动筛选。' : 'Automatic vendor identification failed; the asset vendor is used and manual filtering remains available.'),
      });
    });

    return () => controller.abort();
  }, [assetVendor, canonicalVendor, category, deviceId, zh]);

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    setPage(1);
    setAppliedQuery(query.trim());
  };

  const changeCategory = (nextCategory: MibNodeCategory) => {
    if (nextCategory === category) return;
    setCategory(nextCategory);
    setVendor('');
    setPage(1);
    setSelectedOid('');
  };

  const handlePageSizeChange = (nextPageSize: number) => {
    setPageSize(nextPageSize);
    setPage(1);
  };

  const selectNode = (node: MibBrowserNode) => {
    setSelectedOid(node.oid);
    onSelectOid(node.oid, node);
  };

  const formatAccess = (access: string) => {
    if (!access) return '-';
    const normalized = access.toLowerCase();
    if (!zh) return access;
    if (normalized === 'read-only') return '只读';
    if (normalized === 'read-write') return '读写';
    if (normalized === 'read-create') return '读创建';
    if (normalized === 'not-accessible') return '不可访问';
    return access;
  };

  const formatStatus = (status: string) => {
    if (!status) return '-';
    if (!zh) return status;
    if (status.toLowerCase() === 'current') return '当前';
    if (status.toLowerCase() === 'deprecated') return '已弃用';
    if (status.toLowerCase() === 'obsolete') return '已废弃';
    return status;
  };

  const sourceLabel = (sourceType?: string) => {
    const normalized = String(sourceType || '').trim().toLowerCase();
    if (normalized === 'librenms') return 'LibreNMS';
    if (normalized === 'builtin') return zh ? '系统内置' : 'Built-in';
    if (normalized === 'user_upload') return zh ? '用户导入' : 'User upload';
    return sourceType || (zh ? '未知来源' : 'Unknown source');
  };

  return (
    <section className={`space-y-3 ${className}`.trim()}>
      {showHeader && <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-black/80 dark:text-white/90">
            <Database size={16} className="text-[#008aad] dark:text-[#00bceb]" />
            {zh ? 'MIB 节点目录' : 'MIB node catalog'}
          </div>
          <p className="mt-1 text-xs text-black/45 dark:text-white/45">
            {zh ? '选择公共或厂商私有 OID，用于 SNMP 诊断和 Walk 测试。' : 'Choose a standard or vendor OID for SNMP diagnosis and Walk tests.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadNodes()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-black/10 px-2.5 py-1.5 text-xs text-black/65 hover:bg-black/[.03] disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/10 dark:text-white/65 dark:hover:bg-white/[.04]"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          {zh ? '刷新' : 'Refresh'}
        </button>
      </div>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-lg border border-black/10 bg-black/[.02] p-1 dark:border-white/10 dark:bg-white/[.03]" role="tablist" aria-label={zh ? 'MIB 类型' : 'MIB category'}>
            {(['public', 'private'] as const).map(item => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={category === item}
                onClick={() => changeCategory(item)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${category === item ? 'bg-white text-[#008aad] shadow-sm dark:bg-slate-800 dark:text-[#00bceb]' : 'text-black/50 hover:text-black/75 dark:text-white/50 dark:hover:text-white/80'}`}
              >
                {item === 'public' ? (zh ? '公共 MIB（RFC / IANA）' : 'Public MIB (RFC / IANA)') : (zh ? '私有 MIB（厂商）' : 'Private MIB (Vendor)')}
              </button>
            ))}
          </div>

          {category === 'private' && (
            <label className="flex items-center gap-2 text-xs text-black/55 dark:text-white/55">
              <span className="shrink-0 font-medium">{zh ? '厂商' : 'Vendor'}</span>
              <select
                value={vendor}
                onChange={event => {
                  manualVendorSelection.current = true;
                  setVendor(event.target.value);
                  setPage(1);
                  setSelectedOid('');
                }}
                aria-label={zh ? '按厂商筛选 MIB' : 'Filter MIBs by vendor'}
                className="max-w-[220px] rounded-lg border border-black/10 bg-[var(--card-bg)] px-2.5 py-1.5 text-xs text-black/75 outline-none focus:border-[#00bceb]/60 dark:border-white/10 dark:text-white/80"
              >
                <option value="">{zh ? '全部厂商' : 'All vendors'}</option>
                {ALL_VENDOR_NAMES.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <form onSubmit={submitSearch} className="flex min-w-[260px] flex-1 items-center justify-end gap-2 sm:max-w-[420px]">
          <div className="relative min-w-0 flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
            <input
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder={zh ? '搜索符号名、OID、MIB 或说明' : 'Search symbol, OID, MIB or description'}
              className="w-full rounded-lg border border-black/10 bg-transparent py-1.5 pl-8 pr-3 text-xs outline-none focus:border-[#00bceb]/60 dark:border-white/10"
              aria-label={zh ? '搜索 MIB 节点' : 'Search MIB nodes'}
            />
          </div>
          <button type="submit" disabled={loading} className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[#00a9ce] px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-[#008fb1] disabled:cursor-not-allowed disabled:opacity-50">
            <Search size={12} />
            {zh ? '搜索' : 'Search'}
          </button>
        </form>
      </div>

      {category === 'private' && vendorDetection.status !== 'idle' && (
        <div
          className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
            vendorDetection.status === 'permission'
              ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'
              : vendorDetection.status === 'error' || vendorDetection.status === 'conflict'
                ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300'
                : 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200'
          }`}
          role={vendorDetection.status === 'error' || vendorDetection.status === 'permission' || vendorDetection.status === 'conflict' ? 'alert' : undefined}
        >
          {vendorDetection.status === 'loading' ? <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" /> : vendorDetection.status === 'permission' ? <ShieldAlert size={14} className="mt-0.5 shrink-0" /> : vendorDetection.status === 'identified' ? <Check size={14} className="mt-0.5 shrink-0" /> : <AlertCircle size={14} className="mt-0.5 shrink-0" />}
          <span>
            {vendorDetection.status === 'loading'
              ? (zh ? '正在通过 LibreNMS / SNMP 信息自动识别厂商…' : 'Identifying the vendor from LibreNMS / SNMP data…')
              : vendorDetection.status === 'identified'
                ? (zh ? `已自动识别厂商：${canonicalVendor(vendorDetection.result?.vendor) || vendorDetection.result?.vendor || vendor}` : `Vendor identified automatically: ${canonicalVendor(vendorDetection.result?.vendor) || vendorDetection.result?.vendor || vendor}`)
                : vendorDetection.message}
          </span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300" role="alert">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <DataTableFrame className="overflow-hidden rounded-xl border border-black/8 shadow-sm dark:border-white/8" density="compact">
        <div className="overflow-x-auto">
          <DataTable className="min-w-[980px] text-left text-xs">
            <thead className="border-b border-black/8 bg-black/[.025] text-[10px] uppercase tracking-wide text-black/45 dark:border-white/8 dark:bg-white/[.025] dark:text-white/45">
              <tr>
                <th className="px-3 py-2.5 font-medium">{zh ? '符号' : 'Symbol'}</th>
                <th className="px-3 py-2.5 font-medium">OID</th>
                <th className="px-3 py-2.5 font-medium">{zh ? 'MIB / 厂商' : 'MIB / Vendor'}</th>
                <th className="px-3 py-2.5 font-medium">{zh ? '语法 / 访问' : 'Syntax / Access'}</th>
                <th className="px-3 py-2.5 font-medium">{zh ? '说明' : 'Description'}</th>
                <th className="px-3 py-2.5 text-right font-medium">{zh ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/6 dark:divide-white/6">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-3 py-12 text-center text-xs text-black/40 dark:text-white/40">{zh ? '正在加载 MIB 节点…' : 'Loading MIB nodes…'}</td>
                </tr>
              ) : nodes.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-12 text-center text-xs text-black/40 dark:text-white/40">{zh ? '当前分类下没有匹配的 MIB 节点。' : 'No MIB nodes match the current filters.'}</td>
                </tr>
              ) : nodes.map(node => (
                <tr key={node.id} className="transition-colors hover:bg-black/[.02] dark:hover:bg-white/[.03]">
                  <td className="px-3 py-2.5">
                    <div className="font-mono font-semibold text-black/80 dark:text-white/90">{node.node_name || '-'}</div>
                    {node.status && <div className="mt-0.5 text-[10px] text-black/40 dark:text-white/40">{formatStatus(node.status)}</div>}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[11px] text-[#008aad] dark:text-[#00bceb]">{node.oid || '-'}</td>
                  <td className="px-3 py-2.5">
                    <div className="max-w-[190px] truncate font-medium text-black/75 dark:text-white/80" title={node.mib_name}>{node.mib_name || '-'}</div>
                    <div className="mt-0.5 text-[10px] text-black/40 dark:text-white/40">{node.vendor || '-'}</div>
                    <span className="mt-1 inline-flex rounded-full bg-slate-500/10 px-1.5 py-0.5 text-[9px] text-slate-600 dark:text-slate-300">{sourceLabel(node.source_type)}</span>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-mono text-[11px] text-black/75 dark:text-white/75">{node.syntax_type || '-'}</div>
                    <div className="mt-0.5 text-[10px] text-black/45 dark:text-white/45">{formatAccess(node.access_type)}</div>
                  </td>
                  <td className="max-w-[340px] px-3 py-2.5 text-[11px] leading-relaxed text-black/55 dark:text-white/55" title={node.description || undefined}>
                    <span className="line-clamp-2">{node.description || '-'}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => selectNode(node)}
                      className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors ${selectedOid === node.oid ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-[#00bceb]/10 text-[#008aad] hover:bg-[#00bceb]/20 dark:text-[#00bceb]'}`}
                    >
                      {selectedOid === node.oid ? <Check size={12} /> : null}
                      {selectedOid === node.oid ? (zh ? '已选择' : 'Selected') : (zh ? '使用 OID' : 'Use OID')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <Pagination
          currentPage={page}
          totalItems={total}
          onPageChange={setPage}
          itemsPerPage={pageSize}
          onItemsPerPageChange={handlePageSizeChange}
          language={language}
          alwaysVisible
          itemLabel={zh ? '个节点' : 'nodes'}
        />
      </DataTableFrame>
    </section>
  );
};

export default MibNodeBrowser;
