import { useEffect, useMemo, useState } from 'react';
import {
  Activity, CheckCircle2, Clock3, Globe2, Loader2, Pencil, Plus, RefreshCw,
  Save, ShieldAlert, Trash2, X, XCircle,
} from 'lucide-react';
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend, ReferenceArea,
} from 'recharts';
import type {
  OutboundHealthResponse,
  OutboundProbeType,
  OutboundStatus,
  OutboundTarget,
} from '../types/outbound';
import { ActionIconButton, ActionIconGroup } from './ui/ActionIconButton';

const CustomTooltip = ({ active, payload, label, zh }: any) => {
  if (active && payload && payload.length) {
    const pData = payload[0].payload;
    const lat = pData.latency;
    const avail = pData.availability ?? pData.result;
    const successCount = pData.success_count;
    const totalTargets = pData.total_targets;
    return (
      <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)]/95 px-3 py-2 text-[11px] shadow-xl backdrop-blur-sm">
        <p className="font-extrabold text-[var(--app-text)] mb-1">{label}</p>
        <div className="space-y-0.5 font-bold">
          <p className="flex items-center justify-between gap-4">
            <span className="text-[var(--muted-text)]">{zh ? '平均时延：' : 'Avg Latency: '}</span>
            <span className="text-sky-500">{lat != null ? `${Math.round(Number(lat))} ms` : '--'}</span>
          </p>
          <p className="flex items-center justify-between gap-4">
            <span className="text-[var(--muted-text)]">{zh ? '可用率：' : 'Availability: '}</span>
            <span className="text-emerald-500">{avail != null ? `${Math.round(Number(avail))}%` : '--'}</span>
          </p>
          {successCount != null && totalTargets != null && (
            <p className="flex items-center justify-between gap-4 border-t border-[var(--card-border)] pt-1 mt-1 text-[10px]">
              <span className="text-[var(--muted-text)]">{zh ? '成功目标：' : 'Success Rate: '}</span>
              <span className={successCount === totalTargets ? 'text-emerald-600' : 'text-yellow-600'}>
                {successCount} / {totalTargets}
              </span>
            </p>
          )}
        </div>
      </div>
    );
  }
  return null;
};


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
  if (status === 'degraded') return { text: 'text-yellow-600', bg: 'bg-yellow-50/40', border: 'border-yellow-200', dot: 'bg-yellow-500' };
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
  const [countdown, setCountdown] = useState<string>('');
  const [showRulesModal, setShowRulesModal] = useState(false);

  useEffect(() => {
    if (!current?.next_check_at) {
      setCountdown(zh ? '任务运行中' : 'Task running');
      return;
    }
    const update = () => {
      const next = new Date(current.next_check_at).getTime();
      const now = Date.now();
      const diff = Math.max(0, Math.round((next - now) / 1000));
      if (diff <= 0) {
        setCountdown(zh ? '正在检测...' : 'Checking...');
      } else {
        setCountdown(zh ? `下次检测: ${diff} 秒后` : `Next: ${diff}s`);
      }
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [current?.next_check_at, zh]);
  const chartData = useMemo(() => {
    const rawHistory = data?.history || [];
    if (rawHistory.length === 0) return [];
    
    const sorted = rawHistory.map((point) => ({
      timestamp: new Date(point.finished_at).getTime(),
      time: formatTime(point.finished_at, zh),
      latency: point.average_latency_ms == null ? null : Number(point.average_latency_ms),
      raw_avail: Number(point.availability_percent ?? 100),
      success_count: point.success_count,
      total_targets: point.total_targets,
      status: point.status,
    })).sort((a, b) => a.timestamp - b.timestamp);

    const sortedWithWindow = sorted.map((p, idx) => {
      const windowStart = Math.max(0, idx - 4);
      const windowPoints = sorted.slice(windowStart, idx + 1);
      const sumAvail = windowPoints.reduce((sum, item) => sum + item.raw_avail, 0);
      const avgAvail = sumAvail / windowPoints.length;
      return {
        ...p,
        availability: Math.round(avgAvail),
      };
    });

    const filled: Array<{
      time: string;
      latency: number | null;
      availability: number | null;
      success_count?: number;
      total_targets?: number;
      status?: string;
    }> = [];

    for (let i = 0; i < sortedWithWindow.length; i++) {
      filled.push(sortedWithWindow[i]);
      if (i < sortedWithWindow.length - 1) {
        const currentMs = sortedWithWindow[i].timestamp;
        const nextMs = sortedWithWindow[i + 1].timestamp;
        const gapMs = nextMs - currentMs;
        if (gapMs > 180000) { // Gap > 3 minutes
          filled.push({
            time: formatTime(new Date(currentMs + 60000).toISOString(), zh),
            latency: null,
            availability: null,
          });
        }
      }
    }
    return filled;
  }, [data?.history, zh]);
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
          <span className={`mt-2 block text-2xl font-extrabold ${tone.text}`}>
            {statusLabel(current?.status, zh)}
            {current?.public_ip_changed && <span className="ml-1 text-sm font-semibold text-amber-500">⚠️ {zh ? 'IP 漂移' : 'IP drift'}</span>}
          </span>
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
                  <Plus size={13} />{zh ? '新增探测目标' : 'Add target'}
                </button>
                <button type="button" onClick={() => onRefresh()} className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--card-border)] px-3 py-2 text-xs font-semibold text-[var(--muted-text)] hover:border-sky-300 hover:text-sky-700">
                  <RefreshCw size={13} />{zh ? '刷新' : 'Refresh'}
                </button>
                {!standalone && <button type="button" onClick={() => setModalOpen(false)} className="rounded-xl p-2 text-[var(--muted-text)] hover:bg-black/5" aria-label={zh ? '关闭' : 'Close'}><X size={18} /></button>}
              </div>
            </div>

            {current?.status_reasons && current.status_reasons.length > 0 && (
              <div className="mt-4 space-y-2">
                {current.status_reasons.map((reason, idx) => {
                  const borderClass = reason.severity === 'critical' ? 'border-red-200 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-800';
                  return (
                    <div key={idx} className={`flex items-start gap-2.5 rounded-2xl border p-3.5 text-xs font-semibold ${borderClass}`}>
                      <ShieldAlert size={16} className="mt-0.5 shrink-0" />
                      <div>
                        <span className="font-extrabold">{reason.severity === 'critical' ? (zh ? '【错误/严重告警】' : '[Critical Error] ') : (zh ? '【状态警告】' : '[Warning] ')}</span>
                        {reason.message}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-6">
              {/* Card 1: 综合状态 */}
              <div className={`rounded-2xl border px-3 py-2.5 bg-black/[0.01] ${tone.border}`}>
                <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '综合状态' : 'Overall Status'}</p>
                <p className={`mt-0.5 text-sm font-extrabold ${tone.text}`}>
                  {statusLabel(current?.status, zh)}
                </p>
                <p className="mt-0.5 text-[10px] text-[var(--muted-text)] truncate">
                  {current?.egress_ip?.match === false ? (zh ? '公网 IP 不匹配' : 'IP mismatch') : 
                   current?.status === 'degraded' ? (zh ? '部分拨测失败' : 'Partial failures') : 
                   (zh ? '监控正常运行' : 'Running')}
                </p>
              </div>

              {/* Card 2: 网络连通性 */}
              {(() => {
                const connStatus = current?.connectivity_status || current?.status;
                const connTone = statusTone(connStatus);
                return (
                  <div className={`rounded-2xl border px-3 py-2.5 bg-black/[0.01] ${connTone.border}`}>
                    <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '网络连通性' : 'Connectivity'}</p>
                    <p className={`mt-0.5 text-sm font-extrabold ${connTone.text}`}>
                      {statusLabel(connStatus, zh)}
                    </p>
                    <p className="mt-0.5 text-[10px] text-[var(--muted-text)] truncate">
                      {zh ? `${current?.success_count || 0} / ${current?.total_count || 0} 个可用` : `${current?.success_count || 0} / ${current?.total_count || 0} targets`}
                    </p>
                  </div>
                );
              })()}

              {/* Card 3: 公网出口 IP */}
              <div className="rounded-2xl border border-[var(--card-border)] px-3 py-2.5 bg-black/[0.01]">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '公网出口 IP' : 'Egress IP'}</p>
                <p className="mt-0.5 text-sm font-extrabold text-[var(--app-text)] truncate" title={current?.public_ip || '--'}>
                  {current?.public_ip || '--'}
                </p>
                <p className="mt-0.5 text-[10px] text-[var(--muted-text)] truncate">
                  {current?.egress_ip ? (
                    current.egress_ip.source === 'static_override' ? (zh ? '静态配置 · 未验证' : 'Static (unverified)') :
                    current.egress_ip.source === 'detected' ? (zh ? '在线探测 · 已验证' : 'Detected (verified)') :
                    current.egress_ip.source === 'cached' ? (zh ? '历史缓存' : 'Cached') : (zh ? '未知' : 'Unknown')
                  ) : (zh ? '未知' : 'Unknown')}
                </p>
              </div>

              {/* Card 4: IP 合规状态 */}
              {(() => {
                const hasExpected = current?.egress_ip?.expected && current.egress_ip.expected.length > 0;
                const matchClass = !hasExpected ? 'text-slate-500' : current?.egress_ip?.match ? 'text-emerald-600' : 'text-amber-600';
                const matchBorder = !hasExpected ? 'border-[var(--card-border)] bg-black/[0.01]' : current?.egress_ip?.match ? 'border-emerald-200 bg-emerald-50/10' : 'border-amber-200 bg-amber-50/10';
                return (
                  <div 
                    className={`rounded-2xl border px-3 py-2.5 cursor-pointer transition-colors ${matchBorder}`}
                    onClick={() => { if (hasExpected) setShowRulesModal(true); }}
                    title={zh ? '点击查看详细期望白名单规则' : 'Click to view expected whitelist rules'}
                  >
                    <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? 'IP 合规状态' : 'IP Compliance'}</p>
                    <p className={`mt-0.5 text-sm font-extrabold ${matchClass}`}>
                      {!hasExpected ? (zh ? '未限制' : 'No limit') : current?.egress_ip?.match ? (zh ? '匹配' : 'Match') : (zh ? '不匹配' : 'Mismatch')}
                    </p>
                    <p className="mt-0.5 text-[10px] text-[var(--muted-text)] truncate">
                      {hasExpected ? (
                        current.egress_ip.expected.length === 1 
                          ? (zh ? `期望: ${current.egress_ip.expected[0]}` : `Exp: ${current.egress_ip.expected[0]}`)
                          : (zh ? `${current.egress_ip.expected.length} 条规则` : `${current.egress_ip.expected.length} rules`)
                      ) : (zh ? '未限制' : 'No limit')}
                    </p>
                  </div>
                );
              })()}

              {/* Card 5: 平均时延 */}
              <div className="rounded-2xl border border-[var(--card-border)] px-3 py-2.5 bg-black/[0.01]">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '时延指标' : 'Latency'}</p>
                <p className="mt-0.5 text-sm font-extrabold text-[var(--app-text)] truncate">
                  {current?.average_latency_ms != null ? `${Math.round(current.average_latency_ms)} ms` : '--'}
                </p>
                <p className="mt-0.5 text-[10px] text-[var(--muted-text)] truncate">
                  P95: {current?.p95_latency_ms != null ? Math.round(current.p95_latency_ms) : '--'} ms · {zh ? '最大' : 'Max'}: {current?.max_latency_ms != null ? Math.round(current.max_latency_ms) : '--'} ms
                </p>
              </div>

              {/* Card 6: 最后检测 */}
              <div className="rounded-2xl border border-[var(--card-border)] px-3 py-2.5 bg-black/[0.01]">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '检测状态' : 'Check Status'}</p>
                <p className="mt-0.5 text-sm font-extrabold text-[var(--app-text)] truncate">
                  {formatTime(current?.checked_at, zh)}
                </p>
                <p className={`mt-0.5 text-[10px] truncate ${current?.scheduler_is_running === false ? 'text-red-500 font-semibold animate-pulse' : 'text-[var(--muted-text)]'}`}>
                  {current?.scheduler_is_running === false 
                    ? (zh ? `数据中断 ${current.scheduler_interrupted_minutes}m` : `Stalled ${current.scheduler_interrupted_minutes}m`)
                    : countdown}
                </p>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-5">
              {Object.entries(current?.groups || {}).map(([group, item]) => {
                const groupTone = statusTone(item.status);
                return <div key={group} className={`rounded-xl border px-3 py-2 ${groupTone.border} ${groupTone.bg}`}><div className="flex items-center justify-between"><span className="text-[10px] font-bold text-[var(--muted-text)]">{groupLabel(group, zh)}</span><span className={`h-1.5 w-1.5 rounded-full ${groupTone.dot}`} /></div><p className={`mt-1 text-sm font-bold ${groupTone.text}`}>{item.success_count}/{item.total_count} · {Math.round(item.availability_percent)}%</p></div>;
              })}
            </div>

            <div className="mt-5 rounded-2xl border border-[var(--card-border)] p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-bold text-[var(--app-text)]">
                  {zh ? `${data?.history_hours || 1} 小时趋势` : `${data?.history_hours || 1}-hour trend`}
                </p>
              </div>
              <div className="h-56 w-full">
                {chartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                      <defs>
                        <linearGradient id="outboundLatencyFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.12} />
                          <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,.15)" />
                      <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={24} />
                      <YAxis yAxisId="latency" tick={{ fontSize: 10 }} unit="ms" />
                      <YAxis yAxisId="availability" orientation="right" domain={[0, 110]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 10 }} unit="%" />
                      <Tooltip content={<CustomTooltip zh={zh} />} />
                      <Legend verticalAlign="top" height={36} content={(props) => {
                        const { payload } = props;
                        return (
                          <div className="flex justify-end gap-4 text-[10px] font-bold text-[var(--muted-text)] mb-2">
                            {payload?.map((entry: any, index: number) => {
                              const color = entry.color;
                              const label = entry.value === 'latency' ? (zh ? '平均时延(ms)' : 'Average Latency (ms)') : (zh ? '可用率(%)' : 'Availability (%)');
                              return (
                                <span key={`item-${index}`} className="flex items-center gap-1.5">
                                  <span className="h-1.5 w-3 rounded-full" style={{ backgroundColor: color }} />
                                  {label}
                                </span>
                              );
                            })}
                          </div>
                        );
                      }} />
                      {chartData.map((point, idx) => {
                        if (point.availability != null && point.availability < 100) {
                          return (
                            <ReferenceArea
                              key={`ref-${idx}`}
                              x1={point.time}
                              x2={point.time}
                              yAxisId="availability"
                              fill="rgba(234, 179, 8, 0.12)"
                              stroke="rgba(234, 179, 8, 0.20)"
                              strokeWidth={1}
                            />
                          );
                        }
                        return null;
                      })}
                      <Area yAxisId="latency" type="monotone" dataKey="latency" name="latency" stroke="#0ea5e9" fill="url(#outboundLatencyFill)" connectNulls={false} dot={false} activeDot={{ r: 4 }} />
                      <Area yAxisId="availability" type="linear" dataKey="availability" name="availability" stroke="#10b981" fill="none" strokeWidth={2} connectNulls={false} dot={false} activeDot={{ r: 4 }} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-[var(--muted-text)]">
                    {zh ? '暂无历史样本' : 'No history yet'}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-5 rounded-2xl border border-[var(--card-border)] p-3">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-bold text-[var(--app-text)]">{zh ? '目标级结果与配置' : 'Targets & results'}</p><div className="flex items-center gap-2"><button type="button" onClick={trigger} disabled={loading} className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 px-3 py-2 text-xs font-bold text-white hover:bg-sky-700 disabled:opacity-60">{loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}{zh ? '立即检测' : 'Run now'}</button><button type="button" onClick={openNew} className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-300 px-3 py-2 text-xs font-bold text-emerald-700 hover:bg-emerald-50"><Plus size={13} />{zh ? '新增目标' : 'Add target'}</button></div></div>
              {standalone && showTargetSelector && onSelectTarget && <div className="mb-3 flex flex-wrap items-center gap-2"><label htmlFor="outbound-target-history-select" className="text-[11px] font-semibold text-[var(--muted-text)]">{zh ? '查看单个目标' : 'View target'}</label><select id="outbound-target-history-select" value={selectedTargetId || ''} onChange={(event) => onSelectTarget(event.target.value)} className="min-w-[220px] rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2 text-xs font-semibold text-[var(--app-text)]"><option value="">{zh ? '请选择探测目标' : 'Select a probe target'}</option>{(data?.targets || []).map((target) => <option key={target.id} value={target.id}>{target.target_name}</option>)}</select><span className="text-[10px] text-[var(--muted-text)]">{zh ? '选择后查看该目标的 24 小时历史结果' : 'Select a target to view its 24-hour history'}</span></div>}
              <div className="space-y-2">
                {(data?.targets || []).map((target) => {
                  const result = current?.targets.find((item) => item.target_id === target.id);
                  
                  let statusText = zh ? '待检测' : 'Pending';
                  let targetToneText = 'text-slate-500';
                  let targetToneDot = 'bg-slate-400';
                  let borderClass = 'border-[var(--card-border)]';
                  let bgClass = 'bg-black/[0.01]';
                  
                  if (result) {
                    const avail = result.recent_availability ?? 100;
                    if (!result.success) {
                      statusText = result.error_type ? (zh ? `故障 (${result.error_type})` : `Failed (${result.error_type})`) : (zh ? '故障' : 'Failed');
                      targetToneText = 'text-red-600 font-extrabold';
                      targetToneDot = 'bg-red-500';
                      borderClass = 'border-red-200';
                      bgClass = 'bg-red-50/10';
                    } else if (avail < 95) {
                      statusText = zh ? `不稳定 · 近1小时可用率 ${Math.round(avail)}%` : `Unstable · Last 1h ${Math.round(avail)}%`;
                      targetToneText = 'text-yellow-600 font-extrabold';
                      targetToneDot = 'bg-yellow-500 animate-pulse';
                      borderClass = 'border-yellow-200';
                      bgClass = 'bg-yellow-50/15';
                    } else {
                      statusText = zh ? '可用' : 'Available';
                      targetToneText = 'text-emerald-600 font-extrabold';
                      targetToneDot = 'bg-emerald-500';
                      borderClass = 'border-emerald-200';
                      bgClass = 'bg-emerald-50/10';
                    }
                  }

                  return (
                    <div key={target.id} className={`flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2.5 transition-colors ${borderClass} ${bgClass}`}>
                      <span className={`h-2.5 w-2.5 rounded-full ${targetToneDot}`} />
                      <span className="min-w-[150px] flex-1">
                        <span className="block text-xs font-extrabold text-[var(--app-text)]">{target.target_name}</span>
                        <span className="block text-[10px] text-[var(--muted-text)] font-semibold mt-0.5">
                          {groupLabel(target.group_name, zh)} · {target.probe_type} · {target.host}:{target.port}
                        </span>
                      </span>
                      <span className={`text-[11px] ${targetToneText}`}>
                        {statusText}
                      </span>
                      <span className="w-16 text-right text-[11px] font-bold text-[var(--muted-text)]">
                        {result?.latency_ms != null ? `${Math.round(result.latency_ms)} ms` : '--'}
                      </span>
                      <ActionIconGroup label={zh ? '探测目标操作' : 'Probe target actions'}>
                        <ActionIconButton icon={Pencil} label={zh ? '编辑' : 'Edit'} variant="accent" onClick={() => openEdit(target)} />
                        <ActionIconButton icon={Trash2} label={zh ? '删除' : 'Delete'} variant="danger" onClick={async () => { if (!window.confirm(zh ? `确认删除 ${target.target_name}？` : `Delete ${target.target_name}?`)) return; try { await onDeleteTarget(target.id); showToast(zh ? '目标已删除' : 'Target deleted', 'success'); } catch (error) { showToast(error instanceof Error ? error.message : (zh ? '删除失败' : 'Delete failed'), 'error'); } }} />
                      </ActionIconGroup>
                    </div>
                  );
                })}
              </div>
            </div>

            {formOpen && <div className="mt-4 rounded-2xl border border-sky-200 bg-sky-50/50 p-4"><div className="mb-3 flex items-center justify-between"><p className="text-xs font-bold text-sky-800">{form.id ? (zh ? '编辑探测目标' : 'Edit probe target') : (zh ? '新增探测目标' : 'New probe target')}</p><button type="button" onClick={() => setFormOpen(false)} className="rounded-lg p-1 text-sky-700 hover:bg-white"><X size={14} /></button></div><div className="grid grid-cols-1 gap-3 md:grid-cols-4"><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '名称' : 'Name'}<input value={form.target_name} onChange={(e) => setForm({ ...form, target_name: e.target.value })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label><label className="text-[10px] font-bold text-[var(--muted-text)]">Host<input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '类型' : 'Type'}<select value={form.probe_type} onChange={(e) => setForm({ ...form, probe_type: e.target.value as OutboundProbeType })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="TCP_CONNECT">TCP_CONNECT</option><option value="HTTPS_GET">HTTPS_GET</option><option value="HTTP_GET">HTTP_GET</option><option value="DNS_RESOLVE">DNS_RESOLVE</option><option value="ICMP_PING">ICMP_PING</option></select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '分组' : 'Group'}<select value={form.group_name} onChange={(e) => setForm({ ...form, group_name: e.target.value })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="domestic">{groupLabel('domestic', zh)}</option><option value="international">{groupLabel('international', zh)}</option><option value="dns">DNS</option><option value="web">Web</option><option value="business">{groupLabel('business', zh)}</option></select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '端口' : 'Port'}<input type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label><label className="text-[10px] font-bold text-[var(--muted-text)] md:col-span-2">URL {form.probe_type.includes('HTTP') && <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder={form.probe_type === 'HTTPS_GET' ? 'https://example.com/health' : 'http://example.com/health'} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" />}</label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '超时毫秒' : 'Timeout ms'}<input type="number" min={100} max={10000} value={form.timeout_ms} onChange={(e) => setForm({ ...form, timeout_ms: Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label></div><div className="mt-3 flex items-center justify-between"><label className="inline-flex items-center gap-2 text-xs font-semibold text-[var(--muted-text)]"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />{zh ? '启用目标' : 'Enabled'}</label><button type="button" onClick={save} disabled={saving} className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-700 disabled:opacity-60">{saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}{zh ? '保存' : 'Save'}</button></div></div>}
            {showRulesModal && (
              <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm" onClick={() => setShowRulesModal(false)}>
                <div className="w-full max-w-md overflow-hidden rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center justify-between border-b border-[var(--card-border)] pb-3">
                    <h3 className="text-sm font-extrabold text-[var(--app-text)]">{zh ? '期望公网出口白名单规则' : 'Expected IP Rules'}</h3>
                    <button type="button" onClick={() => setShowRulesModal(false)} className="rounded-lg p-1 text-[var(--muted-text)] hover:bg-black/5"><X size={16} /></button>
                  </div>
                  <div className="mt-4 space-y-2 max-h-60 overflow-y-auto">
                    {current?.egress_ip?.expected.map((rule, idx) => (
                      <div key={idx} className="rounded-xl border border-[var(--card-border)] bg-black/[0.01] px-3.5 py-2.5 text-xs font-semibold text-[var(--app-text)] flex items-center justify-between">
                        <span>{rule}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-extrabold ${current?.public_ip && current.public_ip === rule ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-50 text-slate-600'}`}>
                          {current?.public_ip && current.public_ip === rule ? (zh ? '当前连接中' : 'Connected') : (zh ? '白名单' : 'Allowed')}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-5 flex justify-end">
                    <button type="button" onClick={() => setShowRulesModal(false)} className="rounded-xl bg-sky-600 px-4 py-2 text-xs font-bold text-white hover:bg-sky-700">
                      {zh ? '确定' : 'Close'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
};

export default OutboundHealthPanel;
