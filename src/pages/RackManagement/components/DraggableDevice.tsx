import React, { useState, useRef } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Zap } from 'lucide-react';
import { RackDevice } from '../types';
import { U_PX, RACK_W, STATUS_LABEL } from '../constants';
import { getNormalizedRoleColor, uToY } from '../helpers';
import PowerLed from './PowerLed';
import DeviceIcon from './DeviceIcon';
import { deviceRoleLabel } from '../../../domain/deviceLabels';

interface DraggableDeviceProps {
  device: RackDevice;
  totalU: number;
  viewSide?: 'front' | 'rear';
  isSelected?: boolean;
  zh: boolean;
  isDragOverlay?: boolean;
  onSelect?: (deviceId: string) => void;
}

/** Compact hardware mini-faceplate graphic (real CMDB+SNMP port pips on front; dual A/B PSUs on rear). */
export const Device2DMiniFaceplate: React.FC<{
  device: RackDevice;
  viewSide: 'front' | 'rear';
  heightU: number;
}> = ({ device, viewSide, heightU }) => {
  const role = (device.device_role || '').toLowerCase();
  const isPassive = role.includes('patch');

  if (viewSide === 'rear') {
    if (isPassive) {
      return (
        <div className="hidden sm:flex items-center gap-1 rounded bg-slate-950/60 px-1.5 py-0.5 text-[8px] font-mono text-slate-400 border border-slate-700/60">
          <span>REAR PUNCH</span>
        </div>
      );
    }
    return (
      <div className="hidden sm:flex items-center gap-1 flex-shrink-0">
        <span className="inline-flex items-center gap-0.5 rounded bg-red-950/90 border border-red-500/60 px-1 py-0.2 text-[8px] font-mono font-bold text-red-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          PSU-A
        </span>
        <span className="inline-flex items-center gap-0.5 rounded bg-blue-950/90 border border-blue-500/60 px-1 py-0.2 text-[8px] font-mono font-bold text-blue-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          PSU-B
        </span>
        <span
          className="inline-flex items-center gap-0.5 rounded bg-slate-950/80 border border-slate-700/70 px-1 py-0.5"
          title="Rear Fan Modules"
        >
          {[0, 1, 2].map(i => (
            <span key={i} className="w-1.5 h-2 rounded-[1px] bg-slate-700 border border-slate-600/70" />
          ))}
        </span>
      </div>
    );
  }

  // Front view: render real synced port pips when available, or clean schematic bay slots
  const profile = device.physical_port_profile;
  const ports = profile?.ports || [];
  if (ports.length > 0) {
    // Sample up to 16 visual pips evenly across the port array while guaranteeing all UP ports are visible
    const maxPips = heightU >= 2 ? 18 : 14;
    const upPorts = ports.filter(p => p.oper_status === 'up');
    const step = Math.max(1, Math.floor(ports.length / maxPips));
    const sampled = ports.filter((_, idx) => idx % step === 0).slice(0, maxPips);
    // Ensure real UP count is reflected cleanly
    const upCount = profile?.up_ports ?? upPorts.length;
    const totalCount = profile?.total_ports ?? ports.length;

    return (
      <div className="hidden sm:flex items-center gap-1.5 flex-shrink-0">
        <div className="grid grid-flow-col grid-rows-2 gap-[2px] rounded bg-slate-950/85 border border-slate-700/70 px-1 py-[2px]">
          {sampled.map((p, idx) => {
            const isUp = p.oper_status === 'up';
            return (
              <span
                key={`${p.name}-${idx}`}
                className={`w-[5px] h-[5px] rounded-[1px] ${
                  isUp
                    ? 'bg-emerald-400 shadow-[0_0_4px_#34d399]'
                    : 'bg-slate-700/90'
                }`}
              />
            );
          })}
        </div>
        <span className="text-[8px] font-mono font-semibold text-emerald-300/95 whitespace-nowrap">
          {upCount}/{totalCount}P
        </span>
      </div>
    );
  }

  // Fallback compact schematic vents/bays when no SNMP port profile is attached
  return (
    <div className="hidden sm:flex items-center gap-[2px] rounded bg-slate-950/65 border border-slate-700/60 px-1 py-[3px] flex-shrink-0">
      {[0, 1, 2, 3, 4, 5].map(i => (
        <span key={i} className="w-1.5 h-2 rounded-[1px] bg-slate-700/80" />
      ))}
    </div>
  );
};

export const DraggableDevice: React.FC<DraggableDeviceProps> = ({
  device,
  totalU,
  viewSide = 'front',
  isSelected = false,
  zh,
  isDragOverlay = false,
  onSelect,
}) => {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: device.id,
    data: { device },
  });
  const [showTooltip, setShowTooltip] = useState(false);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const rc = getNormalizedRoleColor(device.device_role, device.name, device.model);
  const startU = device.start_u ?? 1;
  const heightU = device.height_u ?? device.u_height ?? 1;
  const h = heightU * U_PX;
  const topPx = uToY(startU + heightU - 1, totalU);

  const style: React.CSSProperties = isDragOverlay
    ? { width: RACK_W - 4, height: h - 2 }
    : {
        position: 'absolute' as const,
        left: 2,
        right: 2,
        top: topPx + 1,
        height: h - 2,
        transform: CSS.Translate.toString(transform),
        transition: isDragging ? 'none' : 'top 0.2s ease, opacity 0.15s ease',
        opacity: isDragging ? 0.35 : 1,
        zIndex: isDragging ? 50 : showTooltip ? 40 : isSelected ? 20 : 10,
      };

  const endU = startU + heightU - 1;
  const roleName = deviceRoleLabel(device.device_role, zh ? 'zh' : 'en');
  const statusInfo = STATUS_LABEL[device.status] || { zh: device.status, en: device.status };
  const powerColor = device.status === 'active' ? '#4ade80' : device.status === 'planned' ? '#fbbf24' : '#ef4444';
  const portProfile = device.physical_port_profile;

  const handleMouseEnter = () => {
    hoverTimer.current = setTimeout(() => setShowTooltip(true), 260);
  };
  const handleMouseLeave = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    setShowTooltip(false);
  };

  return (
    <div
      ref={isDragOverlay ? undefined : setNodeRef}
      data-device-id={device.id}
      className={`flex items-center rounded-[4px] cursor-grab active:cursor-grabbing select-none overflow-visible group/dev transition-shadow ${
        isSelected ? 'ring-2 ring-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.45)]' : ''
      }`}
      style={{
        ...style,
        background: `linear-gradient(180deg, #253142 0%, #161f2d 55%, #111824 100%)`,
        border: isSelected ? '1px solid #22d3ee' : `1px solid ${rc.bg}88`,
        borderLeft: `4px solid ${rc.bg}`,
        color: '#f1f5f9',
        boxShadow: isDragOverlay
          ? `0 10px 30px rgba(0,0,0,0.55), 0 0 0 1.5px ${rc.bg}`
          : isSelected
            ? '0 0 12px rgba(34,211,238,0.38)'
            : 'inset 0 1px 0 rgba(255,255,255,0.08), 0 1px 2px rgba(0,0,0,0.45)',
      }}
      onMouseEnter={isDragOverlay ? undefined : handleMouseEnter}
      onMouseLeave={isDragOverlay ? undefined : handleMouseLeave}
      onClick={() => !isDragOverlay && onSelect?.(device.id)}
      {...(isDragOverlay ? {} : { ...listeners, ...attributes })}
    >
      {/* Left brushed-metal EIA mounting ear with M6 screw holes */}
      <div className="flex flex-col items-center justify-around self-stretch w-2.5 bg-slate-700/75 border-r border-slate-600/70 flex-shrink-0 py-0.5">
        <span className="w-1 h-1 rounded-full bg-slate-300/85" />
        <span className="w-1 h-1 rounded-full bg-slate-300/85" />
      </div>

      {/* Inner hardware faceplate strip */}
      <div className="flex-1 min-w-0 flex items-center gap-1.5 px-1.5 overflow-hidden">
        <div className="flex-shrink-0 opacity-35 group-hover/dev:opacity-80 transition-opacity">
          <GripVertical size={heightU >= 2 ? 13 : 10} />
        </div>

        <PowerLed status={device.status} size={heightU >= 2 ? 8 : 6} />

        <span
          className="flex items-center justify-center rounded-[3px] p-0.5 flex-shrink-0"
          style={{ background: `${rc.bg}26`, color: rc.bg }}
        >
          <DeviceIcon role={device.device_role} name={device.name} model={device.model} size={heightU >= 2 ? 13 : 11} />
        </span>

        <div className="flex-1 min-w-0 flex items-baseline gap-1.5 overflow-hidden">
          <span className={`font-bold truncate tracking-tight text-slate-100 ${heightU >= 2 ? 'text-[12px]' : 'text-[10.5px]'}`}>
            {device.name}
          </span>
          {(device.vendor || device.model) && (
            <span className="text-[8.5px] font-mono text-slate-400 truncate hidden sm:inline">
              {device.model || device.vendor}
            </span>
          )}
        </div>

        {/* Mini real-port strip (front) or dual PSU/fan strip (rear) */}
        <Device2DMiniFaceplate device={device} viewSide={viewSide} heightU={heightU} />

        {/* Rated wattage + U height */}
        <span className="text-[8.5px] font-mono text-amber-300/90 flex-shrink-0 hidden md:inline">
          {device.power_watts ?? 0}W
        </span>
        <span
          className="rounded px-1 py-0.2 text-[8.5px] font-mono font-bold flex-shrink-0"
          style={{ background: `${rc.bg}28`, color: '#e2e8f0' }}
        >
          {heightU}U
        </span>
      </div>

      {/* Right brushed-metal EIA mounting ear with M6 screw holes */}
      <div className="flex flex-col items-center justify-around self-stretch w-2.5 bg-slate-700/75 border-l border-slate-600/70 flex-shrink-0 py-0.5 rounded-r-[3px]">
        <span className="w-1 h-1 rounded-full bg-slate-300/85" />
        <span className="w-1 h-1 rounded-full bg-slate-300/85" />
      </div>

      {/* Rich Hover Tooltip */}
      {showTooltip && !isDragging && !isDragOverlay && (
        <div
          className="absolute left-full ml-3 top-0 z-[100] pointer-events-none"
          style={{ minWidth: 232 }}
        >
          <div className="rounded-lg p-3 text-[11px] leading-relaxed shadow-2xl border" style={{ background: '#0b1220', border: '1px solid #334155', color: '#e2e8f0' }}>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <p className="text-[13px] font-bold text-white truncate">{device.name}</p>
              <span className="rounded px-1.5 py-0.2 text-[9px] font-semibold" style={{ background: `${rc.bg}28`, color: rc.bg }}>
                {roleName}
              </span>
            </div>
            <div className="space-y-1 text-[10.5px]">
              <p>{zh ? '厂商 / 型号' : 'Model'}: <span className="font-medium text-cyan-300">{device.vendor} {device.model}</span></p>
              <p>{zh ? '安装 U 位' : 'Slot'}: <span className="font-mono font-semibold text-white">U{startU}{endU !== startU ? `–U${endU}` : ''} ({heightU}U)</span></p>
              <p>{zh ? '安装面' : 'Face'}: {device.position === 'rear' ? (zh ? '后面板' : 'Rear') : device.position === 'full_depth' ? (zh ? '前后通深' : 'Full Depth') : (zh ? '前面板' : 'Front')}</p>
              {portProfile && portProfile.total_ports > 0 && (
                <p>
                  {zh ? '物理接口' : 'Ports'}:{' '}
                  <span className="font-mono font-semibold text-emerald-400">{portProfile.up_ports} UP</span>
                  <span className="text-slate-400"> / {portProfile.total_ports} {zh ? '口' : 'ports'}</span>
                </p>
              )}
              {device.serial_number && <p>SN: <span className="font-mono text-[10px] text-slate-300">{device.serial_number}</span></p>}
              <p className="flex items-center gap-1.5 pt-1 border-t border-slate-800 mt-1">
                <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: powerColor, boxShadow: device.status === 'active' ? `0 0 6px ${powerColor}` : 'none' }} />
                <span style={{ color: powerColor }}>{zh ? statusInfo.zh : statusInfo.en}</span>
                <span className="text-slate-600 mx-1">|</span>
                <Zap size={11} className="text-amber-400 flex-shrink-0" />
                <span className="font-mono text-amber-300 font-semibold">{device.power_watts ?? 0} W</span>
              </p>
            </div>
            <div className="absolute left-0 top-3 -translate-x-full" style={{ width: 0, height: 0, borderTop: '6px solid transparent', borderBottom: '6px solid transparent', borderRight: '6px solid #334155' }} />
          </div>
        </div>
      )}
    </div>
  );
};

export default DraggableDevice;
