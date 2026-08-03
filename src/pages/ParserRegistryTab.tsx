import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, FileCode2, GitBranch, Loader2, PlayCircle, Plus, RefreshCw, Send, ShieldCheck, UploadCloud } from 'lucide-react';
import { apiRequest, ApiError } from '../api/http';

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
  field_contract_json?: string;
  test_summary_json?: string;
  submitted_by?: string;
  approved_by?: string;
  published_by?: string;
}

interface TestResult {
  records: Array<Record<string, unknown>>;
  fields: string[];
  summary?: { record_count?: number; fields?: string[]; field_coverage?: Record<string, number> };
}

type DiffRow = { type: 'context' | 'added' | 'removed'; text: string };

const buildLineDiff = (before: string, after: string): DiffRow[] => {
  const oldLines = before.split('\n');
  const newLines = after.split('\n');
  const cellCount = oldLines.length * newLines.length;
  if (cellCount > 200_000) {
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
  }

  const table = Array.from({ length: oldLines.length + 1 }, () => new Uint32Array(newLines.length + 1));
  for (let oldIndex = oldLines.length - 1; oldIndex >= 0; oldIndex -= 1) {
    for (let newIndex = newLines.length - 1; newIndex >= 0; newIndex -= 1) {
      table[oldIndex][newIndex] = oldLines[oldIndex] === newLines[newIndex]
        ? table[oldIndex + 1][newIndex + 1] + 1
        : Math.max(table[oldIndex + 1][newIndex], table[oldIndex][newIndex + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let oldIndex = 0;
  let newIndex = 0;
  while (oldIndex < oldLines.length && newIndex < newLines.length) {
    if (oldLines[oldIndex] === newLines[newIndex]) {
      rows.push({ type: 'context', text: oldLines[oldIndex] || '' });
      oldIndex += 1;
      newIndex += 1;
    } else if (table[oldIndex + 1][newIndex] >= table[oldIndex][newIndex + 1]) {
      rows.push({ type: 'removed', text: oldLines[oldIndex] });
      oldIndex += 1;
    } else {
      rows.push({ type: 'added', text: newLines[newIndex] });
      newIndex += 1;
    }
  }
  while (oldIndex < oldLines.length) rows.push({ type: 'removed', text: oldLines[oldIndex++] });
  while (newIndex < newLines.length) rows.push({ type: 'added', text: newLines[newIndex++] });
  return rows;
};

const parseTestSummary = (value?: string): { record_count?: number; fields?: string[]; field_coverage?: Record<string, number> } => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

interface Props {
  language: string;
}

const panelClass = 'rounded-2xl border border-black/5 bg-white shadow-sm';
const defaultContent = `Value FIELD (.*)\n\nStart\n  ^\\s*\${FIELD}\\s*$ -> Record\n`;

const errorMessage = (cause: unknown, fallback: string): string => (
  cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : fallback
);

const ParserRegistryTab: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';
  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [compareVersionId, setCompareVersionId] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [forking, setForking] = useState(false);
  const [testing, setTesting] = useState(false);
  const [regressionTesting, setRegressionTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [platformCode, setPlatformCode] = useState('cisco_ios');
  const [templateCode, setTemplateCode] = useState('CUSTOM_TEMPLATE');
  const [templateName, setTemplateName] = useState('');
  const [content, setContent] = useState(defaultContent);
  const [contract, setContract] = useState('{}');
  const [sampleOutput, setSampleOutput] = useState('');
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [editorScrollTop, setEditorScrollTop] = useState(0);

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) || null,
    [selectedTemplateId, templates],
  );
  const isSystemTemplate = selectedTemplate?.source === 'SYSTEM';
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
  const editorLineNumbers = useMemo(() => content.split('\n').map((_, index) => index + 1), [content]);
  const sourceDiff = useMemo(
    () => buildLineDiff(compareVersion?.content || '', content),
    [compareVersion?.content, content],
  );
  const currentTestSummary = testResult?.summary || parseTestSummary(selectedVersion?.test_summary_json);
  const compareTestSummary = parseTestSummary(compareVersion?.test_summary_json);
  const currentFields = new Set(testResult?.fields || currentTestSummary.fields || []);
  const compareFields = new Set(compareTestSummary.fields || []);
  const addedResultFields = Array.from(currentFields).filter((field) => !compareFields.has(field));
  const removedResultFields = Array.from(compareFields).filter((field) => !currentFields.has(field));

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiRequest<{ data: TemplateRecord[] }>('/api/parser-templates');
      const next = response.data || [];
      setTemplates(next);
      setSelectedTemplateId((current) => current && next.some((item) => item.id === current) ? current : (next[0]?.id || ''));
    } catch (cause) {
      setError(errorMessage(cause, zh ? '模板注册表加载失败' : 'Failed to load parser registry'));
    } finally {
      setLoading(false);
    }
  }, [zh]);

  const loadVersions = useCallback(async (templateId: string) => {
    if (!templateId) {
      setVersions([]);
      setSelectedVersionId('');
      return;
    }
    try {
      const response = await apiRequest<{ data: VersionRecord[] }>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`);
      const next = response.data || [];
      setVersions(next);
      setSelectedVersionId((current) => current && next.some((item) => item.id === current) ? current : (next[0]?.id || ''));
      setCompareVersionId((current) => current && next.some((item) => item.id === current) ? current : '');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '模板版本加载失败' : 'Failed to load parser versions'));
    }
  }, [zh]);

  useEffect(() => { void loadTemplates(); }, [loadTemplates]);
  useEffect(() => { void loadVersions(selectedTemplateId); }, [loadVersions, selectedTemplateId]);

  useEffect(() => {
    if (!selectedVersion) return;
    setContent(selectedVersion.content || '');
    setContract(selectedVersion.field_contract_json || '{}');
    setTestResult(null);
  }, [selectedVersion]);

  const resetFeedback = () => { setError(''); setMessage(''); };

  const createTemplateIfNeeded = async (): Promise<string> => {
    if (selectedTemplateId) return selectedTemplateId;
    const response = await apiRequest<{ data: TemplateRecord }>('/api/parser-templates', {
      method: 'POST',
      body: JSON.stringify({ platform_code: platformCode, template_code: templateCode, name: templateName || templateCode }),
    });
    const id = response.data.id;
    await loadTemplates();
    setSelectedTemplateId(id);
    return id;
  };

  const saveDraft = async () => {
    resetFeedback();
    if (isSystemTemplate) {
      setError(zh ? 'SYSTEM 模板只读，请先 Fork 为租户模板' : 'SYSTEM templates are read-only; fork it into a tenant template first');
      return;
    }
    if (!content.trim()) {
      setError(zh ? '模板内容不能为空' : 'Template content is required');
      return;
    }
    try {
      setSaving(true);
      const templateId = await createTemplateIfNeeded();
      const response = await apiRequest<{ data: VersionRecord }>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`, {
        method: 'POST',
        body: JSON.stringify({ content, field_contract: JSON.parse(contract || '{}') }),
      });
      await loadVersions(templateId);
      setSelectedVersionId(response.data.id);
      setMessage(zh ? '草稿版本已保存' : 'Draft version saved');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '草稿保存失败；请检查字段契约 JSON' : 'Draft save failed; check field contract JSON'));
    } finally {
      setSaving(false);
    }
  };

  const forkSelectedTemplate = async () => {
    if (!selectedTemplate || !isSystemTemplate) return;
    const defaultCode = `${selectedTemplate.template_code}_FORK`.slice(0, 64);
    const forkCode = window.prompt(
      zh ? '请输入 Fork 后的租户模板编码（大写字母、数字、下划线）' : 'Enter the forked tenant template code (uppercase letters, digits and underscores)',
      defaultCode,
    )?.trim().toUpperCase();
    if (!forkCode) return;
    const forkName = window.prompt(
      zh ? '请输入 Fork 后的租户模板名称' : 'Enter the forked tenant template name',
      `${selectedTemplate.name || selectedTemplate.template_code} · Fork`,
    )?.trim() || `${selectedTemplate.name || selectedTemplate.template_code} · Fork`;
    resetFeedback();
    try {
      setForking(true);
      const response = await apiRequest<{ data: TemplateRecord }>(`/api/parser-templates/${encodeURIComponent(selectedTemplate.id)}/fork`, {
        method: 'POST',
        body: JSON.stringify({ template_code: forkCode, name: forkName }),
      });
      await loadTemplates();
      setSelectedTemplateId(response.data.id);
      setMessage(zh ? 'SYSTEM 模板已 Fork 为租户模板，可继续编辑草稿' : 'SYSTEM template forked into an editable tenant template');
    } catch (cause) {
      setError(errorMessage(cause, zh ? 'Fork 租户模板失败' : 'Failed to fork tenant template'));
    } finally {
      setForking(false);
    }
  };

  const runTest = async () => {
    resetFeedback();
    if (!selectedVersionId || !sampleOutput.trim()) {
      setError(zh ? '请先选择版本并提供测试回显' : 'Select a version and provide sample output');
      return;
    }
    try {
      setTesting(true);
      const response = await apiRequest<{ data: TestResult }>(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/test`, {
        method: 'POST',
        body: JSON.stringify({ sample_output: sampleOutput }),
      });
      setTestResult(response.data);
      await loadVersions(selectedTemplateId);
      setMessage(zh ? 'Sandbox 测试通过' : 'Sandbox test passed');
    } catch (cause) {
      setTestResult(null);
      setError(errorMessage(cause, zh ? 'Sandbox 测试失败' : 'Sandbox test failed'));
    } finally {
      setTesting(false);
    }
  };

  const transition = async (action: 'submit' | 'approve' | 'publish') => {
    if (!selectedVersionId) return;
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/${action}`, { method: 'POST' });
      await loadVersions(selectedTemplateId);
      setMessage(zh ? `版本${action === 'submit' ? '已提交' : action === 'approve' ? '已审批' : '已发布'}` : `Version ${action} completed`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '版本流转失败' : 'Version transition failed'));
    }
  };

  const uploadSample = async () => {
    if (!selectedVersionId || !sampleOutput.trim()) return;
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/samples`, {
        method: 'POST',
        body: JSON.stringify({ sample_name: 'editor-sample', sample_output: sampleOutput }),
      });
      setMessage(zh ? '样例已加密保存' : 'Sample encrypted and stored');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '样例保存失败' : 'Sample upload failed'));
    }
  };

  const runRegression = async () => {
    if (!selectedTemplateId) return;
    resetFeedback();
    try {
      setRegressionTesting(true);
      const response = await apiRequest<{ data: { sample_count?: number; passed?: boolean } }>(
        `/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/regression-test`,
        { method: 'POST', body: JSON.stringify(selectedVersionId ? { version_id: selectedVersionId } : {}) },
      );
      setMessage(zh ? `历史样例回归通过（${response.data?.sample_count || 0} 个样例）` : `Historical regression passed (${response.data?.sample_count || 0} samples)`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '历史样例回归失败' : 'Historical regression failed'));
    } finally {
      setRegressionTesting(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold text-slate-800"><FileCode2 size={20} className="text-[#00bceb]" />{zh ? 'TextFSM 注册表开发' : 'TextFSM Registry Development'}</div>
          <p className="mt-1 text-xs text-slate-500">{zh ? '租户隔离草稿、Sandbox 测试、加密样例与受控发布' : 'Tenant-scoped drafts, sandbox tests, encrypted samples and controlled release'}</p>
        </div>
        <button onClick={() => void loadTemplates()} className="rounded-lg border border-black/10 bg-white p-2 text-slate-500 hover:text-[#00bceb]" title={zh ? '刷新' : 'Refresh'}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>
      </div>

      {(error || message) && <div className={`rounded-xl border px-3 py-2 text-xs ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)] gap-4">
        <aside className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
          <div className="flex items-center justify-between border-b border-black/5 px-4 py-3 text-xs font-semibold text-slate-700"><span>{zh ? '模板' : 'Templates'}</span><Plus size={14} className="text-slate-400" /></div>
          <div className="space-y-1 overflow-y-auto p-2">
            {templates.map((template) => (
              <button key={template.id} onClick={() => setSelectedTemplateId(template.id)} className={`w-full rounded-lg px-3 py-2 text-left ${selectedTemplateId === template.id ? 'bg-cyan-50 text-cyan-800' : 'hover:bg-slate-50'}`}>
                <div className="truncate text-xs font-semibold">{template.template_code}</div>
                <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-slate-400"><span>{template.platform_code}</span><span>{template.source}</span></div>
              </button>
            ))}
            {!templates.length && <div className="p-4 text-center text-xs text-slate-400">{zh ? '暂无可见模板；功能开关关闭或尚未创建' : 'No visible templates'}</div>}
          </div>
          <div className="mt-auto space-y-2 border-t border-black/5 p-3">
            <input value={platformCode} onChange={(event) => setPlatformCode(event.target.value)} placeholder="platform_code" className="w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs" />
            <input value={templateCode} onChange={(event) => setTemplateCode(event.target.value.toUpperCase())} placeholder="TEMPLATE_CODE" className="w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs" />
            <input value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder={zh ? '模板名称（新建时使用）' : 'Template name'} className="w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs" />
          </div>
        </aside>

        <main className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/5 px-4 py-3">
            <div className="flex items-center gap-2 text-xs text-slate-500"><GitBranch size={14} />{selectedTemplate ? selectedTemplate.template_code : (zh ? '新建模板' : 'New template')}{isSystemTemplate && <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">{zh ? 'SYSTEM 只读' : 'SYSTEM read-only'}</span>}</div>
            <div className="flex flex-wrap gap-2">
              {isSystemTemplate ? <button onClick={() => void forkSelectedTemplate()} disabled={forking} className="inline-flex items-center gap-1 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{forking ? <Loader2 size={13} className="animate-spin" /> : <GitBranch size={13} />}{zh ? 'Fork 为租户模板' : 'Fork to tenant template'}</button> : <button onClick={() => void saveDraft()} disabled={saving} className="inline-flex items-center gap-1 rounded-lg bg-[#00bceb] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}{zh ? '保存草稿' : 'Save draft'}</button>}
              <button onClick={() => void runTest()} disabled={testing || !selectedVersionId} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40"><PlayCircle size={13} />{zh ? 'Sandbox 测试' : 'Sandbox test'}</button>
              <button onClick={() => void uploadSample()} disabled={isSystemTemplate || !selectedVersionId || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40"><UploadCloud size={13} />{zh ? '加密上传样例' : 'Upload encrypted sample'}</button>
            </div>
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-2 gap-3 overflow-auto p-4">
            <div className="flex min-h-0 flex-col gap-3">
              <label className="flex min-h-[280px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '模板内容（带行号）' : 'Template content (with line numbers)'}
                <div className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-black/10 bg-slate-950 focus-within:border-cyan-400">
                  <div aria-hidden="true" className="pointer-events-none absolute left-0 top-0 z-10 w-10 select-none border-r border-white/10 bg-slate-900/80 px-2 py-3 text-right font-mono text-xs leading-5 text-slate-500" style={{ transform: `translateY(-${editorScrollTop}px)` }}>
                    {editorLineNumbers.map((lineNumber) => <div key={lineNumber}>{lineNumber}</div>)}
                  </div>
                  <textarea value={content} readOnly={isSystemTemplate} aria-label={zh ? 'TextFSM 模板内容' : 'TextFSM template content'} onChange={(event) => setContent(event.target.value)} onScroll={(event) => setEditorScrollTop(event.currentTarget.scrollTop)} className={`h-full min-h-[280px] w-full resize-none bg-transparent py-3 pl-12 pr-3 font-mono text-xs leading-5 outline-none ${isSystemTemplate ? 'cursor-not-allowed text-slate-400' : 'text-slate-100'}`} spellCheck={false} />
                </div>
              </label>
              <label className="flex min-h-[120px] flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '字段契约 JSON' : 'Field contract JSON'}<textarea value={contract} readOnly={isSystemTemplate} aria-label={zh ? '字段契约 JSON' : 'Field contract JSON'} onChange={(event) => setContract(event.target.value)} className={`min-h-0 flex-1 resize-none rounded-xl border border-black/10 p-3 font-mono text-xs leading-5 outline-none ${isSystemTemplate ? 'cursor-not-allowed bg-slate-100 text-slate-400' : 'bg-slate-50 text-slate-700 focus:border-cyan-400'}`} spellCheck={false} /></label>
            </div>
            <div className="flex min-h-0 flex-col gap-3">
              <label className="flex min-h-[220px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '测试回显（仅用于 Sandbox/加密样例）' : 'Sample output (sandbox/encrypted sample)'}<textarea value={sampleOutput} onChange={(event) => setSampleOutput(event.target.value)} className="min-h-0 flex-1 resize-none rounded-xl border border-black/10 bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700 outline-none focus:border-cyan-400" spellCheck={false} /></label>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3">
                <div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '版本与发布' : 'Version lifecycle'}</div>
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {versions.map((version) => <button key={version.id} onClick={() => setSelectedVersionId(version.id)} className={`rounded-md px-2 py-1 text-[10px] ${selectedVersionId === version.id ? 'bg-cyan-600 text-white' : 'bg-white text-slate-500 ring-1 ring-black/5'}`}>v{version.version_number} · {version.status}</button>)}
                </div>
                {versions.length > 1 && <label className="mb-2 flex items-center gap-2 text-[10px] text-slate-500"><span>{zh ? '对比基线' : 'Compare baseline'}</span><select value={compareVersion?.id || ''} onChange={(event) => setCompareVersionId(event.target.value)} className="min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-[10px] text-slate-600"><option value="">{zh ? '自动选择上一版本' : 'Auto-select previous version'}</option>{versions.filter((version) => version.id !== selectedVersionId).map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {version.status}</option>)}</select></label>}
                {selectedVersion && <div className="flex flex-wrap gap-2">
                  <button onClick={() => void runRegression()} disabled={regressionTesting} className="inline-flex items-center gap-1 rounded-md border border-cyan-200 bg-white px-2 py-1 text-[10px] font-semibold text-cyan-700 disabled:opacity-50"><CheckCircle2 size={11} />{regressionTesting ? (zh ? '回归中…' : 'Running…') : (zh ? '历史回归' : 'Regression')}</button>
                  {selectedVersion.status === 'DRAFT' && <button onClick={() => void transition('submit')} className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-2 py-1 text-[10px] font-semibold text-white"><Send size={11} />{zh ? '提交审核' : 'Submit'}</button>}
                  {selectedVersion.status === 'IN_REVIEW' && <button onClick={() => void transition('approve')} className="inline-flex items-center gap-1 rounded-md bg-indigo-500 px-2 py-1 text-[10px] font-semibold text-white"><ShieldCheck size={11} />{zh ? '审批' : 'Approve'}</button>}
                  {selectedVersion.status === 'APPROVED' && <button onClick={() => void transition('publish')} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-[10px] font-semibold text-white"><CheckCircle2 size={11} />{zh ? '发布' : 'Publish'}</button>}
                </div>}
              </div>
              {testResult && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"><div className="font-semibold">{zh ? '测试结果' : 'Test result'} · {testResult.summary?.record_count ?? testResult.records.length} {zh ? '条记录' : 'records'}</div><div className="mt-1">{zh ? '字段' : 'Fields'}: {testResult.fields.join(', ') || '—'}</div></div>}
              {compareVersion && <div className="space-y-3 rounded-xl border border-violet-100 bg-violet-50/50 p-3">
                <div className="flex items-center justify-between gap-2 text-xs font-semibold text-violet-900"><span>{zh ? `Diff · v${compareVersion.version_number} → 当前编辑内容` : `Diff · v${compareVersion.version_number} → current editor`}</span><span className="text-[10px] font-normal text-violet-700/70">{sourceDiff.filter((row) => row.type === 'added').length} + / {sourceDiff.filter((row) => row.type === 'removed').length} −</span></div>
                <div className="max-h-48 overflow-auto rounded-lg border border-violet-100 bg-slate-950 p-2 font-mono text-[10px] leading-5">
                  {sourceDiff.slice(0, 500).map((row, index) => <div key={`${row.type}-${index}`} className={row.type === 'added' ? 'bg-emerald-900/50 text-emerald-200' : row.type === 'removed' ? 'bg-rose-900/50 text-rose-200' : 'text-slate-400'}><span className="mr-2 inline-block w-3 select-none text-center text-slate-500">{row.type === 'added' ? '+' : row.type === 'removed' ? '−' : ' '}</span>{row.text || ' '}</div>)}
                  {!sourceDiff.length && <div className="text-slate-500">{zh ? '暂无差异' : 'No differences'}</div>}
                  {sourceDiff.length > 500 && <div className="mt-1 text-slate-500">{zh ? '仅展示前 500 行差异' : 'Showing first 500 diff rows'}</div>}
                </div>
                <div className="rounded-lg border border-violet-100 bg-white px-2.5 py-2 text-[10px] text-violet-900">
                  <div className="font-semibold">{zh ? '解析结果 Diff' : 'Parsed result diff'}</div>
                  <div className="mt-1">{zh ? '记录数' : 'Records'}: {compareTestSummary.record_count ?? '—'} → {currentTestSummary.record_count ?? '—'}</div>
                  <div className="mt-1">{zh ? '新增字段' : 'Added fields'}: {addedResultFields.join(', ') || '—'} · {zh ? '移除字段' : 'Removed fields'}: {removedResultFields.join(', ') || '—'}</div>
                </div>
              </div>}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default ParserRegistryTab;
