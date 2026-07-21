import { useEffect, useMemo, useState } from 'react';
import { Globe2, Loader2, Plus } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import PageHero from '../components/PageHero';
import OutboundHealthPanel from '../components/OutboundHealthPanel';
import { useCoreApp } from '../contexts/AppDomainContext';
import type { OutboundTargetHistoryResponse } from '../types/outbound';

const HISTORY_RANGES = [
  { hours: 1, zh: '1小时', en: '1h' },
  { hours: 6, zh: '6小时', en: '6h' },
  { hours: 24, zh: '24小时', en: '24h' },
  { hours: 72, zh: '3天', en: '3d' },
  { hours: 168, zh: '7天', en: '7d' },
] as const;

const formatTime = (value: string | undefined, zh: boolean) => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(zh ? 'zh-CN' : 'en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
};

const targetGroupLabel = (group: string, zh: boolean) => ({
  domestic: zh ? '国内' : 'Domestic',
  international: zh ? '国际' : 'International',
  dns: 'DNS',
  web: 'Web',
  business: zh ? '业务' : 'Business',
}[group] || group);

const TargetHistoryCard: React.FC<{
  data: OutboundTargetHistoryResponse | null;
  loading: boolean;
  language: 'zh' | 'en';
  historyHours: number;
}> = ({ data, loading, language, historyHours }) => {
  const zh = language === 'zh';
  const [granularity, setGranularity] = useState<1 | 5>(5);
  const selectedHours = data?.history_hours ?? historyHours;
  const rangeLabel = HISTORY_RANGES.find((range) => range.hours === selectedHours)?.[zh ? 'zh' : 'en'] || `${selectedHours}h`;

  const chartData = useMemo(() => {
    if (!data?.history || data.history.length === 0) return [];
    
    // 1. Parse and sort all history points
    const points = data.history.map((point) => ({
      timestamp: new Date(point.sampled_at).getTime(),
      latency: point.latency_ms == null ? null : Number(point.latency_ms),
      success: point.success,
    })).sort((a, b) => a.timestamp - b.timestamp);

    const lastPointTime = points[points.length - 1].timestamp;
    const durationMs = selectedHours * 3600 * 1000;
    const startTime = lastPointTime - durationMs;
    const endTime = lastPointTime;
    
    const stepMs = granularity * 60 * 1000;
    
    // Normalize grid boundaries to clean step intervals (e.g. minute alignments)
    const roundedStartTime = Math.floor(startTime / stepMs) * stepMs;
    const roundedEndTime = Math.floor(endTime / stepMs) * stepMs;

    const steps: Array<{
      time: string;
      latency: number | null;
      result: number | null;
    }> = [];

    for (let t = roundedStartTime; t <= roundedEndTime; t += stepMs) {
      // Use centered nearest-neighbor window to group points to their closest tick
      const bucketStart = t - stepMs / 2;
      const bucketEnd = t + stepMs / 2;
      
      const bucketPoints = points.filter((p) => p.timestamp >= bucketStart && p.timestamp < bucketEnd);
      
      if (bucketPoints.length > 0) {
        const latencies = bucketPoints.map((p) => p.latency).filter((l): l is number => l !== null);
        const averageLatency = latencies.length > 0 ? latencies.reduce((a, b) => a + b, 0) / latencies.length : null;
        const successes = bucketPoints.filter((p) => p.success).length;
        const successRate = (successes / bucketPoints.length) * 100;
        
        steps.push({
          time: formatTime(new Date(t).toISOString(), zh),
          latency: averageLatency == null ? null : Math.round(averageLatency * 100) / 100,
          result: successRate,
        });
      } else {
        steps.push({
          time: formatTime(new Date(t).toISOString(), zh),
          latency: null,
          result: null,
        });
      }
    }
    
    return steps;
  }, [data?.history, selectedHours, granularity, zh]);

  if (!data) return null;

  return (
    <section className="mt-5 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-violet-600">{zh ? '单指标监控' : 'Single-target monitoring'}</p>
          <h2 className="mt-1 text-lg font-extrabold text-[var(--app-text)]">{data.target.target_name}</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="inline-flex rounded-md bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700">{zh ? `查询范围：${rangeLabel}` : `Range: ${rangeLabel}`}</span>
            <span className="text-[10px] font-semibold text-[var(--muted-text)]">{zh ? '数据颗粒度' : 'Granularity'}:</span>
            {[1, 5].map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGranularity(g as 1 | 5)}
                className={`rounded-md border px-2 py-0.5 text-[10px] font-bold transition-colors ${granularity === g ? 'border-violet-400 bg-violet-100 text-violet-800' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:border-violet-300 hover:text-violet-700'}`}
              >
                {zh ? `${g}分钟` : `${g}m`}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-[var(--muted-text)]">
            {data.target.probe_type} · {data.target.host}{data.target.port ? `:${data.target.port}` : ''} · {zh ? `最近 ${selectedHours} 小时` : `Last ${selectedHours} hours`}
          </p>
        </div>
        {loading && <Loader2 size={16} className="animate-spin text-violet-600" />}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          [zh ? '可用率' : 'Availability', `${Math.round(data.summary.availability_percent)}%`],
          [zh ? '样本数' : 'Samples', data.summary.sample_count],
          [zh ? '平均时延' : 'Avg latency', data.summary.average_latency_ms == null ? '--' : `${Math.round(data.summary.average_latency_ms)} ms`],
          ['P95', data.summary.p95_latency_ms == null ? '--' : `${Math.round(data.summary.p95_latency_ms)} ms`],
          [zh ? '失败次数' : 'Failures', data.summary.failure_count],
        ].map(([label, value]) => <div key={label} className="rounded-xl border border-[var(--card-border)] bg-black/[0.02] px-3 py-2.5"><p className="text-[10px] font-bold text-[var(--muted-text)]">{label}</p><p className="mt-1 text-sm font-extrabold text-[var(--app-text)]">{value}</p></div>)}
      </div>
      <div className="mt-4 h-60 w-full">
        {chartData.length > 0 ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
          <defs><linearGradient id="outboundSingleTargetLatencyFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.25} /><stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,.15)" />
          <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={24} />
          <YAxis yAxisId="latency" tick={{ fontSize: 10 }} unit="ms" />
          <YAxis yAxisId="result" orientation="right" domain={[0, 100]} tick={{ fontSize: 10 }} unit="%" />
          <Tooltip formatter={(value: number, name: string) => [name === 'result' ? `${value}%` : `${value} ms`, name === 'result' ? (zh ? '检测结果' : 'Result') : (zh ? '时延' : 'Latency')]} />
          <Area yAxisId="latency" type="monotone" dataKey="latency" stroke="#8b5cf6" fill="url(#outboundSingleTargetLatencyFill)" connectNulls={false} />
          <Area yAxisId="result" type="stepAfter" dataKey="result" stroke="#10b981" fill="none" strokeWidth={2} connectNulls={false} />
        </AreaChart></ResponsiveContainer> : <div className="flex h-full items-center justify-center text-xs text-[var(--muted-text)]">{loading ? (zh ? '正在加载历史结果…' : 'Loading history…') : (zh ? '暂无历史样本' : 'No history yet')}</div>}
      </div>
      {data.latest && !data.latest.success && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-[11px] font-semibold text-red-700">{zh ? '最近一次失败：' : 'Latest failure: '}{data.latest.error_type || (zh ? '未知错误' : 'Unknown error')}{data.latest.error_message ? ` · ${data.latest.error_message}` : ''}</p>}
    </section>
  );
};

const OutboundHealthPage: React.FC = () => {
  const {
    language,
    showToast,
    outboundHealth,
    outboundLoading,
    outboundTargetHistory,
    outboundTargetHistoryLoading,
    outboundHistoryHours,
    setOutboundHistoryHours,
    fetchOutboundHealth,
    fetchOutboundTargetHistory,
    triggerOutboundProbe,
    saveOutboundTarget,
    deleteOutboundTarget,
  } = useCoreApp();
  const zh = language === 'zh';
  const [selectedTargetId, setSelectedTargetId] = useState<string>('');
  const [addTargetRequest, setAddTargetRequest] = useState(0);

  const [customRange, setCustomRange] = useState<{ start: string; end: string } | null>(null);
  const [showCustomPicker, setShowCustomPicker] = useState(false);
  const [customQueryDates, setCustomQueryDates] = useState<{ start: string; end: string } | null>(null);

  useEffect(() => {
    const firstTargetId = outboundHealth?.targets[0]?.id || '';
    if (!selectedTargetId || !outboundHealth?.targets.some((target) => target.id === selectedTargetId)) {
      setSelectedTargetId(firstTargetId);
    }
  }, [outboundHealth?.targets, selectedTargetId]);

  useEffect(() => {
    if (!selectedTargetId) return;
    const controller = new AbortController();
    if (showCustomPicker && customQueryDates?.start && customQueryDates?.end) {
      fetchOutboundTargetHistory(
        selectedTargetId,
        controller.signal,
        undefined,
        customQueryDates.start,
        customQueryDates.end
      );
    } else {
      fetchOutboundTargetHistory(selectedTargetId, controller.signal, outboundHistoryHours);
    }
    return () => controller.abort();
  }, [fetchOutboundTargetHistory, outboundHistoryHours, selectedTargetId, showCustomPicker, customQueryDates]);

  const selectHistoryRange = (hours: number) => {
    setShowCustomPicker(false);
    setCustomQueryDates(null);
    setOutboundHistoryHours(hours);
    fetchOutboundHealth(undefined, hours);
  };

  const handleCustomQuery = () => {
    if (!customRange?.start || !customRange?.end) {
      showToast(zh ? '请选择完整的起止时间' : 'Please select start and end times', 'error');
      return;
    }
    const startMs = new Date(customRange.start).getTime();
    const endMs = new Date(customRange.end).getTime();
    if (endMs < startMs) {
      showToast(zh ? '结束时间必须在开始时间之后' : 'End time must be after start time', 'error');
      return;
    }
    const spanDays = (endMs - startMs) / (1000 * 60 * 60 * 24);
    if (spanDays > 7) {
      showToast(zh ? '每次查询的时间跨度不能超过 7 天' : 'Query time span cannot exceed 7 days', 'error');
      return;
    }
    setCustomQueryDates({
      start: new Date(customRange.start).toISOString(),
      end: new Date(customRange.end).toISOString(),
    });
  };

  return (
    <div className="min-h-full bg-[var(--app-bg)]">
      <PageHero
        icon={Globe2}
        title={zh ? '互联网出口健康' : 'Internet Outbound Health'}
        subtitle={zh ? '独立查看平台服务器的公网连通性、目标结果和历史趋势' : 'Platform server egress connectivity, target results, and historical trends'}
        eyebrow={zh ? '实时监控' : 'Real-time monitoring'}
      />
      <div className="sticky top-0 z-20 border-b border-[var(--card-border)] bg-[var(--app-bg)]/95 px-4 py-3 backdrop-blur md:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-bold text-[var(--app-text)]">{zh ? '指标快捷切换' : 'Quick target switcher'}</p>
            <p className="mt-0.5 text-[10px] text-[var(--muted-text)]">{zh ? '选择指标后直接查看单项历史结果' : 'Select a target to view its individual history'}</p>
          </div>
          <button type="button" onClick={() => setAddTargetRequest((value) => value + 1)} className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-emerald-700">
            <Plus size={14} />{zh ? '新增指标' : 'Add target'}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="mr-1 text-[10px] font-semibold text-[var(--muted-text)]">{zh ? '历史范围' : 'History range'}</span>
          {HISTORY_RANGES.map((range) => (
            <button key={range.hours} type="button" onClick={() => selectHistoryRange(range.hours)} className={`rounded-lg border px-2.5 py-1.5 text-[10px] font-bold transition-colors ${(!showCustomPicker && outboundHistoryHours === range.hours) ? 'border-sky-400 bg-sky-50 text-sky-800' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:border-sky-300 hover:text-sky-700'}`}>
              {zh ? range.zh : range.en}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setShowCustomPicker(!showCustomPicker);
              if (!showCustomPicker && !customRange) {
                const now = new Date();
                const yesterday = new Date(now.getTime() - 24 * 3600 * 1000);
                const formatForInput = (d: Date) => {
                  const pad = (n: number) => String(n).padStart(2, '0');
                  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
                };
                const formattedNow = formatForInput(now);
                const formattedYesterday = formatForInput(yesterday);
                setCustomRange({
                  start: formattedYesterday,
                  end: formattedNow,
                });
                setCustomQueryDates({
                  start: new Date(formattedYesterday).toISOString(),
                  end: new Date(formattedNow).toISOString(),
                });
              }
            }}
            className={`rounded-lg border px-2.5 py-1.5 text-[10px] font-bold transition-colors ${showCustomPicker ? 'border-violet-400 bg-violet-50 text-violet-800' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:border-violet-300 hover:text-violet-700'}`}
          >
            {zh ? '自定义时间' : 'Custom range'}
          </button>
        </div>
        {showCustomPicker && customRange && (
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-violet-100 bg-violet-50/30 p-3">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '开始时间' : 'Start Time'}</span>
              <input
                type="datetime-local"
                value={customRange.start}
                onChange={(e) => setCustomRange({ ...customRange, start: e.target.value })}
                className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1 text-xs text-[var(--app-text)] font-semibold"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '结束时间' : 'End Time'}</span>
              <input
                type="datetime-local"
                value={customRange.end}
                onChange={(e) => setCustomRange({ ...customRange, end: e.target.value })}
                className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1 text-xs text-[var(--app-text)] font-semibold"
              />
            </div>
            <button
              type="button"
              onClick={handleCustomQuery}
              className="rounded-lg bg-violet-600 px-3 py-1.5 text-[10px] font-bold text-white shadow-sm hover:bg-violet-700 transition-colors"
            >
              {zh ? '查询' : 'Query'}
            </button>
            <span className="text-[9px] text-[var(--muted-text)]">
              💡 {zh ? '注意：起止跨度不能超过7天' : 'Note: Span cannot exceed 7 days'}
            </span>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {(outboundHealth?.targets || []).map((target) => {
            const result = outboundHealth?.current?.targets.find((item) => item.target_id === target.id);
            const selected = target.id === selectedTargetId;
            return <button key={target.id} type="button" onClick={() => setSelectedTargetId(target.id)} className={`inline-flex min-w-[132px] items-center gap-2 rounded-xl border px-3 py-2 text-left transition-colors ${selected ? 'border-sky-400 bg-sky-50 text-sky-800 shadow-sm' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--app-text)] hover:border-sky-300'}`}><span className={`h-2 w-2 rounded-full ${result ? (result.success ? 'bg-emerald-500' : 'bg-red-500') : 'bg-slate-400'}`} /><span className="min-w-0"><span className="block truncate text-[11px] font-bold">{target.target_name}</span><span className="block truncate text-[9px] text-[var(--muted-text)]">{targetGroupLabel(target.group_name, zh)} · {target.probe_type}</span></span></button>;
          })}
          {!outboundHealth?.targets?.length && <span className="text-xs text-[var(--muted-text)]">{zh ? '暂无已启用的探测指标' : 'No probe targets configured'}</span>}
        </div>
      </div>
      <div className="p-4 md:p-6">
        <TargetHistoryCard data={outboundTargetHistory?.target.id === selectedTargetId ? outboundTargetHistory : null} loading={outboundTargetHistoryLoading} language={language} historyHours={outboundHistoryHours} />
        <OutboundHealthPanel
          language={language}
          data={outboundHealth}
          loading={outboundLoading}
          modalOpen={true}
          setModalOpen={() => undefined}
          standalone
          onRefresh={() => fetchOutboundHealth(undefined, outboundHistoryHours)}
          onTrigger={triggerOutboundProbe}
          onSaveTarget={saveOutboundTarget}
          onDeleteTarget={deleteOutboundTarget}
          showToast={showToast}
          selectedTargetId={selectedTargetId}
          onSelectTarget={setSelectedTargetId}
          showTargetSelector={false}
          addTargetRequest={addTargetRequest}
        />
      </div>
    </div>
  );
};

export default OutboundHealthPage;
