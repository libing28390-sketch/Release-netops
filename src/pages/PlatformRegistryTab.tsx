import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  FileCode2,
  Filter,
  Layers3,
  Loader2,
  LockKeyhole,
  Plus,
  RefreshCw,
  Save,
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
  identification_rules?: Array<{
    id: string;
    command?: string;
    match_type?: string;
    pattern?: string;
    logic_group?: string;
    rule_order?: number;
    confidence?: number;
    negate?: number | boolean;
    enabled?: number | boolean;
  }>;
  parser_templates?: Array<{
    id: string;
    platform_code?: string;
    template_code?: string;
    name?: string;
    source?: string;
    status?: string;
    version_count?: number;
  }>;
}

interface RegistryCapabilities {
  write_enabled: boolean;
  allowed_connection_drivers: string[];
  legacy_textfsm_fallback_enabled: boolean;
  legacy_command_catalog_enabled: boolean;
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

interface ParserVersionOption {
  id: string;
  template_id?: string;
  version_number?: number;
  status?: string;
  checksum?: string;
  field_contract_json?: string;
  platform_code?: string;
  template_code?: string;
  name?: string;
  source?: string;
}

type DetailTab = 'overview' | 'mappings' | 'releases' | 'parser' | 'identification';
type ReadinessFilter = 'all' | 'ready' | 'degraded';

interface Props {
  language: string;
  currentUser?: { role?: string; role_profile?: string } | null;
}

interface CreateProfileForm {
  platform_code: string;
  name_zh: string;
  name_en: string;
  vendor: string;
  connection_driver: string;
  parser_platform: string;
  description: string;
}

const EMPTY_CREATE_PROFILE: CreateProfileForm = {
  platform_code: '',
  name_zh: '',
  name_en: '',
  vendor: '',
  connection_driver: '',
  parser_platform: '',
  description: '',
};

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

const sourceLabel = (value: string | undefined, zh: boolean): string => {
  const normalized = String(value || 'CUSTOM').toUpperCase();
  if (!zh) return normalized;
  return ({ SYSTEM: '系统', CUSTOM: '自定义', FORKED: '租户副本' } as Record<string, string>)[normalized] || normalized;
};

const PlatformRegistryTab: React.FC<Props> = ({ language, currentUser }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const requestIdRef = useRef(0);
  const [profiles, setProfiles] = useState<PlatformProfile[]>([]);
  const [capabilities, setCapabilities] = useState<RegistryCapabilities | null>(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(true);
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
  const [parserVersions, setParserVersions] = useState<ParserVersionOption[]>([]);
  const [parserVersionsLoading, setParserVersionsLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>('overview');
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState('');
  const [sampleRunId, setSampleRunId] = useState('');
  const [identificationConflicts, setIdentificationConflicts] = useState<IdentificationConflict[]>([]);
  const [conflictsLoading, setConflictsLoading] = useState(false);
  const [actionReleaseId, setActionReleaseId] = useState('');
  const [editingActionCode, setEditingActionCode] = useState('');
  const [editingCommand, setEditingCommand] = useState('');
  const [editingParserVersionId, setEditingParserVersionId] = useState('');
  const [actionSaving, setActionSaving] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3>(1);
  const [createForm, setCreateForm] = useState<CreateProfileForm>(EMPTY_CREATE_PROFILE);
  const [wizardSaving, setWizardSaving] = useState(false);
  const [wizardError, setWizardError] = useState('');

  const role = String(currentUser?.role || '');
  const roleProfile = String(currentUser?.role_profile || '');
  const canWrite = Boolean(capabilities?.write_enabled) && (
    role === 'Administrator'
    || (!roleProfile && role === 'Operator')
    || ['Platform Maintainer', 'System Administrator'].includes(roleProfile)
  );
  const canReview = Boolean(capabilities?.write_enabled) && (
    role === 'Administrator'
    || ['Release Manager', 'System Administrator'].includes(roleProfile)
  );

  const loadCapabilities = useCallback(async () => {
    setCapabilitiesLoading(true);
    try {
      const response = await apiRequest<ApiEnvelope<RegistryCapabilities>>('/api/platform-registry/capabilities');
      setCapabilities(response.data || null);
    } catch {
      setCapabilities(null);
    } finally {
      setCapabilitiesLoading(false);
    }
  }, []);

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
      return;
    }
    const requestId = ++requestIdRef.current;
    setDetailLoading(true);
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
  }, [zh]);

  const loadActions = useCallback(async (profileId: string, releaseId = '') => {
    if (!profileId) {
      setActions([]);
      return;
    }
    const requestId = requestIdRef.current;
    setActionsLoading(true);
    setActionsError('');
    try {
      const query = releaseId ? `?release_id=${encodeURIComponent(releaseId)}` : '';
      const response = await apiRequest<ApiEnvelope<ActionDefinition[]>>(
        `/api/platform-registry/profiles/${encodeURIComponent(profileId)}/actions${query}`,
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

  const loadParserVersions = useCallback(async (profileId: string) => {
    if (!profileId) {
      setParserVersions([]);
      setParserVersionsLoading(false);
      return;
    }
    setParserVersionsLoading(true);
    try {
      const response = await apiRequest<ApiEnvelope<ParserVersionOption[]>>(
        `/api/platform-registry/profiles/${encodeURIComponent(profileId)}/parser-versions`,
      );
      if (profileId === selectedProfileId) setParserVersions(response.data || []);
    } catch (cause) {
      if (profileId === selectedProfileId) {
        setParserVersions([]);
        setActionsError(cause instanceof Error ? cause.message : (zh ? '可用解析版本加载失败' : 'Failed to load compatible parser versions'));
      }
    } finally {
      if (profileId === selectedProfileId) setParserVersionsLoading(false);
    }
  }, [selectedProfileId, zh]);

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
  useEffect(() => { void loadCapabilities(); }, [loadCapabilities]);
  useEffect(() => { void loadProfile(selectedProfileId); }, [loadProfile, selectedProfileId]);
  useEffect(() => { void loadParserVersions(selectedProfileId); }, [loadParserVersions, selectedProfileId]);
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
  const activeRelease = currentProfile?.releases?.find((release) => release.id === actionReleaseId) || currentRelease;
  const readyCount = profiles.filter(isReady).length;
  const boundDeviceCount = profiles.reduce((total, profile) => total + Number(profile.bound_device_count || 0), 0);
  const onlineDeviceCount = profiles.reduce((total, profile) => total + Number(profile.online_device_count || 0), 0);

  useEffect(() => {
    if (!currentProfile) {
      setActionReleaseId('');
      return;
    }
    const releaseStillExists = Boolean(actionReleaseId && currentProfile.releases?.some((release) => release.id === actionReleaseId));
    if (!releaseStillExists) {
      setActionReleaseId(currentProfile.current_release_id || currentProfile.releases?.[0]?.id || '');
    }
  }, [currentProfile, actionReleaseId]);

  useEffect(() => {
    void loadActions(selectedProfileId, actionReleaseId);
  }, [actionReleaseId, loadActions, selectedProfileId]);

  const selectProfile = (profileId: string) => {
    setSelectedProfileId(profileId);
    setDetailTab('overview');
    setError('');
  };

  const openCreateWizard = () => {
    const firstDriver = capabilities?.allowed_connection_drivers?.[0] || '';
    setCreateForm({ ...EMPTY_CREATE_PROFILE, connection_driver: firstDriver });
    setWizardStep(1);
    setWizardError('');
    setWizardOpen(true);
  };

  const createPlatformProfile = async () => {
    if (!createForm.platform_code.trim() || !createForm.name_en.trim() || !createForm.vendor.trim()) {
      setWizardError(zh ? '请填写平台编码、英文名称和厂商。' : 'Platform code, English name, and vendor are required.');
      return;
    }
    if (!createForm.connection_driver || !createForm.parser_platform.trim()) {
      setWizardError(zh ? '请选择连接驱动并填写解析平台。' : 'Select a connection driver and enter a parser platform.');
      return;
    }
    setWizardSaving(true);
    setWizardError('');
    try {
      const profileResponse = await apiRequest<ApiEnvelope<PlatformProfile>>('/api/platform-registry/profiles', {
        method: 'POST',
        body: JSON.stringify({
          ...createForm,
          platform_code: createForm.platform_code.trim().toLowerCase(),
          parser_platform: createForm.parser_platform.trim().toLowerCase(),
        }),
      });
      const createdProfile = profileResponse.data;
      const releaseResponse = await apiRequest<ApiEnvelope<PlatformRelease>>(
        `/api/platform-registry/profiles/${encodeURIComponent(createdProfile.id)}/releases`,
        { method: 'POST', body: JSON.stringify({ safety_policy: { read_only: true } }) },
      );
      await refreshProfiles();
      setSelectedProfileId(createdProfile.id);
      setActionReleaseId(releaseResponse.data?.id || '');
      setDetailTab('mappings');
      setWizardOpen(false);
    } catch (cause) {
      setWizardError(cause instanceof Error ? cause.message : (zh ? '创建平台失败' : 'Failed to create platform'));
    } finally {
      setWizardSaving(false);
    }
  };

  const createDraftRelease = async () => {
    if (!currentProfile || !canWrite) return;
    try {
      const response = await apiRequest<ApiEnvelope<PlatformRelease>>(
        `/api/platform-registry/profiles/${encodeURIComponent(currentProfile.id)}/releases`,
        { method: 'POST', body: JSON.stringify({ safety_policy: { read_only: true } }) },
      );
      setActionReleaseId(response.data?.id || '');
      await Promise.all([refreshProfiles(), loadProfile(currentProfile.id)]);
      setDetailTab('mappings');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '创建草稿 Release 失败' : 'Failed to create draft release'));
    }
  };

  const saveActionMapping = async (action: ActionDefinition) => {
    if (!activeRelease?.id || !canWrite || activeRelease.status !== 'DRAFT') return;
    setActionSaving(true);
    setActionsError('');
    try {
      await apiRequest(`/api/platform-registry/releases/${encodeURIComponent(activeRelease.id)}/actions/${encodeURIComponent(action.action_code)}`, {
        method: 'PUT',
        body: JSON.stringify({
          command: editingCommand.trim(),
          parser_template_version_id: editingParserVersionId || null,
          field_contract: parseJsonObject(
            parserVersions.find((version) => version.id === editingParserVersionId)?.field_contract_json
              || action.field_contract_json,
          ),
        }),
      });
      setEditingActionCode('');
      setEditingParserVersionId('');
      await loadActions(selectedProfileId, activeRelease.id);
    } catch (cause) {
      setActionsError(cause instanceof Error ? cause.message : (zh ? '保存动作映射失败' : 'Failed to save action mapping'));
    } finally {
      setActionSaving(false);
    }
  };

  const transitionRelease = async (releaseId: string, event: 'validate' | 'submit' | 'approve' | 'publish') => {
    try {
      await apiRequest(event === 'validate'
        ? `/api/platform-registry/releases/${encodeURIComponent(releaseId)}/validate`
        : `/api/platform-registry/releases/${encodeURIComponent(releaseId)}/${event}`, { method: 'POST' });
      setActionReleaseId(releaseId);
      await Promise.all([refreshProfiles(), loadProfile(selectedProfileId)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? 'Release 操作失败' : 'Release operation failed'));
    }
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
          <div className="flex items-center gap-2">
            {canWrite && (
              <button
                type="button"
                onClick={openCreateWizard}
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-700"
              >
                <Plus size={14} />
                {zh ? '新建平台' : 'Create platform'}
              </button>
            )}
            <button
              type="button"
              onClick={() => void refreshProfiles()}
              disabled={loading || capabilitiesLoading}
              className="inline-flex items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </div>
        )}
      />

      {wizardOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="text-base font-bold text-slate-800">{zh ? '新建自定义平台' : 'Create custom platform'}</h2>
                <p className="mt-1 text-[11px] text-slate-500">{zh ? '创建平台档案并自动生成一个只读 Draft Release。' : 'Create the profile and automatically seed a read-only draft release.'}</p>
              </div>
              <button type="button" onClick={() => setWizardOpen(false)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close"><X size={16} /></button>
            </div>
            <div className="grid grid-cols-3 gap-2 px-5 pt-4 text-[10px] font-semibold">
              {[zh ? '平台身份' : 'Identity', zh ? '连接与解析' : 'Connection & parser', zh ? '确认' : 'Review'].map((label, index) => (
                <div key={label} className={`rounded-lg px-2 py-2 text-center ${wizardStep === index + 1 ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-50 text-slate-400'}`}>{index + 1}. {label}</div>
              ))}
            </div>
            <div className="space-y-4 px-5 py-5">
              {wizardError && <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{wizardError}</div>}
              {wizardStep === 1 && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-slate-600">{zh ? '平台编码' : 'Platform code'}<input value={createForm.platform_code} onChange={(event) => setCreateForm((current) => ({ ...current, platform_code: event.target.value }))} placeholder="acme_router" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '厂商' : 'Vendor'}<input value={createForm.vendor} onChange={(event) => setCreateForm((current) => ({ ...current, vendor: event.target.value }))} placeholder="Acme" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '中文名称' : 'Chinese name'}<input value={createForm.name_zh} onChange={(event) => setCreateForm((current) => ({ ...current, name_zh: event.target.value }))} placeholder={zh ? '可选' : 'Optional'} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '英文名称' : 'English name'}<input value={createForm.name_en} onChange={(event) => setCreateForm((current) => ({ ...current, name_en: event.target.value }))} placeholder="Acme Router" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <label className="text-xs font-semibold text-slate-600 sm:col-span-2">{zh ? '平台说明' : 'Description'}<textarea value={createForm.description} onChange={(event) => setCreateForm((current) => ({ ...current, description: event.target.value }))} rows={3} className="mt-1 w-full resize-y rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                </div>
              )}
              {wizardStep === 2 && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-slate-600">{zh ? '连接驱动' : 'Connection driver'}<select value={createForm.connection_driver} onChange={(event) => setCreateForm((current) => ({ ...current, connection_driver: event.target.value }))} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100"><option value="">{zh ? '请选择' : 'Select driver'}</option>{(capabilities?.allowed_connection_drivers || []).map((driver) => <option key={driver} value={driver}>{driver}</option>)}</select></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '解析平台' : 'Parser platform'}<input value={createForm.parser_platform} onChange={(event) => setCreateForm((current) => ({ ...current, parser_platform: event.target.value }))} placeholder="acme_router" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <div className="rounded-xl border border-cyan-100 bg-cyan-50/60 px-3 py-3 text-[11px] leading-5 text-cyan-800 sm:col-span-2">
                    {zh ? '驱动必须来自后端 allowlist；解析模板需要后续在 TextFSM 页面创建、测试并发布后再绑定到动作。' : 'The driver must come from the backend allowlist. Create, test, and publish parser templates before binding them to actions.'}
                  </div>
                </div>
              )}
              {wizardStep === 3 && (
                <div className="space-y-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {[
                      [zh ? '平台编码' : 'Platform code', createForm.platform_code.toLowerCase()],
                      [zh ? '厂商' : 'Vendor', createForm.vendor],
                      [zh ? '英文名称' : 'English name', createForm.name_en],
                      [zh ? '连接驱动' : 'Driver', createForm.connection_driver],
                      [zh ? '解析平台' : 'Parser platform', createForm.parser_platform.toLowerCase()],
                    [zh ? '初始状态' : 'Initial state', zh ? '自定义 / 启用 / 草稿 Release' : 'CUSTOM / ACTIVE / DRAFT release'],
                    ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 px-3 py-2"><div className="text-[10px] text-slate-400">{label}</div><div className="mt-1 break-all text-xs font-semibold text-slate-700">{value || '-'}</div></div>)}
                  </div>
                  <div className="rounded-xl border border-amber-100 bg-amber-50 px-3 py-3 text-[11px] leading-5 text-amber-800">{zh ? '创建不会自动发布或绑定设备；需要完成动作映射、TextFSM 回归和审批流后才可发布。' : 'Creation does not publish the profile or bind devices. Complete action mappings, TextFSM regression, and approval before publishing.'}</div>
                </div>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-5 py-4">
              <button type="button" onClick={() => setWizardOpen(false)} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">{zh ? '取消' : 'Cancel'}</button>
              <div className="flex items-center gap-2">
                {wizardStep > 1 && <button type="button" onClick={() => { setWizardError(''); setWizardStep((step) => (step - 1) as 1 | 2 | 3); }} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">{zh ? '上一步' : 'Back'}</button>}
                {wizardStep < 3 ? (
                  <button type="button" onClick={() => { setWizardError(''); setWizardStep((step) => (step + 1) as 1 | 2 | 3); }} className="rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">{zh ? '下一步' : 'Next'}</button>
                ) : (
                  <button type="button" onClick={() => void createPlatformProfile()} disabled={wizardSaving} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700 disabled:opacity-50">{wizardSaving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}{zh ? '创建平台' : 'Create platform'}</button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-5 p-6">
        <div className="flex items-start gap-3 rounded-2xl border border-cyan-100 bg-cyan-50 px-4 py-3 text-xs text-cyan-800">
          <LockKeyhole size={16} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">{canWrite ? (zh ? '受控写入模式' : 'Controlled write mode') : (zh ? '当前阶段为只读审查模式' : 'Read-only review mode')}</div>
            <div className="mt-0.5 text-cyan-700/80">
              {canWrite
                ? (zh ? '写入操作受 PLATFORM_REGISTRY_ENABLED、角色档案和后端权限共同控制；发布仍需独立审批。' : 'Writes are gated by PLATFORM_REGISTRY_ENABLED, role profile, and backend authorization; publication still requires independent approval.')
                : (zh
                  ? '本页面默认只读；创建、编辑、审批和发布由 PLATFORM_REGISTRY_ENABLED 及后端权限共同控制。'
                  : 'This page is read-only by default; create, edit, approval, and publish controls are gated by PLATFORM_REGISTRY_ENABLED and backend authorization.')}
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
            <option value="SYSTEM">{sourceLabel('SYSTEM', zh)}</option>
            <option value="CUSTOM">{sourceLabel('CUSTOM', zh)}</option>
            <option value="FORKED">{sourceLabel('FORKED', zh)}</option>
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
              <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${canWrite ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-100 text-slate-500'}`}>{canWrite ? (zh ? '受控写入' : 'CONTROLLED WRITE') : (zh ? '只读' : 'READ ONLY')}</span>
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
                          <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 ${statusClass(profile.source)}`}>{sourceLabel(profile.source, zh)}</span>
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
                        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ring-1 ${statusClass(currentProfile.source)}`}>{sourceLabel(currentProfile.source, zh)}</span>
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
                      ['parser', zh ? '解析模板' : 'Parser templates'],
                      ['identification', zh ? '识别规则' : 'Identification rules'],
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

                    {detailTab === 'parser' && (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-xs font-semibold text-slate-700">{zh ? '已绑定解析模板' : 'Bound parser templates'}</div>
                          <button type="button" onClick={() => navigate('/automation/textfsm')} className="inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-700 hover:text-cyan-900">{zh ? '打开 TextFSM' : 'Open TextFSM'}<ChevronRight size={13} /></button>
                        </div>
                        {(currentProfile.parser_templates || []).length === 0 ? (
                          <div className="rounded-xl border border-dashed border-slate-200 px-4 py-12 text-center text-xs text-slate-400">{zh ? '暂无平台级解析模板' : 'No platform-scoped parser templates'}</div>
                        ) : (currentProfile.parser_templates || []).map((template) => (
                          <div key={template.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50/50 px-3 py-3">
                            <div><div className="font-mono text-xs font-semibold text-slate-800">{template.template_code || template.id}</div><div className="mt-1 text-[11px] text-slate-500">{template.name || template.platform_code || '-'}</div></div>
                            <div className="flex items-center gap-2 text-[10px] text-slate-500"><span className={`rounded-full px-2 py-1 font-semibold ring-1 ${statusClass(template.status)}`}>{statusLabel(template.status, zh)}</span><span>{template.version_count || 0} {zh ? '个版本' : 'versions'}</span></div>
                          </div>
                        ))}
                      </div>
                    )}

                    {detailTab === 'identification' && (
                      <div className="space-y-3">
                        <div className="text-xs font-semibold text-slate-700">{zh ? '平台识别规则' : 'Platform identification rules'}</div>
                        {(currentProfile.identification_rules || []).length === 0 ? (
                          <div className="rounded-xl border border-dashed border-slate-200 px-4 py-12 text-center text-xs text-slate-400">{zh ? '暂无识别规则；平台将保持未验证状态。' : 'No identification rules; the platform remains unverified.'}</div>
                        ) : (currentProfile.identification_rules || []).map((rule) => (
                          <div key={rule.id} className="rounded-xl border border-slate-100 bg-slate-50/50 px-3 py-3">
                            <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-slate-800">#{rule.rule_order ?? '-' } {rule.command || '-'}</span><span className="text-[10px] text-slate-500">{rule.match_type || 'regex'} · {Number(rule.confidence || 0).toFixed(2)}</span></div>
                            <div className="mt-2 break-all rounded-lg bg-white px-2.5 py-2 font-mono text-[10px] text-slate-600">{rule.negate ? 'NOT ' : ''}{rule.pattern || '-'}</div>
                            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-400"><span>{rule.logic_group || 'default'}</span><span>{rule.enabled === false || rule.enabled === 0 ? (zh ? '已停用' : 'Disabled') : (zh ? '已启用' : 'Enabled')}</span></div>
                          </div>
                        ))}
                      </div>
                    )}

                    {detailTab === 'mappings' && (
                      <div>
                        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-cyan-100 bg-cyan-50/50 px-3 py-2">
                          <div className="flex items-center gap-2 text-[11px] font-semibold text-cyan-900"><span>{zh ? '编辑 Release' : 'Editing release'}</span><select value={actionReleaseId} onChange={(event) => setActionReleaseId(event.target.value)} className="rounded-lg border border-cyan-200 bg-white px-2 py-1 text-[10px] font-normal text-slate-700 outline-none">{(currentProfile.releases || []).map((release) => <option key={release.id} value={release.id}>v{release.release_number} · {release.status}</option>)}</select></div>
                          {canWrite && <button type="button" onClick={() => void createDraftRelease()} className="inline-flex items-center gap-1 rounded-lg bg-white px-2.5 py-1.5 text-[10px] font-semibold text-cyan-700 ring-1 ring-cyan-200 hover:bg-cyan-50"><Plus size={12} />{zh ? '新建 Draft' : 'New draft'}</button>}
                        </div>
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
                              const boundParserVersion = parserVersions.find((version) => version.id === action.parser_template_version_id);
                              const openParserVersion = (version: ParserVersionOption | undefined) => {
                                if (!version?.template_id) return;
                                navigate(`/automation/textfsm-registry?template_id=${encodeURIComponent(version.template_id)}&version_id=${encodeURIComponent(version.id)}`);
                              };
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
                                    <div className="rounded-lg border border-slate-100 bg-white px-2.5 py-2"><span className="text-slate-400">{zh ? '解析版本' : 'Parser version'}：</span><span className="break-all text-slate-700">{boundParserVersion?.template_code ? `${boundParserVersion.template_code} · v${boundParserVersion.version_number}` : (action.parser_template_version_id || (zh ? '未绑定' : 'Not bound'))}</span>{boundParserVersion?.template_id && <button type="button" onClick={() => openParserVersion(boundParserVersion)} className="ml-2 inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] font-semibold text-cyan-700 hover:bg-cyan-50" title={zh ? '打开解析版本' : 'Open parser version'}><ExternalLink size={11} />{zh ? '打开模板' : 'Open template'}</button>}</div>
                                  </div>
                                  {(requiredFields.length > 0 || consumers.length > 0 || Object.keys(contract).length > 0) && (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      {requiredFields.map((field) => <span key={`field-${field}`} className="rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[9px] text-slate-600">{field}</span>)}
                                      {consumers.map((consumer) => <span key={`consumer-${consumer}`} className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] text-cyan-700">{consumer}</span>)}
                                      {Object.keys(contract).length > 0 && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[9px] text-violet-700">{zh ? '字段契约已配置' : 'Field contract configured'}</span>}
                                    </div>
                                  )}
                                  <div className="mt-2 rounded-lg border border-cyan-100 bg-cyan-50/60 px-2.5 py-2 text-[10px] leading-4 text-cyan-800">
                                    {zh
                                      ? 'Playbook 只保存 action_code；在这里替换解析版本后，需要完成当前 Release 的验证、审批和发布，后续执行才会使用新 TextFSM。'
                                      : 'Playbooks store only the action_code. After replacing the parser here, validate, approve, and publish this Release before future executions use the new TextFSM.'}
                                  </div>
                                  {editingActionCode === action.action_code ? (
                                    <div className="mt-3 flex flex-wrap items-center gap-2">
                                      <input value={editingCommand} onChange={(event) => setEditingCommand(event.target.value)} className="min-w-[240px] flex-1 rounded-lg border border-cyan-200 bg-white px-2.5 py-2 font-mono text-[10px] outline-none focus:ring-2 focus:ring-cyan-100" aria-label={zh ? '动作命令' : 'Action command'} />
                                      <select value={editingParserVersionId} onChange={(event) => setEditingParserVersionId(event.target.value)} disabled={parserVersionsLoading} className="min-w-[190px] rounded-lg border border-cyan-200 bg-white px-2.5 py-2 text-[10px] text-slate-700 outline-none focus:ring-2 focus:ring-cyan-100" aria-label={zh ? `动作 ${action.action_code} 的解析版本` : `Parser version for ${action.action_code}`}>
                                        <option value="">{zh ? '未绑定（使用平台内置解析）' : 'Not bound (use platform parser)'}</option>
                                        {action.parser_template_version_id && !parserVersions.some((version) => version.id === action.parser_template_version_id) && <option value={action.parser_template_version_id} disabled>{zh ? '当前版本不兼容，请替换' : 'Current version is incompatible; replace it'}</option>}
                                        {parserVersions.map((version) => <option key={version.id} value={version.id}>{version.template_code || version.id} · v{version.version_number} · {sourceLabel(version.source, zh)}</option>)}
                                      </select>
                                      {editingParserVersionId && <button type="button" onClick={() => openParserVersion(parserVersions.find((version) => version.id === editingParserVersionId))} disabled={!parserVersions.some((version) => version.id === editingParserVersionId)} className="inline-flex items-center gap-1 rounded-lg border border-cyan-200 bg-white px-2.5 py-2 text-[10px] font-semibold text-cyan-700 disabled:cursor-not-allowed disabled:opacity-40" title={zh ? '打开所选解析版本' : 'Open selected parser version'}><ExternalLink size={11} />{zh ? '打开模板' : 'Open template'}</button>}
                                      <button type="button" onClick={() => void saveActionMapping(action)} disabled={actionSaving} className="inline-flex items-center gap-1 rounded-lg bg-cyan-600 px-2.5 py-2 text-[10px] font-semibold text-white hover:bg-cyan-700 disabled:opacity-50"><Save size={12} />{actionSaving ? (zh ? '保存中' : 'Saving') : (zh ? '保存' : 'Save')}</button>
                                      <button type="button" onClick={() => setEditingActionCode('')} className="rounded-lg px-2.5 py-2 text-[10px] font-semibold text-slate-500 hover:bg-slate-100">{zh ? '取消' : 'Cancel'}</button>
                                    </div>
                                  ) : canWrite && activeRelease?.status === 'DRAFT' ? (
                                    <button type="button" onClick={() => { setEditingActionCode(action.action_code); setEditingCommand(action.command || ''); setEditingParserVersionId(action.parser_template_version_id || ''); }} className="mt-3 inline-flex items-center gap-1 text-[10px] font-semibold text-cyan-700 hover:text-cyan-900"><Save size={12} />{zh ? '编辑命令/解析版本' : 'Edit command/parser'}</button>
                                  ) : null}
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
                            {(canWrite || canReview) && (
                              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                                {canWrite && release.status === 'DRAFT' && <><button type="button" onClick={() => void transitionRelease(release.id, 'validate')} className="rounded-lg bg-white px-2.5 py-1.5 text-[10px] font-semibold text-cyan-700 ring-1 ring-cyan-200 hover:bg-cyan-50">{zh ? '验证' : 'Validate'}</button><button type="button" onClick={() => void transitionRelease(release.id, 'submit')} className="rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-cyan-700">{zh ? '提交审批' : 'Submit'}</button></>}
                                {canReview && release.status === 'IN_REVIEW' && <button type="button" onClick={() => void transitionRelease(release.id, 'approve')} className="rounded-lg bg-amber-500 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-amber-600">{zh ? '批准' : 'Approve'}</button>}
                                {canReview && release.status === 'APPROVED' && <button type="button" onClick={() => void transitionRelease(release.id, 'publish')} className="rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-emerald-700">{zh ? '发布' : 'Publish'}</button>}
                              </div>
                            )}
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
