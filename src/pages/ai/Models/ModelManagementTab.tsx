import { DataTable } from '../../../components/DataTable';
import React, { useEffect, useMemo, useState } from 'react';
import { Activity, Boxes, Pencil, Plus, RefreshCw, Trash2, Star, Power, Search, XCircle, ShieldCheck } from 'lucide-react';
import { getAIModels, createAIModel, updateAIModel, setAIUserDefaultModel, deleteAIModel, getAIModelDeletePreview, checkAIModelHealth, getAIModelRoutes, upsertAIModelRoute, deleteAIModelRoute, getAIProviders, AIModel, AIModelDeletePreview, AIModelRoute, AIProvider } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { EmptyState } from '../../../components/ui/EmptyState';
import { InfoTip } from '../../../components/ui/InfoTip';
import { cn } from '../../../lib/cn';
import { modelPageCopy } from './ModelManagementTab.copy';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { aiAdminText } from '../../../i18n/aiAdmin';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
import type { TableExportData } from '../../../components/ui/TableExportMenu';
import { buildAIModelExportData } from './modelExportData';
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

/* Shared control styles — token based, same as the Provider page. */
const filterControlClass = 'h-9 rounded-lg border border-line bg-surface px-3 text-[13px] text-fg outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20';
const fieldLabelClass = 'mb-1.5 block text-[13px] font-medium text-fg';
const fieldInputClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20';
const checkboxClass = 'h-4 w-4 rounded border-line-strong text-accent focus:ring-accent';

const getModelHealthTone = (status?: string): StatusTone => {
  switch (String(status || 'unknown').toLowerCase()) {
    case 'healthy': return 'success';
    case 'unhealthy': return 'danger';
    default: return 'neutral';
  }
};

const getModelHealthStatusKey = (status?: string) => {
  switch (String(status || 'unknown').toLowerCase()) {
    case 'healthy': return 'ai.model.health.healthy';
    case 'unhealthy': return 'ai.model.health.unhealthy';
    case 'disabled': return 'ai.model.health.disabled';
    case 'not_supported': return 'ai.model.health.notSupported';
    default: return 'ai.model.health.unknown';
  }
};

export const ModelManagementTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const tx = (key: string, variables: Record<string, string | number> = {}) => aiAdminText(key, language, variables);
  const copy = language === 'zh' ? modelPageCopy.zh : modelPageCopy.en;
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
  const [pageSize, setPageSize] = useState(10);
  const [selectedScenes, setSelectedScenes] = useState<Set<string>>(new Set());
  const [bulkPrimaryModelId, setBulkPrimaryModelId] = useState('');
  const [bulkDataClassification, setBulkDataClassification] = useState('');
  const [bulkApplying, setBulkApplying] = useState(false);
  const [checkingModelId, setCheckingModelId] = useState<string | null>(null);

  // Modal (Create / Edit)
  const [showModal, setShowModal] = useState(false);
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  useEscapeClose(showModal, () => setShowModal(false));
  useFocusTrap(dialogRef, showModal, '#ai-model-name');
  const [name, setName] = useState('');
  const [providerId, setProviderId] = useState('');
  const [modelCode, setModelCode] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [modelType, setModelType] = useState('chat');
  const [streamSupported, setStreamSupported] = useState(true);
  const [thinkingSupported, setThinkingSupported] = useState(false);
  const [toolCallSupported, setToolCallSupported] = useState(true);
  const [jsonSupported, setJsonSupported] = useState(true);
  const [contextLength, setContextLength] = useState(64000);
  const [maxOutputTokens, setMaxOutputTokens] = useState(4096);
  const [priority, setPriority] = useState(10);
  const [costInputPer1k, setCostInputPer1k] = useState(0);
  const [costOutputPer1k, setCostOutputPer1k] = useState(0);

  const fetchData = async (options: { silent?: boolean } = {}) => {
    if (!options.silent) setLoading(true);
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
      if (!options.silent) setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void fetchData({ silent: true });
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const openCreateModal = () => {
    setEditingModelId(null);
    setName('');
    setModelCode('');
    setModelType('chat');
    setIsDefault(false);
    setStreamSupported(true);
    setThinkingSupported(false);
    setToolCallSupported(true);
    setJsonSupported(true);
    setContextLength(64000);
    setMaxOutputTokens(4096);
    setPriority(10);
    setCostInputPer1k(0);
    setCostOutputPer1k(0);
    if (providers.length > 0 && !providerId) setProviderId(providers[0].id);
    setShowModal(true);
  };

  const openEditModal = (model: AIModel) => {
    setEditingModelId(model.id);
    setName(model.name);
    setProviderId(model.provider_id);
    setModelCode(model.model_code);
    setModelType(model.model_type || 'chat');
    setIsDefault(Boolean(model.is_default));
    setStreamSupported(model.stream_supported !== false);
    setThinkingSupported(Boolean(model.thinking_supported));
    setToolCallSupported(model.tool_call_supported !== false);
    setJsonSupported(model.json_supported !== false);
    setContextLength(model.context_length || 64000);
    setMaxOutputTokens(model.max_output_tokens || 4096);
    setPriority(model.priority ?? 10);
    setCostInputPer1k(model.cost_input_per_1k || 0);
    setCostOutputPer1k(model.cost_output_per_1k || 0);
    setShowModal(true);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = {
        name,
        provider_id: providerId,
        model_code: modelCode,
        model_type: modelType,
        is_default: isDefault,
        stream_supported: streamSupported,
        thinking_supported: thinkingSupported,
        tool_call_supported: toolCallSupported,
        json_supported: jsonSupported,
        context_length: contextLength,
        max_output_tokens: maxOutputTokens,
        priority,
        cost_input_per_1k: costInputPer1k,
        cost_output_per_1k: costOutputPer1k,
      };
      if (editingModelId) {
        await updateAIModel(editingModelId, payload);
        showToast(language === 'zh' ? '模型配置已更新' : 'Model updated', 'success');
      } else {
        await createAIModel({
          ...payload,
          enabled: true,
        });
        showToast(language === 'zh' ? '模型已创建' : 'Model created', 'success');
      }
      setShowModal(false);
      setEditingModelId(null);
      setName('');
      setModelCode('');
      setModelType('chat');
      await fetchData();
    } catch (err: any) {
      showToast(err?.message || tx('ai.model.error.create'), 'error');
    }
  };

  const handleToggle = async (model: AIModel) => {
    try {
      await updateAIModel(model.id, { enabled: !model.enabled });
      await fetchData();
    } catch (err: any) {
      showToast(err?.message || tx('ai.model.error.toggle'), 'error');
    }
  };

  const handleSetDefault = async (model: AIModel) => {
    try {
      await updateAIModel(model.id, { is_default: true });
      await setAIUserDefaultModel(model.id);
      await fetchData();
      showToast(language === 'zh' ? `已将 ${model.name} 设为默认模型` : `${model.name} set as default`, 'success');
    } catch (err: any) {
      showToast(err?.message || tx('ai.model.error.default'), 'error');
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
    try {
      if (!modelId) {
        await deleteAIModelRoute(scene);
        await fetchData();
        showToast(language === 'zh' ? `场景 ${scene} 已恢复使用全局默认模型` : `Scene ${scene} reset to global default`, 'success');
        return;
      }
      const existing = routes.find((item) => item.scene === scene);
      await upsertAIModelRoute(
        existing
          ? {
              scene,
              model_id: modelId,
              fallback_model_id: existing.fallback_model_id && existing.fallback_model_id !== modelId ? existing.fallback_model_id : undefined,
              data_classification: existing.data_classification || 'PUBLIC',
              priority: existing.priority || 10,
              enabled: true,
            }
          : { scene, model_id: modelId, enabled: true }
      );
      await fetchData();
    } catch (err: any) {
      showToast(err?.message || tx('ai.model.error.route'), 'error');
    }
  };

  const handleRoutePolicyChange = async (scene: string, fallbackModelId: string, dataClassification: string) => {
    const route = routes.find((item) => item.scene === scene);
    const primaryModelId = route?.model_id || models.find((item) => item.is_default && item.enabled)?.id || models.find((item) => item.enabled)?.id;
    if (!primaryModelId) {
      showToast(tx('ai.model.error.noEnabled'), 'error');
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
      showToast(err?.message || tx('ai.model.error.routePolicy'), 'error');
    }
  };

  const handleHealthCheck = async (model: AIModel) => {
    setCheckingModelId(model.id);
    try {
      const result = await checkAIModelHealth(model.id);
      await fetchData({ silent: true });
      if (result.success) {
        showToast(tx('ai.model.health.toast.success', { name: model.name, latency: result.latency_ms }), 'success');
      } else {
        showToast(tx('ai.model.health.toast.failure', { name: model.name, code: result.error_code || 'unknown' }), 'error');
      }
    } catch (err: any) {
      showToast(err?.message || tx('ai.model.health.toast.error'), 'error');
    } finally {
      setCheckingModelId(null);
    }
  };

  const toggleSceneSelection = (sceneCode: string) => {
    setSelectedScenes((current) => {
      const next = new Set(current);
      if (next.has(sceneCode)) next.delete(sceneCode);
      else next.add(sceneCode);
      return next;
    });
  };

  const toggleAllScenes = () => {
    setSelectedScenes((current) => (
      current.size === SCENES.length
        ? new Set()
        : new Set(SCENES.map((scene) => scene.code))
    ));
  };

  const handleBulkRouteChange = async () => {
    if ((!bulkPrimaryModelId && !bulkDataClassification) || selectedScenes.size === 0) return;
    const targetScenes = SCENES.filter((scene) => selectedScenes.has(scene.code));
    const selectedModel = models.find((model) => model.id === bulkPrimaryModelId);

    setBulkApplying(true);
    const results = await Promise.allSettled(targetScenes.map((scene) => {
      const route = routes.find((item) => item.scene === scene.code);
      const modelId = bulkPrimaryModelId || route?.model_id || defaultModel?.id;
      if (!modelId) {
        return Promise.reject(new Error(tx('ai.model.error.noEnabled')));
      }
      return upsertAIModelRoute({
        scene: scene.code,
        model_id: modelId,
        fallback_model_id: route?.fallback_model_id || undefined,
        priority: route?.priority || 10,
        data_classification: bulkDataClassification || route?.data_classification || 'PUBLIC',
        enabled: true,
      });
    }));
    const succeeded = results.filter((result) => result.status === 'fulfilled').length;
    const failed = results.length - succeeded;

    try {
      if (succeeded > 0) await fetchData();
      if (failed > 0) {
        showToast(tx('ai.model.route.bulk.partial', { success: succeeded, failed }), 'error');
      } else if (bulkPrimaryModelId && bulkDataClassification && selectedModel) {
        showToast(tx('ai.model.route.bulk.successBoth', { count: succeeded, model: selectedModel.name, classification: bulkDataClassification }), 'success');
        setSelectedScenes(new Set());
        setBulkPrimaryModelId('');
        setBulkDataClassification('');
      } else if (bulkPrimaryModelId && selectedModel) {
        showToast(tx('ai.model.route.bulk.success', { count: succeeded, model: selectedModel.name }), 'success');
        setSelectedScenes(new Set());
        setBulkPrimaryModelId('');
        setBulkDataClassification('');
      } else {
        showToast(tx('ai.model.route.bulk.successClassification', { count: succeeded, classification: bulkDataClassification }), 'success');
        setSelectedScenes(new Set());
        setBulkPrimaryModelId('');
        setBulkDataClassification('');
      }
    } finally {
      setBulkApplying(false);
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
  const modelExportData = useMemo<TableExportData>(() => {
    return buildAIModelExportData(filteredModels, providers, {
      headers: [
      tx('ai.model.table.name'), tx('ai.model.table.code'), tx('ai.model.table.provider'),
      tx('ai.model.table.type'), tx('ai.model.table.streaming'), tx('ai.model.table.thinking'),
      tx('ai.model.table.toolCalls'), tx('ai.model.table.json'), tx('ai.model.table.contextLength'),
      tx('ai.model.table.health'), tx('ai.model.table.latency'), tx('ai.model.table.inputCost'),
      tx('ai.model.table.default'), tx('ai.model.table.status'),
      ],
      yes: tx('ai.model.table.yes'),
      no: tx('ai.model.table.no'),
      enabled: tx('ai.model.status.enabled'),
      disabled: tx('ai.model.status.disabled'),
      health: (status) => tx(getModelHealthStatusKey(status)),
    });
  }, [filteredModels, providers, language]);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredModels.length / pageSize));
    if (page > maxPage) setPage(maxPage);
  }, [filteredModels.length, page, pageSize]);

  const defaultModel = useMemo(
    () => models.find((model) => model.is_default && model.enabled) || models.find((model) => model.enabled),
    [models],
  );

  const enabledCount = models.filter((model) => model.enabled).length;
  const healthyCount = models.filter((model) => model.enabled && String(model.health_status || '').toLowerCase() === 'healthy').length;
  const unhealthyCount = models.filter((model) => model.enabled && String(model.health_status || '').toLowerCase() === 'unhealthy').length;
  const routedSceneCount = SCENES.filter((scene) => routes.some((route) => route.scene === scene.code && route.enabled)).length;
  const hasActiveFilters = Boolean(search || providerFilter || typeFilter || statusFilter !== 'all');
  const clearFilters = () => { setSearch(''); setProviderFilter(''); setTypeFilter(''); setStatusFilter('all'); setPage(1); };

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title={tx('ai.model.header.title')}
        description={tx('ai.model.header.description')}
        infoLabel={copy.infoLabel}
        info={copy.info}
        actions={(
          <>
            <ActionButton
              type="button"
              icon={RefreshCw}
              iconClassName={loading ? 'animate-spin motion-reduce:animate-none' : undefined}
              size="md"
              onClick={() => void fetchData()}
            >
              {tx('ai.model.action.refresh')}
            </ActionButton>
            <ActionButton type="button" icon={Plus} variant="primary" size="md" onClick={openCreateModal}>
              {tx('ai.model.action.add')}
            </ActionButton>
          </>
        )}
      />

      <SummaryBar
        label={copy.summaryAria}
        items={[
          { key: 'total', value: models.length, label: copy.summaryTotal },
          { key: 'enabled', value: enabledCount, label: copy.summaryEnabled, tone: 'accent' },
          { key: 'healthy', value: healthyCount, label: copy.summaryHealthy, tone: 'success' },
          ...(unhealthyCount > 0 ? [{ key: 'unhealthy', value: unhealthyCount, label: copy.summaryUnhealthy, tone: 'danger' as StatusTone }] : []),
          { key: 'routes', value: `${routedSceneCount}/${SCENES.length}`, label: copy.summaryRoutes },
        ]}
      />

      <div role="search" aria-label={copy.filterAria} className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-[220px] max-w-sm flex-1 items-center">
          <Search size={15} className="pointer-events-none absolute left-3 text-fg-subtle" aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(event) => { setSearch(event.target.value); setPage(1); }}
            placeholder={tx('ai.model.filter.search')}
            aria-label={copy.filterSearchLabel}
            className={cn(filterControlClass, 'w-full pl-9')}
          />
        </label>
        <select value={providerFilter} onChange={(event) => { setProviderFilter(event.target.value); setPage(1); }} aria-label={tx('ai.model.filter.allProviders')} className={filterControlClass}>
          <option value="">{tx('ai.model.filter.allProviders')}</option>
          {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
        </select>
        <select value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value); setPage(1); }} aria-label={tx('ai.model.filter.allTypes')} className={filterControlClass}>
          <option value="">{tx('ai.model.filter.allTypes')}</option>
          <option value="chat">{tx('ai.model.modal.chat')}</option>
          <option value="reasoning">{tx('ai.model.modal.reasoning')}</option>
          <option value="embedding">{tx('ai.model.modal.embedding')}</option>
          <option value="rerank">{tx('ai.model.modal.rerank')}</option>
        </select>
        <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} aria-label={tx('ai.model.filter.allStatuses')} className={filterControlClass}>
          <option value="all">{tx('ai.model.filter.allStatuses')}</option>
          <option value="enabled">{tx('ai.model.filter.enabled')}</option>
          <option value="disabled">{tx('ai.model.filter.disabled')}</option>
        </select>
        {hasActiveFilters && (
          <button type="button" onClick={clearFilters} className="h-9 rounded-lg px-2 text-[13px] font-medium text-accent hover:bg-accent-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            {copy.clearFilters}
          </button>
        )}
        <span className="ml-auto text-xs text-fg-subtle">{copy.filterCount(filteredModels.length)}</span>
      </div>

      {error && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger-subtle px-4 py-3 text-[13px] text-danger">
          <span className="flex items-start gap-2"><XCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{error}</span>
          <ActionButton type="button" variant="danger" onClick={() => void fetchData()}>{copy.retry}</ActionButton>
        </div>
      )}

      {loading ? (
        <div className="h-[280px] animate-pulse rounded-xl border border-line bg-surface p-5 motion-reduce:animate-none" aria-busy="true" aria-label={tx('ai.model.loading')}>
          <div className="h-5 w-1/4 rounded-md bg-surface-emphasis" />
          <div className="mt-5 space-y-3">
            <div className="h-4 rounded-md bg-surface-muted" />
            <div className="h-4 w-5/6 rounded-md bg-surface-muted" />
            <div className="h-4 w-2/3 rounded-md bg-surface-muted" />
          </div>
        </div>
      ) : models.length === 0 ? (
        <EmptyState icon={Boxes} title={copy.emptyTitle} description={copy.emptyBody} />
      ) : (
        <Panel aria-label={copy.modelsAria} className="overflow-hidden">
          <DataTable unstyled exportConfig={{ filename: 'ai-models', language: language === 'zh' ? 'zh' : 'en', disabled: loading || filteredModels.length === 0, exportData: modelExportData }} className="w-full min-w-[1200px] border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-line bg-surface-muted text-xs font-medium text-fg-muted">
                <th scope="col" className="px-4 py-2.5">{tx('ai.model.table.name')}</th>
                <th scope="col" className="px-4 py-2.5">{tx('ai.model.table.provider')}</th>
                <th scope="col" className="px-4 py-2.5">{tx('ai.model.table.type')}</th>
                <th scope="col" className="px-4 py-2.5">{copy.capabilities}</th>
                <th scope="col" className="px-4 py-2.5 text-right">{tx('ai.model.table.contextLength')}</th>
                <th scope="col" className="px-4 py-2.5">{tx('ai.model.table.health')}</th>
                <th scope="col" className="px-4 py-2.5 text-right">{tx('ai.model.table.latency')}</th>
                <th scope="col" className="px-4 py-2.5 text-right">{tx('ai.model.table.inputCost')}</th>
                <th scope="col" className="px-4 py-2.5">{tx('ai.model.table.status')}</th>
                <TableActionHeader className="px-4 py-2.5 text-right">{tx('ai.model.table.actions')}</TableActionHeader>
              </tr>
            </thead>
            <tbody className="divide-y divide-line text-fg">
              {visibleModels.map((m) => {
                const capabilityBadges = [
                  m.stream_supported ? copy.capStream : null,
                  m.thinking_supported ? copy.capThinking : null,
                  m.tool_call_supported ? copy.capTools : null,
                  m.json_supported ? copy.capJson : null,
                ].filter(Boolean) as string[];
                return (
                  <tr key={m.id} className="align-top transition-colors hover:bg-accent-subtle/60">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 font-medium text-fg">
                        <span className="truncate" title={m.name}>{m.name}</span>
                        {m.is_default && (
                          <StatusBadge tone="warning"><Star size={11} className="fill-current" aria-hidden="true" />{tx('ai.model.table.default')}</StatusBadge>
                        )}
                      </div>
                      <div className="mt-0.5 font-mono text-xs text-fg-muted" title={m.model_code}>{m.model_code}</div>
                    </td>
                    <td className="px-4 py-3"><div className="text-fg">{providers.find((provider) => provider.id === m.provider_id)?.name || '—'}</div></td>
                    <td className="px-4 py-3"><StatusBadge mono>{m.model_type}</StatusBadge></td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {capabilityBadges.length ? capabilityBadges.map((label) => <StatusBadge key={label}>{label}</StatusBadge>) : <span className="text-fg-subtle">—</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">{m.context_length.toLocaleString()}</td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={getModelHealthTone(m.health_status)} dot>{tx(getModelHealthStatusKey(m.health_status))}</StatusBadge>
                      <div data-export-ignore className="mt-1 text-xs text-fg-subtle">
                        {tx('ai.model.health.sla', { hours: m.sla_window_hours || 24, value: m.sla_availability_percent == null ? '—' : `${m.sla_availability_percent.toFixed(2)}%` })}
                        {' · '}{tx('ai.model.health.checks', { success: m.sla_success_count || 0, total: m.sla_check_count || 0 })}
                      </div>
                      <div data-export-ignore className="mt-0.5 text-xs text-fg-subtle">
                        {tx('ai.model.health.avgLatency', { value: m.sla_avg_latency_ms == null ? '—' : `${m.sla_avg_latency_ms} ms` })}
                        {' · '}{tx('ai.model.health.lastCheck', { value: m.last_health_check_at ? new Date(m.last_health_check_at).toLocaleString() : tx('ai.model.health.never') })}
                        {m.last_error_code && <span className="ml-1 font-mono text-danger">· {m.last_error_code}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">{m.last_latency_ms == null ? '—' : `${m.last_latency_ms} ms`}</td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">${(m.cost_input_per_1k || 0).toFixed(4)}</td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={m.enabled ? 'success' : 'neutral'} dot>
                        {m.enabled ? tx('ai.model.status.enabled') : tx('ai.model.status.disabled')}
                      </StatusBadge>
                    </td>
                    <TableActionCell className="px-4 py-3 text-right">
                      <ActionIconGroup label={tx('ai.model.actionGroup')}>
                        <ActionIconButton icon={Pencil} label={language === 'zh' ? '编辑模型' : 'Edit model'} variant="accent" onClick={() => openEditModal(m)} />
                        <ActionIconButton icon={Activity} label={checkingModelId === m.id ? tx('ai.model.health.checking') : tx('ai.model.health.checkAction')} variant="accent" disabled={!m.enabled || checkingModelId !== null} iconClassName={checkingModelId === m.id ? 'animate-spin' : undefined} onClick={() => void handleHealthCheck(m)} />
                        <ActionIconButton icon={Star} label={tx('ai.model.action.setDefault')} variant="accent" onClick={() => void handleSetDefault(m)} />
                        <ActionIconButton icon={Power} label={m.enabled ? tx('ai.model.action.disable') : tx('ai.model.action.enable')} onClick={() => void handleToggle(m)} />
                        <ActionIconButton icon={Trash2} label={tx('ai.model.action.delete')} variant="danger" onClick={() => handleDelete(m.id)} />
                      </ActionIconGroup>
                    </TableActionCell>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
          {!visibleModels.length && <div className="border-t border-line px-4 py-10 text-center text-[13px] text-fg-muted">{copy.noMatch}</div>}
          <Pagination currentPage={page} totalItems={filteredModels.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </Panel>
      )}

      {/* Scene Routes Section */}
      <Panel aria-label={tx('ai.model.route.aria')}>
        <PanelHeader
          title={tx('ai.model.route.title')}
          description={tx('ai.model.route.description')}
          actions={(
            <span className="flex items-center gap-1.5 text-xs text-fg-muted">
              <ShieldCheck size={14} className="text-success" aria-hidden="true" />
              {tx('ai.model.route.currentDefault')}
              <strong className="font-mono font-medium text-fg">{defaultModel ? `${defaultModel.name} (${defaultModel.model_code})` : tx('ai.model.route.noneAvailable')}</strong>
            </span>
          )}
        />

        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
            <span className="font-medium text-fg">{tx('ai.model.route.how')}</span>
            <InfoTip label={copy.routesInfoLabel}>
              {[
                'ai.model.route.step.identifyBody',
                'ai.model.route.step.primaryBody',
                'ai.model.route.step.fallbackBody',
                'ai.model.route.step.defaultBody',
              ].map((key, index) => `${index + 1}. ${tx(key)}`).join(' ')}
            </InfoTip>
            {[
              ['1', 'ai.model.route.step.identify'],
              ['2', 'ai.model.route.step.primary'],
              ['3', 'ai.model.route.step.fallback'],
              ['4', 'ai.model.route.step.default'],
            ].map(([step, titleKey], index, steps) => (
              <React.Fragment key={step}>
                <span className="inline-flex items-center gap-1 rounded-md border border-line bg-surface-muted px-2 py-1">
                  <span className="font-semibold tabular-nums text-accent">{step}</span>{tx(titleKey)}
                </span>
                {index < steps.length - 1 && <span className="text-fg-subtle" aria-hidden="true">→</span>}
              </React.Fragment>
            ))}
            <span className="ml-1 text-fg-subtle">{tx('ai.model.route.enabledOnly')}</span>
          </div>

          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-muted px-3 py-2.5">
            <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] font-medium text-fg">
              <input
                type="checkbox"
                aria-label={tx('ai.model.route.bulk.selectAll')}
                checked={selectedScenes.size === SCENES.length}
                aria-checked={selectedScenes.size > 0 && selectedScenes.size < SCENES.length ? 'mixed' : selectedScenes.size === SCENES.length}
                onChange={toggleAllScenes}
                className={checkboxClass}
              />
              {tx('ai.model.route.bulk.selectAll')}
            </label>
            <span className="text-xs text-fg-muted">{tx('ai.model.route.bulk.selected', { count: selectedScenes.size })}</span>
            <InfoTip label={copy.bulkInfoLabel}>{tx('ai.model.route.bulk.description')}</InfoTip>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <select
                aria-label={tx('ai.model.route.bulk.primary')}
                value={bulkPrimaryModelId}
                onChange={(event) => setBulkPrimaryModelId(event.target.value)}
                className={cn(filterControlClass, 'min-w-[240px]')}
                disabled={selectedScenes.size === 0 || bulkApplying}
              >
                <option value="">{tx('ai.model.route.bulk.primaryPlaceholder')}</option>
                {models.filter((model) => model.enabled).map((model) => (
                  <option key={model.id} value={model.id}>{model.name} ({model.model_code})</option>
                ))}
              </select>
              <select
                aria-label={tx('ai.model.route.bulk.classification')}
                value={bulkDataClassification}
                onChange={(event) => setBulkDataClassification(event.target.value)}
                className={cn(filterControlClass, 'min-w-[180px]')}
                disabled={selectedScenes.size === 0 || bulkApplying}
              >
                <option value="">{tx('ai.model.route.bulk.classificationPlaceholder')}</option>
                <option value="PUBLIC">PUBLIC</option>
                <option value="INTERNAL">INTERNAL</option>
                <option value="CONFIDENTIAL">CONFIDENTIAL</option>
              </select>
              <ActionButton
                type="button"
                variant="primary"
                onClick={() => void handleBulkRouteChange()}
                disabled={selectedScenes.size === 0 || (!bulkPrimaryModelId && !bulkDataClassification) || bulkApplying}
              >
                {bulkApplying ? tx('ai.model.route.bulk.applying') : tx('ai.model.route.bulk.apply')}
              </ActionButton>
              {selectedScenes.size > 0 && (
                <ActionButton
                  type="button"
                  onClick={() => { setSelectedScenes(new Set()); setBulkPrimaryModelId(''); setBulkDataClassification(''); }}
                  disabled={bulkApplying}
                >
                  {tx('ai.model.route.bulk.clear')}
                </ActionButton>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
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
              const routeTone: StatusTone = routeTargetBlocked || (routeConfigured && !routeModel)
                ? 'danger'
                : routeHealthWarning
                  ? 'warning'
                  : routeConfigured && routeModel
                    ? 'success'
                    : 'neutral';
              const selected = selectedScenes.has(scene.code);
              return (
                <article key={scene.code} className={cn('rounded-lg border bg-surface p-4 transition-colors', selected ? 'border-accent ring-1 ring-accent/30' : 'border-line')}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-1.5">
                      <label className="flex min-w-0 cursor-pointer items-start gap-2.5">
                        <input
                          type="checkbox"
                          aria-label={tx('ai.model.route.bulk.selectScene', { name: tx(scene.shortKey) })}
                          checked={selected}
                          onChange={() => toggleSceneSelection(scene.code)}
                          className={cn(checkboxClass, 'mt-0.5')}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm font-semibold text-fg">{tx(scene.labelKey)}</span>
                          <span className="mt-0.5 block font-mono text-xs text-fg-muted">{scene.code}</span>
                        </span>
                      </label>
                      <InfoTip label={copy.sceneInfoLabel(tx(scene.shortKey))}>{tx(scene.descriptionKey)}</InfoTip>
                    </div>
                    <StatusBadge tone={routeTone} dot>{routeStatus}</StatusBadge>
                  </div>

                  <div className="mt-3 rounded-md bg-surface-muted px-3 py-2">
                    <div className="text-xs text-fg-muted">{tx('ai.model.route.effective')}</div>
                    <div className="mt-0.5 flex min-w-0 items-baseline gap-2">
                      <span className="truncate text-[13px] font-medium text-fg">{effectiveModel ? effectiveModel.name : tx('ai.model.route.noModel')}</span>
                      <span className="truncate font-mono text-xs text-fg-muted">{effectiveModel ? effectiveModel.model_code : tx('ai.model.route.addAndEnable')}</span>
                    </div>
                    <div className="mt-0.5 truncate text-xs text-fg-muted">{effectiveProvider ? tx('ai.model.route.provider', { name: effectiveProvider.name, status: effectiveProvider.enabled === false ? tx('ai.model.route.providerDisabled') : tx('ai.model.route.providerEnabled') }) : effectiveModel ? tx('ai.model.route.providerMissing') : tx('ai.model.route.providerDash')}</div>
                    {routeTargetBlocked && <p className="mt-1.5 text-xs leading-5 text-danger">{tx('ai.model.route.targetBlocked')}</p>}
                    {routeHealthWarning && !routeTargetBlocked && <p className="mt-1.5 text-xs leading-5 text-warning">{tx('ai.model.route.healthWarning')}</p>}
                  </div>

                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <label className="block text-xs font-medium text-fg-muted">
                      {tx('ai.model.route.primary')}
                      <select aria-label={tx('ai.model.route.primaryAria', { name: tx(scene.shortKey) })} value={configuredRoute?.model_id || ''} onChange={(event) => handleRouteChange(scene.code, event.target.value)} className={cn(filterControlClass, 'mt-1 w-full')}>
                        <option value="">{tx('ai.model.route.defaultOption')}</option>
                        {models.filter((model) => model.enabled || model.id === configuredRoute?.model_id).map((model) => <option key={model.id} value={model.id}>{model.name} ({model.model_code})</option>)}
                      </select>
                    </label>
                    <label className="block text-xs font-medium text-fg-muted">
                      {tx('ai.model.route.fallback')}
                      <select aria-label={tx('ai.model.route.fallbackAria', { name: tx(scene.shortKey) })} value={configuredRoute?.fallback_model_id || ''} onChange={(event) => void handleRoutePolicyChange(scene.code, event.target.value, configuredRoute?.data_classification || 'PUBLIC')} className={cn(filterControlClass, 'mt-1 w-full')}>
                        <option value="">{tx('ai.model.route.noFallbackOption')}</option>
                        {models.filter((model) => model.enabled && model.id !== configuredRoute?.model_id).map((model) => <option key={model.id} value={model.id}>{model.name} ({model.model_code})</option>)}
                      </select>
                    </label>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <label className="flex items-center gap-2 text-xs font-medium text-fg-muted">
                      {tx('ai.model.route.classification')}
                      <select aria-label={tx('ai.model.route.classificationAria', { name: tx(scene.shortKey) })} value={configuredRoute?.data_classification || 'PUBLIC'} onChange={(event) => void handleRoutePolicyChange(scene.code, configuredRoute?.fallback_model_id || '', event.target.value)} className={cn(filterControlClass, 'h-8 text-xs')}>
                        <option value="PUBLIC">PUBLIC</option>
                        <option value="INTERNAL">INTERNAL</option>
                        <option value="CONFIDENTIAL">CONFIDENTIAL</option>
                      </select>
                    </label>
                    <span className="text-xs text-fg-subtle">{tx('ai.model.route.priority', { priority: configuredRoute?.priority || 10, fallback: fallbackModel ? tx('ai.model.route.hasFallback') : tx('ai.model.route.noFallback') })}</span>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </Panel>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="ai-model-create-title" tabIndex={-1} className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-line bg-surface shadow-xl">
            <div className="border-b border-line px-6 py-4">
              <h3 id="ai-model-create-title" className="text-base font-semibold text-fg">
                {editingModelId ? (language === 'zh' ? '编辑模型配置' : 'Edit AI Model') : tx('ai.model.modal.title')}
              </h3>
            </div>
            <form onSubmit={handleCreate} className="space-y-4 px-6 py-5">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="ai-model-name" className={fieldLabelClass}>{tx('ai.model.modal.name')}</label>
                  <input
                    id="ai-model-name"
                    type="text"
                    required
                    placeholder={tx('ai.model.modal.namePlaceholder')}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className={fieldInputClass}
                  />
                </div>

                <div>
                  <label htmlFor="ai-model-code" className={fieldLabelClass}>{tx('ai.model.modal.code')}</label>
                  <input
                    id="ai-model-code"
                    type="text"
                    required
                    placeholder="deepseek-v4-flash"
                    value={modelCode}
                    onChange={(e) => setModelCode(e.target.value)}
                    className={cn(fieldInputClass, 'font-mono')}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="ai-model-type" className={fieldLabelClass}>{tx('ai.model.modal.type')}</label>
                  <select id="ai-model-type" value={modelType} onChange={(e) => setModelType(e.target.value)} className={fieldInputClass}>
                    <option value="chat">{tx('ai.model.modal.chat')}</option>
                    <option value="reasoning">{tx('ai.model.modal.reasoning')}</option>
                    <option value="embedding">{tx('ai.model.modal.embedding')}</option>
                    <option value="rerank">{tx('ai.model.modal.rerank')}</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="ai-model-provider" className={fieldLabelClass}>{tx('ai.model.modal.provider')}</label>
                  <select
                    id="ai-model-provider"
                    value={providerId}
                    onChange={(e) => setProviderId(e.target.value)}
                    className={fieldInputClass}
                  >
                    {providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.provider_type})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div>
                  <label htmlFor="ai-model-ctx" className={fieldLabelClass}>{tx('ai.model.table.contextLength')}</label>
                  <input id="ai-model-ctx" type="number" min={1024} value={contextLength} onChange={(e) => setContextLength(Number(e.target.value) || 64000)} className={cn(fieldInputClass, 'font-mono')} />
                </div>
                <div>
                  <label htmlFor="ai-model-max-out" className={fieldLabelClass}>{language === 'zh' ? '最大输出 Token' : 'Max Output'}</label>
                  <input id="ai-model-max-out" type="number" min={256} value={maxOutputTokens} onChange={(e) => setMaxOutputTokens(Number(e.target.value) || 4096)} className={cn(fieldInputClass, 'font-mono')} />
                </div>
                <div>
                  <label htmlFor="ai-model-priority" className={fieldLabelClass}>{language === 'zh' ? '优先级' : 'Priority'}</label>
                  <input id="ai-model-priority" type="number" min={1} max={1000} value={priority} onChange={(e) => setPriority(Number(e.target.value) || 10)} className={cn(fieldInputClass, 'font-mono')} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="ai-model-cost-in" className={fieldLabelClass}>{language === 'zh' ? '输入成本 ($/1K tok)' : 'Input Cost ($/1K)'}</label>
                  <input id="ai-model-cost-in" type="number" step="0.0001" min={0} value={costInputPer1k} onChange={(e) => setCostInputPer1k(Number(e.target.value) || 0)} className={cn(fieldInputClass, 'font-mono')} />
                </div>
                <div>
                  <label htmlFor="ai-model-cost-out" className={fieldLabelClass}>{language === 'zh' ? '输出成本 ($/1K tok)' : 'Output Cost ($/1K)'}</label>
                  <input id="ai-model-cost-out" type="number" step="0.0001" min={0} value={costOutputPer1k} onChange={(e) => setCostOutputPer1k(Number(e.target.value) || 0)} className={cn(fieldInputClass, 'font-mono')} />
                </div>
              </div>

              <fieldset className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-surface-muted p-3">
                <legend className="px-1 text-xs font-medium text-fg-muted">{copy.capabilities}</legend>
                <label className="flex items-center gap-2 text-[13px] text-fg">
                  <input type="checkbox" checked={streamSupported} onChange={(e) => setStreamSupported(e.target.checked)} className={checkboxClass} />
                  {tx('ai.model.table.streaming')}
                </label>
                <label className="flex items-center gap-2 text-[13px] text-fg">
                  <input type="checkbox" checked={thinkingSupported} onChange={(e) => setThinkingSupported(e.target.checked)} className={checkboxClass} />
                  {tx('ai.model.table.thinking')}
                </label>
                <label className="flex items-center gap-2 text-[13px] text-fg">
                  <input type="checkbox" checked={toolCallSupported} onChange={(e) => setToolCallSupported(e.target.checked)} className={checkboxClass} />
                  {tx('ai.model.table.toolCalls')}
                </label>
                <label className="flex items-center gap-2 text-[13px] text-fg">
                  <input type="checkbox" checked={jsonSupported} onChange={(e) => setJsonSupported(e.target.checked)} className={checkboxClass} />
                  {tx('ai.model.table.json')}
                </label>
              </fieldset>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is_default"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                  className={checkboxClass}
                />
                <label htmlFor="is_default" className="text-[13px] font-medium text-fg">
                  {tx('ai.model.modal.default')}
                </label>
              </div>

              <div className="flex justify-end gap-2 border-t border-line pt-4">
                <ActionButton type="button" size="md" onClick={() => { setShowModal(false); setEditingModelId(null); }}>
                  {tx('ai.model.modal.cancel')}
                </ActionButton>
                <ActionButton type="submit" variant="primary" size="md">
                  {editingModelId ? (language === 'zh' ? '保存修改' : 'Save Changes') : tx('ai.model.modal.submit')}
                </ActionButton>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
