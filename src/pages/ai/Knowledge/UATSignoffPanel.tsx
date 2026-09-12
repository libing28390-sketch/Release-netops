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

const statusTone: Record<string, string> = {
  PASS: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300',
  'PASS-FALLBACK': 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300',
  PARTIAL: 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300',
  approved: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300',
  partial: 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300',
  rejected: 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300',
  pending: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
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

function signoffTone(status: string): string {
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
    <div className="mx-auto w-full space-y-5 text-slate-900 dark:text-slate-100">
      <section className="rounded-3xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 p-6 shadow-sm dark:border-indigo-900/60 dark:from-indigo-950/40 dark:via-slate-900 dark:to-violet-950/30">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600"><ClipboardCheck className="h-4 w-4" />Browser UAT · GATE-070</div>
            <h1 className="nx-page-title text-slate-900 dark:text-white">四厂商 UAT 签署</h1>
            <p className="nx-page-description mt-2 max-w-4xl text-slate-600 dark:text-slate-300">在这里逐案例确认浏览器终态。观察事实来自脱敏 UAT 证据，签署结论由当前登录账号写入数据库并保留审计历史。</p>
            <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-500 dark:text-slate-400">没有一键全通过：每个案例都必须单独查看来源、风险、外发和 CLI 状态后保存结论。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"><ShieldCheck className="h-4 w-4" />当前用户：{campaign?.current_reviewer?.name || currentUser?.username || '—'}</span>
            <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/40"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</button>
          </div>
        </div>
      </section>

      {error && <div role="alert" className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300"><XCircle className="h-4 w-4" />{error}</div>}
      {notice && <div role="status" className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"><CheckCircle2 className="h-4 w-4" />{notice}</div>}

      <section className="rounded-2xl border border-amber-200 bg-amber-50/50 p-4 dark:border-amber-900/60 dark:bg-amber-950/10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">签署进度</h2>
            <p className="mt-1 text-[11px] text-slate-600 dark:text-slate-300">当前视图：{suiteLabels[suite] || suite}；整项浏览器活动共 {campaignSummary?.total ?? '—'} 个案例。</p>
          </div>
          <div className={`rounded-full px-3 py-1.5 text-xs font-bold ${signoffTone(summary?.overall_status || 'pending')}`}>{resultLabel(summary?.overall_status || 'NOT_READY')} · 门禁 {summary?.release_gate || 'HOLD'}</div>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ['案例', summary?.total ?? 0],
            ['已签署', summary?.signed ?? 0],
            ['待签署', summary?.pending ?? 0],
            ['PASS', summary?.approved ?? 0],
            ['PARTIAL/FAIL', (summary?.partial ?? 0) + (summary?.rejected ?? 0)],
          ].map(([label, value]) => <div key={String(label)} className="rounded-xl bg-white/80 p-3 dark:bg-slate-900/70"><div className="text-[10px] text-slate-500 dark:text-slate-400">{label}</div><div className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{String(value)}</div></div>)}
        </div>
        {campaign && !campaign.can_sign && <div className="mt-3 flex items-start gap-2 rounded-xl border border-slate-200 bg-white/80 px-3 py-2 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />当前账号只有查看权限；需要 Release Manager 或 Administrator 权限才能签署。</div>}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="grid gap-2 md:grid-cols-[1.15fr_1fr_1fr_1.4fr_auto]">
          <label className="text-[11px] text-slate-500">案例集合<select value={suite} onChange={(event) => { setSuite(event.target.value); setSelectedId(''); }} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="UAT 案例集合">{Object.entries(suiteLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="text-[11px] text-slate-500">厂商/范围<select value={vendor} onChange={(event) => setVendor(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="UAT 厂商筛选"><option value="">全部</option>{vendorOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label className="text-[11px] text-slate-500">签署状态<select value={status} onChange={(event) => setStatus(event.target.value as KnowledgeUATSignoffStatus | 'all')} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="UAT 签署状态"><option value="all">全部状态</option><option value="pending">待签署</option><option value="approved">PASS</option><option value="partial">PARTIAL</option><option value="rejected">FAIL</option></select></label>
          <label className="text-[11px] text-slate-500">搜索<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="案例编号、型号、功能或来源" className="mt-1 w-full rounded-lg border border-slate-200 px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="搜索 UAT 案例" /></label>
          <button type="button" onClick={() => void load()} disabled={loading} className="self-end rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">应用筛选</button>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="mb-3 flex items-center justify-between gap-2"><h2 className="text-sm font-bold text-slate-900 dark:text-white">案例列表</h2><span className="text-[11px] text-slate-500">{campaign?.total ?? 0} 条</span></div>
          {loading && !campaign ? <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />正在加载 UAT 案例…</div> : campaign?.items.length ? <div className="max-h-[680px] space-y-2 overflow-y-auto pr-1">{campaign.items.map((item) => <button type="button" key={item.case_id} onClick={() => setSelectedId(item.case_id)} className={`w-full rounded-xl border p-3 text-left transition ${selectedId === item.case_id ? 'border-indigo-300 bg-indigo-50 dark:border-indigo-800 dark:bg-indigo-950/40' : 'border-slate-200 hover:border-indigo-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-indigo-800 dark:hover:bg-slate-800/70'}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">{item.case_id}</span><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${signoffTone(item.signoff_status)}`}>{signoffLabels[item.signoff_status]}</span></div><div className="mt-2 line-clamp-2 text-xs font-semibold text-slate-700 dark:text-slate-200">{item.scope_summary}</div><div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-500"><span>{item.vendor}</span><span>观察：{item.observed_status}</span><span>审计 {item.history_count}</span></div></button>)}</div> : <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500 dark:bg-slate-800/70">当前筛选没有案例。</div>}
        </article>

        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {selected ? <>
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><div className="mb-1 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-600">{selected.suite}</div><h2 className="text-base font-bold text-slate-900 dark:text-white">{selected.case_id}</h2><p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{selected.scope_summary}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${signoffTone(selected.signoff_status)}`}>{signoffLabels[selected.signoff_status]}</span></div>
            <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/20"><div className="mb-2 flex items-center gap-2 text-xs font-bold text-indigo-800 dark:text-indigo-200"><ShieldCheck className="h-4 w-4" />机器观察事实（不可由签署表单修改）</div><dl className="grid gap-x-4 gap-y-2 text-[11px] sm:grid-cols-2"><div><dt className="text-slate-500">观察终态</dt><dd className={`mt-0.5 inline-flex rounded-full px-2 py-0.5 font-semibold ${signoffTone(selected.observed_status)}`}>{selected.observed_status}</dd></div><div><dt className="text-slate-500">风险</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{selected.risk_level}</dd></div><div><dt className="text-slate-500">是否澄清</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{selected.clarification_required ? '是' : '否'}</dd></div><div><dt className="text-slate-500">是否外发</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{selected.external_egress ? '是（经安全网关）' : '否'}</dd></div><div><dt className="text-slate-500">是否执行 CLI</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{selected.cli_executed ? '是' : '否'}</dd></div><div className="sm:col-span-2"><dt className="text-slate-500">来源/命中文档</dt><dd className="mt-0.5 text-slate-800 dark:text-slate-200">{selected.source_summary}</dd></div>{selected.observation_note && <div className="sm:col-span-2"><dt className="text-slate-500">观察说明</dt><dd className="mt-0.5 text-slate-800 dark:text-slate-200">{selected.observation_note}</dd></div>}<div className="sm:col-span-2"><dt className="text-slate-500">证据记录</dt><dd className="mt-0.5 break-all font-mono text-[10px] text-slate-600 dark:text-slate-400">{selected.evidence_ref}</dd></div></dl></div>

            <div className="mt-4 rounded-xl border border-slate-200 p-3 dark:border-slate-800"><div className="mb-3 flex items-center justify-between gap-2"><h3 className="text-xs font-bold text-slate-700 dark:text-slate-200">人工签署</h3>{selected.signed_at && <span className="text-[10px] text-slate-500">{selected.reviewer_name || selected.reviewer_id} · {safeTime(selected.signed_at)}</span>}</div>{campaign?.can_sign ? <div className="space-y-3"><label className="block text-[11px] text-slate-500">签署结论<select value={decision} onChange={(event) => setDecision(event.target.value as KnowledgeUATDecision)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="签署结论">{decisionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label className="block text-[11px] text-slate-500">审核备注{(decision === 'partial' || decision === 'rejected') && <span className="ml-1 text-rose-600">必填</span>}<textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} maxLength={4000} placeholder="说明本案例是否满足发布验收，或记录阻断原因" className="mt-1 w-full resize-y rounded-lg border border-slate-200 px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="UAT 审核备注" /></label><label className="block text-[11px] text-slate-500">证据引用<input value={evidenceRef} onChange={(event) => setEvidenceRef(event.target.value)} maxLength={1024} className="mt-1 w-full rounded-lg border border-slate-200 px-2.5 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="UAT 证据引用" /></label><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[10px] text-slate-500">审核人：{campaign.current_reviewer?.name || '当前登录账号'}；签署时间由服务端生成。</span><button type="button" onClick={() => void submit()} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{selected.signoff_status === 'pending' ? '保存签署' : '更新签署'}</button></div></div> : <div className="text-[11px] text-slate-500">当前账号没有 `knowledge_uat.sign` 权限，只能查看签署状态。</div>}</div>

            <div className="mt-4 rounded-xl border border-slate-100 p-3 dark:border-slate-800"><div className="mb-2 flex items-center gap-2 text-xs font-bold text-slate-700 dark:text-slate-200"><History className="h-3.5 w-3.5 text-indigo-500" />签署审计历史</div>{historyLoading ? <div className="text-[11px] text-slate-500">正在加载历史…</div> : history.length ? <div className="max-h-40 space-y-2 overflow-y-auto">{history.map((event) => <div key={event.id} className="rounded-lg bg-slate-50 px-2.5 py-2 text-[10px] dark:bg-slate-800/70"><div className="flex flex-wrap justify-between gap-2"><span className="font-semibold text-slate-700 dark:text-slate-200">{event.reviewer_name || event.reviewer_id} · {signoffLabels[event.new_status]}</span><span className="text-slate-400">{safeTime(event.created_at)}</span></div>{event.comment && <p className="mt-1 text-slate-500 dark:text-slate-400">{event.comment}</p>}</div>)}</div> : <div className="text-[11px] text-slate-500">尚无签署事件。</div>}</div>
          </> : <div className="flex min-h-[420px] items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-500 dark:bg-slate-800/70">选择一个案例查看观察事实并签署。</div>}
        </article>
      </section>

      <div className="flex items-start gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"><Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-500" />签署只记录验收结论，不会重新执行浏览器案例、访问设备、执行 CLI 或调用 Provider。若要修正结论，重新保存会追加审计事件，不会删除历史记录。</div>
    </div>
  );
};

export default UATSignoffPanel;
