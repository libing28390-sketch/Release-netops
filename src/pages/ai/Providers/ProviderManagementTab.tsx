import React, { useEffect, useState } from 'react';
import { Bot, Key, Plus, RefreshCw, Trash2, CheckCircle, XCircle, Shield, Globe } from 'lucide-react';
import { getAIProviders, createAIProvider, deleteAIProvider, testAIProvider, AIProvider } from '../../../api/ai';

export const ProviderManagementTab: React.FC = () => {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string; latency_ms?: number } | null>(null);
  
  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState('deepseek');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [defaultModelCode, setDefaultModelCode] = useState('deepseek-chat');
  const [timeout, setTimeout] = useState(30);
  const [submitting, setSubmitting] = useState(false);

  const fetchProviders = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAIProviders();
      setProviders(data);
    } catch (err: any) {
      setError(err.message || '获取 Provider 列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  const handleTest = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const res = await testAIProvider(id);
      setTestResult({
        id,
        success: res.success,
        message: res.message,
        latency_ms: res.latency_ms,
        sample_response: res.sample_response,
      });
    } catch (err: any) {
      setTestResult({
        id,
        success: false,
        message: err.message || '测试连通性失败',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('确定要删除该 Provider 吗？')) return;
    try {
      await deleteAIProvider(id);
      fetchProviders();
    } catch (err: any) {
      alert(err.message || '删除失败');
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await createAIProvider({
        name,
        provider_type: providerType,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        default_model_code: defaultModelCode || undefined,
        timeout,
        enabled: true,
      });
      setShowModal(false);
      setName('');
      setApiKey('');
      setBaseUrl('');
      fetchProviders();
    } catch (err: any) {
      alert(err.message || '添加失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Bot className="w-6 h-6 text-indigo-500" />
            AI Provider 供应商管理
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            配置模型供应商 API Key (AES-256-GCM 加密存储) 及 Base URL，支持 DeepSeek、OpenAI 及兼容端点。
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={fetchProviders}
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
            添加 Provider
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-lg text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="p-8 text-center text-gray-500 dark:text-gray-400">加载中...</div>
      ) : providers.length === 0 ? (
        <div className="p-12 text-center border-2 border-dashed border-gray-200 dark:border-gray-800 rounded-xl">
          <Bot className="w-12 h-12 text-gray-400 mx-auto mb-3" />
          <p className="text-gray-600 dark:text-gray-300 font-medium">暂无 Provider 供应商配置</p>
          <p className="text-sm text-gray-400 mt-1">点击右上角添加 DeepSeek 或 OpenAI 兼容供应商</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {providers.map((p) => (
            <div
              key={p.id}
              className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm space-y-4 hover:border-indigo-300 dark:hover:border-indigo-600 transition"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-900 dark:text-white text-base">{p.name}</span>
                    <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 uppercase">
                      {p.provider_type}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-1 font-mono">{p.id}</p>
                </div>
                <button
                  onClick={() => handleDelete(p.id)}
                  className="text-gray-400 hover:text-red-600 transition p-1"
                  title="删除"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-2 text-xs text-gray-600 dark:text-gray-300 font-mono">
                <div className="flex items-center gap-2 bg-gray-50 dark:bg-gray-900/50 p-2 rounded-md">
                  <Globe className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <span className="truncate">{p.base_url || '(使用默认端点)'}</span>
                </div>
                <div className="flex items-center gap-2 bg-gray-50 dark:bg-gray-900/50 p-2 rounded-md">
                  <Key className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <span>{p.api_key_masked || '未配置 Key'}</span>
                  <span className="ml-auto text-[10px] text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                    <Shield className="w-3 h-3" /> AES-256
                  </span>
                </div>
              </div>

              {testResult && testResult.id === p.id && (
                <div
                  className={`p-3 rounded-lg text-xs flex items-start gap-2 ${
                    testResult.success
                      ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                      : 'bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300'
                  }`}
                >
                  {testResult.success ? (
                    <CheckCircle className="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
                  ) : (
                    <XCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="font-medium">{testResult.message}</p>
                    {testResult.latency_ms !== undefined && (
                      <p className="text-[10px] mt-0.5 opacity-80">响应延迟: {testResult.latency_ms} ms</p>
                    )}
                    {testResult.sample_response && (
                      <div className="mt-2 p-2 rounded bg-black/5 dark:bg-white/5 border border-black/5 dark:border-white/5 font-sans leading-relaxed text-[11px] text-gray-800 dark:text-gray-200 break-words">
                        <span className="font-semibold text-emerald-600 dark:text-emerald-400">模型回答：</span>
                        "{testResult.sample_response}"
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="pt-2 border-t border-gray-100 dark:border-gray-700/60 flex items-center justify-between text-xs">
                <span className="text-gray-400">超时: {p.timeout}s</span>
                <button
                  onClick={() => handleTest(p.id)}
                  disabled={testingId === p.id}
                  className="px-3 py-1.5 bg-indigo-50 dark:bg-indigo-950 hover:bg-indigo-100 text-indigo-700 dark:text-indigo-300 rounded-md font-medium flex items-center gap-1 transition disabled:opacity-50"
                >
                  {testingId === p.id ? '测试中...' : '测试连通性'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">添加 AI Provider 供应商</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">名称</label>
                <input
                  type="text"
                  required
                  placeholder="例如：DeepSeek 官方"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">供应商类型</label>
                <select
                  value={providerType}
                  onChange={(e) => {
                    setProviderType(e.target.value);
                    if (e.target.value === 'deepseek' && !baseUrl) {
                      setBaseUrl('https://api.deepseek.com');
                    }
                  }}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                >
                  <option value="deepseek">DeepSeek</option>
                  <option value="openai">OpenAI</option>
                  <option value="qwen">千问 (Qwen)</option>
                  <option value="ollama">Ollama (本地)</option>
                  <option value="openai_compatible">OpenAI Compatible (通用)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Base URL</label>
                <input
                  type="text"
                  placeholder="https://api.deepseek.com"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">API Key (AES-256 加密保存)</label>
                <input
                  type="password"
                  placeholder="sk-..."
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">绑定模型 (Model Code)</label>
                  <span className="text-[10px] text-indigo-600 dark:text-indigo-400">自动注册至模型列表与路由</span>
                </div>
                <input
                  type="text"
                  placeholder={
                    providerType === 'deepseek' ? 'deepseek-chat' :
                    providerType === 'openai' ? 'gpt-4o' :
                    providerType === 'qwen' ? 'qwen-max' : 'model-code'
                  }
                  value={defaultModelCode}
                  onChange={(e) => setDefaultModelCode(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">超时秒数</label>
                <input
                  type="number"
                  min={5}
                  max={300}
                  value={timeout}
                  onChange={(e) => setTimeout(parseInt(e.target.value))}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                />
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
                  disabled={submitting}
                  className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg disabled:opacity-50"
                >
                  {submitting ? '提交中...' : '确认添加'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
