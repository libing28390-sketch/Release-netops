import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Database, Filter, RefreshCw, Search, Server, SlidersHorizontal, Tag as TagIcon, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Pagination from '../components/Pagination';
import TagFilterDropdown from '../components/TagFilterDropdown';
import { TableExportMenu } from '../components/ui/TableExportMenu';
import { fetchAllPaginatedItems } from '../utils/pagination';
import { buildCmdbExportData } from './cmdbExport';
import type { TagDefinition } from '../types';

interface Props {
  language?: string;
}

interface ResourceTag {
  id: string;
  code: string;
  label: string;
  label_zh: string;
  color: string;
  category: string;
}

interface ResourceRow {
  device_id: string;
  asset_id?: string;
  hostname: string;
  asset_tag: string;
  serial_number: string;
  asset_type: string;
  device_category: string;
  device_role: string;
  vendor: string;
  model: string;
  platform: string;
  management_ip: string;
  business_ip: string;
  online_status: string;
  lifecycle_status: string;
  site_code: string;
  site_name: string;
  interface_count: number;
  link_count: number;
  tags?: ResourceTag[];
}

interface SearchFilters {
  q: string;
  search_field: string;
  search_mode: 'fuzzy' | 'exact';
  site_id: string;
  asset_type: string;
  device_category: string;
  vendor: string;
  platform: string;
  status: string;
  lifecycle_status: string;
  tag_match_all: boolean;
}

const INITIAL_FILTERS: SearchFilters = {
  q: '',
  search_field: 'all',
  search_mode: 'fuzzy',
  site_id: '',
  asset_type: 'all',
  device_category: '',
  vendor: '',
  platform: '',
  status: 'all',
  lifecycle_status: 'all',
  tag_match_all: true,
};

const FIELD_OPTIONS = [
  ['all', '全部字段', 'All fields'],
  ['hostname', '设备名称', 'Hostname'],
  ['asset_tag', '资产编号', 'Asset tag'],
  ['serial_number', '序列号 / SN', 'Serial / SN'],
  ['ip', '管理 IP / 业务 IP', 'Management / business IP'],
  ['management_ip', '管理 IP', 'Management IP'],
  ['business_ip', '业务 IP', 'Business IP'],
  ['vendor', '厂商', 'Vendor'],
  ['model', '型号', 'Model'],
  ['platform', '平台', 'Platform'],
] as const;

const TYPE_OPTIONS = [
  ['all', '全部类型', 'All types'],
  ['network_device', '网络设备', 'Network device'],
  ['server', '服务器', 'Server'],
  ['other', '其他资产', 'Other'],
] as const;

const CATEGORY_OPTIONS = [
  ['', '全部设备分类', 'All categories'],
  ['router', '路由器', 'Router'],
  ['switch', '交换机', 'Switch'],
  ['firewall', '防火墙', 'Firewall'],
  ['rack_server', '机架服务器', 'Rack server'],
  ['blade_server', '刀片服务器', 'Blade server'],
  ['storage', '存储设备', 'Storage'],
] as const;

const STATUS_OPTIONS = [
  ['all', '全部在线状态', 'All statuses'],
  ['online', '在线', 'Online'],
  ['offline', '离线', 'Offline'],
  ['pending', '待确认', 'Pending'],
] as const;

const LIFECYCLE_OPTIONS = [
  ['all', '全部生命周期', 'All lifecycle'],
  ['production', '已投产', 'Production'],
  ['staging', '待投产', 'Staging'],
  ['maintenance', '维护中', 'Maintenance'],
  ['decommissioned', '已退役', 'Decommissioned'],
] as const;

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('netops_token') || '';
  return { Authorization: `Bearer ${token}` };
}

function formatType(value: string, zh: boolean): string {
  const match = TYPE_OPTIONS.find(([key]) => key === value);
  return match ? match[zh ? 1 : 2] : value || (zh ? '未分类' : 'Unclassified');
}

function formatStatus(value: string, zh: boolean): string {
  const match = STATUS_OPTIONS.find(([key]) => key === value);
  return match ? match[zh ? 1 : 2] : value || (zh ? '未知' : 'Unknown');
}

function formatLifecycle(value: string, zh: boolean): string {
  const match = LIFECYCLE_OPTIONS.find(([key]) => key === value);
  return match ? match[zh ? 1 : 2] : value || (zh ? '未设置' : 'Unset');
}

const RESOURCE_COLUMNS = [
  { key: 'hostname', zh: '设备名称', en: 'Hostname', value: (row: ResourceRow) => row.hostname || '—' },
  { key: 'asset_type', zh: '资产类型', en: 'Asset type', value: (row: ResourceRow, zh: boolean) => formatType(row.asset_type, zh) },
  { key: 'device_category', zh: '设备分类', en: 'Device category', value: (row: ResourceRow, zh: boolean) => row.device_category || (zh ? '未分类' : 'Unclassified') },
  { key: 'device_role', zh: '设备角色', en: 'Device role', value: (row: ResourceRow) => row.device_role || '—' },
  { key: 'serial_number', zh: '序列号', en: 'Serial number', value: (row: ResourceRow) => row.serial_number || '—' },
  { key: 'asset_tag', zh: '资产编号', en: 'Asset tag', value: (row: ResourceRow) => row.asset_tag || '—' },
  { key: 'management_ip', zh: '管理 IP', en: 'Management IP', value: (row: ResourceRow) => row.management_ip || '—' },
  { key: 'business_ip', zh: '业务 IP', en: 'Business IP', value: (row: ResourceRow) => row.business_ip || '—' },
  { key: 'vendor', zh: '厂商', en: 'Vendor', value: (row: ResourceRow) => row.vendor || '—' },
  { key: 'model', zh: '型号', en: 'Model', value: (row: ResourceRow) => row.model || '—' },
  { key: 'platform', zh: '平台', en: 'Platform', value: (row: ResourceRow) => row.platform || '—' },
  { key: 'tags', zh: '标签', en: 'Tags', value: (row: ResourceRow, zh: boolean) => row.tags?.length ? row.tags.map(tag => zh ? tag.label_zh || tag.label : tag.label).filter(Boolean).join(' · ') : '—' },
  { key: 'online_status', zh: '在线状态', en: 'Online status', value: (row: ResourceRow, zh: boolean) => formatStatus(row.online_status, zh) },
  { key: 'lifecycle_status', zh: '生命周期', en: 'Lifecycle', value: (row: ResourceRow, zh: boolean) => formatLifecycle(row.lifecycle_status, zh) },
  { key: 'site_code', zh: '站点编码', en: 'Site code', value: (row: ResourceRow) => row.site_code || '—' },
  { key: 'site_name', zh: '站点名称', en: 'Site name', value: (row: ResourceRow) => row.site_name || '—' },
  { key: 'interface_count', zh: '接口数', en: 'Interfaces', value: (row: ResourceRow) => Number(row.interface_count || 0) },
  { key: 'link_count', zh: '链路数', en: 'Topology links', value: (row: ResourceRow) => Number(row.link_count || 0) },
] as const;

const ResourceSearchTab: React.FC<Props> = ({ language = 'zh' }) => {
  const zh = language === 'zh';
  const tableRef = useRef<HTMLTableElement>(null);
  const navigate = useNavigate();
  const [filters, setFilters] = useState<SearchFilters>(INITIAL_FILTERS);
  const [queryDraft, setQueryDraft] = useState('');
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [sites, setSites] = useState<Array<{ id: string; site_code?: string; site_name?: string }>>([]);
  const [rows, setRows] = useState<ResourceRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [metadataLoading, setMetadataLoading] = useState(true);
  const [error, setError] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const hasSearchCriteria = useMemo(() => (
    Boolean(
      filters.q.trim()
      || tagIds.length
      || filters.site_id
      || filters.asset_type !== 'all'
      || filters.device_category
      || filters.vendor
      || filters.platform
      || filters.status !== 'all'
      || filters.lifecycle_status !== 'all',
    )
  ), [filters, tagIds.length]);

  const updateFilter = useCallback(<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) => {
    setFilters(current => ({ ...current, [key]: value }));
    setPage(1);
  }, []);

  const loadMetadata = useCallback(async () => {
    setMetadataLoading(true);
    try {
      const [tagsResponse, sitesResponse] = await Promise.all([
        fetch('/api/tags/definitions', { headers: authHeaders() }),
        fetch('/api/cmdb/sites', { headers: authHeaders() }),
      ]);
      const tagsJson = await tagsResponse.json().catch(() => ({}));
      const sitesJson = await sitesResponse.json().catch(() => ({}));
      if (tagsResponse.ok) setAllTags(tagsJson.data || []);
      if (sitesResponse.ok) setSites(sitesJson.data || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setMetadataLoading(false);
    }
  }, []);

  const buildResourceParams = useCallback((requestedPage = page, requestedPageSize = pageSize) => new URLSearchParams({
    q: filters.q,
    search_field: filters.search_field,
    search_mode: filters.search_mode,
    site_id: filters.site_id,
    asset_type: filters.asset_type,
    device_category: filters.device_category,
    vendor: filters.vendor,
    platform: filters.platform,
    status: filters.status,
    lifecycle_status: filters.lifecycle_status,
    tag_ids: tagIds.join(','),
    tag_match_all: String(filters.tag_match_all),
    page: String(requestedPage),
    page_size: String(requestedPageSize),
  }), [filters, page, pageSize, tagIds]);

  const loadResources = useCallback(async () => {
    if (!hasSearchCriteria) {
      setRows([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const params = buildResourceParams();
      const response = await fetch(`/api/cmdb/resources?${params.toString()}`, { headers: authHeaders() });
      const json = await response.json().catch(() => ({}));
      if (!response.ok || json.success === false) throw new Error(json.detail || json.message || 'Resource search failed');
      setRows(json.data?.items || []);
      setTotal(Number(json.data?.total || 0));
    } catch (err) {
      setRows([]);
      setTotal(0);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [buildResourceParams, hasSearchCriteria]);

  useEffect(() => { void loadMetadata(); }, [loadMetadata]);
  useEffect(() => { void loadResources(); }, [loadResources]);

  const activeFilterCount = useMemo(() => {
    let count = tagIds.length;
    if (filters.q) count += 1;
    if (filters.site_id || filters.asset_type !== 'all' || filters.device_category) count += 1;
    if (filters.vendor || filters.platform) count += 1;
    if (filters.status !== 'all' || filters.lifecycle_status !== 'all') count += 1;
    return count;
  }, [filters, tagIds.length]);

  const submitSearch = () => {
    setFilters(current => ({ ...current, q: queryDraft.trim() }));
    setPage(1);
  };

  const resetSearch = () => {
    setQueryDraft('');
    setFilters(INITIAL_FILTERS);
    setTagIds([]);
    setPage(1);
  };

  const renderTags = (row: ResourceRow) => {
    const tags = row.tags || [];
    if (!tags.length) return <span className="text-slate-300">—</span>;
    return (
      <div className="flex max-w-[310px] flex-wrap gap-1">
        {tags.slice(0, 5).map(tag => (
          <span key={tag.id} className="inline-flex items-center gap-1 rounded-full bg-slate-50 px-2 py-1 text-[10px] text-slate-600">
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: tag.color || '#94a3b8' }} />
            {zh ? tag.label_zh || tag.label : tag.label}
          </span>
        ))}
        {tags.length > 5 && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-400">+{tags.length - 5}</span>}
      </div>
    );
  };

  const renderResourceCell = (row: ResourceRow, key: typeof RESOURCE_COLUMNS[number]['key']) => {
    if (key === 'tags') return renderTags(row);
    if (key === 'online_status') return <div className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${row.online_status === 'online' ? 'bg-emerald-500' : row.online_status === 'offline' ? 'bg-slate-400' : 'bg-amber-500'}`} />{formatStatus(row.online_status, zh)}</div>;
    const column = RESOURCE_COLUMNS.find(item => item.key === key);
    const value = column?.value(row, zh);
    return <span className={['serial_number', 'asset_tag', 'management_ip', 'business_ip'].includes(key) ? 'font-mono text-slate-600' : ''}>{value}</span>;
  };

  return (
    <div className="min-h-full min-w-0 w-full bg-slate-50/70 p-4 md:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">
            <Database size={15} /> CMDB / {zh ? '资源检索' : 'Resource search'}
          </div>
          <h1 className="nx-page-title text-slate-900">{zh ? '设备资源检索' : 'Device resource search'}</h1>
          <p className="nx-page-description mt-1 text-slate-500">
            {zh ? '跨站点查询全部设备，按标签、SN、IP 和技术属性快速定位资源。' : 'Search every device across sites by tags, serial numbers, IPs and technical attributes.'}
          </p>
        </div>
        <button onClick={() => { void loadMetadata(); void loadResources(); }} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm hover:border-cyan-300 hover:text-cyan-700">
          <RefreshCw size={14} className={loading || metadataLoading ? 'animate-spin' : ''} />
          {zh ? '刷新资源' : 'Refresh resources'}
        </button>
      </div>

      {error && (
        <div className="mb-4 flex items-center justify-between rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          <span>{error}</span>
          <button onClick={() => setError('')}><X size={14} /></button>
        </div>
      )}

      <section className="mb-4 min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setAdvancedOpen(current => !current)}
            className={`order-3 ml-auto rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition ${advancedOpen ? 'border-cyan-200 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500 hover:border-cyan-300 hover:text-cyan-700'}`}
          >
            {advancedOpen ? (zh ? '收起高级筛选' : 'Hide advanced') : (zh ? '高级筛选' : 'Advanced filters')}
          </button>
          <div className="flex items-center gap-2 text-sm font-bold text-slate-800"><SlidersHorizontal size={15} className="text-cyan-600" />{zh ? '搜索条件' : 'Search criteria'}</div>
          <div className="flex items-center gap-2 text-[11px] text-slate-400"><Filter size={13} />{activeFilterCount ? `${activeFilterCount} ${zh ? '项条件已启用' : 'active filters'}` : (zh ? '未设置筛选条件' : 'No filters')}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[260px] flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={queryDraft}
              onChange={event => setQueryDraft(event.target.value)}
              onKeyDown={event => { if (event.key === 'Enter') submitSearch(); }}
              placeholder={zh ? '输入设备名、资产编号、SN、IP、厂商或型号…' : 'Hostname, asset tag, SN, IP, vendor or model…'}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-9 pr-3 text-xs outline-none focus:border-cyan-400 focus:bg-white"
            />
          </div>
          <select value={filters.search_field} onChange={event => updateFilter('search_field', event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-600">
            {FIELD_OPTIONS.map(([value, zhLabel, enLabel]) => <option key={value} value={value}>{zh ? zhLabel : enLabel}</option>)}
          </select>
          <div className="flex rounded-xl border border-slate-200 bg-slate-50 p-1">
            {(['fuzzy', 'exact'] as const).map(mode => (
              <button key={mode} onClick={() => updateFilter('search_mode', mode)} className={`rounded-lg px-3 py-1.5 text-[11px] font-semibold transition ${filters.search_mode === mode ? 'bg-[#00172d] text-white shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>
                {mode === 'fuzzy' ? (zh ? '模糊' : 'Fuzzy') : (zh ? '精确' : 'Exact')}
              </button>
            ))}
          </div>
          <button onClick={submitSearch} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-cyan-700"><Search size={14} />{zh ? '搜索' : 'Search'}</button>
          <button onClick={resetSearch} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-semibold text-slate-500 hover:border-cyan-300 hover:text-cyan-700">{zh ? '重置' : 'Reset'}</button>
        </div>
        {advancedOpen && <>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          <select value={filters.site_id} onChange={event => updateFilter('site_id', event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
            <option value="">{zh ? '全部站点' : 'All sites'}</option>
            {sites.map(site => <option key={site.id} value={site.id}>{site.site_name || site.site_code || site.id}</option>)}
          </select>
          <select value={filters.asset_type} onChange={event => updateFilter('asset_type', event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
            {TYPE_OPTIONS.map(([value, zhLabel, enLabel]) => <option key={value} value={value}>{zh ? zhLabel : enLabel}</option>)}
          </select>
          <select value={filters.device_category} onChange={event => updateFilter('device_category', event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
            {CATEGORY_OPTIONS.map(([value, zhLabel, enLabel]) => <option key={value} value={value}>{zh ? zhLabel : enLabel}</option>)}
          </select>
          <input value={filters.vendor} onChange={event => updateFilter('vendor', event.target.value)} placeholder={zh ? '精确厂商' : 'Exact vendor'} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-400" />
          <input value={filters.platform} onChange={event => updateFilter('platform', event.target.value)} placeholder={zh ? '精确平台' : 'Exact platform'} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-400" />
          <select value={filters.status} onChange={event => updateFilter('status', event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
            {STATUS_OPTIONS.map(([value, zhLabel, enLabel]) => <option key={value} value={value}>{zh ? zhLabel : enLabel}</option>)}
          </select>
          <select value={filters.lifecycle_status} onChange={event => updateFilter('lifecycle_status', event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
            {LIFECYCLE_OPTIONS.map(([value, zhLabel, enLabel]) => <option key={value} value={value}>{zh ? zhLabel : enLabel}</option>)}
          </select>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <TagFilterDropdown allTags={allTags} selectedTagIds={tagIds} onChange={ids => { setTagIds(ids); setPage(1); }} language={language} />
          <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
            <button onClick={() => updateFilter('tag_match_all', true)} className={`rounded-lg px-2.5 py-1.5 text-[10px] font-semibold ${filters.tag_match_all ? 'bg-white text-cyan-700 shadow-sm' : 'text-slate-400'}`}>{zh ? '标签全部匹配' : 'All tags'}</button>
            <button onClick={() => updateFilter('tag_match_all', false)} className={`rounded-lg px-2.5 py-1.5 text-[10px] font-semibold ${!filters.tag_match_all ? 'bg-white text-cyan-700 shadow-sm' : 'text-slate-400'}`}>{zh ? '标签任一匹配' : 'Any tag'}</button>
          </div>
          <span className="text-[11px] text-slate-400">{zh ? '精确模式适合 SN、IP、资产编号；模糊模式适合设备名、厂商和型号。' : 'Exact mode suits SN, IP and asset tags; fuzzy mode suits names, vendors and models.'}</span>
        </div>
        </>}
        {!advancedOpen && activeFilterCount > 0 && (
          <div className="mt-3 rounded-xl border border-cyan-100 bg-cyan-50/70 px-3 py-2 text-[11px] text-cyan-700">
            {zh ? '已启用筛选条件；点击“高级筛选”可查看或修改站点、设备类型、状态、标签等条件。' : 'Filters are active. Open Advanced filters to review site, type, status, tag, and lifecycle criteria.'}
          </div>
        )}
       </section>

      <section className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-800"><Server size={15} className="text-cyan-600" />{zh ? '资源检索结果' : 'Resource search results'}<span className="rounded-full bg-cyan-50 px-2 py-0.5 text-[11px] text-cyan-700">{total}</span></div>
          <div className="flex items-center gap-3 text-[11px] text-slate-400">
            <span className="flex items-center gap-2"><TagIcon size={13} />{tagIds.length ? `${tagIds.length} ${zh ? '个标签条件' : 'tag conditions'}` : (zh ? '标签未筛选' : 'No tag filter')}</span>
            <TableExportMenu
              tableRef={tableRef}
              filename="cmdb-resource-search"
              language={zh ? 'zh' : 'en'}
              disabled={loading || total === 0}
              exportData={async () => {
                const allRows = await fetchAllPaginatedItems<ResourceRow>(
                  '/api/cmdb/resources', buildResourceParams(1, 1000), 1000,
                );
                return buildCmdbExportData(allRows, RESOURCE_COLUMNS.map(column => ({
                  key: column.key,
                  header: zh ? column.zh : column.en,
                  value: row => column.value(row, zh),
                })));
              }}
            />
          </div>
        </div>
        <div className="min-h-[360px] min-w-0 overflow-x-auto">
          <table ref={tableRef} className="nx-data-table min-w-[1180px] text-left text-xs">
            <thead className="bg-slate-50 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              <tr>
                {RESOURCE_COLUMNS.map(column => <th key={column.key} className="whitespace-nowrap px-4 py-3">{zh ? column.zh : column.en}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr><td colSpan={RESOURCE_COLUMNS.length} className="py-16 text-center text-slate-400"><RefreshCw size={18} className="mx-auto mb-2 animate-spin text-cyan-600" />{zh ? '检索资源中…' : 'Searching resources…'}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={RESOURCE_COLUMNS.length} className="py-16 text-center text-slate-400"><Database size={22} className="mx-auto mb-2 text-slate-300" />{hasSearchCriteria ? (zh ? '没有匹配的设备资源' : 'No matching device resources') : (zh ? '请输入条件后开始检索资源' : 'Enter search criteria to load resources')}</td></tr>
              ) : rows.map(row => (
                <tr key={row.device_id} className="hover:bg-cyan-50/40">
                  {RESOURCE_COLUMNS.map(column => <td key={column.key} className="px-4 py-3 align-top">{renderResourceCell(row, column.key)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination currentPage={page} totalItems={total} onPageChange={setPage} itemsPerPage={pageSize} onItemsPerPageChange={size => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
      </section>
    </div>
  );
};

export default ResourceSearchTab;
