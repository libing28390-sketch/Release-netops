import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronRight,
  FileCode2,
  Filter,
  Layers3,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Search,
  Server,
  ShieldAlert,
  ShieldCheck,
  X,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import PageHero from '../components/PageHero';
import { apiRequest } from '../api/http';

interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  message?: string;
}

interface PlatformRelease {
  id: string;
  profile_id: string;
  release_number: number;
  status: string;
  connection_driver: string;
  parser_platform: string;
  safety_policy_json?: string;
  checksum?: string;
  validation_status?: string;
  validation_result_json?: string;
  created_at?: string;
  updated_at?: string;
  submitted_by?: string;
  approved_by?: string;
  published_by?: string;
}

interface PlatformProfile {
  id: string;
  tenant_id?: string | null;
  platform_code: string;
  name_zh?: string;
  name_en?: string;
  vendor?: string;
  connection_driver?: string;
  parser_platform?: string;
  source?: string;
  status?: string;
  description?: string;
  current_release_id?: string | null;
  current_release_number?: number | null;
  current_release_checksum?: string | null;
  current_release_status?: string | null;
  current_release_validation_status?: string | null;
  current_action_count?: number;
  bound_device_count?: number;
  online_device_count?: number;
  created_at?: string;
  updated_at?: string;
}

interface PlatformProfileDetail extends PlatformProfile {
  releases?: PlatformRelease[];
}

interface PlatformHealth {
  health_score?: number | null;
  health_status?: 'healthy' | 'warning' | 'critical' | 'unknown';
  command_coverage_pct?: number | null;
  template_coverage_pct?: number | null;
  sample_pass_rate_pct?: number | null;
  recent_run_count?: number;
  recent_success_rate_pct?: number | null;
  recent_parse_failure_count?: number;
  recent_parse_failure_rate_pct?: number | null;
  last_run_at?: string | null;
  avg_duration_ms?: number | null;
  p95_duration_ms?: number | null;
  affected_playbook_count?: number;
  failure_queue?: Array<{
    id: string;
    action_code?: string;
    error_code?: string;
    failure_stage?: string;
    created_at?: string;
    raw_output_available?: boolean;
    parser_template_version_id?: string | null;
  }>;
}

interface IdentificationConflict {
  id: string;
  device_id: string;
  hostname?: string;
  ip_address?: string;
  site?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  observation_commands?: string[];
  platform_candidates?: Array<{ platform_profile_id?: string; platform_code?: string; score?: number }>;
}

interface ActionDefinition {
  action_code: string;
  name_zh?: string;
  name_en?: string;
  purpose?: string;
  risk_level?: string;
  required_fields_json?: string;
  consumers_json?: string;
  read_only?: number | boolean;
  max_records?: number;
  timeout_seconds?: number;
  command?: string | null;
  parser_template_version_id?: string | null;
  field_contract_json?: string;
}

type DetailTab = 'overview' | 'mappings' | 'releases';
type ReadinessFilter = 'all' | 'ready' | 'degraded';

interface Props {
  language: string;
}

const panelClass = 'rounded-2xl border border-black/5 bg-white shadow-sm';

const parseJsonList = (value?: string): string[] => {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
};

const parseJsonObject = (value?: string): Record<string, unknown> => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};

const formatDate = (value: string | undefined, zh: boolean): string => {
  if (!value) return zh ? '暂无' : '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const displayName = (profile: PlatformProfile, zh: boolean): string => (
  (zh ? profile.name_zh : profile.name_en) || profile.name_zh || profile.name_en || profile.platform_code
);

const isReady = (profile: PlatformProfile): boolean => (
  String(profile.status || '').toUpperCase() === 'ACTIVE'
  && String(profile.current_release_status || '').toUpperCase() === 'PUBLISHED'
  && String(profile.current_release_validation_status || '').toUpperCase() === 'PASSED'
  && Number(profile.current_action_count || 0) > 0
);

const statusClass = (value?: string): string => {
  switch (String(value || '').toUpperCase()) {
    case 'ACTIVE':
    case 'PUBLISHED':
    case 'PASSED':
      return 'bg-emerald-50 text-emerald-700 ring-emerald-100';
    case 'DRAFT':
    case 'PENDING':
    case 'SUBMITTED':
      return 'bg-amber-50 text-amber-700 ring-amber-100';
    case 'FAILED':
    case 'ARCHIVED':
    case 'DEPRECATED':
      return 'bg-rose-50 text-rose-700 ring-rose-100';
    default:
      return 'bg-slate-50 text-slate-600 ring-slate-100';
  }
};

const statusLabel = (value: string | undefined, zh: boolean): string => {
  const normalized = String(value || '').toUpperCase();
  if (!normalized) return zh ? '未配置' : 'Not configured';
  if (!zh) return normalized;
  const labels: Record<string, string> = {
    ACTIVE: '启用', PUBLISHED: '已发布', PASSED: '通过', DRAFT: '草稿',
    PENDING: '待验证', SUBMITTED: '待审批', FAILED: '失败', ARCHIVED: '已归档', DEPRECATED: '已废弃',
  };
  return labels[normalized] || normalized;
};

const PlatformRegistryTab: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const requestIdRef = useRef(0);
  const [profiles, setProfiles] = useState<PlatformProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [vendorFilter, setVendorFilter] = useState('all');
  const [readinessFilter, setReadinessFilter] = useState<ReadinessFilter>('all');
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [selectedProfile, setSelectedProfile] = useState<PlatformProfileDetail | null>(null);
  const [actions, setActions] = useState<ActionDefinition[]>([]);
  const [actionsLoading, setActionsLoading] = useState(false);
  const [actionsError, setActionsError] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>('overview');
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState('');
  const [sampleRunId, setSampleRunId] = useState('');
  const [identificationConflicts, setIdentificationConflicts] = useState<IdentificationConflict[]>([]);
  const [conflictsLoading, setConflictsLoading] = useState(false);

  const refreshProfiles = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiRequest<ApiEnvelope<PlatformProfile[]>>('/api/platform-registry/profiles');
      const nextProfiles = response.data || [];
      setProfiles(nextProfiles);
      setSelectedProfileId((current) => (
        current && nextProfiles.some((item) => item.id === current) ? current : (nextProfiles[0]?.id || '')
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '平台注册表加载失败' : 'Failed to load platform registry'));
    } finally {
      setLoading(false);
    }
  }, [zh]);

  const loadProfile = useCallback(async (profileId: string) => {
    if (!profileId) {
      setSelectedProfile(null);
      setActions([]);
      return;
    }
    const requestId = ++requestIdRef.current;
    setDetailLoading(true);
    setActionsLoading(true);
    setActionsError('');
    try {
      const response = await apiRequest<ApiEnvelope<PlatformProfileDetail>>(
        `/api/platform-registry/profiles/${encodeURIComponent(profileId)}`,
      );
      if (requestId !== requestIdRef.current) return;
      setSelectedProfile(response.data);
    } catch (cause) {
      if (requestId === requestIdRef.current) {
        setSelectedProfile(null);
        setError(cause instanceof Error ? cause.message : (zh ? '平台详情加载失败' : 'Failed to load platform details'));
      }
    } finally {
      if (requestId === requestIdRef.current) setDetailLoading(false);
    }
    try {
      const response = await apiRequest<ApiEnvelope<ActionDefinition[]>>(
        `/api/platform-registry/profiles/${encodeURIComponent(profileId)}/actions`,
      );
      if (requestId === requestIdRef.current) setActions(response.data || []);
    } catch (cause) {
      if (requestId === requestIdRef.current) {
        setActions([]);
        setActionsError(cause instanceof Error ? cause.message : (zh ? '动作映射加载失败' : 'Failed to load action mappings'));
      }
    } finally {
      if (requestId === requestIdRef.current) setActionsLoading(false);
    }
  }, [zh]);

  const loadHealth = useCallback(async (profileId: string) => {
    if (!profileId) {
      setHealth(null);
      return;
    }
    setHealthLoading(true);
    setHealthError('');
    try {
      const response = await apiRequest<ApiEnvelope<PlatformHealth>>(
        `/api/platform-registry/profiles/${encodeURIComponent(profileId)}/health?range_hours=168`,
      );
      setHealth(response.data || null);
    } catch (cause) {
      setHealth(null);
      setHealthError(cause instanceof Error ? cause.message : (zh ? '平台健康度加载失败' : 'Failed to load platform health'));
    } finally {
      setHealthLoading(false);
    }
  }, [zh]);

  const loadIdentificationConflicts = useCallback(async () => {
    setConflictsLoading(true);
    try {
      const response = await apiRequest<ApiEnvelope<IdentificationConflict[]>>(
        '/api/platform-registry/identification-conflicts?status=OPEN&limit=50',
      );
      setIdentificationConflicts(response.data || []);
    } catch {
      setIdentificationConflicts([]);
    } finally {
      setConflictsLoading(false);
    }
  }, []);

  useEffect(() => { void refreshProfiles(); }, [refreshProfiles]);
  useEffect(() => { void loadProfile(selectedProfileId); }, [loadProfile, selectedProfileId]);
  useEffect(() => { void loadHealth(selectedProfileId); }, [loadHealth, selectedProfileId]);
  useEffect(() => { void loadIdentificationConflicts(); }, [loadIdentificationConflicts]);

  const createFailureSample = async (runId: string) => {
    setSampleRunId(runId);
    try {
      await apiRequest(`/api/platform-registry/runs/${encodeURIComponent(runId)}/parser-sample`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      await loadHealth(selectedProfileId);
    } catch (cause) {
      setHealthError(cause instanceof Error ? cause.message : (zh ? '失败样例保存失败' : 'Failed to save parser sample'));
    } finally {
      setSampleRunId('');
    }
  };

  const vendors = useMemo(
    () => Array.from(new Set(profiles.map((profile) => profile.vendor).filter(Boolean))).sort(),
    [profiles],
  );

  const filteredProfiles = useMemo(() => {
    const query = search.trim().toLowerCase();
    return profiles.filter((profile) => {
      const matchesQuery = !query || [
        profile.platform_code, profile.name_zh, profile.name_en, profile.vendor,
        profile.connection_driver, profile.parser_platform,
      ].some((value) => String(value || '').toLowerCase().includes(query));
      const matchesSource = sourceFilter === 'all' || String(profile.source || '').toUpperCase() === sourceFilter;
      const matchesStatus = statusFilter === 'all' || String(profile.status || '').toUpperCase() === statusFilter;
      const matchesVendor = vendorFilter === 'all' || profile.vendor === vendorFilter;
      const matchesReadiness = readinessFilter === 'all' || (readinessFilter === 'ready' ? isReady(profile) : !isReady(profile));
      return matchesQuery && matchesSource && matchesStatus && matchesVendor && matchesReadiness;
    });
  }, [profiles, readinessFilter, search, sourceFilter, statusFilter, vendorFilter]);

  const selectedListProfile = profiles.find((profile) => profile.id === selectedProfileId) || null;
  const currentProfile: PlatformProfileDetail | null = selectedProfile
    || (selectedListProfile ? { ...selectedListProfile, releases: [] } : null);
  const currentRelease = currentProfile?.releases?.find((release) => release.id === currentProfile.current_release_id)
    || currentProfile?.releases?.[0];
  const readyCount = profiles.filter(isReady).length;
  const boundDeviceCount = profiles.reduce((total, profile) => total + Number(profile.bound_device_count || 0), 0);
  const onlineDeviceCount = profiles.reduce((total, profile) => total + Number(profile.online_device_count || 0), 0);

  const selectProfile = (profileId: string) => {
    setSelectedProfileId(profileId);
    setDetailTab('overview');
    setError('');
  };

  return (
    <div className="min-h-full" style={{ background: 'var(--main-bg)' }}>
      <PageHero
        icon={Layers3}
        title={zh ? '平台注册表' : 'Platform Registry'}
        subtitle={zh ? '查看平台来源、Release、动作映射和设备绑定状态' : 'Review platform source, releases, action mappings, and device bindings'}
        eyebrow={zh ? '自动化平台管理' : 'AUTOMATION PLATFORM MANAGEMENT'}
        accent="#0891b2"
        actions={(
          <button
            type="button"
            onClick={() => void refreshProfiles()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {zh ? '刷新' : 'Refresh'}
          </button>
        )}
      />

      <div className="space-y-5 p-6">
        <div className="flex items-start gap-3 rounded-2xl border border-cyan-100 bg-cyan-50 px-4 py-3 text-xs text-cyan-800">
          <LockKeyhole size={16} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">{zh ? '当前阶段为只读审查模式' : 'Read-only review mode'}</div>
            <div className="mt-0.5 text-cyan-700/80">
              {zh
                ? '本页面不提供创建、编辑、审批、发布和回滚按钮；写入与执行仍由 PLATFORM_REGISTRY_ENABLED 及后端权限共同控制。'
                : 'Create, edit, approval, publish, rollback, and execute controls are intentionally not exposed in this stage.'}
            </div>
          </div>
        </div>

        <div className={`${panelClass} border-amber-100 bg-amber-50/40 px-4 py-3`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-amber-900">
              <ShieldAlert size={15} />
              {zh ? '识别冲突待办' : 'Identification conflict queue'}
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px]">{identificationConflicts.length}</span>
            </div>
            <button type="button" onClick={() => void loadIdentificationConflicts()} disabled={conflictsLoading} className="text-[10px] font-semibold text-amber-800 underline disabled:opacity-50">
              {conflictsLoading ? (zh ? '加载中' : 'Loading') : (zh ? '刷新' : 'Refresh')}
            </button>
          </div>
          {identificationConflicts.length === 0 ? (
            <div className="mt-2 text-[10px] text-amber-800/70">{zh ? '当前没有待处理的同分识别冲突。' : 'No open equal-score identification conflicts.'}</div>
          ) : (
            <div className="mt-2 grid gap-2 lg:grid-cols-2">
              {identificationConflicts.slice(0, 6).map((conflict) => (
                <div key={conflict.id} className="rounded-xl border border-amber-100 bg-white px-3 py-2 text-[10px] text-slate-600">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-slate-800">{conflict.hostname || conflict.device_id}</span>
                    <span className="font-mono text-slate-400">{conflict.site || '-'}</span>
                  </div>
                  <div className="mt-1 text-slate-500">{(conflict.observation_commands || []).join(', ') || '-'}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(conflict.platform_candidates || []).map((candidate) => (
                      <span key={`${conflict.id}-${candidate.platform_profile_id}`} className="rounded-full bg-amber-50 px-1.5 py-0.5 font-mono text-amber-800">
                        {candidate.platform_code || candidate.platform_profile_id || '-'} ({Number(candidate.score || 0).toFixed(2)})
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            { label: zh ? '可见平台' : 'Visible platforms', value: profiles.length, icon: Layers3, tone: 'text-cyan-700 bg-cyan-50' },
            { label: zh ? '就绪平台' : 'Ready platforms', value: readyCount, icon: ShieldCheck, tone: 'text-emerald-700 bg-emerald-50' },
            { label: zh ? '绑定设备' : 'Bound devices', value: boundDeviceCount, icon: Server, tone: 'text-indigo-700 bg-indigo-50' },
            { label: zh ? '在线设备' : 'Online devices', value: onlineDeviceCount, icon: CheckCircle2, tone: 'text-violet-700 bg-violet-50' },
          ].map(({ label, value, icon: Icon, tone }) => (
            <div key={label} className={`${panelClass} flex items-center gap-3 px-4 py-3`}>
              <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${tone}`}><Icon size={17} /></div>
              <div>
                <div className="text-[11px] text-slate-500">{label}</div>
                <div className="text-xl font-bold text-slate-800">{value}</div>
              </div>
            </div>
          ))}
        </div>

        <div className={`${panelClass} flex flex-wrap items-center gap-2 p-3`}>
          <div className="relative min-w-[220px] flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={zh ? '搜索平台、厂商、驱动或解析器' : 'Search platform, vendor, driver, or parser'}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-8 text-xs outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100"
            />
            {search && <button type="button" onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700" aria-label="Clear search"><X size={14} /></button>}
          </div>
          <div className="flex items-center gap-1 text-slate-400"><Filter size={14} /><span className="text-[11px]">{zh ? '筛选' : 'Filters'}</span></div>
          <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none">
            <option value="all">{zh ? '全部来源' : 'All sources'}</option>
            <option value="SYSTEM">SYSTEM</option>
            <option value="CUSTOM">CUSTOM</option>
            <option value="FORKED">FORKED</option>
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none">
            <option value="all">{zh ? '全部状态' : 'All statuses'}</option>
            <option value="ACTIVE">{zh ? '启用' : 'Active'}</option>
            <option value="ARCHIVED">{zh ? '归档' : 'Archived'}</option>
          </select>
          <select value={vendorFilter} onChange={(event) => setVendorFilter(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none">
            <option value="all">{zh ? '全部厂商' : 'All vendors'}</option>
            {vendors.map((vendor) => <option key={vendor} value={vendor}>{vendor}</option>)}
          </select>
          <select value={readinessFilter} onChange={(event) => setReadinessFilter(event.target.value as ReadinessFilter)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none">
            <option value="all">{zh ? '全部就绪度' : 'All readiness'}</option>
            <option value="ready">{zh ? '已就绪' : 'Ready'}</option>
            <option value="degraded">{zh ? '需关注' : 'Needs attention'}</option>
          </select>
        </div>

        {error && (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-xs text-rose-700">
            <span>{error}</span>
            <button type="button" onClick={() => void refreshProfiles()} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button>
          </div>
        )}

        <div className="grid min-h-[560px] gap-5 xl:grid-cols-[minmax(360px,0.9fr)_minmax(520px,1.5fr)]">
          <section className={`${panelClass} overflow-hidden`}>
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-800">{zh ? '平台列表' : 'Platform list'}</h2>
                <p className="mt-0.5 text-[11px] text-slate-400">{zh ? `显示 ${filteredProfiles.length} / ${profiles.length}` : `${filteredProfiles.length} of ${profiles.length} shown`}</p>
              </div>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-500">{zh ? '只读' : 'READ ONLY'}</span>
            </div>
            <div className="max-h-[660px] overflow-y-auto p-2">
              {loading && profiles.length === 0 ? (
                <div className="flex min-h-[220px] items-center justify-center text-slate-400"><Loader2 size={20} className="animate-spin" /></div>
              ) : filteredProfiles.length === 0 ? (
                <div className="px-5 py-16 text-center text-xs text-slate-400">{zh ? '没有匹配的平台' : 'No matching platforms'}</div>
              ) : filteredProfiles.map((profile) => {
                const ready = isReady(profile);
                const selected = profile.id === selectedProfileId;
                return (
                  <button
                    type="button"
                    key={profile.id}
                    onClick={() => selectProfile(profile.id)}
                    className={`mb-1 w-full rounded-xl border px-3 py-3 text-left transition ${selected ? 'border-cyan-200 bg-cyan-50/70 shadow-sm' : 'border-transparent hover:border-slate-200 hover:bg-slate-50'}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-semibold text-slate-800">{displayName(profile, zh)}</span>
                          <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 ${statusClass(profile.source)}`}>{profile.source || '—'}</span>
                        </div>
                        <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{profile.platform_code}</div>
                      </div>
                      {ready ? <ShieldCheck size={16} className="shrink-0 text-emerald-500" /> : <ShieldAlert size={16} className="shrink-0 text-amber-500" />}
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] text-slate-500">
                      <span>{profile.vendor || '—'}</span>
                      <span>{zh ? '设备' : 'Devices'} {Number(profile.bound_device_count || 0)}</span>
                      <span className="text-right">{zh ? '动作' : 'Actions'} {Number(profile.current_action_count || 0)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <section className={`${panelClass} min-w-0 overflow-hidden`}>
            {!currentProfile ? (
              <div className="flex min-h-[500px] items-center justify-center px-5 text-center text-xs text-slate-400">{zh ? '选择一个平台查看详情' : 'Select a platform to view details'}</div>
            ) : (
              <>
                <div className="border-b border-slate-100 px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h2 className="truncate text-lg font-bold text-slate-800">{displayName(currentProfile, zh)}</h2>
                        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ring-1 ${statusClass(currentProfile.source)}`}>{currentProfile.source || '—'}</span>
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-slate-400">{currentProfile.platform_code}</div>
                    </div>
                    <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold ${isReady(currentProfile) ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                      {isReady(currentProfile) ? <CheckCircle2 size={13} /> : <ShieldAlert size={13} />}
                      {isReady(currentProfile) ? (zh ? '注册表就绪' : 'Registry ready') : (zh ? '需要关注' : 'Needs attention')}
                    </div>
                  </div>
                  <div className="mt-4 flex gap-1 overflow-x-auto">
                    {([
                      ['overview', zh ? '基本信息' : 'Overview'],
                      ['mappings', zh ? '命令映射' : 'Command mappings'],
                      ['releases', zh ? '发布记录' : 'Release history'],
                    ] as Array<[DetailTab, string]>).map(([tab, label]) => (
                      <button key={tab} type="button" onClick={() => setDetailTab(tab)} className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition ${detailTab === tab ? 'bg-cyan-600 text-white' : 'text-slate-500 hover:bg-slate-100'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {detailLoading ? (
                  <div className="flex min-h-[420px] items-center justify-center text-slate-400"><Loader2 size={20} className="animate-spin" /></div>
                ) : (
                  <div className="max-h-[660px] overflow-y-auto p-5">
                    {detailTab === 'overview' && (
                      <div className="space-y-5">
                        <div className="grid gap-3 sm:grid-cols-2">
                          {[
                            [zh ? '厂商' : 'Vendor', currentProfile.vendor || '—'],
                            [zh ? '连接驱动' : 'Connection driver', currentProfile.connection_driver || '—'],
                            [zh ? '解析平台' : 'Parser platform', currentProfile.parser_platform || '—'],
                            [zh ? '平台状态' : 'Profile status', statusLabel(currentProfile.status, zh)],
                            [zh ? '当前 Release' : 'Current release', currentProfile.current_release_number ? `v${currentProfile.current_release_number}` : (zh ? '未发布' : 'Not published')],
                            [zh ? '绑定设备' : 'Bound devices', `${Number(currentProfile.bound_device_count || 0)} (${Number(currentProfile.online_device_count || 0)} ${zh ? '在线' : 'online'})`],
                          ].map(([label, value]) => (
                            <div key={label} className="rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-3">
                              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
                              <div className="mt-1 break-all text-xs font-medium text-slate-700">{value}</div>
                            </div>
                          ))}
                        </div>
                        <div className="rounded-xl border border-slate-100 px-4 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs font-semibold text-slate-700">{zh ? '运行健康度（近 7 天）' : 'Runtime health (last 7 days)'}</div>
                            {healthLoading ? <Loader2 size={14} className="animate-spin text-slate-400" /> : (
                              <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${health?.health_status === 'healthy' ? 'bg-emerald-50 text-emerald-700' : health?.health_status === 'critical' ? 'bg-rose-50 text-rose-700' : health?.health_status === 'warning' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>
                                {health?.health_score != null ? `${health.health_score}/100` : (zh ? '暂无运行样本' : 'No runtime sample')}
                              </span>
                            )}
                          </div>
                          {healthError && <div className="mt-2 rounded-lg bg-rose-50 px-2.5 py-2 text-[10px] text-rose-700">{healthError}</div>}
                          <div className="mt-3 grid gap-2 text-[10px] sm:grid-cols-4">
                            {[
                              [zh ? '命令覆盖' : 'Commands', health?.command_coverage_pct == null ? '—' : `${health.command_coverage_pct}%`],
                              [zh ? '模板覆盖' : 'Templates', health?.template_coverage_pct == null ? '—' : `${health.template_coverage_pct}%`],
                              [zh ? '执行成功率' : 'Success', health?.recent_success_rate_pct == null ? '—' : `${health.recent_success_rate_pct}%`],
                              [zh ? '解析失败' : 'Parse failures', health?.recent_parse_failure_count == null ? '—' : `${health.recent_parse_failure_count} (${health.recent_parse_failure_rate_pct || 0}%)`],
                            ].map(([label, value]) => (
                              <div key={label} className="rounded-lg bg-slate-50 px-2.5 py-2"><div className="text-slate-400">{label}</div><div className="mt-1 font-semibold text-slate-700">{value}</div></div>
                            ))}
                          </div>
                          <div className="mt-2 text-[10px] text-slate-400">
                            {zh ? '平均/ P95 延迟' : 'Avg / P95 latency'}：{health?.avg_duration_ms == null ? '—' : `${health.avg_duration_ms}ms / ${health.p95_duration_ms || 0}ms`} · {zh ? '受影响 Playbook' : 'Affected Playbooks'}：{health?.affected_playbook_count ?? '—'}
                          </div>
                          {(health?.failure_queue || []).length > 0 && (
                            <div className="mt-3 border-t border-slate-100 pt-3">
                              <div className="mb-2 text-[10px] font-semibold text-slate-600">{zh ? '失败与未知输出待办' : 'Failure and unknown-output queue'}</div>
                              <div className="space-y-1.5">
                                {(health?.failure_queue || []).slice(0, 5).map((failure) => (
                                  <div key={failure.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-rose-50/60 px-2.5 py-2 text-[10px] text-rose-700">
                                    <span className="font-mono">{failure.action_code || '—'} · {failure.error_code || 'FAILED'}</span>
                                    {failure.raw_output_available && failure.parser_template_version_id && (
                                      <button type="button" onClick={() => void createFailureSample(failure.id)} disabled={sampleRunId === failure.id} className="font-semibold underline disabled:opacity-50">
                                        {sampleRunId === failure.id ? (zh ? '保存中' : 'Saving') : (zh ? '转为脱敏样例' : 'Save redacted sample')}
                                      </button>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                        <div className="rounded-xl border border-slate-100 px-4 py-3">
                          <div className="text-xs font-semibold text-slate-700">{zh ? '平台说明' : 'Description'}</div>
                          <p className="mt-2 text-xs leading-5 text-slate-500">{currentProfile.description || (zh ? '暂无说明' : 'No description')}</p>
                        </div>
                        <div className="rounded-xl border border-slate-100 px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700"><FileCode2 size={15} className="text-cyan-600" />{zh ? '解析模板入口' : 'Parser template entry'}</div>
                            <button type="button" onClick={() => navigate('/automation/textfsm')} className="inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-700 hover:text-cyan-900">{zh ? '查看模板' : 'Open templates'}<ChevronRight size={13} /></button>
                          </div>
                          <p className="mt-2 text-xs text-slate-500">{zh ? '解析平台已绑定到 Release；TextFSM 编辑、测试和结果预览在解析模板模块完成。' : 'The parser platform is bound to the release; editing and regression tests remain in Parse Templates.'}</p>
                        </div>
                      </div>
                    )}

                    {detailTab === 'mappings' && (
                      <div>
                        {actionsError && <div className="mb-3 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-700">{actionsError}</div>}
                        {actionsLoading ? (
                          <div className="flex min-h-[260px] items-center justify-center text-slate-400"><Loader2 size={20} className="animate-spin" /></div>
                        ) : actions.length === 0 ? (
                          <div className="rounded-xl border border-dashed border-slate-200 px-4 py-12 text-center text-xs text-slate-400">{zh ? '暂无可见动作映射，或当前用户没有 command/view 权限。' : 'No visible mappings, or command/view permission is missing.'}</div>
                        ) : (
                          <div className="space-y-2">
                            {actions.map((action) => {
                              const requiredFields = parseJsonList(action.required_fields_json);
                              const consumers = parseJsonList(action.consumers_json);
                              const contract = parseJsonObject(action.field_contract_json);
                              return (
                                <div key={action.action_code} className="rounded-xl border border-slate-100 bg-slate-50/50 p-3">
                                  <div className="flex flex-wrap items-start justify-between gap-2">
                                    <div className="min-w-0">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="font-mono text-xs font-semibold text-slate-800">{action.action_code}</span>
                                        <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 ${action.risk_level === 'sensitive' ? 'bg-amber-50 text-amber-700 ring-amber-100' : 'bg-emerald-50 text-emerald-700 ring-emerald-100'}`}>{action.risk_level || 'low'}</span>
                                        {action.read_only !== false && action.read_only !== 0 && <span className="rounded-full bg-sky-50 px-1.5 py-0.5 text-[9px] font-semibold text-sky-700">{zh ? '只读' : 'Read-only'}</span>}
                                      </div>
                                      <div className="mt-1 text-[11px] text-slate-500">{zh ? action.name_zh || action.name_en : action.name_en || action.name_zh}</div>
                                    </div>
                                    <div className="text-[10px] text-slate-400">{action.timeout_seconds || 30}s / {action.max_records || 0} {zh ? '条' : 'records'}</div>
                                  </div>
                                  <div className="mt-3 grid gap-2 text-[10px] sm:grid-cols-2">
                                    <div className="rounded-lg border border-slate-100 bg-white px-2.5 py-2"><span className="text-slate-400">{zh ? '实际命令' : 'Resolved command'}：</span><code className="break-all text-slate-700">{action.command || (zh ? '未映射' : 'Unmapped')}</code></div>
                                    <div className="rounded-lg border border-slate-100 bg-white px-2.5 py-2"><span className="text-slate-400">{zh ? '解析版本' : 'Parser version'}：</span><span className="break-all text-slate-700">{action.parser_template_version_id || (zh ? '未绑定' : 'Not bound')}</span></div>
                                  </div>
                                  {(requiredFields.length > 0 || consumers.length > 0 || Object.keys(contract).length > 0) && (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      {requiredFields.map((field) => <span key={`field-${field}`} className="rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[9px] text-slate-600">{field}</span>)}
                                      {consumers.map((consumer) => <span key={`consumer-${consumer}`} className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] text-cyan-700">{consumer}</span>)}
                                      {Object.keys(contract).length > 0 && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[9px] text-violet-700">{zh ? '字段契约已配置' : 'Field contract configured'}</span>}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}

                    {detailTab === 'releases' && (
                      <div className="space-y-3">
                        {(currentProfile.releases || []).length === 0 ? (
                          <div className="rounded-xl border border-dashed border-slate-200 px-4 py-12 text-center text-xs text-slate-400">{zh ? '暂无 Release 记录' : 'No release history'}</div>
                        ) : (currentProfile.releases || []).map((release) => (
                          <div key={release.id} className="rounded-xl border border-slate-100 p-4">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex items-center gap-2"><span className="text-sm font-bold text-slate-800">v{release.release_number}</span><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ring-1 ${statusClass(release.status)}`}>{statusLabel(release.status, zh)}</span>{release.id === currentProfile.current_release_id && <span className="rounded-full bg-cyan-50 px-2 py-1 text-[10px] font-semibold text-cyan-700">{zh ? '当前' : 'Current'}</span>}</div>
                              <span className="text-[10px] text-slate-400">{formatDate(release.updated_at || release.created_at, zh)}</span>
                            </div>
                            <div className="mt-3 grid gap-2 text-[10px] text-slate-500 sm:grid-cols-3">
                              <span>{zh ? '驱动' : 'Driver'}：{release.connection_driver}</span>
                              <span>{zh ? '解析器' : 'Parser'}：{release.parser_platform}</span>
                              <span>{zh ? '验证' : 'Validation'}：{statusLabel(release.validation_status, zh)}</span>
                            </div>
                            {release.checksum && <div className="mt-2 break-all font-mono text-[9px] text-slate-400">checksum: {release.checksum}</div>}
                          </div>
                        ))}
                        {currentRelease?.safety_policy_json && (
                          <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-3 text-[10px] text-slate-500">{zh ? '当前安全策略' : 'Current safety policy'}：<code>{JSON.stringify(parseJsonObject(currentRelease.safety_policy_json))}</code></div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
};

export default PlatformRegistryTab;
