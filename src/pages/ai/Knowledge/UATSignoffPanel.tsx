import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  History,
  Loader2,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import {
  getKnowledgeUATCaseHistory,
  getKnowledgeUATCampaign,
  signKnowledgeUATCase,
  type KnowledgeUATCase,
  type KnowledgeUATCampaign,
  type KnowledgeUATDecision,
  type KnowledgeUATSignoffEvent,
  type KnowledgeUATSignoffStatus,
} from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';

const CAMPAIGN_ID = 'browser-uat-20260906';

const signoffLabels: Record<KnowledgeUATSignoffStatus, string> = {
  pending: '待签署',
  approved: 'PASS · 接受',
  partial: 'PARTIAL · 有条件接受',
  rejected: 'FAIL · 不通过',
};

const suiteLabels: Record<string, string> = {
  'UAT-01': 'UAT-01 · 四厂商 20 案例',
  'UAT-02': 'UAT-02 · 业务流程与边界',
  'UAT-03': 'UAT-03 · 安全负向矩阵',
};

const statusTone: Record<string, StatusTone> = {
  PASS: 'success',
  'PASS-FALLBACK': 'warning',
  PARTIAL: 'warning',
  FAIL: 'danger',
  approved: 'success',
  partial: 'warning',
  rejected: 'danger',
  pending: 'neutral',
};

const decisionOptions: Array<{ value: KnowledgeUATDecision; label: string }> = [
  { value: 'approved', label: 'PASS · 接受该案例终态' },
  { value: 'partial', label: 'PARTIAL · 保留覆盖缺口' },
  { value: 'rejected', label: 'FAIL · 不通过' },
];

const extraVendorOptions = ['跨厂商', '流程', '资产', '告警', '查询边界', '安全', '跨平台'];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'UAT 签署请求失败';
}

function safeTime(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function resultLabel(value: string): string {
  if (value === 'PENDING_HUMAN_REVIEW') return '待人工签署';
  if (value === 'NOT_READY') return '未就绪';
  return value;
}

function signoffTone(status: string): StatusTone {
  return statusTone[status] || statusTone.pending;
}

export const UATSignoffPanel: React.FC = () => {
  const { currentUser } = useCoreApp();
  const [suite, setSuite] = useState('UAT-01');
  const [vendor, setVendor] = useState('');
  const [status, setStatus] = useState<KnowledgeUATSignoffStatus | 'all'>('all');
  const [search, setSearch] = useState('');
  const [campaign, setCampaign] = useState<KnowledgeUATCampaign | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [decision, setDecision] = useState<KnowledgeUATDecision>('approved');
  const [comment, setComment] = useState('');
  const [evidenceRef, setEvidenceRef] = useState('');
  const [history, setHistory] = useState<KnowledgeUATSignoffEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await getKnowledgeUATCampaign({
        campaignId: CAMPAIGN_ID,
        suite,
        vendor,
        status,
        search,
      });
      setCampaign(result);
      setSelectedId((current) => result.items.some((item) => item.case_id === current) ? current : (result.items[0]?.case_id || ''));
    } catch (cause) {
      setCampaign(null);
      setSelectedId('');
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [search, status, suite, vendor]);

  useEffect(() => { void load(); }, [load]);

  const selected = useMemo<KnowledgeUATCase | null>(
    () => campaign?.items.find((item) => item.case_id === selectedId) || null,
    [campaign?.items, selectedId],
  );

  const vendorOptions = useMemo(() => {
    const values = new Set([...(campaign?.vendors || []), ...extraVendorOptions]);
    return Array.from(values).sort((left, right) => left.localeCompare(right, 'zh-CN'));
  }, [campaign?.vendors]);

  const loadHistory = useCallback(async (item: KnowledgeUATCase | null) => {
    if (!item || !campaign) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    try {
      setHistory(await getKnowledgeUATCaseHistory(campaign.campaign_id, item.case_id));
    } catch (cause) {
      setHistory([]);
      setError(errorMessage(cause));
    } finally {
      setHistoryLoading(false);
    }
  }, [campaign]);

  useEffect(() => {
    if (!selected) {
      setDecision('approved');
      setComment('');
      setEvidenceRef('');
      setHistory([]);
      return;
    }
    const initialDecision: KnowledgeUATDecision = selected.signoff_status !== 'pending'
      ? selected.signoff_status
      : (selected.observed_status === 'PARTIAL' || selected.observed_status === 'PASS-FALLBACK' ? 'partial' : 'approved');
    setDecision(initialDecision);
    setComment(selected.comment || '');
    setEvidenceRef(selected.signoff_evidence_ref || selected.evidence_ref);
    void loadHistory(selected);
  }, [loadHistory, selected]);

  const submit = async () => {
    if (!campaign || !selected || busy || !campaign.can_sign) return;
    if ((decision === 'partial' || decision === 'rejected') && !comment.trim()) {
      setError('PARTIAL 或 FAIL 签署必须填写备注，说明覆盖缺口或阻断原因。');
      return;
    }
    if (selected.signoff_status !== 'pending' && !window.confirm('该案例已经签署，再次保存会追加一条审计事件。是否继续？')) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await signKnowledgeUATCase(campaign.campaign_id, selected.case_id, {
        decision,
        comment: comment.trim(),
        evidence_ref: evidenceRef.trim(),
      });
      setNotice(`${selected.case_id} 已保存为「${signoffLabels[decision]}」，审核人和签署时间由服务端记录。`);
      await load();
      const refreshed = await getKnowledgeUATCaseHistory(campaign.campaign_id, selected.case_id);
      setHistory(refreshed);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const summary = campaign?.summary;
  const campaignSummary = campaign?.campaign_summary;

  return (
    <div className="mx-auto w-full space-y-4 text-fg">
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><ClipboardCheck className="h-5 w-5 text-accent" aria-hidden="true" />四厂商 UAT 签署</span>}
        description="在这里逐案例确认浏览器终态。观察事实来自脱敏 UAT 证据，签署结论由当前登录账号写入数据库并保留审计历史。"
        info="没有一键全通过：每个案例都必须单独查看来源、风险、外发和 CLI 状态后保存结论。"
        infoLabel="UAT 签署说明"
        actions={(
          <>
            <StatusBadge tone="success"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />当前用户：{campaign?.current_reviewer?.name || currentUser?.username || '—'}</StatusBadge>
            <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-muted disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />刷新</button>
          </>
        )}
      />

      {error && <div role="alert" className="flex items-center gap-2 rounded-xl border border-danger/30 bg-danger-subtle px-4 py-3 text-sm text-danger "><XCircle className="h-4 w-4" />{error}</div>}
      {notice && <div role="status" className="flex items-center gap-2 rounded-xl border border-success/30 bg-success-subtle px-4 py-3 text-sm text-success "><CheckCircle2 className="h-4 w-4" />{notice}</div>}

      <Panel aria-label="签署进度">
        <PanelHeader
          title="签署进度"
          description={<>当前视图：{suiteLabels[suite] || suite}；整项浏览器活动共 {campaignSummary?.total ?? '—'} 个案例。</>}
          actions={<StatusBadge dot tone={signoffTone(summary?.overall_status || 'pending')}>{resultLabel(summary?.overall_status || 'NOT_READY')} · 门禁 {summary?.release_gate || 'HOLD'}</StatusBadge>}
        />
        <div className="p-4">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ['案例', summary?.total ?? 0],
            ['已签署', summary?.signed ?? 0],
            ['待签署', summary?.pending ?? 0],
            ['PASS', summary?.approved ?? 0],
            ['PARTIAL/FAIL', (summary?.partial ?? 0) + (summary?.rejected ?? 0)],
          ].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-line p-3"><div className="text-xs text-fg-muted">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums text-fg">{String(value)}</div></div>)}
        </div>
        {campaign && !campaign.can_sign && <div className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-surface-muted px-3 py-2 text-[11px] text-fg-muted "><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />当前账号只有查看权限；需要 Release Manager 或 Administrator 权限才能签署。</div>}
        </div>
      </Panel>

      <Panel className="p-4" aria-label="UAT 案例筛选">
        <div className="grid gap-2 md:grid-cols-[1.15fr_1fr_1fr_1.4fr_auto]">
          <label className="text-[11px] text-fg-muted">案例集合<select value={suite} onChange={(event) => { setSuite(event.target.value); setSelectedId(''); }} className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-xs text-fg " aria-label="UAT 案例集合">{Object.entries(suiteLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="text-[11px] text-fg-muted">厂商/范围<select value={vendor} onChange={(event) => setVendor(event.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-xs text-fg " aria-label="UAT 厂商筛选"><option value="">全部</option>{vendorOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label className="text-[11px] text-fg-muted">签署状态<select value={status} onChange={(event) => setStatus(event.target.value as KnowledgeUATSignoffStatus | 'all')} className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-xs text-fg " aria-label="UAT 签署状态"><option value="all">全部状态</option><option value="pending">待签署</option><option value="approved">PASS</option><option value="partial">PARTIAL</option><option value="rejected">FAIL</option></select></label>
          <label className="text-[11px] text-fg-muted">搜索<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="案例编号、型号、功能或来源" className="mt-1 w-full rounded-lg border border-line px-2.5 py-2 text-xs text-fg " aria-label="搜索 UAT 案例" /></label>
          <button type="button" onClick={() => void load()} disabled={loading} className="self-end rounded-lg border border-line px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-muted disabled:opacity-50 ">应用筛选</button>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <Panel className="p-4" aria-label="案例列表">
          <div className="mb-3 flex items-center justify-between gap-2"><h2 className="text-base font-semibold text-fg">案例列表</h2><span className="text-xs text-fg-muted">{campaign?.total ?? 0} 条</span></div>
          {loading && !campaign ? <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-fg-muted"><Loader2 className="h-4 w-4 animate-spin" />正在加载 UAT 案例…</div> : campaign?.items.length ? <div className="max-h-[680px] space-y-2 overflow-y-auto pr-1">{campaign.items.map((item) => <button type="button" key={item.case_id} onClick={() => setSelectedId(item.case_id)} className={`w-full rounded-lg border p-3 text-left transition ${selectedId === item.case_id ? 'border-accent/30 bg-accent-subtle' : 'border-line hover:border-accent/30 hover:bg-surface-muted'}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-fg ">{item.case_id}</span><StatusBadge dot tone={signoffTone(item.signoff_status)}>{signoffLabels[item.signoff_status]}</StatusBadge></div><div className="mt-2 line-clamp-2 text-xs font-semibold text-fg ">{item.scope_summary}</div><div className="mt-2 flex flex-wrap gap-1.5 text-xs text-fg-muted"><span>{item.vendor}</span><span>观察：{item.observed_status}</span><span>审计 {item.history_count}</span></div></button>)}</div> : <EmptyState icon={ClipboardCheck} title="当前筛选没有案例" description="调整案例集合、厂商或签署状态后再试。" />}
        </Panel>

        <Panel className="p-5" aria-label="案例详情">
          {selected ? <>
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><div className="mb-1 text-xs font-bold uppercase tracking-[0.16em] text-accent">{selected.suite}</div><h2 className="text-base font-bold text-fg ">{selected.case_id}</h2><p className="mt-1 text-xs text-fg-muted ">{selected.scope_summary}</p></div><StatusBadge dot tone={signoffTone(selected.signoff_status)}>{signoffLabels[selected.signoff_status]}</StatusBadge></div>
            <div className="rounded-lg border border-line bg-surface-muted p-3"><div className="mb-2 flex items-center gap-2 text-xs font-semibold text-fg"><ShieldCheck className="h-4 w-4 text-accent" aria-hidden="true" />机器观察事实（不可由签署表单修改）</div><dl className="grid gap-x-4 gap-y-2 text-[11px] sm:grid-cols-2"><div><dt className="text-fg-muted">观察终态</dt><dd className="mt-0.5"><StatusBadge tone={signoffTone(selected.observed_status)}>{selected.observed_status}</StatusBadge></dd></div><div><dt className="text-fg-muted">风险</dt><dd className="mt-0.5 font-medium text-fg ">{selected.risk_level}</dd></div><div><dt className="text-fg-muted">是否澄清</dt><dd className="mt-0.5 font-medium text-fg ">{selected.clarification_required ? '是' : '否'}</dd></div><div><dt className="text-fg-muted">是否外发</dt><dd className="mt-0.5 font-medium text-fg ">{selected.external_egress ? '是（经安全网关）' : '否'}</dd></div><div><dt className="text-fg-muted">是否执行 CLI</dt><dd className="mt-0.5 font-medium text-fg ">{selected.cli_executed ? '是' : '否'}</dd></div><div className="sm:col-span-2"><dt className="text-fg-muted">来源/命中文档</dt><dd className="mt-0.5 text-fg ">{selected.source_summary}</dd></div>{selected.observation_note && <div className="sm:col-span-2"><dt className="text-fg-muted">观察说明</dt><dd className="mt-0.5 text-fg ">{selected.observation_note}</dd></div>}<div className="sm:col-span-2"><dt className="text-fg-muted">证据记录</dt><dd className="mt-0.5 break-all font-mono text-xs text-fg-muted ">{selected.evidence_ref}</dd></div></dl></div>

            <div className="mt-4 rounded-lg border border-line p-3"><div className="mb-3 flex items-center justify-between gap-2"><h3 className="text-xs font-bold text-fg ">人工签署</h3>{selected.signed_at && <span className="text-xs text-fg-muted">{selected.reviewer_name || selected.reviewer_id} · {safeTime(selected.signed_at)}</span>}</div>{campaign?.can_sign ? <div className="space-y-3"><label className="block text-[11px] text-fg-muted">签署结论<select value={decision} onChange={(event) => setDecision(event.target.value as KnowledgeUATDecision)} className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-xs text-fg " aria-label="签署结论">{decisionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label className="block text-[11px] text-fg-muted">审核备注{(decision === 'partial' || decision === 'rejected') && <span className="ml-1 text-danger">必填</span>}<textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} maxLength={4000} placeholder="说明本案例是否满足发布验收，或记录阻断原因" className="mt-1 w-full resize-y rounded-lg border border-line px-2.5 py-2 text-xs text-fg " aria-label="UAT 审核备注" /></label><label className="block text-[11px] text-fg-muted">证据引用<input value={evidenceRef} onChange={(event) => setEvidenceRef(event.target.value)} maxLength={1024} className="mt-1 w-full rounded-lg border border-line px-2.5 py-2 text-xs text-fg " aria-label="UAT 证据引用" /></label><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-fg-muted">审核人：{campaign.current_reviewer?.name || '当前登录账号'}；签署时间由服务端生成。</span><button type="button" onClick={() => void submit()} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{selected.signoff_status === 'pending' ? '保存签署' : '更新签署'}</button></div></div> : <div className="text-[11px] text-fg-muted">当前账号没有 `knowledge_uat.sign` 权限，只能查看签署状态。</div>}</div>

            <div className="mt-4 rounded-lg border border-line p-3"><div className="mb-2 flex items-center gap-2 text-xs font-bold text-fg "><History className="h-3.5 w-3.5 text-accent" />签署审计历史</div>{historyLoading ? <div className="text-[11px] text-fg-muted">正在加载历史…</div> : history.length ? <div className="max-h-40 space-y-2 overflow-y-auto">{history.map((event) => <div key={event.id} className="rounded-lg bg-surface-muted px-2.5 py-2 text-xs "><div className="flex flex-wrap justify-between gap-2"><span className="font-semibold text-fg ">{event.reviewer_name || event.reviewer_id} · {signoffLabels[event.new_status]}</span><span className="text-fg-subtle">{safeTime(event.created_at)}</span></div>{event.comment && <p className="mt-1 text-fg-muted ">{event.comment}</p>}</div>)}</div> : <div className="text-[11px] text-fg-muted">尚无签署事件。</div>}</div>
          </> : <EmptyState className="min-h-[420px] justify-center" icon={ClipboardCheck} title="选择一个案例" description="选择一个案例查看观察事实并签署。" />}
        </Panel>
      </div>

      <div className="flex items-start gap-2 rounded-xl border border-line bg-surface-muted px-3 py-2 text-[11px] leading-5 text-fg-muted "><Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />签署只记录验收结论，不会重新执行浏览器案例、访问设备、执行 CLI 或调用 Provider。若要修正结论，重新保存会追加审计事件，不会删除历史记录。</div>
    </div>
  );
};

export default UATSignoffPanel;
