import React from 'react';
import { AlertTriangle, Clock3, Copy, Info, Server, ShieldAlert } from 'lucide-react';
import type {
  LibreNMSHardwareMetricSummary,
  LibreNMSHardwareNativeSample,
  LibreNMSHardwareSensor,
  LibreNMSHardwareState,
  SnmpHardwareDiscoveryTestResult,
} from './hardwareDiagnosticTypes';
import { buildHardwareDiagnosticSharePayload, redactHardwareDiagnosticText } from './hardwareDiagnosticUtils';

interface HardwareDiagnosticSummaryProps {
  result: SnmpHardwareDiscoveryTestResult | null;
  zh: boolean;
  loading?: boolean;
  error?: { message: string; permissionDenied: boolean } | null;
  onCopy?: (payload: string) => void;
}

const stateLabels: Record<string, [string, string]> = {
  not_bound: ['未绑定', 'Not bound'],
  binding_conflict: ['绑定冲突', 'Binding conflict'],
  disabled: ['绑定已停用', 'Binding disabled'],
  sync_failed: ['同步失败', 'Sync failed'],
  sync_pending: ['等待同步', 'Sync pending'],
  instance_disabled: ['实例已停用', 'Instance disabled'],
  native_device_missing: ['未关联原生设备', 'Native device missing'],
  credential_unavailable: ['API 凭据不可用', 'API credential unavailable'],
  engine_unavailable: ['引擎不可用', 'Engine unavailable'],
  pending: ['等待本地采集', 'Waiting for local collection'],
  not_configured: ['SNMP 凭据未配置', 'SNMP credentials not configured'],
  available: ['已有硬件样本', 'Hardware samples available'],
  metadata_only: ['仅有元数据', 'Metadata only'],
  no_native_hardware_data: ['暂无硬件结果', 'No hardware results'],
  unavailable: ['暂不可用', 'Unavailable'],
};

const stateTone = (state: string): string => {
  switch (state) {
    case 'available':
      return 'border-emerald-500/20 bg-emerald-500/[.05] text-emerald-700 dark:text-emerald-300';
    case 'metadata_only':
    case 'no_native_hardware_data':
    case 'pending':
    case 'not_bound':
    case 'disabled':
    case 'sync_pending':
    case 'instance_disabled':
    case 'native_device_missing':
      return 'border-amber-500/20 bg-amber-500/[.05] text-amber-700 dark:text-amber-300';
    case 'binding_conflict':
    case 'sync_failed':
    case 'credential_unavailable':
    case 'not_configured':
    case 'engine_unavailable':
    case 'unavailable':
      return 'border-rose-500/20 bg-rose-500/[.05] text-rose-700 dark:text-rose-300';
    default:
      return 'border-slate-500/20 bg-slate-500/[.05] text-slate-600 dark:text-slate-300';
  }
};

const stateLabel = (state: string, zh: boolean): string => {
  const labels = stateLabels[state];
  return labels ? labels[zh ? 0 : 1] : state.replace(/_/g, ' ') || (zh ? '未知' : 'Unknown');
};

const displayValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number' && !Number.isFinite(value)) return '—';
  return redactHardwareDiagnosticText(String(value));
};

const formatTime = (value: string | null | undefined, zh: boolean): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return date.toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false });
};

const formatAge = (value: number | null | undefined, zh: boolean): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return zh ? '时间未知' : 'Age unknown';
  const seconds = Math.max(0, Math.floor(value));
  if (seconds < 60) return zh ? `${seconds} 秒前` : `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  return zh ? `${Math.floor(hours / 24)} 天前` : `${Math.floor(hours / 24)}d ago`;
};

const freshnessLabel = (freshness: string | undefined, zh: boolean): string => {
  const labels: Record<string, [string, string]> = {
    fresh: ['新鲜', 'Fresh'],
    stale: ['已过期', 'Stale'],
    unknown: ['时间未知', 'Unknown age'],
  };
  const pair = freshness ? labels[freshness] : undefined;
  return pair ? pair[zh ? 0 : 1] : zh ? '未知' : 'Unknown';
};

const valueStatusLabel = (status: string | undefined, zh: boolean): string => {
  if (status === 'available') return zh ? '有数值' : 'Value present';
  if (status === 'missing') return zh ? '无数值' : 'No value';
  return zh ? '未知' : 'Unknown';
};

const summaryStatusLabel = (status: string, zh: boolean): string => {
  const labels: Record<string, [string, string]> = {
    available: ['有样本', 'Samples present'],
    stale: ['样本已过期', 'Samples stale'],
    missing: ['无数值', 'No values'],
  };
  const pair = labels[status];
  return pair ? pair[zh ? 0 : 1] : status.replace(/_/g, ' ');
};

const InfoGrid: React.FC<{
  title: string;
  rows: Array<[string, unknown]>;
  zh: boolean;
  icon?: React.ReactNode;
}> = ({ title, rows, zh, icon }) => (
  <div className="min-w-0 rounded-md border border-black/8 p-2 dark:border-white/10">
    <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold text-black/70 dark:text-white/75">
      {icon}{title}
    </div>
    <dl className="grid grid-cols-1 gap-x-3 gap-y-1.5 text-[10px] sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="grid min-w-0 grid-cols-[minmax(86px,auto)_minmax(0,1fr)] gap-2">
          <dt className="text-black/45 dark:text-white/45">{label}</dt>
          <dd className="break-all font-mono text-black/70 dark:text-white/75">{displayValue(value)}</dd>
        </div>
      ))}
    </dl>
  </div>
);

const MetricSummaryCard: React.FC<{ metric: LibreNMSHardwareMetricSummary; zh: boolean; localSource: boolean }> = ({ metric, zh, localSource }) => (
  <article className="min-w-0 rounded-md border border-black/8 bg-white/55 p-2 dark:border-white/10 dark:bg-white/[.025]">
    <div className="flex flex-wrap items-center justify-between gap-1.5">
      <span className="truncate text-[10px] font-semibold text-black/75 dark:text-white/80" title={displayValue(metric.key)}>{displayValue(metric.key)}</span>
      <span className="rounded-full border border-black/10 px-1.5 py-0.5 text-[9px] text-black/55 dark:border-white/10 dark:text-white/55">
        {summaryStatusLabel(metric.status, zh)}
      </span>
    </div>
    <div className="mt-2 grid grid-cols-3 gap-2 text-[9px]">
      <div><div className="text-black/40 dark:text-white/40">{zh ? '实体' : 'Entities'}</div><div className="mt-0.5 font-semibold tabular-nums">{metric.entity_count}</div></div>
      <div><div className="text-black/40 dark:text-white/40">{zh ? '有数值' : 'With value'}</div><div className="mt-0.5 font-semibold tabular-nums">{metric.value_count}</div></div>
      <div><div className="text-black/40 dark:text-white/40">{zh ? '新鲜数值' : 'Fresh values'}</div><div className="mt-0.5 font-semibold tabular-nums">{metric.fresh_count}</div></div>
    </div>
    <div className="mt-1.5 flex items-start gap-1 text-[9px] text-black/45 dark:text-white/45">
      <Clock3 size={10} className="mt-0.5 shrink-0" />
      <span>{zh ? (localSource ? '最新本地样本' : '最新原生样本') : (localSource ? 'Latest local sample' : 'Latest native sample')}: {formatTime(metric.latest_sample_at, zh)}</span>
    </div>
  </article>
);

const RuleSource: React.FC<{ row: LibreNMSHardwareSensor | LibreNMSHardwareNativeSample }> = ({ row }) => (
  <span className="min-w-0 break-all font-mono text-black/50 dark:text-white/50" title={row.source_commit}>
    {displayValue(row.source_path)}<br />
    {row.source_commit ? row.source_commit.slice(0, 12) : '—'}
    {row.poll_interval_seconds ? ` · ${row.poll_interval_seconds}s` : ''}
    {row.last_quality ? ` · ${displayValue(row.last_quality)}` : ''}
  </span>
);

const SensorRows: React.FC<{ sensors: LibreNMSHardwareSensor[]; zh: boolean; localSource: boolean }> = ({ sensors, zh, localSource }) => (
  <div className="mt-2 max-h-80 overflow-auto rounded-md border border-black/8 dark:border-white/10">
    <div className="grid min-w-[960px] grid-cols-[minmax(160px,1.4fr)_minmax(100px,.8fr)_minmax(130px,1fr)_minmax(120px,.8fr)_minmax(130px,1fr)_minmax(175px,1.2fr)] gap-2 border-b border-black/8 bg-black/[.025] px-2.5 py-1.5 text-[9px] font-semibold text-black/45 dark:border-white/10 dark:bg-white/[.03] dark:text-white/45">
      <span>{zh ? '传感器实体' : 'Sensor entity'}</span>
      <span>{zh ? (localSource ? '传感器类别' : '原生类别') : (localSource ? 'Sensor class' : 'Native class')}</span>
      <span>{zh ? (localSource ? '当前值' : '原生当前值') : (localSource ? 'Current value' : 'Native current value')}</span>
      <span>{zh ? '数值状态' : 'Value status'}</span>
      <span>{zh ? '样本时间' : 'Sample time'}</span>
      <span>{localSource ? 'SNMP OID / Index' : 'Native OID / Index'}</span>
    </div>
    {sensors.map((sensor, index) => {
      const id = sensor.sensor_id ?? `${sensor.sensor_oid || ''}-${sensor.sensor_index ?? ''}-${index}`;
      const oidAndIndex = `${displayValue(sensor.sensor_oid)} · ${displayValue(sensor.sensor_index)}`;
      return (
        <div key={String(id)} className="grid min-w-[960px] grid-cols-[minmax(160px,1.4fr)_minmax(100px,.8fr)_minmax(130px,1fr)_minmax(120px,.8fr)_minmax(130px,1fr)_minmax(175px,1.2fr)] gap-2 border-b border-black/[.04] px-2.5 py-1.5 text-[10px] last:border-b-0 dark:border-white/[.05]">
          <span className="truncate font-medium text-black/75 dark:text-white/80" title={displayValue(sensor.sensor_descr)}>{displayValue(sensor.sensor_descr)}</span>
          <span className="truncate text-black/55 dark:text-white/55" title={displayValue(sensor.sensor_class)}>{displayValue(sensor.sensor_class)}</span>
          <span className="truncate font-mono text-black/70 dark:text-white/70" title={displayValue(sensor.sensor_current)}>{displayValue(sensor.sensor_current)}</span>
          <span className="text-black/60 dark:text-white/60">{valueStatusLabel(sensor.value_status, zh)} · {freshnessLabel(sensor.freshness, zh)}</span>
          <span className="text-black/55 dark:text-white/55" title={sensor.lastupdate || sensor.observed_at || undefined}>
            {formatTime(sensor.lastupdate || sensor.observed_at, zh)}<br />{formatAge(sensor.sample_age_seconds, zh)}
          </span>
          <span className="min-w-0 font-mono text-black/45 dark:text-white/45">
            <span className="block truncate" title={oidAndIndex}>{oidAndIndex}</span>
            {localSource && <RuleSource row={sensor} />}
          </span>
        </div>
      );
    })}
  </div>
);

const NativeComputeRows: React.FC<{
  title: string;
  rows: LibreNMSHardwareNativeSample[];
  emptyMessage: string;
  zh: boolean;
  localSource: boolean;
}> = ({ title, rows, emptyMessage, zh, localSource }) => (
  <div className="min-w-0">
    <div className="mb-1.5 text-[10px] font-semibold text-black/65 dark:text-white/70">{title}</div>
    {rows.length > 0 ? (
      <div className="max-h-56 overflow-auto rounded-md border border-black/8 dark:border-white/10">
        <div className="grid min-w-[700px] grid-cols-[minmax(150px,1.2fr)_minmax(130px,1fr)_minmax(120px,.8fr)_minmax(160px,1fr)] gap-2 border-b border-black/8 bg-black/[.025] px-2.5 py-1.5 text-[9px] font-semibold text-black/45 dark:border-white/10 dark:bg-white/[.03] dark:text-white/45">
          <span>{zh ? (localSource ? '采集实体' : '原生实体') : (localSource ? 'Collected entity' : 'Native entity')}</span>
          <span>{zh ? (localSource ? '当前值' : 'LibreNMS 当前值') : (localSource ? 'Current value' : 'LibreNMS current value')}</span>
          <span>{zh ? '数值与新鲜度' : 'Value and freshness'}</span>
          <span>{zh ? (localSource ? '样本时间' : '原生样本时间') : (localSource ? 'Sample time' : 'Native sample time')}</span>
        </div>
        {rows.map((sample, index) => {
          const id = sample.sensor_id ?? `${sample.sensor_descr || ''}-${sample.sensor_index ?? ''}-${index}`;
          const value = displayValue(sample.sensor_current);
          const unit = displayValue(sample.unit);
          const valueWithUnit = value === '—' || unit === '—' ? value : `${value} ${unit}`;
          const sampleTime = sample.lastupdate || sample.observed_at;
          return (
            <div key={String(id)} className="grid min-w-[700px] grid-cols-[minmax(150px,1.2fr)_minmax(130px,1fr)_minmax(120px,.8fr)_minmax(160px,1fr)] gap-2 border-b border-black/[.04] px-2.5 py-1.5 text-[10px] last:border-b-0 dark:border-white/[.05]">
              <span className="min-w-0 font-medium text-black/75 dark:text-white/80">
                <span className="block truncate" title={displayValue(sample.sensor_descr || String(sample.sensor_id ?? ''))}>{displayValue(sample.sensor_descr || (sample.sensor_id !== undefined ? `#${sample.sensor_id}` : '—'))}</span>
                {localSource && <RuleSource row={sample} />}
              </span>
              <span className="truncate font-mono text-black/70 dark:text-white/70" title={valueWithUnit}>{valueWithUnit}</span>
              <span className="text-black/60 dark:text-white/60">{valueStatusLabel(sample.value_status, zh)} · {freshnessLabel(sample.freshness, zh)}</span>
              <span className="text-black/55 dark:text-white/55" title={sampleTime || undefined}>
                {formatTime(sampleTime, zh)}<br />{formatAge(sample.sample_age_seconds, zh)}
              </span>
            </div>
          );
        })}
      </div>
    ) : (
      <div className="rounded-md border border-dashed border-black/10 px-3 py-3 text-center text-[10px] text-black/45 dark:border-white/10 dark:text-white/45">
        {emptyMessage}
      </div>
    )}
  </div>
);

const HardwareDiagnosticSummary: React.FC<HardwareDiagnosticSummaryProps> = ({
  result,
  zh,
  loading = false,
  error = null,
  onCopy,
}) => {
  if (!result) {
    if (error) {
      const Icon = error.permissionDenied ? ShieldAlert : AlertTriangle;
      return (
        <div role="alert" className={`rounded-lg border p-3 text-xs ${error.permissionDenied ? 'border-amber-500/25 bg-amber-500/[.07] text-amber-800 dark:text-amber-200' : 'border-rose-500/20 bg-rose-500/[.06] text-rose-700 dark:text-rose-300'}`}>
          <div className="flex items-start gap-2"><Icon size={15} className="mt-0.5 shrink-0" /><span>{error.message}</span></div>
        </div>
      );
    }
    return (
      <div role={loading ? 'status' : undefined} aria-live={loading ? 'polite' : undefined} className="rounded-md border border-dashed border-black/10 px-3 py-6 text-center text-xs text-black/50 dark:border-white/10 dark:text-white/50">
        {loading
          ? (zh ? '正在读取 Nexora 已保存的最新硬件采集结果…' : 'Reading the latest hardware results saved by Nexora…')
          : (zh ? '选择已纳管设备并读取本地 SNMP 硬件采样。此操作不会触发即时 SNMP 采集。' : 'Select a managed device to read its stored local SNMP hardware samples. This does not trigger an immediate poll.')}
      </div>
    );
  }

  const sensors = result.hardware_sensors || [];
  const processorSensors = result.processor_sensors || [];
  const memoryPools = result.memory_pools || [];
  const summary = result.metric_summary || [];
  const healthGraphs = result.health_graphs || [];
  const transceivers = result.transceivers || [];
  const wirelessSensors = result.wireless_sensors || [];
  const state = String(result.state || 'unknown');
  const localSource = result.source === 'nexora_snmp';
  const hasHardwareRows = sensors.length + processorSensors.length + memoryPools.length + transceivers.length + wirelessSensors.length + healthGraphs.length > 0;
  const hardwareRowCount = result.sensor_count || sensors.length + processorSensors.length + memoryPools.length;

  return (
    <section className="rounded-lg border border-black/8 bg-white/70 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-black/80 dark:text-white/85">{localSource
            ? (zh ? 'Nexora 本地 SNMP 硬件采集结果' : 'Nexora local SNMP hardware results')
            : (zh ? 'LibreNMS 原生硬件采集结果' : 'LibreNMS native hardware results')}</div>
          <div className="mt-1 break-all text-[10px] text-black/50 dark:text-white/50">
            {displayValue(result.identity?.hostname || result.matched_hostname)}
            {result.identity?.native_device_id ? ` · ${zh ? '原生设备 ID' : 'Native device ID'} ${displayValue(result.identity.native_device_id)}` : ''}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${stateTone(state)}`}>
            {stateLabel(state, zh)}
          </span>
          <span className="rounded-full bg-black/[.05] px-2 py-0.5 text-[10px] text-black/65 dark:bg-white/[.08] dark:text-white/70">
            {zh ? `${hardwareRowCount} 个传感器/采样行` : `${hardwareRowCount} sensor/sample rows`}
          </span>
          {onCopy && (
            <button
              type="button"
              onClick={() => onCopy(buildHardwareDiagnosticSharePayload(result))}
              className="inline-flex items-center gap-1 rounded-md border border-black/10 px-2 py-1 text-[10px] font-medium text-black/65 hover:bg-black/[.04] dark:border-white/10 dark:text-white/70 dark:hover:bg-white/[.06]"
              aria-label={zh ? '复制脱敏诊断 JSON' : 'Copy redacted diagnostic JSON'}
            >
              <Copy size={12} />{zh ? '复制诊断 JSON' : 'Copy diagnostic JSON'}
            </button>
          )}
        </div>
      </div>

      <div role="status" className={`mt-2 rounded-md border px-2.5 py-2 text-[10px] leading-4 ${stateTone(state)}`}>
        {displayValue(result.message || stateLabel(state, zh))}
      </div>

      <div className="mt-2 rounded-md border border-cyan-500/15 bg-cyan-500/[.035] px-2.5 py-2 text-[10px] leading-4 text-cyan-900 dark:text-cyan-100">
        {localSource
          ? (zh
            ? '此处读取 Nexora 按打包的 LibreNMS 规则保存的硬件样本；每行显示规则文件、版本和采样周期。页面不会即时触发 SNMP 轮询，Grafana 导出状态需单独验证。'
            : 'This view reads hardware samples collected using the bundled LibreNMS rules. Each row shows its rule file, revision, and polling interval. It does not trigger a poll; validate Grafana export separately.')
          : (zh
            ? '此处读取 LibreNMS 已保存的原生结果；若本地尚无关联，会按唯一管理 IP 自动关联。不会立即发现设备或触发轮询。传感器时间取自原生样本；Grafana/时序导出状态需单独验证。'
            : 'This view reads results already stored by LibreNMS and automatically links an unbound CMDB device only when its management IP has one exact match. It does not trigger discovery or polling. Sensor times come from native samples; Grafana/time-series export must be validated separately.')}
      </div>

      {result.collection && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-[9px] text-black/55 dark:text-white/55">
          <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]">{zh ? '引擎' : 'Engine'}: {result.collection.engine_status || 'unknown'}</span>
          <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]">{zh ? '样本' : 'Samples'}: {result.collection.sample_status || 'unknown'}</span>
          <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]">{zh ? '导出验证' : 'Export validation'}: {result.collection.export_status || 'unknown'}</span>
          <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]">{zh ? '绑定同步' : 'Binding sync'}: {result.collection.sync_status || 'unknown'}</span>
          <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]" title={result.generated_at || undefined}>
            {zh ? '诊断读取' : 'Diagnostic read'}: {formatTime(result.generated_at, zh)}
          </span>
          {result.collection.stale_after_seconds !== null && result.collection.stale_after_seconds !== undefined && (
            <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]">{zh ? '过期阈值' : 'Stale after'}: {result.collection.stale_after_seconds}s</span>
          )}
          {result.collection.poll_interval_seconds && (
            <span className="rounded bg-black/[.04] px-1.5 py-1 dark:bg-white/[.05]">{zh ? '采样周期' : 'Polling interval'}: {result.collection.poll_interval_seconds}s</span>
          )}
          {result.collection.error_code && (
            <span className="rounded bg-rose-500/[.06] px-1.5 py-1 text-rose-700 dark:text-rose-300">{zh ? '错误码' : 'Error code'}: {result.collection.error_code}</span>
          )}
        </div>
      )}

      <div className={`mt-2 grid gap-2 ${localSource ? 'xl:grid-cols-2' : 'xl:grid-cols-3'}`}>
        {!localSource && <InfoGrid
          title={zh ? 'LibreNMS 绑定' : 'LibreNMS binding'}
          zh={zh}
          rows={[
            ['ID', result.binding?.id],
            [zh ? '实例' : 'Instance', result.binding?.instance_name],
            [zh ? '原生设备 ID' : 'Native device ID', result.binding?.native_device_id],
            [zh ? '原生主机名' : 'Native hostname', result.binding?.native_hostname],
            [zh ? '期望状态' : 'Desired state', result.binding?.desired_state],
            [zh ? '同步状态' : 'Sync status', result.binding?.sync_status],
            [zh ? '采集器' : 'Collector', result.binding?.collector_id],
            [zh ? '轮询组' : 'Poller group', result.binding?.poller_group],
            [zh ? '最近同步' : 'Last sync', formatTime(result.binding?.last_sync_at, zh)],
            [zh ? '最近发现' : 'Last discovery', formatTime(result.binding?.last_discovery_at, zh)],
            [zh ? '最近轮询' : 'Last poll', formatTime(result.binding?.last_poll_at, zh)],
            [zh ? '同步错误码' : 'Sync error code', result.binding?.last_error_code],
          ]}
        />}
        <InfoGrid
          title={zh ? (localSource ? '本地采集器' : '原生引擎') : (localSource ? 'Local collector' : 'Native engine')}
          zh={zh}
          icon={<Server size={12} />}
          rows={[
            [zh ? '实例' : 'Instance', result.engine?.name],
            [zh ? '版本' : 'Version', result.engine?.version],
            ['Commit', result.engine?.commit],
            [zh ? '健康状态' : 'Health state', result.engine?.health_state],
          ]}
        />
        <InfoGrid
          title={zh ? (localSource ? '设备身份' : '原生设备身份') : (localSource ? 'Device identity' : 'Native device identity')}
          zh={zh}
          rows={[
            [zh ? '主机名' : 'Hostname', result.identity?.hostname],
            [zh ? '显示名' : 'Display name', result.identity?.display],
            [zh ? '系统' : 'OS', result.identity?.os],
            [zh ? '系统版本' : 'OS version', result.identity?.version],
            [zh ? '硬件型号' : 'Hardware', result.identity?.hardware],
            ['sysObjectID', result.identity?.sysObjectID],
            [zh ? '最近发现' : 'Last discovered', formatTime(result.collection?.last_discovered, zh)],
            [zh ? '最近轮询' : 'Last polled', formatTime(result.collection?.last_polled, zh)],
          ]}
        />
      </div>

      <div className="mt-3">
        <div className="mb-1.5 text-[10px] font-semibold text-black/65 dark:text-white/70">{zh ? (localSource ? '本地传感器分类汇总' : '原生传感器分类汇总') : (localSource ? 'Local sensor class summary' : 'Native sensor class summary')}</div>
        {summary.length > 0 ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {summary.map((metric, index) => <MetricSummaryCard key={`${metric.key}-${index}`} metric={metric} zh={zh} localSource={localSource} />)}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-black/10 px-3 py-3 text-center text-[10px] text-black/45 dark:border-white/10 dark:text-white/45">
            {localSource
              ? (zh ? '当前没有可汇总的本地传感器类别。' : 'No local sensor classes are available to summarize.')
              : (zh ? 'LibreNMS 当前没有返回传感器类别汇总。' : 'LibreNMS returned no sensor class summary.')}
          </div>
        )}
      </div>

      <div className="mt-3 grid gap-2 xl:grid-cols-2">
        <NativeComputeRows
          title={zh ? 'CPU / Processor 当前值' : 'CPU / processor current values'}
          rows={processorSensors}
          zh={zh}
          localSource={localSource}
          emptyMessage={localSource
            ? (zh ? '当前没有本地 CPU 采样值。' : 'No local CPU samples are available.')
            : (zh ? 'LibreNMS 当前没有返回 Processor 当前值。健康图表名称和说明仅是元数据，不代表 CPU 读数。' : 'LibreNMS returned no current processor values. Health graph names and descriptions are metadata, not CPU readings.')}
        />
        <NativeComputeRows
          title={zh ? '内存池当前值' : 'Memory pool current values'}
          rows={memoryPools}
          zh={zh}
          localSource={localSource}
          emptyMessage={localSource
            ? (zh ? '当前没有本地内存池采样值。' : 'No local memory pool samples are available.')
            : (zh ? 'LibreNMS 当前没有返回内存池当前值。健康图表名称和说明仅是元数据，不代表内存读数。' : 'LibreNMS returned no current memory pool values. Health graph names and descriptions are metadata, not memory readings.')}
        />
      </div>

      <div className="mt-3">
        <div className="mb-1.5 text-[10px] font-semibold text-black/65 dark:text-white/70">{localSource
          ? (zh ? '本地 SNMP 传感器实体' : 'Local SNMP sensor entities')
          : (zh ? 'LibreNMS 原生传感器实体' : 'LibreNMS native sensor entities')}</div>
        {sensors.length > 0 ? (
          <SensorRows sensors={sensors} zh={zh} localSource={localSource} />
        ) : (
          <div className="rounded-md border border-dashed border-black/10 px-3 py-3 text-center text-[10px] text-black/45 dark:border-white/10 dark:text-white/45">
            {localSource
              ? (zh ? '当前没有可展示的本地传感器行；请检查上方采集状态和设备 SNMP 凭据。' : 'No local sensor rows are available. Check the collection state and device SNMP credentials above.')
              : (zh ? '没有可展示的原生传感器行；请结合上方绑定、引擎和样本状态判断。' : 'No native sensor rows are available. Check the binding, engine, and sample states above.')}
          </div>
        )}
      </div>

      {healthGraphs.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-[10px] font-semibold text-black/65 dark:text-white/70">{zh ? '特殊健康类别元数据' : 'Special health class metadata'}</div>
          <div role="note" className="mb-1.5 flex items-start gap-1.5 rounded-md border border-amber-500/20 bg-amber-500/[.05] px-2.5 py-2 text-[10px] leading-4 text-amber-800 dark:text-amber-200">
            <Info size={12} className="mt-0.5 shrink-0" />
            <span>{zh
              ? (localSource
                ? '这里只显示硬件规则提供的名称和说明元数据，不是数值样本。CPU 与内存读数只在上方存在对应本地当前值时展示。'
                : '这里只显示 LibreNMS 健康图表的名称和说明元数据，不是数值样本。CPU 与内存读数只在上方存在对应原生当前值时展示。')
              : (localSource
                ? 'These are hardware-rule names and descriptions, not numeric samples. CPU and memory readings appear above only when local current-value rows are available.'
                : 'These are LibreNMS health graph names and descriptions, not numeric samples. CPU and memory readings appear above only when native current-value rows are available.')}</span>
          </div>
          <div className="max-h-48 overflow-auto rounded-md border border-black/8 dark:border-white/10">
            {healthGraphs.map((graph, index) => (
              <div key={`${graph.health_type || ''}-${graph.name || ''}-${index}`} className="grid grid-cols-[minmax(90px,.7fr)_minmax(120px,1fr)_minmax(0,2fr)] gap-2 border-b border-black/[.04] px-2.5 py-1.5 text-[10px] last:border-b-0 dark:border-white/[.05]">
                <span className="font-mono text-black/50 dark:text-white/50">{displayValue(graph.health_type)}</span>
                <span className="break-words font-medium text-black/70 dark:text-white/75">{displayValue(graph.name)}</span>
                <span className="break-words text-black/55 dark:text-white/55">{displayValue(graph.desc)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {wirelessSensors.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-[10px] font-semibold text-black/65 dark:text-white/70">{localSource ? (zh ? '本地无线传感器' : 'Local wireless sensors') : (zh ? '原生无线传感器' : 'Native wireless sensors')}</div>
          <div className="max-h-56 overflow-auto rounded-md border border-black/8 dark:border-white/10">
            {wirelessSensors.map((sensor, index) => (
              <div key={String(sensor.sensor_id ?? `${sensor.sensor_index ?? ''}-${index}`)} className="grid grid-cols-[minmax(130px,1fr)_minmax(90px,.8fr)_minmax(100px,.8fr)_minmax(150px,1.3fr)] gap-2 border-b border-black/[.04] px-2.5 py-1.5 text-[10px] last:border-b-0 dark:border-white/[.05]">
                <span className="truncate" title={displayValue(sensor.sensor_descr)}>{displayValue(sensor.sensor_descr)}</span>
                <span>{displayValue(sensor.sensor_class)}</span>
                <span className="font-mono">{displayValue(sensor.sensor_current)}</span>
                <span className="break-all text-black/50 dark:text-white/50">{displayValue(sensor.ssid || sensor.bssid || sensor.ap_name)} · {formatTime(sensor.lastupdate, zh)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {transceivers.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-[10px] font-semibold text-black/65 dark:text-white/70">{localSource ? (zh ? '本地光模块' : 'Local transceivers') : (zh ? '原生光模块' : 'Native transceivers')}</div>
          <div className="max-h-56 overflow-auto rounded-md border border-black/8 dark:border-white/10">
            {transceivers.map((transceiver, index) => (
              <div key={String(transceiver.port_id ?? `${transceiver.ifIndex ?? ''}-${index}`)} className="grid grid-cols-[minmax(120px,1fr)_minmax(90px,.8fr)_minmax(100px,.8fr)_minmax(130px,1fr)_minmax(130px,1fr)] gap-2 border-b border-black/[.04] px-2.5 py-1.5 text-[10px] last:border-b-0 dark:border-white/[.05]">
                <span className="truncate" title={displayValue(transceiver.ifName || transceiver.ifDescr)}>{displayValue(transceiver.ifName || transceiver.ifDescr)}</span>
                <span>{displayValue(transceiver.vendor)}</span>
                <span>{displayValue(transceiver.part_number)}</span>
                <span className="break-all text-black/50 dark:text-white/50">{zh ? '序列号' : 'Serial'}: {displayValue(transceiver.serial)}</span>
                <span className="break-all text-black/50 dark:text-white/50">{zh ? '修订' : 'Revision'}: {displayValue(transceiver.revision)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!hasHardwareRows && state === 'no_native_hardware_data' && (
        <div role="status" className="mt-2 rounded-md border border-slate-500/15 bg-slate-500/[.04] px-2.5 py-2 text-[10px] leading-4 text-slate-700 dark:text-slate-200">
          {localSource
            ? (zh ? '本地 SNMP 规则当前没有检出硬件实体；这不表示设备不支持硬件监控。' : 'No hardware entities were discovered by the local SNMP rules; this does not prove the device lacks hardware monitoring support.')
            : (zh ? 'LibreNMS 未返回硬件实体。这表示当前没有原生采集结果，不能据此断定设备不支持硬件监控。' : 'LibreNMS returned no hardware entities. This means no native result is available now; it does not prove that the device lacks hardware monitoring support.')}
        </div>
      )}

      <div className="mt-3 flex items-start gap-1.5 text-[9px] leading-4 text-black/40 dark:text-white/40">
        <Info size={11} className="mt-0.5 shrink-0" />
        <span>{localSource
          ? (zh
            ? '硬件数值来自 Nexora 本地 SNMP 采集器保存的样本；此诊断页只读取库存，不触发即时 SNMP GET/WALK。'
            : 'Hardware values come from samples stored by Nexora local SNMP collection. This diagnostic reads inventory only and does not trigger immediate SNMP GET/WALK.')
          : (zh
            ? '硬件数值和原生 OID/索引来自 LibreNMS 返回的传感器实体。此诊断页只读取已有样本，不触发即时 SNMP GET/WALK。'
            : 'Hardware values and native OID/index fields come from LibreNMS sensor entities. This diagnostic reads stored samples only and does not trigger immediate SNMP GET/WALK.')}</span>
      </div>
    </section>
  );
};

export default HardwareDiagnosticSummary;
