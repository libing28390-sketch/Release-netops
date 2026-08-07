import React, { useEffect, useState } from 'react';
import { FileCode, RefreshCw, Plus, Eye } from 'lucide-react';
import { getAIPrompts, createAIPrompt, AIPrompt } from '../../../api/ai';

export const PromptCenterTab: React.FC = () => {
  const [prompts, setPrompts] = useState<AIPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPrompt, setSelectedPrompt] = useState<AIPrompt | null>(null);

  // Create Modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [scene, setScene] = useState('chat');
  const [systemPrompt, setSystemPrompt] = useState('你是一名高级网络工程专家。');
  const [userPromptTemplate, setUserPromptTemplate] = useState('分析设备状态: {input}');

  const fetchPrompts = async () => {
    setLoading(true);
    try {
      const data = await getAIPrompts();
      setPrompts(data);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPrompts();
  }, []);

  const handleCreatePrompt = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createAIPrompt({
        code,
        name,
        scene,
        system_prompt: systemPrompt,
        user_prompt_template: userPromptTemplate,
        enabled: true,
      });
      setShowCreateModal(false);
      setCode('');
      setName('');
      fetchPrompts();
    } catch (err: any) {
      alert(err.message || '创建 Prompt 失败');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <FileCode className="w-6 h-6 text-indigo-500" />
            Prompt Center 提示词中心
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            网络运维 Prompt 模版与版本审计追溯。禁止在业务代码中硬编码 Prompt。
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={fetchPrompts}
            className="px-3 py-2 text-sm bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 text-gray-700 dark:text-gray-300 rounded-lg flex items-center gap-1.5 transition"
          >
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg flex items-center gap-1.5 font-medium shadow-sm transition"
          >
            <Plus className="w-4 h-4" />
            添加 Prompt
          </button>
        </div>
      </div>

      {loading ? (
        <div className="p-8 text-center text-gray-400">加载中...</div>
      ) : prompts.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-12 text-center text-gray-500 dark:text-gray-400">
          <FileCode className="w-12 h-12 text-indigo-400 mx-auto mb-3 opacity-60" />
          <p className="font-semibold text-base">暂无 Prompt 模版</p>
          <p className="text-xs mt-1">点击右上角 “添加 Prompt” 创建首个运维提示词模版。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {prompts.map((p) => (
            <div
              key={p.id}
              className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm space-y-3"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-900 dark:text-white text-base">{p.name}</span>
                    <span className="px-2 py-0.5 text-xs bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300 rounded font-mono font-medium">
                      v{p.version}
                    </span>
                  </div>
                  <p className="text-xs font-mono text-indigo-600 dark:text-indigo-400 mt-1">{p.code}</p>
                </div>
                <button
                  onClick={() => setSelectedPrompt(p)}
                  className="px-3 py-1.5 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 text-gray-700 dark:text-gray-300 text-xs font-medium rounded-md flex items-center gap-1 transition"
                >
                  <Eye className="w-3.5 h-3.5" /> 查看详情
                </button>
              </div>

              <div className="text-xs space-y-2 text-gray-600 dark:text-gray-300">
                <div className="bg-gray-50 dark:bg-gray-900/60 p-3 rounded-lg border border-gray-100 dark:border-gray-800 font-mono text-[11px] leading-relaxed line-clamp-3">
                  <span className="text-gray-400 font-semibold block mb-1">System Prompt:</span>
                  {p.system_prompt}
                </div>
                <div className="bg-gray-50 dark:bg-gray-900/60 p-3 rounded-lg border border-gray-100 dark:border-gray-800 font-mono text-[11px] leading-relaxed line-clamp-2">
                  <span className="text-gray-400 font-semibold block mb-1">User Template:</span>
                  {p.user_prompt_template}
                </div>
              </div>

              <div className="flex items-center justify-between text-xs text-gray-400 pt-2 border-t border-gray-100 dark:border-gray-700/60">
                <span>场景: <strong className="text-gray-600 dark:text-gray-300">{p.scene}</strong></span>
                <span>Temp: <strong className="text-gray-600 dark:text-gray-300">{p.temperature}</strong></span>
                <span>Max Tokens: <strong className="text-gray-600 dark:text-gray-300">{p.max_tokens}</strong></span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl max-w-lg w-full p-6 space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">添加 Prompt 提示词模版</h3>
            <form onSubmit={handleCreatePrompt} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Prompt Code (标识符)</label>
                <input
                  type="text"
                  required
                  placeholder="prompt_troubleshoot_v1"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">模版名称</label>
                <input
                  type="text"
                  required
                  placeholder="故障诊断 Prompt 模版"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">应用场景</label>
                <select
                  value={scene}
                  onChange={(e) => setScene(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
                >
                  <option value="chat">AI Copilot 对话</option>
                  <option value="troubleshooting">网络故障排查</option>
                  <option value="config_explain">配置分析解释</option>
                  <option value="config_diff">Diff 智能对比</option>
                  <option value="alarm_analysis">告警根因诊断</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">System Prompt (系统提示词)</label>
                <textarea
                  rows={3}
                  required
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">User Prompt Template (包含变量如 &#123;input&#125;)</label>
                <textarea
                  rows={3}
                  required
                  value={userPromptTemplate}
                  onChange={(e) => setUserPromptTemplate(e.target.value)}
                  className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white font-mono"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
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

      {/* Detail Modal */}
      {selectedPrompt && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl max-w-2xl w-full p-6 space-y-4 shadow-xl max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 pb-3">
              <div>
                <h3 className="text-lg font-bold text-gray-900 dark:text-white">{selectedPrompt.name}</h3>
                <p className="text-xs font-mono text-indigo-500">{selectedPrompt.code} (v{selectedPrompt.version})</p>
              </div>
              <button
                onClick={() => setSelectedPrompt(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-gray-400 font-bold mb-1">System Prompt</label>
                <div className="bg-gray-900 text-gray-100 p-3 rounded-lg leading-relaxed whitespace-pre-wrap">
                  {selectedPrompt.system_prompt}
                </div>
              </div>

              <div>
                <label className="block text-gray-400 font-bold mb-1">User Prompt Template</label>
                <div className="bg-gray-900 text-gray-100 p-3 rounded-lg leading-relaxed whitespace-pre-wrap">
                  {selectedPrompt.user_prompt_template}
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-4 border-t border-gray-200 dark:border-gray-700">
              <button
                onClick={() => setSelectedPrompt(null)}
                className="px-4 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PromptCenterTab;
