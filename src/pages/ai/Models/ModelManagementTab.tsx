import React, { useEffect, useMemo, useState } from 'react';
import { Cpu, Plus, RefreshCw, Trash2, GitBranch, Star, Power, Search, AlertTriangle, Info, ShieldCheck } from 'lucide-react';
import { getAIModels, createAIModel, updateAIModel, setAIUserDefaultModel, deleteAIModel, getAIModelDeletePreview, getAIModelRoutes, upsertAIModelRoute, getAIProviders, AIModel, AIModelDeletePreview, AIModelRoute, AIProvider } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { aiAdminText } from '../../../i18n/aiAdmin';

const SCENES = [
  { code: 'command_explain', labelKey: 'ai.prompt.scene.command_explain.label', shortKey: 'ai.prompt.scene.command_explain.short', descriptionKey: 'ai.prompt.scene.command_explain.description' },
  { code: 'config_explain', labelKey: 'ai.prompt.scene.config_explain.label', shortKey: 'ai.prompt.scene.config_explain.short', descriptionKey: 'ai.prompt.scene.config_explain.description' },
  { code: 'config_diff', labelKey: 'ai.prompt.scene.config_diff.label', shortKey: 'ai.prompt.scene.config_diff.short', descriptionKey: 'ai.prompt.scene.config_diff.description' },
  { code: 'alarm_analysis', labelKey: 'ai.prompt.scene.alarm_analysis.label', shortKey: 'ai.prompt.scene.alarm_analysis.short', descriptionKey: 'ai.prompt.scene.alarm_analysis.description' },
  { code: 'chat', labelKey: 'ai.prompt.scene.chat.label', shortKey: 'ai.prompt.scene.chat.short', descriptionKey: 'ai.prompt.scene.chat.description' },
  { code: 'troubleshooting', labelKey: 'ai.prompt.scene.troubleshooting.label', shortKey: 'ai.prompt.scene.troubleshooting.short', descriptionKey: 'ai.prompt.scene.troubleshooting.description' },
  { code: 'topology_analysis', labelKey: 'ai.prompt.scene.topology_analysis.label', shortKey: 'ai.prompt.scene.topology_analysis.short', descriptionKey: 'ai.prompt.scene.topology_analysis.description' },
  { code: 'health_summary', labelKey: 'ai.prompt.scene.health_summary.label', shortKey: 'ai.prompt.scene.health_summary.short', descriptionKey: 'ai.prompt.scene.health_summary.description' },
  { code: 'compliance_audit', labelKey: 'ai.prompt.scene.compliance_audit.label', shortKey: 'ai.prompt.scene.compliance_audit.short', descriptionKey: 'ai.prompt.scene.compliance_audit.description' },
  { code: 'change_plan', labelKey: 'ai.prompt.scene.change_plan.label', shortKey: 'ai.prompt.scene.change_plan.short', descriptionKey: 'ai.prompt.scene.change_plan.description' },
  { code: 'rag_answer', labelKey: 'ai.prompt.scene.rag_answer.label', shortKey: 'ai.prompt.scene.rag_answer.short', descriptionKey: 'ai.prompt.scene.rag_answer.description' },
  { code: 'capacity_analysis', labelKey: 'ai.prompt.scene.capacity_analysis.label', shortKey: 'ai.prompt.scene.capacity_analysis.short', descriptionKey: 'ai.prompt.scene.capacity_analysis.description' },
];

export const ModelManagementTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const tx = (key: string, variables: Record<string, string | number> = {}) => aiAdminText(key, language, variables);
  const [models, setModels] = useState<AIModel[]>([]);
  const [routes, setRoutes] = useState<AIModelRoute[]>([]);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [providerId, setProviderId] = useState('');
  const [modelCode, setModelCode] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [modelType, setModelType] = useState('chat');

  const fetchData = async () => {
    setLoading(true);
    setError('');
    try {
      const [mList, rList, pList] = await Promise.all([
        getAIModels(),
        getAIModelRoutes(),
        getAIProviders(),
      ]);
      setModels(mList);
      setRoutes(rList);
      setProviders(pList);
      if (pList.length > 0) setProviderId(pList[0].id);
    } catch (err: any) {
      setError(err?.message || tx('ai.model.error.load'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createAIModel({
        name,
        provider_id: providerId,
        model_code: modelCode,
        model_type: modelType,
        is_default: isDefault,
        enabled: true,
      });
      setShowModal(false);
      setName('');
      setModelCode('');
      setModelType('chat');
      fetchData();
    } catch (err: any) {
      alert(err.message || tx('ai.model.error.create'));
    }
  };

  const handleToggle = async (model: AIModel) => {
    try {
      await updateAIModel(model.id, { enabled: !model.enabled });
      await fetchData();
    } catch (err: any) {
      alert(err.message || tx('ai.model.error.toggle'));
    }
  };

  const handleSetDefault = async (model: AIModel) => {
    try {
      await updateAIModel(model.id, { is_default: true });
      await setAIUserDefaultModel(model.id);
      await fetchData();
    } catch (err: any) {
      alert(err.message || tx('ai.model.error.default'));
    }
  };

  const getModelDeleteBlockedMessage = (modelName: string, preview: Pick<AIModelDeletePreview, 'route_count' | 'message_count'>) => {
    const routeCount = Number(preview.route_count) || 0;
    const messageCount = Number(preview.message_count) || 0;
    if (routeCount > 0 && messageCount > 0) {
      return tx('ai.model.delete.blocked.both', { name: modelName, routes: routeCount, messages: messageCount });
    }
    if (routeCount > 0) {
      return tx('ai.model.delete.blocked.routes', { name: modelName, routes: routeCount });
    }
    return tx('ai.model.delete.blocked.provenance', { name: modelName, messages: messageCount || 1 });
  };

  const getModelDeleteErrorMessage = (error: unknown, modelName: string) => {
    if (error && typeof error === 'object' && 'code' in error) {
      const code = error.code;
      const detail = 'detail' in error && error.detail && typeof error.detail === 'object' ? error.detail : null;
      const details = detail && 'details' in detail && detail.details && typeof detail.details === 'object' ? detail.details : null;
      if (code === 'AI_MODEL_HAS_ROUTES') {
        const routeCount = details && 'route_count' in details && typeof details.route_count === 'number' ? details.route_count : 1;
        return tx('ai.model.delete.blocked.routes', { name: modelName, routes: routeCount });
      }
      if (code === 'AI_MODEL_HAS_PROVENANCE') {
        const messageCount = details && 'message_count' in details && typeof details.message_count === 'number' ? details.message_count : 1;
        return tx('ai.model.delete.blocked.provenance', { name: modelName, messages: messageCount });
      }
    }
    return error instanceof Error && error.message ? error.message : tx('ai.model.error.delete');
  };

  const handleDelete = async (id: string) => {
    const model = models.find((item) => item.id === id);
    const modelName = model?.name || 'Model';
    let preview: AIModelDeletePreview;
    try {
      preview = await getAIModelDeletePreview(id);
    } catch {
      showToast(tx('ai.model.error.deletePreview'), 'error');
      return;
    }
    if (!preview.can_delete || preview.route_count > 0 || preview.message_count > 0) {
      showToast(getModelDeleteBlockedMessage(modelName, preview), 'error');
      return;
    }
    if (!window.confirm(tx('ai.model.confirm.delete', { name: modelName }))) return;
    try {
      await deleteAIModel(id);
      await fetchData();
    } catch (err: any) {
      showToast(getModelDeleteErrorMessage(err, modelName), 'error');
    }
  };

  const handleRouteChange = async (scene: string, modelId: string) => {
    if (!modelId) return;
    try {
      await upsertAIModelRoute({ scene, model_id: modelId, enabled: true });
      await fetchData();
    } catch (err: any) {
      alert(err.message || tx('ai.model.error.route'));
    }
  };

  const handleRoutePolicyChange = async (scene: string, fallbackModelId: string, dataClassification: string) => {
    const route = routes.find((item) => item.scene === scene);
    const primaryModelId = route?.model_id || models.find((item) => item.is_default && item.enabled)?.id || models.find((item) => item.enabled)?.id;
    if (!primaryModelId) {
      alert(tx('ai.model.error.noEnabled'));
      return;
    }
    try {
      await upsertAIModelRoute({
        scene,
        model_id: primaryModelId,
        fallback_model_id: fallbackModelId || undefined,
        data_classification: dataClassification,
        priority: route?.priority || 10,
        enabled: true,
      });
      await fetchData();
    } catch (err: any) {
      alert(err.message || tx('ai.model.error.routePolicy'));
    }
  };

  const filteredModels = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return models.filter((model) => {
      const provider = providers.find((item) => item.id === model.provider_id);
      const matchesSearch = !needle || [model.name, model.model_code, provider?.name, model.health_status]
        .some((value) => String(value || '').toLowerCase().includes(needle));
      const matchesProvider = !providerFilter || model.provider_id === providerFilter;
      const matchesType = !typeFilter || model.model_type === typeFilter;
      const matchesStatus = statusFilter === 'all' || (statusFilter === 'enabled' ? model.enabled : !model.enabled);
      return matchesSearch && matchesProvider && matchesType && matchesStatus;
    });
  }, [models, providerFilter, providers, search, statusFilter, typeFilter]);
  const visibleModels = filteredModels.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredModels.length / pageSize));
    if (page > maxPage) setPage(maxPage);
  }, [filteredModels.length, page, pageSize]);

  const defaultModel = useMemo(
    () => models.find((model) => model.is_default && model.enabled) || models.find((model) => model.enabled),
    [models],
  );

  return (
    <div className="w-full space-y-6 pb-8">
      {/* Models Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="nx-page-title flex items-center gap-2 text-gray-900 dark:text-white">
              <Cpu className="w-6 h-6 text-indigo-500" />
              {tx('ai.model.header.title')}
            </h2>
            <p className="nx-page-description mt-1 text-gray-500 dark:text-gray-400">
              {tx('ai.model.header.description')}
            </p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={fetchData}
              className="px-3 py-2 text-sm bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 text-gray-700 dark:text-gray-300 rounded-lg flex items-center gap-1.5 transition"
            >
              <RefreshCw className="w-4 h-4" />
              {tx('ai.model.action.refresh')}
            </button>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg flex items-center gap-1.5 font-medium shadow-sm transition"
            >
              <Plus className="w-4 h-4" />
              {tx('ai.model.action.add')}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 rounded-xl border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="relative min-w-[240px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={tx('ai.model.filter.search')} className="w-full rounded-lg border border-gray-200 py-2 pl-9 pr-3 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white" /></div>
          <select value={providerFilter} onChange={(event) => { setProviderFilter(event.target.value); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="">{tx('ai.model.filter.allProviders')}</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select>
          <select value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="">{tx('ai.model.filter.allTypes')}</option><option value="chat">{tx('ai.model.modal.chat')}</option><option value="reasoning">{tx('ai.model.modal.reasoning')}</option><option value="embedding">{tx('ai.model.modal.embedding')}</option><option value="rerank">{tx('ai.model.modal.rerank')}</option></select>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="all">{tx('ai.model.filter.allStatuses')}</option><option value="enabled">{tx('ai.model.filter.enabled')}</option><option value="disabled">{tx('ai.model.filter.disabled')}</option></select>
        </div>

        {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"><AlertTriangle className="h-4 w-4" />{error}</div>}

        {loading ? (
          <div className="p-8 text-center text-gray-400">{tx('ai.model.loading')}</div>
        ) : (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 text-xs font-semibold">
                  <th className="py-3 px-4">{tx('ai.model.table.name')}</th>
                  <th className="py-3 px-4">Model Code</th>
                  <th className="py-3 px-4">{tx('ai.model.table.providerCapability')}</th>
                  <th className="py-3 px-4">{tx('ai.model.table.default')}</th>
                  <th className="py-3 px-4">{tx('ai.model.table.status')}</th>
                  <th className="py-3 px-4 text-right">{tx('ai.model.table.actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700 text-gray-700 dark:text-gray-300">
                {visibleModels.map((m) => (
                  <tr key={m.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                    <td className="py-3 px-4 font-semibold text-gray-900 dark:text-white">{m.name}</td>
                    <td className="py-3 px-4 font-mono text-xs text-indigo-600 dark:text-indigo-400">{m.model_code}</td>
                    <td className="py-3 px-4">
                      <div className="font-semibold text-gray-700 dark:text-gray-200">{providers.find((p) => p.id === m.provider_id)?.name || m.provider_id}</div>
                      <div className="mt-1 flex flex-wrap gap-1 text-[10px]">
                        <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">{m.model_type}</span>
                        {m.stream_supported && <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">stream</span>}
                        {m.thinking_supported && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-violet-700 dark:bg-violet-950 dark:text-violet-300">thinking</span>}
                        {m.tool_call_supported && <span className="rounded bg-sky-50 px-1.5 py-0.5 text-sky-700 dark:bg-sky-950 dark:text-sky-300">tools</span>}
                        {m.json_supported && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300">JSON</span>}
                      </div>
                      <div className="mt-1 text-[10px] text-gray-400">{(m.context_length || 0).toLocaleString()} ctx · {m.health_status || 'unknown'} · {m.last_latency_ms ?? '-'} ms · ${(m.cost_input_per_1k || 0).toFixed(4)}/1k in</div>
                    </td>
                    <td className="py-3 px-4">
                      {m.is_default && (
                        <span className="px-2 py-0.5 text-xs bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 rounded-full font-medium inline-flex items-center gap-1">
                          <Star className="w-3 h-3 fill-current text-amber-500" /> Default
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${m.enabled ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-gray-100 text-gray-600'}`}>
                        {m.enabled ? tx('ai.model.status.enabled') : tx('ai.model.status.disabled')}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <ActionIconGroup label={tx('ai.model.actionGroup')}>
                        <ActionIconButton icon={Star} label={tx('ai.model.action.setDefault')} variant="accent" onClick={() => void handleSetDefault(m)} />
                        <ActionIconButton icon={Power} label={m.enabled ? tx('ai.model.action.disable') : tx('ai.model.action.enable')} onClick={() => void handleToggle(m)} />
                        <ActionIconButton icon={Trash2} label={tx('ai.model.action.delete')} variant="danger" onClick={() => handleDelete(m.id)} />
                      </ActionIconGroup>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visibleModels.length && <div className="border-t border-gray-100 px-4 py-10 text-center text-sm text-gray-400 dark:border-gray-700">{tx('ai.model.empty')}</div>}
            <Pagination currentPage={page} totalItems={filteredModels.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
          </div>
        )}
      </div>

      {/* Scene Routes Section */}
      <div className="space-y-4 border-t border-gray-200 pt-6 dark:border-gray-700">
        <div>
          <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900 dark:text-white">
            <GitBranch className="h-5 w-5 text-indigo-500" />
            {tx('ai.model.route.title')}
          </h3>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-gray-500 dark:text-gray-400">
            {tx('ai.model.route.description')}
          </p>
        </div>

        <section className="grid gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 dark:border-indigo-900/60 dark:bg-indigo-950/20" aria-label={tx('ai.model.route.aria')}>
          <div className="flex items-center gap-2 text-xs font-bold text-indigo-900 dark:text-indigo-100"><Info className="h-4 w-4 text-indigo-500" />{tx('ai.model.route.how')}</div>
          <div className="grid gap-2 md:grid-cols-4">
            {[
              ['1', 'ai.model.route.step.identify', 'ai.model.route.step.identifyBody'],
              ['2', 'ai.model.route.step.primary', 'ai.model.route.step.primaryBody'],
              ['3', 'ai.model.route.step.fallback', 'ai.model.route.step.fallbackBody'],
              ['4', 'ai.model.route.step.default', 'ai.model.route.step.defaultBody'],
            ].map(([step, titleKey, descriptionKey], index) => (
              <div key={step} className="relative rounded-xl border border-indigo-100 bg-white/80 p-3 dark:border-indigo-900/50 dark:bg-slate-900/40">
                <div className="flex items-center gap-2"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-bold text-white">{step}</span><span className="text-xs font-semibold text-slate-800 dark:text-slate-100">{tx(titleKey)}</span></div>
                <p className="mt-2 text-[10px] leading-4 text-slate-500 dark:text-slate-400">{tx(descriptionKey)}</p>
                {index < 3 && <span className="absolute -right-2 top-1/2 hidden text-indigo-400 md:block">→</span>}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-indigo-800 dark:text-indigo-200">
            <span className="font-semibold">{tx('ai.model.route.execution')}</span>
            {[tx('ai.model.route.request'), 'Model Route', 'Model → Provider', tx('ai.model.route.security'), tx('ai.model.route.response')].map((step, index, steps) => (
              <React.Fragment key={step}>
                <span className="rounded-full border border-indigo-100 bg-white/80 px-2 py-1 font-medium dark:border-indigo-900/50 dark:bg-slate-900/50">{step}</span>
                {index < steps.length - 1 && <span className="text-indigo-400">→</span>}
              </React.Fragment>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-indigo-800 dark:text-indigo-200"><ShieldCheck className="h-3.5 w-3.5 text-emerald-500" /><span>{tx('ai.model.route.currentDefault')}</span><strong className="font-mono">{defaultModel ? defaultModel.name + ' (' + defaultModel.model_code + ')' : tx('ai.model.route.noneAvailable')}</strong><span className="text-indigo-700/60 dark:text-indigo-300/60">{tx('ai.model.route.enabledOnly')}</span></div>
        </section>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {SCENES.map((scene) => {
            const configuredRoute = routes.find((route) => route.scene === scene.code);
            const routeModel = models.find((model) => model.id === configuredRoute?.model_id);
            const fallbackModel = models.find((model) => model.id === configuredRoute?.fallback_model_id);
            const routeProvider = routeModel ? providers.find((provider) => provider.id === routeModel.provider_id) : undefined;
            const routeConfigured = Boolean(configuredRoute?.enabled);
            const effectiveModel = routeConfigured ? routeModel : defaultModel;
            const effectiveProvider = effectiveModel ? providers.find((provider) => provider.id === effectiveModel.provider_id) : undefined;
            const routeTargetBlocked = routeConfigured && Boolean(routeModel) && (!routeModel?.enabled || !routeProvider || routeProvider.enabled === false);
            const routeHealthWarning = routeConfigured && Boolean(routeModel?.enabled) && routeModel?.health_status === 'unhealthy';
            const routeStatus = !routeConfigured
              ? tx('ai.model.route.useDefault')
              : !routeModel
                ? tx('ai.model.route.missing')
                : routeTargetBlocked
                  ? tx('ai.model.route.unavailable')
                  : routeHealthWarning
                    ? tx('ai.model.route.unhealthy')
                    : tx('ai.model.route.active');
            return (
              <article key={scene.code} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h4 className="font-semibold text-sm text-gray-900 dark:text-white">{tx(scene.labelKey)}</h4>
                    <p className="mt-0.5 font-mono text-xs text-indigo-500">{scene.code}</p>
                    <p className="mt-2 text-[11px] leading-5 text-gray-500 dark:text-gray-400">{tx(scene.descriptionKey)}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${routeTargetBlocked ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300' : routeHealthWarning ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' : routeConfigured && routeModel ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-300'}`}>{routeStatus}</span>
                </div>
                <div className="mt-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/70">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{tx('ai.model.route.effective')}</div>
                  <div className="mt-1 truncate text-xs font-bold text-slate-800 dark:text-slate-100">{effectiveModel ? effectiveModel.name : tx('ai.model.route.noModel')}</div>
                  <div className="mt-0.5 truncate font-mono text-[10px] text-slate-500 dark:text-slate-400">{effectiveModel ? effectiveModel.model_code : tx('ai.model.route.addAndEnable')}</div>
                  <div className="mt-1 truncate text-[10px] text-slate-500 dark:text-slate-400">{effectiveProvider ? tx('ai.model.route.provider', { name: effectiveProvider.name, status: effectiveProvider.enabled === false ? tx('ai.model.route.providerDisabled') : tx('ai.model.route.providerEnabled') }) : effectiveModel ? tx('ai.model.route.providerMissing') : tx('ai.model.route.providerDash')}</div>
                  {routeTargetBlocked && <p className="mt-2 text-[10px] leading-4 text-rose-700 dark:text-rose-300">{tx('ai.model.route.targetBlocked')}</p>}
                  {routeHealthWarning && !routeTargetBlocked && <p className="mt-2 text-[10px] leading-4 text-amber-700 dark:text-amber-300">{tx('ai.model.route.healthWarning')}</p>}
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <label className="text-[10px] font-semibold text-gray-500 dark:text-gray-400">{tx('ai.model.route.primary')}<select aria-label={tx('ai.model.route.primaryAria', { name: tx(scene.shortKey) })} value={configuredRoute?.model_id || ''} onChange={(event) => handleRouteChange(scene.code, event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-xs font-medium text-gray-800 dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="">{tx('ai.model.route.defaultOption')}</option>{models.filter((model) => model.enabled || model.id === configuredRoute?.model_id).map((model) => <option key={model.id} value={model.id}>{model.name} ({model.model_code})</option>)}</select></label>
                  <label className="text-[10px] font-semibold text-gray-500 dark:text-gray-400">{tx('ai.model.route.fallback')}<select aria-label={tx('ai.model.route.fallbackAria', { name: tx(scene.shortKey) })} value={configuredRoute?.fallback_model_id || ''} onChange={(event) => void handleRoutePolicyChange(scene.code, event.target.value, configuredRoute?.data_classification || 'PUBLIC')} className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-xs font-medium text-gray-800 dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="">{tx('ai.model.route.noFallbackOption')}</option>{models.filter((model) => model.enabled && model.id !== configuredRoute?.model_id).map((model) => <option key={model.id} value={model.id}>{model.name} ({model.model_code})</option>)}</select></label>
                </div>
                <div className="mt-2 flex items-center justify-between gap-2"><label className="text-[10px] font-semibold text-gray-500 dark:text-gray-400">{tx('ai.model.route.classification')}<select aria-label={tx('ai.model.route.classificationAria', { name: tx(scene.shortKey) })} value={configuredRoute?.data_classification || 'PUBLIC'} onChange={(event) => void handleRoutePolicyChange(scene.code, configuredRoute?.fallback_model_id || '', event.target.value)} className="ml-2 rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-[10px] dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="PUBLIC">PUBLIC</option><option value="INTERNAL">INTERNAL</option><option value="CONFIDENTIAL">CONFIDENTIAL</option></select></label><span className="text-[10px] text-gray-400">{tx('ai.model.route.priority', { priority: configuredRoute?.priority || 10, fallback: fallbackModel ? tx('ai.model.route.hasFallback') : tx('ai.model.route.noFallback') })}</span></div>
              </article>
            );
          })}
        </div>
      </div>

      {/* Create Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">{tx('ai.model.modal.title')}</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{tx('ai.model.modal.name')}</label>
                <input
                  type="text"
                  required
                  placeholder={tx('ai.model.modal.namePlaceholder')}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{tx('ai.model.modal.code')}</label>
                <input
                  type="text"
                  required
                  placeholder="deepseek-v4-flash"
                  value={modelCode}
                  onChange={(e) => setModelCode(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{tx('ai.model.modal.type')}</label>
                <select value={modelType} onChange={(e) => setModelType(e.target.value)} className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white">
                  <option value="chat">{tx('ai.model.modal.chat')}</option>
                  <option value="reasoning">{tx('ai.model.modal.reasoning')}</option>
                  <option value="embedding">{tx('ai.model.modal.embedding')}</option>
                  <option value="rerank">{tx('ai.model.modal.rerank')}</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{tx('ai.model.modal.provider')}</label>
                <select
                  value={providerId}
                  onChange={(e) => setProviderId(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.provider_type})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is_default"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                  className="rounded border-gray-300"
                />
                <label htmlFor="is_default" className="text-xs text-gray-700 dark:text-gray-300 font-medium">
                  {tx('ai.model.modal.default')}
                </label>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                >
                  {tx('ai.model.modal.cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg"
                >
                  {tx('ai.model.modal.submit')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
