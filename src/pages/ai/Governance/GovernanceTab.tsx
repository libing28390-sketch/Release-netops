import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileCode2, Send, Server, ShieldCheck, Sparkles } from 'lucide-react';
import { generateAIConfig, createChangeDraft } from '../../../api/ai';
import { apiRequest } from '../../../api/http';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { EmptyState } from '../../../components/ui/EmptyState';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';

const fieldLabelClass = 'mb-1.5 flex items-center gap-1 text-[13px] font-medium text-fg';
const fieldInputClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20';

const PLATFORM_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'huawei_vrp', label: 'Huawei VRP' },
  { value: 'h3c_comware', label: 'H3C Comware' },
  { value: 'h3c_comware_v3', label: 'H3C Comware V3' },
  { value: 'cisco_ios', label: 'Cisco IOS / IOS-XE' },
  { value: 'cisco_nxos', label: 'Cisco NX-OS' },
  { value: 'ruijie_os', label: 'Ruijie RGOS' },
];

const listOf = (value: unknown): string[] => (Array.isArray(value) ? value.map((item) => String(item)) : []);

const CommandBlock: React.FC<{ title: string; commands: string[]; empty: string; tone: string; testId: string }> = ({ title, commands, empty, tone, testId }) => (
  <Panel as="div" className="flex min-h-[180px] flex-col">
    <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
      <h4 className="text-[13px] font-semibold text-fg">{title}</h4>
      <StatusBadge tone={commands.length ? 'neutral' : 'warning'}>{commands.length} 条</StatusBadge>
    </div>
    <pre
      data-testid={testId}
      className={`m-0 flex-1 overflow-x-auto whitespace-pre-wrap break-words rounded-b-xl bg-slate-950 p-3 font-mono text-xs leading-relaxed select-text ${tone}`}
    >
      {commands.length ? commands.join('\n') : empty}
    </pre>
  </Panel>
);

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
    if (!result.plan_token) {
      showToast('该方案没有可提交的命令，请重新生成配置', 'error');
      return;
    }
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
        // Server-issued binding to the generated plan; the draft is rejected
        // if the commands were changed or the plan is older than 30 minutes.
        plan_token: String(result.plan_token || ''),
        risk_acknowledged: riskAcknowledged,
      });
      setDraftResult(res);
      showToast(`变更工单草稿已落库 (${res.order_number || res.change_id})`, 'success');
    } catch (err: any) {
      showToast(err?.message || '提交草稿失败', 'error');
    } finally {
      setSubmittingDraft(false);
    }
  };

  const commands = listOf(result?.commands);
  const verificationCommands = listOf(result?.verification_commands);
  const rollbackCommands = listOf(result?.rollback_commands);
  const warnings: any[] = Array.isArray(result?.safety_warnings) ? result.safety_warnings : [];
  const selectedDevice = devices.find((item) => item.id === targetDeviceId);
  const platformLabel = PLATFORM_OPTIONS.find((item) => item.value === platform)?.label || platform;
  const draftNumber = draftResult ? String(draftResult.order_number || draftResult.change_id || '') : '';

  return (
    <div className="w-full space-y-5 pb-8">
      <PageHeader
        title="AI 变更治理"
        description="AI 只生成配置、验证和回滚命令，不连接设备执行；提交后成为变更工单草稿，进入人工审批。"
        info="生成 ≠ 执行：方案由服务端签发 plan_token，命令被修改或超过 30 分钟后提交会被拒绝；含高危命令时必须先人工确认风险。"
        infoLabel="变更治理说明"
        actions={<StatusBadge tone="accent"><ShieldCheck size={12} aria-hidden="true" />Generate ≠ Execute</StatusBadge>}
      />

      <SummaryBar
        label="变更治理概况"
        items={[
          { key: 'devices', value: devices.length || '—', label: devices.length ? '台可选设备' : '设备清单不可用，可手动输入' },
          { key: 'platform', value: platformLabel, label: '目标平台' },
          {
            key: 'plan',
            value: result ? commands.length : '—',
            label: result ? '条变更命令' : '尚未生成方案',
            tone: result ? (warnings.length ? ('danger' as const) : ('success' as const)) : undefined,
          },
          ...(result ? [{ key: 'warnings', value: warnings.length, label: '条高危告警', tone: warnings.length ? ('danger' as const) : ('success' as const) }] : []),
          ...(draftResult ? [{ key: 'draft', value: draftNumber, label: '工单草稿已创建', tone: 'success' as const }] : []),
        ]}
      />

      <Panel>
        <PanelHeader title="生成变更方案" description="描述要做的变更，选择目标设备与平台。" />
        <form onSubmit={handleGenerate} className="space-y-4 p-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
            <div className="md:col-span-6">
              <label htmlFor="governance-intent" className={fieldLabelClass}>配置变更意图描述</label>
              <input
                id="governance-intent"
                type="text"
                required
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                className={fieldInputClass}
              />
            </div>
            <div className="md:col-span-3">
              <label htmlFor="governance-device" className={fieldLabelClass}>
                <Server size={14} className="text-fg-muted" aria-hidden="true" /> 目标设备
              </label>
              {devices.length > 0 ? (
                <select
                  id="governance-device"
                  value={targetDeviceId}
                  onChange={(e) => handleSelectDevice(e.target.value)}
                  className={fieldInputClass}
                >
                  {devices.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.hostname}{d.ip_address ? ` (${d.ip_address})` : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id="governance-device"
                  type="text"
                  value={targetDeviceId}
                  onChange={(e) => setTargetDeviceId(e.target.value)}
                  placeholder="输入设备 ID 或主机名"
                  className={fieldInputClass}
                />
              )}
            </div>
            <div className="md:col-span-3">
              <label htmlFor="governance-platform" className={fieldLabelClass}>厂商 & 平台</label>
              <select
                id="governance-platform"
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
                className={fieldInputClass}
              >
                {PLATFORM_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-fg-muted">
              {selectedDevice ? `目标：${selectedDevice.hostname}${selectedDevice.vendor ? ` · ${selectedDevice.vendor}` : ''}` : `厂商：${vendor}`}
            </span>
            <ActionButton
              type="submit"
              variant="primary"
              size="md"
              icon={Sparkles}
              iconClassName={loading ? 'animate-spin motion-reduce:animate-none' : undefined}
              disabled={loading || !intent.trim()}
            >
              {loading ? '生成中...' : '生成配置命令 (Generate)'}
            </ActionButton>
          </div>
        </form>
      </Panel>

      {!result && !loading && (
        <EmptyState
          icon={FileCode2}
          title="还没有变更方案"
          description="填写变更意图并点击「生成配置命令」，这里会显示配置、验证和回滚命令。"
        />
      )}

      {result && (
        <Panel data-testid="governance-plan">
          <PanelHeader
            title="变更方案"
            description="请逐条复核命令，确认无误后提交为变更工单草稿。"
            actions={warnings.length
              ? <StatusBadge tone="danger" dot>{warnings.length} 条高危</StatusBadge>
              : <StatusBadge tone="success" dot>未发现高危命令</StatusBadge>}
          />
          <div className="space-y-4 p-4">
            {result.summary && (
              <p className="rounded-lg border border-line bg-surface-muted px-4 py-3 text-sm leading-6 text-fg">
                {result.summary}
              </p>
            )}

            {hasSafetyWarnings && (
              <div role="alert" className="space-y-2 rounded-lg border border-danger/40 bg-danger-subtle p-4 text-xs text-danger">
                <div className="flex items-center gap-1.5 text-sm font-semibold">
                  <AlertTriangle size={16} aria-hidden="true" /> 高危命令拦截告警（共 {result.safety_warnings.length} 条）
                </div>
                <ul className="space-y-1">
                  {result.safety_warnings.map((w: any, idx: number) => (
                    <li key={idx} className="font-mono">• {w.reason} — <code>{w.command}</code></li>
                  ))}
                </ul>
                <label className="inline-flex cursor-pointer items-center gap-2 pt-1 font-sans text-xs font-semibold">
                  <input
                    type="checkbox"
                    checked={riskAcknowledged}
                    onChange={(e) => setRiskAcknowledged(e.target.checked)}
                    className="h-4 w-4 rounded border-line-strong accent-[var(--ui-danger)]"
                  />
                  我已人工复核上述高危命令与回滚方案，确认提交草稿进入审批流程
                </label>
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <CommandBlock title="配置变更命令" commands={commands} empty="# 无命令" tone="text-emerald-400" testId="governance-commands" />
              <CommandBlock title="验证命令 (Verification)" commands={verificationCommands} empty="# 无验证命令" tone="text-sky-400" testId="governance-verification" />
              <CommandBlock title="回滚命令 (Rollback)" commands={rollbackCommands} empty="# 无回滚命令" tone="text-amber-400" testId="governance-rollback" />
            </div>

            {draftResult ? (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-success/40 bg-success-subtle p-4 text-xs text-success">
                <span className="inline-flex items-center gap-2 font-mono font-semibold">
                  <CheckCircle2 size={16} aria-hidden="true" />
                  变更工单草稿创建成功 · 工单号：{draftResult.order_number || draftResult.change_id}
                </span>
                <span className="font-semibold">已持久化至变更工单库，等待人工审批</span>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
                <span className="text-xs text-fg-muted">
                  门禁提示：AI 生成结果禁止自动下发，提交后将写入变更工单表并等待双人审批。
                </span>
                <ActionButton
                  type="button"
                  variant="success"
                  size="md"
                  icon={Send}
                  iconClassName={submittingDraft ? 'animate-pulse motion-reduce:animate-none' : undefined}
                  onClick={() => void handleCreateDraft()}
                  disabled={submittingDraft || (hasSafetyWarnings && !riskAcknowledged)}
                >
                  {submittingDraft ? '提交中...' : '提交变更工单 (送审批)'}
                </ActionButton>
              </div>
            )}
          </div>
        </Panel>
      )}
    </div>
  );
};
