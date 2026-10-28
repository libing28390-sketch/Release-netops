import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Clock3, Eye, Globe, Info, RefreshCw, Search, X } from 'lucide-react';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { DataTable } from '../../components/DataTable';
import { ActionIconButton } from '../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { fetchAllIpamExportItems } from './ipamExport';
import {
  buildDiscoveredEndpointQuery,
  getDiscoveryEvidenceLabel,
  getDiscoveryCoverageLabel,
  getDiscoveryHostname,
  getDiscoveryPortLabel,
  getDiscoveryRegistrationLabel,
  getDiscoveryTypeLabel,
  normalizeDiscoveryOptions,
  type DiscoveredEndpointFilters,
  type DiscoveredEndpointRow,
  type DiscoveryFilterOption,
} from './ipamDiscoveryPresentation';

interface DiscoverySummary {
  discovered_ip_count?: number;
  mac_only_count?: number;
  registered_count?: number;
  unregistered_count?: number;
  scope_pending_count?: number;
  conflict_count?: number;
  coverage_status?: string;
  coverage_reason?: string;
  source_last_success_at?: string | null;
}

interface DiscoveryObservation {
  source_type?: string;
  source_device_id?: string | null;
  source_device_name?: string | null;
  interface_name?: string | null;
  vlan?: string | null;
  ip?: string | null;
  mac?: string | null;
  observed_at?: string | null;
  projected_at?: string | null;
  source_version?: string | null;
  coverage_status?: string | null;
  timestamp_status?: string | null;
}

interface DiscoveryDetail extends DiscoveredEndpointRow {
  observations?: DiscoveryObservation[];
  evidence?: unknown;
}

interface DeviceOption extends DiscoveryFilterOption {
  label: string;
}

interface DiscoveredEndpointsTabProps {
  language: string;
  t: (key: string) => string;
}

const initialFilters: DiscoveredEndpointFilters = {
  siteId: '',
  vrfId: '',
  deviceId: '',
  query: '',
  kind: 'ip',
  evidenceStatus: '',
  registrationStatus: '',
  page: 1,
  pageSize: 20,
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;

const readCount = (summary: DiscoverySummary | null, key: keyof DiscoverySummary): string => {
  const value = summary?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
};

const authorizationError = (status: number, zh: boolean): string => {
  if (status === 401) return zh ? '登录状态已失效，请重新登录。' : 'Your session expired. Sign in again.';
  if (status === 403) return zh ? '当前账号没有权限查看发现终端。' : 'You do not have permission to view discovered endpoints.';
  return '';
};

function normalizeEndpoint(value: unknown): DiscoveredEndpointRow | null {
  const row = asRecord(value);
  if (!row || typeof row.id !== 'string' || !row.id) return null;
  const nullableText = (key: string): string | null => typeof row[key] === 'string' && (row[key] as string).trim() ? row[key] as string : null;
  return {
    id: row.id,
    ip: nullableText('ip'),
    mac: nullableText('mac'),
    tenant_id: nullableText('tenant_id'),
    site_id: nullableText('site_id'),
    site_name: nullableText('site_name'),
    vrf_id: nullableText('vrf_id'),
    vrf_name: nullableText('vrf_name'),
    scope_status: typeof row.scope_status === 'string' ? row.scope_status : undefined,
    registration_status: typeof row.registration_status === 'string' ? row.registration_status : undefined,
    subnet_id: nullableText('subnet_id'),
    subnet_prefix: nullableText('subnet_prefix'),
    source_device_id: nullableText('source_device_id'),
    source_device_name: nullableText('source_device_name'),
    switch_id: nullableText('switch_id'),
    switch_name: nullableText('switch_name'),
    switch_port: nullableText('switch_port'),
    vlan: nullableText('vlan'),
    observed_at: nullableText('observed_at'),
    mac_observed_at: nullableText('mac_observed_at'),
    projected_at: nullableText('projected_at'),
    evidence_status: typeof row.evidence_status === 'string' ? row.evidence_status : undefined,
    hostname: nullableText('hostname'),
  };
}

const formatObserved = (value: string | null | undefined): string => value || '—';

const DiscoveredEndpointsTab: React.FC<DiscoveredEndpointsTabProps> = ({ language }) => {
  const zh = language === 'zh';
  const listRequestRef = useRef<AbortController | null>(null);
  const detailRequestRef = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);
  const [filters, setFilters] = useState(initialFilters);
  const [searchDraft, setSearchDraft] = useState('');
  const [items, setItems] = useState<DiscoveredEndpointRow[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<DiscoverySummary | null>(null);
  const [sites, setSites] = useState<DiscoveryFilterOption[]>([]);
  const [vrfs, setVrfs] = useState<DiscoveryFilterOption[]>([]);
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<DiscoveredEndpointRow | null>(null);
  const [detail, setDetail] = useState<DiscoveryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  useEscapeClose(Boolean(selected), () => setSelected(null));

  const authHeaders = useCallback((): Record<string, string> => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadList = useCallback(async () => {
    listRequestRef.current?.abort();
    const controller = new AbortController();
    listRequestRef.current = controller;
    const currentRequest = ++requestSequence.current;
    setLoading(true);
    setLoadError('');
    const query = buildDiscoveredEndpointQuery(filters);
    try {
      const response = await fetch(`/api/ipam/endpoints?${query.toString()}`, {
        headers: authHeaders(),
        signal: controller.signal,
      });
      if (controller.signal.aborted || currentRequest !== requestSequence.current) return;
      if (!response.ok) {
        const message = authorizationError(response.status, zh);
        setLoadError(message || (zh ? '加载发现终端失败，请稍后重试。' : 'Failed to load discovered endpoints. Retry shortly.'));
        setItems([]);
        setTotal(0);
        setSummary(null);
        return;
      }
      const payload = asRecord(await response.json()) || {};
      const rawItems = Array.isArray(payload.items) ? payload.items : [];
      setItems(rawItems.map(normalizeEndpoint).filter((row): row is DiscoveredEndpointRow => row !== null));
      setTotal(typeof payload.total === 'number' && payload.total >= 0 ? payload.total : 0);
      setSummary(asRecord(payload.summary) as DiscoverySummary | null);
      setSites(normalizeDiscoveryOptions(payload.sites, ['id', 'site_id'], ['name', 'site_name', 'label']));
      setVrfs(normalizeDiscoveryOptions(payload.vrfs, ['id', 'vrf_id'], ['name', 'vrf_name', 'label']));
      setDevices(normalizeDiscoveryOptions(payload.devices, ['id', 'device_id', 'source_device_id'], ['name', 'device_name', 'source_device_name', 'hostname'])
        .map((device) => ({ ...device, label: device.name })));
    } catch (error) {
      if (controller.signal.aborted || currentRequest !== requestSequence.current) return;
      setLoadError(zh ? '网络错误，无法加载发现终端。' : 'Network error while loading discovered endpoints.');
      setItems([]);
      setTotal(0);
      setSummary(null);
    } finally {
      if (!controller.signal.aborted && currentRequest === requestSequence.current) setLoading(false);
    }
  }, [authHeaders, filters, zh]);

  useEffect(() => {
    void loadList();
    return () => listRequestRef.current?.abort();
  }, [loadList]);

  useEffect(() => {
    if (!selected) {
      detailRequestRef.current?.abort();
      setDetail(null);
      setDetailError('');
      setDetailLoading(false);
      return;
    }
    detailRequestRef.current?.abort();
    const controller = new AbortController();
    detailRequestRef.current = controller;
    setDetail(null);
    setDetailError('');
    setDetailLoading(true);
    fetch(`/api/ipam/endpoints/${encodeURIComponent(selected.id)}`, { headers: authHeaders(), signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw Object.assign(new Error('detail'), { status: response.status });
        return response.json();
      })
      .then((payload) => {
        if (controller.signal.aborted) return;
        const root = asRecord(payload);
        const normalized = normalizeEndpoint(root);
        if (root && normalized) {
          const observations = Array.isArray(root.observations) ? root.observations as DiscoveryObservation[] : [];
          setDetail({ ...normalized, observations, evidence: root.evidence });
        } else {
          setDetailError(zh ? '详情数据格式不正确。' : 'The detail response has an invalid format.');
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = asRecord(error)?.status;
        setDetailError(typeof status === 'number'
          ? authorizationError(status, zh) || (zh ? '加载来源证据失败。' : 'Failed to load source evidence.')
          : (zh ? '网络错误，无法加载来源证据。' : 'Network error while loading source evidence.'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [authHeaders, selected, zh]);

  const updateFilter = <K extends keyof DiscoveredEndpointFilters>(key: K, value: DiscoveredEndpointFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value, page: 1 }));
  };

  const applySearch = () => updateFilter('query', searchDraft);
  const visibleRows = useMemo(() => items, [items]);
  const coverageStatus = summary?.coverage_status || '';
  const exportAll = useCallback(async () => {
    const rows = await fetchAllIpamExportItems<DiscoveredEndpointRow>('/api/ipam/endpoints', buildDiscoveredEndpointQuery(filters));
    return {
      headers: ['IP', 'MAC', zh ? '主机名 / 类型' : 'Hostname / Type', zh ? 'IPAM 登记' : 'IPAM registration', zh ? '站点 / VRF' : 'Site / VRF', 'VLAN', zh ? '接入设备 / 端口' : 'Access device / port', zh ? '观察时间' : 'Observed at', zh ? '证据状态' : 'Evidence status'],
      rows: rows.map(item => [item.ip || '—', item.mac || '—', `${getDiscoveryHostname(item, zh)} / ${getDiscoveryTypeLabel(zh)}`, `${getDiscoveryRegistrationLabel(item.registration_status, zh)} ${item.subnet_prefix || ''}`.trim(), `${item.site_name || '—'} / ${item.vrf_name || '—'}`, item.vlan || '—', `${item.switch_name || item.source_device_name || '—'} / ${getDiscoveryPortLabel(item, zh)}`, item.observed_at || '—', getDiscoveryEvidenceLabel(item.evidence_status, zh)]),
    };
  }, [filters, zh]);


  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden px-5 py-4 sm:px-6">
      <PageHero
        compact
        icon={Globe}
        title={zh ? '发现终端' : 'Discovered Endpoints'}
        subtitle={zh ? '查看网络发现的 IP、MAC 和接入位置。' : 'Review discovered IPs, MAC addresses, and access locations.'}
      />

      {summary && (
        <section aria-label={zh ? '发现摘要' : 'Discovery summary'} className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {([
            ['discovered_ip_count', zh ? 'IP发现记录' : 'IP discovery records'],
            ['mac_only_count', zh ? '仅 MAC 记录' : 'MAC-only'],
            ['registered_count', zh ? '已登记' : 'Registered'],
            ['unregistered_count', zh ? '未登记' : 'Unregistered'],
            ['scope_pending_count', zh ? '归属待确认' : 'Scope pending'],
            ['conflict_count', zh ? '冲突记录' : 'Conflicts'],
          ] as const).map(([key, label]) => (
            <div key={key} className="rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2">
              <div className="text-[10px] font-semibold text-[var(--muted-text)]">{label}</div>
              <div className="mt-0.5 text-lg font-bold tabular-nums text-[var(--ui-fg)]">{readCount(summary, key)}</div>
            </div>
          ))}
        </section>
      )}

      {summary && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2 text-[11px] text-[var(--muted-text)]">
          <span className="inline-flex items-center gap-1.5"><Info size={13} />{zh ? '覆盖状态' : 'Coverage'}: <strong className="text-[var(--ui-fg)]">{getDiscoveryCoverageLabel(coverageStatus, zh)}</strong></span>
          <span className="inline-flex items-center gap-1.5"><Clock3 size={13} />{zh ? '源采集最近成功' : 'Latest source success'}: {formatObserved(summary.source_last_success_at)}</span>
        </div>
      )}

      <div className="flex flex-shrink-0 flex-wrap items-end gap-2 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-3">
        <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-[10px] font-semibold text-[var(--muted-text)]">
          {zh ? '站点' : 'Site'}
          <select aria-label={zh ? '站点筛选' : 'Filter by site'} value={filters.siteId} onChange={(event) => setFilters((current) => ({ ...current, siteId: event.target.value, vrfId: '', deviceId: '', page: 1 }))} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs text-[var(--ui-fg)]">
            <option value="">{zh ? '全部站点' : 'All sites'}</option>
            {sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
          </select>
        </label>
        <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-[10px] font-semibold text-[var(--muted-text)]">
          VRF
          <select aria-label={zh ? 'VRF筛选' : 'Filter by VRF'} value={filters.vrfId} onChange={(event) => updateFilter('vrfId', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs text-[var(--ui-fg)]">
            <option value="">{zh ? '全部 VRF' : 'All VRFs'}</option>
            {vrfs.map((vrf) => <option key={vrf.id} value={vrf.id}>{vrf.name}</option>)}
          </select>
        </label>
        <label className="flex min-w-[160px] flex-1 flex-col gap-1 text-[10px] font-semibold text-[var(--muted-text)]">
          {zh ? '来源设备' : 'Source device'}
          <select aria-label={zh ? '来源设备筛选' : 'Filter by source device'} value={filters.deviceId} onChange={(event) => updateFilter('deviceId', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs text-[var(--ui-fg)]">
            <option value="">{zh ? '全部设备' : 'All devices'}</option>
            {devices.map((device) => <option key={device.id} value={device.id}>{device.label}</option>)}
          </select>
        </label>
        <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-[10px] font-semibold text-[var(--muted-text)]">
          {zh ? '记录类型' : 'Record type'}
          <select aria-label={zh ? '记录类型筛选' : 'Filter by record type'} value={filters.kind} onChange={(event) => updateFilter('kind', event.target.value as DiscoveredEndpointFilters['kind'])} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs text-[var(--ui-fg)]">
            <option value="ip">{zh ? 'IP 观察（默认）' : 'IP observations (default)'}</option>
            <option value="mac">{zh ? '仅 MAC 记录' : 'MAC-only records'}</option>
            <option value="all">{zh ? '全部记录' : 'All records'}</option>
          </select>
        </label>
        <label className="flex min-w-[135px] flex-1 flex-col gap-1 text-[10px] font-semibold text-[var(--muted-text)]">
          {zh ? '证据状态' : 'Evidence status'}
          <select aria-label={zh ? '证据状态筛选' : 'Filter by evidence status'} value={filters.evidenceStatus} onChange={(event) => updateFilter('evidenceStatus', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs text-[var(--ui-fg)]">
            <option value="">{zh ? '全部状态' : 'All statuses'}</option>
            <option value="recent">{zh ? '近期观察' : 'Recent'}</option>
            <option value="historical">{zh ? '历史观察' : 'Historical'}</option>
            <option value="scope_pending">{zh ? '归属待确认' : 'Scope pending'}</option>
            <option value="conflict">{zh ? 'IP/MAC 冲突' : 'IP/MAC conflict'}</option>
          </select>
        </label>
        <label className="flex min-w-[135px] flex-1 flex-col gap-1 text-[10px] font-semibold text-[var(--muted-text)]">
          {zh ? 'IPAM 登记状态' : 'IPAM registration'}
          <select aria-label={zh ? '登记状态筛选' : 'Filter by registration'} value={filters.registrationStatus} onChange={(event) => updateFilter('registrationStatus', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-xs text-[var(--ui-fg)]">
            <option value="">{zh ? '全部登记状态' : 'All registration states'}</option>
            <option value="registered">{zh ? '已登记' : 'Registered'}</option>
            <option value="unregistered">{zh ? '未登记' : 'Unregistered'}</option>
            <option value="scope_pending">{zh ? '归属待确认' : 'Scope pending'}</option>
          </select>
        </label>
        <form onSubmit={(event) => { event.preventDefault(); applySearch(); }} className="flex min-w-[240px] flex-[2] gap-1.5">
          <label className="relative min-w-0 flex-1">
            <span className="sr-only">{zh ? '搜索 IP、MAC 或设备' : 'Search IP, MAC, or device'}</span>
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" />
            <input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder={zh ? '搜索 IP、MAC、设备...' : 'Search IP, MAC, device...'} className="h-9 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] pl-9 pr-3 text-xs text-[var(--ui-fg)]" />
          </label>
          <button type="submit" className="h-9 rounded-lg bg-[var(--ui-accent)] px-3 text-xs font-semibold text-white">{zh ? '搜索' : 'Search'}</button>
          <button type="button" onClick={() => { setSearchDraft(''); setFilters(initialFilters); }} className="h-9 rounded-lg border border-[var(--ui-border)] px-2.5 text-xs text-[var(--ui-fg-muted)]">{zh ? '重置' : 'Reset'}</button>
        </form>
      </div>

      {loadError && <div role="alert" className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-800"><AlertTriangle size={15} /> <span className="flex-1">{loadError}</span><button type="button" onClick={() => void loadList()} className="font-bold underline">{zh ? '重试' : 'Retry'}</button></div>}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] shadow-sm">
        <div className="flex items-center justify-between border-b border-[var(--ui-border)] px-4 py-2.5 text-xs">
          <strong className="text-[var(--ui-fg)]">{zh ? '发现记录' : 'Discovered records'} <span className="ml-1 tabular-nums text-[var(--ui-fg-muted)]">{total.toLocaleString()}</span></strong>
          <span className="inline-flex items-center gap-1 text-[10px] text-[var(--ui-fg-muted)]"><Info size={12} />{zh ? '观察记录不代表终端在线状态' : 'Observations do not indicate that a host is online'}</span>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {loading ? (
            <div className="flex h-full min-h-40 items-center justify-center gap-2 text-xs text-[var(--muted-text)]"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载已有发现记录…' : 'Loading existing discovery records…'}</div>
          ) : loadError ? (
            <div className="flex h-full min-h-40 items-center justify-center text-xs text-[var(--muted-text)]">{zh ? '无法显示列表，请修复错误后重试。' : 'The list is unavailable. Retry after resolving the error.'}</div>
          ) : (
            <DataTable className="min-w-[1160px] text-left" exportConfig={{ filename: 'ipam-discovered-endpoints', exportData: exportAll, language: zh ? 'zh' : 'en', disabled: loading || visibleRows.length === 0 }}>
              <thead><tr>
                <th>{zh ? 'IP' : 'IP'}</th>
                <th>MAC</th>
                <th>{zh ? '主机名 / 类型' : 'Hostname / Type'}</th>
                <th>{zh ? 'IPAM 登记' : 'IPAM registration'}</th>
                <th>{zh ? '站点 / VRF' : 'Site / VRF'}</th>
                <th>VLAN</th>
                <th>{zh ? '接入设备 / 端口' : 'Access device / port'}</th>
                <th>{zh ? '观察时间' : 'Observed at'}</th>
                <th>{zh ? '证据状态' : 'Evidence status'}</th>
                <TableActionHeader>{zh ? '操作' : 'Actions'}</TableActionHeader>
              </tr></thead>
              <tbody>
                {visibleRows.length ? visibleRows.map((item) => (
                  <tr key={item.id}>
                    <td className="font-mono font-semibold">{item.ip || '—'}</td>
                    <td className="font-mono">{item.mac || '—'}</td>
                    <td><div>{getDiscoveryHostname(item, zh)}</div><div className="text-[10px] text-[var(--ui-fg-muted)]">{getDiscoveryTypeLabel(zh)}</div></td>
                    <td><div>{getDiscoveryRegistrationLabel(item.registration_status, zh)}</div>{item.subnet_prefix && <div className="font-mono text-[10px] text-[var(--ui-fg-muted)]">{item.subnet_prefix}</div>}</td>
                    <td><div>{item.site_name || (zh ? '未知站点' : 'Unknown site')}</div><div className="text-[10px] text-[var(--ui-fg-muted)]">{item.vrf_name || (zh ? 'VRF 未知' : 'VRF unknown')}</div></td>
                    <td>{item.vlan || '—'}</td>
                    <td><div>{item.switch_name || item.source_device_name || (zh ? '未知设备' : 'Unknown device')}</div><div className="text-[10px] text-[var(--ui-fg-muted)]">{getDiscoveryPortLabel(item, zh)}</div></td>
                    <td><div>{formatObserved(item.observed_at)}</div>{item.mac_observed_at && <div className="text-[10px] text-[var(--ui-fg-muted)]">{zh ? 'MAC' : 'MAC'}: {item.mac_observed_at}</div>}</td>
                    <td>{getDiscoveryEvidenceLabel(item.evidence_status, zh)}</td>
                    <TableActionCell><ActionIconButton icon={Eye} label={zh ? '查看来源证据' : 'View source evidence'} onClick={() => setSelected(item)} /></TableActionCell>
                  </tr>
                )) : (
                  <tr><td colSpan={10} className="py-12 text-center text-xs text-[var(--ui-fg-muted)]">{zh ? '当前筛选没有发现记录。清除筛选或更换条件后重试。' : 'No discovery records match the current filters. Clear or change the filters.'}</td></tr>
                )}
              </tbody>
            </DataTable>
          )}
        </div>
        <Pagination currentPage={filters.page} totalItems={total} itemsPerPage={filters.pageSize} onPageChange={(page) => setFilters((current) => ({ ...current, page }))} onItemsPerPageChange={(pageSize) => setFilters((current) => ({ ...current, page: 1, pageSize }))} language={language} alwaysVisible />
      </div>

      {selected && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="endpoint-detail-title" className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
            <header className="flex items-start justify-between gap-3 border-b border-[var(--ui-border)] px-5 py-4">
              <div><h2 id="endpoint-detail-title" className="text-base font-bold text-[var(--ui-fg)]">{zh ? '发现来源证据' : 'Discovery source evidence'}</h2><p className="mt-1 font-mono text-xs text-[var(--ui-fg-muted)]">{selected.ip || '—'} · {selected.mac || '—'}</p></div>
              <button type="button" aria-label={zh ? '关闭详情' : 'Close detail'} onClick={() => setSelected(null)} className="rounded-lg p-2 text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]"><X size={16} /></button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {detailLoading && <div className="flex items-center gap-2 py-6 text-xs text-[var(--ui-fg-muted)]"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载证据…' : 'Loading evidence…'}</div>}
              {detailError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">{detailError}</div>}
              {detail && (
                <>
                  <dl className="grid grid-cols-1 gap-3 rounded-xl border border-[var(--ui-border)] p-3 text-xs sm:grid-cols-2">
                    <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '站点 / VRF' : 'Site / VRF'}</dt><dd className="mt-1 font-semibold">{detail.site_name || (zh ? '未知站点' : 'Unknown site')} / {detail.vrf_name || (zh ? '待确认' : 'Pending')}</dd></div>
                    <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '来源设备 / 端口' : 'Source device / port'}</dt><dd className="mt-1 font-semibold">{detail.source_device_name || detail.switch_name || (zh ? '未知设备' : 'Unknown device')} / {getDiscoveryPortLabel(detail, zh)}</dd></div>
                    <div><dt className="text-[var(--ui-fg-muted)]">{zh ? 'IP 观察时间' : 'IP observed at'}</dt><dd className="mt-1 font-mono">{formatObserved(detail.observed_at)}</dd></div>
                    <div><dt className="text-[var(--ui-fg-muted)]">{zh ? 'MAC 观察时间' : 'MAC observed at'}</dt><dd className="mt-1 font-mono">{formatObserved(detail.mac_observed_at)}</dd></div>
                    <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '投影时间' : 'Projected at'}</dt><dd className="mt-1 font-mono">{formatObserved(detail.projected_at)}</dd></div>
                    <div><dt className="text-[var(--ui-fg-muted)]">{zh ? '登记网段' : 'Registered prefix'}</dt><dd className="mt-1 font-mono">{detail.subnet_prefix || '—'}</dd></div>
                  </dl>
                  <h3 className="mb-2 mt-5 text-xs font-bold text-[var(--ui-fg)]">{zh ? `来源记录（${detail.observations?.length || 0}）` : `Source observations (${detail.observations?.length || 0})`}</h3>
                  {detail.observations?.length ? <div className="space-y-2">{detail.observations.map((observation, index) => (
                    <article key={`${observation.source_type || 'source'}-${observation.source_device_id || index}-${observation.observed_at || index}`} className="rounded-xl border border-[var(--ui-border)] p-3 text-xs">
                      <div className="flex flex-wrap items-center justify-between gap-2 font-semibold"><span>{observation.source_type?.toUpperCase() || (zh ? '来源未知' : 'Unknown source')} · {observation.source_device_name || observation.source_device_id || (zh ? '未知设备' : 'Unknown device')}</span><span className="font-mono text-[var(--ui-fg-muted)]">{formatObserved(observation.observed_at)}</span></div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-[var(--ui-fg-muted)] sm:grid-cols-4"><span>IP: {observation.ip || '—'}</span><span>MAC: {observation.mac || '—'}</span><span>{zh ? '接口' : 'Interface'}: {observation.interface_name || '—'}</span><span>VLAN: {observation.vlan || '—'}</span></div>
                      <div className="mt-1 text-[10px] text-[var(--ui-fg-muted)]">{zh ? '投影时间' : 'Projected'}: {formatObserved(observation.projected_at)} · {zh ? '源版本' : 'Source version'}: {observation.source_version || '—'} · {zh ? '时间校验' : 'Timestamp'}: {observation.timestamp_status || '—'} · {zh ? '覆盖' : 'Coverage'}: {observation.coverage_status || '—'}</div>
                    </article>
                  ))}</div> : <p className="rounded-xl border border-dashed border-[var(--ui-border)] p-4 text-xs text-[var(--ui-fg-muted)]">{zh ? '没有可显示的来源明细。' : 'No source detail is available.'}</p>}
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
};

export default DiscoveredEndpointsTab;
