import React, { useEffect, useState } from 'react';
import { ShieldCheck, AlertTriangle, CheckCircle2, Send, Server, LoaderCircle } from 'lucide-react';
import { generateAIConfig, createChangeDraft } from '../../../api/ai';
import { apiRequest } from '../../../api/http';
import { useCoreApp } from '../../../contexts/AppDomainContext';

interface TargetDeviceOption {
  id: string;
  hostname: string;
  ip_address?: string;
  vendor?: string;
  platform?: string;
}

export const GovernanceTab: React.FC = () => {
  const { showToast } = useCoreApp();
  const [devices, setDevices] = useState<TargetDeviceOption[]>([]);
  const [targetDeviceId, setTargetDeviceId] = useState('');
  const [intent, setIntent] = useState('为业务 VLAN 200 配置 OSPF 宣告与被动接口保护');
  const [vendor, setVendor] = useState('Huawei');
  const [platform, setPlatform] = useState('huawei_vrp');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [submittingDraft, setSubmittingDraft] = useState(false);
  const [draftResult, setDraftResult] = useState<any>(null);
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const res = await apiRequest<any>('/api/devices?limit=200');
        const list = Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
        if (!active) return;
        const mapped: TargetDeviceOption[] = list.map((d: any) => ({
          id: String(d.id || d.hostname),
          hostname: String(d.hostname || d.name || d.id),
          ip_address: d.ip_address ? String(d.ip_address) : undefined,
          vendor: d.vendor ? String(d.vendor) : undefined,
          platform: d.platform ? String(d.platform) : undefined,
        }));
        setDevices(mapped);
        if (mapped.length > 0 && !targetDeviceId) {
          setTargetDeviceId(mapped[0].id);
        }
      } catch {
        // Inventory may be empty or restricted; allow manual device identifier input
      }
    })();
    return () => { active = false; };
  }, []);

  const handleSelectDevice = (id: string) => {
    setTargetDeviceId(id);
    const dev = devices.find((item) => item.id === id);
    if (dev?.platform) {
      setPlatform(dev.platform);
      setVendor(dev.vendor || (dev.platform.includes('cisco') ? 'Cisco' : dev.platform.includes('h3c') ? 'H3C' : 'Huawei'));
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!intent.trim() || loading) return;
    setLoading(true);
    setResult(null);
    setDraftResult(null);
    setRiskAcknowledged(false);
    try {
      const res = await generateAIConfig(intent.trim(), vendor, platform);
      setResult(res);
    } catch (err: any) {
      showToast(err?.message || '配置生成失败', 'error');
    } finally {
      setLoading(false);
    }
  };

  const hasSafetyWarnings = Boolean(result?.safety_warnings?.length);

  const handleCreateDraft = async () => {
    if (!result || submittingDraft) return;
    if (hasSafetyWarnings && !riskAcknowledged) {
      showToast('检测到高危命令告警，请先勾选风险确认后再提交工单草稿', 'error');
      return;
    }
    const resolvedDevice = targetDeviceId.trim() || 'manual-target-device';
    setSubmittingDraft(true);
    try {
      const res = await createChangeDraft({
        title: `AI 配置变更 - ${intent.trim().slice(0, 80)}`,
        device_id: resolvedDevice,
        commands: Array.isArray(result.commands) ? result.commands : [],
        verification_commands: Array.isArray(result.verification_commands) ? result.verification_commands : [],
        rollback_commands: Array.isArray(result.rollback_commands) ? result.rollback_commands : [],
      });
      setDraftResult(res);
      showToast(`变更工单草稿已落库 (${res.order_number || res.change_id})`, 'success');
    } catch (err: any) {
      showToast(err?.message || '提交草稿失败', 'error');
    } finally {
      setSubmittingDraft(false);
    }
  };

  return (
    <div className="w-full space-y-6 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-indigo-100/80 bg-gradient-to-br from-white via-indigo-50/70 to-emerald-50/60 p-6 shadow-sm dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/40 dark:to-slate-900">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-indigo-200/80 bg-white/80 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300">
              <ShieldCheck className="h-3.5 w-3.5" /> Generate ≠ Execute
            </div>
            <h2 className="nx-page-title text-slate-950 dark:text-white">
              AI 变更治理与受控下发门禁
            </h2>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-600 dark:text-slate-300">
              AI 仅生成多厂商配置命令、验证命令与回滚方案，严禁直接连接设备写入；提交后将持久化为标准变更工单草稿并进入人工审批流程。
            </p>
          </div>
        </div>
      </section>

      <form onSubmit={handleGenerate} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
          <div className="md:col-span-6">
            <label className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">配置变更意图描述</label>
            <input
              type="text"
              required
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-500/15 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            />
          </div>
          <div className="md:col-span-3">
            <label className="mb-1.5 flex items-center gap-1 text-xs font-bold text-slate-700 dark:text-slate-300">
              <Server className="h-3.5 w-3.5 text-indigo-500" /> 目标设备
            </label>
            {devices.length > 0 ? (
              <select
                value={targetDeviceId}
                onChange={(e) => handleSelectDevice(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
              >
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.hostname}{d.ip_address ? ` (${d.ip_address})` : ''}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={targetDeviceId}
                onChange={(e) => setTargetDeviceId(e.target.value)}
                placeholder="输入设备 ID 或主机名"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
              />
            )}
          </div>
          <div className="md:col-span-3">
            <label className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">厂商 & 平台</label>
            <select
              value={platform}
              onChange={(e) => {
                setPlatform(e.target.value);
                setVendor(
                  e.target.value.includes('cisco') ? 'Cisco'
                    : e.target.value.includes('h3c') ? 'H3C'
                      : e.target.value.includes('ruijie') ? 'Ruijie'
                        : 'Huawei'
                );
              }}
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            >
              <option value="huawei_vrp">Huawei VRP</option>
              <option value="h3c_comware">H3C Comware</option>
              <option value="h3c_comware_v3">H3C Comware V3</option>
              <option value="cisco_ios">Cisco IOS / IOS-XE</option>
              <option value="cisco_nxos">Cisco NX-OS</option>
              <option value="ruijie_os">Ruijie RGOS</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={loading || !intent.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading && <LoaderCircle className="h-4 w-4 animate-spin" />}
            {loading ? '生成中...' : '生成配置命令 (Generate)'}
          </button>
        </div>
      </form>

      {result && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-6 dark:border-slate-800 dark:bg-slate-900">
          {result.summary && (
            <p className="rounded-xl border border-indigo-100 bg-indigo-50/50 px-4 py-3 text-sm text-slate-700 dark:border-indigo-900/50 dark:bg-indigo-950/30 dark:text-slate-200">
              {result.summary}
            </p>
          )}

          {hasSafetyWarnings && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700 space-y-2 dark:border-rose-900/70 dark:bg-rose-950/40 dark:text-rose-300">
              <div className="flex items-center gap-1.5 text-sm font-bold">
                <AlertTriangle className="h-4 w-4 text-rose-500" /> 高危命令拦截告警（共 {result.safety_warnings.length} 条）
              </div>
              {result.safety_warnings.map((w: any, idx: number) => (
                <p key={idx} className="font-mono">• {w.reason} — <code>{w.command}</code></p>
              ))}
              <label className="mt-2 inline-flex cursor-pointer items-center gap-2 pt-1 font-sans text-xs font-semibold">
                <input
                  type="checkbox"
                  checked={riskAcknowledged}
                  onChange={(e) => setRiskAcknowledged(e.target.checked)}
                  className="h-4 w-4 rounded border-rose-400 text-rose-600 focus:ring-rose-500"
                />
                我已人工复核上述高危命令与回滚方案，确认提交草稿进入审批流程
              </label>
            </div>
          )}

          <div className="grid grid-cols-1 gap-5 font-mono text-xs md:grid-cols-3">
            <div className="space-y-2">
              <h4 className="font-sans text-sm font-bold text-slate-900 dark:text-white">配置变更命令</h4>
              <div className="min-h-[140px] whitespace-pre-wrap rounded-xl bg-slate-950 p-3.5 leading-relaxed text-emerald-400">
                {Array.isArray(result.commands) && result.commands.length ? result.commands.join('\n') : '# 无命令'}
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="font-sans text-sm font-bold text-slate-900 dark:text-white">验证命令 (Verification)</h4>
              <div className="min-h-[140px] whitespace-pre-wrap rounded-xl bg-slate-950 p-3.5 leading-relaxed text-sky-400">
                {Array.isArray(result.verification_commands) && result.verification_commands.length ? result.verification_commands.join('\n') : '# 无验证命令'}
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="font-sans text-sm font-bold text-slate-900 dark:text-white">回滚命令 (Rollback)</h4>
              <div className="min-h-[140px] whitespace-pre-wrap rounded-xl bg-slate-950 p-3.5 leading-relaxed text-amber-400">
                {Array.isArray(result.rollback_commands) && result.rollback_commands.length ? result.rollback_commands.join('\n') : '# 无回滚命令'}
              </div>
            </div>
          </div>

          {draftResult ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
              <span className="inline-flex items-center gap-2 font-mono font-semibold">
                <CheckCircle2 className="h-4 w-4" />
                变更工单草稿创建成功 · 工单号：{draftResult.order_number || draftResult.change_id}
              </span>
              <span className="font-bold">已持久化至变更工单库，等待人工审批</span>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
              <span className="text-xs text-slate-500 dark:text-slate-400">
                门禁提示：AI 生成结果禁止自动下发，提交后将写入变更工单表并等待双人审批。
              </span>
              <button
                type="button"
                onClick={() => void handleCreateDraft()}
                disabled={submittingDraft || (hasSafetyWarnings && !riskAcknowledged)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submittingDraft ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                {submittingDraft ? '提交中...' : '提交变更工单 (送审批)'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
