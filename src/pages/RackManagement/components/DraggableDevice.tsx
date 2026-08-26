import React, { useState, useRef } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Zap } from 'lucide-react';
import { RackDevice } from '../types';
import { U_PX, RACK_W, STATUS_LABEL } from '../constants';
import { getNormalizedRoleColor, uToY } from '../helpers';
import PowerLed from './PowerLed';
import DeviceIcon from './DeviceIcon';

interface DraggableDeviceProps {
  device: RackDevice;
  totalU: number;
  zh: boolean;
  isDragOverlay?: boolean;
  onSelect?: (deviceId: string) => void;
}

export const DraggableDevice: React.FC<DraggableDeviceProps> = ({
  device,
  totalU,
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
  const h = device.u_height * U_PX;
  const topPx = uToY(device.start_u + device.u_height - 1, totalU);

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
        zIndex: isDragging ? 50 : showTooltip ? 40 : 10,
      };

  const endU = device.start_u + device.u_height - 1;
  const roleName = zh ? rc.labelZh : rc.label;
  const statusInfo = STATUS_LABEL[device.status] || { zh: device.status, en: device.status };
  const powerColor = device.status === 'active' ? '#4ade80' : device.status === 'planned' ? '#fbbf24' : '#ef4444';

  const handleMouseEnter = () => {
    hoverTimer.current = setTimeout(() => setShowTooltip(true), 300);
  };
  const handleMouseLeave = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    setShowTooltip(false);
  };

  return (
    <div
      ref={isDragOverlay ? undefined : setNodeRef}
      className="flex items-center gap-1.5 rounded-[4px] cursor-grab active:cursor-grabbing select-none overflow-visible group/dev"
      style={{
        ...style,
        background: `linear-gradient(135deg, ${rc.bg}, ${rc.bg}cc)`,
        border: `1.5px solid ${rc.border}`,
        color: rc.text,
        boxShadow: isDragOverlay
          ? `0 8px 30px ${rc.bg}60, 0 2px 8px rgba(0,0,0,0.4)`
          : `0 1px 3px ${rc.bg}30`,
      }}
      onMouseEnter={isDragOverlay ? undefined : handleMouseEnter}
      onMouseLeave={isDragOverlay ? undefined : handleMouseLeave}
      onClick={() => !isDragOverlay && onSelect?.(device.id)}
      {...(isDragOverlay ? {} : { ...listeners, ...attributes })}
    >
      {/* Grip handle */}
      <div className="flex-shrink-0 pl-1 opacity-40">
        <GripVertical size={device.u_height >= 2 ? 14 : 11} />
      </div>

      {/* Power LED */}
      <PowerLed status={device.status} size={device.u_height >= 2 ? 8 : 6} />

      {/* Icon */}
      <DeviceIcon role={device.device_role} size={device.u_height >= 2 ? 15 : 12} />

      {/* Text */}
      <div className="flex-1 min-w-0 flex items-center gap-1.5 overflow-hidden">
        <span className={`font-bold truncate ${device.u_height >= 2 ? 'text-[12px]' : 'text-[10px]'}`}>
          {device.name}
        </span>
        {device.u_height >= 2 && (
          <span className="text-[9px] opacity-60 truncate hidden sm:inline">
            {device.vendor} {device.model}
          </span>
        )}
      </div>

      {/* U badge */}
      <span className="text-[9px] font-mono opacity-60 pr-1.5 flex-shrink-0">
        {device.u_height}U
      </span>

      {/* Hover Tooltip */}
      {showTooltip && !isDragging && !isDragOverlay && (
        <div
          className="absolute left-full ml-3 top-0 z-[100] pointer-events-none"
          style={{ minWidth: 220 }}
        >
          <div className="rounded-lg p-3 text-[11px] leading-relaxed shadow-xl border" style={{ background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0' }}>
            <p className="text-[13px] font-bold mb-1.5" style={{ color: '#f1f5f9' }}>{device.name}</p>
            <div className="space-y-1">
              <p>{zh ? '型号' : 'Model'}: <span className="font-medium text-cyan-300">{device.vendor} {device.model}</span></p>
              <p>{zh ? '角色' : 'Role'}: <span className="font-medium" style={{ color: rc.bg }}>{roleName}</span></p>
              <p>U{zh ? '位' : ''}: <span className="font-mono font-medium">U{device.start_u}{endU !== device.start_u ? `–U${endU}` : ''} ({device.u_height}U)</span></p>
              <p>{zh ? '面板' : 'Panel'}: {device.position === 'front' ? (zh ? '前面板' : 'Front') : (zh ? '后面板' : 'Rear')}</p>
              <p>{zh ? '状态' : 'Status'}: {zh ? statusInfo.zh : statusInfo.en}</p>
              {device.serial_number && <p>SN: <span className="font-mono text-[10px]">{device.serial_number}</span></p>}
              <p className="flex items-center gap-1.5 mt-1">
                {zh ? '电源' : 'Power'}: <span className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: powerColor, boxShadow: device.status === 'active' ? `0 0 6px ${powerColor}` : 'none' }} />
                <span style={{ color: powerColor }}>{zh ? statusInfo.zh : statusInfo.en}</span>
                <span className="text-slate-500 mx-1">|</span>
                <Zap size={11} className="text-amber-400 flex-shrink-0" />
                <span className="font-mono text-amber-300 font-semibold">{device.power_watts ?? 0} W</span>
              </p>
            </div>
            {/* Arrow */}
            <div className="absolute left-0 top-3 -translate-x-full" style={{ width: 0, height: 0, borderTop: '6px solid transparent', borderBottom: '6px solid transparent', borderRight: '6px solid #334155' }} />
          </div>
        </div>
      )}
    </div>
  );
};

export default DraggableDevice;
