import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, ClipboardCheck, Eye, Globe, Info, Plus, RefreshCw, Search, ShieldAlert, WifiOff, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { DataTable } from '../../components/DataTable';
import { ActionIconButton } from '../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { getDiscoveryCoverageLabel } from './ipamDiscoveryPresentation';
import { fetchAllIpamReconciliationItems } from './ipamExport';
import {
  canCalibrateMac,
  getReconciliationCategoryCount,
  getReconciliationEmptyMessage,
  getReconciliationEmptyState,
  RECONCILIATION_TABS,
  type ReconciliationTab,
} from './ipReconciliationPresentation';

type ReconciliationRow = Record<string, unknown> & {
  observation_id?: string;
  ipam_address_id?: string;
  ip?: string;
  address?: string;
  mac?: string;
  ipam_mac?: string;
  observed_mac?: string;
  observed_at?: string;
  last_observed_at?: string | null;
  scope_status?: string;
  evidence_status?: string;
  mac_mismatch?: boolean;
  subnet_id?: string;
  subnet_prefix?: string;
  site_id?: string | null;
  site?: string;
  site_name?: string;
  vrf_id?: string | null;
  vrf?: string;
  vrf_name?: string;
  source_device_id?: string;
  source_device_name?: string;
  switch_name?: string;
  switch_port?: string;
  vlan?: string;
  reason?: string;
};

interface ReconciliationSummary extends Record<string, unknown> {
  total_undocumented?: number;
  total_mismatched?: number;
  total_stale?: number;
  total_never_observed?: number;
  total_unscoped?: number;
  total_unavailable?: number;
  ipam_address_record_count?: number;
  allocated_ipam_address_count?: number;
  active_endpoint_count?: number;
  current_endpoint_count?: number;
  interface_snapshot_ip_count?: number;
  coverage_status?: string;
  coverage_reason?: string;
  latest_active_endpoint_seen?: string | null;
  latest_endpoint_seen?: string | null;
  endpoint_cache_fresh?: boolean;
  stale_after_days?: number;
}

interface ReconciliationData {
  undocumented_endpoints: ReconciliationRow[];
  mismatched_endpoints: ReconciliationRow[];
  stale_ip_addresses: ReconciliationRow[];
  never_observed: ReconciliationRow[];
  unscoped: ReconciliationRow[];
  unavailable: ReconciliationRow[];
  summary: ReconciliationSummary;
  resultTotal: number;
}

interface SubnetOption {
  id: string;
  prefix: string;
  name?: string;
  site_id?: string | null;
  site_name?: string | null;
  vrf_id?: string | null;
  vrf_name?: string | null;
  tenant_id?: string | null;
}

interface EndpointEvidenceDetail extends Record<string, unknown> {
  observations?: Array<Record<string, unknown>>;
}

interface IPReconciliationTabProps {
  language: string;
  t: (key: string) => string;
}

const TAB_METADATA: Record<ReconciliationTab, { title: [string, string]; icon: React.ComponentType<{ size?: number; className?: string }>; countKey: string }> = {
  undocumented: { title: ['发现未登记', 'Undocumented'], icon: Plus, countKey: 'total_undocumented' },
  mismatched: { title: ['信息不一致', 'Mismatched'], icon: ShieldAlert, countKey: 'total_mismatched' },
  stale: { title: ['长期未发现', 'Stale'], icon: WifiOff, countKey: 'total_stale' },
  never_observed: { title: ['登记后未观察', 'Never observed'], icon: Info, countKey: 'total_never_observed' },
  unscoped: { title: ['归属待确认', 'Unscoped'], icon: Globe, countKey: 'total_unscoped' },
  unavailable: { title: ['来源不可用', 'Unavailable'], icon: AlertTriangle, countKey: 'total_unavailable' },
};

const emptyData = (): ReconciliationData => ({
  undocumented_endpoints: [],
  mismatched_endpoints: [],
  stale_ip_addresses: [],
  never_observed: [],
  unscoped: [],
  unavailable: [],
  summary: {},
  resultTotal: 0,
});

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;

const asString = (value: unknown): string => typeof value === 'string' ? value : '';

const asCount = (value: unknown): number => {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
};

const asRows = (value: unknown): ReconciliationRow[] => Array.isArray(value)
  ? value.map(asRecord).filter((row): row is Record<string, unknown> => row !== null) as ReconciliationRow[]
  : [];

const textValue = (row: ReconciliationRow, ...keys: string[]): string => {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
};

const evidenceStatusLabel = (status: string, zh: boolean): string => {
  const labels: Record<string, [string, string]> = {
    recent: ['近期观察', 'Recent'], historical: ['历史观察', 'Historical'],
    scope_pending: ['归属待确认', 'Scope pending'], conflict: ['存在冲突', 'Conflict'],
    unknown: ['观察时间未知（不参与当前对账）', 'Observation time unknown (excluded from reconciliation)'],
  };
  return labels[status]?.[zh ? 0 : 1] || status || '—';
};

const scopeStatusLabel = (status: string, zh: boolean): string => {
  const labels: Record<string, [string, string]> = {
    resolved: ['范围已确认', 'Scope resolved'], scope_pending: ['归属待确认', 'Scope pending'], conflict: ['范围冲突', 'Scope conflict'],
  };
  return labels[status]?.[zh ? 0 : 1] || status || '—';
};

const safeErrorMessage = async (response: Response, zh: boolean): Promise<string> => {
  if (response.status === 401) return zh ? '登录状态已失效，请重新登录。' : 'Your session expired. Sign in again.';
  if (response.status === 403) return zh ? '当前账号没有权限执行此 IPAM 操作。' : 'You do not have permission for this IPAM action.';
  try {
    const body = asRecord(await response.json());
    const detail = body?.detail ?? body?.message;
    if (typeof detail === 'string' && detail.trim()) return detail;
  } catch { /* Response may not contain JSON. */ }
  if (response.status === 409) return zh ? '证据版本或地址状态已变化，请刷新后复核。' : 'Evidence or address state changed. Refresh and review again.';
  if (response.status === 422) return zh ? '所选地址范围或提交字段不符合要求。' : 'The selected scope or submitted fields are invalid.';
  return zh ? '操作失败，请刷新后重试。' : 'The operation failed. Refresh and retry.';
};

const getRowsForTab = (data: ReconciliationData, tab: ReconciliationTab): ReconciliationRow[] => {
  const keys: Record<ReconciliationTab, keyof ReconciliationData> = {
    undocumented: 'undocumented_endpoints',
    mismatched: 'mismatched_endpoints',
    stale: 'stale_ip_addresses',
    never_observed: 'never_observed',
    unscoped: 'unscoped',
    unavailable: 'unavailable',
  };
  const rows = data[keys[tab]];
  return Array.isArray(rows) ? rows as ReconciliationRow[] : [];
};

const IPReconciliationTab: React.FC<IPReconciliationTabProps> = ({ language }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const requestRef = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);
  const [data, setData] = useState<ReconciliationData>(emptyData);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [activeTab, setActiveTab] = useState<ReconciliationTab>('undocumented');
  const [loading, setLoading] = useState(true);
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [apiError, setApiError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [evidenceItem, setEvidenceItem] = useState<ReconciliationRow | null>(null);
  const [evidenceDetail, setEvidenceDetail] = useState<EndpointEvidenceDetail | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState('');
  const [registerItem, setRegisterItem] = useState<ReconciliationRow | null>(null);
  const [subnets, setSubnets] = useState<SubnetOption[]>([]);
  const [subnetsLoading, setSubnetsLoading] = useState(false);
  const [registerSubnetId, setRegisterSubnetId] = useState('');
  const [confirmedScope, setConfirmedScope] = useState(false);
  const [registerError, setRegisterError] = useState('');
  const [registerSubmitting, setRegisterSubmitting] = useState(false);
  const [calibrateItem, setCalibrateItem] = useState<ReconciliationRow | null>(null);
  const [calibrateConfirmed, setCalibrateConfirmed] = useState(false);
  const [calibrateError, setCalibrateError] = useState('');
  const [calibrateSubmitting, setCalibrateSubmitting] = useState(false);
  useEscapeClose(Boolean(evidenceItem), () => setEvidenceItem(null));
  useEscapeClose(Boolean(registerItem), () => setRegisterItem(null));
  useEscapeClose(Boolean(calibrateItem), () => setCalibrateItem(null));

  const authHeaders = useCallback((): Record<string, string> => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadData = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const currentRequest = ++requestSequence.current;
    setLoading(true);
    setApiError('');
    const params = new URLSearchParams({ active_tab: activeTab, q: search.trim(), page: String(page), page_size: String(pageSize) });
    try {
      const response = await fetch(`/api/ipam/reconciliation?${params.toString()}`, { headers: authHeaders(), signal: controller.signal });
      if (controller.signal.aborted || requestSequence.current !== currentRequest) return;
      if (!response.ok) {
        setApiError(await safeErrorMessage(response, zh));
        setData(emptyData());
        setHasLoaded(false);
        return;
      }
      const payload = asRecord(await response.json()) || {};
      const summary = asRecord(payload.summary) || {};
      const rawResultTotal = payload.result_total ?? payload.total;
      const resultTotal = typeof rawResultTotal === 'number' && rawResultTotal >= 0
        ? rawResultTotal
        : getReconciliationCategoryCount(summary, activeTab);
      setData({
        undocumented_endpoints: asRows(payload.undocumented_endpoints),
        mismatched_endpoints: asRows(payload.mismatched_endpoints),
        stale_ip_addresses: asRows(payload.stale_ip_addresses),
        never_observed: asRows(payload.never_observed),
        unscoped: asRows(payload.unscoped),
        unavailable: asRows(payload.unavailable),
        summary: summary as ReconciliationSummary,
        resultTotal,
      });
      setHasLoaded(true);
    } catch (error) {
      if (controller.signal.aborted || requestSequence.current !== currentRequest) return;
      setApiError(zh ? '网络错误，无法加载对账结果。' : 'Network error while loading reconciliation results.');
      setData(emptyData());
      setHasLoaded(false);
    } finally {
      if (!controller.signal.aborted && requestSequence.current === currentRequest) setLoading(false);
    }
  }, [activeTab, authHeaders, page, pageSize, search, zh]);

  useEffect(() => {
    void loadData();
    return () => requestRef.current?.abort();
  }, [loadData]);

  const activeRows = useMemo(() => getRowsForTab(data, activeTab), [data, activeTab]);
  const emptyState = getReconciliationEmptyState({
    endpoint_cache_fresh: data.summary.endpoint_cache_fresh,
    allocated_ipam_address_count: typeof data.summary.allocated_ipam_address_count === 'number' ? data.summary.allocated_ipam_address_count : undefined,
    active_endpoint_count: typeof data.summary.active_endpoint_count === 'number'
      ? data.summary.active_endpoint_count
      : typeof data.summary.current_endpoint_count === 'number' ? data.summary.current_endpoint_count : undefined,
    interface_snapshot_ip_count: typeof data.summary.interface_snapshot_ip_count === 'number' ? data.summary.interface_snapshot_ip_count : undefined,
    total_unscoped: asCount(data.summary.total_unscoped),
    coverage_status: asString(data.summary.coverage_status) || undefined,
    coverage_reason: asString(data.summary.coverage_reason) || undefined,
  }, { resultTotal: data.resultTotal, search });
  const emptyMessage = getReconciliationEmptyMessage(emptyState, activeTab, zh, asString(data.summary.coverage_reason));

  const refresh = () => { void loadData(); };
  const applySearch = () => { setPage(1); setSearch(searchDraft.trim()); };

  const openRegister = async (item: ReconciliationRow) => {
    setRegisterItem(item);
    setRegisterSubnetId('');
    setConfirmedScope(false);
    setRegisterError('');
    setSubnetsLoading(true);
    try {
      const response = await fetch('/api/ipam/subnets', { headers: authHeaders() });
      if (!response.ok) {
        setRegisterError(await safeErrorMessage(response, zh));
        setSubnets([]);
        return;
      }
      const payload = await response.json();
      const rows = Array.isArray(payload) ? payload : Array.isArray(asRecord(payload)?.items) ? asRecord(payload)?.items as unknown[] : [];
      setSubnets(rows.flatMap((raw): SubnetOption[] => {
        const row = asRecord(raw);
        if (!row || typeof row.id !== 'string' || typeof row.prefix !== 'string') return [];
        return [{
          id: row.id,
          prefix: row.prefix,
          name: typeof row.name === 'string' ? row.name : undefined,
          site_id: typeof row.site_id === 'string' ? row.site_id : null,
          site_name: typeof row.site_name === 'string' ? row.site_name : null,
          vrf_id: typeof row.vrf_id === 'string' ? row.vrf_id : null,
          vrf_name: typeof row.vrf_name === 'string' ? row.vrf_name : null,
          tenant_id: typeof row.tenant_id === 'string' ? row.tenant_id : null,
        }];
      }));
    } catch {
      setRegisterError(zh ? '网络错误，无法加载可选网段。' : 'Network error while loading candidate prefixes.');
    } finally {
      setSubnetsLoading(false);
    }
  };

  const submitRegister = async () => {
    if (!registerItem) return;
    const observationId = textValue(registerItem, 'observation_id');
    const observedAt = textValue(registerItem, 'observed_at');
    const ip = textValue(registerItem, 'ip', 'address');
    if (!observationId || !observedAt || !ip || !registerSubnetId || !confirmedScope) {
      setRegisterError(zh ? '请确认来源观察、选择网段并确认该 IP 的站点归属。' : 'Confirm the source observation, choose a prefix, and confirm the IP scope.');
      return;
    }
    setRegisterSubmitting(true);
    setRegisterError('');
    try {
      const response = await fetch('/api/ipam/reconciliation/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ observation_id: observationId, subnet_id: registerSubnetId, expected_observed_at: observedAt, confirmed_scope: true }),
      });
      if (!response.ok) {
        setRegisterError(await safeErrorMessage(response, zh));
        return;
      }
      setRegisterItem(null);
      setSuccessMessage(zh ? `已登记 IP ${ip}。原观察中的未知归属不会被回写。` : `Registered ${ip}. Unknown scope on the source observation was not rewritten.`);
      window.setTimeout(() => setSuccessMessage(''), 4500);
      void loadData();
    } catch {
      setRegisterError(zh ? '网络错误，登记未完成。' : 'Network error. Registration was not completed.');
    } finally {
      setRegisterSubmitting(false);
    }
  };

  const submitMacCalibration = async () => {
    if (!calibrateItem || !canCalibrateMac(calibrateItem) || !calibrateConfirmed) {
      setCalibrateError(zh ? '请确认只校准此 IPAM 地址的 MAC。' : 'Confirm that only this IPAM address MAC will be calibrated.');
      return;
    }
    setCalibrateSubmitting(true);
    setCalibrateError('');
    try {
      const response = await fetch('/api/ipam/reconciliation/calibrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          observation_id: calibrateItem.observation_id,
          ipam_address_id: calibrateItem.ipam_address_id,
          expected_observed_at: calibrateItem.observed_at,
          expected_mac_address: calibrateItem.ipam_mac,
          confirmed: true,
        }),
      });
      if (!response.ok) {
        setCalibrateError(await safeErrorMessage(response, zh));
        return;
      }
      const ip = textValue(calibrateItem, 'ip', 'address');
      setCalibrateItem(null);
      setSuccessMessage(zh ? `已更新 ${ip} 的登记 MAC。` : `Updated the registered MAC for ${ip}.`);
      window.setTimeout(() => setSuccessMessage(''), 4500);
      void loadData();
    } catch {
      setCalibrateError(zh ? '网络错误，MAC 校准未完成。' : 'Network error. MAC calibration was not completed.');
    } finally {
      setCalibrateSubmitting(false);
    }
  };

  useEffect(() => {
    if (!evidenceItem) {
      setEvidenceDetail(null);
      setEvidenceError('');
      setEvidenceLoading(false);
      return;
    }
    const observationId = textValue(evidenceItem, 'observation_id');
    if (!observationId) {
      setEvidenceDetail(null);
      setEvidenceError('');
      setEvidenceLoading(false);
      return;
    }
    const controller = new AbortController();
    setEvidenceDetail(null);
    setEvidenceError('');
    setEvidenceLoading(true);
    fetch(`/api/ipam/endpoints/${encodeURIComponent(observationId)}`, { headers: authHeaders(), signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw Object.assign(new Error('evidence'), { status: response.status });
        return response.json();
      })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setEvidenceDetail(asRecord(payload) as EndpointEvidenceDetail | null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = asRecord(error)?.status;
        setEvidenceError(typeof status === 'number'
          ? status === 401 ? (zh ? '登录状态已失效。' : 'Your session expired.') : status === 403 ? (zh ? '没有权限查看来源证据。' : 'You do not have permission to view this evidence.') : (zh ? '加载来源证据失败。' : 'Failed to load source evidence.')
          : (zh ? '网络错误，无法加载来源证据。' : 'Network error while loading source evidence.'));
      })
      .finally(() => { if (!controller.signal.aborted) setEvidenceLoading(false); });
    return () => controller.abort();
  }, [authHeaders, evidenceItem, zh]);

  const selectedSubnet = subnets.find((subnet) => subnet.id === registerSubnetId) || null;
  const categoryCountDisplay = (tab: ReconciliationTab): string => {
    const key = TAB_METADATA[tab].countKey;
    const raw = data.summary[key];
    const count = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : NaN;
    return hasLoaded && Number.isFinite(count) && count >= 0 ? count.toLocaleString() : '—';
  };
  const coverageStatus = getDiscoveryCoverageLabel(asString(data.summary.coverage_status), zh);
  const exportAll = useCallback(async () => {
    const rows = await fetchAllIpamReconciliationItems<ReconciliationRow>('/api/ipam/reconciliation', new URLSearchParams({ active_tab: activeTab, q: search }), activeTab);
    const site = (item: ReconciliationRow) => `${textValue(item, 'site_name', 'site') || '—'} / ${textValue(item, 'vrf_name', 'vrf') || '—'}`;
    if (activeTab === 'unavailable') return {
      headers: [zh ? '来源设备' : 'Source device', zh ? '来源类型' : 'Source type', zh ? '采集状态' : 'Collection status', zh ? '最近成功时间' : 'Last success', zh ? '原因' : 'Reason'],
      rows: rows.map(item => [textValue(item, 'source_device_name', 'source_device_id'), textValue(item, 'source_type'), textValue(item, 'status'), textValue(item, 'last_success_at'), textValue(item, 'reason')]),
    };
    if (activeTab === 'stale' || activeTab === 'never_observed') return {
      headers: ['IP', zh ? '状态' : 'Status', zh ? '网段' : 'Prefix', zh ? '站点 / VRF' : 'Site / VRF', zh ? '最近观察' : 'Last observed', zh ? '完整未发现次数' : 'Complete misses'],
      rows: rows.map(item => [textValue(item, 'ip', 'address'), textValue(item, 'registration_status', 'status'), textValue(item, 'subnet_prefix'), site(item), textValue(item, 'last_observed_at'), textValue(item, 'miss_count')]),
    };
    if (activeTab === 'mismatched') return {
      headers: ['IP', 'IPAM MAC', zh ? '观察 MAC' : 'Observed MAC', zh ? '站点 / VRF' : 'Site / VRF', zh ? '观察时间' : 'Observed at', zh ? '范围 / 证据' : 'Scope / evidence'],
      rows: rows.map(item => [textValue(item, 'ip', 'address'), textValue(item, 'ipam_mac'), textValue(item, 'observed_mac'), site(item), textValue(item, 'observed_at'), `${scopeStatusLabel(textValue(item, 'scope_status'), zh)} / ${evidenceStatusLabel(textValue(item, 'evidence_status'), zh)}`]),
    };
    return {
      headers: ['IP', 'MAC', zh ? '站点 / VRF' : 'Site / VRF', zh ? '来源设备 / 端口' : 'Source device / port', zh ? '网段' : 'Prefix', zh ? '观察时间' : 'Observed at', zh ? '范围 / 证据' : 'Scope / evidence'],
      rows: rows.map(item => [textValue(item, 'ip', 'address'), textValue(item, 'mac'), site(item), `${textValue(item, 'source_device_name', 'switch_name')} / ${textValue(item, 'switch_port')}`, textValue(item, 'subnet_prefix'), textValue(item, 'observed_at', 'last_observed_at'), `${scopeStatusLabel(textValue(item, 'scope_status'), zh)} / ${evidenceStatusLabel(textValue(item, 'evidence_status'), zh)}`]),
    };
  }, [activeTab, search, zh]);



  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden px-5 py-4 sm:px-6">
      <PageHero
        compact
        icon={ClipboardCheck}
        title={zh ? 'IPAM 对账' : 'IPAM Reconciliation'}
        subtitle={zh ? '核对 IPAM 登记与 ARP/MAC 发现记录，找出需要确认的差异。' : 'Review differences between the IPAM ledger and discovery evidence. This page does not release addresses or collect from devices.'}
        actions={<button type="button" onClick={refresh} disabled={loading} className="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--ui-accent)] px-3 text-xs font-semibold text-white disabled:opacity-60"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{zh ? '刷新结果' : 'Refresh'}</button>}
      />

      {apiError && <div role="alert" className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-800"><AlertTriangle size={15} /><span className="flex-1">{apiError}</span><button type="button" onClick={() => setApiError('')} aria-label={zh ? '关闭错误' : 'Dismiss error'}><X size={14} /></button></div>}
      {successMessage && <div role="status" className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs text-emerald-800"><CheckCircle2 size={15} />{successMessage}</div>}

      <section aria-label={zh ? '对账覆盖摘要' : 'Reconciliation coverage summary'} className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[var(--muted-text)]">
        <span>{zh ? 'IPAM 已登记 IP' : 'Registered IPs'}: <strong>{typeof data.summary.ipam_address_record_count === 'number' ? data.summary.ipam_address_record_count.toLocaleString() : typeof data.summary.allocated_ipam_address_count === 'number' ? data.summary.allocated_ipam_address_count.toLocaleString() : '—'}</strong></span>
        <span>{zh ? '可核对发现 IP' : 'Comparable discovered IPs'}: <strong>{typeof data.summary.active_endpoint_count === 'number' ? data.summary.active_endpoint_count.toLocaleString() : '—'}</strong></span>
        <span>{coverageStatus}</span>
      </section>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 2xl:grid-cols-6" role="group" aria-label={zh ? '对账分类' : 'Reconciliation categories'}>
        {RECONCILIATION_TABS.map((tab) => {
          const active = activeTab === tab;
          const metadata = TAB_METADATA[tab];
          const Icon = metadata.icon;
          return (
            <button key={tab} type="button" aria-pressed={active} onClick={() => { setActiveTab(tab); setPage(1); }} className={`rounded-xl border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] ${active ? 'border-[var(--ui-accent)] bg-[var(--ui-accent-soft)]' : 'border-[var(--card-border)] bg-[var(--card-bg)] hover:border-[var(--ui-accent)]'}`}>
              <span className="flex items-center justify-between gap-2"><span className="text-[10px] font-semibold text-[var(--muted-text)]">{metadata.title[zh ? 0 : 1]}</span><Icon size={14} className="text-[var(--ui-accent)]" /></span>
              <strong className="mt-1 block text-lg tabular-nums text-[var(--ui-fg)]">{categoryCountDisplay(tab)}</strong>
            </button>
          );
        })}
      </div>

      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ui-border)] px-4 py-3">
          <div><h2 className="text-sm font-bold text-[var(--ui-fg)]">{TAB_METADATA[activeTab].title[zh ? 0 : 1]}</h2><p className="mt-0.5 text-[10px] text-[var(--muted-text)]">{zh ? `当前分类 ${data.resultTotal.toLocaleString()} 条` : `${data.resultTotal.toLocaleString()} results in this category`}</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <form onSubmit={(event) => { event.preventDefault(); applySearch(); }} className="flex gap-1.5">
              <label className="relative"><span className="sr-only">{zh ? '搜索 IP、MAC、站点或来源设备' : 'Search IP, MAC, site, or source device'}</span><Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" /><input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder={zh ? '搜索 IP / MAC / 站点...' : 'Search IP / MAC / site...'} className="h-9 w-56 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] pl-8 pr-2 text-xs text-[var(--ui-fg)]" /></label>
              <button type="submit" className="h-9 rounded-lg border border-[var(--ui-border)] px-3 text-xs font-semibold text-[var(--ui-fg)]">{zh ? '搜索' : 'Search'}</button>
              {search && <button type="button" onClick={() => { setSearch(''); setSearchDraft(''); setPage(1); }} className="h-9 rounded-lg px-2 text-xs text-[var(--ui-fg-muted)]">{zh ? '清除' : 'Clear'}</button>}
            </form>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {loading ? <div className="flex h-full min-h-40 items-center justify-center gap-2 text-xs text-[var(--muted-text)]"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载对账结果…' : 'Loading reconciliation results…'}</div>
            : apiError ? <div className="flex h-full min-h-40 items-center justify-center text-xs text-[var(--muted-text)]">{zh ? '结果暂不可用，请修复错误后重试。' : 'Results are unavailable. Retry after resolving the error.'}</div>
              : <DataTable className="min-w-[1020px] text-left" exportConfig={{ filename: `ipam-reconciliation-${activeTab}`, exportData: exportAll, language: zh ? 'zh' : 'en', disabled: loading || activeRows.length === 0 }}>
                <thead><tr>
                  {activeTab === 'unavailable' ? <><th>{zh ? '来源设备' : 'Source device'}</th><th>{zh ? '来源类型' : 'Source type'}</th><th>{zh ? '采集状态' : 'Collection status'}</th><th>{zh ? '最近成功时间' : 'Last success'}</th><th>{zh ? '原因' : 'Reason'}</th></>
                    : activeTab === 'stale' || activeTab === 'never_observed' ? <><th>IP</th><th>{zh ? '状态' : 'Status'}</th><th>{zh ? '网段' : 'Prefix'}</th><th>{zh ? '站点 / VRF' : 'Site / VRF'}</th><th>{zh ? '最近观察' : 'Last observed'}</th><th>{zh ? '完整未发现次数' : 'Complete misses'}</th></>
                      : activeTab === 'mismatched' ? <><th>IP</th><th>{zh ? 'IPAM MAC' : 'IPAM MAC'}</th><th>{zh ? '观察 MAC' : 'Observed MAC'}</th><th>{zh ? '站点 / VRF' : 'Site / VRF'}</th><th>{zh ? '观察时间' : 'Observed at'}</th><th>{zh ? '范围 / 证据' : 'Scope / evidence'}</th></>
                        : <><th>IP</th><th>MAC</th><th>{zh ? '站点 / VRF' : 'Site / VRF'}</th><th>{zh ? '来源设备 / 端口' : 'Source device / port'}</th><th>{zh ? '网段' : 'Prefix'}</th><th>{zh ? '观察时间' : 'Observed at'}</th><th>{zh ? '范围 / 证据' : 'Scope / evidence'}</th></>}
                  <TableActionHeader>{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr></thead>
                <tbody>
                  {activeRows.length ? activeRows.map((item, index) => {
                    const ip = textValue(item, 'ip', 'address');
                    const observationId = textValue(item, 'observation_id');
                    const isRegisterable = activeTab === 'undocumented'
                      && Boolean(observationId && ip && textValue(item, 'observed_at'))
                      && textValue(item, 'evidence_status') === 'recent'
                      && textValue(item, 'timestamp_status') === 'valid';
                    const isCalibratable = activeTab === 'mismatched' && canCalibrateMac(item);
                    return <tr key={observationId || textValue(item, 'ipam_address_id', 'id') || `${activeTab}-${index}`}>
                      {activeTab === 'unavailable' ? <><td>{textValue(item, 'source_device_name', 'source_device_id') || (zh ? '未知来源' : 'Unknown source')}</td><td>{textValue(item, 'source_type') || '—'}</td><td>{textValue(item, 'status') || (zh ? '未知' : 'Unknown')}</td><td className="font-mono">{textValue(item, 'last_success_at') || '—'}</td><td>{textValue(item, 'reason') || '—'}</td></>
                        : activeTab === 'stale' || activeTab === 'never_observed' ? <><td className="font-mono font-semibold">{ip || '—'}</td><td>{textValue(item, 'registration_status', 'status') || (zh ? '已登记' : 'Registered')}</td><td className="font-mono">{textValue(item, 'subnet_prefix') || '—'}</td><td>{textValue(item, 'site_name', 'site') || (zh ? '未知站点' : 'Unknown site')} / {textValue(item, 'vrf_name', 'vrf') || (zh ? '待确认' : 'Pending')}</td><td className="font-mono">{textValue(item, 'last_observed_at') || (zh ? '从未观察' : 'Never observed')}</td><td>{textValue(item, 'miss_count') ? `${textValue(item, 'miss_count')}/${textValue(item, 'required_misses') || '—'}` : '—'}</td></>
                      : activeTab === 'mismatched' ? <><td className="font-mono font-semibold">{ip || '—'}</td><td className="font-mono">{textValue(item, 'ipam_mac') || '—'}</td><td className="font-mono">{textValue(item, 'observed_mac') || '—'}</td><td>{textValue(item, 'site_name', 'site') || (zh ? '未知站点' : 'Unknown site')} / {textValue(item, 'vrf_name', 'vrf') || (zh ? '待确认' : 'Pending')}</td><td className="font-mono">{textValue(item, 'observed_at') || '—'}</td><td>{scopeStatusLabel(textValue(item, 'scope_status'), zh)} / {evidenceStatusLabel(textValue(item, 'evidence_status'), zh)}</td></>
                            : <><td className="font-mono font-semibold">{ip || '—'}</td><td className="font-mono">{textValue(item, 'mac') || '—'}</td><td>{textValue(item, 'site_name', 'site') || (zh ? '未知站点' : 'Unknown site')} / {textValue(item, 'vrf_name', 'vrf') || (zh ? '待确认' : 'Pending')}</td><td>{textValue(item, 'source_device_name', 'switch_name') || (zh ? '未知设备' : 'Unknown device')} / {textValue(item, 'switch_port') || (zh ? '端口待定位' : 'Port pending')}</td><td className="font-mono">{textValue(item, 'subnet_prefix') || '—'}</td><td className="font-mono">{textValue(item, 'observed_at', 'last_observed_at') || '—'}</td><td>{scopeStatusLabel(textValue(item, 'scope_status'), zh)} / {evidenceStatusLabel(textValue(item, 'evidence_status'), zh)}</td></>}
                      <TableActionCell><div className="flex items-center justify-end gap-1">
                        <ActionIconButton icon={Eye} label={zh ? '查看证据' : 'View evidence'} onClick={() => setEvidenceItem(item)} />
                        {isRegisterable && <ActionIconButton icon={Plus} label={zh ? '登记到 IPAM' : 'Register in IPAM'} variant="accent" onClick={() => void openRegister(item)} />}
                        {isCalibratable && <ActionIconButton icon={CheckCircle2} label={zh ? '校准 MAC' : 'Calibrate MAC'} variant="accent" onClick={() => { setCalibrateItem(item); setCalibrateConfirmed(false); setCalibrateError(''); }} />}
                        <ActionIconButton icon={Globe} label={zh ? '打开 IP 地址台账' : 'Open IP address ledger'} onClick={() => navigate('/ipam/ips')} />
                      </div></TableActionCell>
                    </tr>;
                  }) : <tr><td colSpan={activeTab === 'unavailable' ? 6 : activeTab === 'stale' || activeTab === 'never_observed' ? 7 : activeTab === 'mismatched' ? 7 : 8} className="py-12 text-center text-xs text-[var(--ui-fg-muted)]">{emptyMessage}</td></tr>}
                </tbody>
              </DataTable>}
        </div>
        <Pagination currentPage={page} totalItems={data.resultTotal} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
      </section>

      {evidenceItem && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setEvidenceItem(null); }}>
        <section role="dialog" aria-modal="true" aria-labelledby="reconciliation-evidence-title" className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
          <header className="flex items-start justify-between border-b border-[var(--ui-border)] px-5 py-4"><div><h2 id="reconciliation-evidence-title" className="text-sm font-bold text-[var(--ui-fg)]">{zh ? '核查证据' : 'Review evidence'}</h2><p className="mt-1 font-mono text-xs text-[var(--ui-fg-muted)]">{textValue(evidenceItem, 'ip', 'address') || '—'} · {textValue(evidenceItem, 'observation_id') || (zh ? '无观察 ID' : 'No observation ID')}</p></div><button type="button" onClick={() => setEvidenceItem(null)} aria-label={zh ? '关闭证据' : 'Close evidence'} className="rounded-lg p-2 text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]"><X size={15} /></button></header>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {evidenceLoading && <div className="flex items-center gap-2 py-4 text-xs text-[var(--ui-fg-muted)]"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载来源证据…' : 'Loading source evidence…'}</div>}
            {evidenceError && <div role="alert" className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">{evidenceError}</div>}
            <dl className="grid grid-cols-1 gap-3 rounded-xl border border-[var(--ui-border)] p-3 text-xs sm:grid-cols-2">
              <div><dt className="text-[var(--ui-fg-muted)]">{zh ? 'IPAM 地址 ID' : 'IPAM address ID'}</dt><dd className="mt-1 font-mono">{textValue(evidenceItem, 'ipam_address_id') || '—'}</dd></div>
              <div><dt className="text-[var(--ui-fg-muted)]">{zh ? 'MAC（登记 / 观察）' : 'MAC (registered / observed)'}</dt><dd className="mt-1 font-mono">{textValue(evidenceItem, 'ipam_mac') || '—'} / {textValue(evidenceItem, 'observed_mac', 'mac') || '—'}</dd></div>
              <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '站点 / VRF' : 'Site / VRF'}</dt><dd className="mt-1">{textValue(evidenceItem, 'site_name', 'site') || '—'} / {textValue(evidenceItem, 'vrf_name', 'vrf') || '—'}</dd></div>
              <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '范围 / 证据状态' : 'Scope / evidence status'}</dt><dd className="mt-1">{scopeStatusLabel(textValue(evidenceItem, 'scope_status'), zh)} / {evidenceStatusLabel(textValue(evidenceItem, 'evidence_status'), zh)}</dd></div>
              <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '观察时间 / 最近成功' : 'Observed / last success'}</dt><dd className="mt-1 font-mono">{textValue(evidenceItem, 'observed_at', 'last_observed_at', 'last_success_at') || '—'}</dd></div>
              <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '来源 / 原因' : 'Source / reason'}</dt><dd className="mt-1">{textValue(evidenceItem, 'source_device_name', 'source_device_id', 'source_type') || '—'} / {textValue(evidenceItem, 'reason') || '—'}</dd></div>
            </dl>
            {evidenceDetail?.observations?.length ? <div className="mt-4 space-y-2"><h3 className="text-xs font-bold">{zh ? '原始观察' : 'Source observations'}</h3>{evidenceDetail.observations.map((observation, index) => <article key={String(observation.source_version || observation.observed_at || index)} className="rounded-xl border border-[var(--ui-border)] p-3 text-xs"><div className="flex justify-between gap-2"><strong>{asString(observation.source_type).toUpperCase() || '—'} · {asString(observation.source_device_name) || asString(observation.source_device_id) || '—'}</strong><span className="font-mono">{asString(observation.observed_at) || (zh ? '时间未知' : 'Time unknown')}</span></div><div className="mt-2 grid grid-cols-2 gap-2 text-[var(--ui-fg-muted)] sm:grid-cols-4"><span>IP: {asString(observation.ip) || '—'}</span><span>MAC: {asString(observation.mac) || '—'}</span><span>{zh ? '接口' : 'Interface'}: {asString(observation.interface_name) || '—'}</span><span>VLAN: {asString(observation.vlan) || '—'}</span></div><div className="mt-1 text-[10px] text-[var(--ui-fg-muted)]">{zh ? '源版本' : 'Source version'}: {asString(observation.source_version) || '—'} · {zh ? '时间校验' : 'Timestamp'}: {asString(observation.timestamp_status) || '—'} · {zh ? '覆盖状态' : 'Coverage'}: {asString(observation.coverage_status) || '—'}</div></article>)}</div> : null}
            {!textValue(evidenceItem, 'observation_id') && <p className="mt-3 text-[11px] text-[var(--ui-fg-muted)]">{zh ? '该记录没有单条观察 ID，以上为对账返回的历史/来源状态；请前往 IP 地址台账继续核查。' : 'This row has no individual observation ID. The fields above are the returned historical/source status; continue in the IP address ledger.'}</p>}
            <button type="button" onClick={() => { setEvidenceItem(null); navigate('/ipam/ips'); }} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-[var(--ui-border)] px-3 py-2 text-xs font-semibold text-[var(--ui-fg)]"><Globe size={13} />{zh ? '打开 IP 地址台账' : 'Open IP address ledger'}</button>
          </div>
        </section>
      </div>}

      {registerItem && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setRegisterItem(null); }}>
        <section role="dialog" aria-modal="true" aria-labelledby="register-observation-title" className="w-full max-w-xl overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
          <header className="flex items-start justify-between border-b border-[var(--ui-border)] px-5 py-4"><div><h2 id="register-observation-title" className="text-sm font-bold">{zh ? '登记观察到的 IP' : 'Register observed IP'}</h2><p className="mt-1 text-[11px] text-[var(--ui-fg-muted)]">{zh ? '请选择目标网段并明确确认地址归属；不会修改原始观察的站点或 VRF。' : 'Choose the target prefix and explicitly confirm scope. The source observation site or VRF will not be changed.'}</p></div><button type="button" onClick={() => setRegisterItem(null)} aria-label={zh ? '关闭登记' : 'Close registration'}><X size={15} /></button></header>
          <div className="space-y-3 p-5">
            <div className="grid grid-cols-2 gap-3 rounded-xl border border-[var(--ui-border)] p-3 text-xs"><div><span className="text-[var(--ui-fg-muted)]">IP</span><div className="mt-1 font-mono font-bold">{textValue(registerItem, 'ip', 'address') || '—'}</div></div><div><span className="text-[var(--ui-fg-muted)]">MAC</span><div className="mt-1 font-mono">{textValue(registerItem, 'mac') || '—'}</div></div><div><span className="text-[var(--ui-fg-muted)]">{zh ? '来源站点 / VRF' : 'Observed site / VRF'}</span><div className="mt-1">{textValue(registerItem, 'site_name', 'site') || (zh ? '待确认' : 'Pending')} / {textValue(registerItem, 'vrf_name', 'vrf') || (zh ? '待确认' : 'Pending')}</div></div><div><span className="text-[var(--ui-fg-muted)]">{zh ? '来源版本时间' : 'Observation version'}</span><div className="mt-1 font-mono">{textValue(registerItem, 'observed_at') || '—'}</div></div></div>
            <label className="block text-xs font-semibold">{zh ? '目标网段' : 'Target prefix'}<select aria-label={zh ? '目标 IPAM 网段' : 'Target IPAM prefix'} value={registerSubnetId} onChange={(event) => setRegisterSubnetId(event.target.value)} disabled={subnetsLoading} className="mt-1.5 h-10 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-xs"><option value="">{subnetsLoading ? (zh ? '加载网段…' : 'Loading prefixes…') : (zh ? '请选择网段' : 'Select a prefix')}</option>{subnets.map((subnet) => <option key={subnet.id} value={subnet.id}>{subnet.prefix}{subnet.name ? ` · ${subnet.name}` : ''} · {subnet.site_name || subnet.site_id || (zh ? '未知站点' : 'Unknown site')}{subnet.vrf_name ? ` · ${subnet.vrf_name}` : ''}</option>)}</select></label>
            {selectedSubnet && <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900"><strong>{zh ? '登记预览' : 'Registration preview'}</strong><p className="mt-1 font-mono">{textValue(registerItem, 'ip', 'address')} → {selectedSubnet.prefix}</p><p className="mt-1">{zh ? '目标站点 / VRF' : 'Target site / VRF'}: {selectedSubnet.site_name || selectedSubnet.site_id || (zh ? '未提供' : 'Not provided')} / {selectedSubnet.vrf_name || (zh ? '未提供' : 'Not provided')}</p></div>}
            <label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><input type="checkbox" checked={confirmedScope} onChange={(event) => setConfirmedScope(event.target.checked)} className="mt-0.5" /><span>{zh ? '我已核对来源、目标网段和站点归属，确认将此 IP 登记到所选网段。若服务端无法验证来源设备范围，操作会被拒绝。' : 'I reviewed the source, target prefix, and site assignment and confirm registering this IP in the selected prefix. The server will reject the operation if the source device scope cannot be verified.'}</span></label>
            {registerError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-800">{registerError}</div>}
          </div>
          <footer className="flex justify-end gap-2 border-t border-[var(--ui-border)] px-5 py-3"><button type="button" onClick={() => setRegisterItem(null)} className="rounded-lg border border-[var(--ui-border)] px-3 py-2 text-xs">{zh ? '取消' : 'Cancel'}</button><button type="button" onClick={() => void submitRegister()} disabled={registerSubmitting || subnetsLoading || !registerSubnetId || !confirmedScope} className="rounded-lg bg-[var(--ui-accent)] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{registerSubmitting ? (zh ? '提交中…' : 'Submitting…') : (zh ? '确认登记' : 'Confirm registration')}</button></footer>
        </section>
      </div>}

      {calibrateItem && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCalibrateItem(null); }}>
        <section role="dialog" aria-modal="true" aria-labelledby="calibrate-mac-title" className="w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
          <header className="flex items-start justify-between border-b border-[var(--ui-border)] px-5 py-4"><div><h2 id="calibrate-mac-title" className="text-sm font-bold">{zh ? '确认校准登记 MAC' : 'Confirm registered MAC calibration'}</h2><p className="mt-1 text-[11px] text-[var(--ui-fg-muted)]">{zh ? '仅更新当前 IPAM 地址的 MAC；不会修改主机名、状态、站点或 VRF。' : 'Only the MAC on this IPAM address will change. Hostname, status, site, and VRF remain unchanged.'}</p></div><button type="button" onClick={() => setCalibrateItem(null)} aria-label={zh ? '关闭校准' : 'Close calibration'}><X size={15} /></button></header>
          <div className="space-y-3 p-5 text-xs"><div className="rounded-xl border border-[var(--ui-border)] p-3"><div>{zh ? 'IP / 站点 / VRF' : 'IP / Site / VRF'}: <strong className="font-mono">{textValue(calibrateItem, 'ip')}</strong> · {textValue(calibrateItem, 'site_name', 'site') || '—'} / {textValue(calibrateItem, 'vrf_name', 'vrf') || '—'}</div><div className="mt-2 font-mono">{textValue(calibrateItem, 'ipam_mac')} → {textValue(calibrateItem, 'observed_mac')}</div><div className="mt-2 text-[10px] text-[var(--ui-fg-muted)]">{zh ? '当前观察版本' : 'Observation version'}: {textValue(calibrateItem, 'observed_at')}</div></div><p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">{zh ? '仅当范围明确、当前 ARP 观察唯一且无同 IP 多 MAC 冲突时允许校准。提交会携带当前 MAC 与观察时间做版本校验。' : 'Calibration is allowed only for a resolved scope with one current ARP observation and no same-IP multi-MAC conflict. The request carries the current MAC and observation timestamp for version checks.'}</p><label className="flex items-start gap-2"><input type="checkbox" checked={calibrateConfirmed} onChange={(event) => setCalibrateConfirmed(event.target.checked)} className="mt-0.5" /><span>{zh ? '我确认仅将 IPAM 登记 MAC 更新为本次显示的 ARP 观察 MAC。' : 'I confirm changing only the registered MAC to the ARP MAC shown above.'}</span></label>{calibrateError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-rose-800">{calibrateError}</div>}</div>
          <footer className="flex justify-end gap-2 border-t border-[var(--ui-border)] px-5 py-3"><button type="button" onClick={() => setCalibrateItem(null)} className="rounded-lg border border-[var(--ui-border)] px-3 py-2 text-xs">{zh ? '取消' : 'Cancel'}</button><button type="button" onClick={() => void submitMacCalibration()} disabled={calibrateSubmitting || !calibrateConfirmed} className="rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{calibrateSubmitting ? (zh ? '校准中…' : 'Calibrating…') : (zh ? '确认校准 MAC' : 'Confirm MAC calibration')}</button></footer>
        </section>
      </div>}
    </div>
  );
};

export default IPReconciliationTab;
