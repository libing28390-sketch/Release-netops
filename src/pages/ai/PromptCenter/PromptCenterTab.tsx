import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Copy,
  Eye,
  FileCode2,
  GitCompareArrows,
  History,
  Info,
  Layers3,
  Pencil,
  Play,
  Plus,
  Power,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  RotateCcw,
  X,
  type LucideIcon,
} from 'lucide-react';
import {
  compareAIPromptVersions,
  copyAIPrompt,
  createAIPrompt,
  getAIPromptAudit,
  getAIPromptVersions,
  getAIPromptsPage,
  restoreAIPromptVersion,
  updateAIPrompt,
  type AIPrompt,
  type AIPromptAuditEvent,
  type AIPromptVersion,
  type AIPromptVersionCompare,
} from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import Pagination from '../../../components/Pagination';
import { aiAdminText } from '../../../i18n/aiAdmin';

const sceneOptions = [
  { value: 'chat', labelKey: 'ai.prompt.scene.chat.label', shortLabelKey: 'ai.prompt.scene.chat.short', descriptionKey: 'ai.prompt.scene.chat.description' },
  { value: 'troubleshooting', labelKey: 'ai.prompt.scene.troubleshooting.label', shortLabelKey: 'ai.prompt.scene.troubleshooting.short', descriptionKey: 'ai.prompt.scene.troubleshooting.description' },
  { value: 'command_explain', labelKey: 'ai.prompt.scene.command_explain.label', shortLabelKey: 'ai.prompt.scene.command_explain.short', descriptionKey: 'ai.prompt.scene.command_explain.description' },
  { value: 'config_explain', labelKey: 'ai.prompt.scene.config_explain.label', shortLabelKey: 'ai.prompt.scene.config_explain.short', descriptionKey: 'ai.prompt.scene.config_explain.description' },
  { value: 'config_diff', labelKey: 'ai.prompt.scene.config_diff.label', shortLabelKey: 'ai.prompt.scene.config_diff.short', descriptionKey: 'ai.prompt.scene.config_diff.description' },
  { value: 'alarm_analysis', labelKey: 'ai.prompt.scene.alarm_analysis.label', shortLabelKey: 'ai.prompt.scene.alarm_analysis.short', descriptionKey: 'ai.prompt.scene.alarm_analysis.description' },
  { value: 'topology_analysis', labelKey: 'ai.prompt.scene.topology_analysis.label', shortLabelKey: 'ai.prompt.scene.topology_analysis.short', descriptionKey: 'ai.prompt.scene.topology_analysis.description' },
  { value: 'health_summary', labelKey: 'ai.prompt.scene.health_summary.label', shortLabelKey: 'ai.prompt.scene.health_summary.short', descriptionKey: 'ai.prompt.scene.health_summary.description' },
  { value: 'compliance_audit', labelKey: 'ai.prompt.scene.compliance_audit.label', shortLabelKey: 'ai.prompt.scene.compliance_audit.short', descriptionKey: 'ai.prompt.scene.compliance_audit.description' },
  { value: 'change_plan', labelKey: 'ai.prompt.scene.change_plan.label', shortLabelKey: 'ai.prompt.scene.change_plan.short', descriptionKey: 'ai.prompt.scene.change_plan.description' },
  { value: 'rag_answer', labelKey: 'ai.prompt.scene.rag_answer.label', shortLabelKey: 'ai.prompt.scene.rag_answer.short', descriptionKey: 'ai.prompt.scene.rag_answer.description' },
  { value: 'capacity_analysis', labelKey: 'ai.prompt.scene.capacity_analysis.label', shortLabelKey: 'ai.prompt.scene.capacity_analysis.short', descriptionKey: 'ai.prompt.scene.capacity_analysis.description' },
];

const sceneMap = Object.fromEntries(sceneOptions.map((item) => [item.value, item]));
const SAMPLE_VARIABLE_KEYS: Record<string, string> = {
  input: 'ai.prompt.sample.input',
  command: 'ai.prompt.sample.command',
  output: 'ai.prompt.sample.output',
  vendor: 'ai.prompt.sample.vendor',
  platform: 'ai.prompt.sample.platform',
  config_text: 'ai.prompt.sample.configText',
  diff_text: 'ai.prompt.sample.diffText',
  alarm_title: 'ai.prompt.sample.alarmTitle',
  severity: 'ai.prompt.sample.severity',
  fingerprint: 'ai.prompt.sample.fingerprint',
  raw_content: 'ai.prompt.sample.rawContent',
  context_data: 'ai.prompt.sample.contextData',
  topology_data: 'ai.prompt.sample.topologyData',
  symptom: 'ai.prompt.sample.symptom',
  device_snapshot: 'ai.prompt.sample.deviceSnapshot',
  metrics_window: 'ai.prompt.sample.metricsWindow',
  policy: 'ai.prompt.sample.policy',
  objective: 'ai.prompt.sample.objective',
  current_state: 'ai.prompt.sample.currentState',
  constraints: 'ai.prompt.sample.constraints',
  question: 'ai.prompt.sample.question',
  context: 'ai.prompt.sample.context',
  citations: 'ai.prompt.sample.citations',
  metrics: 'ai.prompt.sample.metrics',
  threshold: 'ai.prompt.sample.threshold',
  window: 'ai.prompt.sample.window',
};

function sampleVariables(language: 'zh' | 'en'): Record<string, string> {
  return Object.fromEntries(
    Object.entries(SAMPLE_VARIABLE_KEYS).map(([name, key]) => [name, aiAdminText(key, language)]),
  );
}

const cn = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(' ');
const getErrorMessage = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
type TextVariables = Record<string, string | number>;

const PROMPT_VERSION_TYPE_LABELS: Record<string, string> = {
  create: 'ai.prompt.version.create',
  update: 'ai.prompt.version.update',
  copy: 'ai.prompt.version.copy',
  restore: 'ai.prompt.version.restore',
};
const PROMPT_AUDIT_EVENT_LABELS: Record<string, string> = {
  ai_prompt_create: 'ai.prompt.audit.create',
  ai_prompt_update: 'ai.prompt.audit.update',
  ai_prompt_copy: 'ai.prompt.audit.copy',
  ai_prompt_restore: 'ai.prompt.audit.restore',
};
const PROMPT_FIELD_LABELS: Record<string, string> = {
  system_prompt: 'ai.prompt.field.system',
  user_prompt_template: 'ai.prompt.field.user',
  output_schema: 'ai.prompt.field.output',
  temperature: 'ai.prompt.field.temperature',
  max_tokens: 'ai.prompt.field.maxTokens',
};

function promptDataLabel(tx: (key: string, variables?: TextVariables) => string, labels: Record<string, string>, value: string): string {
  return labels[value] ? tx(labels[value]) : value;
}

interface PromptStatProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
  helper: string;
  tone: string;
}

const PromptStat: React.FC<PromptStatProps> = ({ icon: Icon, label, value, helper, tone }) => (
  <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none">
    <div className="flex items-start justify-between gap-3">
      <div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">{label}</p><p className="mt-2 text-2xl font-bold tracking-tight text-slate-900 dark:text-white">{value}</p></div>
      <span className={cn('flex h-9 w-9 items-center justify-center rounded-xl', tone)}><Icon className="h-4 w-4" /></span>
    </div>
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{helper}</p>
  </div>
);

const PromptBlock: React.FC<{ label: string; value: string; compact?: boolean; charsLabel?: string }> = ({ label, value, compact, charsLabel = 'chars' }) => (
  <div className={cn('rounded-2xl border border-slate-100 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-950/50', compact ? 'min-h-[108px]' : 'min-h-[128px]')}>
    <div className="mb-2 flex items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500">{label}</span><span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] font-mono text-slate-400 shadow-sm dark:bg-slate-900 dark:text-slate-500">{value.length} {charsLabel}</span></div>
    <p className={cn('whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-slate-600 dark:text-slate-300', compact && 'line-clamp-4')}>{value || '—'}</p>
  </div>
);

function extractVariables(template: string): string[] {
  const variables = new Set<string>();
  const matcher = /\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}|\{([A-Za-z0-9_.-]+)\}/g;
  let match: RegExpExecArray | null;
  while ((match = matcher.exec(template)) !== null) variables.add(match[1] || match[2]);
  return Array.from(variables);
}

function previewValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function renderPromptTemplate(template: string, variables: Record<string, unknown>, language: 'zh' | 'en'): string {
  const matcher = /\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}|\{([A-Za-z0-9_.-]+)\}/g;
  return template.replace(matcher, (_match, jinjaKey: string, simpleKey: string) => {
    const key = jinjaKey || simpleKey;
    return Object.prototype.hasOwnProperty.call(variables, key) ? previewValue(variables[key]) : aiAdminText('ai.prompt.preview.missing', language, { name: key });
  });
}

function validateOutputSchema(value: string, language: 'zh' | 'en'): { valid: boolean; message: string } {
  try {
    const parsed = JSON.parse(value || '{}');
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return { valid: false, message: aiAdminText('ai.prompt.validation.schemaObject', language) };
    return { valid: true, message: aiAdminText('ai.prompt.validation.schemaValid', language) };
  } catch { return { valid: false, message: aiAdminText('ai.prompt.validation.schemaJson', language) }; }
}

function formatDate(value?: string, emptyLabel = '—'): string {
  if (!value) return emptyLabel;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

const modalInputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white';

export const PromptCenterTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const tx = (key: string, variables?: TextVariables) => aiAdminText(key, language, variables);
  const localizedSampleVariables = useMemo(() => sampleVariables(language), [language]);
  const [prompts, setPrompts] = useState<AIPrompt[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPrompt, setSelectedPrompt] = useState<AIPrompt | null>(null);
  const [selectedVersions, setSelectedVersions] = useState<AIPromptVersion[]>([]);
  const [selectedAudit, setSelectedAudit] = useState<AIPromptAuditEvent[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<AIPrompt | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [editorError, setEditorError] = useState('');
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [sceneFilter, setSceneFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [compareLeft, setCompareLeft] = useState(0);
  const [compareRight, setCompareRight] = useState(0);
  const [compareResult, setCompareResult] = useState<AIPromptVersionCompare | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [restoreVersion, setRestoreVersion] = useState<AIPromptVersion | null>(null);
  const [restoreReason, setRestoreReason] = useState('');
  const [restoreSubmitting, setRestoreSubmitting] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyCode, setCopyCode] = useState('');
  const [copyName, setCopyName] = useState('');
  const [copyReason, setCopyReason] = useState('');
  const [copySubmitting, setCopySubmitting] = useState(false);

  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [scene, setScene] = useState('chat');
  const [vendor, setVendor] = useState('all');
  const [platform, setPlatform] = useState('all');
  const [systemPrompt, setSystemPrompt] = useState(() => tx('ai.prompt.default.system'));
  const [userPromptTemplate, setUserPromptTemplate] = useState(() => tx('ai.prompt.default.user'));
  const [outputSchema, setOutputSchema] = useState(() => tx('ai.prompt.default.output'));
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [formEnabled, setFormEnabled] = useState(true);
  const [changeReason, setChangeReason] = useState('');

  const fetchPrompts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getAIPromptsPage({
        search: appliedSearch,
        scene: sceneFilter,
        enabled: statusFilter === 'all' ? undefined : statusFilter === 'enabled',
        page,
        page_size: pageSize,
      });
      setPrompts(result.items);
      setTotal(result.total);
    } catch (err: unknown) {
      const message = getErrorMessage(err, tx('ai.prompt.error.list'));
      setError(message);
      showToast(message, 'error');
    } finally { setLoading(false); }
  }, [appliedSearch, language, page, pageSize, sceneFilter, showToast, statusFilter]);

  useEffect(() => { void fetchPrompts(); }, [fetchPrompts]);

  const enabledCount = prompts.filter((prompt) => prompt.enabled).length;
  const sceneCount = new Set(prompts.map((prompt) => prompt.scene)).size;
  const latestVersion = prompts.reduce((max, prompt) => Math.max(max, prompt.version || 0), 0);
  const selectedScene = useMemo(() => selectedPrompt ? sceneMap[selectedPrompt.scene] : null, [selectedPrompt]);
  const createScene = sceneMap[scene] || sceneOptions[0];
  const formVariables = useMemo(() => extractVariables(userPromptTemplate), [userPromptTemplate]);
  const schemaStatus = useMemo(() => validateOutputSchema(outputSchema, language), [language, outputSchema]);

  const loadHistory = useCallback(async (promptId: string) => {
    setVersionsLoading(true);
    setAuditLoading(true);
    try {
      const versions = await getAIPromptVersions(promptId);
      setSelectedVersions(versions);
      const current = versions[0];
      const older = versions.find((item) => item.version !== current?.version);
      setCompareLeft(older?.version || current?.version || 0);
      setCompareRight(current?.version || 0);
      setCompareResult(null);
    } catch (err: unknown) {
      showToast(getErrorMessage(err, tx('ai.prompt.error.versions')), 'error');
    } finally { setVersionsLoading(false); }
    try {
      const audit = await getAIPromptAudit(promptId, { page: 1, page_size: 20 });
      setSelectedAudit(audit.items);
    } catch (err: unknown) {
      showToast(getErrorMessage(err, tx('ai.prompt.error.audit')), 'error');
    } finally { setAuditLoading(false); }
  }, [language, showToast]);

  const resetForm = () => {
    setCode(''); setName(''); setScene('chat'); setVendor('all'); setPlatform('all');
    setSystemPrompt(tx('ai.prompt.default.system')); setUserPromptTemplate(tx('ai.prompt.default.user'));
    setOutputSchema(tx('ai.prompt.default.output')); setTemperature(0.2); setMaxTokens(2048);
    setFormEnabled(true); setChangeReason(''); setEditorError('');
  };

  const openCreateEditor = () => { setEditingPrompt(null); resetForm(); setEditorOpen(true); };

  const openEditEditor = (prompt: AIPrompt) => {
    setEditingPrompt(prompt); setCode(prompt.code); setName(prompt.name); setScene(prompt.scene);
    setVendor(prompt.vendor || 'all'); setPlatform(prompt.platform || 'all');
    setSystemPrompt(prompt.system_prompt); setUserPromptTemplate(prompt.user_prompt_template);
    setOutputSchema(prompt.output_schema || '{}'); setTemperature(prompt.temperature ?? 0.2);
    setMaxTokens(prompt.max_tokens ?? 2048); setFormEnabled(prompt.enabled); setChangeReason('');
    setEditorError(''); setEditorOpen(true);
  };

  const closeEditor = () => { if (!submitting) setEditorOpen(false); };

  const handleSavePrompt = async (event: React.FormEvent) => {
    event.preventDefault();
    const normalizedCode = code.trim();
    const normalizedName = name.trim();
    const normalizedSystem = systemPrompt.trim();
    const normalizedUserTemplate = userPromptTemplate.trim();
    const normalizedSchema = outputSchema.trim() || '{}';
    if (!editingPrompt && !normalizedCode) { setEditorError(tx('ai.prompt.error.codeRequired')); return; }
    if (!normalizedName || !normalizedSystem || !normalizedUserTemplate) { setEditorError(tx('ai.prompt.error.fieldsRequired')); return; }
    if (editingPrompt && !changeReason.trim()) { setEditorError(tx('ai.prompt.error.reasonRequired')); return; }
    const currentSchemaStatus = validateOutputSchema(normalizedSchema, language);
    if (!currentSchemaStatus.valid) { setEditorError(currentSchemaStatus.message); return; }
    setSubmitting(true); setEditorError('');
    try {
      const saved = editingPrompt
        ? await updateAIPrompt(editingPrompt.id, {
          name: normalizedName, scene, vendor: vendor.trim() || 'all', platform: platform.trim() || 'all',
          system_prompt: normalizedSystem, user_prompt_template: normalizedUserTemplate, output_schema: normalizedSchema,
          temperature, max_tokens: maxTokens, enabled: formEnabled, expected_version: editingPrompt.version,
          change_reason: changeReason.trim(),
        })
        : await createAIPrompt({
          code: normalizedCode, name: normalizedName, scene, vendor: vendor.trim() || 'all', platform: platform.trim() || 'all',
          system_prompt: normalizedSystem, user_prompt_template: normalizedUserTemplate, output_schema: normalizedSchema,
          temperature, max_tokens: maxTokens, enabled: formEnabled, change_reason: changeReason.trim() || tx('ai.prompt.reason.create'),
        });
      setSelectedPrompt((current) => current?.id === saved.id ? saved : current);
      setEditorOpen(false);
      await fetchPrompts();
      showToast(editingPrompt ? tx('ai.prompt.toast.saved') : tx('ai.prompt.toast.created'), 'success');
    } catch (err: unknown) {
      setEditorError(getErrorMessage(err, editingPrompt ? tx('ai.prompt.error.save') : tx('ai.prompt.error.create')));
    } finally { setSubmitting(false); }
  };

  const handleTogglePrompt = async (prompt: AIPrompt) => {
    try {
      const saved = await updateAIPrompt(prompt.id, {
        enabled: !prompt.enabled,
        expected_version: prompt.version,
        change_reason: tx('ai.prompt.reason.toggle', { status: tx(prompt.enabled ? 'ai.prompt.status.disabled' : 'ai.prompt.status.enabled') }),
      });
      setPrompts((current) => current.map((item) => item.id === saved.id ? saved : item));
      setSelectedPrompt((current) => current?.id === saved.id ? saved : current);
      showToast(tx('ai.prompt.toast.toggled', { name: prompt.name, status: tx(saved.enabled ? 'ai.prompt.status.enabled' : 'ai.prompt.status.disabled') }), 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, tx('ai.prompt.error.toggle')), 'error');
    }
  };

  const openPromptDetails = async (prompt: AIPrompt) => {
    setSelectedPrompt(prompt); setShowPreview(false); setSelectedVersions([]); setSelectedAudit([]);
    await loadHistory(prompt.id);
  };

  const handleCompare = async () => {
    if (!selectedPrompt || !compareLeft || !compareRight || compareLeft === compareRight) return;
    setCompareLoading(true);
    try { setCompareResult(await compareAIPromptVersions(selectedPrompt.id, compareLeft, compareRight)); }
    catch (err: unknown) { showToast(getErrorMessage(err, tx('ai.prompt.error.compare')), 'error'); }
    finally { setCompareLoading(false); }
  };

  const openCopyModal = (prompt: AIPrompt) => {
    setSelectedPrompt(prompt); setCopyCode(prompt.code + '_copy'); setCopyName(prompt.name + ' ' + tx('ai.prompt.copy.suffix'));
    setCopyReason(''); setCopyOpen(true);
  };

  const handleCopy = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedPrompt || !copyCode.trim() || !copyReason.trim()) return;
    setCopySubmitting(true);
    try {
      const copied = await copyAIPrompt(selectedPrompt.id, { code: copyCode.trim(), name: copyName.trim() || undefined, change_reason: copyReason.trim() });
      setCopyOpen(false); await fetchPrompts();
      showToast(tx('ai.prompt.toast.copied'), 'success');
      setSelectedPrompt(copied); await loadHistory(copied.id);
    } catch (err: unknown) {
      showToast(getErrorMessage(err, tx('ai.prompt.error.copy')), 'error');
    } finally { setCopySubmitting(false); }
  };

  const openRestoreModal = (version: AIPromptVersion) => { setRestoreVersion(version); setRestoreReason(''); };

  const handleRestore = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedPrompt || !restoreVersion || !restoreReason.trim()) return;
    setRestoreSubmitting(true);
    try {
      const saved = await restoreAIPromptVersion(selectedPrompt.id, restoreVersion.version, { change_reason: restoreReason.trim(), expected_current_version: selectedPrompt.version });
      setSelectedPrompt(saved); setRestoreVersion(null); await fetchPrompts(); await loadHistory(saved.id);
      showToast(tx('ai.prompt.toast.restored'), 'success');
    } catch (err: unknown) { showToast(getErrorMessage(err, tx('ai.prompt.error.restore')), 'error'); }
    finally { setRestoreSubmitting(false); }
  };

  const clearFilters = () => { setSearch(''); setAppliedSearch(''); setSceneFilter(''); setStatusFilter('all'); setPage(1); };
  const emptySearchResult = !loading && total > 0 && prompts.length === 0;

  return (
    <div className="w-full space-y-5 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-violet-100/80 bg-gradient-to-br from-white via-violet-50/70 to-indigo-100/70 px-5 py-6 shadow-sm shadow-violet-100/50 dark:border-violet-900/60 dark:from-slate-900 dark:via-violet-950/40 dark:to-slate-900 dark:shadow-none sm:px-7 sm:py-7">
        <div className="relative flex flex-col justify-between gap-6 xl:flex-row xl:items-center"><div className="max-w-4xl">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-violet-200/80 bg-white/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-violet-600 dark:border-violet-800 dark:bg-violet-950/50 dark:text-violet-300"><Sparkles className="h-3.5 w-3.5" />{tx('ai.prompt.header.eyebrow')}</div>
          <h2 className="nx-page-title flex items-center gap-3 text-slate-950 dark:text-white"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-600 text-white shadow-lg shadow-violet-600/25"><FileCode2 className="h-6 w-6" /></span>{tx('ai.prompt.header.title')}</h2>
          <p className="nx-page-description mt-3 max-w-3xl text-slate-600 dark:text-slate-300">{tx('ai.prompt.header.description')}</p>
        </div><div className="flex shrink-0 items-center gap-2 self-start xl:self-center">
          <button type="button" onClick={() => void fetchPrompts()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-white/90 bg-white/80 px-3.5 py-2.5 text-sm font-semibold text-slate-600 shadow-sm transition hover:border-violet-200 hover:bg-white hover:text-violet-600 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300"><RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />{tx('ai.common.refresh')}</button>
          <button type="button" onClick={openCreateEditor} className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-600/20 transition hover:bg-violet-700"><Plus className="h-4 w-4" />{tx('ai.prompt.action.add')}</button>
        </div></div>
      </section>

      <section className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <form onSubmit={(event) => { event.preventDefault(); setPage(1); setAppliedSearch(search.trim()); }} className="relative min-w-[260px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={tx('ai.prompt.search.placeholder')} className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-violet-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></form>
        <select value={sceneFilter} onChange={(event) => { setSceneFilter(event.target.value); setPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">{tx('ai.prompt.filter.allScenes')}</option>{sceneOptions.map((option) => <option key={option.value} value={option.value}>{tx(option.shortLabelKey)}</option>)}</select>
        <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="all">{tx('ai.prompt.filter.allStatuses')}</option><option value="enabled">{tx('ai.prompt.filter.enabled')}</option><option value="disabled">{tx('ai.prompt.filter.disabled')}</option></select>
        {(appliedSearch || sceneFilter || statusFilter !== 'all') && <button type="button" onClick={clearFilters} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-500 hover:border-violet-300 dark:border-slate-700">{tx('ai.common.clearFilters')}</button>}
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <PromptStat icon={FileCode2} label={tx('ai.prompt.stat.matching')} value={total} helper={tx('ai.prompt.stat.matchingHelp')} tone="bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300" />
        <PromptStat icon={CheckCircle2} label={tx('ai.prompt.stat.enabled')} value={enabledCount} helper={tx('ai.prompt.stat.enabledHelp')} tone="bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300" />
        <PromptStat icon={Layers3} label={tx('ai.prompt.stat.scenes')} value={sceneCount} helper={tx('ai.prompt.stat.scenesHelp')} tone="bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300" />
        <PromptStat icon={Clock3} label={tx('ai.prompt.stat.latest')} value={latestVersion ? 'v' + latestVersion : tx('ai.common.na')} helper={tx('ai.prompt.stat.latestHelp')} tone="bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300" />
      </section>

      <section className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 dark:border-indigo-900/60 dark:bg-indigo-950/20" aria-label={tx('ai.prompt.coverage.aria')}>
        <div className="mb-3 flex items-center gap-2"><SlidersHorizontal className="h-4 w-4 text-indigo-500" /><h3 className="text-sm font-bold text-indigo-950 dark:text-indigo-100">{tx('ai.prompt.coverage.title')}</h3></div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{sceneOptions.map((option) => {
          const count = prompts.filter((prompt) => prompt.scene === option.value).length;
          return <button key={option.value} type="button" onClick={() => { setSceneFilter(option.value); setPage(1); }} className={cn('rounded-xl border bg-white/80 px-3 py-2 text-left transition hover:border-indigo-300 dark:border-indigo-900/50 dark:bg-slate-900/40', sceneFilter === option.value ? 'border-indigo-500 ring-2 ring-indigo-200 dark:ring-indigo-900' : 'border-indigo-100')}><div className="flex items-center justify-between gap-2"><span className="truncate text-xs font-semibold text-slate-800 dark:text-slate-100">{tx(option.labelKey)}</span><span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">{count}</span></div><p className="mt-1 truncate text-[10px] text-slate-500 dark:text-slate-400">{tx(option.descriptionKey)}</p></button>;
        })}</div>
      </section>

      <section className="flex flex-col gap-3 rounded-2xl border border-violet-100 bg-violet-50/60 px-4 py-4 dark:border-violet-900/70 dark:bg-violet-950/20 sm:flex-row sm:items-start sm:px-5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-600 text-white shadow-md shadow-violet-600/20"><Info className="h-4 w-4" /></span>
        <div><h3 className="text-sm font-bold text-violet-950 dark:text-violet-100">{tx('ai.prompt.rules.title')}</h3><p className="mt-1.5 whitespace-pre-wrap text-xs leading-5 text-violet-900/70 dark:text-violet-200/70">{tx('ai.prompt.rules.body')}</p></div>
      </section>

      {error && <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300"><span>{error}</span><button type="button" onClick={() => void fetchPrompts()} className="rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold dark:bg-rose-900/30">{tx('ai.common.retry')}</button></div>}

      {loading ? <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">{[0, 1].map((item) => <div key={item} className="h-[390px] animate-pulse rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"><div className="h-12 w-2/3 rounded-xl bg-slate-100 dark:bg-slate-800" /><div className="mt-6 h-28 rounded-2xl bg-slate-100 dark:bg-slate-800" /><div className="mt-4 h-20 rounded-2xl bg-slate-100 dark:bg-slate-800" /></div>)}</div>
        : total === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-14 text-center dark:border-slate-700 dark:bg-slate-900/60"><span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-50 text-violet-500"><FileCode2 className="h-7 w-7" /></span><h3 className="mt-4 text-base font-bold text-slate-800 dark:text-white">{appliedSearch || sceneFilter || statusFilter !== 'all' ? tx('ai.prompt.empty.filtered') : tx('ai.prompt.empty.none')}</h3><p className="mx-auto mt-1.5 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{tx('ai.prompt.empty.body')}</p><button type="button" onClick={openCreateEditor} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white"><Plus className="h-4 w-4" />{tx('ai.prompt.action.add')}</button></div>
        : emptySearchResult ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/60">{tx('ai.prompt.empty.page')}</div>
        : <div className="space-y-3"><div className="grid grid-cols-1 gap-4 xl:grid-cols-2">{prompts.map((prompt) => {
          const sceneInfo = sceneMap[prompt.scene] || { labelKey: '', descriptionKey: '' };
          const variables = extractVariables(prompt.user_prompt_template);
          return <article key={prompt.id} className="group relative flex min-h-[420px] flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="h-1 bg-gradient-to-r from-violet-500 via-indigo-500 to-cyan-400" /><div className="flex flex-1 flex-col p-5 sm:p-6">
             <div className="flex items-start justify-between gap-4"><div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-violet-50 text-violet-600"><FileCode2 className="h-5 w-5" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-base font-bold text-slate-900 dark:text-white">{prompt.name}</h3><span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-bold text-violet-700">v{prompt.version}</span><span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold', prompt.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500')}>{tx(prompt.enabled ? 'ai.prompt.filter.enabled' : 'ai.prompt.filter.disabled')}</span></div><p className="mt-1 truncate font-mono text-xs text-violet-600">{prompt.code}</p></div></div>
               <div className="flex shrink-0 items-center gap-1"><button type="button" onClick={() => void openPromptDetails(prompt)} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-2.5 py-2 text-xs font-semibold text-slate-600 hover:border-violet-200 hover:bg-violet-50" title={tx('ai.prompt.action.detailTitle')}><Eye className="h-3.5 w-3.5" />{tx('ai.prompt.action.view')}</button><button type="button" onClick={() => openCopyModal(prompt)} className="rounded-xl p-2 text-slate-400 hover:bg-violet-50 hover:text-violet-600" title={tx('ai.prompt.action.copy')} aria-label={tx('ai.prompt.action.copy')}><Copy className="h-4 w-4" /></button><button type="button" onClick={() => openEditEditor(prompt)} className="rounded-xl p-2 text-slate-400 hover:bg-violet-50 hover:text-violet-600" title={tx('ai.prompt.action.edit')} aria-label={tx('ai.prompt.action.editNamed', { name: prompt.name })}><Pencil className="h-4 w-4" /></button><button type="button" onClick={() => void handleTogglePrompt(prompt)} className="rounded-xl p-2 text-slate-400 hover:bg-amber-50 hover:text-amber-600" title={tx(prompt.enabled ? 'ai.prompt.action.disable' : 'ai.prompt.action.enable')} aria-label={tx(prompt.enabled ? 'ai.prompt.action.disableNamed' : 'ai.prompt.action.enableNamed', { name: prompt.name })}><Power className="h-4 w-4" /></button></div>
            </div>
             <div className="mt-4 flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2.5"><SlidersHorizontal className="h-4 w-4 shrink-0 text-violet-500" /><div className="min-w-0"><p className="text-xs font-semibold text-slate-800">{sceneInfo.labelKey ? tx(sceneInfo.labelKey) : prompt.scene}</p><p className="truncate text-[11px] text-slate-500">{sceneInfo.descriptionKey ? tx(sceneInfo.descriptionKey) : tx('ai.prompt.scene.custom')}</p></div></div>
             <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500"><span className="rounded-full bg-slate-100 px-2 py-1">{tx('ai.prompt.card.vendor', { value: prompt.vendor || 'all' })}</span><span className="rounded-full bg-slate-100 px-2 py-1">{tx('ai.prompt.card.platform', { value: prompt.platform || 'all' })}</span><span className="rounded-full bg-violet-50 px-2 py-1 font-semibold text-violet-700">{tx('ai.prompt.card.variables', { count: variables.length })}</span></div>
             <div className="mt-4 grid gap-3 sm:grid-cols-2"><PromptBlock label={tx('ai.prompt.detail.system')} value={prompt.system_prompt} charsLabel={tx('ai.prompt.chars')} compact /><PromptBlock label={tx('ai.prompt.detail.user')} value={prompt.user_prompt_template} charsLabel={tx('ai.prompt.chars')} compact /></div>
            <div className="mt-3 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-3"><div className="mb-1.5 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-indigo-600">Output Contract</div><p className="line-clamp-2 whitespace-pre-wrap break-all font-mono text-[10px] leading-4 text-indigo-900/75">{prompt.output_schema || '{}'}</p></div>
             <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4"><div className="flex items-center gap-4 text-xs text-slate-400"><span>{tx('ai.prompt.card.temperature')} <strong className="font-mono text-slate-600">{prompt.temperature}</strong></span><span>{tx('ai.prompt.card.maxTokens')} <strong className="font-mono text-slate-600">{prompt.max_tokens}</strong></span></div><span className="inline-flex items-center gap-1.5 text-[11px] text-slate-400"><History className="h-3.5 w-3.5 text-violet-500" />{tx('ai.prompt.card.updated', { value: formatDate(prompt.updated_at, tx('ai.common.na')) })}</span></div>
          </div></article>;
        })}</div><Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible /></div>}

      {editorOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="prompt-editor-title"><div className="flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-white/60 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800"><div><div className="mb-2 inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-violet-500">{editingPrompt ? <Pencil className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}{tx(editingPrompt ? 'ai.prompt.editor.editEyebrow' : 'ai.prompt.editor.newEyebrow')}</div><h3 id="prompt-editor-title" className="text-xl font-bold text-slate-950 dark:text-white">{tx(editingPrompt ? 'ai.prompt.editor.editTitle' : 'ai.prompt.editor.newTitle')}</h3><p className="mt-1 text-xs text-slate-500">{tx(editingPrompt ? 'ai.prompt.editor.editDescription' : 'ai.prompt.editor.newDescription')}</p></div><button type="button" onClick={closeEditor} disabled={submitting} aria-label={tx('ai.prompt.editor.close')} className="flex h-9 w-9 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100"><X className="h-5 w-5" /></button></div>
        <form onSubmit={handleSavePrompt} className="min-h-0 overflow-y-auto px-5 py-5"><div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]"><div className="space-y-4">
           <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="prompt-code" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.code')} <span className="font-normal text-slate-400">{tx('ai.prompt.editor.unique')}</span></label><input id="prompt-code" required={!editingPrompt} disabled={Boolean(editingPrompt)} value={code} onChange={(event) => setCode(event.target.value)} placeholder="topology_analysis_v1" className={cn(modalInputClass, 'font-mono disabled:cursor-not-allowed disabled:bg-slate-100')} /></div><div><label htmlFor="prompt-name" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.name')}</label><input id="prompt-name" required value={name} onChange={(event) => setName(event.target.value)} placeholder={tx('ai.prompt.scene.topology_analysis.label')} className={modalInputClass} /></div></div>
           <div className="grid gap-4 sm:grid-cols-3"><div><label htmlFor="prompt-scene" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.scene')}</label><select id="prompt-scene" value={scene} onChange={(event) => setScene(event.target.value)} className={modalInputClass}>{sceneOptions.map((option) => <option key={option.value} value={option.value}>{tx(option.labelKey)}</option>)}</select><p className="mt-1 text-[10px] text-slate-400">{tx(createScene.descriptionKey)}</p></div><div><label htmlFor="prompt-vendor" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.vendor')}</label><input id="prompt-vendor" value={vendor} onChange={(event) => setVendor(event.target.value)} placeholder="all / Huawei" className={modalInputClass} /></div><div><label htmlFor="prompt-platform" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.platform')}</label><input id="prompt-platform" value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="all / huawei_vrp" className={modalInputClass} /></div></div>
           <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-system" className="block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.systemLabel')} <span className="font-normal text-slate-400">{tx('ai.prompt.editor.systemHint')}</span></label><span className="font-mono text-[10px] text-slate-400">{systemPrompt.length} {tx('ai.prompt.chars')}</span></div><textarea id="prompt-system" rows={5} required value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} className={cn(modalInputClass, 'resize-y bg-slate-50 font-mono text-xs leading-5')} /><p className="mt-1.5 text-[11px] text-slate-400">{tx('ai.prompt.editor.systemAdvice')}</p></div>
           <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-user-template" className="block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.userLabel')} <span className="font-normal text-slate-400">{tx('ai.prompt.editor.userHint')}</span></label><span className="font-mono text-[10px] text-slate-400">{userPromptTemplate.length} {tx('ai.prompt.chars')}</span></div><textarea id="prompt-user-template" rows={7} required value={userPromptTemplate} onChange={(event) => setUserPromptTemplate(event.target.value)} className={cn(modalInputClass, 'resize-y bg-slate-50 font-mono text-xs leading-5')} /><div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400"><span>{tx('ai.prompt.editor.variables')}</span>{formVariables.length > 0 ? formVariables.map((item) => <code key={item} className="rounded-md bg-violet-50 px-1.5 py-0.5 font-mono text-violet-700">{item}</code>) : <span>{tx('ai.prompt.editor.noVariables')}</span>}</div></div>
           <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-output-schema" className="block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.outputLabel')} <span className="font-normal text-slate-400">{tx('ai.prompt.editor.outputHint')}</span></label><span className={cn('text-[10px] font-semibold', schemaStatus.valid ? 'text-emerald-600' : 'text-rose-600')}>{schemaStatus.message}</span></div><textarea id="prompt-output-schema" rows={5} required value={outputSchema} onChange={(event) => setOutputSchema(event.target.value)} className={cn(modalInputClass, 'resize-y bg-slate-50 font-mono text-xs leading-5', schemaStatus.valid ? 'border-emerald-200' : 'border-rose-300')} /><p className="mt-1.5 text-[11px] text-slate-400">{tx('ai.prompt.editor.outputAdvice')}</p></div>
           {editingPrompt && <div><label htmlFor="prompt-change-reason" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.reason')}</label><textarea id="prompt-change-reason" required value={changeReason} onChange={(event) => setChangeReason(event.target.value)} rows={2} placeholder={tx('ai.prompt.editor.reasonPlaceholder')} className={modalInputClass} /></div>}
           <div className="grid gap-4 sm:grid-cols-3"><label className="text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.temperature')}<input type="number" min="0" max="2" step="0.1" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} className={cn(modalInputClass, 'mt-1.5 font-mono')} /></label><label className="text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.editor.maxTokens')}<input type="number" min="1" max="131072" value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} className={cn(modalInputClass, 'mt-1.5 font-mono')} /></label><label className="flex items-end gap-2 pb-2.5 text-xs font-semibold text-slate-700 dark:text-slate-300"><input type="checkbox" checked={formEnabled} onChange={(event) => setFormEnabled(event.target.checked)} className="h-4 w-4 rounded border-slate-300 text-violet-600" />{tx('ai.prompt.editor.enableAfterSave')}</label></div>
         </div><aside className="space-y-3"><div className="rounded-2xl border border-emerald-100 bg-emerald-50/70 p-4"><div className="flex items-center gap-2 text-xs font-bold text-emerald-800"><Play className="h-3.5 w-3.5" />{tx('ai.prompt.preview.title')}</div><p className="mt-1.5 text-[11px] leading-5 text-emerald-800/70">{tx('ai.prompt.preview.body')}</p><div className="mt-3 rounded-xl border border-emerald-200/80 bg-white/80 p-3"><div className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-600">{tx('ai.prompt.preview.renderedUser')}</div><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-slate-700">{renderPromptTemplate(userPromptTemplate, localizedSampleVariables, language)}</pre></div></div><div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4"><div className="flex items-center gap-2 text-xs font-bold text-slate-700"><Info className="h-3.5 w-3.5 text-violet-500" />{tx('ai.prompt.preview.checks')}</div><ul className="mt-2 space-y-2 text-[11px] leading-5 text-slate-500"><li>{tx('ai.prompt.preview.systemFilled', { status: systemPrompt.trim() ? tx('ai.prompt.preview.filled') : tx('ai.prompt.preview.pending') })}</li><li>{tx('ai.prompt.editor.variables')} {formVariables.length ? tx('ai.prompt.preview.variablesFound', { count: formVariables.length }) : tx('ai.prompt.preview.optional')}</li><li>{tx('ai.prompt.editor.outputLabel')} {schemaStatus.valid ? tx('ai.prompt.preview.parseable') : tx('ai.prompt.preview.needsFix')}</li></ul></div></aside></div>
         {editorError && <div role="alert" className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{editorError}</div>}<div className="mt-6 flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end"><button type="button" onClick={closeEditor} disabled={submitting} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500">{tx('ai.common.cancel')}</button><button type="submit" disabled={submitting || !schemaStatus.valid} className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"><RefreshCw className={cn('h-4 w-4', submitting && 'animate-spin')} />{submitting ? tx('ai.common.saving') : editingPrompt ? tx('ai.prompt.editor.save') : tx('ai.prompt.editor.add')}</button></div>
        </form></div></div>}

      {selectedPrompt && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="prompt-detail-title"><div className="flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-white/60 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800 sm:px-6"><div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-50 text-violet-600"><FileCode2 className="h-5 w-5" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 id="prompt-detail-title" className="truncate text-xl font-bold text-slate-950 dark:text-white">{selectedPrompt.name}</h3><span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-bold text-violet-700">v{selectedPrompt.version}</span><span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold', selectedPrompt.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500')}>{tx(selectedPrompt.enabled ? 'ai.prompt.filter.enabled' : 'ai.prompt.filter.disabled')}</span></div><p className="mt-1 truncate font-mono text-xs text-violet-600">{selectedPrompt.code}</p></div></div><div className="flex items-center gap-1"><button type="button" onClick={() => openCopyModal(selectedPrompt)} title={tx('ai.prompt.action.copy')} aria-label={tx('ai.prompt.action.copy')} className="rounded-xl p-2 text-slate-400 hover:bg-violet-50 hover:text-violet-600"><Copy className="h-4 w-4" /></button><button type="button" onClick={() => openEditEditor(selectedPrompt)} title={tx('ai.prompt.action.edit')} aria-label={tx('ai.prompt.action.edit')} className="rounded-xl p-2 text-slate-400 hover:bg-violet-50 hover:text-violet-600"><Pencil className="h-4 w-4" /></button><button type="button" onClick={() => void handleTogglePrompt(selectedPrompt)} title={tx(selectedPrompt.enabled ? 'ai.prompt.action.disable' : 'ai.prompt.action.enable')} aria-label={tx(selectedPrompt.enabled ? 'ai.prompt.action.disable' : 'ai.prompt.action.enable')} className="rounded-xl p-2 text-slate-400 hover:bg-amber-50 hover:text-amber-600"><Power className="h-4 w-4" /></button><button type="button" onClick={() => setSelectedPrompt(null)} aria-label={tx('ai.common.close')} className="flex h-9 w-9 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100"><X className="h-5 w-5" /></button></div></div>
         <div className="min-h-0 overflow-y-auto px-5 py-5 sm:px-6"><div className="flex flex-wrap items-center gap-2"><span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700"><SlidersHorizontal className="h-3.5 w-3.5" />{selectedScene ? tx(selectedScene.labelKey) : selectedPrompt.scene}</span><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">{tx('ai.prompt.card.vendor', { value: selectedPrompt.vendor || 'all' })} · {tx('ai.prompt.card.platform', { value: selectedPrompt.platform || 'all' })}</span><span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700"><Clock3 className="h-3.5 w-3.5" />{tx('ai.prompt.detail.temperature')} {selectedPrompt.temperature} · {tx('ai.prompt.detail.maxTokens')} {selectedPrompt.max_tokens}</span></div>
           <div className="mt-5 grid gap-4 lg:grid-cols-2"><PromptBlock label={tx('ai.prompt.detail.system')} value={selectedPrompt.system_prompt} charsLabel={tx('ai.prompt.chars')} /><PromptBlock label={tx('ai.prompt.detail.user')} value={selectedPrompt.user_prompt_template} charsLabel={tx('ai.prompt.chars')} /></div><div className="mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4"><div className="mb-2 flex items-center justify-between gap-2"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-indigo-600">{tx('ai.prompt.detail.output')}</div><span className="font-mono text-[10px] text-indigo-500">{selectedPrompt.output_schema?.length || 2} {tx('ai.prompt.chars')}</span></div><pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-indigo-950/80">{selectedPrompt.output_schema || '{}'}</pre></div>
           <div className="mt-4 rounded-2xl border border-emerald-100 bg-emerald-50/60 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="flex items-center gap-2 text-sm font-bold text-emerald-900"><Play className="h-4 w-4 text-emerald-600" />{tx('ai.prompt.detail.preview')}</div><p className="mt-1 text-[11px] text-emerald-800/70">{tx('ai.prompt.detail.previewBody')}</p></div><button type="button" onClick={() => setShowPreview((current) => !current)} className="rounded-xl border border-emerald-200 bg-white px-3 py-2 text-xs font-semibold text-emerald-700">{showPreview ? tx('ai.prompt.detail.collapsePreview') : tx('ai.prompt.detail.expandPreview')}</button></div>{showPreview && <div className="mt-3 grid gap-3 lg:grid-cols-2"><div className="rounded-xl border border-emerald-200/80 bg-white/80 p-3"><div className="mb-2 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-600">{tx('ai.prompt.detail.systemPreview')}</div><pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-slate-700">{renderPromptTemplate(selectedPrompt.system_prompt, localizedSampleVariables, language)}</pre></div><div className="rounded-xl border border-emerald-200/80 bg-white/80 p-3"><div className="mb-2 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-600">{tx('ai.prompt.detail.userPreview')}</div><pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-slate-700">{renderPromptTemplate(selectedPrompt.user_prompt_template, localizedSampleVariables, language)}</pre></div></div>}</div>

          <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50/80 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-sm font-bold text-slate-800"><History className="h-4 w-4 text-violet-500" />{tx('ai.prompt.detail.history')}</div><div className="flex flex-wrap items-center gap-2"><select aria-label={tx('ai.prompt.detail.leftVersion')} value={compareLeft || ''} onChange={(event) => setCompareLeft(Number(event.target.value))} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs"><option value="">{tx('ai.prompt.detail.leftPlaceholder')}</option>{selectedVersions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select><GitCompareArrows className="h-4 w-4 text-slate-400" /><select aria-label={tx('ai.prompt.detail.rightVersion')} value={compareRight || ''} onChange={(event) => setCompareRight(Number(event.target.value))} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs"><option value="">{tx('ai.prompt.detail.rightPlaceholder')}</option>{selectedVersions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select><button type="button" onClick={() => void handleCompare()} disabled={compareLoading || !compareLeft || !compareRight || compareLeft === compareRight} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><GitCompareArrows className="h-3.5 w-3.5" />{compareLoading ? tx('ai.prompt.detail.comparing') : tx('ai.prompt.detail.compare')}</button></div></div>
            {versionsLoading ? <div className="mt-3 flex items-center gap-2 text-xs text-slate-400"><RefreshCw className="h-3.5 w-3.5 animate-spin" />{tx('ai.prompt.detail.loadingHistory')}</div> : selectedVersions.length === 0 ? <p className="mt-3 text-xs text-slate-400">{tx('ai.prompt.detail.noHistory')}</p> : <div className="mt-3 grid gap-2 sm:grid-cols-2">{selectedVersions.map((version) => <div key={version.id} className={cn('rounded-xl border px-3 py-2', version.version === selectedPrompt.version ? 'border-violet-200 bg-violet-50/70' : 'border-slate-200 bg-white')}><div className="flex items-center justify-between gap-2"><span className="text-xs font-bold text-slate-800">v{version.version}</span><div className="flex items-center gap-2">{version.version === selectedPrompt.version && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-700">{tx('ai.prompt.detail.current')}</span>}{version.version !== selectedPrompt.version && <button type="button" onClick={() => openRestoreModal(version)} className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-2 py-1 text-[10px] font-semibold text-amber-700 hover:bg-amber-50"><RotateCcw className="h-3 w-3" />{tx('ai.prompt.detail.restore')}</button>}</div></div><div className="mt-1 text-[10px] text-slate-500">{version.created_by || tx('ai.prompt.detail.auditSystem')} · {formatDate(version.created_at, tx('ai.common.na'))}</div><div className="mt-1 text-[10px] text-slate-400">{promptDataLabel(tx, PROMPT_VERSION_TYPE_LABELS, version.change_type || 'update')} · {version.change_reason || tx('ai.common.na')}</div></div>)}</div>}
            {compareResult && <div className="mt-4 rounded-xl border border-violet-200 bg-white p-3"><div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-violet-800"><GitCompareArrows className="h-4 w-4" />v{compareResult.left.version} → v{compareResult.right.version}<span className="font-normal text-slate-500">{tx('ai.prompt.detail.changedFields', { fields: compareResult.changed_fields.map((field) => promptDataLabel(tx, PROMPT_FIELD_LABELS, field)).join(', ') || tx('ai.prompt.detail.none') })}</span></div>{Object.keys(compareResult.diff).length === 0 ? <p className="mt-2 text-xs text-slate-500">{tx('ai.prompt.detail.same')}</p> : <div className="mt-3 space-y-3">{Object.entries(compareResult.diff).map(([field, lines]) => <div key={field}><div className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">{promptDataLabel(tx, PROMPT_FIELD_LABELS, field)}</div><pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-[10px] leading-5 text-slate-200">{lines.join('\n')}</pre></div>)}</div>}</div>}
          </div>

          <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4"><div className="flex items-center gap-2 text-sm font-bold text-slate-800"><ClipboardList className="h-4 w-4 text-indigo-500" />{tx('ai.prompt.detail.audit')}</div>{auditLoading ? <div className="mt-3 flex items-center gap-2 text-xs text-slate-400"><RefreshCw className="h-3.5 w-3.5 animate-spin" />{tx('ai.prompt.detail.loadingAudit')}</div> : selectedAudit.length === 0 ? <p className="mt-3 text-xs text-slate-400">{tx('ai.prompt.detail.noAudit')}</p> : <div className="mt-3 space-y-2">{selectedAudit.map((event) => <div key={event.id} className="rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-semibold text-slate-700">{promptDataLabel(tx, PROMPT_AUDIT_EVENT_LABELS, event.event_type)}</span><span className="text-[10px] text-slate-400">{formatDate(event.created_at, tx('ai.common.na'))}</span></div><div className="mt-1 text-[10px] text-slate-500">{event.actor_username || tx('ai.prompt.detail.auditSystem')} · {event.details?.change_reason ? String(event.details.change_reason) : tx('ai.common.na')}{Array.isArray(event.details?.changed_fields) ? ' · ' + (event.details.changed_fields as string[]).map((field) => promptDataLabel(tx, PROMPT_FIELD_LABELS, field)).join(', ') : ''}</div></div>)}</div>}</div>
          <div className="mt-4 flex items-start gap-2 rounded-2xl border border-violet-100 bg-violet-50/60 p-4 text-xs leading-5 text-violet-900/75"><Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" /><span>{tx('ai.prompt.detail.privacy')}</span></div>
        </div><div className="flex justify-end border-t border-slate-100 px-5 py-4"><button type="button" onClick={() => setSelectedPrompt(null)} className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm font-semibold text-slate-700">{tx('ai.common.close')}</button></div>
      </div></div>}

      {copyOpen && selectedPrompt && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="prompt-copy-title"><div className="w-full max-w-lg rounded-3xl bg-white p-5 shadow-2xl dark:bg-slate-900"><div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-violet-500"><Copy className="h-4 w-4" />{tx('ai.prompt.copy.title')}</div><h3 id="prompt-copy-title" className="mt-2 text-lg font-bold text-slate-900 dark:text-white">{tx('ai.prompt.copy.heading')}</h3><p className="mt-1 text-xs text-slate-500">{tx('ai.prompt.copy.body')}</p></div><button type="button" onClick={() => setCopyOpen(false)} aria-label={tx('ai.prompt.copy.close')} className="rounded-xl p-2 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button></div><form onSubmit={handleCopy} className="mt-5 space-y-4"><div><label htmlFor="copy-code" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.copy.code')}</label><input id="copy-code" required value={copyCode} onChange={(event) => setCopyCode(event.target.value)} className={cn(modalInputClass, 'font-mono')} /></div><div><label htmlFor="copy-name" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.copy.name')}</label><input id="copy-name" value={copyName} onChange={(event) => setCopyName(event.target.value)} className={modalInputClass} /></div><div><label htmlFor="copy-reason" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.copy.reason')}</label><textarea id="copy-reason" required value={copyReason} onChange={(event) => setCopyReason(event.target.value)} rows={3} placeholder={tx('ai.prompt.copy.reasonPlaceholder')} className={modalInputClass} /></div><div className="flex justify-end gap-2 border-t border-slate-100 pt-4"><button type="button" onClick={() => setCopyOpen(false)} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500">{tx('ai.common.cancel')}</button><button type="submit" disabled={copySubmitting} className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"><Copy className="h-4 w-4" />{copySubmitting ? tx('ai.prompt.copy.submitting') : tx('ai.prompt.copy.confirm')}</button></div></form></div></div>}

      {restoreVersion && selectedPrompt && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="prompt-restore-title"><div className="w-full max-w-lg rounded-3xl bg-white p-5 shadow-2xl dark:bg-slate-900"><div className="flex items-start gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-600"><RotateCcw className="h-5 w-5" /></span><div><h3 id="prompt-restore-title" className="text-lg font-bold text-slate-900 dark:text-white">{tx('ai.prompt.restore.heading', { version: restoreVersion.version })}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{tx('ai.prompt.restore.body')}</p></div></div><form onSubmit={handleRestore} className="mt-5 space-y-4"><div><label htmlFor="restore-reason" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.prompt.restore.reason')}</label><textarea id="restore-reason" required value={restoreReason} onChange={(event) => setRestoreReason(event.target.value)} rows={3} placeholder={tx('ai.prompt.restore.reasonPlaceholder')} className={modalInputClass} /></div><div className="flex justify-end gap-2 border-t border-slate-100 pt-4"><button type="button" onClick={() => setRestoreVersion(null)} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500">{tx('ai.common.cancel')}</button><button type="submit" disabled={restoreSubmitting} className="inline-flex items-center gap-2 rounded-xl bg-amber-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"><RotateCcw className="h-4 w-4" />{restoreSubmitting ? tx('ai.prompt.restore.submitting') : tx('ai.prompt.restore.confirm')}</button></div></form></div></div>}
    </div>
  );
};

export default PromptCenterTab;
