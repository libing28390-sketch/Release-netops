import React from 'react';
import type { Device, DeviceConnectionCheckSummary } from '../../types';
import { HEALTH_CFG, CHECK_BADGE, formatCheckTime } from './StatusBadge';
import Sparkline from '../Sparkline';

interface DeviceRowExpandProps {
  device: Device;
  language: string;
  deviceConnectionChecks: Record<string, DeviceConnectionCheckSummary>;
}

const DeviceRowExpand: React.FC<DeviceRowExpandProps> = ({
  device, language, deviceConnectionChecks,
}) => {
  const zh = language === 'zh';
  const check = deviceConnectionChecks[device.id];
  const badge = check ? (CHECK_BADGE[check.status] || CHECK_BADGE.fail) : null;
  const h = HEALTH_CFG[device.health_status || 'unknown'] || HEALTH_CFG.unknown;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 px-6 py-4
      bg-black/[.015] dark:bg-white/[.02] border-t border-black/4 dark:border-white/6 text-[11px]">

      {/* Col 1: Hardware */}
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1.5">
          {zh ? '硬件' : 'Hardware'}
        </span>
        <div className="space-y-0.5">
          <p className="text-black/65 dark:text-white/65">
            {zh ? '型号' : 'Model'}: <span className="font-medium">{device.model || 'N/A'}</span>
          </p>
          <p className="text-black/65 dark:text-white/65">
            SN: <span className="font-mono font-medium">{device.sn || 'N/A'}</span>
          </p>
          <p className="text-black/65 dark:text-white/65">
            {zh ? '运行时间' : 'Uptime'}: <span className="font-medium">{device.uptime || 'N/A'}</span>
          </p>
        </div>
      </div>

      {/* Col 2: Software */}
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1.5">
          {zh ? '软件' : 'Software'}
        </span>
        <div className="space-y-0.5">
          <p className="text-black/65 dark:text-white/65">
            {zh ? '版本' : 'Version'}: <span className="font-medium">{device.version || 'N/A'}</span>
          </p>
          <p className="text-black/65 dark:text-white/65">
            {zh ? '协议' : 'Method'}: <span className="font-medium uppercase">{device.connection_method || 'ssh'}</span>
          </p>
          <p className="text-black/65 dark:text-white/65">
            {zh ? '合规' : 'Compliance'}:
            <span className={`ml-1 font-medium ${
              device.compliance === 'compliant' ? 'text-emerald-600 dark:text-emerald-400'
              : device.compliance === 'non-compliant' ? 'text-red-500 dark:text-red-400'
              : 'text-black/40 dark:text-white/40'
            }`}>
              {device.compliance || 'unknown'}
            </span>
          </p>
        </div>
      </div>

      {/* Col 3: Health */}
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1.5">
          {zh ? '健康详情' : 'Health Detail'}
        </span>
        <p className="text-black/65 dark:text-white/65">
          {zh ? '评分' : 'Score'}: <span className="font-semibold">{Math.max(0, Math.min(100, Number(device.health_score || 0)))}</span>
          <span className={`ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase ${h.bg} ${h.border} ${h.text}`}>
            {zh ? h.labelZh : h.labelEn}
          </span>
        </p>
        <p className="text-black/45 dark:text-white/40 mt-0.5 line-clamp-2">
          {device.health_summary || (zh ? '暂无摘要' : 'No summary')}
        </p>
        <div className="flex gap-3 mt-1 text-[10px] text-black/40 dark:text-white/35">
          <span>{zh ? '告警' : 'Alerts'} {Number(device.open_alert_count || 0)}</span>
          <span>{zh ? '接口Down' : 'IF Down'} {Number(device.interface_down_count || 0)}</span>
        </div>
      </div>

      {/* Col 4: Trends & Uptime */}
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1.5">
          {zh ? '趋势' : 'Trends'}
        </span>
        {device.cpu_history && device.cpu_history.length > 0 ? (
          <>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[9px] font-semibold text-black/40 dark:text-white/40 w-8">CPU</span>
              <Sparkline data={device.cpu_history} color="#00bceb" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-semibold text-black/40 dark:text-white/40 w-8">MEM</span>
              <Sparkline data={device.memory_history || []} color="#10b981" />
            </div>
          </>
        ) : (
          <p className="text-[10px] text-black/20 dark:text-white/15">{zh ? '暂无趋势数据' : 'No trend data'}</p>
        )}
        {device.uptime && (
          <p className="text-[9px] text-black/30 dark:text-white/25 font-mono mt-1.5" title={device.uptime}>
            ⏱ {device.uptime.length > 28 ? device.uptime.slice(0, 28) + '…' : device.uptime}
          </p>
        )}
        {check && badge && (
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase ${badge.cls}`}>
              {zh ? badge.zh : badge.en}
            </span>
            <span className="text-[9px] text-black/30 dark:text-white/25">
              {formatCheckTime(check.checked_at, language)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default DeviceRowExpand;
