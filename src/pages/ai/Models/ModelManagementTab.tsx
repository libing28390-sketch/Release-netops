import React, { useEffect, useState } from 'react';
import { Cpu, Plus, RefreshCw, Trash2, GitBranch, Star } from 'lucide-react';
import { getAIModels, createAIModel, deleteAIModel, getAIModelRoutes, upsertAIModelRoute, getAIProviders, AIModel, AIModelRoute, AIProvider } from '../../../api/ai';

export const ModelManagementTab: React.FC = () => {
  const [models, setModels] = useState<AIModel[]>([]);
  const [routes, setRoutes] = useState<AIModelRoute[]>([]);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [loading, setLoading] = useState(true);

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [providerId, setProviderId] = useState('');
  const [modelCode, setModelCode] = useState('');
  const [isDefault, setIsDefault] = useState(false);

  const fetchData = async () => {
    setLoading(true);
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
      console.error(err);
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
        model_type: 'chat',
        is_default: isDefault,
        enabled: true,
      });
      setShowModal(false);
      setName('');
      setModelCode('');
      fetchData();
    } catch (err: any) {
      alert(err.message || '添加模型失败');
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

  return (
    <div className="space-y-8">
      {/* Models Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <Cpu className="w-6 h-6 text-indigo-500" />
              AI Model 模型管理
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
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

        {loading ? (
          <div className="p-8 text-center text-gray-400">加载中...</div>
        ) : (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 text-xs font-semibold">
                  <th className="py-3 px-4">模型名称</th>
                  <th className="py-3 px-4">Model Code</th>
                  <th className="py-3 px-4">供应商 ID</th>
                  <th className="py-3 px-4">默认模型</th>
                  <th className="py-3 px-4">状态</th>
                  <th className="py-3 px-4 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700 text-gray-700 dark:text-gray-300">
                {models.map((m) => (
                  <tr key={m.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                    <td className="py-3 px-4 font-semibold text-gray-900 dark:text-white">{m.name}</td>
                    <td className="py-3 px-4 font-mono text-xs text-indigo-600 dark:text-indigo-400">{m.model_code}</td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-400">{m.provider_id}</td>
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
                      <button onClick={() => handleDelete(m.id)} className="text-gray-400 hover:text-red-600">
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
