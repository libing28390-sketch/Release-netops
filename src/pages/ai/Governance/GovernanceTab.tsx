import React, { useState } from 'react';
import { ShieldCheck, AlertTriangle, FileCode, CheckCircle2, Send, Plus } from 'lucide-react';
import { generateAIConfig, createChangeDraft } from '../../../api/ai';

export const GovernanceTab: React.FC = () => {
  const [intent, setIntent] = useState('在 Core-SW01 上为 VLAN 200 配置 OSPF 宣告');
  const [vendor, setVendor] = useState('Huawei');
  const [platform, setPlatform] = useState('huawei_vrp');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [submittingDraft, setSubmittingDraft] = useState(false);
  const [draftResult, setDraftResult] = useState<any>(null);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!intent.trim() || loading) return;
    setLoading(true);
    setResult(null);
    setDraftResult(null);
    try {
      const res = await generateAIConfig(intent.trim(), vendor, platform);
      setResult(res);
    } catch (err: any) {
      alert(err.message || '配置生成失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateDraft = async () => {
    if (!result || submittingDraft) return;
    setSubmittingDraft(true);
    try {
      const res = await createChangeDraft({
        title: `AI 配置变更 - ${intent}`,
        device_id: 'Core-SW01',
        commands: result.commands,
        verification_commands: result.verification_commands,
        rollback_commands: result.rollback_commands,
      });
      setDraftResult(res);
    } catch (err: any) {
      alert(err.message || '提交草稿失败');
    } finally {
      setSubmittingDraft(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <ShieldCheck className="w-6 h-6 text-indigo-500" />
          AI 变更治理与受控下发门禁 (Generate ≠ Execute)
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          AI 生成网络命令、验证命令与回滚命令，严禁 AI 直接连接设备写入；必须提交工单并经过人类审批。
        </p>
      </div>

      <form onSubmit={handleGenerate} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">配置变更意图描述</label>
            <input
              type="text"
              required
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">厂商 & 平台</label>
            <select
              value={platform}
              onChange={(e) => {
                setPlatform(e.target.value);
                setVendor(e.target.value.includes('cisco') ? 'Cisco' : e.target.value.includes('h3c') ? 'H3C' : 'Huawei');
              }}
              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-900 dark:text-white"
            >
              <option value="huawei_vrp">Huawei VRP</option>
              <option value="h3c_comware">H3C Comware</option>
              <option value="cisco_ios">Cisco IOS</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={loading || !intent.trim()}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm rounded-xl flex items-center gap-1.5 disabled:opacity-50 transition"
          >
            {loading ? '生成中...' : '生成配置命令 (Generate)'}
          </button>
        </div>
      </form>

      {result && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-6 shadow-sm space-y-6">
          {/* Safety Warning */}
          {result.safety_warnings?.length > 0 && (
            <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-300 text-xs space-y-1">
              <div className="font-bold flex items-center gap-1.5 text-sm">
                <AlertTriangle className="w-4 h-4 text-red-500" /> 高危命令拦截告警！
              </div>
              {result.safety_warnings.map((w: any, idx: number) => (
                <p key={idx}>• {w.reason} (命令: {w.command})</p>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 font-mono text-xs">
            {/* Commands */}
            <div className="space-y-2">
              <h4 className="font-bold text-gray-900 dark:text-white font-sans text-sm">配置变更命令</h4>
              <div className="bg-gray-900 text-emerald-400 p-3 rounded-xl leading-relaxed whitespace-pre-wrap min-h-[120px]">
                {result.commands?.join('\n') || '# 无命令'}
              </div>
            </div>

            {/* Verification Commands */}
            <div className="space-y-2">
              <h4 className="font-bold text-gray-900 dark:text-white font-sans text-sm">验证命令 (Verification)</h4>
              <div className="bg-gray-900 text-blue-400 p-3 rounded-xl leading-relaxed whitespace-pre-wrap min-h-[120px]">
                {result.verification_commands?.join('\n') || '# 无验证命令'}
              </div>
            </div>

            {/* Rollback Commands */}
            <div className="space-y-2">
              <h4 className="font-bold text-gray-900 dark:text-white font-sans text-sm">回滚命令 (Rollback)</h4>
              <div className="bg-gray-900 text-amber-400 p-3 rounded-xl leading-relaxed whitespace-pre-wrap min-h-[120px]">
                {result.rollback_commands?.join('\n') || '# 无回滚命令'}
              </div>
            </div>
          </div>

          {draftResult ? (
            <div className="p-4 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 rounded-xl text-xs flex items-center justify-between font-mono">
              <span>✓ 变更工单草稿创建成功 (ID: {draftResult.change_id})</span>
              <span className="font-sans font-bold">已送去人类管理员审批</span>
            </div>
          ) : (
            <div className="flex items-center justify-between pt-4 border-t border-gray-200 dark:border-gray-700">
              <span className="text-xs text-gray-400">门禁提示：AI 生成结果禁止自动下发，点击提交为工单草稿。</span>
              <button
                onClick={handleCreateDraft}
                disabled={submittingDraft}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs rounded-xl flex items-center gap-1.5 transition"
              >
                <Send className="w-3.5 h-3.5" /> 提交变更工单 (送审批)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
