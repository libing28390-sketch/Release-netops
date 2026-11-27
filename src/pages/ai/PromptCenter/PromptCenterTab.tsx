import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ClipboardList,
  Clock3,
  Copy,
  Eye,
  FileCode2,
  GitCompareArrows,
  History,
  Info,
  Pencil,
  Play,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  X,
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
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { EmptyState } from '../../../components/ui/EmptyState';
import { cn } from '../../../lib/cn';
import { promptCenterText } from './PromptCenterTab.copy';

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
  name: 'ai.prompt.editor.name',
  scene: 'ai.prompt.editor.scene',
  vendor: 'ai.prompt.editor.vendor',
  platform: 'ai.prompt.editor.platform',
  enabled: 'ai.prompt.filter.enabled',
};

function promptDataLabel(tx: (key: string, variables?: TextVariables) => string, labels: Record<string, string>, value: string): string {
  return labels[value] ? tx(labels[value]) : value;
}

const PromptBlock: React.FC<{ label: string; value: string; compact?: boolean; charsLabel?: string }> = ({ label, value, compact, charsLabel = 'chars' }) => (
  <div className={cn('rounded-lg border border-line bg-surface-muted p-3', compact ? 'min-h-[96px]' : 'min-h-[120px]')}>
    <div className="mb-2 flex items-center justify-between gap-2">
      <span className="text-xs font-medium text-fg-muted">{label}</span>
      <span className="font-mono text-xs text-fg-subtle">{value.length} {charsLabel}</span>
    </div>
    <p className={cn('whitespace-pre-wrap break-words font-mono text-xs leading-5 text-fg', compact && 'line-clamp-4')}>{value || '—'}</p>
  </div>
);

function extractVariables(template: string): string[] {
  const variables = new Set<string>();
  const matcher = /\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = matcher.exec(template)) !== null) variables.add(match[1]);
  return Array.from(variables);
}

function previewValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function renderPromptTemplate(template: string, variables: Record<string, unknown>, language: 'zh' | 'en'): string {
  const matcher = /\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g;
  return template.replace(matcher, (_match, jinjaKey: string) => {
    return Object.prototype.hasOwnProperty.call(variables, jinjaKey) ? previewValue(variables[jinjaKey]) : aiAdminText('ai.prompt.preview.missing', language, { name: jinjaKey });
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

/* Shared control styles — token based, same as the Provider page. */
const modalInputClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20';
const filterControlClass = 'h-9 rounded-lg border border-line bg-surface px-3 text-[13px] text-fg outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20';
const fieldLabelClass = 'mb-1.5 block text-[13px] font-medium text-fg';
const fieldHintClass = 'font-normal text-fg-subtle';
const dialogOverlayClass = 'fixed inset-0 flex items-center justify-center bg-slate-950/40 p-4';
const subPanelClass = 'rounded-lg border border-line bg-surface p-4';

export const PromptCenterTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const tx = (key: string, variables?: TextVariables) => aiAdminText(key, language, variables);
  const localizedSampleVariables = useMemo(() => sampleVariables(language), [language]);
  const copy = promptCenterText(language);
  const [prompts, setPrompts] = useState<AIPrompt[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<{ total_all?: number; enabled_count?: number; max_version?: number; scene_counts?: Record<string, number> } | null>(null);
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
  const [pageSize, setPageSize] = useState(10);
  const [compareLeft, setCompareLeft] = useState(0);
  const [compareRight, setCompareRight] = useState(0);
  const [compareResult, setCompareResult] = useState<AIPromptVersionCompare | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [restoreVersion, setRestoreVersion] = useState<AIPromptVersion | null>(null);
  const [restoreReason, setRestoreReason] = useState('');
  const [restoreSubmitting, setRestoreSubmitting] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const editorDialogRef = useRef<HTMLDivElement>(null);
  const detailDialogRef = useRef<HTMLDivElement>(null);
  const copyDialogRef = useRef<HTMLDivElement>(null);
  const restoreDialogRef = useRef<HTMLDivElement>(null);
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
      setFacets(result.facets || null);
    } catch (err: unknown) {
      const message = getErrorMessage(err, tx('ai.prompt.error.list'));
      setError(message);
      showToast(message, 'error');
    } finally { setLoading(false); }
  }, [appliedSearch, language, page, pageSize, sceneFilter, showToast, statusFilter]);

  useEffect(() => { void fetchPrompts(); }, [fetchPrompts]);

  const enabledCount = facets?.enabled_count ?? prompts.filter((prompt) => prompt.enabled).length;
  const sceneCount = facets?.scene_counts ? Object.keys(facets.scene_counts).length : new Set(prompts.map((prompt) => prompt.scene)).size;
  const latestVersion = facets?.max_version ?? prompts.reduce((max, prompt) => Math.max(max, prompt.version || 0), 0);
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
  useEscapeClose(editorOpen, closeEditor);
  useEscapeClose(Boolean(selectedPrompt), () => setSelectedPrompt(null));
  useEscapeClose(copyOpen && Boolean(selectedPrompt) && !copySubmitting, () => setCopyOpen(false));
  useEscapeClose(Boolean(restoreVersion) && Boolean(selectedPrompt) && !restoreSubmitting, () => setRestoreVersion(null));
  useFocusTrap(editorDialogRef, editorOpen, '#prompt-name');
  useFocusTrap(detailDialogRef, Boolean(selectedPrompt));
  useFocusTrap(copyDialogRef, copyOpen && Boolean(selectedPrompt), '#copy-code');
  useFocusTrap(restoreDialogRef, Boolean(restoreVersion) && Boolean(selectedPrompt), '#restore-reason');

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
      const wasViewingSaved = selectedPrompt?.id === saved.id;
      setSelectedPrompt((current) => current?.id === saved.id ? saved : current);
      setEditorOpen(false);
      await fetchPrompts();
      if (wasViewingSaved) {
        void loadHistory(saved.id);
      }
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
      const wasViewingSaved = selectedPrompt?.id === saved.id;
      setSelectedPrompt((current) => current?.id === saved.id ? saved : current);
      if (wasViewingSaved) {
        void loadHistory(saved.id);
      }
      void fetchPrompts();
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
  const hasActiveFilters = Boolean(appliedSearch || sceneFilter || statusFilter !== 'all');

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title={tx('ai.prompt.header.title')}
        description={tx('ai.prompt.header.description')}
        infoLabel={copy.rulesLabel}
        info={<span className="whitespace-pre-wrap">{tx('ai.prompt.rules.body')}</span>}
        actions={(
          <>
            <ActionButton
              type="button"
              icon={RefreshCw}
              iconClassName={loading ? 'animate-spin motion-reduce:animate-none' : undefined}
              size="md"
              disabled={loading}
              onClick={() => void fetchPrompts()}
            >
              {tx('ai.common.refresh')}
            </ActionButton>
            <ActionButton type="button" icon={Plus} variant="primary" size="md" onClick={openCreateEditor}>
              {tx('ai.prompt.action.add')}
            </ActionButton>
          </>
        )}
      />

      <SummaryBar
        label={copy.summaryAria}
        items={[
          { key: 'matching', value: total, label: tx('ai.prompt.stat.matching') },
          { key: 'enabled', value: enabledCount, label: tx('ai.prompt.stat.enabled'), tone: 'success' },
          { key: 'scenes', value: sceneCount, label: tx('ai.prompt.stat.scenes'), tone: 'accent' },
          { key: 'latest', value: latestVersion ? 'v' + latestVersion : tx('ai.common.na'), label: tx('ai.prompt.stat.latest') },
        ]}
      />

      <form
        onSubmit={(event) => { event.preventDefault(); setPage(1); setAppliedSearch(search.trim()); }}
        aria-label={copy.filterAria}
        className="flex flex-wrap items-center gap-2"
      >
        <label className="relative flex min-w-[240px] max-w-md flex-1 items-center">
          <Search size={15} className="pointer-events-none absolute left-3 text-fg-subtle" aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={tx('ai.prompt.search.placeholder')}
            aria-label={tx('ai.prompt.search.placeholder')}
            className={cn(filterControlClass, 'w-full pl-9')}
          />
        </label>
        <select value={sceneFilter} onChange={(event) => { setSceneFilter(event.target.value); setPage(1); }} aria-label={tx('ai.prompt.filter.allScenes')} className={filterControlClass}>
          <option value="">{tx('ai.prompt.filter.allScenes')}</option>
          {sceneOptions.map((option) => <option key={option.value} value={option.value}>{tx(option.shortLabelKey)}</option>)}
        </select>
        <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} aria-label={tx('ai.prompt.filter.allStatuses')} className={filterControlClass}>
          <option value="all">{tx('ai.prompt.filter.allStatuses')}</option>
          <option value="enabled">{tx('ai.prompt.filter.enabled')}</option>
          <option value="disabled">{tx('ai.prompt.filter.disabled')}</option>
        </select>
        {hasActiveFilters && (
          <button type="button" onClick={clearFilters} className="h-9 rounded-lg px-2 text-[13px] font-medium text-accent hover:bg-accent-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            {tx('ai.common.clearFilters')}
          </button>
        )}
      </form>

      <Panel aria-label={tx('ai.prompt.coverage.aria')}>
        <PanelHeader title={tx('ai.prompt.coverage.title')} />
        <div className="grid gap-2 p-3 sm:grid-cols-2 xl:grid-cols-4">
          {sceneOptions.map((option) => {
            const count = facets ? (facets.scene_counts?.[option.value] ?? 0) : prompts.filter((prompt) => prompt.scene === option.value).length;
            const active = sceneFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => { setSceneFilter(active ? '' : option.value); setPage(1); }}
                className={cn(
                  'rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                  active ? 'border-accent bg-accent-subtle' : 'border-line bg-surface hover:bg-surface-muted',
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-medium text-fg">{tx(option.labelKey)}</span>
                  <span className="font-mono text-xs tabular-nums text-fg-muted">{count}</span>
                </span>
                <span className="mt-0.5 block truncate text-xs text-fg-muted">{tx(option.descriptionKey)}</span>
              </button>
            );
          })}
        </div>
      </Panel>

      {error && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger-subtle px-4 py-3 text-[13px] text-danger">
          <span>{error}</span>
          <ActionButton type="button" variant="danger" onClick={() => void fetchPrompts()}>{tx('ai.common.retry')}</ActionButton>
        </div>
      )}

      {loading ? (
        <Panel aria-busy="true">
          <div role="status" className="sr-only">{copy.loading}</div>
          <div className="space-y-3 p-4">
            {[0, 1, 2, 3].map((item) => (
              <div key={item} className="h-10 animate-pulse rounded-md bg-surface-muted motion-reduce:animate-none" />
            ))}
          </div>
        </Panel>
      ) : total === 0 ? (
        <EmptyState
          icon={FileCode2}
          title={hasActiveFilters ? tx('ai.prompt.empty.filtered') : tx('ai.prompt.empty.none')}
          description={tx('ai.prompt.empty.body')}
          action={hasActiveFilters
            ? <ActionButton type="button" size="md" onClick={clearFilters}>{tx('ai.common.clearFilters')}</ActionButton>
            : <ActionButton type="button" icon={Plus} variant="primary" size="md" onClick={openCreateEditor}>{tx('ai.prompt.action.add')}</ActionButton>}
        />
      ) : emptySearchResult ? (
        <EmptyState icon={FileCode2} title={tx('ai.prompt.empty.page')} />
      ) : (
        <div className="space-y-3">
          <Panel aria-label={copy.listAria}>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th scope="col">{copy.colName}</th>
                    <th scope="col">{copy.colScene}</th>
                    <th scope="col">{copy.colScope}</th>
                    <th scope="col">{copy.colVariables}</th>
                    <th scope="col">{copy.colVersion}</th>
                    <th scope="col">{copy.colStatus}</th>
                    <th scope="col">{copy.colParams}</th>
                    <th scope="col">{copy.colUpdated}</th>
                    <th scope="col" className="text-right">{copy.colActions}</th>
                  </tr>
                </thead>
                <tbody>
                  {prompts.map((prompt) => {
                    const sceneInfo = sceneMap[prompt.scene] || { labelKey: '', descriptionKey: '' };
                    const variables = extractVariables(prompt.user_prompt_template);
                    return (
                      <tr key={prompt.id}>
                        <td className="max-w-[280px]">
                          <div className="truncate font-semibold text-fg" title={prompt.name}>{prompt.name}</div>
                          <div className="truncate font-mono text-xs text-fg-muted" title={prompt.code}>{prompt.code}</div>
                        </td>
                        <td className="max-w-[240px]">
                          <div className="truncate text-fg">{sceneInfo.labelKey ? tx(sceneInfo.labelKey) : prompt.scene}</div>
                          <div className="truncate text-xs text-fg-muted">{sceneInfo.descriptionKey ? tx(sceneInfo.descriptionKey) : tx('ai.prompt.scene.custom')}</div>
                        </td>
                        <td className="whitespace-nowrap text-xs text-fg-muted">
                          <div>{tx('ai.prompt.card.vendor', { value: prompt.vendor || 'all' })}</div>
                          <div>{tx('ai.prompt.card.platform', { value: prompt.platform || 'all' })}</div>
                        </td>
                        <td className="whitespace-nowrap text-xs text-fg-muted" title={variables.join(', ') || undefined}>
                          <span>{tx('ai.prompt.card.variables', { count: variables.length })}</span>
                        </td>
                        <td><StatusBadge tone="accent" mono>v{prompt.version}</StatusBadge></td>
                        <td>
                          <StatusBadge tone={prompt.enabled ? 'success' : 'neutral'} dot>
                            {tx(prompt.enabled ? 'ai.prompt.filter.enabled' : 'ai.prompt.filter.disabled')}
                          </StatusBadge>
                        </td>
                        <td className="whitespace-nowrap font-mono text-xs text-fg-muted">
                          <div>{tx('ai.prompt.card.temperature')} {prompt.temperature}</div>
                          <div>{tx('ai.prompt.card.maxTokens')} {prompt.max_tokens}</div>
                        </td>
                        <td className="whitespace-nowrap text-xs text-fg-muted">{formatDate(prompt.updated_at, tx('ai.common.na'))}</td>
                        <td>
                          <ActionIconGroup className="justify-end">
                            <ActionButton type="button" icon={Eye} title={tx('ai.prompt.action.detailTitle')} onClick={() => void openPromptDetails(prompt)}>
                              {tx('ai.prompt.action.view')}
                            </ActionButton>
                            <ActionIconButton icon={Copy} label={tx('ai.prompt.action.copy')} onClick={() => openCopyModal(prompt)} />
                            <ActionIconButton icon={Pencil} label={tx('ai.prompt.action.editNamed', { name: prompt.name })} tooltip={tx('ai.prompt.action.edit')} onClick={() => openEditEditor(prompt)} />
                            <ActionIconButton
                              icon={Power}
                              variant={prompt.enabled ? 'danger' : 'success'}
                              label={tx(prompt.enabled ? 'ai.prompt.action.disableNamed' : 'ai.prompt.action.enableNamed', { name: prompt.name })}
                              tooltip={tx(prompt.enabled ? 'ai.prompt.action.disable' : 'ai.prompt.action.enable')}
                              onClick={() => void handleTogglePrompt(prompt)}
                            />
                          </ActionIconGroup>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </div>
      )}

      {editorOpen && <div ref={editorDialogRef} className={cn(dialogOverlayClass, 'z-50')} role="dialog" aria-modal="true" aria-labelledby="prompt-editor-title" tabIndex={-1}><div className="nx-form-dialog-surface flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden">
        <div className="flex items-start justify-between gap-4 nx-dialog-header border-b px-6 py-4"><div><div className="mb-1 inline-flex items-center gap-1.5 text-xs font-medium text-accent">{editingPrompt ? <Pencil className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}{tx(editingPrompt ? 'ai.prompt.editor.editEyebrow' : 'ai.prompt.editor.newEyebrow')}</div><h3 id="prompt-editor-title" className="text-base font-semibold text-fg">{tx(editingPrompt ? 'ai.prompt.editor.editTitle' : 'ai.prompt.editor.newTitle')}</h3><p className="mt-0.5 text-[13px] text-fg-muted">{tx(editingPrompt ? 'ai.prompt.editor.editDescription' : 'ai.prompt.editor.newDescription')}</p></div><button type="button" onClick={closeEditor} disabled={submitting} aria-label={tx('ai.prompt.editor.close')} className="flex h-9 w-9 items-center justify-center rounded-lg text-fg-subtle transition-colors hover:bg-surface-muted hover:text-fg"><X className="h-5 w-5" /></button></div>
        <form onSubmit={handleSavePrompt} className="min-h-0 overflow-y-auto px-5 py-5"><div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]"><div className="space-y-4">
           <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="prompt-code" className={fieldLabelClass}>{tx('ai.prompt.editor.code')} <span className={fieldHintClass}>{tx('ai.prompt.editor.unique')}</span></label><input id="prompt-code" required={!editingPrompt} disabled={Boolean(editingPrompt)} value={code} onChange={(event) => setCode(event.target.value)} placeholder="topology_analysis_v1" className={cn(modalInputClass, 'font-mono disabled:cursor-not-allowed disabled:bg-surface-muted')} /></div><div><label htmlFor="prompt-name" className={fieldLabelClass}>{tx('ai.prompt.editor.name')}</label><input id="prompt-name" required value={name} onChange={(event) => setName(event.target.value)} placeholder={tx('ai.prompt.scene.topology_analysis.label')} className={modalInputClass} /></div></div>
           <div className="grid gap-4 sm:grid-cols-3"><div><label htmlFor="prompt-scene" className={fieldLabelClass}>{tx('ai.prompt.editor.scene')}</label><select id="prompt-scene" value={scene} onChange={(event) => setScene(event.target.value)} className={modalInputClass}>{sceneOptions.map((option) => <option key={option.value} value={option.value}>{tx(option.labelKey)}</option>)}</select><p className="mt-1 text-[10px] text-fg-subtle">{tx(createScene.descriptionKey)}</p></div><div><label htmlFor="prompt-vendor" className={fieldLabelClass}>{tx('ai.prompt.editor.vendor')}</label><input id="prompt-vendor" value={vendor} onChange={(event) => setVendor(event.target.value)} placeholder="all / Huawei" className={modalInputClass} /></div><div><label htmlFor="prompt-platform" className={fieldLabelClass}>{tx('ai.prompt.editor.platform')}</label><input id="prompt-platform" value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="all / huawei_vrp" className={modalInputClass} /></div></div>
           <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-system" className="block text-[13px] font-medium text-fg">{tx('ai.prompt.editor.systemLabel')} <span className={fieldHintClass}>{tx('ai.prompt.editor.systemHint')}</span></label><span className="font-mono text-[10px] text-fg-subtle">{systemPrompt.length} {tx('ai.prompt.chars')}</span></div><textarea id="prompt-system" rows={5} required value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} className={cn(modalInputClass, 'resize-y bg-surface-muted font-mono text-xs leading-5')} /><p className="mt-1.5 text-[11px] text-fg-subtle">{tx('ai.prompt.editor.systemAdvice')}</p></div>
           <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-user-template" className="block text-[13px] font-medium text-fg">{tx('ai.prompt.editor.userLabel')} <span className={fieldHintClass}>{tx('ai.prompt.editor.userHint')}</span></label><span className="font-mono text-[10px] text-fg-subtle">{userPromptTemplate.length} {tx('ai.prompt.chars')}</span></div><textarea id="prompt-user-template" rows={7} required value={userPromptTemplate} onChange={(event) => setUserPromptTemplate(event.target.value)} className={cn(modalInputClass, 'resize-y bg-surface-muted font-mono text-xs leading-5')} /><div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-subtle"><span>{tx('ai.prompt.editor.variables')}</span>{formVariables.length > 0 ? formVariables.map((item) => <code key={item} className="rounded-md bg-accent-subtle px-1.5 py-0.5 font-mono text-accent">{item}</code>) : <span>{tx('ai.prompt.editor.noVariables')}</span>}</div></div>
           <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-output-schema" className="block text-[13px] font-medium text-fg">{tx('ai.prompt.editor.outputLabel')} <span className={fieldHintClass}>{tx('ai.prompt.editor.outputHint')}</span></label><span className={cn('text-[10px] font-semibold', schemaStatus.valid ? 'text-success' : 'text-danger')}>{schemaStatus.message}</span></div><textarea id="prompt-output-schema" rows={5} required value={outputSchema} onChange={(event) => setOutputSchema(event.target.value)} className={cn(modalInputClass, 'resize-y bg-surface-muted font-mono text-xs leading-5', schemaStatus.valid ? 'border-line' : 'border-danger/40')} /><p className="mt-1.5 text-[11px] text-fg-subtle">{tx('ai.prompt.editor.outputAdvice')}</p></div>
           {editingPrompt && <div><label htmlFor="prompt-change-reason" className={fieldLabelClass}>{tx('ai.prompt.editor.reason')}</label><textarea id="prompt-change-reason" required value={changeReason} onChange={(event) => setChangeReason(event.target.value)} rows={2} placeholder={tx('ai.prompt.editor.reasonPlaceholder')} className={modalInputClass} /></div>}
           <div className="grid gap-4 sm:grid-cols-3"><label className="text-[13px] font-medium text-fg">{tx('ai.prompt.editor.temperature')}<input type="number" min="0" max="2" step="0.1" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} className={cn(modalInputClass, 'mt-1.5 font-mono')} /></label><label className="text-[13px] font-medium text-fg">{tx('ai.prompt.editor.maxTokens')}<input type="number" min="1" max="131072" value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} className={cn(modalInputClass, 'mt-1.5 font-mono')} /></label><label className="flex items-end gap-2 pb-2.5 text-[13px] font-medium text-fg"><input type="checkbox" checked={formEnabled} onChange={(event) => setFormEnabled(event.target.checked)} className="h-4 w-4 rounded border-line text-accent" />{tx('ai.prompt.editor.enableAfterSave')}</label></div>
         </div><aside className="space-y-3"><div className="rounded-xl border border-line bg-success-subtle p-4"><div className="flex items-center gap-2 text-xs font-bold text-fg"><Play className="h-3.5 w-3.5" />{tx('ai.prompt.preview.title')}</div><p className="mt-1.5 text-[11px] leading-5 text-fg">{tx('ai.prompt.preview.body')}</p><div className="mt-3 rounded-xl border border-line bg-surface p-3"><div className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-success">{tx('ai.prompt.preview.renderedUser')}</div><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-fg">{renderPromptTemplate(userPromptTemplate, localizedSampleVariables, language)}</pre></div></div><div className="rounded-xl border border-line bg-surface-muted p-4"><div className="flex items-center gap-2 text-xs font-bold text-fg"><Info className="h-3.5 w-3.5 text-accent" />{tx('ai.prompt.preview.checks')}</div><ul className="mt-2 space-y-2 text-[11px] leading-5 text-fg-muted"><li>{tx('ai.prompt.preview.systemFilled', { status: systemPrompt.trim() ? tx('ai.prompt.preview.filled') : tx('ai.prompt.preview.pending') })}</li><li>{tx('ai.prompt.editor.variables')} {formVariables.length ? tx('ai.prompt.preview.variablesFound', { count: formVariables.length }) : tx('ai.prompt.preview.optional')}</li><li>{tx('ai.prompt.editor.outputLabel')} {schemaStatus.valid ? tx('ai.prompt.preview.parseable') : tx('ai.prompt.preview.needsFix')}</li></ul></div></aside></div>
         {editorError && <div role="alert" className="mt-5 rounded-xl border border-danger/40 bg-danger-subtle px-3 py-2 text-xs text-danger">{editorError}</div>}<div className="mt-6 flex flex-col-reverse gap-2 border-t border-line pt-4 sm:flex-row sm:justify-end"><button type="button" onClick={closeEditor} disabled={submitting} className="nx-dialog-action-secondary px-4 py-2">{tx('ai.common.cancel')}</button><button type="submit" disabled={submitting || !schemaStatus.valid} className="nx-dialog-action-primary inline-flex items-center justify-center gap-2 px-4 py-2 disabled:opacity-60"><RefreshCw className={cn('h-4 w-4', submitting && 'animate-spin')} />{submitting ? tx('ai.common.saving') : editingPrompt ? tx('ai.prompt.editor.save') : tx('ai.prompt.editor.add')}</button></div>
        </form></div></div>}

      {selectedPrompt && <div ref={detailDialogRef} className={cn(dialogOverlayClass, 'z-50')} role="dialog" aria-modal="true" aria-labelledby="prompt-detail-title" aria-hidden={editorOpen || copyOpen || Boolean(restoreVersion)} tabIndex={-1}><div className="nx-form-dialog-surface flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden">
        <div className="flex items-start justify-between gap-4 nx-dialog-header border-b px-6 py-4"><div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-muted text-fg-muted"><FileCode2 className="h-5 w-5" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 id="prompt-detail-title" className="truncate text-base font-semibold text-fg">{selectedPrompt.name}</h3><span className="rounded-full bg-accent-subtle px-2 py-0.5 font-mono text-xs font-medium text-accent">v{selectedPrompt.version}</span><span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold', selectedPrompt.enabled ? 'bg-success-subtle text-success' : 'bg-surface-muted text-fg-muted')}>{tx(selectedPrompt.enabled ? 'ai.prompt.filter.enabled' : 'ai.prompt.filter.disabled')}</span></div><p className="mt-0.5 truncate font-mono text-xs text-fg-muted">{selectedPrompt.code}</p></div></div><div className="flex items-center gap-1"><button type="button" onClick={() => openCopyModal(selectedPrompt)} title={tx('ai.prompt.action.copy')} aria-label={tx('ai.prompt.action.copy')} className="rounded-lg p-2 text-fg-subtle transition-colors hover:bg-surface-muted hover:text-accent"><Copy className="h-4 w-4" /></button><button type="button" onClick={() => openEditEditor(selectedPrompt)} title={tx('ai.prompt.action.edit')} aria-label={tx('ai.prompt.action.edit')} className="rounded-lg p-2 text-fg-subtle transition-colors hover:bg-surface-muted hover:text-accent"><Pencil className="h-4 w-4" /></button><button type="button" onClick={() => void handleTogglePrompt(selectedPrompt)} title={tx(selectedPrompt.enabled ? 'ai.prompt.action.disable' : 'ai.prompt.action.enable')} aria-label={tx(selectedPrompt.enabled ? 'ai.prompt.action.disable' : 'ai.prompt.action.enable')} className="rounded-lg p-2 text-fg-subtle transition-colors hover:bg-surface-muted hover:text-warning"><Power className="h-4 w-4" /></button><button type="button" onClick={() => setSelectedPrompt(null)} aria-label={tx('ai.common.close')} className="flex h-9 w-9 items-center justify-center rounded-lg text-fg-subtle transition-colors hover:bg-surface-muted hover:text-fg"><X className="h-5 w-5" /></button></div></div>
         <div className="min-h-0 overflow-y-auto px-5 py-5 sm:px-6"><div className="flex flex-wrap items-center gap-2"><span className="inline-flex items-center gap-1.5 rounded-full bg-accent-subtle px-2.5 py-1 text-xs font-semibold text-accent"><SlidersHorizontal className="h-3.5 w-3.5" />{selectedScene ? tx(selectedScene.labelKey) : selectedPrompt.scene}</span><span className="rounded-full bg-surface-muted px-2.5 py-1 text-xs text-fg-muted">{tx('ai.prompt.card.vendor', { value: selectedPrompt.vendor || 'all' })} · {tx('ai.prompt.card.platform', { value: selectedPrompt.platform || 'all' })}</span><span className="inline-flex items-center gap-1.5 rounded-full bg-warning-subtle px-2.5 py-1 text-xs font-semibold text-warning"><Clock3 className="h-3.5 w-3.5" />{tx('ai.prompt.detail.temperature')} {selectedPrompt.temperature} · {tx('ai.prompt.detail.maxTokens')} {selectedPrompt.max_tokens}</span></div>
           <div className="mt-5 grid gap-4 lg:grid-cols-2"><PromptBlock label={tx('ai.prompt.detail.system')} value={selectedPrompt.system_prompt} charsLabel={tx('ai.prompt.chars')} /><PromptBlock label={tx('ai.prompt.detail.user')} value={selectedPrompt.user_prompt_template} charsLabel={tx('ai.prompt.chars')} /></div><div className="mt-4 rounded-xl border border-line bg-accent-subtle p-4"><div className="mb-2 flex items-center justify-between gap-2"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-accent">{tx('ai.prompt.detail.output')}</div><span className="font-mono text-[10px] text-accent">{selectedPrompt.output_schema?.length || 2} {tx('ai.prompt.chars')}</span></div><pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-fg">{selectedPrompt.output_schema || '{}'}</pre></div>
           <div className="mt-4 rounded-xl border border-line bg-success-subtle p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="flex items-center gap-2 text-sm font-bold text-fg"><Play className="h-4 w-4 text-success" />{tx('ai.prompt.detail.preview')}</div><p className="mt-1 text-[11px] text-fg">{tx('ai.prompt.detail.previewBody')}</p></div><button type="button" onClick={() => setShowPreview((current) => !current)} className="rounded-xl border border-line bg-surface px-3 py-2 text-xs font-semibold text-success">{showPreview ? tx('ai.prompt.detail.collapsePreview') : tx('ai.prompt.detail.expandPreview')}</button></div>{showPreview && <div className="mt-3 grid gap-3 lg:grid-cols-2"><div className="rounded-xl border border-line bg-surface p-3"><div className="mb-2 text-[10px] font-bold uppercase tracking-[0.12em] text-success">{tx('ai.prompt.detail.systemPreview')}</div><pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-fg">{renderPromptTemplate(selectedPrompt.system_prompt, localizedSampleVariables, language)}</pre></div><div className="rounded-xl border border-line bg-surface p-3"><div className="mb-2 text-[10px] font-bold uppercase tracking-[0.12em] text-success">{tx('ai.prompt.detail.userPreview')}</div><pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-fg">{renderPromptTemplate(selectedPrompt.user_prompt_template, localizedSampleVariables, language)}</pre></div></div>}</div>

          <div className="mt-4 rounded-xl border border-line bg-surface-muted p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-sm font-bold text-fg"><History className="h-4 w-4 text-accent" />{tx('ai.prompt.detail.history')}</div><div className="flex flex-wrap items-center gap-2"><select aria-label={tx('ai.prompt.detail.leftVersion')} value={compareLeft || ''} onChange={(event) => setCompareLeft(Number(event.target.value))} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-xs"><option value="">{tx('ai.prompt.detail.leftPlaceholder')}</option>{selectedVersions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select><GitCompareArrows className="h-4 w-4 text-fg-subtle" /><select aria-label={tx('ai.prompt.detail.rightVersion')} value={compareRight || ''} onChange={(event) => setCompareRight(Number(event.target.value))} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-xs"><option value="">{tx('ai.prompt.detail.rightPlaceholder')}</option>{selectedVersions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select><button type="button" onClick={() => void handleCompare()} disabled={compareLoading || !compareLeft || !compareRight || compareLeft === compareRight} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><GitCompareArrows className="h-3.5 w-3.5" />{compareLoading ? tx('ai.prompt.detail.comparing') : tx('ai.prompt.detail.compare')}</button></div></div>
            {versionsLoading ? <div className="mt-3 flex items-center gap-2 text-xs text-fg-subtle"><RefreshCw className="h-3.5 w-3.5 animate-spin" />{tx('ai.prompt.detail.loadingHistory')}</div> : selectedVersions.length === 0 ? <p className="mt-3 text-xs text-fg-subtle">{tx('ai.prompt.detail.noHistory')}</p> : <div className="mt-3 grid gap-2 sm:grid-cols-2">{selectedVersions.map((version) => <div key={version.id} className={cn('rounded-xl border px-3 py-2', version.version === selectedPrompt.version ? 'border-line bg-accent-subtle' : 'border-line bg-surface')}><div className="flex items-center justify-between gap-2"><span className="text-xs font-bold text-fg">v{version.version}</span><div className="flex items-center gap-2">{version.version === selectedPrompt.version && <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-[10px] font-semibold text-accent">{tx('ai.prompt.detail.current')}</span>}{version.version !== selectedPrompt.version && <button type="button" onClick={() => openRestoreModal(version)} className="inline-flex items-center gap-1 rounded-lg border border-warning/30 px-2 py-1 text-[10px] font-semibold text-warning hover:bg-warning-subtle"><RotateCcw className="h-3 w-3" />{tx('ai.prompt.detail.restore')}</button>}</div></div><div className="mt-1 text-[10px] text-fg-muted">{version.created_by || tx('ai.prompt.detail.auditSystem')} · {formatDate(version.created_at, tx('ai.common.na'))}</div><div className="mt-1 text-[10px] text-fg-subtle">{promptDataLabel(tx, PROMPT_VERSION_TYPE_LABELS, version.change_type || 'update')} · {version.change_reason || tx('ai.common.na')}</div></div>)}</div>}
            {compareResult && <div className="mt-4 rounded-xl border border-line bg-surface p-3"><div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-fg"><GitCompareArrows className="h-4 w-4" />v{compareResult.left.version} → v{compareResult.right.version}<span className="font-normal text-fg-muted">{tx('ai.prompt.detail.changedFields', { fields: compareResult.changed_fields.map((field) => promptDataLabel(tx, PROMPT_FIELD_LABELS, field)).join(', ') || tx('ai.prompt.detail.none') })}</span></div>{Object.keys(compareResult.diff).length === 0 ? <p className="mt-2 text-xs text-fg-muted">{tx('ai.prompt.detail.same')}</p> : <div className="mt-3 space-y-3">{Object.entries(compareResult.diff).map(([field, lines]) => <div key={field}><div className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-fg-subtle">{promptDataLabel(tx, PROMPT_FIELD_LABELS, field)}</div><pre className="max-h-48 overflow-auto rounded-lg bg-fg p-3 font-mono text-[10px] leading-5 text-surface">{lines.join('\n')}</pre></div>)}</div>}</div>}
          </div>

          <div className="mt-4 rounded-xl border border-line bg-surface p-4"><div className="flex items-center gap-2 text-sm font-bold text-fg"><ClipboardList className="h-4 w-4 text-accent" />{tx('ai.prompt.detail.audit')}</div>{auditLoading ? <div className="mt-3 flex items-center gap-2 text-xs text-fg-subtle"><RefreshCw className="h-3.5 w-3.5 animate-spin" />{tx('ai.prompt.detail.loadingAudit')}</div> : selectedAudit.length === 0 ? <p className="mt-3 text-xs text-fg-subtle">{tx('ai.prompt.detail.noAudit')}</p> : <div className="mt-3 space-y-2">{selectedAudit.map((event) => <div key={event.id} className="rounded-xl border border-line bg-surface-muted px-3 py-2"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-semibold text-fg">{promptDataLabel(tx, PROMPT_AUDIT_EVENT_LABELS, event.event_type)}</span><span className="text-[10px] text-fg-subtle">{formatDate(event.created_at, tx('ai.common.na'))}</span></div><div className="mt-1 text-[10px] text-fg-muted">{event.actor_username || tx('ai.prompt.detail.auditSystem')} · {event.details?.change_reason ? String(event.details.change_reason) : tx('ai.common.na')}{Array.isArray(event.details?.changed_fields) ? ' · ' + (event.details.changed_fields as string[]).map((field) => promptDataLabel(tx, PROMPT_FIELD_LABELS, field)).join(', ') : ''}</div></div>)}</div>}</div>
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-line bg-accent-subtle p-4 text-xs leading-5 text-fg"><Info className="mt-0.5 h-4 w-4 shrink-0 text-accent" /><span>{tx('ai.prompt.detail.privacy')}</span></div>
        </div><div className="flex justify-end border-t border-line px-5 py-4"><button type="button" onClick={() => setSelectedPrompt(null)} className="nx-dialog-action-secondary px-4 py-2">{tx('ai.common.close')}</button></div>
      </div></div>}

      {copyOpen && selectedPrompt && <div ref={copyDialogRef} className={cn(dialogOverlayClass, 'z-[60]')} role="dialog" aria-modal="true" aria-labelledby="prompt-copy-title" tabIndex={-1}><div className="nx-form-dialog-surface w-full max-w-lg p-5"><div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-xs font-medium text-accent"><Copy className="h-4 w-4" />{tx('ai.prompt.copy.title')}</div><h3 id="prompt-copy-title" className="mt-1 text-base font-semibold text-fg">{tx('ai.prompt.copy.heading')}</h3><p className="mt-0.5 text-[13px] text-fg-muted">{tx('ai.prompt.copy.body')}</p></div><button type="button" onClick={() => setCopyOpen(false)} aria-label={tx('ai.prompt.copy.close')} className="rounded-lg p-2 text-fg-subtle transition-colors hover:bg-surface-muted hover:text-fg"><X className="h-4 w-4" /></button></div><form onSubmit={handleCopy} className="mt-5 space-y-4"><div><label htmlFor="copy-code" className={fieldLabelClass}>{tx('ai.prompt.copy.code')}</label><input id="copy-code" required value={copyCode} onChange={(event) => setCopyCode(event.target.value)} className={cn(modalInputClass, 'font-mono')} /></div><div><label htmlFor="copy-name" className={fieldLabelClass}>{tx('ai.prompt.copy.name')}</label><input id="copy-name" value={copyName} onChange={(event) => setCopyName(event.target.value)} className={modalInputClass} /></div><div><label htmlFor="copy-reason" className={fieldLabelClass}>{tx('ai.prompt.copy.reason')}</label><textarea id="copy-reason" required value={copyReason} onChange={(event) => setCopyReason(event.target.value)} rows={3} placeholder={tx('ai.prompt.copy.reasonPlaceholder')} className={modalInputClass} /></div><div className="flex justify-end gap-2 border-t border-line pt-4"><button type="button" onClick={() => setCopyOpen(false)} className="nx-dialog-action-secondary px-4 py-2">{tx('ai.common.cancel')}</button><button type="submit" disabled={copySubmitting} className="nx-dialog-action-primary inline-flex items-center gap-2 px-4 py-2 disabled:opacity-60"><Copy className="h-4 w-4" />{copySubmitting ? tx('ai.prompt.copy.submitting') : tx('ai.prompt.copy.confirm')}</button></div></form></div></div>}

      {restoreVersion && selectedPrompt && <div ref={restoreDialogRef} className={cn(dialogOverlayClass, 'z-[60]')} role="dialog" aria-modal="true" aria-labelledby="prompt-restore-title" tabIndex={-1}><div className="nx-form-dialog-surface w-full max-w-lg p-5"><div className="flex items-start gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-warning-subtle text-warning"><RotateCcw className="h-5 w-5" /></span><div><h3 id="prompt-restore-title" className="text-base font-semibold text-fg">{tx('ai.prompt.restore.heading', { version: restoreVersion.version })}</h3><p className="mt-0.5 text-[13px] leading-5 text-fg-muted">{tx('ai.prompt.restore.body')}</p></div></div><form onSubmit={handleRestore} className="mt-5 space-y-4"><div><label htmlFor="restore-reason" className={fieldLabelClass}>{tx('ai.prompt.restore.reason')}</label><textarea id="restore-reason" required value={restoreReason} onChange={(event) => setRestoreReason(event.target.value)} rows={3} placeholder={tx('ai.prompt.restore.reasonPlaceholder')} className={modalInputClass} /></div><div className="flex justify-end gap-2 border-t border-line pt-4"><button type="button" onClick={() => setRestoreVersion(null)} className="nx-dialog-action-secondary px-4 py-2">{tx('ai.common.cancel')}</button><button type="submit" disabled={restoreSubmitting} className="nx-dialog-action-primary inline-flex items-center gap-2 px-4 py-2 disabled:opacity-60"><RotateCcw className="h-4 w-4" />{restoreSubmitting ? tx('ai.prompt.restore.submitting') : tx('ai.prompt.restore.confirm')}</button></div></form></div></div>}
    </div>
  );
};

export default PromptCenterTab;
