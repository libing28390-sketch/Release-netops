import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronRight,
  Pencil,
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
  Trash2,
  X,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import PageHero from '../components/PageHero';
import { ActionButton } from '../components/ui/ActionIconButton';
import ResultStatusModal from '../components/ResultStatusModal';
import { apiRequest } from '../api/http';
import { ALL_VENDOR_NAMES } from './AssetManagement/constants';

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
  created_by?: string;
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
    device_id?: string;
    device_hostname?: string | null;
    device_role?: string | null;
    command?: string | null;
    created_at?: string;
    raw_output_available?: boolean;
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
  field_contract_json?: string;
}

const healthErrorLabel = (code: string | undefined, zh: boolean): string => {
  if (!code) return zh ? '执行失败' : 'Failed';
  const labels: Record<string, [string, string]> = {
    CONNECTION_OR_COMMAND_FAILED: ['连接/命令执行失败', 'Connection/command failed'],
    TEMPLATE_NOT_MATCHED: ['解析未匹配', 'Parser did not match'],
    FIELD_CONTRACT_VIOLATION: ['字段契约不满足', 'Field contract violation'],
  };
  return labels[code] ? `${labels[code][zh ? 0 : 1]} (${code})` : code;
};

type DetailTab = 'overview' | 'mappings' | 'releases' | 'parser' | 'identification';
type ReadinessFilter = 'all' | 'ready' | 'degraded';

interface Props {
  language: string;
  currentUser?: { id?: string; username?: string; role?: string; role_profile?: string } | null;
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
    case 'IN_REVIEW':
      return 'bg-amber-50 text-amber-700 ring-amber-100';
    case 'APPROVED':
      return 'bg-cyan-50 text-cyan-700 ring-cyan-100';
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
    PENDING: '待验证', SUBMITTED: '待审批', IN_REVIEW: '审核中', APPROVED: '已批准', FAILED: '失败', ARCHIVED: '已归档', DEPRECATED: '已废弃',
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
  const deepLinkAppliedRef = useRef(false);
  const pendingReleaseSelectionRef = useRef('');
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
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>('overview');
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState('');
  const [identificationConflicts, setIdentificationConflicts] = useState<IdentificationConflict[]>([]);
  const [conflictsLoading, setConflictsLoading] = useState(false);
  const [actionReleaseId, setActionReleaseId] = useState('');
  const [actionSearch, setActionSearch] = useState('');
  const [editingActionCode, setEditingActionCode] = useState('');
  const [editingCommand, setEditingCommand] = useState('');
  const [actionSaving, setActionSaving] = useState(false);
  const [releaseDeleting, setReleaseDeleting] = useState(false);
  const [rejectReleaseId, setRejectReleaseId] = useState('');
  const [rejectReleaseReason, setRejectReleaseReason] = useState('');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardMode, setWizardMode] = useState<'create' | 'edit'>('create');
  const [wizardStep, setWizardStep] = useState<1 | 2>(1);
  const [createForm, setCreateForm] = useState<CreateProfileForm>(EMPTY_CREATE_PROFILE);
  const [wizardSaving, setWizardSaving] = useState(false);
  const [wizardError, setWizardError] = useState('');
  const [profileDeleting, setProfileDeleting] = useState(false);
  const deepLink = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedDetail = params.get('detail');
    return {
      profileId: params.get('profile_id') || '',
      releaseId: params.get('release_id') || '',
      detailTab: requestedDetail === 'mappings' ? 'mappings' as DetailTab : null,
    };
  }, []);

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
  const currentUserKeys = useMemo(
    () => [currentUser?.id, currentUser?.username].filter(Boolean).map(String),
    [currentUser?.id, currentUser?.username],
  );
  const releaseSelfReviewBlocked = (release: PlatformRelease) => Boolean(
    release.created_by && currentUserKeys.includes(String(release.created_by)),
  );
  const releaseWithdrawAllowed = (release: PlatformRelease) => Boolean(
    canWrite
      && release.status === 'IN_REVIEW'
      && currentUserKeys.some((actor) => [release.submitted_by, release.created_by].filter(Boolean).map(String).includes(actor)),
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
      const requestedProfile = deepLink.profileId
        ? nextProfiles.find((item) => item.id === deepLink.profileId)
        : null;
      setSelectedProfileId((current) => (
        deepLink.profileId
          ? (requestedProfile?.id || '')
          : (current && nextProfiles.some((item) => item.id === current) ? current : (nextProfiles[0]?.id || ''))
      ));
      if (deepLink.profileId && !requestedProfile) {
        setError(zh ? `未找到指定的平台 Profile：${deepLink.profileId}` : `Requested platform Profile was not found: ${deepLink.profileId}`);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '平台注册加载失败' : 'Failed to load platform registry'));
    } finally {
      setLoading(false);
    }
  }, [deepLink.profileId, zh]);

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
  useEffect(() => { void loadHealth(selectedProfileId); }, [loadHealth, selectedProfileId]);
  useEffect(() => { void loadIdentificationConflicts(); }, [loadIdentificationConflicts]);

  const vendors = useMemo(
    () => Array.from(new Set(profiles.map((profile) => profile.vendor).filter(Boolean))).sort(),
    [profiles],
  );

  // Vendor identity is selected from the registry catalog rather than typed
  // freely, so custom profiles keep the same canonical vendor spelling as
  // the built-in profiles.  Keep the current value available while editing
  // older/custom data that may no longer be present in the visible list.
  const vendorOptions = useMemo(
    () => Array.from(new Set([...ALL_VENDOR_NAMES, ...vendors, createForm.vendor].filter(Boolean))).sort(),
    [createForm.vendor, vendors],
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
  const isCustomProfile = Boolean(currentProfile)
    && String(currentProfile?.source || '').toUpperCase() !== 'SYSTEM';
  const currentRelease = currentProfile?.releases?.find((release) => release.id === currentProfile.current_release_id)
    || currentProfile?.releases?.[0];
  const activeRelease = currentProfile?.releases?.find((release) => release.id === actionReleaseId) || currentRelease;
  const visibleActions = useMemo(() => {
    const query = actionSearch.trim().toLowerCase();
    if (!query) return actions;
    return actions.filter((action) => [action.action_code, action.name_zh, action.name_en, action.command]
      .some((value) => String(value || '').toLowerCase().includes(query)));
  }, [actionSearch, actions]);
  const readyCount = profiles.filter(isReady).length;
  const boundDeviceCount = profiles.reduce((total, profile) => total + Number(profile.bound_device_count || 0), 0);
  const onlineDeviceCount = profiles.reduce((total, profile) => total + Number(profile.online_device_count || 0), 0);

  useEffect(() => {
    if (!currentProfile) {
      setActionReleaseId('');
      return;
    }
    const releaseStillExists = Boolean(actionReleaseId && currentProfile.releases?.some((release) => release.id === actionReleaseId));
    const pendingReleaseId = pendingReleaseSelectionRef.current;
    const pendingReleaseExists = Boolean(pendingReleaseId && currentProfile.releases?.some((release) => release.id === pendingReleaseId));
    const deepLinkedRelease = deepLink.releaseId && currentProfile.releases?.some((release) => release.id === deepLink.releaseId)
      ? deepLink.releaseId
      : '';
    if (pendingReleaseExists) {
      pendingReleaseSelectionRef.current = '';
      if (actionReleaseId !== pendingReleaseId) setActionReleaseId(pendingReleaseId);
    } else if (deepLinkedRelease && !deepLinkAppliedRef.current) {
      deepLinkAppliedRef.current = true;
      setActionReleaseId(deepLinkedRelease);
    } else if (!releaseStillExists) {
      setActionReleaseId(deepLinkedRelease || currentProfile.current_release_id || currentProfile.releases?.[0]?.id || '');
    }
    if (deepLink.detailTab) setDetailTab(deepLink.detailTab);
  }, [currentProfile, actionReleaseId, deepLink]);

  useEffect(() => {
    void loadActions(selectedProfileId, actionReleaseId);
  }, [actionReleaseId, loadActions, selectedProfileId]);

  const selectProfile = (profileId: string) => {
    const nextProfile = profiles.find((profile) => profile.id === profileId);
    setSelectedProfileId(profileId);
    // Do not reuse the previously selected profile's Release while the
    // detail request is in flight; that transient mismatch used to produce
    // a noisy 404 on the action-mapping endpoint.
    setActionReleaseId(nextProfile?.current_release_id || '');
    setDetailTab('overview');
    setError('');
  };

  const openCreateWizard = () => {
    const firstDriver = capabilities?.allowed_connection_drivers?.[0] || '';
    setWizardMode('create');
    setCreateForm({ ...EMPTY_CREATE_PROFILE, connection_driver: firstDriver });
    setWizardStep(1);
    setWizardError('');
    setWizardOpen(true);
  };

  const openEditWizard = () => {
    if (!currentProfile || !canWrite || String(currentProfile.source || '').toUpperCase() === 'SYSTEM') return;
    setWizardMode('edit');
    setCreateForm({
      platform_code: currentProfile.platform_code || '',
      name_zh: currentProfile.name_zh || '',
      name_en: currentProfile.name_en || '',
      vendor: currentProfile.vendor || '',
      connection_driver: currentProfile.connection_driver || '',
      parser_platform: currentProfile.parser_platform || '',
      description: currentProfile.description || '',
    });
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
      if (wizardMode === 'edit' && currentProfile) {
        await apiRequest<ApiEnvelope<PlatformProfile>>(
          `/api/platform-registry/profiles/${encodeURIComponent(currentProfile.id)}`,
          {
            method: 'PUT',
            body: JSON.stringify({
              ...createForm,
              platform_code: createForm.platform_code.trim().toLowerCase(),
              parser_platform: createForm.parser_platform.trim().toLowerCase(),
            }),
          },
        );
        await Promise.all([refreshProfiles(), loadProfile(currentProfile.id)]);
        setWizardOpen(false);
        return;
      }
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
    if (!currentProfile || !canWrite || !isCustomProfile) return;
    try {
      const response = await apiRequest<ApiEnvelope<PlatformRelease>>(
        `/api/platform-registry/profiles/${encodeURIComponent(currentProfile.id)}/releases`,
        { method: 'POST', body: JSON.stringify({ safety_policy: { read_only: true } }) },
      );
      const draftReleaseId = response.data?.id || '';
      pendingReleaseSelectionRef.current = draftReleaseId;
      setEditingActionCode('');
      setActionsError('');
      await Promise.all([refreshProfiles(), loadProfile(currentProfile.id)]);
      if (draftReleaseId) setActionReleaseId(draftReleaseId);
      setDetailTab('mappings');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '创建草稿 Release 失败' : 'Failed to create draft release'));
    }
  };

  const saveActionMapping = async (action: ActionDefinition) => {
    if (!activeRelease?.id || !canWrite || !isCustomProfile || activeRelease.status !== 'DRAFT') return;
    setActionSaving(true);
    setActionsError('');
    try {
      await apiRequest(`/api/platform-registry/releases/${encodeURIComponent(activeRelease.id)}/actions/${encodeURIComponent(action.action_code)}`, {
        method: 'PUT',
        body: JSON.stringify({
          command: editingCommand.trim(),
          // TextFSM is resolved at execution time by the concrete platform
          // version and exact command; it is not part of a command mapping.
          field_contract: parseJsonObject(action.field_contract_json),
        }),
      });
      setEditingActionCode('');
      await Promise.all([
        loadActions(selectedProfileId, activeRelease.id),
        loadProfile(selectedProfileId),
        refreshProfiles(),
      ]);
    } catch (cause) {
      setActionsError(cause instanceof Error ? cause.message : (zh ? '保存动作映射失败' : 'Failed to save action mapping'));
    } finally {
      setActionSaving(false);
    }
  };

  const deletePlatformProfile = async () => {
    if (!currentProfile || !canWrite || String(currentProfile.source || '').toUpperCase() === 'SYSTEM' || profileDeleting) return;
    const boundDeviceCountForDelete = Number(currentProfile.bound_device_count || 0);
    if (boundDeviceCountForDelete > 0) {
      setError(zh ? `该平台仍绑定 ${boundDeviceCountForDelete} 台设备，不能删除。` : `This platform still has ${boundDeviceCountForDelete} bound device(s) and cannot be deleted.`);
      return;
    }
    const confirmed = window.confirm(
      zh
        ? `确定删除平台“${displayName(currentProfile, zh)}”吗？删除后平台会归档，不能继续用于设备绑定。`
        : `Delete “${displayName(currentProfile, zh)}”? It will be archived and cannot be used for new device bindings.`,
    );
    if (!confirmed) return;
    setProfileDeleting(true);
    setError('');
    try {
      await apiRequest(`/api/platform-registry/profiles/${encodeURIComponent(currentProfile.id)}`, { method: 'DELETE' });
      setSelectedProfile(null);
      setSelectedProfileId('');
      await refreshProfiles();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '删除平台失败' : 'Failed to delete platform'));
    } finally {
      setProfileDeleting(false);
    }
  };

  const deleteDraftRelease = async () => {
    if (!activeRelease?.id || !currentProfile || !canWrite || !isCustomProfile || activeRelease.status !== 'DRAFT' || releaseDeleting) return;
    const confirmed = window.confirm(
      zh
        ? `确定删除 v${activeRelease.release_number} 草稿吗？草稿中的单条命令修改也会一起删除。`
        : `Delete draft v${activeRelease.release_number}? All command changes in this draft will be removed.`,
    );
    if (!confirmed) return;
    setReleaseDeleting(true);
    setError('');
    try {
      await apiRequest(`/api/platform-registry/releases/${encodeURIComponent(activeRelease.id)}`, { method: 'DELETE' });
      setEditingActionCode('');
      setActionReleaseId(currentProfile.current_release_id || '');
      await Promise.all([refreshProfiles(), loadProfile(currentProfile.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '删除草稿 Release 失败' : 'Failed to delete draft release'));
    } finally {
      setReleaseDeleting(false);
    }
  };

  const transitionRelease = async (releaseId: string, event: 'validate' | 'submit' | 'withdraw' | 'approve' | 'reject' | 'publish', reason = '') => {
    if (!currentProfile || !isCustomProfile) return;
    try {
      await apiRequest(event === 'validate'
        ? `/api/platform-registry/releases/${encodeURIComponent(releaseId)}/validate`
        : `/api/platform-registry/releases/${encodeURIComponent(releaseId)}/${event}`, {
          method: 'POST',
          ...(event === 'reject' ? { body: JSON.stringify({ reason }) } : {}),
        });
      setRejectReleaseId('');
      setRejectReleaseReason('');
      setActionReleaseId(releaseId);
      await Promise.all([refreshProfiles(), loadProfile(selectedProfileId)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? 'Release 操作失败' : 'Release operation failed'));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col" style={{ background: 'var(--main-bg)' }}>
      <PageHero
        icon={Layers3}
        title={zh ? '平台注册' : 'Platform Registry'}
        subtitle={zh ? '查看平台来源、Release、动作映射和设备绑定状态' : 'Review platform source, releases, action mappings, and device bindings'}
        eyebrow={zh ? '自动化平台管理' : 'AUTOMATION PLATFORM MANAGEMENT'}
        accent="#0891b2"
        className="!px-4 !pt-3 !pb-3"
        actions={(
          <div className="flex items-center gap-2">
            {canWrite && (
              <button
                type="button"
                onClick={openCreateWizard}
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-700"
              >
                <Plus size={14} />
                {zh ? '新建自定义平台' : 'Create custom platform'}
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
                <h2 className="text-base font-bold text-slate-800">{wizardMode === 'edit' ? (zh ? '编辑自定义平台' : 'Edit custom platform') : (zh ? '新建自定义平台' : 'Create custom platform')}</h2>
                <p className="mt-1 text-[11px] text-slate-500">{wizardMode === 'edit' ? (zh ? '仅自定义平台可编辑；系统内置平台保持只读。' : 'Only custom profiles can be edited; system profiles remain read-only.') : (zh ? '创建平台档案并自动生成一个只读 Draft Release。' : 'Create the profile and automatically seed a read-only draft release.')}</p>
              </div>
              <button type="button" onClick={() => setWizardOpen(false)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close"><X size={16} /></button>
            </div>
            <div className="grid grid-cols-2 gap-2 px-5 pt-4 text-[10px] font-semibold">
              {[zh ? '平台身份' : 'Identity', zh ? '确认' : 'Review'].map((label, index) => (
                <div key={label} className={`rounded-lg px-2 py-2 text-center ${wizardStep === index + 1 ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-50 text-slate-400'}`}>{index + 1}. {label}</div>
              ))}
            </div>
            <div className="space-y-4 px-5 py-5">
              {wizardError && <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{wizardError}</div>}
              {wizardStep === 1 && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-slate-600">{zh ? '平台编码' : 'Platform code'}<input value={createForm.platform_code} onChange={(event) => setCreateForm((current) => ({ ...current, platform_code: event.target.value }))} disabled={wizardMode === 'edit' && Number(currentProfile?.bound_device_count || 0) > 0} placeholder="acme_router" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:cursor-not-allowed disabled:bg-slate-100" /></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '厂商' : 'Vendor'}<select value={createForm.vendor} onChange={(event) => setCreateForm((current) => ({ ...current, vendor: event.target.value }))} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100"><option value="">{zh ? '请选择厂商' : 'Select vendor'}</option>{vendorOptions.map((vendor) => <option key={vendor} value={vendor}>{vendor}</option>)}</select></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '中文名称' : 'Chinese name'}<input value={createForm.name_zh} onChange={(event) => setCreateForm((current) => ({ ...current, name_zh: event.target.value }))} placeholder={zh ? '可选' : 'Optional'} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '英文名称' : 'English name'}<input value={createForm.name_en} onChange={(event) => setCreateForm((current) => ({ ...current, name_en: event.target.value }))} placeholder="Acme Router" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '连接驱动' : 'Connection driver'}<select value={createForm.connection_driver} onChange={(event) => setCreateForm((current) => ({ ...current, connection_driver: event.target.value }))} disabled={wizardMode === 'edit' && Number(currentProfile?.bound_device_count || 0) > 0} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:cursor-not-allowed disabled:bg-slate-100"><option value="">{zh ? '请选择' : 'Select driver'}</option>{(capabilities?.allowed_connection_drivers || []).map((driver) => <option key={driver} value={driver}>{driver}</option>)}</select></label>
                  <label className="text-xs font-semibold text-slate-600">{zh ? '解析平台' : 'Parser platform'}<input value={createForm.parser_platform} onChange={(event) => setCreateForm((current) => ({ ...current, parser_platform: event.target.value }))} disabled={wizardMode === 'edit' && Number(currentProfile?.bound_device_count || 0) > 0} placeholder="acme_router" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:cursor-not-allowed disabled:bg-slate-100" /></label>
                  <div className="rounded-xl border border-cyan-100 bg-cyan-50/60 px-3 py-3 text-[11px] leading-5 text-cyan-800 sm:col-span-2">
                    {zh ? '驱动必须来自后端 allowlist；TextFSM 模板可单独创建，执行时按平台版本和实际命令自动匹配。' : 'The driver must come from the backend allowlist. TextFSM templates are independent and are matched by platform version and exact command at runtime.'}
                  </div>
                  <label className="text-xs font-semibold text-slate-600 sm:col-span-2">{zh ? '平台说明' : 'Description'}<textarea value={createForm.description} onChange={(event) => setCreateForm((current) => ({ ...current, description: event.target.value }))} rows={3} className="mt-1 w-full resize-y rounded-xl border border-slate-200 px-3 py-2 text-xs font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
                </div>
              )}
              {wizardStep === 2 && (
                <div className="space-y-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {[
                      [zh ? '平台编码' : 'Platform code', createForm.platform_code.toLowerCase()],
                      [zh ? '厂商' : 'Vendor', createForm.vendor],
                      [zh ? '英文名称' : 'English name', createForm.name_en],
                      [zh ? '连接驱动' : 'Driver', createForm.connection_driver],
                      [zh ? '解析平台' : 'Parser platform', createForm.parser_platform.toLowerCase()],
                    [zh ? '初始状态' : 'Initial state', wizardMode === 'edit' ? (zh ? '保留当前 Release 和绑定关系' : 'Existing releases and bindings are preserved') : (zh ? '自定义 / 启用 / 草稿 Release' : 'CUSTOM / ACTIVE / DRAFT release')],
                    ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 px-3 py-2"><div className="text-[10px] text-slate-400">{label}</div><div className="mt-1 break-all text-xs font-semibold text-slate-700">{value || '-'}</div></div>)}
                  </div>
                  <div className="rounded-xl border border-amber-100 bg-amber-50 px-3 py-3 text-[11px] leading-5 text-amber-800">{wizardMode === 'edit' ? (zh ? '已绑定设备的平台只允许修改名称、厂商和说明；平台编码、驱动和解析平台会被锁定。' : 'Profiles with bound devices only allow name, vendor, and description edits; platform code, driver, and parser platform are locked.') : (zh ? '创建平台后可直接配置动作命令；TextFSM 不需要注册、发布或审核前置，验证通过即可使用。' : 'After creating a platform, configure action commands directly. TextFSM has no registration, publication, or approval prerequisite; a verified template can be used immediately.')}</div>
                </div>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-5 py-4">
              <button type="button" onClick={() => setWizardOpen(false)} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">{zh ? '取消' : 'Cancel'}</button>
              <div className="flex items-center gap-2">
                {wizardStep > 1 && <button type="button" onClick={() => { setWizardError(''); setWizardStep((step) => (step - 1) as 1 | 2); }} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">{zh ? '上一步' : 'Back'}</button>}
                {wizardStep < 2 ? (
                  <button type="button" onClick={() => { setWizardError(''); setWizardStep((step) => (step + 1) as 1 | 2); }} className="rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">{zh ? '下一步' : 'Next'}</button>
                ) : (
                  <button type="button" onClick={() => void createPlatformProfile()} disabled={wizardSaving} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700 disabled:opacity-50">{wizardSaving ? <Loader2 size={14} className="animate-spin" /> : wizardMode === 'edit' ? <Save size={14} /> : <Plus size={14} />}{wizardMode === 'edit' ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建平台' : 'Create platform')}</button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="space-y-4 p-4 md:p-5">
        <div className="flex items-start gap-3 rounded-2xl border border-cyan-100 bg-cyan-50 px-3 py-2.5 text-xs text-cyan-800">
          <LockKeyhole size={16} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">{canWrite ? (zh ? '受控写入模式' : 'Controlled write mode') : (zh ? '当前阶段为只读审查模式' : 'Read-only review mode')}</div>
            <div className="mt-0.5 text-cyan-700/80">
              {canWrite
                ? (zh ? '自定义平台支持新增、编辑和归档；系统内置平台只读，绑定设备后不能删除；发布仍需独立审批。' : 'Custom platforms support create, edit, and archive; built-in platforms are read-only and bound platforms cannot be deleted; publication still requires independent approval.')
                : (zh
                  ? '本页面默认按角色权限控制；创建、编辑、审批和发布仍需通过后端权限与生命周期校验。'
                  : 'This page is controlled by role permissions; create, edit, approval, and publish still require backend authorization and lifecycle checks.')}
            </div>
          </div>
        </div>

        <div className={`${panelClass} border-amber-100 bg-amber-50/40 px-3 py-2.5`}>
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
            <div key={label} className={`${panelClass} flex items-center gap-3 px-3 py-2.5`}>
              <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${tone}`}><Icon size={17} /></div>
              <div>
                <div className="text-[11px] text-slate-500">{label}</div>
                <div className="text-xl font-bold text-slate-800">{value}</div>
              </div>
            </div>
          ))}
        </div>

        <div className={`${panelClass} flex flex-wrap items-center gap-2 p-2.5`}>
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
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-rose-100 bg-rose-50 px-3 py-2.5 text-xs text-rose-700">
            <span>{error}</span>
            <button type="button" onClick={() => void refreshProfiles()} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button>
          </div>
        )}

        <div className="grid min-h-[440px] gap-4 xl:grid-cols-[minmax(300px,0.65fr)_minmax(0,2fr)]">
          <section className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-800">{zh ? '平台列表' : 'Platform list'}</h2>
                <p className="mt-0.5 text-[11px] text-slate-400">{zh ? `显示 ${filteredProfiles.length} / ${profiles.length}` : `${filteredProfiles.length} of ${profiles.length} shown`}</p>
              </div>
              <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${canWrite ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-100 text-slate-500'}`}>{canWrite ? (zh ? '受控写入' : 'CONTROLLED WRITE') : (zh ? '只读' : 'READ ONLY')}</span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
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

          <section className={`${panelClass} flex min-h-0 min-w-0 flex-col overflow-hidden`}>
            {!currentProfile ? (
              <div className="flex min-h-[500px] items-center justify-center px-5 text-center text-xs text-slate-400">{zh ? '选择一个平台查看详情' : 'Select a platform to view details'}</div>
            ) : (
              <>
                <div className="shrink-0 border-b border-slate-100 px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h2 className="truncate text-lg font-bold text-slate-800">{displayName(currentProfile, zh)}</h2>
                        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ring-1 ${statusClass(currentProfile.source)}`}>{sourceLabel(currentProfile.source, zh)}</span>
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-slate-400">{currentProfile.platform_code}</div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold ${isReady(currentProfile) ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                        {isReady(currentProfile) ? <CheckCircle2 size={13} /> : <ShieldAlert size={13} />}
                        {isReady(currentProfile) ? (zh ? '注册表就绪' : 'Registry ready') : (zh ? '需要关注' : 'Needs attention')}
                      </div>
                      {String(currentProfile.source || '').toUpperCase() === 'SYSTEM' ? (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">{zh ? '系统内置 · 只读' : 'System built-in · read-only'}</span>
                          {canWrite && <>
                            <ActionButton type="button" icon={Pencil} variant="default" size="sm" disabled title={zh ? '系统内置平台不可编辑' : 'Built-in platforms cannot be edited'} className="!h-8 !cursor-not-allowed !px-2.5 !text-[10px]">{zh ? '编辑平台' : 'Edit platform'}</ActionButton>
                            <ActionButton type="button" icon={Trash2} variant="default" size="sm" disabled title={zh ? '系统内置平台不可删除' : 'Built-in platforms cannot be deleted'} className="!h-8 !cursor-not-allowed !px-2.5 !text-[10px]">{zh ? '删除平台' : 'Delete platform'}</ActionButton>
                          </>}
                        </div>
                      ) : canWrite ? (
                        <div className="flex items-center gap-1.5">
                          <ActionButton type="button" icon={Pencil} variant="default" size="sm" onClick={openEditWizard} className="!h-8 !px-2.5 !text-[10px]">{zh ? '编辑平台' : 'Edit platform'}</ActionButton>
                          <ActionButton
                            type="button"
                            icon={Trash2}
                            variant="danger"
                            size="sm"
                            onClick={() => void deletePlatformProfile()}
                            disabled={profileDeleting || Number(currentProfile.bound_device_count || 0) > 0}
                            title={Number(currentProfile.bound_device_count || 0) > 0 ? (zh ? '存在绑定设备，不能删除' : 'Cannot delete while devices are bound') : undefined}
                            className="!h-8 !px-2.5 !text-[10px]"
                          >{profileDeleting ? (zh ? '删除中' : 'Deleting') : (zh ? '删除平台' : 'Delete platform')}</ActionButton>
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {String(currentProfile.source || '').toUpperCase() === 'SYSTEM' && (
                    <div className="mt-3 flex items-start gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] leading-4 text-slate-500">
                      <LockKeyhole size={13} className="mt-0.5 shrink-0" />
                      <span>{zh ? '当前为系统内置平台，只能查看和绑定设备。点击右上角“新建自定义平台”后，选中自定义平台即可使用编辑和归档操作。' : 'This is a built-in platform and is read-only. Use “Create custom platform” above, then select the custom profile to edit or archive it.'}</span>
                    </div>
                  )}
                  <div className="mt-3 flex gap-1 overflow-x-auto">
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
                  <div className="min-h-0 flex-1 overflow-y-auto p-4">
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
                        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-100 bg-amber-50/70 px-3 py-2.5 text-[10px] leading-4 text-amber-900">
                          <span>{zh ? '设备绑定只确定设备归属本 Profile；动作保存实际命令，执行时由设备的具体平台版本和命令精确匹配 TextFSM。没有模板时不改写命令、不跨版本猜测，并保留原始回显。' : 'Device binding only assigns the device to this Profile. Actions store the actual command; execution matches TextFSM by concrete platform version and exact command. Missing templates never rewrite or guess across versions, and raw output is preserved.'}</span>
                          <button type="button" onClick={() => setDetailTab('mappings')} className="shrink-0 font-semibold text-amber-800 underline underline-offset-2 hover:text-amber-950">{zh ? '查看命令映射' : 'View command mappings'}</button>
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
                          <div className="mt-3 grid gap-2 text-[10px] sm:grid-cols-3">
                            {[
                              [zh ? '命令覆盖' : 'Commands', health?.command_coverage_pct == null ? '—' : `${health.command_coverage_pct}%`],
                              [zh ? '执行成功率' : 'Success', health?.recent_success_rate_pct == null ? '—' : `${health.recent_success_rate_pct}%`],
                              [zh ? '解析失败' : 'Parse failures', health?.recent_parse_failure_count == null ? '—' : `${health.recent_parse_failure_count} (${health.recent_parse_failure_rate_pct || 0}%)`],
                            ].map(([label, value]) => (
                              <div key={label} className="rounded-lg bg-slate-50 px-2.5 py-2"><div className="text-slate-400">{label}</div><div className="mt-1 font-semibold text-slate-700">{value}</div></div>
                            ))}
                          </div>
                          <div className="mt-2 text-[10px] text-slate-400">
                            {zh ? '平均/ P95 延迟' : 'Avg / P95 latency'}：{health?.avg_duration_ms == null ? '—' : `${health.avg_duration_ms}ms / ${health.p95_duration_ms || 0}ms`} · {zh ? '受影响 Playbook' : 'Affected Playbooks'}：{health?.affected_playbook_count ?? '—'}
                          </div>
                          <div className="mt-1 text-[9px] text-slate-400">{zh ? '“解析失败”只统计解析阶段错误；连接/命令失败会在下方失败队列单列。' : 'Parse failures count parser-stage errors only; connection/command failures are listed separately below.'}</div>
                          <div className="mt-2 rounded-lg border border-sky-100 bg-sky-50/60 px-2.5 py-2 text-[10px] leading-4 text-sky-800">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span>{zh ? '提示：默认采集设备基本信息；L3 设备额外采集路由表和 BGP 状态，ARP、MAC/VLAN、LLDP 和其他动态协议可按设备单独开启。如果失败来自手动 Playbook、诊断或自定义动作，需在对应任务/设备采集计划中停用该 action。这里的历史失败记录会按保留周期逐步消失。' : 'Note: the default collection plan gathers device basics; L3 devices additionally collect the main route table and BGP state. ARP, MAC/VLAN, LLDP, and other dynamic protocols can be enabled per device. If a failure came from a manual Playbook, diagnosis, or custom action, disable that action in the task or device collection plan; historical failures age out according to retention.'}</span>
                              <button type="button" onClick={() => navigate('/automation/inspections')} className="shrink-0 font-semibold text-sky-800 underline underline-offset-2 hover:text-sky-950">{zh ? '打开设备采集计划' : 'Open collection plans'}</button>
                            </div>
                          </div>
                          {(health?.failure_queue || []).length > 0 && (
                            <div className="mt-3 border-t border-slate-100 pt-3">
                              <div className="mb-2 text-[10px] font-semibold text-slate-600">{zh ? '失败与未知输出待办' : 'Failure and unknown-output queue'}</div>
                              <div className="mb-2 text-[9px] leading-4 text-slate-400">{zh ? '这里展示近 7 天动作遥测；解析未匹配时仍可查看保留的脱敏原始回显，便于补充模板。' : 'This queue shows action telemetry from the last 7 days. An unmatched parse can still expose retained redacted raw output for template improvement.'}</div>
                              <div className="space-y-1.5">
                                {(health?.failure_queue || []).slice(0, 5).map((failure) => (
                                  <div key={failure.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-rose-50/60 px-2.5 py-2 text-[10px] text-rose-700">
                                    <div className="min-w-0">
                                      <div className="font-mono">{failure.action_code || '—'} · {healthErrorLabel(failure.error_code, zh)}</div>
                                      <div className="mt-1 truncate text-[9px] text-rose-500">
                                        {(failure.device_hostname || failure.device_id || (zh ? '未知设备' : 'Unknown device'))}
                                        {failure.device_role ? ` · ${failure.device_role}` : ''}
                                        {failure.failure_stage ? ` · ${failure.failure_stage}` : ''}
                                      </div>
                                      {failure.command && <code className="mt-1 block truncate text-[9px] text-rose-500/80">{failure.command}</code>}
                                    </div>
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
                          <p className="mt-2 text-xs text-slate-500">{zh ? '设备绑定后，解析平台取设备确定的具体版本；模板保存即生效，执行时按具体平台版本和实际命令精确匹配。' : 'After binding, parsing uses the device’s concrete platform version. Saved templates take effect immediately and match by exact platform version and command.'}</p>
                        </div>
                      </div>
                    )}

                    {detailTab === 'parser' && (
                      <div className="space-y-3">
                        <div className="rounded-2xl border border-cyan-100 bg-cyan-50/60 px-4 py-4">
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700"><FileCode2 size={15} className="text-cyan-600" />{zh ? '直接解析模板' : 'Direct parser templates'}</div>
                            <button type="button" onClick={() => navigate('/automation/textfsm')} className="inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-700 hover:text-cyan-900">{zh ? '打开 TextFSM' : 'Open TextFSM'}<ChevronRight size={13} /></button>
                          </div>
                          <p className="mt-2 text-xs leading-5 text-slate-600">{zh ? '这里不再维护模板注册、发布或版本绑定。请在 TextFSM 页面直接创建模板，选择厂商、平台版本和实际命令；保存后立即参与解析。Action 关联是可选项。' : 'Template registration, publication, and version binding are not maintained here. Create a template directly in TextFSM with vendor, platform version, and exact command; it is active immediately. Action association is optional.'}</p>
                        </div>
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
                        <div className="mb-3 rounded-2xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="flex min-w-0 flex-wrap items-center gap-2">
                              <span className="text-[11px] font-semibold text-slate-800">{zh ? '命令映射版本' : 'Command mapping release'}</span>
                              <select value={actionReleaseId} onChange={(event) => { setEditingActionCode(''); setActionReleaseId(event.target.value); }} className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[10px] font-medium text-slate-700 outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100">
                                {(currentProfile.releases || []).map((release) => <option key={release.id} value={release.id}>v{release.release_number} · {statusLabel(release.status, zh)}</option>)}
                              </select>
                              {activeRelease && <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ring-1 ${statusClass(activeRelease.status)}`}>{statusLabel(activeRelease.status, zh)}</span>}
                              <span className="text-[10px] text-slate-400">{zh ? '按单条 action_code 修改并保存' : 'Edit and save one action_code at a time'}</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              {canWrite && isCustomProfile && <button type="button" onClick={() => void createDraftRelease()} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-cyan-700"><Plus size={12} />{zh ? '新建草稿' : 'New draft'}</button>}
                              {canWrite && isCustomProfile && activeRelease?.status === 'DRAFT' && <ActionButton type="button" icon={Trash2} variant="danger" size="sm" onClick={() => void deleteDraftRelease()} disabled={releaseDeleting} className="!h-8 !px-2.5 !text-[10px]">{releaseDeleting ? (zh ? '删除中' : 'Deleting') : (zh ? '删除草稿' : 'Delete draft')}</ActionButton>}
                            </div>
                          </div>
                          {activeRelease?.status === 'DRAFT' && <div className="mt-2 flex items-center gap-1.5 text-[10px] text-cyan-700"><Save size={12} />{zh ? '修改实际命令后，点击动作行内的“保存命令”；TextFSM 不需要在这里单独绑定。' : 'Edit the exact command and use the row “Save command” button; TextFSM does not need a separate binding here.'}</div>}
                        </div>
                        {actionsError && <div className="mb-3 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-700">{actionsError}</div>}
                        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-2 text-[10px] leading-4 text-slate-600">
                          <span>{zh ? 'Playbook 只保存 action_code；Release 发布的是平台映射快照，未修改的命令会从已发布版本带入。未绑定时不会改写命令或回退到其他模板。' : 'Playbooks store only action_code. A release publishes the platform mapping snapshot; unchanged commands are carried forward. Unbound actions never rewrite commands or fall back to another template.'}</span>
                          <label className="relative min-w-[220px] flex-1 sm:max-w-xs">
                            <Search size={12} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                            <input value={actionSearch} onChange={(event) => setActionSearch(event.target.value)} placeholder={zh ? '筛选 action_code / 命令' : 'Filter action_code / command'} className="w-full rounded-lg border border-slate-200 bg-white px-7 py-1.5 text-[10px] text-slate-700 outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" />
                          </label>
                        </div>
                        {actionsLoading ? (
                          <div className="flex min-h-[260px] items-center justify-center text-slate-400"><Loader2 size={20} className="animate-spin" /></div>
                        ) : visibleActions.length === 0 ? (
                          <div className="rounded-xl border border-dashed border-slate-200 px-4 py-12 text-center text-xs text-slate-400">{zh ? '暂无可见动作映射，或当前用户没有 command/view 权限。' : 'No visible mappings, or command/view permission is missing.'}</div>
                        ) : (
                          <div className="space-y-2">
                            {visibleActions.map((action) => {
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
                                    <div className="rounded-lg border border-slate-100 bg-white px-2.5 py-2">
                                      <span className="text-slate-400">{zh ? 'TextFSM 解析' : 'TextFSM parsing'}：</span>
                                      <span className="font-medium text-cyan-700">{zh ? '按平台版本 + 实际命令自动匹配' : 'Automatic match by platform version + exact command'}</span>
                                      <div className="mt-1 text-[10px] leading-4 text-slate-400">{zh ? '模板可在 TextFSM 页面直接创建；没有匹配模板时仍保留原始回显。' : 'Create templates directly in TextFSM; unmatched responses still keep the raw CLI output.'}</div>
                                    </div>
                                  </div>
                                  {(requiredFields.length > 0 || consumers.length > 0 || Object.keys(contract).length > 0) && (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      {requiredFields.map((field) => <span key={`field-${field}`} className="rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[9px] text-slate-600">{field}</span>)}
                                      {consumers.map((consumer) => <span key={`consumer-${consumer}`} className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] text-cyan-700">{consumer}</span>)}
                                      {Object.keys(contract).length > 0 && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[9px] text-violet-700">{zh ? '字段契约已配置' : 'Field contract configured'}</span>}
                                    </div>
                                  )}
                                  {editingActionCode === action.action_code ? (
                                    <div className="mt-3 flex flex-wrap items-center gap-2">
                                      <input value={editingCommand} onChange={(event) => setEditingCommand(event.target.value)} className="min-w-[240px] flex-1 rounded-lg border border-cyan-200 bg-white px-2.5 py-2 font-mono text-[10px] outline-none focus:ring-2 focus:ring-cyan-100" aria-label={zh ? '动作命令' : 'Action command'} />
                                      <button type="button" onClick={() => void saveActionMapping(action)} disabled={actionSaving} className="inline-flex items-center gap-1 rounded-lg bg-cyan-600 px-2.5 py-2 text-[10px] font-semibold text-white hover:bg-cyan-700 disabled:opacity-50"><Save size={12} />{actionSaving ? (zh ? '保存中' : 'Saving') : (zh ? '保存命令' : 'Save command')}</button>
                                      <button type="button" onClick={() => setEditingActionCode('')} className="rounded-lg px-2.5 py-2 text-[10px] font-semibold text-slate-500 hover:bg-slate-100">{zh ? '取消' : 'Cancel'}</button>
                                    </div>
                                  ) : canWrite && isCustomProfile && activeRelease?.status === 'DRAFT' ? (
                                    <button type="button" aria-label={zh ? '编辑动作命令' : 'Edit action command'} onClick={() => { setEditingActionCode(action.action_code); setEditingCommand(action.command || ''); }} className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-[10px] font-semibold text-cyan-700 transition hover:border-cyan-400 hover:bg-cyan-50"><Save size={12} />{zh ? '编辑此动作命令' : 'Edit this action command'}</button>
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
                            {((canWrite && isCustomProfile) || (canReview && isCustomProfile)) && (
                              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                                {canWrite && isCustomProfile && release.status === 'DRAFT' && <><button type="button" onClick={() => void transitionRelease(release.id, 'validate')} className="rounded-lg bg-white px-2.5 py-1.5 text-[10px] font-semibold text-cyan-700 ring-1 ring-cyan-200 hover:bg-cyan-50">{zh ? '验证' : 'Validate'}</button><button type="button" onClick={() => void transitionRelease(release.id, 'submit')} className="rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-cyan-700">{zh ? '提交审批' : 'Submit'}</button></>}
                                {releaseWithdrawAllowed(release) && <button type="button" onClick={() => void transitionRelease(release.id, 'withdraw')} className="rounded-lg bg-white px-2.5 py-1.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200 hover:bg-amber-50">{zh ? '撤回到草稿' : 'Withdraw'}</button>}
                                {canReview && isCustomProfile && release.status === 'IN_REVIEW' && <><button type="button" onClick={() => { setRejectReleaseReason(''); setRejectReleaseId(release.id); }} disabled={releaseSelfReviewBlocked(release)} title={releaseSelfReviewBlocked(release) ? (zh ? '创建人不能审核自己的 Release，请由另一位具备审批权限的管理员处理。' : 'The creator cannot review their own Release; ask another authorized reviewer.') : undefined} className="rounded-lg bg-white px-2.5 py-1.5 text-[10px] font-semibold text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50">{zh ? '驳回' : 'Reject'}</button><button type="button" onClick={() => void transitionRelease(release.id, 'approve')} disabled={releaseSelfReviewBlocked(release)} title={releaseSelfReviewBlocked(release) ? (zh ? '创建人不能审核自己的 Release，请由另一位具备审批权限的管理员处理。' : 'The creator cannot review their own Release; ask another authorized reviewer.') : undefined} className="rounded-lg bg-amber-500 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-50">{zh ? '批准' : 'Approve'}</button>{releaseSelfReviewBlocked(release) && <span className="self-center text-[10px] text-rose-600">{zh ? '创建人不能自审批' : 'Creator cannot self-review'}</span>}</>}
                                {canReview && isCustomProfile && release.status === 'APPROVED' && <button type="button" onClick={() => void transitionRelease(release.id, 'publish')} className="rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-emerald-700">{zh ? '发布' : 'Publish'}</button>}
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
      <ResultStatusModal
        open={Boolean(rejectReleaseId)}
        onClose={() => setRejectReleaseId('')}
        title={zh ? '驳回 Release' : 'Reject release'}
        closeTitle={zh ? '关闭驳回窗口' : 'Close rejection dialog'}
        icon={ShieldAlert}
        iconClassName="bg-rose-100 text-rose-700"
        headerClassName="border-b border-rose-100 bg-rose-50/70"
        panelClassName="w-full max-w-lg rounded-2xl border border-rose-100 bg-white shadow-2xl"
        bodyClassName="p-5"
      >
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (rejectReleaseId) void transitionRelease(rejectReleaseId, 'reject', rejectReleaseReason.trim()); }}>
          <p className="text-xs leading-5 text-slate-600">{zh ? '驳回后 Release 会退回草稿，提交人可以修改动作映射后再次提交。原因会记录在审计日志中。' : 'The release returns to DRAFT so its submitter can correct the mappings. The reason is stored in the audit log.'}</p>
          <label className="block text-xs font-semibold text-slate-700">
            {zh ? '驳回原因（可选）' : 'Rejection reason (optional)'}
            <textarea value={rejectReleaseReason} onChange={(event) => setRejectReleaseReason(event.target.value)} maxLength={2000} autoFocus className="mt-1 min-h-28 w-full resize-y rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-rose-400 focus:ring-2 focus:ring-rose-100" />
          </label>
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={() => setRejectReleaseId('')} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">{zh ? '取消' : 'Cancel'}</button>
            <button type="submit" className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-700">{zh ? '确认驳回' : 'Confirm rejection'}</button>
          </div>
        </form>
      </ResultStatusModal>
    </div>
  );
};

export default PlatformRegistryTab;
