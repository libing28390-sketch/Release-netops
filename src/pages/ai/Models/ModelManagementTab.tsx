import React, { useEffect, useMemo, useState } from 'react';
import { Cpu, Plus, RefreshCw, Trash2, GitBranch, Star, Power, Search, AlertTriangle } from 'lucide-react';
import { getAIModels, createAIModel, updateAIModel, setAIUserDefaultModel, deleteAIModel, getAIModelRoutes, upsertAIModelRoute, getAIProviders, AIModel, AIModelRoute, AIProvider } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';

export const ModelManagementTab: React.FC = () => {
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
      setError(err?.message || '模型、Provider 或路由加载失败');
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
      alert(err.message || '添加模型失败');
    }
  };

  const handleToggle = async (model: AIModel) => {
    try {
      await updateAIModel(model.id, { enabled: !model.enabled });
      await fetchData();
    } catch (err: any) {
      alert(err.message || '更新模型状态失败');
    }
  };

  const handleSetDefault = async (model: AIModel) => {
    try {
      await updateAIModel(model.id, { is_default: true });
      await setAIUserDefaultModel(model.id);
      await fetchData();
    } catch (err: any) {
      alert(err.message || '设置默认模型失败');
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('确定删除该 Model 吗？')) return;
    try {
      await deleteAIModel(id);
      fetchData();
    } catch (err: any) {
      alert(err.message || '删除失败');
    }
  };

  const handleRouteChange = async (scene: string, modelId: string) => {
    try {
      await upsertAIModelRoute({ scene, model_id: modelId, enabled: true });
      fetchData();
    } catch (err: any) {
      alert(err.message || '配置场景路由失败');
    }
  };

  const SCENES = [
    { code: 'command_explain', label: '命令解释' },
    { code: 'config_explain', label: '配置分析' },
    { code: 'config_diff', label: 'Diff 智能分析' },
    { code: 'alarm_analysis', label: '告警分析' },
    { code: 'chat', label: 'AI 助手' },
    { code: 'troubleshooting', label: '网络故障诊断' },
  ];

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

  return (
    <div className="space-y-8">
      {/* Models Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="nx-page-title flex items-center gap-2 text-gray-900 dark:text-white">
              <Cpu className="w-6 h-6 text-indigo-500" />
              AI Model 模型管理
            </h2>
            <p className="nx-page-description mt-1 text-gray-500 dark:text-gray-400">
              定义可供调用的模型标识（如 deepseek-v4-flash, deepseek-v4-pro）。
            </p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={fetchData}
              className="px-3 py-2 text-sm bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 text-gray-700 dark:text-gray-300 rounded-lg flex items-center gap-1.5 transition"
            >
              <RefreshCw className="w-4 h-4" />
              刷新
            </button>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg flex items-center gap-1.5 font-medium shadow-sm transition"
            >
              <Plus className="w-4 h-4" />
              添加 Model
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 rounded-xl border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="relative min-w-[240px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索模型名称、Model Code、Provider 或健康状态" className="w-full rounded-lg border border-gray-200 py-2 pl-9 pr-3 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white" /></div>
          <select value={providerFilter} onChange={(event) => { setProviderFilter(event.target.value); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="">全部 Provider</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select>
          <select value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="">全部用途</option><option value="chat">Chat</option><option value="reasoning">Reasoning</option><option value="embedding">Embedding</option><option value="rerank">Rerank</option></select>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-white"><option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select>
        </div>

        {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"><AlertTriangle className="h-4 w-4" />{error}</div>}

        {loading ? (
          <div className="p-8 text-center text-gray-400">加载中...</div>
        ) : (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 text-xs font-semibold">
                  <th className="py-3 px-4">模型名称</th>
                  <th className="py-3 px-4">Model Code</th>
                  <th className="py-3 px-4">Provider / 能力</th>
                  <th className="py-3 px-4">默认模型</th>
                  <th className="py-3 px-4">状态</th>
                  <th className="py-3 px-4 text-right">操作</th>
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
                        {m.enabled ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <ActionIconGroup label="模型操作">
                        <ActionIconButton icon={Star} label="设为当前用户默认" variant="accent" onClick={() => void handleSetDefault(m)} />
                        <ActionIconButton icon={Power} label={m.enabled ? '禁用' : '启用'} onClick={() => void handleToggle(m)} />
                        <ActionIconButton icon={Trash2} label="删除" variant="danger" onClick={() => handleDelete(m.id)} />
                      </ActionIconGroup>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visibleModels.length && <div className="border-t border-gray-100 px-4 py-10 text-center text-sm text-gray-400 dark:border-gray-700">当前搜索和筛选没有匹配模型</div>}
            <Pagination currentPage={page} totalItems={filteredModels.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language="zh" alwaysVisible />
          </div>
        )}
      </div>

      {/* Scene Routes Section */}
      <div className="space-y-4 pt-6 border-t border-gray-200 dark:border-gray-700">
        <div>
          <h3 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-indigo-500" />
            Model Route 场景动态路由
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            针对不同业务场景（如配置分析、Diff 智能分析、告警诊断）分派最适合的模型。
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {SCENES.map((scene) => {
            const activeRoute = routes.find((r) => r.scene === scene.code);
            return (
              <div key={scene.code} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 flex items-center justify-between shadow-sm">
                <div>
                  <h4 className="font-semibold text-gray-900 dark:text-white text-sm">{scene.label}</h4>
                  <p className="text-xs text-gray-400 font-mono mt-0.5">{scene.code}</p>
                </div>
                <select
                  aria-label={`${scene.label}模型路由`}
                  value={activeRoute?.model_id || ''}
                  onChange={(e) => handleRouteChange(scene.code, e.target.value)}
                  className="px-3 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-medium"
                >
                  <option value="">(使用全局默认模型)</option>
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.model_code})
                    </option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>
      </div>

      {/* Create Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">添加 AI Model 模型</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">模型显示名称</label>
                <input
                  type="text"
                  required
                  placeholder="例如：DeepSeek V4 Flash"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Model Code (实际 API 请求参数)</label>
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
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">模型用途</label>
                <select value={modelType} onChange={(e) => setModelType(e.target.value)} className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white">
                  <option value="chat">Chat 对话</option>
                  <option value="reasoning">Reasoning 推理</option>
                  <option value="embedding">Embedding 向量</option>
                  <option value="rerank">Rerank 重排</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">关联 Provider</label>
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
                  设为系统全局默认模型
                </label>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg"
                >
                  确认添加
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
