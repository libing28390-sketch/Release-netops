import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Clock,
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
interface DHCPLease {
  id: string;
  revision: number;
  address: string;
  mac_address: string;
  hostname: string;
  dhcp_server: string;
  lease_state: string;
  source_lease_state?: string;
  effective_state?: string;
  is_expired?: boolean;
  blocks_local_allocation?: boolean;
  lease_start: string;
  lease_end: string;
  pool_id?: string | null;
  pool_name?: string | null;
  address_space_id?: string | null;
  address_space_name?: string | null;
  scope_pending?: boolean | number;
  scope_status?: string;
  created_at: string;
  updated_at: string;
}

interface ExternalDhcpPoolOption {
  id: string;
  name: string;
  address_space_id: string;
  address_space_name?: string;
  start_ip: string;
  end_ip: string;
  management_mode: string;
  status: string;
  allocation_allowed: boolean | number;
  mark_populated: boolean | number;
  policy_pending?: boolean | number;
}

interface PendingCreateRequest {
  fingerprint: string;
  key: string;
}

const enabledFlag = (value: unknown) => value === true || value === 1;

export function filterExternalDhcpPools(value: unknown): ExternalDhcpPoolOption[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.filter((item): item is ExternalDhcpPoolOption => {
    if (!item || typeof item !== 'object') return false;
    const pool = item as Partial<ExternalDhcpPoolOption>;
    return Boolean(pool.id)
      && String(pool.status || '').toLowerCase() === 'active'
      && pool.management_mode === 'external_dhcp'
      && Boolean(pool.address_space_id)
      && !enabledFlag(pool.policy_pending);
  }).map((pool) => ({
    ...pool,
    id: String(pool.id),
    name: String(pool.name || pool.id),
    address_space_id: String(pool.address_space_id || ''),
    address_space_name: pool.address_space_name ? String(pool.address_space_name) : undefined,
    start_ip: String(pool.start_ip || ''),
    end_ip: String(pool.end_ip || ''),
    management_mode: String(pool.management_mode || ''),
    status: String(pool.status || ''),
  }));
}

interface DHCPLeaseTabProps {
  language: string;
  t: (key: string) => string;
}

export function formatLocalDateInput(date: Pick<Date, 'getFullYear' | 'getMonth' | 'getDate'>): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function getDefaultLeaseDateRange(now: Date): { start: string; end: string } {
  const leaseEnd = new Date(now.getTime());
  leaseEnd.setDate(leaseEnd.getDate() + 7);
  return {
    start: formatLocalDateInput(now),
    end: formatLocalDateInput(leaseEnd),
  };
}

const DHCPLeaseTab: React.FC<DHCPLeaseTabProps> = ({ language, t }) => {
  const zh = language === 'zh';
  const tableRef = useRef<HTMLTableElement>(null);

  const [leases, setLeases] = useState<DHCPLease[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalLeases, setTotalLeases] = useState(0);
  const [loadError, setLoadError] = useState('');

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingLease, setEditingLease] = useState<DHCPLease | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingLease(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));

  // Form State
  const [form, setForm] = useState({
    address: '',
    pool_id: '',
    mac_address: '',
    hostname: '',
    dhcp_server: '',
    lease_state: 'active',
    lease_start: '',
    lease_end: '',
  });
  const [errorMsg, setErrorMsg] = useState('');
  const [externalPools, setExternalPools] = useState<ExternalDhcpPoolOption[]>([]);
  const [isLoadingPools, setIsLoadingPools] = useState(false);
  const [poolLoadError, setPoolLoadError] = useState('');
  const [poolRetryCount, setPoolRetryCount] = useState(0);
  const poolRequest = useRef<AbortController | null>(null);
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
    setLoading(true);
    setLoadError('');
    const hdrs = authHeaders();
    try {
      const res = await fetch(`/api/ipam/leases?q=${encodeURIComponent(search.trim())}&state=${encodeURIComponent(stateFilter)}&page=${page}&page_size=${pageSize}`, { headers: hdrs });
      if (!res.ok) {
        setLoadError(res.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : res.status === 403
            ? (zh ? '当前账号没有查看 DHCP 租约的权限。' : 'You do not have permission to view DHCP leases.')
            : (zh ? '加载 DHCP 租约失败，请重试。' : 'Failed to load DHCP leases. Please retry.'));
        return;
      }
      const payload = await res.json();
      const data = payload?.data && !Array.isArray(payload.data) ? payload.data : payload;
      const items = Array.isArray(payload) ? payload : Array.isArray(payload?.data) ? payload.data : Array.isArray(data) ? data : (data?.items || []);
      setLeases(items);
      setTotalLeases(Array.isArray(data) ? items.length : Number(data?.total || payload?.total || items.length));
    } catch (e) {
      console.error(e);
      setLoadError(zh ? '加载 DHCP 租约失败，请检查网络后重试。' : 'Failed to load DHCP leases. Check the connection and retry.');
    } finally {
      setLoading(false);
    }
  }, [authHeaders, page, pageSize, search, stateFilter, zh]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    poolRequest.current?.abort();
    poolRequest.current = null;
    setExternalPools([]);
    setPoolLoadError('');
    setIsLoadingPools(false);
    if (!showAddEdit) return undefined;

    const controller = new AbortController();
    poolRequest.current = controller;
    setIsLoadingPools(true);
    void (async () => {
      try {
        const query = new URLSearchParams({ status: 'active', page: '1', page_size: '100' });
        const response = await fetch(`/api/ipam/pools?${query.toString()}`, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (controller.signal.aborted || poolRequest.current !== controller) return;
        if (!response.ok) {
          setExternalPools([]);
          setPoolLoadError(response.status === 401
            ? (zh ? '登录已过期，无法加载外部 DHCP 池，请重新登录后重试。' : 'Your session expired. Sign in to load external DHCP pools.')
            : response.status === 403
              ? (zh ? '当前账号没有查看外部 DHCP 池的权限，已停止池选择。' : 'You do not have permission to view DHCP pools. Pool selection is unavailable.')
              : (zh ? '加载外部 DHCP 池失败，已停止池选择。' : 'Failed to load DHCP pools. Pool selection is unavailable.'));
          return;
        }
        const payload: unknown = await response.json();
        if (controller.signal.aborted || poolRequest.current !== controller) return;
        const root = payload && typeof payload === 'object' && 'data' in payload
          ? (payload as { data?: unknown }).data
          : payload;
        const rows = Array.isArray(root)
          ? root
          : root && typeof root === 'object' && Array.isArray((root as { items?: unknown }).items)
            ? (root as { items: unknown[] }).items
            : null;
        if (!rows) {
          setExternalPools([]);
          setPoolLoadError(zh ? '外部 DHCP 池响应无效，已停止池选择。' : 'The DHCP pool response was invalid. Pool selection is unavailable.');
          return;
        }
        const eligible = filterExternalDhcpPools(rows);
        setExternalPools(eligible);
        setPoolLoadError('');
        setForm((current) => current.pool_id && eligible.some((pool) => pool.id === current.pool_id)
          ? current
          : editingLease
            ? current
            : { ...current, pool_id: '' });
      } catch (error) {
        if (controller.signal.aborted || poolRequest.current !== controller) return;
        console.error(error);
        setExternalPools([]);
        setPoolLoadError(zh ? '加载外部 DHCP 池失败，已停止池选择。请检查网络后重试。' : 'Failed to load DHCP pools. Pool selection is unavailable; check the connection and retry.');
      } finally {
        if (poolRequest.current === controller) {
          poolRequest.current = null;
          setIsLoadingPools(false);
        }
      }
    })();

    return () => {
      controller.abort();
      if (poolRequest.current === controller) poolRequest.current = null;
    };
  }, [authHeaders, editingLease, poolRetryCount, showAddEdit, zh]);

  const openForm = (leaseItem: DHCPLease | null = null) => {
    setErrorMsg('');
    pendingCreateRequest.current = null;
    if (leaseItem) {
      setEditingLease(leaseItem);
      setForm({
        address: leaseItem.address,
        pool_id: leaseItem.pool_id || '',
        mac_address: leaseItem.mac_address,
        hostname: leaseItem.hostname || '',
        dhcp_server: leaseItem.dhcp_server || '',
        lease_state: leaseItem.lease_state || 'active',
        lease_start: leaseItem.lease_start || '',
        lease_end: leaseItem.lease_end || '',
      });
    } else {
      setEditingLease(null);
      const today = new Date();
      const defaultDateRange = getDefaultLeaseDateRange(today);
      setForm({
        address: '',
        pool_id: '',
        mac_address: '',
        hostname: '',
        dhcp_server: 'Infoblox',
        lease_state: 'active',
        lease_start: defaultDateRange.start,
        lease_end: defaultDateRange.end,
      });
    }
    setShowAddEdit(true);
  };

  const handleSave = async () => {
    setErrorMsg('');
    if (!form.address || !form.mac_address) {
      setErrorMsg(zh ? '请填写所有必填字段' : 'Please fill all required fields');
      return;
    }

    try {
      const url = editingLease ? `/api/ipam/leases/${editingLease.id}` : '/api/ipam/leases';
      const method = editingLease ? 'PUT' : 'POST';
      const { pool_id, ...leaseFields } = form;
      const payload = editingLease
        ? { ...leaseFields, pool_id, expected_revision: editingLease.revision }
        : pool_id
          ? { ...leaseFields, pool_id }
          : leaseFields;
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          ...(!editingLease ? { 'Idempotency-Key': getCreateIdempotencyKey(payload) } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        if (!editingLease) pendingCreateRequest.current = null;
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
    const lease = leases.find((item) => item.id === id);
    if (!lease) return;
    try {
      const query = new URLSearchParams({ expected_revision: String(lease.revision) });
      const res = await fetch(`/api/ipam/leases/${encodeURIComponent(id)}?${query.toString()}`, {
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

  // Filter lease list
  const filteredLeases = leases;
  const paginatedLeases = leases;

  const exportData = useCallback(async () => {
    const params = new URLSearchParams({ q: search.trim(), state: stateFilter });
    const allLeases = await fetchAllIpamExportItems<DHCPLease>('/api/ipam/leases', params);
    return buildVisibleIpamExportData(tableRef.current, [
      { header: zh ? '动态分配IP' : 'Assigned IP', value: (lease) => lease.address },
      { header: zh ? 'MAC地址' : 'MAC Address', value: (lease) => lease.mac_address },
      { header: zh ? '终端主机名' : 'Client Hostname', value: (lease) => lease.hostname || '-' },
      { header: zh ? 'DHCP 服务源' : 'DHCP Server', value: (lease) => lease.dhcp_server || '-' },
      {
        header: zh ? '地址空间 / DHCP 池' : 'Address Space / DHCP Pool',
        value: (lease) => lease.scope_pending || lease.scope_status === 'scope_unknown' || !lease.address_space_id
          ? (zh ? '范围待确认' : 'Scope pending')
          : `${lease.address_space_name || lease.address_space_id} · ${lease.pool_name || lease.pool_id || '-'}`,
      },
      { header: zh ? '租约状态' : 'Lease State', value: (lease) => (lease.effective_state || lease.lease_state).toUpperCase() },
      { header: zh ? '租用生效时间' : 'Lease Started', value: (lease) => lease.lease_start || '-' },
      { header: zh ? '租用过期时间' : 'Lease Expires', value: (lease) => lease.lease_end || '-' },
    ], allLeases);
  }, [search, stateFilter, zh]);

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={Clock}
        title={zh ? 'DHCP 租约分配管理' : 'DHCP Leases'}
        subtitle={zh ? 'DHCP 租约是外部观测，不等同于静态 IP 归属；仅明确关联到外部 DHCP 池时显示所属地址空间' : 'DHCP leases are external observations, not static IP ownership. Address scope is shown only when linked to an external DHCP pool.'}
        actions={
          <div className="flex items-center gap-2">
            <TableExportMenu tableRef={tableRef} exportData={exportData} filename="ipam-dhcp-leases" language={zh ? 'zh' : 'en'} disabled={loading || paginatedLeases.length === 0} />
            <button
              onClick={() => openForm(null)}
              className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
            >
              <Plus size={14} />
              {zh ? '创建租约' : 'Add Lease'}
            </button>
          </div>
        }
        extras={
          <div className="flex items-center gap-3 w-full md:w-auto">
            {/* State Filter */}
            <select
              value={stateFilter}
              onChange={(e) => { setStateFilter(e.target.value); setPage(1); }}
              className="px-3.5 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none"
            >
              <option value="all">{zh ? '所有租约状态' : 'All Lease States'}</option>
              <option value="active">ACTIVE (活跃)</option>
              <option value="expired">EXPIRED (过期)</option>
            </select>

            {/* Search Input */}
            <div className="relative w-full md:w-64">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="search"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder={zh ? '搜索IP、MAC地址、DHCP服务器...' : 'Search DHCP leases...'}
                className="w-full pl-10 pr-4 py-1.5 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
              />
            </div>
          </div>
        }
      />

      {loadError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-700">
          <span>{loadError}</span>
          <button type="button" onClick={loadData} className="shrink-0 rounded-lg bg-white px-3 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading leases...'}
            </div>
          ) : (
            <table ref={tableRef} className="nx-data-table text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? '动态分配IP' : 'Assigned IP'}</th>
                  <th className="px-4 py-4">{zh ? 'MAC地址' : 'MAC Address'}</th>
                  <th className="px-4 py-4">{zh ? '终端主机名' : 'Client Hostname'}</th>
                  <th className="px-4 py-4">{zh ? 'DHCP 服务源' : 'DHCP Server'}</th>
                  <th className="px-4 py-4">{zh ? '地址空间 / DHCP 池' : 'Address Space / DHCP Pool'}</th>
                  <th className="px-4 py-4">{zh ? '租约状态' : 'Lease State'}</th>
                  <th className="px-4 py-4">{zh ? '租用生效时间' : 'Lease Started'}</th>
                  <th className="px-4 py-4">{zh ? '租用过期时间' : 'Lease Expires'}</th>
                  <TableActionHeader className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody>
                {paginatedLeases.length > 0 ? (
                  paginatedLeases.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="pl-6 py-4 font-mono font-bold text-xs text-gray-800">{node.address}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-600">{node.mac_address}</td>
                      <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.hostname || '-'}</td>
                      <td className="px-4 py-4 text-xs font-bold text-indigo-600">{node.dhcp_server}</td>
                      <td className="px-4 py-4">
                        {node.scope_pending || node.scope_status === 'scope_unknown' || !node.address_space_id ? (
                          <div className="space-y-0.5">
                            <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                              {zh ? '范围待确认' : 'Scope pending'}
                            </span>
                            <div className="text-[10px] text-gray-400">
                              {zh ? '不参与自动分配占用' : 'Does not block auto-allocation'}
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-0.5 text-[10px]">
                            <div className="font-semibold text-gray-700">{node.address_space_name || node.address_space_id}</div>
                            <div className="text-gray-500">{node.pool_name || node.pool_id || (zh ? '未关联池' : 'No pool')}</div>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        {(() => {
                          const effectiveState = (node.effective_state || node.lease_state || 'active').toLowerCase();
                          const sourceState = (node.source_lease_state || node.lease_state || 'active').toLowerCase();
                          const derivedExpired = effectiveState === 'expired' && sourceState === 'active';
                          return (
                            <div className="flex flex-col items-start gap-0.5">
                              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                                effectiveState === 'active'
                                  ? 'bg-emerald-50 text-emerald-600 border border-emerald-500/10'
                                  : 'bg-rose-50 text-rose-600 border border-rose-500/10'
                              }`}>
                                <span className={`w-1 h-1 rounded-full ${effectiveState === 'active' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                                {effectiveState.toUpperCase()}
                              </span>
                              {derivedExpired && (
                                <span className="text-[10px] text-amber-700">
                                  {zh ? '已过租期（来源仍标记 ACTIVE）' : 'Past lease_end (source ACTIVE)'}
                                </span>
                              )}
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-4 py-4 font-mono text-[10px] text-gray-500">{node.lease_start || '-'}</td>
                      <td className="px-4 py-4 font-mono text-[10px] text-gray-500">{node.lease_end || '-'}</td>
                      <TableActionCell className="pr-6 py-4 text-right">
                        <ActionIconGroup label={zh ? '租约操作' : 'Lease actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
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
                    <td colSpan={9} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '当前无任何DHCP租约分配数据' : 'No active DHCP lease mappings found'}
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
            totalItems={totalLeases}
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
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-lg rounded-3xl overflow-hidden shadow-2xl border border-black/5 flex flex-col max-h-[90vh]"
            >
              <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600">
                    <PlusCircle size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">{editingLease ? (zh ? '编辑租约' : 'Edit DHCP Lease') : (zh ? '登记租约' : 'Create DHCP Lease')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '输入动态分配IP的MAC物理地址绑定与有效期' : 'Enter MAC bindings and lease durations.'}</p>
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
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-[11px] leading-relaxed text-slate-700">
                  {zh
                    ? '租约是 DHCP 来源观测，不会单独占用静态分配地址；需要明确空间时请选择对应的外部 DHCP 池。'
                    : 'A lease is an observation from DHCP and does not independently reserve a static address. Select its external DHCP pool to assign a known scope.'}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {/* IP Address */}
                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="dhcp-lease-address" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '分配 IP 地址 *' : 'Assigned IP Address *'}</label>
                    <input
                      id="dhcp-lease-address"
                      type="text"
                      value={form.address}
                      onChange={(e) => setForm({ ...form, address: e.target.value })}
                      placeholder="e.g. 10.1.1.21"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="dhcp-lease-pool" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">
                      {zh ? '外部 DHCP 地址池（可选）' : 'External DHCP Pool (optional)'}
                    </label>
                    <select
                      id="dhcp-lease-pool"
                      aria-label={zh ? '外部 DHCP 地址池' : 'External DHCP Pool'}
                      value={form.pool_id}
                      disabled={isLoadingPools || Boolean(poolLoadError)}
                      onChange={(event) => setForm((current) => ({ ...current, pool_id: event.target.value }))}
                      className="w-full rounded-xl border border-gray-150 bg-gray-50/50 px-4 py-2.5 text-xs font-medium outline-none transition-all focus:border-cyan-400 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <option value="">{zh ? '不关联池（范围待确认）' : 'No pool linked (scope pending)'}</option>
                      {form.pool_id && !externalPools.some((pool) => pool.id === form.pool_id) && (
                        <option value={form.pool_id}>{zh ? '现有池关联待核验' : 'Existing Pool link needs review'}</option>
                      )}
                      {externalPools.map((pool) => (
                        <option key={pool.id} value={pool.id}>
                          {pool.name} · {pool.start_ip} – {pool.end_ip}
                        </option>
                      ))}
                    </select>
                    {isLoadingPools && <p role="status" className="ml-1 text-[10px] text-gray-500">{zh ? '正在加载外部 DHCP 池…' : 'Loading external DHCP pools…'}</p>}
                    {poolLoadError && (
                      <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[10px] font-semibold text-rose-700">
                        <span>{poolLoadError}</span>
                        <button type="button" onClick={() => setPoolRetryCount((count) => count + 1)} disabled={isLoadingPools} className="rounded-lg bg-white px-2.5 py-1 text-rose-700 shadow-sm disabled:opacity-50">
                          {zh ? '重试' : 'Retry'}
                        </button>
                      </div>
                    )}
                    {form.pool_id ? (
                      <p className="ml-1 text-[10px] text-cyan-700">
                        {zh ? '租约范围由所选外部 DHCP 池确认；该观测仍不会单独阻止静态分配。' : 'The selected external DHCP pool establishes this observation scope; the lease itself still does not block static allocation.'}
                      </p>
                    ) : (
                      <p className="ml-1 text-[10px] text-amber-700">
                        {zh ? '未关联外部 DHCP 池时，租约范围保持待确认。' : 'Without an external DHCP pool, lease scope remains pending.'}
                      </p>
                    )}
                    {!isLoadingPools && !poolLoadError && externalPools.length === 0 && (
                      <p className="ml-1 text-[10px] text-gray-500">
                        {zh ? '当前没有可关联的活动外部 DHCP 池。' : 'No active external DHCP pools are available to link.'}
                      </p>
                    )}
                  </div>

                  {/* MAC Address */}
                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="dhcp-lease-mac" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '客户端 MAC 物理地址 *' : 'Client MAC Address *'}</label>
                    <input
                      id="dhcp-lease-mac"
                      type="text"
                      value={form.mac_address}
                      onChange={(e) => setForm({ ...form, mac_address: e.target.value })}
                      placeholder="e.g. aa:bb:cc:dd:ee:ff"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Hostname */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '终端主机名' : 'Client Hostname'}</label>
                    <input
                      type="text"
                      value={form.hostname}
                      onChange={(e) => setForm({ ...form, hostname: e.target.value })}
                      placeholder="e.g. workstation-john"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* DHCP Server */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'DHCP 服务源' : 'DHCP Server'}</label>
                    <input
                      type="text"
                      value={form.dhcp_server}
                      onChange={(e) => setForm({ ...form, dhcp_server: e.target.value })}
                      placeholder="e.g. Infoblox, Windows DHCP"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Lease State */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '租约状态' : 'Lease State'}</label>
                    <select
                      value={form.lease_state}
                      onChange={(e) => setForm({ ...form, lease_state: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="active">ACTIVE</option>
                      <option value="expired">EXPIRED</option>
                    </select>
                  </div>

                  {/* Lease Start */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '租约生效时间' : 'Lease Start'}</label>
                    <input
                      type="date"
                      value={form.lease_start}
                      onChange={(e) => setForm({ ...form, lease_start: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Lease End */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '租约失效过期时间' : 'Lease Expires'}</label>
                    <input
                      type="date"
                      value={form.lease_end}
                      onChange={(e) => setForm({ ...form, lease_end: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>
                </div>
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
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '删除租约记录？' : 'Delete Lease?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '确定要手动删除这行DHCP客户端IP租约记录吗？' : 'Are you sure you want to remove this DHCP host lease record?'}
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

export default DHCPLeaseTab;
