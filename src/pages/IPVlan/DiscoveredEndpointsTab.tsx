import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ChevronDown, Eye, Info, RefreshCw, Search, Terminal, X } from 'lucide-react';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { DataTable, DataTableFrame } from '../../components/DataTable';
import { ActionIconButton } from '../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { fetchAllIpamExportItems } from './ipamExport';
import {
  buildDiscoveredEndpointQuery,
  getDiscoveryEvidenceLabel,
  getDiscoveryRegistrationLabel,
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
    vrf_context_inferred: row.vrf_context_inferred === true,
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

const formatObserved = (value: string | null | undefined, includeSeconds = true): string => {
  if (!value) return '—';
  const text = value.trim();
  let normalized = text;
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    normalized = `${text}T00:00:00+08:00`;
  } else if (!text.includes('T')) {
    normalized = text.replace(' ', 'T');
  }
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const date = new Date(hasTimezone ? normalized : `${normalized}+08:00`);
  if (Number.isNaN(date.getTime())) return value;

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    ...(includeSeconds ? { second: '2-digit' } : {}),
    hourCycle: 'h23',
  }).formatToParts(date);
  const part = (type: string) => parts.find((item) => item.type === type)?.value || '';
  const dateText = `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`;
  return includeSeconds ? `${dateText}:${part('second')}` : dateText;
};

const formatObservedCompact = (value: string | null | undefined): string => formatObserved(value, false);

const DiscoveredEndpointsTab: React.FC<DiscoveredEndpointsTabProps> = ({ language }) => {
  const zh = language === 'zh';
  const listRequestRef = useRef<AbortController | null>(null);
  const detailRequestRef = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);
  const listInFlight = useRef(false);
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

  const loadList = useCallback(async (silent = false) => {
    listRequestRef.current?.abort();
    const controller = new AbortController();
    listRequestRef.current = controller;
    const currentRequest = ++requestSequence.current;
    listInFlight.current = true;
    if (!silent) setLoading(true);
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
      if (currentRequest === requestSequence.current) listInFlight.current = false;
      if (!silent && !controller.signal.aborted && currentRequest === requestSequence.current) setLoading(false);
    }
  }, [authHeaders, filters, zh]);

  useEffect(() => {
    void loadList();
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible' && !listInFlight.current) void loadList(true);
    }, 60000);
    return () => {
      window.clearInterval(timer);
      listRequestRef.current?.abort();
    };
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
          setDetail({
            ...normalized,
            vrf_name: selected.vrf_context_inferred ? selected.vrf_name : normalized.vrf_name,
            vrf_context_inferred: selected.vrf_context_inferred,
            observations,
            evidence: root.evidence,
          });
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
  const advancedFilterCount = [filters.vrfId, filters.evidenceStatus, filters.registrationStatus].filter(Boolean).length;
  const exportAll = useCallback(async () => {
    const rows = await fetchAllIpamExportItems<DiscoveredEndpointRow>('/api/ipam/endpoints', buildDiscoveredEndpointQuery(filters));
    return {
      headers: ['IP', 'MAC', zh ? '主机名' : 'Hostname', zh ? 'IPAM 登记' : 'IPAM registration', zh ? '站点' : 'Site', 'VRF', 'VLAN', zh ? '接入设备' : 'Access device', zh ? '接入端口' : 'Access port', zh ? '观察时间' : 'Observed at', zh ? '证据状态' : 'Evidence status'],
      rows: rows.map(item => [item.ip || '', item.mac || '', item.hostname?.trim() || '', item.registration_status ? `${getDiscoveryRegistrationLabel(item.registration_status, zh)} ${item.subnet_prefix || ''}`.trim() : item.subnet_prefix || '', item.site_name || '', item.vrf_context_inferred ? '' : item.vrf_name || '', item.vlan || '', item.switch_name || '', item.switch_port || '', item.observed_at || '', item.evidence_status ? getDiscoveryEvidenceLabel(item.evidence_status, zh) : '']),
    };
  }, [filters, zh]);


  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden px-5 py-4 font-sans text-[var(--ui-text-body)] sm:px-6">
      <PageHero
        compact
        icon={Terminal}
        title={zh ? '发现终端' : 'Discovered Endpoints'}
        subtitle={zh ? '查看网络发现的 IP、MAC 和接入位置。' : 'Review discovered IPs, MAC addresses, and access locations.'}
      />

      {summary && (
        <section aria-label={zh ? '发现摘要' : 'Discovery summary'} className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-4">
          {([
            ['discovered_ip_count', zh ? 'IP发现记录' : 'IP discovery records'],
            ['registered_count', zh ? '已登记' : 'Registered'],
            ['unregistered_count', zh ? '未登记' : 'Unregistered'],
            ['conflict_count', zh ? '冲突记录' : 'Conflicts'],
          ] as const).map(([key, label]) => (
            <div key={key} className="flex h-full min-h-16 flex-col justify-between rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2">
              <div className="text-[var(--ui-text-caption)] font-semibold text-[var(--muted-text)]">{label}</div>
              <div className="text-[var(--ui-text-body)] font-bold tabular-nums text-[var(--ui-fg)]">{readCount(summary, key)}</div>
            </div>
          ))}
        </section>
      )}

      <div className="flex flex-shrink-0 flex-col gap-2 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-3">
        <div className="grid grid-cols-1 items-end gap-2 md:grid-cols-2 xl:grid-cols-[minmax(145px,1fr)_minmax(160px,1.1fr)_minmax(145px,1fr)_minmax(320px,2.2fr)]">
        <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
          {zh ? '站点' : 'Site'}
          <select aria-label={zh ? '站点筛选' : 'Filter by site'} value={filters.siteId} onChange={(event) => setFilters((current) => ({ ...current, siteId: event.target.value, vrfId: '', deviceId: '', page: 1 }))} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
            <option value="">{zh ? '全部站点' : 'All sites'}</option>
            {sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
          {zh ? '来源设备' : 'Source device'}
          <select aria-label={zh ? '来源设备筛选' : 'Filter by source device'} value={filters.deviceId} onChange={(event) => updateFilter('deviceId', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
            <option value="">{zh ? '全部设备' : 'All devices'}</option>
            {devices.map((device) => <option key={device.id} value={device.id}>{device.label}</option>)}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
          {zh ? '记录类型' : 'Record type'}
          <select aria-label={zh ? '记录类型筛选' : 'Filter by record type'} value={filters.kind} onChange={(event) => updateFilter('kind', event.target.value as DiscoveredEndpointFilters['kind'])} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
            <option value="ip">{zh ? 'IP 观察（默认）' : 'IP observations (default)'}</option>
            <option value="mac">{zh ? '仅 MAC 记录' : 'MAC-only records'}</option>
            <option value="all">{zh ? '全部记录' : 'All records'}</option>
          </select>
        </label>
        <form onSubmit={(event) => { event.preventDefault(); applySearch(); }} className="flex min-w-0 items-end gap-1.5 xl:self-end">
          <label className="relative min-w-0 flex-1">
            <span className="sr-only">{zh ? '搜索 IP、MAC 或设备' : 'Search IP, MAC, or device'}</span>
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" />
            <input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder={zh ? '搜索 IP、MAC、设备...' : 'Search IP, MAC, device...'} className="h-9 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] pl-9 pr-3 text-[var(--ui-text-body)] text-[var(--ui-fg)]" />
          </label>
          <button type="submit" className="h-9 shrink-0 rounded-lg bg-[var(--ui-accent)] px-3 text-[var(--ui-text-body)] font-semibold text-white">{zh ? '搜索' : 'Search'}</button>
          <button type="button" onClick={() => void loadList()} disabled={loading} className="h-9 shrink-0 rounded-lg border border-[var(--ui-border)] px-2.5 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)] disabled:opacity-50">{zh ? '刷新' : 'Refresh'}</button>
          <button type="button" onClick={() => { setSearchDraft(''); setFilters(initialFilters); }} className="h-9 shrink-0 rounded-lg border border-[var(--ui-border)] px-2.5 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]">{zh ? '重置' : 'Reset'}</button>
        </form>
        </div>
        <details className="group border-t border-[var(--ui-border)] pt-2">
          <summary className="flex w-fit cursor-pointer list-none items-center gap-2 text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ui-accent)]">
            {zh ? '更多筛选' : 'More filters'}
            {advancedFilterCount > 0 && <span className="rounded-full bg-[var(--ui-accent)]/10 px-1.5 py-0.5 text-[var(--ui-text-caption)] text-[var(--ui-accent)]">{advancedFilterCount}</span>}
            <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              VRF
              <select aria-label={zh ? 'VRF筛选' : 'Filter by VRF'} value={filters.vrfId} onChange={(event) => updateFilter('vrfId', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
                <option value="">{zh ? '全部 VRF' : 'All VRFs'}</option>
                {vrfs.map((vrf) => <option key={vrf.id} value={vrf.id}>{vrf.name}</option>)}
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              {zh ? '证据状态' : 'Evidence status'}
              <select aria-label={zh ? '证据状态筛选' : 'Filter by evidence status'} value={filters.evidenceStatus} onChange={(event) => updateFilter('evidenceStatus', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
                <option value="">{zh ? '全部状态' : 'All statuses'}</option>
                <option value="recent">{zh ? '近期观察' : 'Recent'}</option>
                <option value="historical">{zh ? '历史观察' : 'Historical'}</option>
                <option value="scope_pending">{zh ? '归属待确认' : 'Scope pending'}</option>
                <option value="conflict">{zh ? 'IP/MAC 冲突' : 'IP/MAC conflict'}</option>
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              {zh ? 'IPAM 登记状态' : 'IPAM registration'}
              <select aria-label={zh ? '登记状态筛选' : 'Filter by registration'} value={filters.registrationStatus} onChange={(event) => updateFilter('registrationStatus', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
                <option value="">{zh ? '全部登记状态' : 'All registration states'}</option>
                <option value="registered">{zh ? '已登记' : 'Registered'}</option>
                <option value="unregistered">{zh ? '未登记' : 'Unregistered'}</option>
                <option value="scope_pending">{zh ? '归属待确认' : 'Scope pending'}</option>
              </select>
            </label>
          </div>
        </details>
      </div>

      {loadError && <div role="alert" className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-[var(--ui-text-body)] text-rose-800"><AlertTriangle size={15} /> <span className="flex-1">{loadError}</span><button type="button" onClick={() => void loadList()} className="font-bold underline">{zh ? '重试' : 'Retry'}</button></div>}

      <DataTableFrame className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-[var(--ui-border)] px-4 py-2.5 text-[var(--ui-text-body)]">
          <strong className="text-[var(--ui-fg)]">{zh ? '发现记录' : 'Discovered records'} <span className="ml-1 tabular-nums text-[var(--ui-fg-muted)]">{total.toLocaleString()}</span></strong>
          <span className="inline-flex items-center gap-1 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]"><Info size={12} />{zh ? '观察记录不代表终端在线状态' : 'Observations do not indicate that a host is online'}</span>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {loading ? (
            <div className="flex h-full min-h-40 items-center justify-center gap-2 text-[var(--ui-text-body)] text-[var(--muted-text)]"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载已有发现记录…' : 'Loading existing discovery records…'}</div>
          ) : loadError ? (
            <div className="flex h-full min-h-40 items-center justify-center text-[var(--ui-text-body)] text-[var(--muted-text)]">{zh ? '无法显示列表，请修复错误后重试。' : 'The list is unavailable. Retry after resolving the error.'}</div>
          ) : (
            <DataTable className="min-w-[1280px] text-[var(--ui-text-body)] text-left" exportConfig={{ filename: 'ipam-discovered-endpoints', exportData: exportAll, language: zh ? 'zh' : 'en', disabled: loading || visibleRows.length === 0 }}>
              <thead><tr>
                <th>IP</th>
                <th>MAC</th>
                <th>{zh ? '主机名' : 'Hostname'}</th>
                <th>{zh ? 'IPAM 登记' : 'IPAM registration'}</th>
                <th>{zh ? '站点' : 'Site'}</th>
                <th>VRF</th>
                <th>VLAN</th>
                <th>{zh ? '接入设备' : 'Access device'}</th>
                <th>{zh ? '接入端口' : 'Access port'}</th>
                <th>{zh ? '上一次时间' : 'Last seen'}</th>
                <TableActionHeader>{zh ? '操作' : 'Actions'}</TableActionHeader>
              </tr></thead>
              <tbody>
                {visibleRows.length ? visibleRows.map((item) => (
                  <tr key={item.id}>
                    <td className="font-mono font-semibold">{item.ip || ''}</td>
                    <td className="font-mono">{item.mac || ''}</td>
                    <td>{item.hostname?.trim() || ''}</td>
                    <td>{item.registration_status && <div>{getDiscoveryRegistrationLabel(item.registration_status, zh)}</div>}{item.subnet_prefix && <div className="font-mono text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{item.subnet_prefix}</div>}</td>
                    <td>{item.site_name || ''}</td>
                    <td>{item.vrf_context_inferred ? '' : item.vrf_name || ''}</td>
                    <td>{item.vlan || ''}</td>
                    <td>{item.switch_name || ''}</td>
                    <td>{item.switch_port || ''}</td>
                    <td title={item.observed_at ? formatObserved(item.observed_at) : undefined} className="tabular-nums">{item.observed_at ? formatObservedCompact(item.observed_at) : ''}</td>
                    <TableActionCell><ActionIconButton icon={Eye} label={zh ? '查看详情' : 'View details'} onClick={() => setSelected(item)} /></TableActionCell>
                  </tr>
                )) : (
                  <tr><td colSpan={11} className="py-12 text-center text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]">{zh ? '当前筛选没有发现记录。清除筛选或更换条件后重试。' : 'No discovery records match the current filters. Clear or change the filters.'}</td></tr>
                )}
              </tbody>
            </DataTable>
          )}
        </div>
        <Pagination currentPage={filters.page} totalItems={total} itemsPerPage={filters.pageSize} onPageChange={(page) => setFilters((current) => ({ ...current, page }))} onItemsPerPageChange={(pageSize) => setFilters((current) => ({ ...current, page: 1, pageSize }))} language={language} alwaysVisible />
      </DataTableFrame>

      {selected && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="endpoint-detail-title" className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
            <header className="flex items-start justify-between gap-3 border-b border-[var(--ui-border)] px-5 py-4">
              <div><h2 id="endpoint-detail-title" className="text-base font-bold text-[var(--ui-fg)]">{zh ? '终端详情' : 'Endpoint details'}</h2></div>
              <button type="button" aria-label={zh ? '关闭详情' : 'Close detail'} onClick={() => setSelected(null)} className="rounded-lg p-2 text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]"><X size={16} /></button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {detailLoading && <div className="flex items-center gap-2 py-6 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载证据…' : 'Loading evidence…'}</div>}
              {detailError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-[var(--ui-text-body)] text-rose-800">{detailError}</div>}
              {detail && (
                <>
                  <dl className="grid grid-cols-1 gap-4 text-[var(--ui-text-body)] sm:grid-cols-2">
                    {[
                      ['IP', detail.ip || ''],
                      ['MAC', detail.mac || ''],
                      ['VLAN', detail.vlan || ''],
                      [zh ? '站点' : 'Site', detail.site_name || ''],
                      [zh ? '来源设备' : 'Source device', detail.source_device_name || ''],
                      [zh ? '接入设备' : 'Access device', detail.switch_name || ''],
                      [zh ? '接入端口' : 'Access port', detail.switch_port || ''],
                      [zh ? '上一次时间' : 'Last seen', detail.observed_at ? formatObserved(detail.observed_at) : ''],
                    ].map(([label, value]) => (
                      <div key={label}><dt className="text-[var(--ui-text-label)] text-[var(--ui-fg-muted)]">{label}</dt><dd className="mt-1 break-words font-medium">{value}</dd></div>
                    ))}
                  </dl>
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
