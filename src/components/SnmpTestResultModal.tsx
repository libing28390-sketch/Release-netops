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

          {/* ── 错误信息 ── */}
          {result.error && (
            <div className="rounded-xl border border-red-100 bg-red-50/50 px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-red-400 mb-1">{isZh ? '错误信息' : 'Error'}</p>
              <p className="text-[11px] text-red-500 break-all leading-relaxed">{result.error}</p>
            </div>
          )}

          {/* ── 同步提示 ── */}
          {success && (
            <p className="text-[11px] text-black/30 text-center">{isZh ? '后台正在同步设备完整数据，稍后自动刷新' : 'Full device data syncing in background…'}</p>
          )}
        </div>
      )}
    </ResultStatusModal>
  );
};

export default SnmpTestResultModal;