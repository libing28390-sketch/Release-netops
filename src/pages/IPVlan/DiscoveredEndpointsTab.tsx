import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ChevronDown, Eye, Info, Plus, RefreshCw, Search, Terminal, X } from 'lucide-react';
import EndpointRegistrationDialog from './EndpointRegistrationDialog';
import { Link } from 'react-router-dom';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { DataTable, DataTableFrame } from '../../components/DataTable';
import { ActionIconButton } from '../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { fetchAllIpamExportItems } from './ipamExport';
import {
  buildDiscoveredEndpointQuery,
  canRegisterEndpoint,
  getEndpointClassLabel,
  getEndpointClassReason,
  getDiscoveryCollectionStatusLabel,
  getDiscoveryEvidenceLabel,
  getDiscoveryObservationSourceLabel,
  getDiscoveryPathLabel,
  getDiscoveryRegistrationLabel,
  normalizeDiscoveryOptions,
  type DiscoveredEndpointFilters,
  type DiscoveredEndpointRow,
  type DiscoveryFilterOption,
} from './ipamDiscoveryPresentation';

interface DiscoverySummary {
  discovered_ip_count?: number;
  distinct_ip_count?: number;
  infrastructure_ip_count?: number;
  access_host_ip_count?: number;
  candidate_ip_count?: number;
  mac_only_count?: number;
  registered_count?: number;
  unregistered_count?: number;
  scope_pending_count?: number;
  conflict_count?: number;
  path_ambiguity_count?: number;
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
  networkScope: 'all',
  endpointClass: 'terminal',
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
  const nonNegativeInteger = (key: string): number | undefined =>
    typeof row[key] === 'number' && Number.isInteger(row[key]) && (row[key] as number) >= 0
      ? row[key] as number
      : undefined;
  return {
    id: row.id,
    ip: nullableText('ip'),
    mac: nullableText('mac'),
    tenant_id: nullableText('tenant_id'),
    site_id: nullableText('site_id'),
    site_name: nullableText('site_name'),
    vrf_id: nullableText('vrf_id'),
    address_space_id: nullableText('address_space_id'),
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
    collection_status: nullableText('collection_status') || undefined,
    generation: nonNegativeInteger('generation'),
    latest_attempt_generation: nonNegativeInteger('latest_attempt_generation'),
    last_success_generation: nonNegativeInteger('last_success_generation'),
    last_success_at: nullableText('last_success_at'),
    hostname: nullableText('hostname'),
    source_type: nullableText('source_type') || undefined,
    observation_source: nullableText('observation_source') || undefined,
    path_ambiguity: row.path_ambiguity === true,
    path_ambiguity_reason: nullableText('path_ambiguity_reason') || undefined,
    path_classification: nullableText('path_classification') || undefined,
    path_evidence: nullableText('path_evidence') || undefined,
    aggregation_name: nullableText('aggregation_name') || undefined,
    aggregation_protocol: nullableText('aggregation_protocol') || undefined,
    topology_link_kind: nullableText('topology_link_kind') || undefined,
    virtual_gateway_mac: row.virtual_gateway_mac === true,
    endpoint_class: nullableText('endpoint_class') || undefined,
    endpoint_class_reason: nullableText('endpoint_class_reason') || undefined,
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
  const [registerItem, setRegisterItem] = useState<DiscoveredEndpointRow | null>(null);
  const [registrationNotice, setRegistrationNotice] = useState('');
  useEffect(() => {
    if (!registrationNotice) return;
    const timer = window.setTimeout(() => setRegistrationNotice(''), 8000);
    return () => window.clearTimeout(timer);
  }, [registrationNotice]);
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

  const updateScopeStatusFilter = (key: 'evidenceStatus' | 'registrationStatus', value: string) => {
    setFilters((current) => ({
      ...current,
      [key]: value,
      networkScope: value === 'scope_pending' && current.kind !== 'mac' ? 'all' : current.networkScope,
      page: 1,
    }));
  };

  const applySearch = () => updateFilter('query', searchDraft);
  const visibleRows = useMemo(() => items, [items]);
  const advancedFilterCount = [filters.vrfId, filters.evidenceStatus, filters.registrationStatus, !['all', 'terminal'].includes(filters.endpointClass) ? filters.endpointClass : ''].filter(Boolean).length;
  const exportAll = useCallback(async () => {
    const rows = await fetchAllIpamExportItems<DiscoveredEndpointRow>('/api/ipam/endpoints', buildDiscoveredEndpointQuery(filters));
    return {
      headers: ['IP', 'MAC', zh ? '判定' : 'Classification', zh ? '判定依据' : 'Classification evidence', zh ? '来源' : 'Source', zh ? 'IPAM 主机名' : 'IPAM hostname', zh ? 'IPAM 登记' : 'IPAM registration', zh ? '站点' : 'Site', 'VRF', 'VLAN', zh ? '采集设备' : 'Collector device', zh ? '观察接口与路径' : 'Observed interface and path', zh ? '观察时间' : 'Observed at', zh ? '证据状态' : 'Evidence status'],
      rows: rows.map(item => [item.ip || '', item.mac || '', getEndpointClassLabel(item.endpoint_class, zh), getEndpointClassReason(item.endpoint_class_reason, zh), getDiscoveryObservationSourceLabel(item.observation_source, item.source_type, zh), item.hostname?.trim() || '', item.registration_status ? `${getDiscoveryRegistrationLabel(item.registration_status, zh)} ${item.scope_status === 'scope_pending' ? (zh ? '范围待确认' : 'Scope pending') : ''} ${item.subnet_prefix || ''}`.trim() : item.subnet_prefix || '', item.site_name || '', item.vrf_context_inferred ? '' : item.vrf_name || '', item.vlan || '', item.source_device_name || item.switch_name || '', [item.switch_port || '', getDiscoveryPathLabel(item, zh), item.path_ambiguity ? (zh ? '路径有歧义' : 'Path ambiguous') : ''].filter(Boolean).join(' · '), item.observed_at || '', item.evidence_status ? getDiscoveryEvidenceLabel(item.evidence_status, zh) : '']),
    };
  }, [filters, zh]);


  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden px-5 py-4 font-sans text-[var(--ui-text-body)] sm:px-6">
      <PageHero
        compact
        icon={Terminal}
        title={zh ? '发现终端' : 'Discovered Endpoints'}
        subtitle={zh ? '默认只显示主机候选和接入口主机；命中 CMDB 管理地址或当前接口 IP 的基础设施地址会从列表隐藏，摘要仍统计其数量，可在更多筛选中查看。IPAM 主机名是地址台账名称；采集设备显示实际读取 ARP / ND 的设备。' : 'By default, show host candidates and access hosts only. Infrastructure addresses matching CMDB management/interface IPs are hidden from the list, counted in the summary, and available in More filters. IPAM hostname is the ledger name; collector device is the device that read ARP / ND.'}
      />

      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--ui-fg-muted)]">
        <span>{zh ? '确认归属后，可在行内登记 IP；仅 MAC 记录不能登记为 IP。' : 'Register an IP from its row after confirming scope. MAC-only records cannot be registered as IPs.'}</span>
        <Link className="text-cyan-700 underline" to="/ipam/prefixes">{zh ? '维护网段 / 地址空间' : 'Manage prefixes / address spaces'}</Link>
        <Link className="text-cyan-700 underline" to="/ipam/ips">{zh ? '查看 IPAM 台账' : 'IPAM ledger'}</Link>
      </div>
      {registrationNotice && <div role="status" className="rounded-lg bg-emerald-50 p-3 text-xs text-emerald-800">{registrationNotice}<button type="button" className="ml-3 underline" onClick={() => setRegistrationNotice('')}>{zh ? '关闭' : 'Dismiss'}</button></div>}

      {summary && (
        <section aria-label={zh ? '发现摘要' : 'Discovery summary'} className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-4 xl:grid-cols-8">
          {([
            ['discovered_ip_count', zh ? 'ARP/ND 观察条数' : 'ARP/ND observations'],
            ['distinct_ip_count', zh ? '不同 IP（当前范围）' : 'Distinct IPs (current scope)'],
            ['access_host_ip_count', zh ? '接入口主机候选' : 'Access-port host candidates'],
            ['candidate_ip_count', zh ? '待核主机候选' : 'Host candidates pending review'],
            ['infrastructure_ip_count', zh ? '基础设施地址' : 'Infrastructure addresses'],
            ['mac_only_count', zh ? '仅 MAC 观察' : 'MAC-only observations'],
            ['scope_pending_count', zh ? '范围待确认' : 'Scope pending'],
            ['path_ambiguity_count', zh ? '路径待核' : 'Ambiguous paths'],
          ] as const).map(([key, label]) => (
            <div key={key} className="flex h-full min-h-16 flex-col justify-between rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2">
              <div className="text-[var(--ui-text-caption)] font-semibold text-[var(--muted-text)]">{label}</div>
              <div className="text-[var(--ui-text-body)] font-bold tabular-nums text-[var(--ui-fg)]">{readCount(summary, key)}</div>
            </div>
          ))}
        </section>
      )}

      <div className="flex flex-shrink-0 flex-col gap-2 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-3">
        <div className="grid grid-cols-1 items-end gap-2 md:grid-cols-2 xl:grid-cols-[minmax(125px,0.9fr)_minmax(145px,1fr)_minmax(150px,1fr)_minmax(205px,1.5fr)_minmax(320px,2.2fr)]">
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
            <option value="mac">{zh ? '仅 MAC 观察（不登记 IP）' : 'MAC-only observations (no IP registration)'}</option>
            <option value="all">{zh ? '全部记录' : 'All record types'}</option>
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
          {zh ? '观察范围' : 'Observation scope'}
          <select aria-label={zh ? '观察范围筛选' : 'Filter by observation scope'} value={filters.kind === 'mac' ? 'all' : filters.networkScope} disabled={filters.kind === 'mac'} onChange={(event) => updateFilter('networkScope', event.target.value as DiscoveredEndpointFilters['networkScope'])} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)] disabled:opacity-60">
            <option value="business_vlan">{zh ? '已映射业务网段' : 'Mapped business networks'}</option>
            <option value="all">{zh ? '全部当前 IP 观察（默认，含范围待确认）' : 'All current IP observations (default, including scope-pending)'}</option>
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
        {filters.kind !== 'mac' && filters.networkScope === 'business_vlan' && (
          <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">
            {zh
              ? '业务网段视图只显示可关联到活动业务 Prefix 的 IP；未知或待确认范围的当前记录，请切换到“全部当前 IP 观察”查看。结果仍受当前账号的站点和租户权限限制，系统不会自动归入 Global 或 VRF。'
              : 'Business-network view shows IPs linked to active business prefixes. Switch to “All current IP observations” to review unknown or pending scopes. Results remain limited by your site and tenant permissions; the system will not assign them to Global or a VRF.'}
          </p>
        )}
        <details className="group border-t border-[var(--ui-border)] pt-2">
          <summary className="flex w-fit cursor-pointer list-none items-center gap-2 text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ui-accent)]">
            {zh ? '更多筛选' : 'More filters'}
            {advancedFilterCount > 0 && <span className="rounded-full bg-[var(--ui-accent)]/10 px-1.5 py-0.5 text-[var(--ui-text-caption)] text-[var(--ui-accent)]">{advancedFilterCount}</span>}
            <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-4">
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              {zh ? '主机判定' : 'Host classification'}
              <select aria-label={zh ? '主机判定筛选' : 'Filter by host classification'} value={filters.endpointClass} onChange={(event) => updateFilter('endpointClass', event.target.value as DiscoveredEndpointFilters['endpointClass'])} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
                <option value="all">{zh ? '全部判定' : 'All classifications'}</option>
                <option value="terminal">{zh ? '终端候选（默认）' : 'Terminal candidates (default)'}</option>
                <option value="access_host">{zh ? '接入口主机候选' : 'Access-port host candidates'}</option>
                <option value="candidate">{zh ? '待核主机候选' : 'Host candidates pending review'}</option>
                <option value="infrastructure">{zh ? '基础设施地址' : 'Infrastructure addresses'}</option>
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              VRF
              <select aria-label={zh ? 'VRF筛选' : 'Filter by VRF'} value={filters.vrfId} onChange={(event) => updateFilter('vrfId', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
                <option value="">{zh ? '全部 VRF' : 'All VRFs'}</option>
                {vrfs.map((vrf) => <option key={vrf.id} value={vrf.id}>{vrf.name}</option>)}
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              {zh ? '证据状态' : 'Evidence status'}
              <select aria-label={zh ? '证据状态筛选' : 'Filter by evidence status'} value={filters.evidenceStatus} onChange={(event) => updateScopeStatusFilter('evidenceStatus', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
                <option value="">{zh ? '全部状态' : 'All statuses'}</option>
                <option value="recent">{zh ? '近期观察' : 'Recent'}</option>
                <option value="stale">{zh ? '当前成功代次较早' : 'Latest successful generation is old'}</option>
                <option value="scope_pending">{zh ? '归属待确认' : 'Scope pending'}</option>
                <option value="conflict">{zh ? 'IP/MAC 冲突' : 'IP/MAC conflict'}</option>
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-[var(--ui-text-label)] font-semibold text-[var(--muted-text)]">
              {zh ? 'IPAM 登记状态' : 'IPAM registration'}
              <select aria-label={zh ? '登记状态筛选' : 'Filter by registration'} value={filters.registrationStatus} onChange={(event) => updateScopeStatusFilter('registrationStatus', event.target.value)} className="h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
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
            <DataTable className="min-w-[1520px] text-[var(--ui-text-body)] text-left" exportConfig={{ filename: 'ipam-discovered-endpoints', exportData: exportAll, language: zh ? 'zh' : 'en', disabled: loading || visibleRows.length === 0 }}>
              <thead><tr>
                <th>IP</th>
                <th>MAC</th>
                <th>{zh ? '主机判定' : 'Host classification'}</th>
                <th>{zh ? '来源' : 'Source'}</th>
                <th>{zh ? 'IPAM 主机名' : 'IPAM hostname'}</th>
                <th>{zh ? 'IPAM 登记' : 'IPAM registration'}</th>
                <th>{zh ? '站点' : 'Site'}</th>
                <th>VRF</th>
                <th>VLAN</th>
                <th>{zh ? '采集设备' : 'Collector device'}</th>
                <th>{zh ? '观察接口与路径' : 'Observed interface and path'}</th>
                <th>{zh ? '上一次时间' : 'Last seen'}</th>
                <TableActionHeader>{zh ? '操作' : 'Actions'}</TableActionHeader>
              </tr></thead>
              <tbody>
                {visibleRows.length ? visibleRows.map((item) => (
                  <tr key={item.id}>
                    <td className="font-mono font-semibold">{item.ip || ''}</td>
                    <td className="font-mono">{item.mac || ''}</td>
                    <td><div className="font-semibold">{getEndpointClassLabel(item.endpoint_class, zh)}</div><div className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{getEndpointClassReason(item.endpoint_class_reason, zh)}</div></td>
                    <td>{getDiscoveryObservationSourceLabel(item.observation_source, item.source_type, zh)}</td>
                    <td>{item.hostname?.trim() || ''}</td>
                    <td>{item.registration_status && <div>{getDiscoveryRegistrationLabel(item.registration_status, zh)}</div>}{item.scope_status === 'scope_pending' && <div className="text-[var(--ui-text-caption)] text-amber-700">{zh ? '范围待确认' : 'Scope pending'}</div>}{item.subnet_prefix && <div className="font-mono text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{item.subnet_prefix}</div>}</td>
                    <td>{item.site_name || ''}</td>
                    <td>{item.vrf_context_inferred ? '' : item.vrf_name || ''}</td>
                    <td>{item.vlan || ''}</td>
                    <td>{item.source_device_name || item.switch_name || ''}</td>
                    <td>
                      <div>{item.switch_port || ''}{item.path_ambiguity && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800" title={item.path_ambiguity_reason}>{zh ? '路径歧义' : 'Path ambiguous'}</span>}</div>
                      {getDiscoveryPathLabel(item, zh) && <div className="text-[10px] text-[var(--ui-fg-muted)]" title={item.path_evidence || undefined}>{getDiscoveryPathLabel(item, zh)}</div>}
                    </td>
                    <td title={item.observed_at ? formatObserved(item.observed_at) : undefined} className="tabular-nums">{item.observed_at ? formatObservedCompact(item.observed_at) : ''}</td>
                    <TableActionCell>
                      <div className="flex justify-end gap-1">
                        <ActionIconButton icon={Eye} label={zh ? '查看详情' : 'View details'} onClick={() => setSelected(item)} />
                        {canRegisterEndpoint(item) && <ActionIconButton icon={Plus} label={zh ? '登记到 IPAM' : 'Register in IPAM'} onClick={() => setRegisterItem(item)} />}
                      </div>
                    </TableActionCell>
                  </tr>
                )) : (
                  <tr><td colSpan={13} className="py-12 text-center text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]">{zh ? '当前筛选没有发现记录。清除筛选或更换条件后重试。' : 'No discovery records match the current filters. Clear or change the filters.'}</td></tr>
                )}
              </tbody>
            </DataTable>
          )}
        </div>
        <Pagination currentPage={filters.page} totalItems={total} itemsPerPage={filters.pageSize} onPageChange={(page) => setFilters((current) => ({ ...current, page }))} onItemsPerPageChange={(pageSize) => setFilters((current) => ({ ...current, page: 1, pageSize }))} language={language} alwaysVisible />
      </DataTableFrame>

      {registerItem && <EndpointRegistrationDialog key={registerItem.id} item={registerItem} zh={zh} onClose={() => setRegisterItem(null)} onRegistered={() => {
        setRegistrationNotice(zh ? `已登记 IP ${registerItem.ip}，可在 IPAM 台账补充用途、设备和接口。` : `Registered ${registerItem.ip}. Edit its purpose, device, and interface in the IPAM ledger.`);
        setRegisterItem(null);
        void loadList();
      }} />}

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
                      [zh ? '主机判定' : 'Host classification', getEndpointClassLabel(detail.endpoint_class, zh)],
                      [zh ? '判定依据' : 'Classification evidence', getEndpointClassReason(detail.endpoint_class_reason, zh)],
                      ['VLAN', detail.vlan || ''],
                      [zh ? '站点' : 'Site', detail.site_name || ''],
                      [zh ? '来源设备' : 'Source device', detail.source_device_name || ''],
                      [zh ? '观察设备' : 'Observed device', detail.switch_name || ''],
                      [zh ? '观察接口' : 'Observed interface', detail.switch_port || ''],
                      [zh ? '路径判定' : 'Path classification', getDiscoveryPathLabel(detail, zh)],
                      [zh ? '范围状态' : 'Scope status', detail.scope_status === 'scope_pending' ? (zh ? '待确认' : 'Pending') : (detail.scope_status || '')],
                      [zh ? '来源' : 'Source', getDiscoveryObservationSourceLabel(detail.observation_source, detail.source_type, zh)],
                      ...(detail.generation !== undefined ? [[zh ? '当前成功代次' : 'Current successful generation', String(detail.generation)]] : []),
                      ...(detail.last_success_generation !== undefined ? [[zh ? '最近成功代次' : 'Last successful generation', String(detail.last_success_generation)]] : []),
                      ...(detail.latest_attempt_generation !== undefined ? [[zh ? '最新尝试代次' : 'Latest attempt generation', String(detail.latest_attempt_generation)]] : []),
                      ...(detail.collection_status ? [[zh ? '最新采集状态' : 'Latest collection status', getDiscoveryCollectionStatusLabel(detail.collection_status, zh)]] : []),
                      ...(detail.last_success_at ? [[zh ? '最近成功时间' : 'Last successful collection', formatObserved(detail.last_success_at)]] : []),
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
