import React from 'react';
import { CheckCircle, Clock, Loader2, Network, RotateCcw, Server, XCircle } from 'lucide-react';
import ResultStatusModal from './ResultStatusModal';

interface SnmpTestResult {
  success?: boolean;
  response_ms?: number | null;
  ip?: string;
  community?: string;
  port?: number;
  sys_name?: string;
  sys_descr?: string;
  error?: string;
  metric_profile_id?: string | null;
  metric_profile_status?: string;
  metric_profile_source?: string;
  metric_sources?: Record<string, string>;
  collection_mode?: string;
  hardware_metrics?: Record<string, unknown>;
  metric_details?: Record<string, { status?: string; unit?: string; message?: string; source?: string; oid?: string; mode?: string }>;
  hardware_collection_status?: string;
}

interface SnmpTestResultModalProps {
  open: boolean;
  language: string;
  result: SnmpTestResult | null;
  onClose: () => void;
}

const SnmpTestResultModal: React.FC<SnmpTestResultModalProps> = ({ open, language, result, onClose }) => {
  const isZh = language === 'zh';
  const success = !!result?.success;
  const hardwareLabels: Record<string, string> = isZh
    ? { cpu: 'CPU 使用率', memory: '内存使用率', temperature: '设备温度', fan: '风扇状态', power_supply: '电源状态' }
    : { cpu: 'CPU usage', memory: 'Memory usage', temperature: 'Temperature', fan: 'Fan status', power_supply: 'Power supply' };
  const hardwareUnits: Record<string, string> = { cpu: '%', memory: '%', temperature: '°C' };
  const hardwareEntries = Object.entries(result?.hardware_metrics || {});
  const sourceLabel = (key: string, detail: { source?: string }) => {
    const source = result?.metric_sources?.[key] || detail.source || '';
    if (source === 'snmp_template' || source === 'verified_model_profile' || source === 'template_definition') return isZh ? 'SNMP 型号模板' : 'SNMP model template';
    if (source === 'device_override') return isZh ? '旧版单台覆盖（已忽略）' : 'Legacy device override (ignored)';
    return isZh ? '未应用 SNMP 模板' : 'SNMP template not applied';
  };
  const profileSourceLabel = (source?: string) => {
    if (!isZh) return source || 'template_not_applied';
    return ({
      snmp_template: 'SNMP 型号模板',
      model_profile: '型号模板',
      verified_model_profile: '型号模板',
      device_override: '旧版单台覆盖（已忽略）',
      mixed: 'SNMP 型号模板',
      template_not_applied: '未应用 SNMP 模板',
      builtin_default: '已停用的内置默认',
    } as Record<string, string>)[source || 'template_not_applied'] || source || '未应用 SNMP 模板';
  };
  const profileStatusLabel = (status?: string) => {
    if (!isZh) return status || 'none';
    return ({ verified: '已验证', unverified: '待验证', failed: '验证失败', none: '未配置' } as Record<string, string>)[status || 'none'] || status || '未配置';
  };
  const collectionModeLabel = (mode?: string) => {
    if (!isZh) return mode || 'health_only';
    return ({ health_only: '仅硬件健康', traffic: '接口流量', full: '完整采集' } as Record<string, string>)[mode || 'health_only'] || mode || '仅硬件健康';
  };

  return (
    <ResultStatusModal
      open={open}
      onClose={onClose}
      title={isZh ? 'SNMP 连通测试' : 'SNMP Connectivity Test'}
      closeTitle={isZh ? '关闭' : 'Close'}
      icon={result ? (success ? CheckCircle : XCircle) : Network}
      iconClassName={result ? (success ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-500') : 'bg-slate-100 text-slate-500'}
      onBackdropClick={onClose}
    >
      {!result ? (
        <div className="flex flex-col items-center justify-center py-10 gap-3">
          <Loader2 className="animate-spin text-cyan-500" size={28} />
          <p className="text-sm text-black/40">{isZh ? '正在测试 SNMP 连通性…' : 'Testing SNMP connectivity…'}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* ── 状态横幅 ── */}
          <div className={`rounded-xl px-4 py-3 flex items-center gap-3 ${success ? 'bg-emerald-50' : 'bg-red-50'}`}>
            {success ? <CheckCircle size={20} className="text-emerald-600 shrink-0" /> : <XCircle size={20} className="text-red-500 shrink-0" />}
            <div className="min-w-0">
              <p className={`font-semibold text-sm ${success ? 'text-emerald-700' : 'text-red-600'}`}>
                {success ? (isZh ? 'SNMP 连通成功' : 'SNMP Reachable') : (isZh ? 'SNMP 连通失败' : 'SNMP Unreachable')}
              </p>
              {result.response_ms != null && (
                <p className="text-[11px] text-black/40 flex items-center gap-1 mt-0.5">
                  <Clock size={10} /> {result.response_ms} ms
                </p>
              )}
            </div>
          </div>

          {/* ── 连接参数 ── */}
          <div className="rounded-xl border border-black/5 overflow-hidden">
            <div className="px-3 py-2 bg-black/[0.02] border-b border-black/5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '连接参数' : 'Connection'}</p>
            </div>
            <div className="divide-y divide-black/5 text-xs">
              {[
                { label: 'IP', value: result.ip },
                { label: 'Community', value: result.community },
                { label: 'Port', value: result.port },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between px-3 py-2">
                  <span className="text-black/40">{row.label}</span>
                  <span className="font-mono text-[#0b2340]">{row.value ?? '-'}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── 设备信息 ── */}
          {(result.sys_name || result.sys_descr) && (
            <div className="rounded-xl border border-black/5 overflow-hidden">
              <div className="px-3 py-2 bg-black/[0.02] border-b border-black/5 flex items-center gap-1.5">
                <Server size={12} className="text-black/30" />
                <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '设备信息' : 'Device Info'}</p>
              </div>
              <div className="divide-y divide-black/5 text-xs">
                {result.sys_name && (
                  <div className="flex items-center justify-between px-3 py-2">
                    <span className="text-black/40">sysName</span>
                    <span className="font-semibold text-[#0b2340]">{result.sys_name}</span>
                  </div>
                )}
                {result.sys_descr && (
                  <div className="px-3 py-2">
                    <span className="text-black/40 text-[10px] block mb-1.5">sysDescr</span>
                    <pre className="text-[11px] text-black/55 bg-black/[0.02] rounded-lg px-2.5 py-2 whitespace-pre-wrap break-all leading-relaxed max-h-[120px] overflow-y-auto font-mono">{result.sys_descr}</pre>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="rounded-xl border border-cyan-100 bg-cyan-50/50 px-3 py-2.5">
            <p className="text-[10px] font-bold uppercase tracking-widest text-cyan-900/55 mb-1.5">{isZh ? '健康模板关联' : 'Health Template'}</p>
            <div className="space-y-1 text-[11px] text-cyan-950">
              <p>{isZh ? '模板 ID' : 'Profile ID'}: <span className="font-mono font-semibold">{result.metric_profile_id || (isZh ? '未配置，使用内置默认' : 'Not configured; built-in default')}</span></p>
               <p>{isZh ? '来源 / 状态' : 'Source / Status'}: <span className="font-semibold">{profileSourceLabel(result.metric_profile_source)} / {profileStatusLabel(result.metric_profile_status)}</span></p>
               <p>{isZh ? '采集模式' : 'Collection mode'}: <span className="font-semibold">{collectionModeLabel(result.collection_mode)}</span></p>
            </div>
          </div>

          {hardwareEntries.length > 0 && (
            <div className="rounded-xl border border-black/5 overflow-hidden">
              <div className="px-3 py-2 bg-black/[0.02] border-b border-black/5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '硬件健康采集' : 'Hardware Health'}</p>
              </div>
              <div className="grid grid-cols-2 gap-2 p-3">
                {hardwareEntries.map(([key, value]) => {
                  const detail = result.metric_details?.[key] || {};
                  const status = String(detail.status || (value === null || value === undefined ? 'missing' : value === false ? 'fail' : 'ok')).toLowerCase();
                  const abnormal = ['fail', 'warning', 'probe_error'].includes(status);
                  const invalid = ['missing', 'invalid_value', 'out_of_range'].includes(status);
                  const text = value === true
                    ? (isZh ? '正常' : 'Normal')
                    : value === false
                      ? (isZh ? '异常' : 'Abnormal')
                      : value === null || value === undefined || value === ''
                        ? '—'
                        : `${String(value)}${hardwareUnits[key] ? ` ${hardwareUnits[key]}` : ''}`;
                  return (
                    <div key={key} className={`rounded-lg border px-2.5 py-2 ${abnormal ? 'border-red-200 bg-red-50/60' : invalid ? 'border-amber-200 bg-amber-50/60' : 'border-emerald-200 bg-emerald-50/50'}`}>
                      <div className="text-[10px] text-black/45">{hardwareLabels[key] || key}</div>
                      <div className={`mt-1 text-sm font-semibold ${abnormal ? 'text-red-600' : invalid ? 'text-amber-600' : 'text-emerald-700'}`}>{text}</div>
                      <div className="mt-1 text-[9px] font-semibold text-cyan-700 dark:text-cyan-600">{isZh ? '采集来源：' : 'Source: '}{sourceLabel(key, detail)}</div>
                      {detail.message && <div className="mt-0.5 text-[9px] text-black/40 line-clamp-2">{detail.message}</div>}
                      {detail.oid && <div className="mt-0.5 truncate font-mono text-[8px] text-black/30" title={detail.oid}>OID {detail.oid}</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {success && hardwareEntries.length === 0 && result.hardware_collection_status && result.hardware_collection_status !== 'pending' && (
            <div className="rounded-xl border border-amber-100 bg-amber-50/60 px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-amber-700/70 mb-1">{isZh ? '硬件采集状态' : 'Hardware Collection'}</p>
              <p className="text-[11px] text-amber-700">
                {result.hardware_collection_status === 'failed'
                  ? (isZh ? 'SNMP 通道成功，但硬件指标采集失败；请检查模板 OID、SNMP View 和设备权限。' : 'SNMP is reachable, but hardware collection failed; check template OIDs, SNMP view, and permissions.')
                  : (isZh ? 'SNMP 通道成功，但默认硬件指标没有返回值。' : 'SNMP is reachable, but the default hardware metrics returned no value.')}
              </p>
            </div>
          )}

          {/* ── 错误信息 ── */}
          {result.error && (
            <div className="rounded-xl border border-red-100 bg-red-50/50 px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-red-400 mb-1">{isZh ? '错误信息' : 'Error'}</p>
              <p className="text-[11px] text-red-500 break-all leading-relaxed">{result.error}</p>
            </div>
          )}

          {/* ── 同步提示 ── */}
          {success && (
            <p className="text-[11px] text-black/30 text-center">
              {result.hardware_collection_status === 'success'
                ? (isZh ? '硬件健康指标已采集，设备列表将在下一次刷新后显示' : 'Hardware health metrics collected; the device list will show them after refresh.')
                : (isZh ? '后台正在同步轻量健康数据，稍后自动刷新' : 'Lightweight health data is syncing in background…')}
            </p>
          )}
        </div>
      )}
    </ResultStatusModal>
  );
};

export default SnmpTestResultModal;
