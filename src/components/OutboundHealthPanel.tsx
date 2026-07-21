import { useEffect, useMemo, useState } from 'react';
import {
  Activity, CheckCircle2, Clock3, Globe2, Loader2, Pencil, Plus, RefreshCw,
  Save, ShieldAlert, Trash2, X, XCircle,
} from 'lucide-react';
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type {
  OutboundHealthResponse,
  OutboundProbeType,
  OutboundStatus,
  OutboundTarget,
} from '../types/outbound';

interface OutboundHealthPanelProps {
  language: 'zh' | 'en';
  data: OutboundHealthResponse | null;
  loading: boolean;
  modalOpen: boolean;
  setModalOpen: (value: boolean) => void;
  standalone?: boolean;
  onRefresh: () => Promise<unknown>;
  onTrigger: () => Promise<unknown>;
  onSaveTarget: (target: Partial<OutboundTarget>) => Promise<unknown>;
  onDeleteTarget: (targetId: string) => Promise<void>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  selectedTargetId?: string | null;
  onSelectTarget?: (targetId: string) => void;
  showTargetSelector?: boolean;
  addTargetRequest?: number;
}

type TargetForm = {
  id?: string;
  target_name: string;
  host: string;
  port: number;
  probe_type: OutboundProbeType;
  group_name: string;
  url: string;
  expected_status_code: number;
  expected_keyword: string;
  timeout_ms: number;
  enabled: boolean;
};

const EMPTY_FORM: TargetForm = {
  target_name: '', host: '', port: 443, probe_type: 'TCP_CONNECT', group_name: 'business',
  url: '', expected_status_code: 200, expected_keyword: '', timeout_ms: 2000, enabled: true,
};

const statusTone = (status?: OutboundStatus | null) => {
  if (status === 'healthy') return { text: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', dot: 'bg-emerald-500' };
  if (status === 'degraded') return { text: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200', dot: 'bg-amber-500' };
  if (status === 'unavailable') return { text: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200', dot: 'bg-red-500' };
  return { text: 'text-slate-500', bg: 'bg-slate-50', border: 'border-slate-200', dot: 'bg-slate-400' };
};

const statusLabel = (status: OutboundStatus | undefined, zh: boolean) => ({
  healthy: zh ? '正常' : 'Healthy',
  degraded: zh ? '降级' : 'Degraded',
  unavailable: zh ? '出口中断' : 'Unavailable',
  unknown: zh ? '未知' : 'Unknown',
}[status || 'unknown']);

const groupLabel = (group: string, zh: boolean) => ({
  domestic: zh ? '国内' : 'Domestic',
  international: zh ? '国际' : 'International',
  dns: zh ? 'DNS 服务' : 'DNS',
  web: zh ? 'Web 服务' : 'Web',
  business: zh ? '业务站点' : 'Business',
}[group] || group);

const formatTime = (value: string | undefined, zh: boolean) => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(zh ? 'zh-CN' : 'en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
};

const OutboundHealthPanel: React.FC<OutboundHealthPanelProps> = ({
  language, data, loading, modalOpen, setModalOpen, onRefresh, onTrigger,
  onSaveTarget, onDeleteTarget, showToast, standalone = false,
  selectedTargetId = null, onSelectTarget,
  showTargetSelector = true, addTargetRequest = 0,
}) => {
  const zh = language === 'zh';
  const current = data?.current;
  const tone = statusTone(current?.status);
  const [form, setForm] = useState<TargetForm>(EMPTY_FORM);
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const chartData = useMemo(() => (data?.history || []).map((point) => ({
    time: formatTime(point.finished_at, zh),
    latency: point.average_latency_ms == null ? null : Number(point.average_latency_ms),
    availability: Number(point.availability_percent || 0),
    status: point.status,
  })), [data?.history, zh]);
  useEffect(() => {
    if (!addTargetRequest) return;
    setForm(EMPTY_FORM);
    setFormOpen(true);
    window.setTimeout(() => {
      const main = document.querySelector('main');
      if (main) main.scrollTo({ top: main.scrollHeight, behavior: 'smooth' });
    }, 0);
  }, [addTargetRequest]);

  const openNew = () => {
    setForm(EMPTY_FORM);
    setFormOpen(true);
  };
  const openEdit = (target: OutboundTarget) => {
    setForm({
      id: target.id,
      target_name: target.target_name,
      host: target.host,
      port: target.port,
      probe_type: (target.probe_type || 'TCP_CONNECT') as OutboundProbeType,
      group_name: target.group_name || 'business',
      url: target.url || '',
      expected_status_code: target.expected_status_code || 200,
      expected_keyword: target.expected_keyword || '',
      timeout_ms: target.timeout_ms || 2000,
      enabled: Boolean(target.enabled),
    });
    setFormOpen(true);
  };
  const save = async () => {
    setSaving(true);
    try {
      await onSaveTarget(form);
      setFormOpen(false);
      showToast(zh ? '探测目标已保存' : 'Probe target saved', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '保存失败' : 'Save failed'), 'error');
    } finally {
      setSaving(false);
    }
  };
  const trigger = async () => {
    try {
      await onTrigger();
      showToast(zh ? '已完成一次出口检测' : 'Outbound probe completed', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '检测失败' : 'Probe failed'), 'error');
    }
  };

  return (
    <>
      {!standalone && <button
        type="button"
        onClick={() => setModalOpen(true)}
        className={`ops-surface flex min-h-[126px] w-full items-center gap-4 rounded-2xl border p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-lg ${tone.border} ${tone.bg}`}
      >
        <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${tone.bg} ${tone.text}`}>
          {current?.status === 'unavailable' ? <XCircle size={25} /> : current?.status === 'degraded' ? <ShieldAlert size={25} /> : <Globe2 size={25} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--muted-text)]">
            {zh ? '互联网出口' : 'Internet Outbound'}
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
          </span>
          <span className={`mt-2 block text-2xl font-extrabold ${tone.text}`}>{statusLabel(current?.status, zh)}</span>
          <span className="mt-1 block truncate text-[11px] text-[var(--muted-text)]">
            {current?.availability_percent != null ? `${Math.round(current.availability_percent)}%` : '--'} · {current?.public_ip || '--'} · {formatTime(current?.checked_at, zh)}
          </span>
        </span>
        <Activity size={17} className="shrink-0 text-[var(--muted-text)]" />
      </button>}

      {(standalone || modalOpen) && (
        <div className={standalone ? 'w-full' : 'fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm'} role={standalone ? undefined : 'dialog'} aria-modal={standalone ? undefined : true}>
          <div className={standalone ? 'w-full' : 'max-h-[92vh] w-full max-w-6xl overflow-auto rounded-3xl border border-[var(--card-border)] bg-[var(--card-bg)] p-5 shadow-2xl'}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-sky-600">{zh ? '平台服务器出口' : 'Platform Server Egress'}</p>
                <h2 className="mt-1 text-xl font-extrabold text-[var(--app-text)]">{zh ? '互联网出口健康' : 'Internet Outbound Health'}</h2>
                <p className="mt-1 text-xs text-[var(--muted-text)]">{current?.status_reason || (zh ? '等待首个有效样本' : 'Waiting for the first valid sample')}</p>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={openNew} className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-300 px-3 py-2 text-xs font-bold text-emerald-700 hover:bg-emerald-50">
                  <Plus size={13} />{zh ? '新增指标' : 'Add target'}
                </button>
                <button type="button" onClick={() => onRefresh()} className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--card-border)] px-3 py-2 text-xs font-semibold text-[var(--muted-text)] hover:border-sky-300 hover:text-sky-700">
                  <RefreshCw size={13} />{zh ? '刷新' : 'Refresh'}
                </button>
                {!standalone && <button type="button" onClick={() => setModalOpen(false)} className="rounded-xl p-2 text-[var(--muted-text)] hover:bg-black/5" aria-label={zh ? '关闭' : 'Close'}><X size={18} /></button>}
              </div>
            </div>

            <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
              {[
                [zh ? '状态' : 'Status', statusLabel(current?.status, zh)],
                [zh ? '可用率' : 'Availability', current ? `${Math.round(current.availability_percent)}%` : '--'],
                [zh ? '平均时延' : 'Avg latency', current?.average_latency_ms == null ? '--' : `${Math.round(current.average_latency_ms)} ms`],
                [zh ? '公网 IP' : 'Public IP', current?.public_ip || '--'],
                [zh ? '连续失败' : 'Failure streak', String(current?.consecutive_failure_count || 0)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl border border-[var(--card-border)] bg-black/[0.02] px-3 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{label}</p>
                  <p className="mt-1 truncate text-sm font-extrabold text-[var(--app-text)]">{value}</p>
                </div>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-5">
              {Object.entries(current?.groups || {}).map(([group, item]) => {
                const groupTone = statusTone(item.status);
                return <div key={group} className={`rounded-xl border px-3 py-2 ${groupTone.border} ${groupTone.bg}`}><div className="flex items-center justify-between"><span className="text-[10px] font-bold text-[var(--muted-text)]">{groupLabel(group, zh)}</span><span className={`h-1.5 w-1.5 rounded-full ${groupTone.dot}`} /></div><p className={`mt-1 text-sm font-bold ${groupTone.text}`}>{item.success_count}/{item.total_count} · {Math.round(item.availability_percent)}%</p></div>;
              })}
            </div>

            <div className="mt-5 rounded-2xl border border-[var(--card-border)] p-3">
              <div className="mb-2 flex items-center justify-between"><p className="text-xs font-bold text-[var(--app-text)]">{zh ? '24 小时趋势' : '24-hour trend'}</p><span className="text-[10px] text-[var(--muted-text)]">{zh ? '左轴时延 / 右轴可用率' : 'Latency left / availability right'}</span></div>
              <div className="h-56 w-full">
                {chartData.length > 0 ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                  <defs><linearGradient id="outboundLatencyFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.25} /><stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,.15)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={24} />
                  <YAxis yAxisId="latency" tick={{ fontSize: 10 }} unit="ms" />
                  <YAxis yAxisId="availability" orientation="right" domain={[0, 100]} tick={{ fontSize: 10 }} unit="%" />
                  <Tooltip formatter={(value: number, name: string) => [name === 'availability' ? `${value}%` : `${value} ms`, name === 'availability' ? (zh ? '可用率' : 'Availability') : (zh ? '时延' : 'Latency')]} />
                  <Area yAxisId="latency" type="monotone" dataKey="latency" stroke="#0ea5e9" fill="url(#outboundLatencyFill)" connectNulls />
                  <Area yAxisId="availability" type="monotone" dataKey="availability" stroke="#10b981" fill="none" strokeWidth={2} />
                </AreaChart></ResponsiveContainer> : <div className="flex h-full items-center justify-center text-xs text-[var(--muted-text)]">{zh ? '暂无历史样本' : 'No history yet'}</div>}
              </div>
            </div>

            <div className="mt-5 rounded-2xl border border-[var(--card-border)] p-3">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-bold text-[var(--app-text)]">{zh ? '目标级结果与配置' : 'Targets & results'}</p><div className="flex items-center gap-2"><button type="button" onClick={trigger} disabled={loading} className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 px-3 py-2 text-xs font-bold text-white hover:bg-sky-700 disabled:opacity-60">{loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}{zh ? '立即检测' : 'Run now'}</button><button type="button" onClick={openNew} className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-300 px-3 py-2 text-xs font-bold text-emerald-700 hover:bg-emerald-50"><Plus size={13} />{zh ? '新增目标' : 'Add target'}</button></div></div>
              {standalone && showTargetSelector && onSelectTarget && <div className="mb-3 flex flex-wrap items-center gap-2"><label htmlFor="outbound-target-history-select" className="text-[11px] font-semibold text-[var(--muted-text)]">{zh ? '查看单个目标' : 'View target'}</label><select id="outbound-target-history-select" value={selectedTargetId || ''} onChange={(event) => onSelectTarget(event.target.value)} className="min-w-[220px] rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2 text-xs font-semibold text-[var(--app-text)]"><option value="">{zh ? '请选择探测目标' : 'Select a probe target'}</option>{(data?.targets || []).map((target) => <option key={target.id} value={target.id}>{target.target_name}</option>)}</select><span className="text-[10px] text-[var(--muted-text)]">{zh ? '选择后查看该目标的 24 小时历史结果' : 'Select a target to view its 24-hour history'}</span></div>}
              <div className="space-y-2">
                {(data?.targets || []).map((target) => {
                  const result = current?.targets.find((item) => item.target_id === target.id);
                  const targetTone = result?.success ? statusTone('healthy') : result ? statusTone('unavailable') : statusTone('unknown');
                  return <div key={target.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--card-border)] px-3 py-2.5"><span className={`h-2 w-2 rounded-full ${targetTone.dot}`} /><span className="min-w-[150px] flex-1"><span className="block text-xs font-bold text-[var(--app-text)]">{target.target_name}</span><span className="block text-[10px] text-[var(--muted-text)]">{groupLabel(target.group_name, zh)} · {target.probe_type} · {target.host}:{target.port}</span></span><span className={`text-[11px] font-bold ${targetTone.text}`}>{result ? (result.success ? (zh ? '成功' : 'Success') : (result.error_type || (zh ? '失败' : 'Failed'))) : (zh ? '待检测' : 'Pending')}</span><span className="w-16 text-right text-[11px] text-[var(--muted-text)]">{result?.latency_ms != null ? `${Math.round(result.latency_ms)} ms` : '--'}</span><button type="button" onClick={() => openEdit(target)} className="rounded-lg p-1.5 text-[var(--muted-text)] hover:bg-sky-50 hover:text-sky-700" aria-label={zh ? '编辑' : 'Edit'}><Pencil size={13} /></button><button type="button" onClick={async () => { if (!window.confirm(zh ? `确认删除 ${target.target_name}？` : `Delete ${target.target_name}?`)) return; try { await onDeleteTarget(target.id); showToast(zh ? '目标已删除' : 'Target deleted', 'success'); } catch (error) { showToast(error instanceof Error ? error.message : (zh ? '删除失败' : 'Delete failed'), 'error'); } }} className="rounded-lg p-1.5 text-[var(--muted-text)] hover:bg-red-50 hover:text-red-700" aria-label={zh ? '删除' : 'Delete'}><Trash2 size={13} /></button></div>;
                })}
              </div>
            </div>

            {formOpen && <div className="mt-4 rounded-2xl border border-sky-200 bg-sky-50/50 p-4"><div className="mb-3 flex items-center justify-between"><p className="text-xs font-bold text-sky-800">{form.id ? (zh ? '编辑探测目标' : 'Edit probe target') : (zh ? '新增探测目标' : 'New probe target')}</p><button type="button" onClick={() => setFormOpen(false)} className="rounded-lg p-1 text-sky-700 hover:bg-white"><X size={14} /></button></div><div className="grid grid-cols-1 gap-3 md:grid-cols-4"><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '名称' : 'Name'}<input value={form.target_name} onChange={(e) => setForm({ ...form, target_name: e.target.value })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label><label className="text-[10px] font-bold text-[var(--muted-text)]">Host<input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '类型' : 'Type'}<select value={form.probe_type} onChange={(e) => setForm({ ...form, probe_type: e.target.value as OutboundProbeType })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="TCP_CONNECT">TCP_CONNECT</option><option value="HTTPS_GET">HTTPS_GET</option><option value="HTTP_GET">HTTP_GET</option><option value="DNS_RESOLVE">DNS_RESOLVE</option><option value="ICMP_PING">ICMP_PING</option></select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '分组' : 'Group'}<select value={form.group_name} onChange={(e) => setForm({ ...form, group_name: e.target.value })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="domestic">{groupLabel('domestic', zh)}</option><option value="international">{groupLabel('international', zh)}</option><option value="dns">DNS</option><option value="web">Web</option><option value="business">{groupLabel('business', zh)}</option></select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '端口' : 'Port'}<input type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label><label className="text-[10px] font-bold text-[var(--muted-text)] md:col-span-2">URL {form.probe_type.includes('HTTP') && <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder={form.probe_type === 'HTTPS_GET' ? 'https://example.com/health' : 'http://example.com/health'} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" />}</label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '超时毫秒' : 'Timeout ms'}<input type="number" min={100} max={10000} value={form.timeout_ms} onChange={(e) => setForm({ ...form, timeout_ms: Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label></div><div className="mt-3 flex items-center justify-between"><label className="inline-flex items-center gap-2 text-xs font-semibold text-[var(--muted-text)]"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />{zh ? '启用目标' : 'Enabled'}</label><button type="button" onClick={save} disabled={saving} className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-700 disabled:opacity-60">{saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}{zh ? '保存' : 'Save'}</button></div></div>}
          </div>
        </div>
      )}
    </>
  );
};

export default OutboundHealthPanel;
