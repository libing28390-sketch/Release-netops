import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Clock3, Network, RefreshCw, ShieldCheck } from 'lucide-react';
import {
  DeviceTelemetryLoadResult,
  PhysicalInterfaceItem,
  loadDeviceTelemetry,
} from '../adapters/snmpTelemetry';

interface DevicePortMatrixProps {
  deviceId: string;
  deviceName: string;
  deviceRole?: string;
  zh: boolean;
}

const formatBps = (bps: number = 0) => {
  if (bps >= 1_000_000_000) return `${(bps / 1_000_000_000).toFixed(1)} Gbps`;
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} Mbps`;
  if (bps >= 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`;
  return `${bps} bps`;
};

const formatSampleTime = (value: string | undefined, zh: boolean) => {
  if (!value) return zh ? '无采样时间' : 'No sample timestamp';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(zh ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
};

export const DevicePortMatrix: React.FC<DevicePortMatrixProps> = ({
  deviceId,
  deviceName,
  zh,
}) => {
  const [result, setResult] = useState<DeviceTelemetryLoadResult | null>(null);
  const [selectedPortName, setSelectedPortName] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setSelectedPortName(null);
    loadDeviceTelemetry(deviceName, deviceId).then(next => {
      if (cancelled) return;
      setResult(next);
      if (next.status === 'ready') {
        const firstUp = next.data.interfaces.find(item => item.status === 'up');
        setSelectedPortName((firstUp || next.data.interfaces[0])?.name || null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [deviceId, deviceName, reloadKey]);

  const telemetry = result?.status === 'ready' ? result.data : null;
  const interfaces = telemetry?.interfaces || [];
  const selectedPort = useMemo<PhysicalInterfaceItem | null>(
    () => interfaces.find(item => item.name === selectedPortName) || interfaces[0] || null,
    [interfaces, selectedPortName],
  );
  const topRow = useMemo(() => interfaces.filter((_, index) => index % 2 === 0), [interfaces]);
  const bottomRow = useMemo(() => interfaces.filter((_, index) => index % 2 === 1), [interfaces]);

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/90 p-3 text-slate-200">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5">
            <Network size={14} className="text-cyan-400" />
            <h4 className="text-xs font-bold text-white">
              {zh ? '物理接口遥测' : 'Physical Interface Telemetry'}
            </h4>
          </div>
          <p className="mt-1 text-[10px] text-slate-500">
            {zh ? '数据源：监控服务 IF-MIB；不生成模拟端口或流量' : 'Source: monitoring IF-MIB; no simulated ports or traffic'}
          </p>
        </div>
        {telemetry && (
          <div className="text-right text-[10px] text-slate-400">
            <div className="flex items-center justify-end gap-1">
              <Clock3 size={10} />
              {formatSampleTime(telemetry.sampledAt, zh)}
            </div>
            <span className={telemetry.isStale ? 'text-amber-400' : 'text-emerald-400'}>
              {telemetry.isStale ? (zh ? '数据已过期' : 'Stale') : (zh ? '数据新鲜' : 'Fresh')}
            </span>
          </div>
        )}
      </div>

      {!result ? (
        <div className="flex h-24 items-center justify-center gap-2 rounded border border-slate-800 bg-slate-950/70 text-xs text-slate-500">
          <RefreshCw size={13} className="animate-spin" />
          {zh ? '正在读取真实接口遥测…' : 'Loading verified interface telemetry…'}
        </div>
      ) : result.status === 'error' ? (
        <div className="flex min-h-24 flex-col items-center justify-center rounded border border-amber-500/30 bg-amber-950/20 px-4 text-center text-xs text-amber-300">
          <AlertTriangle size={16} className="mb-1" />
          <span>{zh ? '接口遥测请求失败，当前状态未知' : 'Interface telemetry request failed; state is unknown.'}</span>
          <button
            type="button"
            onClick={() => setReloadKey(value => value + 1)}
            className="mt-2 rounded border border-amber-500/40 px-2 py-1 text-[10px] hover:bg-amber-500/10"
          >
            {zh ? '重试遥测' : 'Retry telemetry'}
          </button>
        </div>
      ) : result.status === 'empty' ? (
        <div className="flex min-h-24 flex-col items-center justify-center rounded border border-dashed border-slate-700 bg-slate-950/70 px-4 text-center text-xs text-slate-500">
          <ShieldCheck size={16} className="mb-1 text-slate-400" />
          <span>
            {result.reason === 'not_registered'
              ? (zh ? '设备未关联监控对象，无法读取接口遥测' : 'The rack device is not linked to a monitoring target.')
              : (zh ? '最近 15 分钟没有可用的物理接口采样' : 'No physical interface samples are available in the last 15 minutes.')}
          </span>
          <span className="mt-1 text-[10px] text-slate-600">
            {zh ? '系统不会用演示端口填补缺失数据' : 'Missing data is never replaced with demo ports.'}
          </span>
        </div>
      ) : (
        <>
          <div className="mb-2 flex items-center justify-between text-[10px]">
            <span className="text-slate-400">{interfaces.length} {zh ? '个已验证接口' : 'verified interfaces'}</span>
            <div className="flex items-center gap-2 font-mono">
              <span className="font-bold text-emerald-400">{telemetry?.upCount ?? 0} UP</span>
              <span className="text-slate-500">{telemetry?.downCount ?? 0} DOWN</span>
            </div>
          </div>

          <div className="mb-3 rounded-lg border border-slate-800 bg-slate-950/80 p-2">
            <div className="flex flex-col gap-1.5">
              {[topRow, bottomRow].map((row, rowIndex) => (
                <div key={rowIndex} className="flex gap-1">
                  {row.map(port => {
                    const selected = selectedPort?.name === port.name;
                    const up = port.status === 'up';
                    return (
                      <button
                        key={port.name}
                        type="button"
                        onClick={() => setSelectedPortName(port.name)}
                        className={`flex h-6 min-w-5 flex-1 items-center justify-center rounded-[3px] border transition-all ${
                          selected
                            ? 'z-10 scale-105 border-cyan-400 bg-cyan-950/80 ring-2 ring-cyan-500/50'
                            : up
                              ? 'border-emerald-500/80 bg-emerald-950/70 hover:border-emerald-400'
                              : 'border-slate-800 bg-slate-900/90 hover:border-slate-600'
                        }`}
                        title={`${port.name} (${port.status.toUpperCase()})`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${up ? 'bg-emerald-400 shadow-[0_0_5px_#34d399]' : 'bg-slate-600'}`} />
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          {selectedPort && (
            <div className="rounded-lg border border-cyan-500/30 bg-slate-950 p-2.5 text-xs">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="truncate font-mono font-bold text-white">{selectedPort.name}</div>
                <span className={selectedPort.status === 'up' ? 'text-emerald-400' : 'text-slate-400'}>
                  ● {selectedPort.status.toUpperCase()}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-300">
                <span>{zh ? '速率' : 'Speed'}: {selectedPort.speedMbps ? `${selectedPort.speedMbps} Mbps` : '—'}</span>
                <span>{zh ? '介质' : 'Medium'}: {selectedPort.cableType === 'fiber' ? (zh ? '光纤' : 'Fiber') : (zh ? '双绞线' : 'Copper')}</span>
              </div>
              {selectedPort.description && (
                <div className="mt-2 rounded border border-slate-800 bg-slate-900 p-1.5 text-[11px] text-amber-300">
                  {selectedPort.description}
                </div>
              )}
              <div className="mt-2 flex items-center justify-between border-t border-slate-800 pt-1.5 font-mono text-[10px] text-slate-300">
                <span>IN: {formatBps(selectedPort.inBps)}</span>
                <span>OUT: {formatBps(selectedPort.outBps)}</span>
                {(selectedPort.inErrors || 0) + (selectedPort.outErrors || 0) > 0 && (
                  <span className="font-bold text-red-400">{zh ? '错包' : 'Errors'}: {selectedPort.inErrors}/{selectedPort.outErrors}</span>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
