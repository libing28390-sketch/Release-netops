import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileCode2,
  GitBranch,
  Loader2,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from 'lucide-react';
import { ApiError, apiRequest } from '../api/http';
import ResultStatusModal from '../components/ResultStatusModal';

interface Props {
  language: string;
  currentUser?: { role?: string; role_profile?: string } | null;
}

interface TemplateRecord {
  id: string;
  tenant_id?: string | null;
  platform_profile_id?: string | null;
  platform_code: string;
  template_code: string;
  name?: string;
  source?: string;
  status?: string;
  lock_version?: number;
}

interface VersionRecord {
  id: string;
  version_number: number;
  status: string;
  content: string;
  lock_version?: number;
  field_contract_json?: string;
  test_summary_json?: string;
  submitted_by?: string;
  approved_by?: string;
  published_by?: string;
}

interface TestSummary {
  passed?: boolean;
  record_count?: number;
  fields?: string[];
  field_coverage?: Record<string, number>;
  field_contract?: Record<string, unknown>;
  duration_ms?: number;
  tested_at?: string;
  regression_count?: number;
}

interface TestResult {
  version_id?: string | null;
  records: Array<Record<string, unknown>>;
  fields: string[];
  count?: number;
  summary?: TestSummary;
}

interface SampleRecord {
  id: string;
  sample_name: string;
  expected_records_json?: string;
  checksum?: string;
  created_by?: string;
  created_at?: string;
  raw_output_expires_at?: string;
}

interface ImpactRecord {
  action_count?: number;
  release_count?: number;
  profile_count?: number;
  device_count?: number;
  playbook_count?: number;
  version_count?: number;
}

interface AuditRecord {
  id: string;
  event_type: string;
  actor_username?: string;
  metadata_json?: string;
  created_at?: string;
}

interface ListMeta {
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

interface PlatformProfileOption {
  id: string;
  platform_code: string;
  parser_platform?: string;
  name_zh?: string;
  name_en?: string;
  vendor?: string;
  source?: string;
}

interface ParserCapabilities {
  write_enabled: boolean;
  read_only_sandbox_enabled: boolean;
}

interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  meta?: Partial<ListMeta>;
  message?: string;
}

type DiffRow = { type: 'context' | 'added' | 'removed'; text: string };

const panelClass = 'rounded-2xl border border-black/5 bg-white shadow-sm';
const defaultContent = `Value FIELD (.*)

Start
  ^\${FIELD} -> Record
`;

const TEXTFSM_KEYWORDS = /^(Value|Start|EOF|Record|Continue|Clear|Error|Filldown|Fillup|List|Required|Key)\b/;

const highlightedTextFSM = (value: string): React.ReactNode[] => value.split('\n').map((line, index) => {
  const trimmed = line.trimStart();
  if (trimmed.startsWith('#')) return <div key={`line-${index}`} className="h-5 whitespace-pre text-slate-500">{line || ' '}</div>;
  const keyword = trimmed.match(TEXTFSM_KEYWORDS)?.[0];
  if (keyword) {
    const prefix = line.slice(0, line.length - trimmed.length);
    return <div key={`line-${index}`} className="h-5 whitespace-pre"><span className="text-slate-400">{prefix}</span><span className="text-cyan-300">{keyword}</span><span className="text-slate-200">{trimmed.slice(keyword.length) || ' '}</span></div>;
  }
  if (trimmed.includes('->')) {
    const arrow = line.indexOf('->');
    return <div key={`line-${index}`} className="h-5 whitespace-pre"><span className="text-amber-200">{line.slice(0, arrow)}</span><span className="text-fuchsia-300">-&gt;</span><span className="text-emerald-300">{line.slice(arrow + 2) || ' '}</span></div>;
  }
  return <div key={`line-${index}`} className="h-5 whitespace-pre text-slate-200">{line || ' '}</div>;
});

const parseJsonObject = (value?: string): Record<string, unknown> => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};

const parseSummary = (value?: string): TestSummary => {
  const parsed = parseJsonObject(value);
  return parsed as TestSummary;
};

const buildLineDiff = (before: string, after: string): DiffRow[] => {
  const oldLines = before.split('\n');
  const newLines = after.split('\n');
  const rows: DiffRow[] = [];
  const limit = Math.max(oldLines.length, newLines.length);
  for (let index = 0; index < limit; index += 1) {
    const oldLine = oldLines[index];
    const newLine = newLines[index];
    if (oldLine === newLine) rows.push({ type: 'context', text: oldLine || '' });
    else {
      if (oldLine !== undefined) rows.push({ type: 'removed', text: oldLine });
      if (newLine !== undefined) rows.push({ type: 'added', text: newLine });
    }
  }
  return rows;
};

const formatDate = (value: string | undefined, zh: boolean): string => {
  if (!value) return zh ? '暂无' : '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const sourceLabel = (source: string | undefined, zh: boolean): string => {
  const normalized = String(source || 'CUSTOM').toUpperCase();
  if (!zh) return normalized;
  return ({ SYSTEM: '系统', CUSTOM: '自定义', FORKED: '租户副本' } as Record<string, string>)[normalized] || normalized;
};

const errorMessage = (cause: unknown, fallback: string, zh = false): string => {
  if (cause instanceof ApiError) {
    const detail = cause.detail;
    const code = detail && typeof detail === 'object' && 'code' in detail
      ? String((detail as { code?: unknown }).code || '')
      : '';
    if (code === 'SYSTEM_TEMPLATE_IMMUTABLE') {
      const message = zh
        ? '系统解析版本为只读，不能废弃或回滚。请先复制为租户副本。'
        : 'SYSTEM parser versions are read-only and cannot be deprecated or rolled back. Fork a tenant template first.';
      return cause.requestId ? `${message} (Request ID: ${cause.requestId})` : message;
    }
    if (zh && code === 'PARSER_TEMPLATE_IN_USE') return '模板已被平台 Release 引用，请先替换命令映射再删除。';
    if (zh && code === 'PARSER_TEMPLATE_DELETE_BLOCKED') return '模板存在已审批或已发布版本，不能直接删除。';
    if (zh && code === 'PARSER_TEMPLATE_CONFLICT') return '模板已被其他人修改，请刷新后再保存。';
    return cause.message;
  }
  return cause instanceof Error ? cause.message : fallback;
};

const ParserRegistryTab: React.FC<Props> = ({ language, currentUser }) => {
  const zh = language === 'zh';
  const role = String(currentUser?.role || '');
  const roleProfile = String(currentUser?.role_profile || '');
  const isAdmin = role === 'Administrator';
  const roleCanEdit = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);
  const roleCanReview = isAdmin || ['Release Manager', 'System Administrator'].includes(roleProfile);
  const roleCanTest = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);
  const roleCanSample = roleCanEdit || isAdmin;
  const roleCanDelete = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);

  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
  const [platformProfiles, setPlatformProfiles] = useState<PlatformProfileOption[]>([]);
  const [capabilities, setCapabilities] = useState<ParserCapabilities | null>(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(true);
  const [capabilitiesError, setCapabilitiesError] = useState('');
  const [meta, setMeta] = useState<ListMeta>({ total: 0, page: 1, page_size: 50, pages: 0 });
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [samples, setSamples] = useState<SampleRecord[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [impact, setImpact] = useState<ImpactRecord | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [compareVersionId, setCompareVersionId] = useState('');
  const [newMode, setNewMode] = useState(false);
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [forking, setForking] = useState(false);
  const [forkModalOpen, setForkModalOpen] = useState(false);
  const [forkCode, setForkCode] = useState('');
  const [forkName, setForkName] = useState('');
  const [forkModalError, setForkModalError] = useState('');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteModalError, setDeleteModalError] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [regressionTesting, setRegressionTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [platformCode, setPlatformCode] = useState('cisco_ios');
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [templateCode, setTemplateCode] = useState('CUSTOM_TEMPLATE');
  const [templateName, setTemplateName] = useState('');
  const [content, setContent] = useState(defaultContent);
  const [contract, setContract] = useState('{}');
  const [sampleOutput, setSampleOutput] = useState('');
  const [sampleName, setSampleName] = useState('editor-sample');
  const [expectedRecords, setExpectedRecords] = useState('[]');
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [editorScrollLeft, setEditorScrollLeft] = useState(0);
  const [editorScrollTop, setEditorScrollTop] = useState(0);

  const deepLink = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return {
      templateId: params.get('template_id') || '',
      versionId: params.get('version_id') || '',
    };
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) || null,
    [selectedTemplateId, templates],
  );
  const selectedVersion = useMemo(
    () => versions.find((item) => item.id === selectedVersionId) || null,
    [selectedVersionId, versions],
  );
  const compareVersion = useMemo(
    () => versions.find((item) => item.id === compareVersionId && item.id !== selectedVersionId)
      || versions.find((item) => item.id !== selectedVersionId)
      || null,
    [compareVersionId, selectedVersionId, versions],
  );
  const isSystemTemplate = selectedTemplate?.source === 'SYSTEM';
  const isMutableDraft = Boolean(selectedVersion && selectedVersion.status === 'DRAFT' && !isSystemTemplate && !newMode);
  const editorLineNumbers = useMemo(() => content.split('\n').map((_, index) => index + 1), [content]);
  const sourceDiff = useMemo(() => buildLineDiff(compareVersion?.content || '', content), [compareVersion?.content, content]);
  const currentSummary = testResult?.summary || parseSummary(selectedVersion?.test_summary_json);
  const compareSummary = parseSummary(compareVersion?.test_summary_json);
  const currentFields = new Set(testResult?.fields || currentSummary.fields || []);
  const compareFields = new Set(compareSummary.fields || []);
  const addedFields = Array.from(currentFields).filter((field) => !compareFields.has(field));
  const removedFields = Array.from(compareFields).filter((field) => !currentFields.has(field));
  const writeEnabled = capabilities?.write_enabled === true;
  const readOnlySandboxEnabled = !capabilitiesLoading && capabilities?.read_only_sandbox_enabled !== false;
  const canWrite = writeEnabled && roleCanEdit;
  const canEdit = canWrite;
  const canDelete = writeEnabled && roleCanDelete;
  // A published tenant version can seed a new draft, but its identity/scope
  // remains immutable until a draft exists.
  const canEditCurrent = canWrite && (newMode || Boolean(selectedVersion && !isSystemTemplate));
  const canEditMetadata = canWrite && (newMode || isMutableDraft);
  const canReview = writeEnabled && roleCanReview;
  const canSample = writeEnabled && roleCanSample;
  const canTest = roleCanTest && (isSystemTemplate ? readOnlySandboxEnabled : writeEnabled);

  const selectedPlatformProfile = useMemo(
    () => platformProfiles.find((profile) => profile.id === selectedProfileId) || null,
    [platformProfiles, selectedProfileId],
  );
  const profileOptions = useMemo(() => {
    if (newMode) return platformProfiles;
    return platformProfiles.filter((profile) => profile.parser_platform === platformCode || profile.platform_code === platformCode);
  }, [newMode, platformCode, platformProfiles]);

  const resetFeedback = () => {
    setError('');
    setMessage('');
  };

  const loadCapabilities = useCallback(async () => {
    setCapabilitiesLoading(true);
    setCapabilitiesError('');
    try {
      const response = await apiRequest<ApiEnvelope<ParserCapabilities>>('/api/parser-templates/capabilities');
      setCapabilities(response.data || null);
    } catch (cause) {
      setCapabilities(null);
      setCapabilitiesError(errorMessage(cause, zh ? '功能开关状态读取失败，已关闭写入操作' : 'Could not read feature gate; writes are disabled'));
    } finally {
      setCapabilitiesLoading(false);
    }
  }, [zh]);

  const loadPlatformProfiles = useCallback(async () => {
    try {
      const response = await apiRequest<ApiEnvelope<PlatformProfileOption[]>>('/api/platform-registry/profiles');
      setPlatformProfiles(response.data || []);
    } catch {
      // Template editing remains available for legacy/unscoped records. A new
      // controlled template will surface a clear profile-required error.
      setPlatformProfiles([]);
    }
  }, []);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(meta.page_size), search, source: sourceFilter, status: statusFilter });
      const response = await apiRequest<ApiEnvelope<TemplateRecord[]>>(`/api/parser-templates?${params.toString()}`);
      const next = response.data || [];
      setTemplates(next);
      setMeta({
        total: Number(response.meta?.total || 0),
        page: Number(response.meta?.page || page),
        page_size: Number(response.meta?.page_size || meta.page_size),
        pages: Number(response.meta?.pages || 0),
      });
      if (!newMode) {
        setSelectedTemplateId((current) => current && next.some((item) => item.id === current)
          ? current
          : (next.find((item) => item.id === deepLink.templateId)?.id || next[0]?.id || ''));
      }
    } catch (cause) {
      setError(errorMessage(cause, zh ? '模板列表加载失败' : 'Failed to load parser templates'));
    } finally {
      setLoading(false);
    }
  }, [deepLink.templateId, meta.page_size, newMode, page, search, sourceFilter, statusFilter, zh]);

  const loadVersions = useCallback(async (templateId: string) => {
    if (!templateId) return;
    setDetailsLoading(true);
    try {
      const response = await apiRequest<ApiEnvelope<VersionRecord[]>>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`);
      const next = response.data || [];
      setVersions(next);
      setSelectedVersionId((current) => current && next.some((item) => item.id === current)
        ? current
        : (next.find((item) => item.id === deepLink.versionId)?.id || next[0]?.id || ''));
    } catch (cause) {
      setError(errorMessage(cause, zh ? '版本加载失败' : 'Failed to load versions'));
    } finally {
      setDetailsLoading(false);
    }
  }, [deepLink.versionId, zh]);

  const loadVersionDetails = useCallback(async (versionId: string) => {
    if (!versionId) {
      setSamples([]);
      return;
    }
    try {
      const [sampleResponse, impactResponse, auditResponse] = await Promise.all([
        apiRequest<ApiEnvelope<SampleRecord[]>>(`/api/parser-templates/versions/${encodeURIComponent(versionId)}/samples`),
        selectedTemplateId ? apiRequest<ApiEnvelope<ImpactRecord>>(`/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/impact`) : Promise.resolve(null),
        selectedTemplateId ? apiRequest<ApiEnvelope<AuditRecord[]>>(`/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/audit?limit=50`) : Promise.resolve(null),
      ]);
      setSamples(sampleResponse?.data || []);
      setImpact(impactResponse?.data || null);
      setAudit(auditResponse?.data || []);
    } catch (cause) {
      // Metadata is useful but should not hide the editor if an older install lacks one endpoint.
      setSamples([]);
      setAudit([]);
      setImpact(null);
      if (cause instanceof ApiError && cause.status >= 500) setError(errorMessage(cause, zh ? '模板元数据加载失败' : 'Failed to load template metadata'));
    }
  }, [selectedTemplateId, zh]);

  useEffect(() => { void loadCapabilities(); }, [loadCapabilities]);
  useEffect(() => { void loadPlatformProfiles(); }, [loadPlatformProfiles]);

  useEffect(() => {
    if (!platformProfiles.length || selectedProfileId) return;
    const matching = platformProfiles.find((profile) => profile.parser_platform === platformCode);
    if (matching) setSelectedProfileId(matching.id);
  }, [platformCode, platformProfiles, selectedProfileId]);

  useEffect(() => { void loadTemplates(); }, [loadTemplates]);

  useEffect(() => {
    if (selectedTemplateId && !newMode) void loadVersions(selectedTemplateId);
    else {
      setVersions([]);
      setSelectedVersionId('');
      setSamples([]);
      setImpact(null);
      setAudit([]);
    }
  }, [loadVersions, newMode, selectedTemplateId]);

  useEffect(() => {
    if (selectedVersionId && !newMode) void loadVersionDetails(selectedVersionId);
  }, [loadVersionDetails, newMode, selectedVersionId]);

  useEffect(() => {
    if (!selectedVersion || newMode) return;
    setContent(selectedVersion.content || '');
    setContract(JSON.stringify(parseJsonObject(selectedVersion.field_contract_json), null, 2));
    setTestResult(null);
  }, [newMode, selectedVersion]);

  useEffect(() => {
    if (!selectedTemplateId || newMode) return;
    const template = templates.find((item) => item.id === selectedTemplateId);
    if (!template) return;
    setPlatformCode(template.platform_code);
    setTemplateCode(template.template_code);
    setTemplateName(template.name || template.template_code);
    const matchingProfile = platformProfiles.find((profile) => profile.id === template.platform_profile_id)
      || platformProfiles.find((profile) => profile.parser_platform === template.platform_code);
    setSelectedProfileId(matchingProfile?.id || '');
  }, [newMode, platformProfiles, selectedTemplateId, templates]);

  const startNewTemplate = () => {
    if (!canWrite) return;
    resetFeedback();
    setNewMode(true);
    setSelectedTemplateId('');
    setSelectedVersionId('');
    setVersions([]);
    setSamples([]);
    setImpact(null);
    setAudit([]);
    const defaultProfile = platformProfiles.find((profile) => profile.parser_platform === 'cisco_ios') || platformProfiles[0];
    setSelectedProfileId(defaultProfile?.id || '');
    setPlatformCode(defaultProfile?.parser_platform || 'cisco_ios');
    setTemplateCode('CUSTOM_TEMPLATE');
    setTemplateName('');
    setContent(defaultContent);
    setContract('{}');
    setTestResult(null);
  };

  const selectTemplate = (template: TemplateRecord) => {
    resetFeedback();
    setNewMode(false);
    setSelectedTemplateId(template.id);
    setSelectedVersionId('');
    // Clear the previous template's editor immediately. If the details request
    // fails or is still in flight, never present stale Cisco/Huawei content
    // under the newly selected template metadata.
    setVersions([]);
    setSamples([]);
    setImpact(null);
    setAudit([]);
    setContent('');
    setContract('{}');
    setPlatformCode(template.platform_code);
    const matchingProfile = platformProfiles.find((profile) => profile.id === template.platform_profile_id)
      || platformProfiles.find((profile) => profile.parser_platform === template.platform_code);
    setSelectedProfileId(matchingProfile?.id || '');
    setTemplateCode(template.template_code);
    setTemplateName(template.name || template.template_code);
    setTestResult(null);
  };

  const parseContract = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(contract || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('contract');
      return parsed as Record<string, unknown>;
    } catch {
      setError(zh ? '字段契约必须是 JSON 对象' : 'Field contract must be a JSON object');
      return null;
    }
  };

  const saveDraft = async () => {
    if (!canEdit) return;
    const parsedContract = parseContract();
    if (!parsedContract || !content.trim()) return;
    const selectedProfile = platformProfiles.find((profile) => profile.id === selectedProfileId);
    if (newMode && !selectedProfile) {
      setError(zh ? '请选择目标平台 Profile，确保 TextFSM 与平台解析器一致' : 'Select a target platform profile so the TextFSM parser matches the platform');
      return;
    }
    const effectivePlatformCode = selectedProfile?.parser_platform || platformCode.trim();
    if (newMode && selectedProfile && effectivePlatformCode !== platformCode.trim()) {
      setPlatformCode(effectivePlatformCode);
    }
    resetFeedback();
    setSaving(true);
    try {
      let templateId = selectedTemplateId;
      if (newMode || !templateId) {
        const templateResponse = await apiRequest<ApiEnvelope<TemplateRecord>>('/api/parser-templates', {
          method: 'POST',
          body: JSON.stringify({ platform_code: effectivePlatformCode, platform_profile_id: selectedProfileId, template_code: templateCode.trim().toUpperCase(), name: templateName.trim() || templateCode.trim().toUpperCase() }),
        });
        templateId = templateResponse.data.id;
        setNewMode(false);
        setSelectedTemplateId(templateId);
      }
      if (!newMode && templateId && selectedVersion?.status === 'DRAFT' && !isSystemTemplate) {
        await apiRequest<ApiEnvelope<TemplateRecord>>(`/api/parser-templates/${encodeURIComponent(templateId)}`, {
          method: 'PUT',
          body: JSON.stringify({
            platform_code: effectivePlatformCode,
            platform_profile_id: selectedProfileId || selectedTemplate?.platform_profile_id || null,
            template_code: templateCode.trim().toUpperCase(),
            name: templateName.trim() || templateCode.trim().toUpperCase(),
            lock_version: selectedTemplate?.lock_version,
          }),
        });
      }
      if (selectedVersion && selectedVersion.status === 'DRAFT' && !isSystemTemplate && !newMode && selectedVersion.id) {
        await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersion.id)}`, {
          method: 'PUT',
          body: JSON.stringify({ content, field_contract: parsedContract, lock_version: selectedVersion.lock_version }),
        });
      } else {
        const versionResponse = await apiRequest<ApiEnvelope<VersionRecord>>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`, {
          method: 'POST',
          body: JSON.stringify({ content, field_contract: parsedContract }),
        });
        setSelectedVersionId(versionResponse.data.id);
      }
      await loadTemplates();
      await loadVersions(templateId);
      setMessage(zh ? (newMode ? '草稿已保存' : '修改已保存') : (newMode ? 'Draft saved' : 'Changes saved'));
    } catch (cause) {
      setError(errorMessage(cause, zh ? '草稿保存失败' : 'Failed to save draft'));
    } finally {
      setSaving(false);
    }
  };

  const openDeleteModal = () => {
    if (!selectedTemplate || isSystemTemplate || !canDelete) return;
    setDeleteModalError('');
    setDeleteModalOpen(true);
  };

  const deleteSelectedTemplate = async () => {
    if (!selectedTemplate || isSystemTemplate || !canDelete) return;
    setDeleteModalError('');
    setDeleting(true);
    try {
      await apiRequest(`/api/parser-templates/${encodeURIComponent(selectedTemplate.id)}`, { method: 'DELETE' });
      setDeleteModalOpen(false);
      setSelectedTemplateId('');
      setSelectedVersionId('');
      setVersions([]);
      setSamples([]);
      setImpact(null);
      setAudit([]);
      setContent('');
      setContract('{}');
      await loadTemplates();
      setMessage(zh ? '模板已删除' : 'Template deleted');
    } catch (cause) {
      const messageText = errorMessage(cause, zh ? '模板删除失败' : 'Failed to delete template', zh);
      setDeleteModalError(messageText);
    } finally {
      setDeleting(false);
    }
  };

  const openForkModal = () => {
    if (!selectedTemplate || !isSystemTemplate || !canEdit) return;
    if (!selectedProfileId) {
      setError(zh ? '请选择目标平台 Profile 后再复制' : 'Select a target platform profile before forking');
      return;
    }
    setForkCode(`${selectedTemplate.template_code}_FORK`.slice(0, 64));
    setForkName(`${selectedTemplate.name || selectedTemplate.template_code} ${zh ? '副本' : 'Fork'}`);
    setForkModalError('');
    setForkModalOpen(true);
  };

  const forkSelectedTemplate = async () => {
    if (!selectedTemplate || !isSystemTemplate || !canEdit) return;
    const normalizedCode = forkCode.trim().toUpperCase();
    const normalizedName = forkName.trim();
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(normalizedCode)) {
      setForkModalError(zh ? '模板编码必须以大写字母开头，只能包含大写字母、数字和下划线' : 'Template code must start with an uppercase letter and use only A-Z, 0-9, and underscore');
      return;
    }
    if (!normalizedName) {
      setForkModalError(zh ? '请输入租户模板名称' : 'Enter a tenant template name');
      return;
    }
    resetFeedback();
    setForking(true);
    try {
      const response = await apiRequest<ApiEnvelope<TemplateRecord>>(`/api/parser-templates/${encodeURIComponent(selectedTemplate.id)}/fork`, {
        method: 'POST',
        body: JSON.stringify({ template_code: normalizedCode, name: normalizedName, platform_profile_id: selectedProfileId || undefined }),
      });
      setForkModalOpen(false);
      setNewMode(false);
      setSelectedTemplateId(response.data.id);
      await loadTemplates();
      setMessage(zh ? '系统模板已复制为租户副本' : 'SYSTEM template forked into a tenant template');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '复制失败' : 'Failed to fork template'));
    } finally {
      setForking(false);
    }
  };

  const runTest = async () => {
    if (!canTest) return;
    const parsedContract = parseContract();
    if (!parsedContract || !sampleOutput.trim()) {
      if (!sampleOutput.trim()) setError(zh ? '请提供测试回显' : 'Provide sample output first');
      return;
    }
    resetFeedback();
    setTesting(true);
    try {
      const response = await apiRequest<ApiEnvelope<TestResult>>('/api/parser-templates/sandbox-test', {
        method: 'POST',
        body: JSON.stringify({
          version_id: selectedVersionId || undefined,
          content,
          field_contract: parsedContract,
          sample_output: sampleOutput,
          persist: isMutableDraft,
          lock_version: selectedVersion?.lock_version,
        }),
      });
      setTestResult(response.data);
      if (isMutableDraft && selectedTemplateId) await loadVersions(selectedTemplateId);
      setMessage(zh ? `Sandbox 解析通过，共 ${response.data.records.length} 条记录` : `Sandbox passed with ${response.data.records.length} records`);
    } catch (cause) {
      setTestResult(null);
      setError(errorMessage(cause, zh ? 'Sandbox 测试失败' : 'Sandbox test failed'));
    } finally {
      setTesting(false);
    }
  };

  const transition = async (action: 'submit' | 'approve' | 'publish' | 'rollback' | 'deprecate') => {
    const allowed = action === 'submit' ? canEdit : canReview;
    if (!selectedVersionId || !allowed) return;
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/${action}`, { method: 'POST' });
      await loadVersions(selectedTemplateId);
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? `版本${action === 'submit' ? '已提交' : action === 'approve' ? '已审批' : action === 'publish' ? '已发布' : action === 'rollback' ? '已回滚' : '已废弃'}` : `Version ${action} completed`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '版本流转失败' : 'Version transition failed', zh));
    }
  };

  const uploadSample = async () => {
    if (!selectedVersionId || !sampleOutput.trim() || !canSample || isSystemTemplate) return;
    let expected: unknown[] = [];
    try {
      const parsed = JSON.parse(expectedRecords || '[]');
      if (!Array.isArray(parsed)) throw new Error('expected_records');
      expected = parsed;
    } catch {
      setError(zh ? '期望记录必须是 JSON 数组' : 'Expected records must be a JSON array');
      return;
    }
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/samples`, {
        method: 'POST',
        body: JSON.stringify({ sample_name: sampleName.trim() || 'editor-sample', sample_output: sampleOutput, expected_records: expected }),
      });
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? '样例已加密保存' : 'Sample encrypted and stored');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '样例保存失败' : 'Sample upload failed'));
    }
  };

  const removeSample = async (sampleId: string) => {
    if (!canSample || isSystemTemplate) return;
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/samples/${encodeURIComponent(sampleId)}`, { method: 'DELETE' });
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? '样例已删除' : 'Sample deleted');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '样例删除失败' : 'Sample delete failed'));
    }
  };

  const runRegression = async () => {
    if (!selectedTemplateId || !selectedVersionId || isSystemTemplate || !canWrite) return;
    resetFeedback();
    setRegressionTesting(true);
    try {
      const response = await apiRequest<ApiEnvelope<{ sample_count?: number }>>(`/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/regression-test`, {
        method: 'POST',
        body: JSON.stringify({ version_id: selectedVersionId }),
      });
      setMessage(zh ? `历史样例回归通过（${response.data.sample_count || 0} 个样例）` : `Historical regression passed (${response.data.sample_count || 0} samples)`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '历史样例回归失败' : 'Historical regression failed'));
    } finally {
      setRegressionTesting(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold text-slate-800"><FileCode2 size={20} className="text-[#00bceb]" />{zh ? 'TextFSM 注册表开发' : 'TextFSM Registry Development'}</div>
          <p className="mt-1 text-xs text-slate-500">{zh ? '租户隔离草稿、沙箱解析、加密样例、影响分析与受控发布' : 'Tenant drafts, sandbox parsing, encrypted samples, impact analysis and controlled release'}</p>
        </div>
        <div className="flex items-center gap-2"><button onClick={() => setManualOpen(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-700 hover:bg-cyan-100" data-testid="parser-manual-button"><BookOpen size={14} />{zh ? '注册手册' : 'Registration guide'}</button><button onClick={() => void loadTemplates()} className="rounded-lg border border-black/10 bg-white p-2 text-slate-500 hover:text-[#00bceb]" title={zh ? '刷新' : 'Refresh'} data-testid="parser-refresh"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button></div>
      </div>

      {(error || message) && <div className={`rounded-xl border px-3 py-2 text-xs ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}
      {capabilitiesLoading && <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{zh ? '正在读取功能开关状态…' : 'Reading feature gate…'}</div>}
      {!capabilitiesLoading && capabilities && !capabilities.write_enabled && <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{zh ? '当前为只读审查模式：仅允许 SYSTEM（系统）模板只读 Sandbox，不会保存版本或样例。' : 'Read-only review mode: only SYSTEM read-only Sandbox is available; no versions or samples are saved.'}</div>}
      {!capabilitiesLoading && capabilities?.write_enabled && !roleCanEdit && <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">{zh ? '当前角色没有 TextFSM 写入权限；可继续查看模板和允许的测试能力。' : 'Your current role has no TextFSM write permission; you can still view templates and allowed test capabilities.'}</div>}
      {capabilitiesError && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{capabilitiesError}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)]" data-testid="parser-registry-layout">
        <aside className={`${panelClass} flex min-h-[300px] flex-col overflow-hidden lg:min-h-0`}>
          <div className="border-b border-black/5 p-3">
            <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-700"><span>{zh ? '模板' : 'Templates'}</span>{canWrite && <button onClick={startNewTemplate} className="inline-flex items-center gap-1 rounded-md bg-[#00bceb] px-2 py-1 text-[10px] font-semibold text-white" data-testid="parser-new-template"><Plus size={13} />{zh ? '新建' : 'New'}</button>}</div>
            <div className="relative"><Search size={13} className="absolute left-2.5 top-2.5 text-slate-400" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={zh ? '搜索模板/平台' : 'Search template/platform'} className="w-full rounded-lg border border-black/10 py-2 pl-8 pr-2 text-xs outline-none focus:border-cyan-400" data-testid="parser-search" /></div>
            <div className="mt-2 grid grid-cols-2 gap-2"><select value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); setPage(1); }} className="rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-slate-600" data-testid="parser-source-filter"><option value="">{zh ? '全部来源' : 'All sources'}</option><option value="SYSTEM">{sourceLabel('SYSTEM', zh)}</option><option value="CUSTOM">{sourceLabel('CUSTOM', zh)}</option><option value="FORKED">{sourceLabel('FORKED', zh)}</option></select><select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-slate-600" data-testid="parser-status-filter"><option value="">{zh ? '全部状态' : 'All statuses'}</option><option value="ACTIVE">ACTIVE</option><option value="ARCHIVED">ARCHIVED</option></select></div>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {templates.map((template) => <button key={template.id} onClick={() => selectTemplate(template)} className={`w-full rounded-lg px-3 py-2.5 text-left ${!newMode && selectedTemplateId === template.id ? 'bg-cyan-50 text-cyan-800 ring-1 ring-cyan-100' : 'hover:bg-slate-50'}`} data-testid={`parser-template-${template.template_code}`} title={`${template.name || template.template_code} · ${template.template_code}`}><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-xs font-semibold" title={template.name || template.template_code}>{template.name || template.template_code}</div><div className="mt-1 truncate font-mono text-[10px] text-slate-500" title={template.template_code}>{template.template_code}</div></div><span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${template.source === 'SYSTEM' ? 'bg-slate-100 text-slate-500' : 'bg-cyan-50 text-cyan-700'}`}>{sourceLabel(template.source, zh)}</span></div><div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-slate-400"><span className="truncate" title={template.platform_code}>{template.platform_code}</span><span className="shrink-0">{template.status || 'ACTIVE'}</span></div></button>)}
            {!templates.length && <div className="p-4 text-center text-xs text-slate-400">{zh ? '暂无可见模板' : 'No visible templates'}</div>}
          </div>
          <div className="flex items-center justify-between border-t border-black/5 px-3 py-2 text-[10px] text-slate-400"><span>{meta.total} {zh ? '个模板' : 'templates'}</span><div className="flex items-center gap-1"><button disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft size={13} /></button><span>{page}/{Math.max(meta.pages, 1)}</span><button disabled={!meta.pages || page >= meta.pages} onClick={() => setPage((current) => current + 1)} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronRight size={13} /></button></div></div>
        </aside>

        <main className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/5 px-4 py-3">
            <div className="flex items-center gap-2 text-xs text-slate-500"><GitBranch size={14} />{newMode ? (zh ? '新建模板' : 'New template') : selectedTemplate ? selectedTemplate.template_code : (zh ? '请选择模板' : 'Select a template')}{isSystemTemplate && <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">{sourceLabel('SYSTEM', zh)} {zh ? '只读' : 'read-only'}</span>}</div>
            <div className="flex flex-wrap gap-2">
              {isSystemTemplate && canWrite && <button onClick={openForkModal} disabled={forking || !canEdit} className="inline-flex items-center gap-1 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><GitBranch size={13} />{forking ? (zh ? '复制中' : 'Forking') : (zh ? '复制为租户模板' : 'Fork to tenant')}</button>}
              {!isSystemTemplate && canWrite && <button onClick={() => void saveDraft()} disabled={saving || !canEditCurrent} className="inline-flex items-center gap-1 rounded-lg bg-[#00bceb] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" data-testid="parser-save-draft">{saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}{newMode ? (zh ? '保存草稿' : 'Save draft') : selectedVersion?.status === 'DRAFT' ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建草稿' : 'Create draft')}</button>}
              {!newMode && !isSystemTemplate && canDelete && <button onClick={openDeleteModal} disabled={deleting} className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-50" data-testid="parser-delete-template"><Trash2 size={13} />{zh ? '删除模板' : 'Delete template'}</button>}
              <button onClick={() => void runTest()} disabled={testing || !canTest || !content.trim() || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40" data-testid="parser-sandbox-test"><PlayCircle size={13} />{testing ? (zh ? '解析中' : 'Testing') : (zh ? 'Sandbox 测试' : 'Sandbox test')}</button>
              <button onClick={() => void uploadSample()} disabled={!selectedVersionId || isSystemTemplate || !canSample || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40" data-testid="parser-upload-sample"><UploadCloud size={13} />{zh ? '上传加密样例' : 'Upload sample'}</button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4" data-testid="parser-registry-scroll-area">
            <div data-testid="parser-copy-help" className="mb-3 rounded-xl border border-cyan-100 bg-cyan-50/70 px-3 py-2 text-[11px] leading-5 text-cyan-950">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-semibold">{zh ? '编辑提示' : 'Edit guide'}</span><span className="text-cyan-800">{zh ? '复制 → 编辑规则 → Sandbox → 保存修改 → 提交/发布' : 'Copy → edit rules → Sandbox → save changes → submit/publish'}</span><details className="ml-auto"><summary className="cursor-pointer select-none text-[10px] font-semibold text-cyan-700">{zh ? '查看字段和命令说明' : 'Show field and command guide'}</summary><div className="mt-2 grid grid-cols-1 gap-2 border-t border-cyan-100 pt-2 text-[10px] sm:grid-cols-2">
                <div data-testid="parser-command-help" className="rounded-lg border border-amber-100 bg-amber-50/70 p-2 text-amber-950"><b>{zh ? '命令绑定位置' : 'Command mapping'}</b><br />{zh ? '命令不写在 TextFSM 里；到“平台注册表 → Profile → 命令映射”绑定 command、action_code 和已发布解析版本。' : 'Commands are not stored in TextFSM; bind command, action_code and the published parser version in Platform Registry → Profile → Command mappings.'}<code className="mt-1 block font-mono text-[9px]">action_code → command + parser_template_version_id</code></div>
                <div data-testid="parser-field-guide" className="rounded-lg border border-slate-200 bg-white/80 p-2 text-slate-600"><b className="text-slate-800">{zh ? '字段说明' : 'Field guide'}</b><div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1"><span><b>Profile</b>：{zh ? '平台范围' : 'platform scope'}</span><span><b>parser_platform</b>：{zh ? '解析键' : 'parser key'}</span><span><b>template_code</b>：{zh ? '唯一编码，非命令' : 'unique code, not command'}</span><span><b>name</b>：{zh ? '显示名称' : 'display name'}</span><span><b>content</b>：{zh ? 'Value/Start/Record 规则' : 'Value/Start/Record rules'}</span><span><b>field_contract</b>：{zh ? '输出字段 JSON' : 'output field JSON'}</span><span><b>sample output</b>：{zh ? '脱敏回显' : 'redacted CLI output'}</span><span><b>expected records</b>：{zh ? '期望记录数组' : 'expected record array'}</span></div></div>
                <div className="rounded-lg border border-cyan-100 bg-white/80 p-2 font-mono text-[9px] leading-4 text-slate-700 sm:col-span-2"><b className="font-sans text-slate-800">TextFSM</b><br />{'Value INTERFACE (\\S+)\nValue STATUS (up|down)\nStart\n  ^${INTERFACE}\\s+${STATUS} -> Record'}</div>
              </div></details></div>
            </div>
            <div className="grid min-w-0 grid-cols-2 gap-3">
            <div className="flex min-w-0 flex-col gap-3">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="parser-identity-fields">
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '目标平台 Profile' : 'Target platform Profile'}</span><select value={selectedProfileId} onChange={(event) => { const nextId = event.target.value; const nextProfile = platformProfiles.find((profile) => profile.id === nextId); setSelectedProfileId(nextId); if (nextProfile?.parser_platform) setPlatformCode(nextProfile.parser_platform); }} disabled={!canEditMetadata} aria-label={zh ? '目标平台 Profile' : 'Target platform profile'} className="w-full rounded-lg border border-cyan-200 bg-white px-2.5 py-2 text-xs font-normal text-slate-700 outline-none focus:border-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500">
                    <option value="">{zh ? '选择平台 Profile' : 'Select platform profile'}</option>
                    {profileOptions.map((profile) => <option key={profile.id} value={profile.id}>{(zh ? profile.name_zh : profile.name_en) || profile.vendor || profile.platform_code} · {profile.platform_code} / {profile.parser_platform}</option>)}
                  </select></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">parser_platform</span><input value={platformCode} readOnly={!canEditMetadata || Boolean(selectedProfileId)} aria-readonly={!canEditMetadata || Boolean(selectedProfileId)} onChange={(event) => setPlatformCode(event.target.value)} placeholder="parser_platform" className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal outline-none ${!canEditMetadata || Boolean(selectedProfileId) ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">template_code</span><input value={templateCode} readOnly={!canEditMetadata} aria-readonly={!canEditMetadata} onChange={(event) => setTemplateCode(event.target.value.toUpperCase())} placeholder="TEMPLATE_CODE" className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal outline-none ${!canEditMetadata ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '模板名称' : 'Template name'}</span><input value={templateName} readOnly={!canEditMetadata} aria-readonly={!canEditMetadata} onChange={(event) => setTemplateName(event.target.value)} placeholder={zh ? '模板名称' : 'Template name'} className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal outline-none ${!canEditMetadata ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
              </div>
              {newMode && <div className="text-[10px] text-slate-400">{zh ? `平台选择决定 parser_platform：${selectedPlatformProfile?.parser_platform || '尚未选择'}；保存后只能绑定到同一 Profile。` : `The selected profile determines parser_platform: ${selectedPlatformProfile?.parser_platform || 'not selected'}; bindings are restricted to the same profile.`}</div>}
              <label className="flex min-h-[280px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '模板内容（带行号）' : 'Template content (with line numbers)'}<div className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-black/10 bg-slate-950 focus-within:border-cyan-400"><div aria-hidden="true" className="pointer-events-none absolute left-0 top-0 z-10 w-10 select-none border-r border-white/10 bg-slate-900/80 px-2 py-3 text-right font-mono text-xs leading-5 text-slate-500" style={{ transform: `translateY(-${editorScrollTop}px)` }}>{editorLineNumbers.map((lineNumber) => <div key={lineNumber}>{lineNumber}</div>)}</div><pre aria-hidden="true" className="pointer-events-none absolute left-12 top-0 min-w-full py-3 pr-3 font-mono text-xs leading-5" style={{ transform: `translate(${-editorScrollLeft}px, -${editorScrollTop}px)` }}>{highlightedTextFSM(content)}</pre><textarea value={content} readOnly={!canEditCurrent} aria-label={zh ? 'TextFSM 模板内容' : 'TextFSM template content'} onChange={(event) => setContent(event.target.value)} onScroll={(event) => { setEditorScrollTop(event.currentTarget.scrollTop); setEditorScrollLeft(event.currentTarget.scrollLeft); }} className={`relative z-20 h-full min-h-[280px] w-full resize-none bg-transparent py-3 pl-12 pr-3 font-mono text-xs leading-5 outline-none selection:bg-cyan-300/30 ${!canEditCurrent ? 'cursor-not-allowed text-transparent caret-slate-400' : 'text-transparent caret-white'}`} spellCheck={false} /></div></label>
              <label className="flex min-h-[120px] flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '字段契约 JSON' : 'Field contract JSON'}<textarea value={contract} readOnly={!canEditCurrent} onChange={(event) => setContract(event.target.value)} className={`min-h-0 flex-1 resize-none rounded-xl border border-black/10 p-3 font-mono text-xs leading-5 outline-none ${!canEditCurrent ? 'cursor-not-allowed bg-slate-100 text-slate-400' : 'bg-slate-50 text-slate-700 focus:border-cyan-400'}`} spellCheck={false} /></label>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '影响分析' : 'Impact analysis'}</div><div className="grid grid-cols-3 gap-2 text-[10px] text-slate-500"><span>Actions: <b className="text-slate-800">{impact?.action_count || 0}</b></span><span>Releases: <b className="text-slate-800">{impact?.release_count || 0}</b></span><span>Profiles: <b className="text-slate-800">{impact?.profile_count || 0}</b></span><span>Devices: <b className="text-slate-800">{impact?.device_count || 0}</b></span><span>Playbooks: <b className="text-slate-800">{impact?.playbook_count || 0}</b></span><span>Versions: <b className="text-slate-800">{impact?.version_count || 0}</b></span></div></div>
            </div>

            <div className="flex min-w-0 flex-col gap-3">
              <label className="flex min-h-[180px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600"><span className="flex items-center justify-between gap-2"><span>{zh ? '测试回显（Sandbox/加密样例）' : 'Sample output (sandbox/encrypted sample)'}</span><span id="parser-sandbox-hint" className="font-normal text-slate-400" data-testid="parser-sandbox-hint">{sampleOutput.trim() ? (zh ? '可运行只读测试' : 'Ready for read-only test') : (zh ? '请先填写测试回显' : 'Enter sample output to enable testing')}</span></span><textarea value={sampleOutput} onChange={(event) => setSampleOutput(event.target.value)} aria-describedby="parser-sandbox-hint" className="min-h-0 flex-1 resize-none rounded-xl border border-black/10 bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700 outline-none focus:border-cyan-400" spellCheck={false} /></label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2"><label className="text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '样例名称' : 'Sample name'}</span><input value={sampleName} onChange={(event) => setSampleName(event.target.value)} placeholder="editor-sample" aria-label={zh ? '样例名称' : 'Sample name'} className="w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal" /></label><label className="text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '期望记录 JSON 数组' : 'Expected records JSON array'}</span><input value={expectedRecords} onChange={(event) => setExpectedRecords(event.target.value)} placeholder="[]" aria-label={zh ? '期望记录 JSON 数组' : 'Expected records JSON array'} className="w-full rounded-lg border border-black/10 px-2.5 py-2 font-mono text-xs font-normal" /></label></div>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-600"><span>{zh ? '版本与发布' : 'Version lifecycle'}</span>{detailsLoading && <Loader2 size={13} className="animate-spin text-cyan-600" />}</div>{isSystemTemplate && <div className="mb-2 rounded-lg border border-amber-100 bg-amber-50 px-2.5 py-2 text-[10px] leading-4 text-amber-800">{zh ? '系统版本为只读，不能废弃或回滚；如需修改或替换，请先复制为租户副本。' : 'SYSTEM versions are read-only and cannot be deprecated or rolled back. Fork a tenant template to modify or replace the parser.'}</div>}<div className="mb-2 flex flex-wrap gap-1.5">{versions.map((version) => <button key={version.id} onClick={() => { setSelectedVersionId(version.id); setCompareVersionId(''); }} className={`rounded-md px-2 py-1 text-[10px] ${selectedVersionId === version.id ? 'bg-cyan-600 text-white' : 'bg-white text-slate-500 ring-1 ring-black/5'}`}>v{version.version_number} · {version.status}</button>)}{!versions.length && <span className="text-[10px] text-slate-400">{newMode ? (zh ? '保存后生成版本' : 'Save to create a version') : (zh ? '暂无版本' : 'No versions')}</span>}</div>{versions.length > 1 && <label className="mb-2 flex items-center gap-2 text-[10px] text-slate-500"><span>{zh ? '对比基线' : 'Compare baseline'}</span><select value={compareVersion?.id || ''} onChange={(event) => setCompareVersionId(event.target.value)} className="min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-[10px]"><option value="">{zh ? '自动选择上一版本' : 'Auto-select previous version'}</option>{versions.filter((version) => version.id !== selectedVersionId).map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {version.status}</option>)}</select></label>}{selectedVersion && <div className="flex flex-wrap gap-1.5"><button onClick={() => void runRegression()} disabled={regressionTesting || isSystemTemplate || !canWrite} className="rounded-md border border-cyan-200 bg-white px-2 py-1 text-[10px] font-semibold text-cyan-700 disabled:opacity-40">{regressionTesting ? '…' : (zh ? '历史回归' : 'Regression')}</button>{selectedVersion.status === 'DRAFT' && canEdit && <button onClick={() => void transition('submit')} className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-2 py-1 text-[10px] font-semibold text-white"><Send size={11} />{zh ? '提交审核' : 'Submit'}</button>}{selectedVersion.status === 'IN_REVIEW' && canReview && <button onClick={() => void transition('approve')} className="inline-flex items-center gap-1 rounded-md bg-indigo-500 px-2 py-1 text-[10px] font-semibold text-white"><ShieldCheck size={11} />{zh ? '审批' : 'Approve'}</button>}{selectedVersion.status === 'APPROVED' && canReview && <button onClick={() => void transition('publish')} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-xs font-semibold text-white"><CheckCircle2 size={11} />{zh ? '发布' : 'Publish'}</button>}{selectedVersion.status === 'PUBLISHED' && canReview && !isSystemTemplate && <button onClick={() => void transition('deprecate')} className="rounded-md border border-rose-200 bg-white px-2 py-1 text-[10px] font-semibold text-rose-700">{zh ? '废弃' : 'Deprecate'}</button>}{selectedVersion.status === 'DEPRECATED' && canReview && !isSystemTemplate && <button onClick={() => void transition('rollback')} className="rounded-md border border-violet-200 bg-white px-2 py-1 text-[10px] font-semibold text-violet-700">{zh ? '回滚' : 'Rollback'}</button>}</div>}</div>
              {testResult && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"><div className="font-semibold">{zh ? '解析结果' : 'Parsed result'} · {testResult.records.length} {zh ? '条记录' : 'records'}</div><div className="mt-1">{zh ? '字段' : 'Fields'}: {testResult.fields.join(', ') || '—'} · {zh ? '耗时' : 'Duration'}: {currentSummary.duration_ms ?? 0} ms</div><div className="mt-2 max-h-48 overflow-auto rounded-lg border border-emerald-100 bg-white"><table className="min-w-full text-left text-[10px]"><thead className="bg-emerald-100/60 text-emerald-900"><tr>{testResult.fields.map((field) => <th key={field} className="px-2 py-1 font-semibold">{field}</th>)}</tr></thead><tbody>{testResult.records.slice(0, 100).map((record, index) => <tr key={`record-${index}`} className="border-t border-emerald-100"><td colSpan={Math.max(testResult.fields.length, 1)} className="px-2 py-1 align-top"><code>{JSON.stringify(record)}</code></td></tr>)}</tbody></table></div></div>}
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '加密样例列表' : 'Encrypted samples'}</div>{samples.length ? <div className="space-y-1">{samples.map((sample) => <div key={sample.id} className="flex items-center justify-between gap-2 rounded-lg bg-white px-2.5 py-2 text-[10px] text-slate-500"><span className="min-w-0 truncate"><b className="text-slate-700">{sample.sample_name}</b> · {formatDate(sample.created_at, zh)}</span>{canSample && !isSystemTemplate && <button onClick={() => void removeSample(sample.id)} className="rounded p-1 text-rose-500 hover:bg-rose-50" title={zh ? '删除样例' : 'Delete sample'}><Trash2 size={12} /></button>}</div>)}</div> : <div className="text-[10px] text-slate-400">{zh ? '暂无已保存样例' : 'No stored samples'}</div>}</div>
              {compareVersion && <div className="space-y-2 rounded-xl border border-violet-100 bg-violet-50/50 p-3"><div className="flex items-center justify-between text-xs font-semibold text-violet-900"><span>{zh ? `Diff · v${compareVersion.version_number} → 当前编辑内容` : `Diff · v${compareVersion.version_number} → current editor`}</span><span className="text-[10px] font-normal">{sourceDiff.filter((row) => row.type === 'added').length} + / {sourceDiff.filter((row) => row.type === 'removed').length} −</span></div><div className="max-h-40 overflow-auto rounded-lg border border-violet-100 bg-slate-950 p-2 font-mono text-[10px] leading-5">{sourceDiff.slice(0, 300).map((row, index) => <div key={`${row.type}-${index}`} className={row.type === 'added' ? 'bg-emerald-900/50 text-emerald-200' : row.type === 'removed' ? 'bg-rose-900/50 text-rose-200' : 'text-slate-400'}><span className="mr-2 inline-block w-3 text-center text-slate-500">{row.type === 'added' ? '+' : row.type === 'removed' ? '−' : ' '}</span>{row.text || ' '}</div>)}</div><div className="text-[10px] text-violet-900">{zh ? '解析字段变化' : 'Parsed fields'}: +{addedFields.join(', ') || '—'} / −{removedFields.join(', ') || '—'}</div></div>}
              {audit.length > 0 && <details className="rounded-xl border border-black/5 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">{zh ? '审计记录' : 'Audit history'} ({audit.length})</summary><div className="mt-2 max-h-24 space-y-1 overflow-auto text-[10px] text-slate-500">{audit.map((item) => <div key={item.id}>{formatDate(item.created_at, zh)} · <b>{item.event_type}</b> · {item.actor_username || 'system'}</div>)}</div></details>}
            </div>
            </div>
          </div>
        </main>
      </div>
      <ResultStatusModal
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title={zh ? 'TextFSM 注册手册' : 'TextFSM registration guide'}
        closeTitle={zh ? '关闭注册手册' : 'Close registration guide'}
        icon={BookOpen}
        iconClassName="bg-cyan-100 text-cyan-700"
        headerClassName="border-b border-cyan-100 bg-cyan-50/70"
        panelClassName="w-full max-w-3xl rounded-2xl border border-cyan-100 bg-white shadow-2xl"
        bodyClassName="max-h-[75vh] overflow-y-auto p-5"
      >
        <div data-testid="parser-registration-manual" className="space-y-5 text-xs leading-5 text-slate-600">
          <section><h3 className="font-semibold text-slate-900">{zh ? '一、复制或新建' : '1. Copy or create'}</h3><p className="mt-1">{zh ? '系统模板不能直接修改。选择系统模板后点击“复制为租户模板”，填写模板编码和名称；或点击“新建”创建租户模板。复制只生成副本，不会改变系统模板。' : 'SYSTEM templates are read-only. Select one and choose “Fork to tenant template”, then provide a code and name; or choose New to create a tenant template. Copying never changes the SYSTEM template.'}</p></section>
          <section><h3 className="font-semibold text-slate-900">{zh ? '二、填写模板' : '2. Fill in the template'}</h3><div className="mt-1 grid gap-2 sm:grid-cols-2"><div><b className="text-slate-800">Profile / parser_platform</b><br />{zh ? '先选目标平台 Profile；它决定解析平台键，必须与模板平台一致。' : 'Choose the target platform Profile first; it determines the parser key and must match the template platform.'}</div><div><b className="text-slate-800">template_code / name</b><br />{zh ? '编码是唯一标识（大写字母、数字、下划线），名称用于页面展示；两者都不是设备命令。' : 'The code is a unique identifier (A-Z, digits and underscores); the name is for display. Neither is a device command.'}</div><div><b className="text-slate-800">content</b><br />{zh ? 'TextFSM 规则通常由 Value 定义字段、Start 匹配行、Record 输出记录。' : 'TextFSM rules normally define fields with Value, match lines in Start, and emit records with Record.'}</div><div><b className="text-slate-800">field_contract</b><br />{zh ? '用 JSON 声明 required、optional 和 types，约束解析结果。' : 'Use JSON to declare required, optional and types for the parsed result.'}</div></div><pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-[10px] leading-4 text-slate-200">{'Value INTERFACE (\\S+)\nValue STATUS (up|down)\n\nStart\n  ^${INTERFACE}\\s+${STATUS} -> Record'}</pre></section>
          <section><h3 className="font-semibold text-slate-900">{zh ? '三、测试和保存' : '3. Test and save'}</h3><p className="mt-1">{zh ? '粘贴脱敏的设备 CLI 回显，点击 Sandbox 测试；确认 records、字段和类型正确后，草稿点击“保存修改”，已发布版本点击“创建草稿”生成新版本。系统模板只能只读测试。' : 'Paste redacted device CLI output and run Sandbox test. Save a draft with Save changes; for a published tenant version, choose Create draft to start a new version. SYSTEM templates are read-only.'}</p></section>
          <section><h3 className="font-semibold text-slate-900">{zh ? '四、发布版本' : '4. Release a version'}</h3><p className="mt-1">{zh ? '按“提交审核 → 审批 → 发布”推进版本。只有 PUBLISHED 版本可以被平台 Release 的命令映射引用。需要删除草稿时点击“删除模板”；若已被 Release 引用或有已发布版本，系统会阻止删除。' : 'Advance the version with Submit → Approve → Publish. Only PUBLISHED versions can be referenced by a platform Release mapping. Use Delete template for an unused draft; mappings or released versions block deletion.'}</p></section>
          <section className="rounded-xl border border-amber-100 bg-amber-50 p-3"><h3 className="font-semibold text-amber-950">{zh ? '五、命令和 Playbook 的关联' : '5. Bind the command to a Playbook'}</h3><p className="mt-1 text-amber-900">{zh ? '命令不在 TextFSM 页面填写。到“平台注册表 → 平台 Profile → 命令映射”，为 action_code 绑定只读 command 和 PUBLISHED 的 parser_template_version_id；Playbook 只保存 action_code。' : 'The CLI command is not entered on this page. Go to Platform Registry → platform Profile → Command mappings and bind a read-only command plus the PUBLISHED parser_template_version_id; the Playbook stores only action_code.'}</p><code className="mt-2 block rounded-lg bg-white px-2 py-1.5 font-mono text-[10px] text-slate-700">action_code → command + parser_template_version_id</code></section>
        </div>
      </ResultStatusModal>
      <ResultStatusModal
        open={forkModalOpen}
        onClose={() => { if (!forking) setForkModalOpen(false); }}
        title={zh ? '复制为租户模板' : 'Fork to tenant template'}
        closeTitle={zh ? '关闭复制窗口' : 'Close Fork dialog'}
        icon={GitBranch}
        iconClassName="bg-amber-100 text-amber-700"
        headerClassName="border-b border-amber-100 bg-amber-50/70"
        panelClassName="w-full max-w-lg rounded-2xl shadow-2xl border border-amber-100 overflow-hidden bg-white"
        bodyClassName="p-5"
        closeDisabled={forking}
      >
        <form
          className="space-y-4"
          onSubmit={(event) => { event.preventDefault(); void forkSelectedTemplate(); }}
        >
          <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
            <div className="font-semibold text-slate-800">{selectedTemplate?.template_code || (zh ? '系统模板' : 'SYSTEM template')}</div>
            <div className="mt-1">{zh ? '复制为租户副本后，可在新模板中修改、测试并发布独立版本。' : 'The copied tenant template can be edited, tested, and released independently.'}</div>
          </div>
          <label className="block text-xs font-semibold text-slate-700">
            {zh ? '租户模板编码' : 'Tenant template code'}
            <input
              value={forkCode}
              onChange={(event) => setForkCode(event.target.value.toUpperCase())}
              maxLength={64}
              autoFocus
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-sm outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
              aria-label={zh ? '租户模板编码' : 'Tenant template code'}
            />
            <span className="mt-1 block text-[10px] font-normal text-slate-400">{zh ? 'A-Z 开头 · A-Z / 0-9 / _' : 'Starts with A-Z · A-Z / 0-9 / _'} · {forkCode.length}/64</span>
          </label>
          <label className="block text-xs font-semibold text-slate-700">
            {zh ? '租户模板名称' : 'Tenant template name'}
            <input
              value={forkName}
              onChange={(event) => setForkName(event.target.value)}
              maxLength={128}
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
              aria-label={zh ? '租户模板名称' : 'Tenant template name'}
            />
          </label>
          {forkModalError && <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{forkModalError}</div>}
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={() => setForkModalOpen(false)} disabled={forking} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button>
            <button type="submit" disabled={forking} className="inline-flex items-center gap-1.5 rounded-xl bg-amber-500 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-amber-600 disabled:opacity-50">
              {forking && <Loader2 size={13} className="animate-spin" />}
              {forking ? (zh ? '复制中' : 'Forking') : (zh ? '确认复制' : 'Confirm Fork')}
            </button>
          </div>
        </form>
      </ResultStatusModal>
      <ResultStatusModal
        open={deleteModalOpen}
        onClose={() => { if (!deleting) setDeleteModalOpen(false); }}
        title={zh ? '删除租户模板' : 'Delete tenant template'}
        closeTitle={zh ? '关闭删除窗口' : 'Close delete dialog'}
        icon={Trash2}
        iconClassName="bg-rose-100 text-rose-700"
        headerClassName="border-b border-rose-100 bg-rose-50/70"
        panelClassName="w-full max-w-lg rounded-2xl border border-rose-100 bg-white shadow-2xl"
        bodyClassName="p-5"
        closeDisabled={deleting}
      >
        <div className="space-y-4">
          <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2.5 text-xs leading-5 text-rose-900">
            <div className="font-semibold">{selectedTemplate?.name || selectedTemplate?.template_code}</div>
            <div className="mt-1">{zh ? '只删除租户模板及其草稿、样例和审计数据；系统模板不会被删除。若模板已被 Release 引用或存在已发布版本，后端会阻止删除。' : 'This removes the tenant template and its drafts, samples and audit data. SYSTEM templates cannot be deleted; mappings or released versions must be removed first.'}</div>
          </div>
          {deleteModalError && <div className="rounded-xl border border-rose-200 bg-rose-100 px-3 py-2 text-xs text-rose-800">{deleteModalError}</div>}
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={() => setDeleteModalOpen(false)} disabled={deleting} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button>
            <button type="button" onClick={() => void deleteSelectedTemplate()} disabled={deleting} className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-700 disabled:opacity-50">
              {deleting && <Loader2 size={13} className="animate-spin" />}
              {deleting ? (zh ? '删除中' : 'Deleting') : (zh ? '确认删除' : 'Delete template')}
            </button>
          </div>
        </div>
      </ResultStatusModal>
    </div>
  );
};

export default ParserRegistryTab;
