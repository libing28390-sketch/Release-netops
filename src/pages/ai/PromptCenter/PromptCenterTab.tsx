import React, { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Clock3,
  Eye,
  FileCode2,
  Info,
  Layers3,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
  type LucideIcon,
} from 'lucide-react';
import { getAIPrompts, createAIPrompt, type AIPrompt } from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import Pagination from '../../../components/Pagination';

const sceneOptions = [
  { value: 'chat', label: 'AI Copilot 对话', shortLabel: 'Copilot', description: '面向运维人员的自然语言问答' },
  { value: 'troubleshooting', label: '网络故障排查', shortLabel: '故障排查', description: '结合设备状态定位网络问题' },
  { value: 'command_explain', label: '命令解释与巡检', shortLabel: '命令解释', description: '解释 CLI 命令输出并标记异常' },
  { value: 'config_explain', label: '配置分析解释', shortLabel: '配置分析', description: '解释配置意图、风险与建议' },
  { value: 'config_diff', label: 'Diff 智能对比', shortLabel: 'Diff 对比', description: '识别变更影响并给出回退建议' },
  { value: 'alarm_analysis', label: '告警根因诊断', shortLabel: '告警分析', description: '从告警上下文提炼根因和处置动作' },
];

const sceneMap = Object.fromEntries(sceneOptions.map((item) => [item.value, item]));

const getErrorMessage = (error: unknown, fallback: string) => (
  error instanceof Error && error.message ? error.message : fallback
);

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
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">{label}</p>
        <p className="mt-2 text-2xl font-bold tracking-tight text-slate-900 dark:text-white">{value}</p>
      </div>
      <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${tone}`}><Icon className="h-4 w-4" /></span>
    </div>
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{helper}</p>
  </div>
);

const PromptBlock: React.FC<{ label: string; value: string; compact?: boolean }> = ({ label, value, compact }) => (
  <div className={`rounded-2xl border border-slate-100 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-950/50 ${compact ? 'min-h-[92px]' : 'min-h-[128px]'}`}>
    <div className="mb-2 flex items-center justify-between gap-2">
      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500">{label}</span>
      <span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] font-mono text-slate-400 shadow-sm dark:bg-slate-900 dark:text-slate-500">{value.length} chars</span>
    </div>
    <p className={`whitespace-pre-wrap font-mono text-[11px] leading-5 text-slate-600 dark:text-slate-300 ${compact ? 'line-clamp-3' : ''}`}>{value || '—'}</p>
  </div>
);

export const PromptCenterTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const zh = language === 'zh';
  const [prompts, setPrompts] = useState<AIPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPrompt, setSelectedPrompt] = useState<AIPrompt | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState('');
  const [sceneFilter, setSceneFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [scene, setScene] = useState('chat');
  const [systemPrompt, setSystemPrompt] = useState('你是一名高级网络工程专家。');
  const [userPromptTemplate, setUserPromptTemplate] = useState('分析设备状态：{input}');

  const fetchPrompts = async () => {
    setLoading(true);
    setError(null);
    try {
      setPrompts(await getAIPrompts());
    } catch (err: unknown) {
      const message = getErrorMessage(err, zh ? '获取 Prompt 列表失败' : 'Failed to load prompts');
      setError(message);
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchPrompts();
  }, []);

  const enabledCount = prompts.filter((prompt) => prompt.enabled).length;
  const sceneCount = new Set(prompts.map((prompt) => prompt.scene)).size;
  const latestVersion = prompts.reduce((max, prompt) => Math.max(max, prompt.version || 0), 0);
  const createScene = sceneMap[scene] || sceneOptions[0];

  const resetForm = () => {
    setCode('');
    setName('');
    setScene('chat');
    setSystemPrompt('你是一名高级网络工程专家。');
    setUserPromptTemplate('分析设备状态：{input}');
  };

  const handleCreatePrompt = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await createAIPrompt({
        code: code.trim(),
        name: name.trim(),
        scene,
        system_prompt: systemPrompt.trim(),
        user_prompt_template: userPromptTemplate.trim(),
        enabled: true,
      });
      setShowCreateModal(false);
      resetForm();
      await fetchPrompts();
      showToast(zh ? 'Prompt 模板已创建' : 'Prompt template created', 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, zh ? '创建 Prompt 失败' : 'Failed to create prompt'), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const selectedScene = useMemo(() => (selectedPrompt ? sceneMap[selectedPrompt.scene] : null), [selectedPrompt]);
  const filteredPrompts = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return prompts.filter((prompt) => {
      const matchesSearch = !needle || [prompt.name, prompt.code, prompt.scene, prompt.system_prompt, prompt.user_prompt_template]
        .some((value) => String(value || '').toLowerCase().includes(needle));
      const matchesScene = !sceneFilter || prompt.scene === sceneFilter;
      const matchesStatus = statusFilter === 'all' || (statusFilter === 'enabled' ? prompt.enabled : !prompt.enabled);
      return matchesSearch && matchesScene && matchesStatus;
    });
  }, [prompts, sceneFilter, search, statusFilter]);
  const visiblePrompts = filteredPrompts.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredPrompts.length / pageSize));
    if (page > maxPage) setPage(maxPage);
  }, [filteredPrompts.length, page, pageSize]);

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-violet-100/80 bg-gradient-to-br from-white via-violet-50/70 to-indigo-100/70 px-5 py-6 shadow-sm shadow-violet-100/50 dark:border-violet-900/60 dark:from-slate-900 dark:via-violet-950/40 dark:to-slate-900 dark:shadow-none sm:px-7 sm:py-7">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-violet-300/20 blur-3xl dark:bg-violet-500/10" />
        <div className="relative flex flex-col justify-between gap-6 xl:flex-row xl:items-center">
          <div className="max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-violet-200/80 bg-white/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-violet-600 dark:border-violet-800 dark:bg-violet-950/50 dark:text-violet-300">
              <Sparkles className="h-3.5 w-3.5" />
              {zh ? 'AI 治理 · Prompt 资产' : 'AI Governance · Prompt Assets'}
            </div>
            <h2 className="nx-page-title flex items-center gap-3 text-slate-950 dark:text-white">
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-600 text-white shadow-lg shadow-violet-600/25"><FileCode2 className="h-6 w-6" /></span>
              {zh ? 'Prompt Center 提示词中心' : 'Prompt Center'}
            </h2>
            <p className="nx-page-description mt-3 max-w-2xl text-slate-600 dark:text-slate-300">
              {zh ? '把运维场景中的提示词集中管理，明确每个模板的用途、版本和输入变量，避免 Prompt 散落在业务代码里。' : 'Manage operational prompts centrally with clear purpose, versions, and input variables instead of hard-coding them in business code.'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2 self-start xl:self-center">
            <button type="button" onClick={() => void fetchPrompts()} className="inline-flex items-center gap-2 rounded-xl border border-white/90 bg-white/80 px-3.5 py-2.5 text-sm font-semibold text-slate-600 shadow-sm transition hover:border-violet-200 hover:bg-white hover:text-violet-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-violet-700 dark:hover:text-violet-300">
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />{zh ? '刷新' : 'Refresh'}
            </button>
            <button type="button" onClick={() => setShowCreateModal(true)} className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-600/20 transition hover:bg-violet-700 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-2 dark:focus:ring-offset-slate-950">
              <Plus className="h-4 w-4" />{zh ? '添加 Prompt' : 'Add Prompt'}
            </button>
          </div>
        </div>
      </section>

      <section className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="relative min-w-[260px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={zh ? '搜索名称、Code、场景或提示词内容' : 'Search name, code, scene, or prompt content'} className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-violet-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></div>
        <select value={sceneFilter} onChange={(event) => { setSceneFilter(event.target.value); setPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">{zh ? '全部场景' : 'All scenes'}</option>{sceneOptions.map((option) => <option key={option.value} value={option.value}>{option.shortLabel}</option>)}</select>
        <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="all">{zh ? '全部状态' : 'All statuses'}</option><option value="enabled">{zh ? '已启用' : 'Enabled'}</option><option value="disabled">{zh ? '已停用' : 'Disabled'}</option></select>
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <PromptStat icon={FileCode2} label={zh ? '模板总数' : 'Templates'} value={prompts.length} helper={zh ? '已登记的 Prompt 资产' : 'Registered prompt assets'} tone="bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300" />
        <PromptStat icon={CheckCircle2} label={zh ? '已启用' : 'Enabled'} value={enabledCount} helper={zh ? '当前可被路由调用' : 'Available for routing'} tone="bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300" />
        <PromptStat icon={Layers3} label={zh ? '应用场景' : 'Scenes'} value={sceneCount} helper={zh ? '覆盖的运维业务场景' : 'Operational use cases covered'} tone="bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300" />
        <PromptStat icon={Clock3} label={zh ? '最高版本' : 'Latest version'} value={latestVersion ? `v${latestVersion}` : '—'} helper={zh ? '版本审计从这里开始' : 'Version audit starts here'} tone="bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300" />
      </section>

      <section className="flex flex-col gap-3 rounded-2xl border border-violet-100 bg-violet-50/60 px-4 py-4 dark:border-violet-900/70 dark:bg-violet-950/20 sm:flex-row sm:items-start sm:px-5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-600 text-white shadow-md shadow-violet-600/20"><Info className="h-4 w-4" /></span>
        <div>
          <h3 className="text-sm font-bold text-violet-950 dark:text-violet-100">{zh ? '一个模板应该让人一眼看懂三件事' : 'Every template should make three things obvious'}</h3>
          <p className="mt-1.5 text-xs leading-5 text-violet-900/70 dark:text-violet-200/70">
            {zh ? <>它服务什么场景、系统角色如何约束模型、用户输入会被放到哪里。变量使用 <code className="rounded bg-white/70 px-1 font-mono text-violet-700 dark:bg-violet-900/50 dark:text-violet-200">{'{input}'}</code> 这类占位符，不要把具体设备数据写进模板。</> : <>The target scene, the system role, and where user input is inserted. Use placeholders such as <code className="rounded bg-white/70 px-1 font-mono text-violet-700 dark:bg-violet-900/50 dark:text-violet-200">{'{input}'}</code>; never put live device data in the template.</>}
          </p>
        </div>
      </section>

      {error && <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300"><span>{error}</span><button type="button" onClick={() => void fetchPrompts()} className="rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold dark:bg-rose-900/30">{zh ? '重试' : 'Retry'}</button></div>}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {[0, 1].map((item) => <div key={item} className="h-[360px] animate-pulse rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"><div className="h-12 w-2/3 rounded-xl bg-slate-100 dark:bg-slate-800" /><div className="mt-6 h-28 rounded-2xl bg-slate-100 dark:bg-slate-800" /><div className="mt-4 h-20 rounded-2xl bg-slate-100 dark:bg-slate-800" /><div className="mt-5 h-9 rounded-xl bg-slate-100 dark:bg-slate-800" /></div>)}
        </div>
      ) : prompts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-14 text-center dark:border-slate-700 dark:bg-slate-900/60">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-50 text-violet-500 dark:bg-violet-950/50 dark:text-violet-300"><FileCode2 className="h-7 w-7" /></span>
          <h3 className="mt-4 text-base font-bold text-slate-800 dark:text-white">{zh ? '还没有 Prompt 模板' : 'No prompt templates yet'}</h3>
          <p className="mx-auto mt-1.5 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{zh ? '创建第一个模板，把运维场景、模型角色和输入变量固定下来。' : 'Create the first template to define the operational scene, model role, and input variables.'}</p>
          <button type="button" onClick={() => setShowCreateModal(true)} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-600/20 transition hover:bg-violet-700"><Plus className="h-4 w-4" />{zh ? '添加第一个 Prompt' : 'Add your first Prompt'}</button>
        </div>
      ) : filteredPrompts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-400">{zh ? '当前搜索和筛选没有匹配的 Prompt 模板' : 'No prompt templates match the current filters'}</div>
      ) : (
        <div className="space-y-3">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {visiblePrompts.map((prompt) => {
            const sceneInfo = sceneMap[prompt.scene] || { label: prompt.scene, shortLabel: prompt.scene, description: '自定义应用场景' };
            return (
              <article key={prompt.id} className="group relative flex min-h-[360px] flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm shadow-slate-200/50 transition duration-200 hover:-translate-y-0.5 hover:border-violet-200 hover:shadow-xl hover:shadow-violet-100/50 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none dark:hover:border-violet-800">
                <div className="h-1 bg-gradient-to-r from-violet-500 via-indigo-500 to-cyan-400" />
                <div className="flex flex-1 flex-col p-5 sm:p-6">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300"><FileCode2 className="h-5 w-5" /></span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-base font-bold text-slate-900 dark:text-white">{prompt.name}</h3>
                          <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">v{prompt.version}</span>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${prompt.enabled ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>{prompt.enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')}</span>
                        </div>
                        <p className="mt-1 truncate font-mono text-xs text-violet-600 dark:text-violet-300" title={prompt.code}>{prompt.code}</p>
                      </div>
                    </div>
                    <button type="button" onClick={() => setSelectedPrompt(prompt)} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-violet-200 hover:bg-violet-50 hover:text-violet-700 dark:border-slate-700 dark:text-slate-300 dark:hover:border-violet-700 dark:hover:bg-violet-950/30 dark:hover:text-violet-200"><Eye className="h-3.5 w-3.5" />{zh ? '查看' : 'View'}</button>
                  </div>

                  <div className="mt-4 flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-950/60">
                    <SlidersHorizontal className="h-4 w-4 shrink-0 text-violet-500" />
                    <div className="min-w-0"><p className="text-xs font-semibold text-slate-800 dark:text-slate-100">{sceneInfo.label}</p><p className="truncate text-[11px] text-slate-500 dark:text-slate-400">{sceneInfo.description}</p></div>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <PromptBlock label="System Prompt" value={prompt.system_prompt} compact />
                    <PromptBlock label="User Template" value={prompt.user_prompt_template} compact />
                  </div>

                  <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
                    <div className="flex items-center gap-4 text-xs text-slate-400 dark:text-slate-500"><span>Temp <strong className="font-mono text-slate-600 dark:text-slate-300">{prompt.temperature}</strong></span><span>Max tokens <strong className="font-mono text-slate-600 dark:text-slate-300">{prompt.max_tokens}</strong></span></div>
                    <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-400 dark:text-slate-500"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />{zh ? '受版本审计' : 'Version audited'}</span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
        <Pagination currentPage={page} totalItems={filteredPrompts.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </div>
      )}

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="create-prompt-title">
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-white/60 bg-white shadow-2xl shadow-slate-950/20 dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800 sm:px-6">
              <div><div className="mb-2 inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-violet-500"><Plus className="h-3.5 w-3.5" />{zh ? '新增模板' : 'New template'}</div><h3 id="create-prompt-title" className="text-xl font-bold tracking-tight text-slate-950 dark:text-white">{zh ? '添加 Prompt 提示词模板' : 'Add prompt template'}</h3><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{zh ? '先定义模板用途，再分别填写系统角色和用户输入模板。' : 'Define the use case, then add the system role and user input template.'}</p></div>
              <button type="button" onClick={() => setShowCreateModal(false)} aria-label={zh ? '关闭' : 'Close'} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"><X className="h-5 w-5" /></button>
            </div>
            <form onSubmit={handleCreatePrompt} className="overflow-y-auto px-5 py-5 sm:px-6">
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-[1fr_1fr]">
                  <div><label htmlFor="prompt-code" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">Prompt Code <span className="font-normal text-slate-400">({zh ? '唯一标识' : 'unique key'})</span></label><input id="prompt-code" type="text" required placeholder="prompt_troubleshoot_v1" value={code} onChange={(e) => setCode(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></div>
                  <div><label htmlFor="prompt-name" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '模板名称' : 'Template name'}</label><input id="prompt-name" type="text" required placeholder={zh ? '故障诊断 Prompt 模板' : 'Troubleshooting prompt template'} value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></div>
                </div>
                <div><label htmlFor="prompt-scene" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '应用场景' : 'Use case'}</label><select id="prompt-scene" value={scene} onChange={(e) => setScene(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white">{sceneOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><p className="mt-1.5 text-[11px] text-slate-400">{createScene.description}</p></div>
                <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-system" className="block text-xs font-bold text-slate-700 dark:text-slate-300">System Prompt <span className="font-normal text-slate-400">({zh ? '系统提示词' : 'model role'})</span></label><span className="font-mono text-[10px] text-slate-400">{systemPrompt.length} chars</span></div><textarea id="prompt-system" rows={4} required value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 font-mono text-xs leading-5 text-slate-900 outline-none transition focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /><p className="mt-1.5 text-[11px] text-slate-400">{zh ? '说明模型身份、回答边界和输出要求，不要放入具体设备数据。' : 'Define the model role, boundaries, and output requirements.'}</p></div>
                <div><div className="mb-1.5 flex items-center justify-between gap-2"><label htmlFor="prompt-user-template" className="block text-xs font-bold text-slate-700 dark:text-slate-300">User Prompt Template <span className="font-normal text-slate-400">({zh ? '用户模板' : 'user template'})</span></label><span className="font-mono text-[10px] text-slate-400">{userPromptTemplate.length} chars</span></div><textarea id="prompt-user-template" rows={5} required value={userPromptTemplate} onChange={(e) => setUserPromptTemplate(e.target.value)} className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 font-mono text-xs leading-5 text-slate-900 outline-none transition focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /><div className="mt-2 flex items-center gap-2 text-[11px] text-slate-400"><span>{zh ? '变量示例' : 'Variable'}</span><code className="rounded-md bg-violet-50 px-1.5 py-0.5 font-mono text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">{'{input}'}</code><span>{zh ? '运行时由业务请求填充' : 'filled by the request at runtime'}</span></div></div>
              </div>
              <div className="mt-6 flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 dark:border-slate-800 sm:flex-row sm:justify-end"><button type="button" onClick={() => setShowCreateModal(false)} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-slate-200">{zh ? '取消' : 'Cancel'}</button><button type="submit" disabled={submitting} className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-600/20 transition hover:bg-violet-700 disabled:cursor-wait disabled:opacity-60">{submitting && <RefreshCw className="h-4 w-4 animate-spin" />}{submitting ? (zh ? '保存中…' : 'Saving…') : (zh ? '确认添加' : 'Create template')}</button></div>
            </form>
          </div>
        </div>
      )}

      {selectedPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="prompt-detail-title">
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-white/60 bg-white shadow-2xl shadow-slate-950/20 dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800 sm:px-6"><div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300"><FileCode2 className="h-5 w-5" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 id="prompt-detail-title" className="truncate text-xl font-bold tracking-tight text-slate-950 dark:text-white">{selectedPrompt.name}</h3><span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-bold text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">v{selectedPrompt.version}</span></div><p className="mt-1 truncate font-mono text-xs text-violet-600 dark:text-violet-300">{selectedPrompt.code}</p></div></div><button type="button" onClick={() => setSelectedPrompt(null)} aria-label={zh ? '关闭' : 'Close'} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"><X className="h-5 w-5" /></button></div>
            <div className="overflow-y-auto px-5 py-5 sm:px-6"><div className="flex flex-wrap items-center gap-2"><span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"><SlidersHorizontal className="h-3.5 w-3.5" />{selectedScene?.label || selectedPrompt.scene}</span><span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" />{selectedPrompt.enabled ? (zh ? '当前启用' : 'Enabled') : (zh ? '当前停用' : 'Disabled')}</span><span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300"><Clock3 className="h-3.5 w-3.5" />{zh ? `温度 ${selectedPrompt.temperature} · 最大 ${selectedPrompt.max_tokens} tokens` : `Temperature ${selectedPrompt.temperature} · Max ${selectedPrompt.max_tokens} tokens`}</span></div><div className="mt-5 grid gap-4"><PromptBlock label="System Prompt · 系统提示词" value={selectedPrompt.system_prompt} /><PromptBlock label="User Prompt Template · 用户模板" value={selectedPrompt.user_prompt_template} /></div><div className="mt-4 flex items-start gap-2 rounded-2xl border border-violet-100 bg-violet-50/60 p-4 text-xs leading-5 text-violet-900/75 dark:border-violet-900/60 dark:bg-violet-950/20 dark:text-violet-200/70"><Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" /><span>{zh ? <>模板中的 <code className="rounded bg-white/80 px-1 font-mono text-violet-700 dark:bg-violet-900/50 dark:text-violet-200">{'{input}'}</code> 会在运行时替换为当前请求内容；详情页只展示模板本身，不展示真实业务请求。</> : <>The <code className="rounded bg-white/80 px-1 font-mono text-violet-700 dark:bg-violet-900/50 dark:text-violet-200">{'{input}'}</code> placeholder is filled at runtime. This view shows the template only, never live business requests.</>}</span></div></div>
            <div className="flex justify-end border-t border-slate-100 px-5 py-4 dark:border-slate-800 sm:px-6"><button type="button" onClick={() => setSelectedPrompt(null)} className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700">{zh ? '关闭' : 'Close'}</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PromptCenterTab;
