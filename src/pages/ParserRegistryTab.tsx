import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
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

interface Props {
  language: string;
  currentUser?: { role?: string; role_profile?: string } | null;
}

interface TemplateRecord {
  id: string;
  tenant_id?: string | null;
  platform_code: string;
  template_code: string;
  name?: string;
  source?: string;
  status?: string;
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

const errorMessage = (cause: unknown, fallback: string): string => (
  cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : fallback
);

const ParserRegistryTab: React.FC<Props> = ({ language, currentUser }) => {
  const zh = language === 'zh';
  const role = String(currentUser?.role || '');
  const roleProfile = String(currentUser?.role_profile || '');
  const isAdmin = role === 'Administrator';
  const canEdit = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);
  const canReview = isAdmin || ['Release Manager', 'System Administrator'].includes(roleProfile);
  const canSample = canEdit || isAdmin;

  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
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
  const [regressionTesting, setRegressionTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [platformCode, setPlatformCode] = useState('cisco_ios');
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

  const resetFeedback = () => {
    setError('');
    setMessage('');
  };

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
        setSelectedTemplateId((current) => current && next.some((item) => item.id === current) ? current : (next[0]?.id || ''));
      }
    } catch (cause) {
      setError(errorMessage(cause, zh ? '模板列表加载失败' : 'Failed to load parser templates'));
    } finally {
      setLoading(false);
    }
  }, [meta.page_size, newMode, page, search, sourceFilter, statusFilter, zh]);

  const loadVersions = useCallback(async (templateId: string) => {
    if (!templateId) return;
    setDetailsLoading(true);
    try {
      const response = await apiRequest<ApiEnvelope<VersionRecord[]>>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`);
      const next = response.data || [];
      setVersions(next);
      setSelectedVersionId((current) => current && next.some((item) => item.id === current) ? current : (next[0]?.id || ''));
    } catch (cause) {
      setError(errorMessage(cause, zh ? '版本加载失败' : 'Failed to load versions'));
    } finally {
      setDetailsLoading(false);
    }
  }, [zh]);

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

  const startNewTemplate = () => {
    resetFeedback();
    setNewMode(true);
    setSelectedTemplateId('');
    setSelectedVersionId('');
    setVersions([]);
    setSamples([]);
    setImpact(null);
    setAudit([]);
    setPlatformCode('cisco_ios');
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
    setPlatformCode(template.platform_code);
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
    if (!canEdit && !isAdmin) return;
    const parsedContract = parseContract();
    if (!parsedContract || !content.trim()) return;
    resetFeedback();
    setSaving(true);
    try {
      let templateId = selectedTemplateId;
      if (newMode || !templateId) {
        const templateResponse = await apiRequest<ApiEnvelope<TemplateRecord>>('/api/parser-templates', {
          method: 'POST',
          body: JSON.stringify({ platform_code: platformCode.trim(), template_code: templateCode.trim().toUpperCase(), name: templateName.trim() || templateCode.trim().toUpperCase() }),
        });
        templateId = templateResponse.data.id;
        setNewMode(false);
        setSelectedTemplateId(templateId);
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
      setMessage(zh ? '草稿已保存' : 'Draft saved');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '草稿保存失败' : 'Failed to save draft'));
    } finally {
      setSaving(false);
    }
  };

  const forkSelectedTemplate = async () => {
    if (!selectedTemplate || !isSystemTemplate || (!canEdit && !isAdmin)) return;
    const suggested = `${selectedTemplate.template_code}_FORK`.slice(0, 64);
    const forkCode = window.prompt(zh ? '请输入 Fork 后的租户模板编码' : 'Enter the forked tenant template code', suggested)?.trim().toUpperCase();
    if (!forkCode) return;
    const forkName = window.prompt(zh ? '请输入 Fork 后的租户模板名称' : 'Enter the forked tenant template name', `${selectedTemplate.name || selectedTemplate.template_code} Fork`)?.trim() || `${selectedTemplate.template_code} Fork`;
    resetFeedback();
    setForking(true);
    try {
      const response = await apiRequest<ApiEnvelope<TemplateRecord>>(`/api/parser-templates/${encodeURIComponent(selectedTemplate.id)}/fork`, {
        method: 'POST',
        body: JSON.stringify({ template_code: forkCode, name: forkName }),
      });
      setNewMode(false);
      setSelectedTemplateId(response.data.id);
      await loadTemplates();
      setMessage(zh ? 'SYSTEM 模板已 Fork 为租户模板' : 'SYSTEM template forked into a tenant template');
    } catch (cause) {
      setError(errorMessage(cause, zh ? 'Fork 失败' : 'Failed to fork template'));
    } finally {
      setForking(false);
    }
  };

  const runTest = async () => {
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
    if (!selectedVersionId) return;
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/${action}`, { method: 'POST' });
      await loadVersions(selectedTemplateId);
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? `版本${action === 'submit' ? '已提交' : action === 'approve' ? '已审批' : action === 'publish' ? '已发布' : action === 'rollback' ? '已回滚' : '已废弃'}` : `Version ${action} completed`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '版本流转失败' : 'Version transition failed'));
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
    if (!selectedTemplateId || !selectedVersionId || isSystemTemplate) return;
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
        <button onClick={() => void loadTemplates()} className="rounded-lg border border-black/10 bg-white p-2 text-slate-500 hover:text-[#00bceb]" title={zh ? '刷新' : 'Refresh'} data-testid="parser-refresh"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>
      </div>

      {(error || message) && <div className={`rounded-xl border px-3 py-2 text-xs ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)] gap-4">
        <aside className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
          <div className="border-b border-black/5 p-3">
            <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-700"><span>{zh ? '模板' : 'Templates'}</span><button onClick={startNewTemplate} className="inline-flex items-center gap-1 rounded-md bg-[#00bceb] px-2 py-1 text-[10px] font-semibold text-white" data-testid="parser-new-template"><Plus size={13} />{zh ? '新建' : 'New'}</button></div>
            <div className="relative"><Search size={13} className="absolute left-2.5 top-2.5 text-slate-400" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={zh ? '搜索模板/平台' : 'Search template/platform'} className="w-full rounded-lg border border-black/10 py-2 pl-8 pr-2 text-xs outline-none focus:border-cyan-400" data-testid="parser-search" /></div>
            <div className="mt-2 grid grid-cols-2 gap-2"><select value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); setPage(1); }} className="rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-slate-600" data-testid="parser-source-filter"><option value="">{zh ? '全部来源' : 'All sources'}</option><option value="SYSTEM">SYSTEM</option><option value="CUSTOM">CUSTOM</option><option value="FORKED">FORKED</option></select><select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-slate-600" data-testid="parser-status-filter"><option value="">{zh ? '全部状态' : 'All statuses'}</option><option value="ACTIVE">ACTIVE</option><option value="ARCHIVED">ARCHIVED</option></select></div>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {templates.map((template) => <button key={template.id} onClick={() => selectTemplate(template)} className={`w-full rounded-lg px-3 py-2 text-left ${!newMode && selectedTemplateId === template.id ? 'bg-cyan-50 text-cyan-800 ring-1 ring-cyan-100' : 'hover:bg-slate-50'}`} data-testid={`parser-template-${template.template_code}`}><div className="truncate text-xs font-semibold">{template.template_code}</div><div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-slate-400"><span>{template.platform_code}</span><span>{template.source || 'CUSTOM'}</span></div></button>)}
            {!templates.length && <div className="p-4 text-center text-xs text-slate-400">{zh ? '暂无可见模板' : 'No visible templates'}</div>}
          </div>
          <div className="flex items-center justify-between border-t border-black/5 px-3 py-2 text-[10px] text-slate-400"><span>{meta.total} {zh ? '个模板' : 'templates'}</span><div className="flex items-center gap-1"><button disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft size={13} /></button><span>{page}/{Math.max(meta.pages, 1)}</span><button disabled={!meta.pages || page >= meta.pages} onClick={() => setPage((current) => current + 1)} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronRight size={13} /></button></div></div>
        </aside>

        <main className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/5 px-4 py-3"><div className="flex items-center gap-2 text-xs text-slate-500"><GitBranch size={14} />{newMode ? (zh ? '新建模板' : 'New template') : selectedTemplate ? selectedTemplate.template_code : (zh ? '请选择模板' : 'Select a template')}{isSystemTemplate && <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">SYSTEM {zh ? '只读' : 'read-only'}</span>}</div><div className="flex flex-wrap gap-2">{isSystemTemplate && <button onClick={() => void forkSelectedTemplate()} disabled={forking || !canEdit} className="inline-flex items-center gap-1 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><GitBranch size={13} />{forking ? (zh ? 'Fork 中' : 'Forking') : (zh ? 'Fork 为租户模板' : 'Fork to tenant')}</button>}{!isSystemTemplate && <button onClick={() => void saveDraft()} disabled={saving || !canEdit} className="inline-flex items-center gap-1 rounded-lg bg-[#00bceb] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" data-testid="parser-save-draft">{saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}{zh ? '保存草稿' : 'Save draft'}</button>}<button onClick={() => void runTest()} disabled={testing || !content.trim() || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40" data-testid="parser-sandbox-test"><PlayCircle size={13} />{testing ? (zh ? '解析中' : 'Testing') : (zh ? 'Sandbox 测试' : 'Sandbox test')}</button><button onClick={() => void uploadSample()} disabled={!selectedVersionId || isSystemTemplate || !canSample || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40" data-testid="parser-upload-sample"><UploadCloud size={13} />{zh ? '上传加密样例' : 'Upload sample'}</button></div></div>

          <div className="grid min-h-0 flex-1 grid-cols-2 gap-3 overflow-auto p-4">
            <div className="flex min-h-0 flex-col gap-3">
              <div className="grid grid-cols-3 gap-2"><input value={platformCode} readOnly={!newMode} onChange={(event) => setPlatformCode(event.target.value)} placeholder="platform_code" className="rounded-lg border border-black/10 px-2.5 py-2 text-xs disabled:bg-slate-100" /><input value={templateCode} readOnly={!newMode} onChange={(event) => setTemplateCode(event.target.value.toUpperCase())} placeholder="TEMPLATE_CODE" className="rounded-lg border border-black/10 px-2.5 py-2 text-xs" /><input value={templateName} readOnly={!newMode} onChange={(event) => setTemplateName(event.target.value)} placeholder={zh ? '模板名称' : 'Template name'} className="rounded-lg border border-black/10 px-2.5 py-2 text-xs" /></div>
              <label className="flex min-h-[280px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '模板内容（带行号）' : 'Template content (with line numbers)'}<div className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-black/10 bg-slate-950 focus-within:border-cyan-400"><div aria-hidden="true" className="pointer-events-none absolute left-0 top-0 z-10 w-10 select-none border-r border-white/10 bg-slate-900/80 px-2 py-3 text-right font-mono text-xs leading-5 text-slate-500" style={{ transform: `translateY(-${editorScrollTop}px)` }}>{editorLineNumbers.map((lineNumber) => <div key={lineNumber}>{lineNumber}</div>)}</div><pre aria-hidden="true" className="pointer-events-none absolute left-12 top-0 min-w-full py-3 pr-3 font-mono text-xs leading-5" style={{ transform: `translate(${-editorScrollLeft}px, -${editorScrollTop}px)` }}>{highlightedTextFSM(content)}</pre><textarea value={content} readOnly={isSystemTemplate} aria-label={zh ? 'TextFSM 模板内容' : 'TextFSM template content'} onChange={(event) => setContent(event.target.value)} onScroll={(event) => { setEditorScrollTop(event.currentTarget.scrollTop); setEditorScrollLeft(event.currentTarget.scrollLeft); }} className={`relative z-20 h-full min-h-[280px] w-full resize-none bg-transparent py-3 pl-12 pr-3 font-mono text-xs leading-5 outline-none selection:bg-cyan-300/30 ${isSystemTemplate ? 'cursor-not-allowed text-transparent caret-slate-400' : 'text-transparent caret-white'}`} spellCheck={false} /></div></label>
              <label className="flex min-h-[120px] flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '字段契约 JSON' : 'Field contract JSON'}<textarea value={contract} readOnly={isSystemTemplate} onChange={(event) => setContract(event.target.value)} className={`min-h-0 flex-1 resize-none rounded-xl border border-black/10 p-3 font-mono text-xs leading-5 outline-none ${isSystemTemplate ? 'cursor-not-allowed bg-slate-100 text-slate-400' : 'bg-slate-50 text-slate-700 focus:border-cyan-400'}`} spellCheck={false} /></label>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '影响分析' : 'Impact analysis'}</div><div className="grid grid-cols-3 gap-2 text-[10px] text-slate-500"><span>Actions: <b className="text-slate-800">{impact?.action_count || 0}</b></span><span>Releases: <b className="text-slate-800">{impact?.release_count || 0}</b></span><span>Profiles: <b className="text-slate-800">{impact?.profile_count || 0}</b></span><span>Devices: <b className="text-slate-800">{impact?.device_count || 0}</b></span><span>Playbooks: <b className="text-slate-800">{impact?.playbook_count || 0}</b></span><span>Versions: <b className="text-slate-800">{impact?.version_count || 0}</b></span></div></div>
            </div>

            <div className="flex min-h-0 flex-col gap-3">
              <label className="flex min-h-[180px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '测试回显（Sandbox/加密样例）' : 'Sample output (sandbox/encrypted sample)'}<textarea value={sampleOutput} onChange={(event) => setSampleOutput(event.target.value)} className="min-h-0 flex-1 resize-none rounded-xl border border-black/10 bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700 outline-none focus:border-cyan-400" spellCheck={false} /></label>
              <div className="grid grid-cols-2 gap-2"><input value={sampleName} onChange={(event) => setSampleName(event.target.value)} placeholder={zh ? '样例名称' : 'Sample name'} className="rounded-lg border border-black/10 px-2.5 py-2 text-xs" /><input value={expectedRecords} onChange={(event) => setExpectedRecords(event.target.value)} placeholder={zh ? '期望记录 JSON 数组' : 'Expected records JSON array'} className="rounded-lg border border-black/10 px-2.5 py-2 font-mono text-xs" /></div>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-600"><span>{zh ? '版本与发布' : 'Version lifecycle'}</span>{detailsLoading && <Loader2 size={13} className="animate-spin text-cyan-600" />}</div><div className="mb-2 flex flex-wrap gap-1.5">{versions.map((version) => <button key={version.id} onClick={() => { setSelectedVersionId(version.id); setCompareVersionId(''); }} className={`rounded-md px-2 py-1 text-[10px] ${selectedVersionId === version.id ? 'bg-cyan-600 text-white' : 'bg-white text-slate-500 ring-1 ring-black/5'}`}>v{version.version_number} · {version.status}</button>)}{!versions.length && <span className="text-[10px] text-slate-400">{newMode ? (zh ? '保存后生成版本' : 'Save to create a version') : (zh ? '暂无版本' : 'No versions')}</span>}</div>{versions.length > 1 && <label className="mb-2 flex items-center gap-2 text-[10px] text-slate-500"><span>{zh ? '对比基线' : 'Compare baseline'}</span><select value={compareVersion?.id || ''} onChange={(event) => setCompareVersionId(event.target.value)} className="min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-[10px]"><option value="">{zh ? '自动选择上一版本' : 'Auto-select previous version'}</option>{versions.filter((version) => version.id !== selectedVersionId).map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {version.status}</option>)}</select></label>}{selectedVersion && <div className="flex flex-wrap gap-1.5"><button onClick={() => void runRegression()} disabled={regressionTesting || isSystemTemplate} className="rounded-md border border-cyan-200 bg-white px-2 py-1 text-[10px] font-semibold text-cyan-700 disabled:opacity-40">{regressionTesting ? '…' : (zh ? '历史回归' : 'Regression')}</button>{selectedVersion.status === 'DRAFT' && canEdit && <button onClick={() => void transition('submit')} className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-2 py-1 text-[10px] font-semibold text-white"><Send size={11} />{zh ? '提交审核' : 'Submit'}</button>}{selectedVersion.status === 'IN_REVIEW' && canReview && <button onClick={() => void transition('approve')} className="inline-flex items-center gap-1 rounded-md bg-indigo-500 px-2 py-1 text-[10px] font-semibold text-white"><ShieldCheck size={11} />{zh ? '审批' : 'Approve'}</button>}{selectedVersion.status === 'APPROVED' && canReview && <button onClick={() => void transition('publish')} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-[10px] font-semibold text-white"><CheckCircle2 size={11} />{zh ? '发布' : 'Publish'}</button>}{selectedVersion.status === 'PUBLISHED' && canReview && <button onClick={() => void transition('deprecate')} className="rounded-md border border-rose-200 bg-white px-2 py-1 text-[10px] font-semibold text-rose-700">{zh ? '废弃' : 'Deprecate'}</button>}{selectedVersion.status === 'DEPRECATED' && canReview && <button onClick={() => void transition('rollback')} className="rounded-md border border-violet-200 bg-white px-2 py-1 text-[10px] font-semibold text-violet-700">{zh ? '回滚' : 'Rollback'}</button>}</div>}</div>
              {testResult && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"><div className="font-semibold">{zh ? '解析结果' : 'Parsed result'} · {testResult.records.length} {zh ? '条记录' : 'records'}</div><div className="mt-1">{zh ? '字段' : 'Fields'}: {testResult.fields.join(', ') || '—'} · {zh ? '耗时' : 'Duration'}: {currentSummary.duration_ms ?? 0} ms</div><div className="mt-2 max-h-48 overflow-auto rounded-lg border border-emerald-100 bg-white"><table className="min-w-full text-left text-[10px]"><thead className="bg-emerald-100/60 text-emerald-900"><tr>{testResult.fields.map((field) => <th key={field} className="px-2 py-1 font-semibold">{field}</th>)}</tr></thead><tbody>{testResult.records.slice(0, 100).map((record, index) => <tr key={`record-${index}`} className="border-t border-emerald-100"><td colSpan={Math.max(testResult.fields.length, 1)} className="px-2 py-1 align-top"><code>{JSON.stringify(record)}</code></td></tr>)}</tbody></table></div></div>}
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '加密样例列表' : 'Encrypted samples'}</div>{samples.length ? <div className="space-y-1">{samples.map((sample) => <div key={sample.id} className="flex items-center justify-between gap-2 rounded-lg bg-white px-2.5 py-2 text-[10px] text-slate-500"><span className="min-w-0 truncate"><b className="text-slate-700">{sample.sample_name}</b> · {formatDate(sample.created_at, zh)}</span>{canSample && !isSystemTemplate && <button onClick={() => void removeSample(sample.id)} className="rounded p-1 text-rose-500 hover:bg-rose-50" title={zh ? '删除样例' : 'Delete sample'}><Trash2 size={12} /></button>}</div>)}</div> : <div className="text-[10px] text-slate-400">{zh ? '暂无已保存样例' : 'No stored samples'}</div>}</div>
              {compareVersion && <div className="space-y-2 rounded-xl border border-violet-100 bg-violet-50/50 p-3"><div className="flex items-center justify-between text-xs font-semibold text-violet-900"><span>{zh ? `Diff · v${compareVersion.version_number} → 当前编辑内容` : `Diff · v${compareVersion.version_number} → current editor`}</span><span className="text-[10px] font-normal">{sourceDiff.filter((row) => row.type === 'added').length} + / {sourceDiff.filter((row) => row.type === 'removed').length} −</span></div><div className="max-h-40 overflow-auto rounded-lg border border-violet-100 bg-slate-950 p-2 font-mono text-[10px] leading-5">{sourceDiff.slice(0, 300).map((row, index) => <div key={`${row.type}-${index}`} className={row.type === 'added' ? 'bg-emerald-900/50 text-emerald-200' : row.type === 'removed' ? 'bg-rose-900/50 text-rose-200' : 'text-slate-400'}><span className="mr-2 inline-block w-3 text-center text-slate-500">{row.type === 'added' ? '+' : row.type === 'removed' ? '−' : ' '}</span>{row.text || ' '}</div>)}</div><div className="text-[10px] text-violet-900">{zh ? '解析字段变化' : 'Parsed fields'}: +{addedFields.join(', ') || '—'} / −{removedFields.join(', ') || '—'}</div></div>}
              {audit.length > 0 && <details className="rounded-xl border border-black/5 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">{zh ? '审计记录' : 'Audit history'} ({audit.length})</summary><div className="mt-2 max-h-24 space-y-1 overflow-auto text-[10px] text-slate-500">{audit.map((item) => <div key={item.id}>{formatDate(item.created_at, zh)} · <b>{item.event_type}</b> · {item.actor_username || 'system'}</div>)}</div></details>}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default ParserRegistryTab;
