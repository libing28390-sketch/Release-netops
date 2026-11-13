import React from 'react';
import { AlertCircle, RotateCcw, ShieldCheck } from 'lucide-react';
import type { Device } from '../types';
import ResultStatusModal from './ResultStatusModal';

interface ConnectionStage {
  stage: string;
  ok: boolean;
  summary: string;
  detail: string;
  latency_ms?: number | null;
}

interface ConnectionTestResult {
  success: boolean;
  message: string;
  output?: string;
  rawError?: string;
  errorCode?: string;
  checkMode?: string;
  stages?: ConnectionStage[];
}

interface TestConnectionResultModalProps {
  open: boolean;
  language: string;
  isTestingConnection: boolean;
  connectionTestMode: 'quick' | 'deep';
  connectionTestDevice: Device | null;
  selectedDevice: Device | null;
  testResult: ConnectionTestResult | null;
  onClose: () => void;
  onRetry: (device: Device | null, mode: 'quick' | 'deep') => void;
}

const TestConnectionResultModal: React.FC<TestConnectionResultModalProps> = ({
  open,
  language,
  isTestingConnection,
  connectionTestMode,
  connectionTestDevice,
  selectedDevice,
  testResult,
  onClose,
  onRetry,
}) => {
  const targetDevice = connectionTestDevice || selectedDevice;
  const success = !!testResult?.success;

  const title = isTestingConnection
    ? (connectionTestMode === 'deep'
      ? (language === 'zh' ? 'SSH 登录校验中...' : 'Running SSH Login Validation...')
      : (language === 'zh' ? '快速连通性检测中...' : 'Running Reachability Check...'))
    : success
      ? (testResult?.checkMode === 'deep'
        ? (language === 'zh' ? 'SSH 登录成功' : 'SSH Login Successful')
        : (language === 'zh' ? '连通性正常' : 'Reachability Confirmed'))
      : (testResult?.checkMode === 'deep'
        ? (language === 'zh' ? 'SSH 登录异常' : 'SSH Login Failed')
        : (language === 'zh' ? '连通性异常' : 'Reachability Failed'));

  return (
    <ResultStatusModal
      open={open}
      onClose={onClose}
      title={title}
      closeTitle={language === 'zh' ? '关闭结果窗口' : 'Close result dialog'}
      icon={isTestingConnection ? RotateCcw : success ? ShieldCheck : AlertCircle}
      iconClassName={isTestingConnection ? 'bg-blue-500 text-white animate-pulse' : success ? 'bg-emerald-500 text-white' : 'bg-red-500 text-white'}
      headerClassName={isTestingConnection ? 'border-b border-black/5 bg-blue-50' : success ? 'border-b border-black/5 bg-emerald-50' : 'border-b border-black/5 bg-red-50'}
      panelClassName="bg-white w-full max-w-lg rounded-3xl shadow-2xl border border-black/5 overflow-hidden"
      bodyClassName="px-6 py-5 space-y-4"
      closeDisabled={isTestingConnection}
    >
      <p className="text-xs text-black/40 -mt-3">{targetDevice?.hostname || '-'} ({targetDevice?.ip_address || '-'})</p>
      {isTestingConnection ? (
        <div className="py-10 flex flex-col items-center justify-center gap-3">
          <div className="relative">
            <div className="w-12 h-12 border-[3px] border-blue-100 rounded-full" />
            <div className="absolute inset-0 w-12 h-12 border-[3px] border-blue-500 rounded-full border-t-transparent animate-spin" />
          </div>
          <p className="text-sm font-medium text-blue-600 animate-pulse">
            {connectionTestMode === 'deep'
              ? (language === 'zh' ? '正在校验...' : 'Validating...')
              : (language === 'zh' ? '正在检测...' : 'Checking...')}
          </p>
        </div>
      ) : (
        <>
          {Array.isArray(testResult?.stages) && testResult.stages.length > 0 && (
            <div className="space-y-2">
              {testResult.stages.map((stage) => {
                const label = stage.stage === 'icmp'
                  ? 'ICMP'
                  : stage.stage === 'tcp'
                    ? `TCP/${targetDevice?.management_port || ((targetDevice?.connection_method as any) === 'telnet' ? 23 : 22)}`
                    : 'SSH';
                return (
                  <div key={`${stage.stage}-${stage.summary}`} className="flex items-center gap-3 px-3 py-2 rounded-xl bg-black/[0.03]">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${stage.ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
                    <span className="text-xs font-bold uppercase tracking-wider text-black/50 w-12">{label}</span>
                    <span className={`text-sm font-medium flex-1 ${stage.ok ? 'text-emerald-700' : 'text-red-700'}`}>
                      {stage.ok ? (language === 'zh' ? '正常' : 'OK') : (stage.detail || (language === 'zh' ? '失败' : 'Fail'))}
                    </span>
                    {typeof stage.latency_ms === 'number' && Number.isFinite(stage.latency_ms) && (
                      <span className="text-[11px] text-black/35 tabular-nums">{stage.latency_ms} ms</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {testResult?.message && (
            <p className={`text-sm ${success ? 'text-emerald-700' : 'text-red-700'}`}>{testResult.message}</p>
          )}

          {testResult?.output && (
            <details className="rounded-xl border border-black/8 bg-black/[0.02] px-3 py-2">
              <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-[0.15em] text-black/40">
                {language === 'zh' ? '原始日志' : 'Raw log'}
              </summary>
              <div className="mt-2 bg-[#00172D] p-3 rounded-lg overflow-auto max-h-[160px]">
                <pre className="text-xs font-mono text-emerald-400/90 whitespace-pre-wrap">{testResult.output}</pre>
              </div>
            </details>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={onClose}
              className="flex-1 px-3 py-2.5 rounded-xl border border-black/10 font-bold uppercase tracking-widest text-[10px] hover:bg-black/5 transition-all"
            >
              {language === 'zh' ? '关闭' : 'Close'}
            </button>
            {!success && (
              <>
                <button
                  onClick={() => onRetry(targetDevice, 'quick')}
                  className="flex-1 px-3 py-2.5 rounded-xl bg-black text-white font-bold uppercase tracking-widest text-[10px] hover:bg-black/80 transition-all shadow-lg shadow-black/20"
                >
                  {language === 'zh' ? '重试' : 'Retry'}
                </button>
                <button
                  onClick={() => onRetry(targetDevice, 'deep')}
                  className="flex-1 px-3 py-2.5 rounded-xl border border-black/10 font-bold uppercase tracking-widest text-[10px] hover:bg-black/5 transition-all"
                >
                  {language === 'zh' ? 'SSH 校验' : 'SSH Check'}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </ResultStatusModal>
  );
};

export default TestConnectionResultModal;