import React from 'react';
import { AlertTriangle, Clock3, Database, Eye, HeartPulse, Server, Zap } from 'lucide-react';
import { RackDeviceVM } from '../types';
import { DevicePortMatrix } from './DevicePortMatrix';

interface RackReadonlyInspectorProps {
  device: RackDeviceVM;
  rackUpdatedAt?: string;
  zh: boolean;
}

const formatTime = (value: string | undefined, zh: boolean) => {
  if (!value) return zh ? '未提供' : 'Not provided';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(zh ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
};

const healthStyle: Record<RackDeviceVM['healthStatus'], string> = {
  healthy: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
  warning: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  critical: 'bg-red-500/10 text-red-600 border-red-500/30',
  offline: 'bg-slate-500/10 text-slate-500 border-slate-500/30',
  unknown: 'bg-slate-500/10 text-slate-500 border-slate-500/30',
};

export const RackReadonlyInspector: React.FC<RackReadonlyInspectorProps> = ({
  device,
  rackUpdatedAt,
  zh,
}) => {
  const isUMount = device.mountKind === 'u_mount';
  const hasKnownUPlacement = isUMount && device.startKnown !== false && device.heightKnown !== false;
  const uRange = isUMount
    ? (hasKnownUPlacement
      ? (device.heightU > 1 ? `U${device.startU}–U${device.endU}` : `U${device.startU}`)
      : (zh ? 'U 位待确认' : 'U position pending'))
    : (zh ? '非标准 U 位' : 'Non-U placement');
  const mountKindLabel: Record<string, string> = {
    u_mount: zh ? '标准 U 位' : 'Standard U mount',
    zero_u: '0U',
    side_mount: zh ? '侧挂' : 'Side mount',
    floor: zh ? '落地' : 'Floor-standing',
    unknown: zh ? '待确认' : 'Unknown',
  };
  const positionLabel: Record<string, string> = {
    front: zh ? '前面板' : 'Front',
    rear: zh ? '后面板' : 'Rear',
    full_depth: zh ? '全深度' : 'Full depth',
    left_side: zh ? '左侧挂' : 'Left side',
    right_side: zh ? '右侧挂' : 'Right side',
    unknown: zh ? '待确认' : 'Unknown',
  };
  const placementStatusLabel: Record<string, string> = {
    confirmed: zh ? '已确认' : 'Confirmed',
    estimated: zh ? '估算' : 'Estimated',
    unknown: zh ? '待确认' : 'Unknown',
    invalid: zh ? '异常' : 'Invalid',
  };
  const fidelityLabel: Record<string, string> = {
    exact: zh ? '精确模型' : 'Exact model',
    family: zh ? '系列模型' : 'Family model',
    vendor: zh ? '厂商通用模型' : 'Vendor generic',
    generic: zh ? '全局通用模型' : 'Global generic',
  };
  const healthLabel: Record<RackDeviceVM['healthStatus'], string> = {
    healthy: zh ? '正常' : 'Healthy',
    warning: zh ? '警告' : 'Warning',
    critical: zh ? '严重' : 'Critical',
    offline: zh ? '离线' : 'Offline',
    unknown: zh ? '无遥测' : 'No telemetry',
  };

  const assetDisplay = device.assetTag || device.assetId || (zh ? '未关联' : 'Not linked');
  const monitoringTargetDisplay = (() => {
    const parts = [device.networkHostname, device.networkIp].filter(Boolean);
    if (parts.length > 0) return parts.join(' · ');
    if (device.networkDeviceId) return zh ? '已关联监控' : 'Linked';
    return zh ? '未关联' : 'Not linked';
  })();

  const fields: Array<{ label: string; value: string; title?: string }> = [
    { label: zh ? '位置' : 'Placement', value: `${uRange}${hasKnownUPlacement ? ` · ${device.heightU}U` : ''}` },
    { label: zh ? '安装方式' : 'Mount kind', value: mountKindLabel[device.mountKind || 'unknown'] || device.mountKind || '—' },
    { label: zh ? '安装位置' : 'Position', value: positionLabel[device.position || 'unknown'] || device.position || '—' },
    { label: zh ? '安装面' : 'Face', value: device.face === 'front' ? (zh ? '前面板' : 'Front') : (zh ? '后面板' : 'Rear') },
    {
      label: zh ? '位置状态' : 'Placement status',
      value: device.placementStatus
        ? (placementStatusLabel[device.placementStatus.toLowerCase()] || device.placementStatus)
        : (zh ? '未提供' : 'Not provided'),
    },
    { label: zh ? '位置说明' : 'Location note', value: device.locationNote || '—' },
    { label: zh ? '厂商 / 型号' : 'Vendor / model', value: `${device.vendor || '—'} / ${device.model || '—'}` },
    { label: zh ? '序列号' : 'Serial number', value: device.serialNumber || '—' },
    {
      label: zh ? '资产关联' : 'Asset link',
      value: assetDisplay,
      title: device.assetId ? `ID: ${device.assetId}` : undefined,
    },
    {
      label: zh ? '监控对象' : 'Monitoring target',
      value: monitoringTargetDisplay,
      title: device.networkDeviceId ? `ID: ${device.networkDeviceId}` : undefined,
    },
    ...(device.assetKey
      ? [{ label: zh ? '3D 资产' : '3D asset', value: `${fidelityLabel[device.assetFidelity || 'generic'] || device.assetFidelity || '—'} · ${device.assetKey}` }]
      : []),
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3">
        <div className="flex items-center gap-2">
          <Eye size={15} className="text-cyan-600" />
          <div>
            <p className="text-xs font-bold" style={{ color: 'var(--heading-text)' }}>
              {zh ? '设备资产与监控详情' : 'Device Asset & Monitoring Details'}
            </p>
            <p className="text-[10px]" style={{ color: 'var(--muted-text)' }}>
              {zh ? 'U 位来自 CMDB 机柜台账；健康与端口状态来自实时监控' : 'U-slot comes from CMDB rack inventory; health and ports come from live monitoring.'}
            </p>
          </div>
        </div>
        <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${healthStyle[device.healthStatus]}`}>
          {healthLabel[device.healthStatus]}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        {fields.map(({ label, value, title }) => (
          <div key={label} title={title} className="rounded-lg border p-2" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)' }}>
            <div className="mb-1 text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{label}</div>
            <div className="break-all font-medium" style={{ color: 'var(--body-text)' }}>{value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--card-border)' }}>
          <div className="flex items-center gap-1 text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>
            <Zap size={11} /> {zh ? '额定功率' : 'Rated power'}
          </div>
          <div className="mt-1 font-mono font-bold text-amber-500">{device.metrics.ratedPowerWatts} W</div>
          <div className="mt-0.5 text-[9px]" style={{ color: 'var(--muted-text)' }}>{device.metrics.powerSource}</div>
        </div>
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--card-border)' }}>
          <div className="flex items-center gap-1 text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>
            <HeartPulse size={11} /> {zh ? '健康依据' : 'Health source'}
          </div>
          <div className="mt-1 font-medium" style={{ color: 'var(--body-text)' }}>
            {device.healthStatus === 'unknown' ? (zh ? '缺少有效遥测' : 'No verified telemetry') : (zh ? '监控与告警聚合' : 'Monitoring and alert aggregation')}
          </div>
        </div>
      </div>

      <div className="rounded-lg border p-2.5 text-[10px]" style={{ borderColor: 'var(--card-border)' }}>
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1 font-semibold" style={{ color: 'var(--body-text)' }}>
            <Database size={11} /> {zh ? '布局数据源：CMDB 机柜布局' : 'Layout source: CMDB rack layout'}
          </span>
          <span className="flex items-center gap-1" style={{ color: 'var(--muted-text)' }}>
            <Clock3 size={10} /> {formatTime(rackUpdatedAt, zh)}
          </span>
        </div>
      </div>

      {!device.dataQuality.valid && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5 text-[10px] text-amber-600">
          <div className="mb-1 flex items-center gap-1 font-bold">
            <AlertTriangle size={12} /> {zh ? '数据质量问题' : 'Data quality issues'}
          </div>
          <ul className="list-disc space-y-0.5 pl-4">
            {device.dataQuality.issues.map(issue => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-1 text-[10px]" style={{ color: 'var(--muted-text)' }}>
        <Server size={11} />
        {zh ? '接口区域仅展示当前监控接口返回的真实采样。' : 'The interface panel only displays samples returned by monitoring.'}
      </div>
      <DevicePortMatrix
        deviceId={device.networkDeviceId || device.assetId || device.id}
        deviceName={device.name}
        deviceRole={device.role}
        fallbackPortProfile={device.physicalPortProfile}
        zh={zh}
      />
    </div>
  );
};
