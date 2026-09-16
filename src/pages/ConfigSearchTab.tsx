import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Bookmark,
  Braces,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  FileSearch,
  Filter,
  Hash,
  History,
  Loader2,
  Maximize2,
  Minimize2,
  Network,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  WrapText,
  X,
} from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton } from '../components/ui/ActionIconButton';
import { apiRequest, authHeaders } from '../api/http';

type SearchType =
  | 'AUTO'
  | 'TEXT'
  | 'EXACT_TEXT'
  | 'IPV4'
  | 'IPV6'
  | 'CIDR'
  | 'VLAN'
  | 'ASN'
  | 'INTERFACE'
  | 'PROTOCOL'
  | 'REGEX'
  | 'STRUCTURED';

type SearchScope =
  | 'LATEST_VALID_RUNNING'
  | 'LATEST_RUNNING'
  | 'ALL_LATEST'
  | 'HISTORY'
  | 'RUNNING_HISTORY'
  | 'STARTUP_HISTORY'
  | 'BASELINE'
  | 'TIME_RANGE'
  | 'SPECIFIC_VERSION'
  | 'TEMPLATES';

interface SearchFilters {
  vendors: string[];
  platforms: string[];
  sites: string[];
  roles: string[];
  device_ids: string[];
  config_types: string[];
  integrity: string[];
  snapshot_ids: string[];
  from_time: string;
  to_time: string;
}

interface ConfigSearchMatch {
  line: number;
  content: string;
  context: Array<{ line: number; content: string }>;
  match_reason: string;
  object_type: string;
  object_key: string;
  score: number;
}

interface ConfigSearchResult {
  snapshot_id: string;
  device_id: string;
  hostname: string;
  ip_address: string;
  vendor: string;
  platform: string;
  site: string;
  role: string;
  snapshot_time: string;
  trigger: string;
  integrity_status: string;
  config_type: string;
  total_matches: number;
  matches: ConfigSearchMatch[];
  score: number;
  first_seen: string;
  last_seen: string;
  occurrence_count: number;
}

interface SearchResponse {
  query: string;
  interpretation: {
    search_type: SearchType;
    normalized_query: string;
    title: string;
    description: string;
    warnings: string[];
  };
  scope: SearchScope;
  summary: {
    devices: number;
    snapshots: number;
    matches: number;
    searched_snapshots: number;
    index_updates: number;
    objects: number;
    duration_ms: number;
    truncated: boolean;
  };
  facets: Record<string, Array<{ value: string; count: number }>>;
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  results: ConfigSearchResult[];
}

interface SavedSearch {
  id: string;
  name?: string;
  query_text: string;
  search_type: SearchType;
  search_scope: SearchScope;
  filters: SearchFilters;
  result_count?: number;
  duration_ms?: number;
  created_at?: string;
  is_favorite?: boolean;
}

interface ConfigSearchTabProps {
  t: (key: string) => string;
  language?: string;
}

const EMPTY_FILTERS: SearchFilters = {
  vendors: [],
  platforms: [],
  sites: [],
  roles: [],
  device_ids: [],
  config_types: [],
  integrity: [],
  snapshot_ids: [],
  from_time: '',
  to_time: '',
};

const QUICK_QUERIES = [
  { value: '192.168.1.1', label: '精确 IP' },
  { value: '10.0.0.0/24', label: 'CIDR 关系' },
  { value: 'VLAN 100', label: 'VLAN 100' },
  { value: 'ospf', label: 'OSPF' },
  { value: 'bgp', label: 'BGP' },
  { value: 'interface', label: '接口' },
  { value: 'acl', label: 'ACL' },
  { value: 'ntp', label: 'NTP' },
];

const SEARCH_TYPE_OPTIONS: Array<{ value: SearchType; zh: string; en: string }> = [
  { value: 'AUTO', zh: '自动识别', en: 'Auto detect' },
  { value: 'TEXT', zh: '文本包含', en: 'Text' },
  { value: 'EXACT_TEXT', zh: '精确文本', en: 'Exact text' },
  { value: 'IPV4', zh: 'IPv4 地址', en: 'IPv4' },
  { value: 'IPV6', zh: 'IPv6 地址', en: 'IPv6' },
  { value: 'CIDR', zh: 'CIDR 网段关系', en: 'CIDR relation' },
  { value: 'VLAN', zh: 'VLAN ID', en: 'VLAN ID' },
  { value: 'ASN', zh: 'BGP ASN', en: 'BGP ASN' },
  { value: 'INTERFACE', zh: '接口对象', en: 'Interface' },
  { value: 'PROTOCOL', zh: '协议对象', en: 'Protocol' },
  { value: 'REGEX', zh: '安全正则', en: 'Safe regex' },
  { value: 'STRUCTURED', zh: '结构化表达式', en: 'Structured' },
];

const SCOPE_OPTIONS: Array<{ value: SearchScope; zh: string; en: string }> = [
  { value: 'LATEST_VALID_RUNNING', zh: '最新有效运行配置', en: 'Latest valid running' },
  { value: 'LATEST_RUNNING', zh: '最新运行配置', en: 'Latest running' },
  { value: 'ALL_LATEST', zh: '各设备最新配置', en: 'All latest snapshots' },
  { value: 'HISTORY', zh: '全部历史版本', en: 'All historical snapshots' },
  { value: 'RUNNING_HISTORY', zh: '运行配置历史', en: 'Running history' },
  { value: 'STARTUP_HISTORY', zh: '启动配置历史', en: 'Startup history' },
  { value: 'BASELINE', zh: '已设定基线', en: 'Designated baselines' },
  { value: 'TIME_RANGE', zh: '时间范围内快照', en: 'Snapshots in time range' },
  { value: 'SPECIFIC_VERSION', zh: '指定快照版本', en: 'Specific snapshot versions' },
  { value: 'TEMPLATES', zh: '配置模板', en: 'Configuration templates' },
];

const FACET_LABELS: Record<string, string> = {
  vendor: '厂商',
  platform: '平台',
  site: '站点',
  role: '角色',
  object_type: '对象类型',
  integrity_status: '完整性',
  config_type: '配置类型',
};

const FILTER_TO_FACET: Record<string, keyof SearchFilters> = {
  vendor: 'vendors',
  platform: 'platforms',
  site: 'sites',
  role: 'roles',
  integrity_status: 'integrity',
  config_type: 'config_types',
};

const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100';
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const formatTime = (value: string, language: string) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US');
};

const downloadBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

const ConfigSearchTab: React.FC<ConfigSearchTabProps> = ({ t, language = 'zh' }) => {
  const zh = language === 'zh';
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [searchType, setSearchType] = useState<SearchType>((searchParams.get('type') as SearchType) || 'AUTO');
  const [scope, setScope] = useState<SearchScope>((searchParams.get('scope') as SearchScope) || 'LATEST_VALID_RUNNING');
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  const [contextLines, setContextLines] = useState(2);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [recentSearches, setRecentSearches] = useState<SavedSearch[]>([]);
  const [suggestions, setSuggestions] = useState<Array<{ value: string; category: string }>>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set());
  const [isResultsFullscreen, setIsResultsFullscreen] = useState(false);
  const [wrapLines, setWrapLines] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState('');

  const activeFilterCount = useMemo(
    () => Object.entries(filters).reduce((count, [, value]) => (
      count + (Array.isArray(value) ? value.length : (value ? 1 : 0))
    ), 0),
    [filters],
  );

  const requestBody = useCallback((page = 1) => ({
    query: query.trim(),
    search_type: searchType,
    scope,
    filters,
    page,
    page_size: 20,
    context_lines: contextLines,
  }), [contextLines, filters, query, scope, searchType]);

  const loadLibrary = useCallback(async () => {
    try {
      const [saved, recent] = await Promise.all([
        apiRequest<SavedSearch[]>('/api/configs/search/saved'),
        apiRequest<SavedSearch[]>('/api/configs/search/recent?limit=20'),
      ]);
      setSavedSearches(saved);
      setRecentSearches(recent);
    } catch {
      // The search workspace remains usable if personal history is unavailable.
    }
  }, []);

  useEffect(() => {
    void loadLibrary();
  }, [loadLibrary]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isResultsFullscreen) {
        setIsResultsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isResultsFullscreen]);

  useEffect(() => {
    if (!query.trim()) {
      setSuggestions([]);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      try {
        const data = await apiRequest<{ items: Array<{ value: string; category: string }> }>(
          `/api/configs/search/suggestions?q=${encodeURIComponent(query.trim())}&limit=12`,
        );
        setSuggestions(data.items || []);
      } catch {
        setSuggestions([]);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const runSearch = useCallback(async (page = 1, override?: Partial<{
    query: string;
    searchType: SearchType;
    scope: SearchScope;
    filters: SearchFilters;
  }>) => {
    const nextQuery = (override?.query ?? query).trim();
    if (!nextQuery) {
      setError(zh ? '请输入要查找的配置内容。' : 'Enter configuration content to search.');
      return;
    }
    const body = {
      ...requestBody(page),
      query: nextQuery,
      search_type: override?.searchType ?? searchType,
      scope: override?.scope ?? scope,
      filters: override?.filters ?? filters,
    };
    setLoading(true);
    setError('');
    setShowSuggestions(false);
    try {
      const data = await apiRequest<SearchResponse>('/api/configs/search/query', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setResponse(data);
      setSearchParams({
        q: nextQuery,
        type: body.search_type,
        scope: body.scope,
      }, { replace: true });
      setExpandedResults(new Set(data.results.slice(0, 1).map((item) => item.snapshot_id)));
      if (override?.query !== undefined) setQuery(override.query);
      if (override?.searchType) setSearchType(override.searchType);
      if (override?.scope) setScope(override.scope);
      if (override?.filters) setFilters(override.filters);
      void loadLibrary();
    } catch (requestError) {
      setResponse(null);
      setError(requestError instanceof Error ? requestError.message : (zh ? '搜索请求失败。' : 'Search failed.'));
    } finally {
      setLoading(false);
    }
  }, [filters, loadLibrary, query, requestBody, scope, searchType, setSearchParams, zh]);

  const applySavedSearch = useCallback((item: SavedSearch) => {
    const nextFilters = item.filters || EMPTY_FILTERS;
    setQuery(item.query_text);
    setSearchType(item.search_type || 'AUTO');
    setScope(item.search_scope || 'LATEST_VALID_RUNNING');
    setFilters(nextFilters);
    setShowLibrary(false);
    void runSearch(1, {
      query: item.query_text,
      searchType: item.search_type || 'AUTO',
      scope: item.search_scope || 'LATEST_VALID_RUNNING',
      filters: nextFilters,
    });
  }, [runSearch]);

  const saveCurrentSearch = useCallback(async () => {
    const name = saveName.trim();
    if (!name || !query.trim()) return;
    setSaving(true);
    try {
      await apiRequest('/api/configs/search/saved', {
        method: 'POST',
        body: JSON.stringify({
          name,
          query: query.trim(),
          search_type: searchType,
          scope,
          filters,
          is_favorite: false,
        }),
      });
      setSaveName('');
      await loadLibrary();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : (zh ? '保存失败。' : 'Save failed.'));
    } finally {
      setSaving(false);
    }
  }, [filters, loadLibrary, query, saveName, scope, searchType, zh]);

  const deleteSavedSearch = useCallback(async (id: string) => {
    try {
      await apiRequest(`/api/configs/search/saved/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await loadLibrary();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : (zh ? '删除失败。' : 'Delete failed.'));
    }
  }, [loadLibrary, zh]);

  const exportResults = useCallback(async (format: 'csv' | 'xlsx' | 'json' | 'markdown') => {
    if (!query.trim()) return;
    setExporting(format);
    try {
      const exportResponse = await fetch(`/api/configs/search/export?format=${format}`, {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(requestBody(1)),
      });
      if (!exportResponse.ok) {
        const payload = await exportResponse.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${exportResponse.status}`);
      }
      const blob = await exportResponse.blob();
      const extension = format === 'markdown' ? 'md' : format;
      downloadBlob(blob, `config-search-${new Date().toISOString().slice(0, 10)}.${extension}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : (zh ? '导出失败。' : 'Export failed.'));
    } finally {
      setExporting('');
    }
  }, [query, requestBody, zh]);

  const toggleFacet = useCallback((facet: string, value: string) => {
    const filterKey = FILTER_TO_FACET[facet];
    if (!filterKey) return;
    setFilters((current) => {
      const existing = current[filterKey];
      if (!Array.isArray(existing)) return current;
      const nextValues = existing.includes(value)
        ? existing.filter((item) => item !== value)
        : [...existing, value];
      return { ...current, [filterKey]: nextValues };
    });
  }, []);

  const setCommaFilter = useCallback((key: keyof SearchFilters, value: string) => {
    setFilters((current) => ({
      ...current,
      [key]: value.split(',').map((item) => item.trim()).filter(Boolean),
    }));
  }, []);

  const toggleExpanded = useCallback((id: string) => {
    setExpandedResults((current) => {
      return current.has(id) ? new Set() : new Set([id]);
    });
  }, []);

  const renderHighlighted = useCallback((content: string) => {
    const needle = response?.interpretation.normalized_query || query.trim();
    if (!needle || searchType === 'REGEX' || needle.length > 120) return content;
    const parts = content.split(new RegExp(`(${escapeRegExp(needle)})`, 'gi'));
    return parts.map((part, index) => (
      part.toLocaleLowerCase() === needle.toLocaleLowerCase()
        ? <mark key={`${index}-${part}`} className="rounded bg-cyan-300/30 px-0.5 text-cyan-100">{part}</mark>
        : <React.Fragment key={`${index}-${part}`}>{part}</React.Fragment>
    ));
  }, [query, response?.interpretation.normalized_query, searchType]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50">
      <PageHero
        icon={Search}
        title={t('configSearchTab')}
        subtitle={zh ? '面向最新与历史配置的对象级检索、定位、审计与导出工作台' : 'Object-aware search, traceability, audit, and export across configuration snapshots'}
        actions={(
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowLibrary((value) => !value)}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 shadow-sm hover:border-cyan-300 hover:text-cyan-700"
            >
              <Bookmark size={14} />
              {zh ? '搜索库' : 'Search library'}
              {savedSearches.length > 0 && <span className="rounded-full bg-cyan-50 px-1.5 py-0.5 text-[9px] text-cyan-700">{savedSearches.length}</span>}
            </button>
          </div>
        )}
      />

      <div className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-hidden px-5 py-4">
        <section className="shrink-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 xl:flex-row">
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <input
                autoFocus
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setShowSuggestions(true);
                }}
                onFocus={() => setShowSuggestions(true)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void runSearch(1);
                  if (event.key === 'Escape') setShowSuggestions(false);
                }}
                placeholder={zh ? '输入 IP、CIDR、VLAN、ASN、接口、协议、文本或安全正则…' : 'IP, CIDR, VLAN, ASN, interface, protocol, text, or safe regex…'}
                className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50 pl-10 pr-10 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-400 focus:bg-white focus:ring-4 focus:ring-cyan-50"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    setResponse(null);
                    setError('');
                  }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                  aria-label={zh ? '清空搜索' : 'Clear search'}
                >
                  <X size={14} />
                </button>
              )}
              {showSuggestions && suggestions.length > 0 && (
                <div className="absolute left-0 right-0 top-12 z-30 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
                  {suggestions.map((item) => (
                    <button
                      type="button"
                      key={`${item.category}-${item.value}`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        setQuery(item.value);
                        setShowSuggestions(false);
                      }}
                      className="flex w-full items-center gap-3 border-b border-slate-100 px-3.5 py-2 text-left last:border-0 hover:bg-cyan-50"
                    >
                      <Search size={13} className="text-cyan-600" />
                      <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-700">{item.value}</span>
                      <span className="text-[10px] text-slate-400">{item.category}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <select
              value={searchType}
              onChange={(event) => setSearchType(event.target.value as SearchType)}
              className="h-11 min-w-[160px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold text-slate-700 outline-none focus:border-cyan-400"
              aria-label={zh ? '搜索类型' : 'Search type'}
            >
              {SEARCH_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{zh ? option.zh : option.en}</option>
              ))}
            </select>
            <select
              value={scope}
              onChange={(event) => setScope(event.target.value as SearchScope)}
              className="h-11 min-w-[190px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold text-slate-700 outline-none focus:border-cyan-400"
              aria-label={zh ? '搜索作用域' : 'Search scope'}
            >
              {SCOPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{zh ? option.zh : option.en}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setShowFilters((value) => !value)}
              className={`relative inline-flex h-11 items-center justify-center gap-2 rounded-xl border px-4 text-xs font-bold transition ${
                showFilters || activeFilterCount > 1
                  ? 'border-cyan-300 bg-cyan-50 text-cyan-700'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-cyan-300'
              }`}
            >
              <Filter size={14} />
              {zh ? '筛选' : 'Filters'}
              {activeFilterCount > 0 && (
                <span className="rounded-full bg-cyan-600 px-1.5 py-0.5 text-[9px] text-white">{activeFilterCount}</span>
              )}
            </button>
            <button
              type="button"
              onClick={() => void runSearch(1)}
              disabled={loading || !query.trim()}
              className="inline-flex h-11 min-w-[112px] items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 px-5 text-xs font-black text-white shadow-lg shadow-cyan-200 transition hover:-translate-y-0.5 disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
              {zh ? '开始搜索' : 'Search'}
            </button>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? '快速示例' : 'Quick examples'}</span>
            {QUICK_QUERIES.map((item) => (
              <button
                type="button"
                key={item.value}
                onClick={() => {
                  setQuery(item.value);
                  setSearchType('AUTO');
                }}
                className="rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-slate-500 hover:border-cyan-200 hover:bg-cyan-50 hover:text-cyan-700"
              >
                {item.label}
              </button>
            ))}
            <span className="ml-auto text-[10px] text-slate-400">
              {zh ? '默认仅检索最新、完整性有效的 running-config' : 'Default: latest valid running-config only'}
            </span>
          </div>

          {showFilters && (
            <div className="mt-4 grid grid-cols-1 gap-3 rounded-xl border border-cyan-100 bg-cyan-50/40 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
              {([
                ['vendors', zh ? '厂商（逗号分隔）' : 'Vendors'],
                ['platforms', zh ? '平台（逗号分隔）' : 'Platforms'],
                ['sites', zh ? '站点（逗号分隔）' : 'Sites'],
                ['roles', zh ? '角色（逗号分隔）' : 'Roles'],
              ] as Array<[keyof SearchFilters, string]>).map(([key, label]) => (
                <label key={key} className="space-y-1.5">
                  <span className="text-[10px] font-bold text-slate-500">{label}</span>
                  <input
                    value={(filters[key] as string[]).join(', ')}
                    onChange={(event) => setCommaFilter(key, event.target.value)}
                    className={inputClass}
                    placeholder={key === 'vendors' ? 'Cisco, Huawei' : ''}
                  />
                </label>
              ))}
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold text-slate-500">{zh ? '完整性' : 'Integrity'}</span>
                <select
                  value={filters.integrity[0] || ''}
                  onChange={(event) => setFilters((current) => ({ ...current, integrity: event.target.value ? [event.target.value] : [] }))}
                  className={inputClass}
                >
                  <option value="">{zh ? '全部' : 'All'}</option>
                  <option value="verified">{zh ? '已验证' : 'Verified'}</option>
                  <option value="unknown">{zh ? '未知' : 'Unknown'}</option>
                  <option value="invalid">{zh ? '无效' : 'Invalid'}</option>
                </select>
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold text-slate-500">{zh ? '上下文行数' : 'Context lines'}</span>
                <select value={contextLines} onChange={(event) => setContextLines(Number(event.target.value))} className={inputClass}>
                  {[0, 1, 2, 3, 5, 8].map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold text-slate-500">{zh ? '开始时间' : 'From'}</span>
                <input
                  type="datetime-local"
                  value={filters.from_time}
                  onChange={(event) => setFilters((current) => ({ ...current, from_time: event.target.value }))}
                  className={inputClass}
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold text-slate-500">{zh ? '结束时间' : 'To'}</span>
                <input
                  type="datetime-local"
                  value={filters.to_time}
                  onChange={(event) => setFilters((current) => ({ ...current, to_time: event.target.value }))}
                  className={inputClass}
                />
              </label>
              <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-2">
                <button
                  type="button"
                  onClick={() => setFilters(EMPTY_FILTERS)}
                  className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-[10px] font-bold text-slate-500 hover:text-rose-600"
                >
                  {zh ? '重置筛选' : 'Reset'}
                </button>
                <button
                  type="button"
                  onClick={() => void runSearch(1)}
                  className="h-9 rounded-lg bg-slate-900 px-4 text-[10px] font-bold text-white"
                >
                  {zh ? '应用筛选' : 'Apply'}
                </button>
              </div>
            </div>
          )}
        </section>

        {error && (
          <div className="flex shrink-0 items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
            <AlertCircle size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
            <button type="button" onClick={() => void runSearch(response?.page || 1)} className="inline-flex items-center gap-1 font-bold hover:underline">
              <RefreshCw size={12} /> {zh ? '重试' : 'Retry'}
            </button>
            <button type="button" onClick={() => setError('')}><X size={14} /></button>
          </div>
        )}

        {loading ? (
          <div className="flex min-h-0 flex-1 items-center justify-center rounded-2xl border border-slate-200 bg-white">
            <div className="text-center">
              <Loader2 size={30} className="mx-auto animate-spin text-cyan-600" />
              <p className="mt-3 text-sm font-bold text-slate-700">{zh ? '正在解析配置对象并计算相关度…' : 'Parsing objects and ranking matches…'}</p>
              <p className="mt-1 text-xs text-slate-400">{zh ? '历史作用域可能需要读取更多快照' : 'Historical scope may scan more snapshots'}</p>
            </div>
          </div>
        ) : response ? (
          <>
            <section className="grid shrink-0 grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
              {[
                { icon: Server, label: zh ? '命中设备' : 'Devices', value: response.summary.devices, tone: 'text-cyan-700 bg-cyan-50' },
                { icon: FileSearch, label: zh ? '命中快照' : 'Snapshots', value: response.summary.snapshots, tone: 'text-blue-700 bg-blue-50' },
                { icon: Braces, label: zh ? '配置对象' : 'Objects', value: response.summary.objects, tone: 'text-indigo-700 bg-indigo-50' },
                { icon: Hash, label: zh ? '命中行' : 'Matches', value: response.summary.matches, tone: 'text-violet-700 bg-violet-50' },
                { icon: Clock3, label: zh ? '耗时' : 'Duration', value: `${response.summary.duration_ms} ms`, tone: 'text-amber-700 bg-amber-50' },
                { icon: Network, label: zh ? '扫描快照' : 'Scanned', value: response.summary.searched_snapshots, tone: 'text-emerald-700 bg-emerald-50' },
              ].map((metric) => (
                <div key={metric.label} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className={`flex h-7 w-7 items-center justify-center rounded-lg ${metric.tone}`}><metric.icon size={13} /></span>
                    <div className="min-w-0">
                      <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{metric.label}</p>
                      <p className="truncate text-sm font-black text-slate-800">{metric.value}</p>
                    </div>
                  </div>
                </div>
              ))}
            </section>

            <div className={`flex min-h-0 gap-4 overflow-hidden ${isResultsFullscreen
              ? 'fixed inset-3 z-50 rounded-2xl bg-slate-50 p-3 shadow-2xl ring-1 ring-slate-200'
              : 'flex-1'
            }`}>
              <aside className="hidden w-56 shrink-0 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3 shadow-sm lg:block">
                <div className="mb-3 flex items-center gap-2 border-b border-slate-100 pb-2">
                  <SlidersHorizontal size={14} className="text-cyan-600" />
                  <h3 className="text-xs font-black text-slate-700">{zh ? '结果分面' : 'Result facets'}</h3>
                </div>
                <div className="space-y-4">
                  {Object.entries(response.facets).map(([facet, values]) => (
                    <div key={facet}>
                      <p className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-slate-400">{FACET_LABELS[facet] || facet}</p>
                      <div className="space-y-0.5">
                        {values.slice(0, 8).map((item) => {
                          const filterKey = FILTER_TO_FACET[facet];
                          const selected = filterKey && Array.isArray(filters[filterKey]) && (filters[filterKey] as string[]).includes(item.value);
                          return (
                            <button
                              type="button"
                              key={item.value}
                              onClick={() => toggleFacet(facet, item.value)}
                              disabled={!filterKey}
                              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[10px] transition ${
                                selected ? 'bg-cyan-50 font-bold text-cyan-700' : 'text-slate-600 hover:bg-slate-50 disabled:cursor-default'
                              }`}
                            >
                              <span className="min-w-0 flex-1 truncate">{item.value}</span>
                              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-500">{item.count}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </aside>

              <main className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-slate-100 bg-gradient-to-r from-slate-50 to-white px-4 py-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700"><Sparkles size={15} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-xs font-black text-slate-800">{response.interpretation.title}</p>
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold text-emerald-700">
                        {SCOPE_OPTIONS.find((item) => item.value === response.scope)?.[zh ? 'zh' : 'en']}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-bold text-slate-600">
                        {zh ? `类型：${response.interpretation.search_type}` : response.interpretation.search_type}
                      </span>
                      {response.summary.truncated && (
                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-bold text-amber-700">{zh ? '已达到扫描上限' : 'Scan limit reached'}</span>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-[10px] text-slate-500">{response.interpretation.description}</p>
                  </div>
                  <div className="flex items-center gap-1">
                    <ActionIconButton
                      icon={isResultsFullscreen ? Minimize2 : Maximize2}
                      label={isResultsFullscreen ? (zh ? '退出沉浸查看' : 'Exit focus view') : (zh ? '沉浸查看结果' : 'Focus results')}
                      variant={isResultsFullscreen ? 'accent' : 'default'}
                      size="sm"
                      aria-pressed={isResultsFullscreen}
                      onClick={() => setIsResultsFullscreen((value) => !value)}
                    />
                    <button
                      type="button"
                      onClick={() => setWrapLines((value) => !value)}
                      className={`rounded-lg border p-2 ${wrapLines ? 'border-cyan-200 bg-cyan-50 text-cyan-700' : 'border-slate-200 text-slate-500 hover:text-slate-800'}`}
                      title={zh ? '切换自动换行' : 'Toggle line wrapping'}
                    >
                      <WrapText size={13} />
                    </button>
                    {(['csv', 'xlsx', 'json', 'markdown'] as const).map((format) => (
                      <ActionButton
                        type="button"
                        key={format}
                        icon={exporting === format ? Loader2 : Download}
                        iconClassName={exporting === format ? 'animate-spin' : undefined}
                        variant="default"
                        size="sm"
                        onClick={() => void exportResults(format)}
                        disabled={Boolean(exporting)}
                        className="!h-8 !px-2 !text-[9px] uppercase"
                      >
                        {format === 'markdown' ? 'MD' : format.toUpperCase()}
                      </ActionButton>
                    ))}
                  </div>
                </div>

                {response.interpretation.warnings.length > 0 && (
                  <div className="shrink-0 border-b border-amber-100 bg-amber-50 px-4 py-2 text-[10px] text-amber-800">
                    {response.interpretation.warnings.join('；')}
                  </div>
                )}

                <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                  {response.results.length === 0 ? (
                    <div className="flex h-full min-h-[260px] flex-col items-center justify-center text-center">
                      <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-50 text-slate-300"><FileSearch size={30} /></span>
                      <p className="mt-4 text-sm font-black text-slate-700">{zh ? '没有找到匹配配置' : 'No configuration matched'}</p>
                      <p className="mt-1 max-w-lg text-xs leading-5 text-slate-400">
                        {zh ? '请检查检索类型、作用域和筛选条件。纯数字存在歧义，必要时可手工切换为 VLAN、ASN 或精确文本。' : 'Review the type, scope, and filters. Bare numbers are ambiguous; choose VLAN, ASN, or exact text when needed.'}
                      </p>
                    </div>
                  ) : response.results.map((result) => {
                    const expanded = expandedResults.has(result.snapshot_id);
                    const visibleMatches = expanded ? result.matches : result.matches.slice(0, 3);
                    return (
                      <article key={result.snapshot_id} className="overflow-hidden rounded-xl border border-slate-200 bg-white transition hover:border-cyan-200 hover:shadow-md">
                        <button
                          type="button"
                          onClick={() => toggleExpanded(result.snapshot_id)}
                          className="flex w-full items-center gap-3 bg-slate-50/70 px-4 py-3 text-left"
                        >
                          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${result.integrity_status === 'verified' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                            <Server size={15} />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="text-xs font-black text-slate-800">{result.hostname}</h3>
                              <code className="text-[10px] text-slate-400">{result.ip_address}</code>
                              {[result.vendor, result.platform, result.site, result.role].filter(Boolean).map((value) => (
                                <span key={value} className="rounded bg-white px-1.5 py-0.5 text-[9px] font-semibold text-slate-500 ring-1 ring-slate-200">{value}</span>
                              ))}
                            </div>
                            <p className="mt-1 text-[10px] text-slate-400">
                              {formatTime(result.snapshot_time, language)} · {result.config_type} · {result.integrity_status}
                              {scope === 'HISTORY' && ` · ${zh ? '首次/末次' : 'first/last'} ${formatTime(result.first_seen, language)} / ${formatTime(result.last_seen, language)}`}
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="text-sm font-black text-cyan-700">{result.total_matches}</p>
                            <p className="text-[9px] text-slate-400">{zh ? '命中行' : 'matches'}</p>
                          </div>
                          <ChevronDown size={15} className={`text-slate-400 transition ${expanded ? 'rotate-180' : ''}`} />
                        </button>

                        <div className={`bg-[#0b1220] font-mono text-[11px] leading-5 text-slate-300 ${expanded ? 'max-h-[min(60vh,560px)] overflow-y-auto' : ''}`}>
                          {visibleMatches.map((match, matchIndex) => (
                            <div key={`${match.line}-${matchIndex}`} className="border-b border-white/5 last:border-0">
                              <div className="flex items-center gap-2 bg-white/[0.025] px-3 py-1 text-[9px] text-slate-500">
                                <span className="rounded bg-cyan-500/10 px-1.5 text-cyan-300">{match.object_type}</span>
                                {match.object_key && <span className="max-w-[360px] truncate">{match.object_key}</span>}
                                <span className="ml-auto text-cyan-400">{match.match_reason}</span>
                              </div>
                              {(match.context?.length ? match.context : [{ line: match.line, content: match.content }]).map((line) => (
                                <div key={`${match.line}-${line.line}`} className={`flex px-3 py-0.5 ${line.line === match.line ? 'bg-cyan-400/10' : ''}`}>
                                  <span className="w-12 shrink-0 select-none pr-3 text-right text-slate-600">{line.line}</span>
                                  <code className={`${wrapLines ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'} min-w-0 flex-1 overflow-x-auto`}>
                                    {line.line === match.line ? renderHighlighted(line.content) : line.content}
                                  </code>
                                </div>
                              ))}
                            </div>
                          ))}
                          {!expanded && result.matches.length > 3 && (
                            <button
                              type="button"
                              onClick={() => toggleExpanded(result.snapshot_id)}
                              className="w-full px-4 py-2 text-left text-[10px] font-bold text-cyan-400 hover:bg-white/5"
                            >
                              + {zh ? `展开其余 ${result.matches.length - 3} 处命中` : `Show ${result.matches.length - 3} more matches`}
                            </button>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>

                {response.total_pages > 1 && (
                  <div className="flex shrink-0 items-center justify-between border-t border-slate-100 px-4 py-2.5">
                    <span className="text-[10px] text-slate-400">{zh ? `共 ${response.total} 个快照结果` : `${response.total} snapshot results`}</span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={response.page <= 1 || loading}
                        onClick={() => void runSearch(response.page - 1)}
                        className="rounded-lg border border-slate-200 p-1.5 text-slate-500 disabled:opacity-30"
                      >
                        <ChevronLeft size={13} />
                      </button>
                      <span className="text-[10px] font-bold text-slate-600">{response.page} / {response.total_pages}</span>
                      <button
                        type="button"
                        disabled={response.page >= response.total_pages || loading}
                        onClick={() => void runSearch(response.page + 1)}
                        className="rounded-lg border border-slate-200 p-1.5 text-slate-500 disabled:opacity-30"
                      >
                        <ChevronRight size={13} />
                      </button>
                    </div>
                  </div>
                )}
              </main>
            </div>
          </>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/70">
            <div className="max-w-2xl px-8 text-center">
              <span className="mx-auto flex h-20 w-20 items-center justify-center rounded-3xl bg-gradient-to-br from-cyan-50 to-blue-50 text-cyan-600 ring-1 ring-cyan-100"><Search size={34} strokeWidth={1.5} /></span>
              <h2 className="mt-5 text-lg font-black text-slate-800">{zh ? '从“字符串搜索”升级为配置对象检索' : 'Search configuration objects, not just strings'}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">
                {zh
                  ? '系统会自动区分 IP、CIDR、VLAN、ASN、接口和协议，识别华为 VRP、H3C Comware 与 Cisco IOS 常见配置块，并默认遮蔽口令、密钥和 SNMP 团体字。'
                  : 'The workspace classifies IP, CIDR, VLAN, ASN, interface, and protocol queries, understands common vendor blocks, and redacts secrets by default.'}
              </p>
              <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
                {[
                  { icon: Sparkles, title: zh ? '自动解释' : 'Interpretation', text: zh ? '显示系统如何理解输入' : 'See how input is understood' },
                  { icon: ShieldCheck, title: zh ? '安全展示' : 'Safe output', text: zh ? '敏感配置默认脱敏' : 'Secrets redacted by default' },
                  { icon: History, title: zh ? '历史追溯' : 'History', text: zh ? '定位首次与末次出现' : 'Trace first and last occurrence' },
                ].map((item) => (
                  <div key={item.title} className="rounded-xl border border-slate-200 bg-white p-3 text-left">
                    <item.icon size={16} className="text-cyan-600" />
                    <p className="mt-2 text-xs font-black text-slate-700">{item.title}</p>
                    <p className="mt-1 text-[10px] text-slate-400">{item.text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {showLibrary && (
          <aside className="absolute bottom-4 right-5 top-4 z-40 flex w-[390px] max-w-[calc(100%-2.5rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
            <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-50 text-cyan-700"><Bookmark size={16} /></span>
              <div className="flex-1">
                <h3 className="text-sm font-black text-slate-800">{zh ? '个人搜索库' : 'Personal search library'}</h3>
                <p className="text-[10px] text-slate-400">{zh ? '保存条件并回看最近检索' : 'Saved conditions and recent searches'}</p>
              </div>
              <button type="button" onClick={() => setShowLibrary(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={15} /></button>
            </div>
            <div className="border-b border-slate-100 bg-slate-50 p-3">
              <div className="flex gap-2">
                <input
                  value={saveName}
                  onChange={(event) => setSaveName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void saveCurrentSearch();
                  }}
                  placeholder={zh ? '为当前条件命名…' : 'Name current search…'}
                  className={inputClass}
                />
                <button
                  type="button"
                  onClick={() => void saveCurrentSearch()}
                  disabled={saving || !saveName.trim() || !query.trim()}
                  className="inline-flex shrink-0 items-center gap-1 rounded-xl bg-slate-900 px-3 text-[10px] font-bold text-white disabled:opacity-40"
                >
                  {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  {zh ? '保存' : 'Save'}
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <p className="mb-2 flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-slate-400"><Star size={12} /> {zh ? '已保存' : 'Saved'}</p>
              <div className="space-y-2">
                {savedSearches.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-slate-200 py-5 text-center text-[10px] text-slate-400">{zh ? '尚未保存搜索条件' : 'No saved searches'}</p>
                ) : savedSearches.map((item) => (
                  <div key={item.id} className="group flex items-center gap-2 rounded-xl border border-slate-200 p-2.5 hover:border-cyan-200 hover:bg-cyan-50/30">
                    <button type="button" onClick={() => applySavedSearch(item)} className="min-w-0 flex-1 text-left">
                      <p className="truncate text-xs font-black text-slate-700">{item.name || item.query_text}</p>
                      <p className="mt-0.5 truncate font-mono text-[9px] text-slate-400">{item.query_text} · {item.search_type}</p>
                    </button>
                    <ActionIconButton
                      icon={Trash2}
                      label={zh ? '删除已保存搜索' : 'Delete saved search'}
                      size="xs"
                      variant="danger"
                      onClick={() => void deleteSavedSearch(item.id)}
                      className="opacity-0 group-hover:opacity-100"
                    />
                  </div>
                ))}
              </div>

              <p className="mb-2 mt-5 flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-slate-400"><Clock3 size={12} /> {zh ? '最近搜索' : 'Recent'}</p>
              <div className="space-y-1">
                {recentSearches.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    onClick={() => applySavedSearch(item)}
                    className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left hover:bg-slate-50"
                  >
                    <History size={12} className="shrink-0 text-slate-300" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-[10px] text-slate-600">{item.query_text}</p>
                      <p className="text-[9px] text-slate-400">{item.search_type} · {item.result_count || 0} {zh ? '条结果' : 'results'} · {item.duration_ms || 0} ms</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
};

export default ConfigSearchTab;
