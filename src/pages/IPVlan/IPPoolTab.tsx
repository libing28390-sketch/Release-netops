import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Package,
  Plus,
  Trash2,
  Search,
  Pencil,
  X,
  PlusCircle,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { TableExportMenu } from '../../components/ui/TableExportMenu';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { buildVisibleIpamExportData, fetchAllIpamExportItems } from './ipamExport';

import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
type IPPoolManagementMode = 'local_static' | 'reserved' | 'external_dhcp' | 'external_other';

interface IPPool {
  id: string;
  revision: number;
  name: string;
  prefix_id: string;
  prefix: string;
  prefix_name: string | null;
  start_ip: string;
  end_ip: string;
  description: string;
  status: string;
  management_mode: IPPoolManagementMode | null;
  allocation_allowed: boolean | number | null;
  mark_populated: boolean | number | null;
  mark_utilized: boolean | number | null;
  policy_pending?: boolean;
  tenant_id: string;
  tenant_name: string | null;
  total_ips: number;
  used_ips: number;
  utilization: number;
}

interface Prefix {
  id: string;
  prefix: string;
  name: string;
  tenant_id?: string;
}

const isEnabled = (value: boolean | number | null | undefined) => value === true || value === 1;
const isActivePool = (status: string | null | undefined) => String(status || '').trim().toLowerCase() === 'active';

const poolStatusLabel = (status: string | null | undefined, zh: boolean) => {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'active') return zh ? '启用' : 'Active';
  if (normalized === 'reserved') return zh ? '保留' : 'Reserved';
  if (normalized === 'deprecated') return zh ? '已弃用' : 'Deprecated';
  return zh ? '未知' : 'Unknown';
};

const poolModeLabel = (mode: IPPoolManagementMode | null | undefined, zh: boolean) => {
  if (mode === 'local_static') return zh ? '本地静态' : 'Local static';
  if (mode === 'reserved') return zh ? '保留范围' : 'Reserved range';
  if (mode === 'external_dhcp') return zh ? '外部 DHCP' : 'External DHCP';
  if (mode === 'external_other') return zh ? '外部管理' : 'Externally managed';
  return zh ? '策略待确认' : 'Policy pending';
};

const localAllocationLabel = (pool: Pick<IPPool, 'management_mode' | 'allocation_allowed' | 'mark_populated' | 'policy_pending' | 'status'>, zh: boolean) => {
  if (pool.policy_pending || !pool.management_mode) return zh ? '受限' : 'Restricted';
  if (!isActivePool(pool.status)) return zh ? '暂停' : 'Paused';
  if (pool.management_mode === 'local_static' && isEnabled(pool.allocation_allowed) && !isEnabled(pool.mark_populated)) {
    return zh ? '允许' : 'Allowed';
  }
  return zh ? '受限' : 'Restricted';
};

interface PendingCreateRequest {
  fingerprint: string;
  key: string;
}

interface IPPoolTabProps {
  language: string;
  t: (key: string) => string;
  prefixId?: string;
  embedded?: boolean;
}

const IPPoolTab: React.FC<IPPoolTabProps> = ({ language, t, prefixId = '', embedded = false }) => {
  const zh = language === 'zh';
  const tableRef = useRef<HTMLTableElement>(null);

  const [pools, setPools] = useState<IPPool[]>([]);
  const [prefixes, setPrefixes] = useState<Prefix[]>([]);
  const [loading, setLoading] = useState(true);
  const hasLoadedPools = useRef(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalPools, setTotalPools] = useState(0);
  const [loadError, setLoadError] = useState('');

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingPool, setEditingPool] = useState<IPPool | null>(null);
  const [showAdvancedFields, setShowAdvancedFields] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingPool(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));

  // Form State
  const [form, setForm] = useState({
    name: '',
    prefix_id: '',
    start_ip: '',
    end_ip: '',
    description: '',
    status: 'active',
    management_mode: '' as IPPoolManagementMode | '',
    allocation_allowed: false,
    mark_populated: false,
    mark_utilized: false,
  });
  const [errorMsg, setErrorMsg] = useState('');
  const pendingCreateRequest = useRef<PendingCreateRequest | null>(null);

  const getCreateIdempotencyKey = (payload: unknown) => {
    const fingerprint = JSON.stringify(payload);
    if (!pendingCreateRequest.current || pendingCreateRequest.current.fingerprint !== fingerprint) {
      pendingCreateRequest.current = {
        fingerprint,
        key: globalThis.crypto?.randomUUID?.() || `ipam-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      };
    }
    return pendingCreateRequest.current.key;
  };

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadData = useCallback(async () => {
    if (!hasLoadedPools.current) setLoading(true);
    setLoadError('');
    const hdrs = authHeaders();
    let poolsLoaded = false;
    try {
      const poolQuery = new URLSearchParams({
        q: search.trim(),
        page: String(page),
        page_size: String(pageSize),
      });
      if (prefixId) poolQuery.set('prefix_id', prefixId);
      const [poolRes, prefRes] = await Promise.all([
        fetch(`/api/ipam/pools?${poolQuery.toString()}`, { headers: hdrs }),
        fetch('/api/ipam/subnets', { headers: hdrs }),
      ]);
      if (!poolRes.ok) {
        setLoadError(poolRes.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : poolRes.status === 403
            ? (zh ? '当前账号没有查看地址池的权限。' : 'You do not have permission to view IP pools.')
            : (zh ? '加载地址池失败，请重试。' : 'Failed to load IP pools. Please retry.'));
      } else {
        const payload = await poolRes.json();
        const data = payload?.data && !Array.isArray(payload.data) ? payload.data : payload;
        setPools(Array.isArray(data) ? data : (data?.items || []));
        setTotalPools(Array.isArray(data) ? data.length : Number(data?.total || 0));
        poolsLoaded = true;
      }
      if (prefRes.ok) {
        setPrefixes(await prefRes.json());
      } else if (poolRes.ok) {
        setLoadError(prefRes.status === 401
          ? (zh ? '登录已过期，无法加载所属网段。' : 'Your session has expired; parent prefixes could not be loaded.')
          : prefRes.status === 403
            ? (zh ? '当前账号没有查看所属网段的权限。' : 'You do not have permission to view parent prefixes.')
            : (zh ? '加载所属网段失败，请重试。' : 'Failed to load parent prefixes. Please retry.'));
      }
    } catch (e) {
      console.error(e);
      setLoadError(zh ? '加载地址池失败，请检查网络后重试。' : 'Failed to load IP pools. Check the connection and retry.');
    } finally {
      if (poolsLoaded) hasLoadedPools.current = true;
      setLoading(false);
    }
  }, [authHeaders, page, pageSize, prefixId, search, zh]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    setPage(1);
  }, [prefixId]);

  const openForm = (poolItem: IPPool | null = null) => {
    setErrorMsg('');
    setShowAdvancedFields(Boolean(poolItem));
    if (poolItem) {
      pendingCreateRequest.current = null;
      setEditingPool(poolItem);
      setForm({
        name: poolItem.name,
        prefix_id: poolItem.prefix_id,
        start_ip: poolItem.start_ip,
        end_ip: poolItem.end_ip,
        description: poolItem.description || '',
        status: poolItem.status || '',
        management_mode: poolItem.management_mode || '',
        allocation_allowed: poolItem.management_mode === 'local_static' && isEnabled(poolItem.allocation_allowed),
        mark_populated: isEnabled(poolItem.mark_populated),
        mark_utilized: isEnabled(poolItem.mark_utilized),
      });
    } else {
      pendingCreateRequest.current = null;
      setEditingPool(null);
      setForm({
        name: '',
        prefix_id: prefixId || '',
        start_ip: '',
        end_ip: '',
        description: '',
        status: 'active',
        management_mode: '',
        allocation_allowed: false,
        mark_populated: false,
        mark_utilized: false,
      });
    }
    setShowAddEdit(true);
  };

  const handleSave = async () => {
    setErrorMsg('');
    if (!form.name || !form.prefix_id || !form.start_ip || !form.end_ip) {
      setErrorMsg(zh ? '请填写所有必填字段' : 'Please fill all required fields');
      return;
    }
    if (!form.management_mode) {
      setErrorMsg(zh ? '请选择地址池管理方式' : 'Select a pool management mode');
      return;
    }
    if (!form.status) {
      setErrorMsg(zh ? '请选择地址池生命周期状态' : 'Select a pool lifecycle status');
      return;
    }

    try {
      const url = editingPool ? `/api/ipam/pools/${editingPool.id}` : '/api/ipam/pools';
      const method = editingPool ? 'PUT' : 'POST';
      const requestBody = {
        ...form,
        allocation_allowed: form.management_mode === 'local_static' && form.allocation_allowed,
        ...(editingPool ? { expected_revision: editingPool.revision } : {}),
      };
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          ...(!editingPool ? { 'Idempotency-Key': getCreateIdempotencyKey(requestBody) } : {}),
        },
        body: JSON.stringify(requestBody),
      });

      if (res.ok) {
        if (!editingPool) pendingCreateRequest.current = null;
        setShowAddEdit(false);
        loadData();
      } else {
        const err = await res.json();
        setErrorMsg(err.detail || (zh ? '操作失败' : 'Operation failed'));
      }
    } catch (e) {
      setErrorMsg(zh ? '网络请求错误' : 'Network request error');
    }
  };

  const handleDelete = async (id: string) => {
    const pool = pools.find((item) => item.id === id);
    if (!pool) return;
    try {
      const query = new URLSearchParams({ expected_revision: String(pool.revision) });
      const res = await fetch(`/api/ipam/pools/${encodeURIComponent(id)}?${query.toString()}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (res.ok) {
        setShowDeleteConfirm(null);
        loadData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Filter pool list
  const filteredPools = pools;
  const paginatedPools = pools;

  const exportData = useCallback(async () => {
    const params = new URLSearchParams({ q: search.trim() });
    if (prefixId) params.set('prefix_id', prefixId);
    const allPools = await fetchAllIpamExportItems<IPPool>('/api/ipam/pools', params);
    return buildVisibleIpamExportData(tableRef.current, [
      { header: zh ? '地址池名称' : 'Pool Name', value: (pool) => pool.name },
      { header: zh ? '所属前缀' : 'Parent Prefix', value: (pool) => pool.prefix || '-' },
      { header: zh ? '起始IP' : 'Start IP', value: (pool) => pool.start_ip },
      { header: zh ? '结束IP' : 'End IP', value: (pool) => pool.end_ip },
      { header: zh ? '管理方式' : 'Management Mode', value: (pool) => poolModeLabel(pool.management_mode, zh) },
      { header: zh ? '当前本地分配状态' : 'Current Local Allocation', value: (pool) => localAllocationLabel(pool, zh) },
      { header: zh ? '禁止单 IP 登记' : 'Block Individual IP Registration', value: (pool) => isEnabled(pool.mark_populated) ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No') },
      { header: zh ? '计入整段利用率' : 'Count Full Range Utilization', value: (pool) => isEnabled(pool.mark_utilized) ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No') },
      { header: zh ? '已用IP数' : 'Used IPs', value: (pool) => pool.used_ips },
      { header: zh ? '总IP数' : 'Total IPs', value: (pool) => pool.total_ips },
      { header: zh ? '状态' : 'Status', value: (pool) => String(pool.status || 'unknown').toUpperCase() },
      { header: zh ? '利用率' : 'Utilization', value: (pool) => `${pool.utilization}%` },
    ], allPools);
  }, [prefixId, search, zh]);

  const getUtilColor = (util: number) => {
    if (util < 60) return 'from-emerald-400 to-green-500';
    if (util < 80) return 'from-amber-400 to-orange-500';
    return 'from-rose-400 to-red-500';
  };

  const getStatusPresentation = (status: string) => {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'active') return { badge: 'bg-emerald-50 text-emerald-700 border-emerald-500/10', dot: 'bg-emerald-500' };
    if (normalized === 'reserved') return { badge: 'bg-amber-50 text-amber-700 border-amber-500/10', dot: 'bg-amber-500' };
    if (normalized === 'deprecated' || normalized === 'released') return { badge: 'bg-slate-100 text-slate-600 border-slate-300', dot: 'bg-slate-400' };
    return { badge: 'bg-slate-50 text-slate-600 border-slate-300', dot: 'bg-slate-400' };
  };

  return (
    <div className={embedded ? 'w-full min-h-0 flex flex-col gap-3' : 'flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4'}>
      {embedded ? (
        <div className="shrink-0 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-gray-900">{zh ? '地址池 / 分配范围' : 'Address Pools / Allocation Ranges'}</h3>
              <p className="mt-1 text-[10px] text-gray-500">
                {zh ? '管理当前网段中的连续地址范围。' : 'Manage contiguous address ranges within this prefix.'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <TableExportMenu tableRef={tableRef} exportData={exportData} filename="ipam-address-pools" language={zh ? 'zh' : 'en'} disabled={loading || paginatedPools.length === 0} />
              <button
                type="button"
                onClick={() => openForm(null)}
                className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
              >
                <Plus size={14} />
                {zh ? '创建地址池' : 'Create Pool'}
              </button>
            </div>
          </div>
          <div className="relative w-full md:w-72">
            <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="search"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder={zh ? '搜索地址池名称、网段...' : 'Search pools...'}
              className="w-full pl-10 pr-4 py-2 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
            />
          </div>
        </div>
      ) : (
        <PageHero
          icon={Package}
          title={zh ? 'IP地址池管理' : 'IP Pool Management'}
          subtitle={zh ? '登记网段内的连续 IP 范围并查看利用率；此处不配置或下发 DHCP 租约' : 'Record IP ranges and utilization; DHCP lease assignment is not configured here.'}
          actions={
            <div className="flex items-center gap-2">
              <TableExportMenu tableRef={tableRef} exportData={exportData} filename="ipam-address-pools" language={zh ? 'zh' : 'en'} disabled={loading || paginatedPools.length === 0} />
              <button
                onClick={() => openForm(null)}
                className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
              >
                <Plus size={14} />
                {zh ? '创建地址池' : 'Create Pool'}
              </button>
            </div>
          }
          extras={
            <div className="relative w-full md:w-64">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="search"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder={zh ? '搜索地址池名称、网段...' : 'Search pools...'}
                className="w-full pl-10 pr-4 py-1.5 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
              />
            </div>
          }
        />
      )}

      {loadError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-700">
          <span>{loadError}</span>
          <button type="button" onClick={loadData} className="shrink-0 rounded-lg bg-white px-3 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {/* Main Table Card */}
      <div className={`flex-1 min-h-0 bg-white ${embedded ? 'rounded-2xl' : 'rounded-[28px]'} border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col`}>
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading IP pools...'}
            </div>
          ) : (
            <table ref={tableRef} className="nx-data-table text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? '地址池名称' : 'Pool Name'}</th>
                  <th className="px-4 py-4">{zh ? '所属前缀' : 'Parent Prefix'}</th>
                  <th className="px-4 py-4">{zh ? '起始IP' : 'Start IP'}</th>
                  <th className="px-4 py-4">{zh ? '结束IP' : 'End IP'}</th>
                  <th className="px-4 py-4">{zh ? '管理/分配策略' : 'Management / Allocation'}</th>
                  <th className="px-4 py-4">{zh ? '已用IP数' : 'Used IPs'}</th>
                  <th className="px-4 py-4">{zh ? '总IP数' : 'Total IPs'}</th>
                  <th className="px-4 py-4">{zh ? '状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '利用率' : 'Utilization'}</th>
                  <TableActionHeader className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody>
                {paginatedPools.length > 0 ? (
                  paginatedPools.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="pl-6 py-4 text-sm font-semibold text-gray-800">{node.name}</td>
                      <td className="px-4 py-4 text-xs font-mono font-bold text-cyan-600">{node.prefix}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-700">{node.start_ip}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-700">{node.end_ip}</td>
                      <td className="px-4 py-4 min-w-56">
                        {(() => {
                          const policyPending = Boolean(node.policy_pending) || !node.management_mode;
                          const lifecyclePaused = !isActivePool(node.status);
                          return (
                            <div className="space-y-1.5 text-[10px]">
                              <span className={`inline-flex rounded-full border px-2 py-0.5 font-bold ${policyPending ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
                                {poolModeLabel(node.management_mode, zh)}
                              </span>
                              <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-gray-600">
                                <span>{zh ? '本地分配' : 'Local allocation'}: {localAllocationLabel(node, zh)}</span>
                                <span>{zh ? '单 IP 登记' : 'Single IP registration'}: {isEnabled(node.mark_populated) ? (zh ? '禁止' : 'Blocked') : (zh ? '未禁止' : 'Not blocked')}</span>
                                <span>{zh ? '计入整段利用率' : 'Count full range'}: {isEnabled(node.mark_utilized) ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No')}</span>
                              </div>
                              {policyPending && <div className="font-semibold text-amber-700">{zh ? '策略未确认，分配受限' : 'Policy pending; allocations are restricted'}</div>}
                              {!policyPending && lifecyclePaused && <div className="font-semibold text-amber-700">{zh ? `生命周期状态为${poolStatusLabel(node.status, zh)}，当前暂停分配` : `Lifecycle status is ${poolStatusLabel(node.status, zh)}; allocation is paused`}</div>}
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-4 py-4 text-xs text-gray-600 font-semibold">{node.used_ips}</td>
                      <td className="px-4 py-4 text-xs text-gray-600 font-semibold">{node.total_ips}</td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[11px] font-bold ${getStatusPresentation(node.status).badge}`}>
                          <span className={`w-1 h-1 rounded-full ${getStatusPresentation(node.status).dot}`} />
                          {String(node.status || 'unknown').toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-col gap-1 w-24">
                          <span className="text-xs font-semibold tabular-nums text-[var(--ui-fg)]">{node.utilization}%</span>
                          <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div 
                              className={`h-full rounded-full bg-gradient-to-r ${getUtilColor(node.utilization)}`} 
                              style={{ width: `${node.utilization}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <TableActionCell className="pr-6 py-4 text-right">
                        <ActionIconGroup label={zh ? '地址池操作' : 'Pool actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
                          <ActionIconButton
                            icon={Pencil}
                            label={zh ? '编辑' : 'Edit'}
                            onClick={() => openForm(node)}
                          />
                          <ActionIconButton
                            icon={Trash2}
                            label={zh ? '删除' : 'Delete'}
                            variant="danger"
                            onClick={() => setShowDeleteConfirm(node.id)}
                          />
                        </ActionIconGroup>
                      </TableActionCell>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={10} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '暂无地址范围记录' : 'No address ranges configured'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="px-6 py-4 border-t border-gray-100">
          <Pagination
            currentPage={page}
            totalItems={totalPools}
            itemsPerPage={pageSize}
            onPageChange={setPage}
            onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
            language={language}
            alwaysVisible={true}
          />
        </div>
      </div>

      {/* Add / Edit Modal */}
      <AnimatePresence>
        {showAddEdit && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="bg-white w-full max-w-lg rounded-3xl overflow-hidden shadow-2xl border border-black/5 flex flex-col max-h-[90vh]"
            >
              <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600">
                    <PlusCircle size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">{editingPool ? (zh ? '编辑地址池' : 'Edit IP Pool') : (zh ? '新建地址池' : 'Create IP Pool')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '登记一个 IP 地址范围并统计使用情况' : 'Record an IP range and track its utilization.'}</p>
                  </div>
                </div>
                <button onClick={() => setShowAddEdit(false)} className="p-1.5 rounded-lg hover:bg-gray-50 transition-colors text-gray-400">
                  <X size={16} />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {errorMsg && (
                  <div className="p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-xs font-semibold text-rose-600">
                    {errorMsg}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  <div className="col-span-2 rounded-xl border border-cyan-100 bg-cyan-50/60 px-3.5 py-3 text-xs leading-relaxed text-cyan-900">
                    {zh
                      ? '明确地址范围由谁管理、本地是否允许分配，以及范围是否计入利用率。外部 DHCP 租约不会在此配置。'
                      : 'Set who manages the range, whether local allocation is allowed, and how utilization is counted. DHCP leases are not configured here.'}
                  </div>

                  {/* Name */}
                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="pool-name" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '地址池名称 *' : 'Pool Name *'}</label>
                    <input
                      id="pool-name"
                      type="text"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder={zh ? '例如：办公区静态分配范围' : 'e.g. Office static allocation range'}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Prefix Select */}
                  {!prefixId && (
                    <div className="space-y-1.5 col-span-2">
                      <label htmlFor="pool-prefix" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '所属网段 *' : 'Prefix *'}</label>
                      <select
                        id="pool-prefix"
                        value={form.prefix_id}
                        onChange={(e) => setForm({ ...form, prefix_id: e.target.value })}
                        className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                      >
                        <option value="">{zh ? '请选择网段' : 'Select a prefix'}</option>
                        {prefixes.map((item) => (
                          <option key={item.id} value={item.id}>{item.prefix} {item.name ? `(${item.name})` : ''}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {prefixId && (
                    <div className="col-span-2 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                      <div className="text-[10px] font-semibold text-gray-400">{zh ? '所属网段' : 'Prefix'}</div>
                      <div className="mt-1 font-mono text-sm font-bold text-gray-800">
                        {prefixes.find((item) => item.id === prefixId)?.prefix || prefixId}
                        {prefixes.find((item) => item.id === prefixId)?.name && (
                          <span className="ml-2 font-sans text-xs font-medium text-gray-500">
                            {prefixes.find((item) => item.id === prefixId)?.name}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Start IP */}
                  <div className="space-y-1.5">
                    <label htmlFor="pool-start-ip" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '起始 IP 地址 *' : 'Start IP *'}</label>
                    <input
                      id="pool-start-ip"
                      type="text"
                      value={form.start_ip}
                      onChange={(e) => setForm({ ...form, start_ip: e.target.value })}
                      placeholder="e.g. 10.1.1.100"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* End IP */}
                  <div className="space-y-1.5">
                    <label htmlFor="pool-end-ip" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '结束 IP 地址 *' : 'End IP *'}</label>
                    <input
                      id="pool-end-ip"
                      type="text"
                      value={form.end_ip}
                      onChange={(e) => setForm({ ...form, end_ip: e.target.value })}
                      placeholder="e.g. 10.1.1.200"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {editingPool && (Boolean(editingPool.policy_pending) || !editingPool.management_mode) && (
                    <div role="status" className="col-span-2 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-relaxed text-amber-900">
                      {zh
                        ? '此地址池的管理策略尚未确认，因此本地分配受限。请选择并保存明确策略后再使用。'
                        : 'This pool has no confirmed management policy, so local allocation is restricted. Select and save an explicit policy before using it.'}
                    </div>
                  )}

                  {!isActivePool(form.status) && (
                    <div role="status" className="col-span-2 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-relaxed text-amber-900">
                      {zh
                        ? `当前生命周期状态为${poolStatusLabel(form.status, zh)}，此状态下地址池暂停参与分配。管理方式和分配策略会保留；将状态改为启用后才会生效。`
                        : `The current lifecycle status is ${poolStatusLabel(form.status, zh)}. Allocation is paused while the pool is not active. Its management mode and allocation policy are preserved and take effect only when status is set to Active.`}
                    </div>
                  )}

                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="pool-management-mode" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">
                      {zh ? '管理方式 *' : 'Management Mode *'}
                    </label>
                    <select
                      id="pool-management-mode"
                      value={form.management_mode}
                      onChange={(e) => {
                        const mode = e.target.value as IPPoolManagementMode | '';
                        setForm((current) => ({
                          ...current,
                          management_mode: mode,
                          allocation_allowed: mode === 'local_static' ? current.allocation_allowed : false,
                        }));
                      }}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择管理方式' : 'Select a management mode'}</option>
                      <option value="local_static">{zh ? '本地静态分配' : 'Local static allocation'}</option>
                      <option value="reserved">{zh ? '保留范围' : 'Reserved range'}</option>
                      <option value="external_dhcp">{zh ? '外部 DHCP 管理' : 'Managed by external DHCP'}</option>
                      <option value="external_other">{zh ? '其他外部系统管理' : 'Managed by another external system'}</option>
                    </select>
                    <p className="ml-1 text-[10px] leading-relaxed text-gray-500">
                      {zh
                        ? '管理方式决定范围的所有权；它与利用率统计和单 IP 登记规则分开设置。'
                        : 'Management mode describes who controls the range; utilization and single-IP registration are configured separately.'}
                    </p>
                  </div>

                  <label className={`col-span-2 flex items-start gap-3 rounded-xl border px-3.5 py-3 ${form.management_mode === 'local_static' ? 'border-gray-200 bg-white' : 'border-gray-100 bg-gray-50'}`}>
                    <input
                      type="checkbox"
                      checked={form.management_mode === 'local_static' && form.allocation_allowed}
                      disabled={form.management_mode !== 'local_static'}
                      onChange={(e) => setForm((current) => ({ ...current, allocation_allowed: e.target.checked }))}
                      aria-label={zh ? '允许本地静态分配' : 'Allow local static allocation'}
                      className="mt-0.5 accent-cyan-600 disabled:cursor-not-allowed"
                    />
                    <span className="space-y-0.5">
                      <span className="block text-xs font-semibold text-gray-800">{zh ? '允许本地静态分配' : 'Allow local static allocation'}</span>
                      <span className="block text-[10px] leading-relaxed text-gray-500">
                        {form.management_mode === 'local_static'
                          ? (zh ? '只有本地静态范围可以开启；默认关闭。' : 'Only local static ranges can enable this; default is off.')
                          : (zh ? '保留或外部管理范围不允许本地静态分配。' : 'Reserved and externally managed ranges cannot be allocated locally.')}
                      </span>
                    </span>
                  </label>

                  <label className="col-span-2 flex items-start gap-3 rounded-xl border border-gray-200 bg-white px-3.5 py-3">
                    <input
                      type="checkbox"
                      checked={form.mark_populated}
                      onChange={(e) => setForm((current) => ({ ...current, mark_populated: e.target.checked }))}
                      aria-label={zh ? '禁止在范围内创建单个 IP 地址' : 'Prevent individual IP registration in this range'}
                      className="mt-0.5 accent-cyan-600"
                    />
                    <span className="space-y-0.5">
                      <span className="block text-xs font-semibold text-gray-800">{zh ? '禁止创建单个 IP 地址' : 'Prevent individual IP registration'}</span>
                      <span className="block text-[10px] leading-relaxed text-gray-500">
                        {zh ? '独立控制范围内是否允许逐个登记 IP。' : 'Independently controls whether individual IPs can be registered in this range.'}
                      </span>
                    </span>
                  </label>

                  <label className="col-span-2 flex items-start gap-3 rounded-xl border border-gray-200 bg-white px-3.5 py-3">
                    <input
                      type="checkbox"
                      checked={form.mark_utilized}
                      onChange={(e) => setForm((current) => ({ ...current, mark_utilized: e.target.checked }))}
                      aria-label={zh ? '利用率按整个地址范围计入' : 'Count the full range as utilized'}
                      className="mt-0.5 accent-cyan-600"
                    />
                    <span className="space-y-0.5">
                      <span className="block text-xs font-semibold text-gray-800">{zh ? '利用率按整个范围计入' : 'Count the full range as utilized'}</span>
                      <span className="block text-[10px] leading-relaxed text-gray-500">
                        {zh ? '只影响利用率统计，不会自动开启或关闭本地分配。' : 'Affects utilization reporting only; it does not enable or disable allocation.'}
                      </span>
                    </span>
                  </label>

                  {showAdvancedFields && (
                    <>
                      {/* Status */}
                      <div className="space-y-1.5">
                        <label htmlFor="pool-status" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '生命周期状态' : 'Lifecycle Status'}</label>
                        <select
                          id="pool-status"
                          value={form.status}
                          onChange={(e) => setForm({ ...form, status: e.target.value })}
                          className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                        >
                          {!form.status && <option value="">{zh ? '请选择生命周期状态' : 'Select a lifecycle status'}</option>}
                          <option value="active">{zh ? '启用' : 'Active'}</option>
                          <option value="reserved">{zh ? '保留' : 'Reserved'}</option>
                          <option value="deprecated">{zh ? '已弃用' : 'Deprecated'}</option>
                        </select>
                      </div>

                      {/* Description */}
                      <div className="space-y-1.5 col-span-2">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '备注' : 'Notes'}</label>
                        <textarea
                          value={form.description}
                          onChange={(e) => setForm({ ...form, description: e.target.value })}
                          placeholder={zh ? '可补充说明该地址范围的用途' : 'Optional notes about this range'}
                          rows={2}
                          className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                        />
                      </div>
                    </>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => setShowAdvancedFields((current) => !current)}
                  className="w-full rounded-xl border border-dashed border-gray-200 bg-gray-50 px-3 py-2.5 text-xs font-semibold text-gray-600 hover:border-cyan-200 hover:bg-cyan-50/40 hover:text-cyan-700 transition-colors"
                  aria-expanded={showAdvancedFields}
                >
                  {showAdvancedFields
                    ? (zh ? '收起可选设置' : 'Hide optional settings')
                    : (zh ? '可选设置：状态、备注' : 'Optional settings: status and notes')}
                </button>
              </div>

              <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex items-center justify-end gap-3 flex-shrink-0">
                <button onClick={() => setShowAddEdit(false)} className="px-4 py-2 text-xs font-bold text-gray-500 hover:bg-gray-100 rounded-xl">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={handleSave} className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white text-xs font-extrabold rounded-xl shadow-md transition-all active:scale-95">
                  {zh ? '确认保存' : 'Save'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {showDeleteConfirm && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-md rounded-3xl overflow-hidden shadow-2xl border border-black/5"
            >
              <div className="p-6">
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '删除地址池？' : 'Delete IP Pool?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '确定要删除此地址范围记录吗？删除后只会移除范围记录，不会删除网段中已登记的 IP 地址。' : 'Delete this address range record? Only the range will be removed; registered IP addresses in the prefix remain.'}
                </p>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button onClick={() => setShowDeleteConfirm(null)} className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={() => handleDelete(showDeleteConfirm)} className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold">
                  {zh ? '确定删除' : 'Delete'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default IPPoolTab;
