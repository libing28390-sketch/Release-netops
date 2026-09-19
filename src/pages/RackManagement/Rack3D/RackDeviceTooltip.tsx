import React, { useState, useEffect, memo } from 'react';
import { AlertTriangle, Network, ExternalLink, RefreshCw } from 'lucide-react';
import { RackDeviceVM } from '../types';
import { loadDeviceTelemetry, DeviceTelemetryResult, PhysicalInterfaceItem } from '../adapters/snmpTelemetry';

interface RackDeviceTooltipProps {
  device: RackDeviceVM;
  onOpenDetail: (deviceId: string) => void;
  zh: boolean;
}

export const RackDeviceTooltip: React.FC<RackDeviceTooltipProps> = memo(({
  device,
  onOpenDetail,
  zh
}) => {
  const [telemetry, setTelemetry] = useState<DeviceTelemetryResult | null>(null);
  const [telemetryStatus, setTelemetryStatus] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [telemetryReloadKey, setTelemetryReloadKey] = useState(0);
  const [selectedPortName, setSelectedPortName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTelemetryStatus('loading');
    setTelemetry(null);
    setSelectedPortName(null);
    loadDeviceTelemetry(device.name, device.networkDeviceId || device.assetId || device.id).then(result => {
      if (cancelled) return;
      setTelemetryStatus(result.status);
      setTelemetry(result.status === 'ready' ? result.data : null);
      if (result.status === 'ready' && result.data.interfaces.length > 0) {
        const firstUp = result.data.interfaces.find(i => i.status === 'up');
        setSelectedPortName((firstUp || result.data.interfaces[0]).name);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [device.assetId, device.id, device.name, device.networkDeviceId, telemetryReloadKey]);

  // Interfaces list
  const interfaces: PhysicalInterfaceItem[] = React.useMemo(() => {
    return telemetry?.interfaces || [];
  }, [telemetry]);

  const upCount = telemetry?.upCount ?? 0;
  const downCount = telemetry?.downCount ?? 0;

  // Split into 2 rows for realistic physical dual-row patch/switch panel
  const topRow = React.useMemo(() => interfaces.filter((_, idx) => idx % 2 === 0), [interfaces]);
  const bottomRow = React.useMemo(() => interfaces.filter((_, idx) => idx % 2 === 1), [interfaces]);

  // Stable active port lookup
  const activePort = React.useMemo(() => {
    if (selectedPortName) {
      const found = interfaces.find(i => i.name === selectedPortName);
      if (found) return found;
    }
    return interfaces.find(i => i.status === 'up') || interfaces[0];
  }, [selectedPortName, interfaces]);

  const healthColor = {
    healthy: 'text-emerald-400 bg-emerald-950/80 border-emerald-500/40',
    warning: 'text-amber-400 bg-amber-950/80 border-amber-500/40',
    critical: 'text-red-400 bg-red-950/80 border-red-500/40',
    offline: 'text-slate-400 bg-slate-900/80 border-slate-700/40',
    unknown: 'text-slate-300 bg-slate-800/80 border-slate-600/40'
  }[device.healthStatus];

  const healthDot = {
    healthy: 'bg-emerald-400 shadow-[0_0_8px_#34d399]',
    warning: 'bg-amber-400 shadow-[0_0_8px_#fbbf24]',
    critical: 'bg-red-400 shadow-[0_0_10px_#f87171] animate-pulse',
    offline: 'bg-slate-500',
    unknown: 'bg-slate-400'
  }[device.healthStatus];

  const healthLabel = {
    healthy: zh ? '正常运行' : 'Normal',
    warning: zh ? '注意警告' : 'Warning',
    critical: zh ? '严重告警' : 'Critical',
    offline: zh ? '已离线' : 'Offline',
    unknown: zh ? '无遥测' : 'Unknown'
  }[device.healthStatus];

  const hasKnownUPlacement = device.mountKind === 'u_mount' && device.startKnown !== false && device.heightKnown !== false;
  const uRange = device.mountKind === 'u_mount'
    ? (hasKnownUPlacement
      ? (device.heightU > 1 ? `U${device.startU} - U${device.endU}` : `U${device.startU}`)
      : (zh ? 'U 位待确认' : 'U position pending'))
    : `${device.mountKind || 'unknown'} / ${device.position || 'unknown'}`;

  const formatBps = (bps: number = 0) => {
    if (bps >= 1000000000) return `${(bps / 1000000000).toFixed(1)} Gbps`;
    if (bps >= 1000000) return `${(bps / 1000000).toFixed(1)} Mbps`;
    if (bps >= 1000) return `${(bps / 1000).toFixed(1)} Kbps`;
    return `${bps} bps`;
  };

  return (
    <div
      onClick={() => onOpenDetail(device.id)}
      className="absolute bottom-4 right-4 z-20 w-88 rounded-xl shadow-2xl backdrop-blur-xl bg-slate-950/95 border border-slate-700/80 text-slate-100 p-3.5 cursor-pointer hover:border-cyan-500/70 transition-colors duration-150"
    >
      {/* Header: Device Name & Status */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-bold text-sm text-white truncate">{device.name}</span>
          <span className="px-1.5 py-0.2 rounded text-[10px] font-semibold uppercase bg-slate-800/90 text-slate-300 border border-slate-700">
            {device.role}
          </span>
        </div>
        <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${healthColor}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${healthDot}`} />
          <span>{healthLabel}</span>
        </div>
      </div>

      {/* Model & placement */}
      <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
        <span className="truncate">{device.vendor} {device.model || 'Device'}</span>
        <span className="text-slate-300 font-semibold">{uRange}{hasKnownUPlacement ? ` (${device.heightU}U)` : ''}</span>
      </div>

      {/* Embedded Real SNMP Port Matrix */}
      <div className="p-2.5 rounded-lg bg-slate-900/95 border border-slate-800 mb-2">
        <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1.5">
          <div className="flex items-center gap-1 font-semibold text-slate-200">
            <Network size={12} className="text-cyan-400" />
            <span>
              {telemetryStatus === 'loading'
                ? (zh ? '正在读取接口遥测' : 'Loading interface telemetry')
                : telemetryStatus === 'error'
                  ? (zh ? '接口遥测不可用' : 'Interface telemetry unavailable')
                : interfaces.length > 0
                  ? `${interfaces.length}× ${zh ? '真实接口（IF-MIB）' : 'verified interfaces (IF-MIB)'}`
                  : (zh ? '无接口遥测数据' : 'No interface telemetry')}
            </span>
          </div>
          {interfaces.length > 0 && (
            <div className="flex items-center gap-2 font-mono">
              <span className="text-emerald-400 font-bold">{upCount} UP</span>
              <span className="text-slate-500">{downCount} DOWN</span>
            </div>
          )}
        </div>

        {telemetryStatus === 'loading' ? (
          <div className="flex h-24 items-center justify-center rounded border border-slate-800 bg-slate-950/70 text-xs text-slate-500">
            {zh ? '正在从监控接口读取真实数据…' : 'Loading verified monitoring data…'}
          </div>
        ) : telemetryStatus === 'error' ? (
          <div className="flex h-24 flex-col items-center justify-center rounded border border-amber-500/30 bg-amber-950/20 px-4 text-center text-xs text-amber-300">
            <AlertTriangle size={15} className="mb-1" />
            <span>{zh ? '遥测请求失败，当前接口状态未知' : 'Telemetry request failed; interface state is unknown.'}</span>
            <button
              type="button"
              onClick={event => {
                event.stopPropagation();
                setTelemetryReloadKey(value => value + 1);
              }}
              className="mt-1.5 flex items-center gap-1 rounded border border-amber-500/40 px-2 py-0.5 text-[10px]"
            >
              <RefreshCw size={10} /> {zh ? '重试' : 'Retry'}
            </button>
          </div>
        ) : interfaces.length === 0 ? (
          <div className="flex h-24 flex-col items-center justify-center rounded border border-dashed border-slate-700 bg-slate-950/70 px-4 text-center text-xs text-slate-500">
            <span>{zh ? '当前设备没有可用的物理接口遥测' : 'No physical interface telemetry is available for this device.'}</span>
            <span className="mt-1 text-[10px] text-slate-600">{zh ? '系统不会生成模拟端口或流量' : 'No simulated ports or traffic are generated.'}</span>
          </div>
        ) : (
          <>
            {/* Physical Port Matrix (Fixed Geometry - Zero Layout Shift) */}
            <div className="flex flex-col gap-1 mb-2">
              {[topRow, bottomRow].map((row, rowIndex) => (
                <div key={rowIndex} className="flex gap-1">
                  {row.map(p => {
                    const isSelected = activePort?.name === p.name;
                    const isUp = p.status === 'up';
                    return (
                      <div
                        key={p.name}
                        onMouseEnter={() => setSelectedPortName(p.name)}
                        className={`flex-1 h-5 rounded-[3px] border flex items-center justify-center transition-colors cursor-pointer ${
                          isSelected
                            ? 'border-cyan-400 ring-2 ring-cyan-500/60 bg-cyan-950/90 brightness-125'
                            : isUp
                              ? 'border-emerald-500/80 bg-emerald-950/70 hover:border-emerald-400'
                              : 'border-slate-800 bg-slate-950 hover:border-slate-600'
                        }`}
                        title={`${p.name} (${isUp ? 'UP' : 'DOWN'})`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${isUp ? 'bg-emerald-400 shadow-[0_0_5px_#34d399]' : 'bg-slate-600'}`} />
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="h-[68px] p-2 rounded bg-slate-950/90 border border-cyan-500/40 text-[11px] font-mono flex flex-col justify-between overflow-hidden">
              {activePort && (
                <>
                  <div className="flex items-center justify-between font-bold">
                    <span className="text-cyan-300 truncate">{activePort.name}</span>
                    <span className={`px-1.5 py-0.2 rounded text-[9px] font-semibold ${activePort.status === 'up' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                      {activePort.status === 'up' ? '● UP' : '● DOWN'}
                    </span>
                  </div>

                  <div className="text-[10px] text-amber-300 truncate">
                    {activePort.description ? (
                      <span>{zh ? '对端/说明:' : 'Desc:'} <strong>{activePort.description}</strong></span>
                    ) : (
                      <span className="text-slate-500">{zh ? '无对端描述信息' : 'No description'}</span>
                    )}
                  </div>

                  <div className="flex items-center justify-between text-[10px] text-slate-300">
                    <span>IN: {formatBps(activePort.inBps)}</span>
                    <span>OUT: {formatBps(activePort.outBps)}</span>
                    {(activePort.inErrors || 0) + (activePort.outErrors || 0) > 0 && (
                      <span className="text-red-400">{zh ? '错包' : 'Err'}: {activePort.inErrors}/{activePort.outErrors}</span>
                    )}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>

      {/* Telemetry quick summary (CPU/Mem/Temp from real SNMP) */}
      {telemetry && (
        <div className="flex items-center justify-between text-[11px] text-slate-400 mb-2">
          {telemetry.cpuPct != null && (
            <span>CPU: <strong className={telemetry.cpuPct > 80 ? 'text-red-400' : 'text-slate-200'}>{telemetry.cpuPct}%</strong></span>
          )}
          {telemetry.memoryPct != null && (
            <span>{zh ? '内存' : 'Mem'}: <strong className={telemetry.memoryPct > 80 ? 'text-red-400' : 'text-slate-200'}>{telemetry.memoryPct}%</strong></span>
          )}
          {telemetry.temperatureC != null && (
            <span>{zh ? '温度' : 'Temp'}: <strong className="text-slate-200">{telemetry.temperatureC}°C</strong></span>
          )}
        </div>
      )}

      {/* Action Prompt */}
      <div className="flex items-center justify-between text-[10px] text-cyan-400 font-medium border-t border-slate-800/80 pt-1.5">
        <span>{zh ? '点击打开完整监控与资产面板' : 'Click to open Full Monitoring & CMDB Panel'}</span>
        <ExternalLink size={11} />
      </div>
    </div>
  );
});
