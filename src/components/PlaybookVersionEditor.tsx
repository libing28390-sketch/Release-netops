import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, FileJson, Loader2, RefreshCw, Send, ShieldCheck } from 'lucide-react';
import { ApiError, apiRequest } from '../api/http';

interface ScenarioOption {
  id: string;
  name: string;
  name_zh?: string;
}

interface PlaybookVersion {
  id: string;
  playbook_id: string;
  version_number: number;
  status: string;
  name?: string;
  checksum?: string;
  definition?: Record<string, unknown>;
  validation_status?: string;
  validation_result?: { valid?: boolean; errors?: Array<{ code?: string; message?: string }> };
  created_by?: string;
  updated_at?: string;
}

interface Props {
  language: string;
  scenarios: ScenarioOption[];
  currentUser?: { role?: string; role_profile?: string };
}

const emptyDefinition = {
  phases: {
    pre_check: [],
    execute: [],
    post_check: [],
    rollback: [],
  },
};

const formatError = (cause: unknown, fallback: string): string => (
  cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : fallback
);

const PlaybookVersionEditor: React.FC<Props> = ({ language, scenarios, currentUser }) => {
  const zh = language === 'zh';
  const [playbookId, setPlaybookId] = useState('');
  const [versions, setVersions] = useState<PlaybookVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [definitionText, setDefinitionText] = useState(JSON.stringify(emptyDefinition, null, 2));
  const [draftName, setDraftName] = useState('');
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [stepPhase, setStepPhase] = useState<'pre_check' | 'execute' | 'post_check' | 'rollback'>('execute');

  const selectedVersion = useMemo(
    () => versions.find((version) => version.id === selectedVersionId) || null,
    [selectedVersionId, versions],
  );
  const role = currentUser?.role || 'Viewer';
  const roleProfile = currentUser?.role_profile || '';
  const canEditByRole = role === 'Administrator' || (role === 'Operator' && !roleProfile) || ['Template Developer', 'Platform Maintainer', 'Playbook Author', 'System Administrator'].includes(roleProfile);
  const canReview = role === 'Administrator' || ['Release Manager', 'System Administrator'].includes(roleProfile);
  const canEdit = canEditByRole && (!selectedVersion || selectedVersion.status === 'DRAFT');

  const addStep = (type: 'action' | 'branch' | 'notification' | 'approval') => {
    if (!canEdit) return;
    try {
      const parsed = JSON.parse(definitionText) as { phases?: Record<string, unknown> };
      const phases = parsed.phases && typeof parsed.phases === 'object' ? parsed.phases as Record<string, unknown> : {};
      const phase = Array.isArray(phases[stepPhase]) ? [...(phases[stepPhase] as unknown[])] : [];
      const defaults: Record<typeof type, Record<string, unknown>> = {
        action: { type: 'action', action_code: 'get_version', parameters: {} },
        branch: { type: 'branch', condition: { source: 'variables', key: '', operator: 'exists', value: '' }, then: [], else: [] },
        notification: { type: 'notification', title: '', message: '', level: 'info' },
        approval: { type: 'approval', title: '', message: '', roles: ['Administrator'], fields: [] },
      };
      phase.push(defaults[type]);
      const next = { ...parsed, phases: { ...phases, [stepPhase]: phase } };
      setDefinitionText(JSON.stringify(next, null, 2));
      setMessage(zh ? `已加入 ${stepPhase} 的 ${type} 步骤模板，请补齐参数后保存` : `Added a ${type} template to ${stepPhase}; complete its parameters before saving`);
    } catch {
      setError(zh ? '请先修正 JSON，再添加步骤模板' : 'Fix the JSON before adding a step template');
    }
  };

  useEffect(() => {
    if (!playbookId && scenarios[0]?.id) setPlaybookId(scenarios[0].id);
    if (playbookId && !scenarios.some((scenario) => scenario.id === playbookId)) setPlaybookId(scenarios[0]?.id || '');
  }, [playbookId, scenarios]);

  const loadVersions = useCallback(async () => {
    if (!playbookId) {
      setVersions([]);
      setSelectedVersionId('');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await apiRequest<{ data: PlaybookVersion[] }>(`/api/playbooks/${encodeURIComponent(playbookId)}/versions`);
      const next = response.data || [];
      setVersions(next);
      setSelectedVersionId((current) => current && next.some((version) => version.id === current) ? current : (next[0]?.id || ''));
    } catch (cause) {
      setVersions([]);
      setSelectedVersionId('');
      setError(formatError(cause, zh ? 'Playbook 版本加载失败' : 'Failed to load Playbook versions'));
    } finally {
      setLoading(false);
    }
  }, [playbookId, zh]);

  useEffect(() => { void loadVersions(); }, [loadVersions]);

  useEffect(() => {
    if (!selectedVersion) {
      setDefinitionText(JSON.stringify(emptyDefinition, null, 2));
      setDraftName('');
      return;
    }
    setDefinitionText(JSON.stringify(selectedVersion.definition || emptyDefinition, null, 2));
    setDraftName(selectedVersion.name || '');
  }, [selectedVersion]);

  const resetFeedback = () => { setError(''); setMessage(''); };

  const saveDraft = async () => {
    resetFeedback();
    if (!playbookId) {
      setError(zh ? '请先选择 Playbook' : 'Select a Playbook first');
      return;
    }
    let definition: Record<string, unknown>;
    try {
      const parsed = JSON.parse(definitionText);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object required');
      definition = parsed as Record<string, unknown>;
    } catch {
      setError(zh ? '版本定义必须是合法 JSON 对象' : 'Version definition must be a valid JSON object');
      return;
    }
    try {
      setWorking(true);
      const response = await apiRequest<{ data: PlaybookVersion }>(selectedVersion ? `/api/playbook-versions/${encodeURIComponent(selectedVersion.id)}` : `/api/playbooks/${encodeURIComponent(playbookId)}/versions`, {
        method: selectedVersion ? 'PUT' : 'POST',
        body: JSON.stringify({ name: draftName.trim(), definition }),
      });
      await loadVersions();
      setSelectedVersionId(response.data.id);
      setMessage(zh ? (selectedVersion ? '草稿版本已保存；旧校验结果已清除' : '草稿版本已创建；请先校验再提交审核') : (selectedVersion ? 'Draft version saved; previous validation was cleared' : 'Draft version created; validate it before submitting'));
    } catch (cause) {
      setError(formatError(cause, zh ? '草稿创建失败' : 'Failed to create draft'));
    } finally {
      setWorking(false);
    }
  };

  const runLifecycleAction = async (action: 'validate' | 'submit' | 'approve' | 'publish') => {
    if (!selectedVersionId) return;
    resetFeedback();
    try {
      setWorking(true);
      await apiRequest(`/api/playbook-versions/${encodeURIComponent(selectedVersionId)}/${action}`, { method: 'POST' });
      await loadVersions();
      setMessage(zh ? `版本${action === 'validate' ? '校验完成' : action === 'submit' ? '已提交审核' : action === 'approve' ? '已审批' : '已发布'}` : `Version ${action} completed`);
    } catch (cause) {
      setError(formatError(cause, zh ? '版本流转失败' : 'Version lifecycle action failed'));
    } finally {
      setWorking(false);
    }
  };

  const selectedScenario = scenarios.find((scenario) => scenario.id === playbookId);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden rounded-2xl border border-black/5 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/5 pb-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><FileJson size={17} className="text-cyan-600" />{zh ? '受控 Playbook 版本编辑' : 'Controlled Playbook version editor'}</div>
          <p className="mt-1 text-[11px] text-slate-500">{zh ? '仅保存声明式 phases；原始 Python、Shell 和命令文本由后端校验拒绝。' : 'Only declarative phases are stored; the backend rejects raw Python, Shell, and command text.'}</p>
        </div>
        <button type="button" onClick={() => void loadVersions()} disabled={loading} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-2.5 py-1.5 text-[11px] font-semibold text-slate-600 disabled:opacity-50"><RefreshCw size={12} className={loading ? 'animate-spin' : ''} />{zh ? '刷新版本' : 'Refresh versions'}</button>
      </div>

      {(error || message) && <div className={`rounded-lg border px-3 py-2 text-[11px] ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col gap-3 rounded-xl border border-black/5 bg-slate-50 p-3">
          <label className="text-[11px] font-semibold text-slate-600">{zh ? 'Playbook 场景' : 'Playbook scenario'}
            <select value={playbookId} onChange={(event) => setPlaybookId(event.target.value)} className="mt-1 w-full rounded-lg border border-black/10 bg-white px-2 py-2 text-xs">
              {!scenarios.length && <option value="">{zh ? '暂无可编辑场景' : 'No editable scenarios'}</option>}
              {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{zh ? scenario.name_zh || scenario.name : scenario.name}</option>)}
            </select>
          </label>
          <div className="min-h-0 flex-1 overflow-auto">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{zh ? '版本' : 'Versions'}</div>
            <div className="space-y-1">
              {versions.map((version) => <button type="button" key={version.id} onClick={() => setSelectedVersionId(version.id)} className={`w-full rounded-lg px-2.5 py-2 text-left text-[11px] ${selectedVersionId === version.id ? 'bg-cyan-100 text-cyan-800' : 'bg-white text-slate-600 hover:bg-cyan-50'}`}><div className="font-semibold">v{version.version_number} · {version.status}</div><div className="mt-0.5 truncate text-[10px] text-slate-400">{version.name || version.id}</div></button>)}
              {!versions.length && <div className="rounded-lg border border-dashed border-slate-200 bg-white px-2.5 py-3 text-[11px] text-slate-400">{zh ? '暂无版本，可创建草稿' : 'No versions; create a draft'}</div>}
            </div>
          </div>
        </aside>

        <section className="flex min-h-0 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs text-slate-500">{selectedScenario ? (zh ? selectedScenario.name_zh || selectedScenario.name : selectedScenario.name) : (zh ? '未选择 Playbook' : 'No Playbook selected')}</div>
            <div className="flex flex-wrap gap-1.5">
              {selectedVersion && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{selectedVersion.status}</span>}
              {selectedVersion?.validation_status && <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${selectedVersion.validation_status === 'PASSED' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{selectedVersion.validation_status}</span>}
            </div>
          </div>
          <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
            <textarea value={definitionText} readOnly={!canEdit} onChange={(event) => setDefinitionText(event.target.value)} aria-label={zh ? 'Playbook 版本定义 JSON' : 'Playbook version definition JSON'} spellCheck={false} className={`min-h-[360px] w-full resize-none rounded-xl border p-3 font-mono text-xs leading-5 outline-none ${canEdit ? 'border-black/10 bg-slate-950 text-slate-100 focus:border-cyan-400' : 'cursor-not-allowed border-black/5 bg-slate-100 text-slate-500'}`} />
            <div className="flex flex-col gap-3 rounded-xl border border-black/5 bg-slate-50 p-3">
              <label className="text-[11px] font-semibold text-slate-600">{zh ? '版本名称' : 'Version name'}<input value={draftName} readOnly={!canEdit} onChange={(event) => setDraftName(event.target.value)} className="mt-1 w-full rounded-lg border border-black/10 bg-white px-2 py-2 text-xs read-only:cursor-not-allowed read-only:bg-slate-100" placeholder={zh ? '例如：接口巡检 v2' : 'e.g. Interface audit v2'} /></label>
              <div className="text-[10px] leading-5 text-slate-500">{zh ? '步骤类型：action、branch、notification、approval。approval 只能在 pre_check/execute 阶段顶层定义，审批通过前会暂停执行；action 必须引用已发布动作，通知只能使用系统已配置渠道。' : 'Step types: action, branch, notification, approval. Approval gates are top-level pre_check/execute steps and pause execution until approved; actions reference published actions and notifications use configured system channels.'}</div>
              {canEdit && <div className="rounded-lg border border-cyan-100 bg-cyan-50/60 p-2">
                <div className="mb-1 text-[10px] font-semibold text-cyan-800">{zh ? '受控步骤模板' : 'Controlled step templates'}</div>
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  <select value={stepPhase} onChange={(event) => setStepPhase(event.target.value as typeof stepPhase)} className="rounded-md border border-cyan-200 bg-white px-1.5 py-1 text-[10px] text-cyan-800">
                    <option value="pre_check">pre_check</option><option value="execute">execute</option><option value="post_check">post_check</option><option value="rollback">rollback</option>
                  </select>
                  {(['action', 'branch', 'notification', 'approval'] as const).map((type) => <button key={type} type="button" onClick={() => addStep(type)} className="rounded-md border border-cyan-200 bg-white px-1.5 py-1 text-[10px] font-semibold text-cyan-700 hover:bg-cyan-100">+ {type}</button>)}
                </div>
                <div className="text-[10px] text-cyan-800/70">{zh ? '只插入声明式模板；保存和校验仍由后端限制动作白名单、参数、分支深度、审批范围和总步骤数。' : 'Templates are declarative only; backend validation still enforces action allowlists, parameters, branch depth, approval scope and total steps.'}</div>
              </div>}
              <div className="mt-auto flex flex-wrap gap-1.5">
                {canEdit && (!selectedVersion || selectedVersion.status === 'DRAFT') && <button type="button" onClick={() => void saveDraft()} disabled={working || !playbookId} className="inline-flex items-center gap-1 rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50">{working ? <Loader2 size={12} className="animate-spin" /> : <FileJson size={12} />}{zh ? (selectedVersion ? '保存草稿' : '创建草稿') : (selectedVersion ? 'Save draft' : 'Create draft')}</button>}
                {canEdit && selectedVersion?.status === 'DRAFT' && <button type="button" onClick={() => void runLifecycleAction('validate')} disabled={working} className="inline-flex items-center gap-1 rounded-lg border border-cyan-200 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-cyan-700 disabled:opacity-50"><CheckCircle2 size={12} />{zh ? '校验' : 'Validate'}</button>}
                {canEdit && selectedVersion?.status === 'DRAFT' && <button type="button" onClick={() => void runLifecycleAction('submit')} disabled={working} className="inline-flex items-center gap-1 rounded-lg bg-amber-500 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50"><Send size={12} />{zh ? '提交审核' : 'Submit'}</button>}
                {selectedVersion?.status === 'IN_REVIEW' && canReview && <button type="button" onClick={() => void runLifecycleAction('approve')} disabled={working} className="inline-flex items-center gap-1 rounded-lg bg-indigo-500 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50"><ShieldCheck size={12} />{zh ? '审批' : 'Approve'}</button>}
                {selectedVersion?.status === 'APPROVED' && canReview && <button type="button" onClick={() => void runLifecycleAction('publish')} disabled={working} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50"><CheckCircle2 size={12} />{zh ? '发布' : 'Publish'}</button>}
              </div>
              {selectedVersion?.validation_result?.errors?.length ? <div className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-[10px] text-rose-700">{selectedVersion.validation_result.errors.map((item, index) => <div key={`${item.code || 'error'}-${index}`}>{item.code || 'INVALID'}：{item.message || (zh ? '校验失败' : 'Validation failed')}</div>)}</div> : null}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default PlaybookVersionEditor;
