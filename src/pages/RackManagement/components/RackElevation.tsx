import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  DndContext, DragOverlay, PointerSensor, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent, type DragMoveEvent,
} from '@dnd-kit/core';
import { AlertTriangle, ChevronsUpDown, Plus, Zap } from 'lucide-react';
import { RackLayout, RackDevice } from '../types';
import { U_PX, RACK_W, LABEL_W } from '../constants';
import { yToU, hasConflict, getNormalizedRoleColor } from '../helpers';
import DroppableSlot from './DroppableSlot';
import DraggableDevice, { Device2DMiniFaceplate } from './DraggableDevice';
import PowerLed from './PowerLed';
import DeviceIcon from './DeviceIcon';

interface RackElevationProps {
  layout: RackLayout;
  viewSide: 'front' | 'rear';
  selectedDeviceId?: string | null;
  zh: boolean;
  collapseEmpty: boolean;
  rackScale?: number;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  onDeviceMove: (deviceId: string, newStartU: number) => Promise<void>;
  onDeviceSelect?: (deviceId: string) => void;
  onEmptySlotClick?: (uNumber: number) => void;
}

/**
 * Only confirmed/estimated U geometry may block an editable U slot. Unknown
 * and invalid rows stay visible in the review strip below the elevation but
 * must never be turned into occupancy or drag targets.
 */
export function isStandardElevationPlacement(device: RackDevice): boolean {
  const mountKind = (device.mount_kind || 'u_mount').toLowerCase();
  const placementStatus = (device.placement_status || '').toLowerCase();
  const heightU = device.height_u ?? device.u_height ?? 0;
  return mountKind === 'u_mount'
    && device.start_u != null
    && heightU >= 1
    && placementStatus !== 'unknown'
    && placementStatus !== 'invalid';
}

export const RackElevation: React.FC<RackElevationProps> = ({
  layout,
  viewSide,
  selectedDeviceId,
  zh,
  collapseEmpty,
  rackScale = 1,
  scrollContainerRef,
  onDeviceMove,
  onDeviceSelect,
  onEmptySlotClick,
}) => {
  const totalU = layout.total_u;
  const nonStandardDevices = useMemo(
    () => layout.devices.filter(d => {
      const mountKind = (d.mount_kind || 'u_mount').toLowerCase();
      const placementStatus = (d.placement_status || '').toLowerCase();
      const hasKnownUGeometry = mountKind === 'u_mount'
        && d.start_u != null
        && (d.height_u ?? d.u_height ?? 0) >= 1;
      if (mountKind !== 'u_mount') return true;
      if (!hasKnownUGeometry) return true;
      return placementStatus === 'unknown' || placementStatus === 'invalid';
    }),
    [layout.devices],
  );
  const sideDevices = useMemo(
    () => layout.devices.filter(d => {
      if (!isStandardElevationPlacement(d)) return false;
      return d.position === viewSide || d.position === 'full_depth';
    }),
    [layout.devices, viewSide],
  );

  // Compute occupied slots
  const occupiedUs = useMemo(() => {
    const s = new Set<number>();
    for (const d of sideDevices) {
      const startU = d.start_u ?? 1;
      const heightU = d.height_u ?? d.u_height ?? 1;
      for (let u = startU; u < startU + heightU; u++) s.add(u);
    }
    return s;
  }, [sideDevices]);

  type Segment =
    | { type: 'normal'; uStart: number; uEnd: number }
    | { type: 'collapsed'; uStart: number; uEnd: number; count: number };

  const [expandedSegments, setExpandedSegments] = useState<Set<string>>(new Set());

  const segments = useMemo<Segment[]>(() => {
    if (!collapseEmpty) return [{ type: 'normal', uStart: 1, uEnd: totalU }];
    const segs: Segment[] = [];
    let emptyRunStart: number | null = null;

    for (let u = totalU; u >= 1; u--) {
      if (!occupiedUs.has(u)) {
        if (emptyRunStart === null) emptyRunStart = u;
      } else {
        if (emptyRunStart !== null) {
          const runCount = emptyRunStart - u;
          if (runCount > 3) {
            segs.push({ type: 'collapsed', uStart: u + 1, uEnd: emptyRunStart, count: runCount });
          } else {
            segs.push({ type: 'normal', uStart: u + 1, uEnd: emptyRunStart });
          }
          emptyRunStart = null;
        }
        const dev = sideDevices.find(d => {
          const startU = d.start_u ?? 1;
          const heightU = d.height_u ?? d.u_height ?? 1;
          return u >= startU && u < startU + heightU;
        });
        if (dev) {
          const devStartU = dev.start_u ?? 1;
          const devEndU = devStartU + (dev.height_u ?? dev.u_height ?? 1) - 1;
          if (segs.length > 0 && segs[segs.length - 1].type === 'normal') {
            segs[segs.length - 1].uStart = Math.min(segs[segs.length - 1].uStart, devStartU);
          } else {
            segs.push({ type: 'normal', uStart: devStartU, uEnd: devEndU });
          }
          u = devStartU;
        } else {
          if (segs.length > 0 && segs[segs.length - 1].type === 'normal') {
            segs[segs.length - 1].uStart = u;
          } else {
            segs.push({ type: 'normal', uStart: u, uEnd: u });
          }
        }
      }
    }
    if (emptyRunStart !== null) {
      const runCount = emptyRunStart;
      if (runCount > 3) {
        segs.push({ type: 'collapsed', uStart: 1, uEnd: emptyRunStart, count: runCount });
      } else {
        segs.push({ type: 'normal', uStart: 1, uEnd: emptyRunStart });
      }
    }
    return segs;
  }, [collapseEmpty, occupiedUs, sideDevices, totalU]);

  const finalSegments = useMemo<Segment[]>(() => {
    return segments.map(seg => {
      if (seg.type === 'collapsed' && expandedSegments.has(`${seg.uStart}-${seg.uEnd}`)) {
        return { type: 'normal', uStart: seg.uStart, uEnd: seg.uEnd };
      }
      return seg;
    });
  }, [segments, expandedSegments]);

  const toggleSegment = useCallback((key: string) => {
    setExpandedSegments(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const [activeDevice, setActiveDevice] = useState<RackDevice | null>(null);
  const [ghostU, setGhostU] = useState<number | null>(null);
  const [hoveredEmptyU, setHoveredEmptyU] = useState<number | null>(null);
  const rackBodyRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef<number | null>(null);
  const scrollSpeedRef = useRef(0);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const stopAutoScroll = useCallback(() => {
    scrollSpeedRef.current = 0;
    if (autoScrollRef.current !== null) {
      cancelAnimationFrame(autoScrollRef.current);
      autoScrollRef.current = null;
    }
  }, []);

  const startAutoScroll = useCallback((direction: 'up' | 'down', intensity: number) => {
    const newSpeed = direction === 'up' ? -intensity : intensity;
    scrollSpeedRef.current = newSpeed;
    if (autoScrollRef.current === null && scrollContainerRef?.current) {
      const tick = () => {
        if (!scrollContainerRef?.current || scrollSpeedRef.current === 0) {
          autoScrollRef.current = null;
          return;
        }
        scrollContainerRef.current.scrollTop += scrollSpeedRef.current;
        autoScrollRef.current = requestAnimationFrame(tick);
      };
      autoScrollRef.current = requestAnimationFrame(tick);
    }
  }, [scrollContainerRef]);

  useEffect(() => () => stopAutoScroll(), [stopAutoScroll]);

  // Smoothly scroll selected device into view inside the 2D container
  useEffect(() => {
    if (!selectedDeviceId || !rackBodyRef.current) return;
    const el = rackBodyRef.current.querySelector(`[data-device-id="${CSS.escape(selectedDeviceId)}"]`) as HTMLElement | null;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [selectedDeviceId]);

  const ghostConflict = useMemo(() => {
    if (!activeDevice || ghostU === null) return true;
    return hasConflict(ghostU, activeDevice.height_u ?? activeDevice.u_height ?? 1, totalU, sideDevices, activeDevice.id);
  }, [activeDevice, ghostU, totalU, sideDevices]);

  const handleDragStart = useCallback((e: DragStartEvent) => {
    const dev = e.active.data.current?.device as RackDevice | undefined;
    if (dev) {
      setActiveDevice(dev);
      setGhostU(dev.start_u ?? 1);
    }
  }, []);

  const handleDragMove = useCallback((e: DragMoveEvent) => {
    if (!activeDevice || !rackBodyRef.current) return;
    const rackRect = rackBodyRef.current.getBoundingClientRect();
    const currentScale = (totalU * U_PX > 0 ? rackRect.height / (totalU * U_PX) : rackScale) || 1;
    const pointerY = (e.activatorEvent as PointerEvent).clientY + (e.delta.y ?? 0);

    if (scrollContainerRef?.current) {
      const containerRect = scrollContainerRef.current.getBoundingClientRect();
      const edgeThreshold = 44;
      if (pointerY < containerRect.top + edgeThreshold) {
        const intensity = Math.max(2, Math.min(14, (containerRect.top + edgeThreshold - pointerY) / 3));
        startAutoScroll('up', intensity);
      } else if (pointerY > containerRect.bottom - edgeThreshold) {
        const intensity = Math.max(2, Math.min(14, (pointerY - (containerRect.bottom - edgeThreshold)) / 3));
        startAutoScroll('down', intensity);
      } else {
        stopAutoScroll();
      }
    }

    const relY = (pointerY - rackRect.top) / currentScale;
    const topU = yToU(relY, totalU);
    const deviceHeightU = activeDevice.height_u ?? activeDevice.u_height ?? 1;
    const startU = topU - deviceHeightU + 1;
    const clamped = Math.max(1, Math.min(totalU - deviceHeightU + 1, startU));
    setGhostU(clamped);
  }, [activeDevice, totalU, rackScale, scrollContainerRef, startAutoScroll, stopAutoScroll]);

  const handleDragEnd = useCallback(async (_e: DragEndEvent) => {
    stopAutoScroll();
    const activeHeightU = activeDevice?.height_u ?? activeDevice?.u_height ?? 1;
    if (activeDevice && ghostU !== null && !hasConflict(ghostU, activeHeightU, totalU, sideDevices, activeDevice.id)) {
      if (ghostU !== (activeDevice.start_u ?? 1)) {
        await onDeviceMove(activeDevice.id, ghostU);
      }
    }
    setActiveDevice(null);
    setGhostU(null);
  }, [activeDevice, ghostU, totalU, sideDevices, onDeviceMove, stopAutoScroll]);

  const handleDragCancel = useCallback(() => {
    stopAutoScroll();
    setActiveDevice(null);
    setGhostU(null);
  }, [stopAutoScroll]);

  const ghostUSet = useMemo(() => {
    if (!activeDevice || ghostU === null) return new Set<number>();
    const s = new Set<number>();
    const deviceHeightU = activeDevice.height_u ?? activeDevice.u_height ?? 1;
    for (let u = ghostU; u < ghostU + deviceHeightU; u++) s.add(u);
    return s;
  }, [activeDevice, ghostU]);

  const COLLAPSED_PH = 34;
  const collapsedTotalH = useMemo(() => {
    if (!collapseEmpty) return totalU * U_PX;
    let h = 0;
    for (const seg of finalSegments) {
      if (seg.type === 'collapsed') h += COLLAPSED_PH;
      else h += (seg.uEnd - seg.uStart + 1) * U_PX;
    }
    return h;
  }, [collapseEmpty, finalSegments, totalU]);

  const uUtilPct = Math.round(((layout.total_used || 0) / Math.max(1, totalU)) * 100);
  const powerUsed = (layout as any).power_used_watts ?? layout.devices.reduce((s, d) => s + (d.power_watts || 0), 0);
  const outerFrameW = RACK_W + LABEL_W * 2;

  const renderURuler = (side: 'left' | 'right') => {
    const renderCell = (u: number, key: string) => {
      const isOccupied = occupiedUs.has(u);
      const isHovered = hoveredEmptyU === u;
      const isFiveMark = u % 5 === 0 || u === 1 || u === totalU;
      return (
        <div
          key={key}
          className={`flex items-center justify-center text-[9px] font-mono tabular-nums transition-colors ${
            side === 'left' ? 'border-r border-slate-700/70' : 'border-l border-slate-700/70'
          }`}
          style={{
            height: U_PX,
            color: isHovered ? '#38bdf8' : isOccupied ? '#cbd5e1' : isFiveMark ? '#64748b' : '#475569',
            fontWeight: isOccupied || isHovered ? 700 : 500,
            background: isHovered
              ? 'rgba(14,165,233,0.14)'
              : isOccupied
                ? 'rgba(30,41,59,0.92)'
                : 'rgba(15,23,42,0.85)',
          }}
        >
          {u}
        </div>
      );
    };

    if (!collapseEmpty) {
      return (
        <div className="flex-shrink-0 flex flex-col" style={{ width: LABEL_W }}>
          {Array.from({ length: totalU }, (_, i) => renderCell(totalU - i, `${side}-${totalU - i}`))}
        </div>
      );
    }

    return (
      <div className="flex-shrink-0 flex flex-col" style={{ width: LABEL_W }}>
        {finalSegments.map((seg, si) => {
          if (seg.type === 'collapsed') {
            return (
              <div
                key={`${side}-c-${si}`}
                className={`flex items-center justify-center text-[8px] font-mono text-slate-600 ${
                  side === 'left' ? 'border-r border-slate-700/70' : 'border-l border-slate-700/70'
                }`}
                style={{ height: COLLAPSED_PH, background: 'rgba(15,23,42,0.75)' }}
              >
                ···
              </div>
            );
          }
          return Array.from({ length: seg.uEnd - seg.uStart + 1 }, (_, j) => {
            const u = seg.uEnd - j;
            return renderCell(u, `${side}-${si}-${u}`);
          });
        })}
      </div>
    );
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragMove={handleDragMove}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="relative mx-auto w-fit select-none">
        {/* Physical 19-Inch Cabinet Top Crown Header */}
        <div
          className="rounded-t-xl border-x-2 border-t-2 border-slate-700 bg-gradient-to-b from-slate-800 via-slate-900 to-slate-950 px-3 py-2 text-slate-200 shadow-lg"
          style={{ width: outerFrameW }}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
              <span className="text-xs font-bold tracking-wide text-white truncate">{layout.name}</span>
              <span className="rounded bg-slate-800 border border-slate-700 px-1.5 py-0.2 text-[9px] font-semibold text-cyan-300">
                {viewSide === 'front' ? (zh ? '前面板' : 'FRONT') : (zh ? '后面板' : 'REAR')}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[9.5px] font-mono">
              <span className="text-slate-300">{layout.total_used}/{totalU}U ({uUtilPct}%)</span>
              <span className="text-amber-300 flex items-center gap-0.5 font-semibold">
                <Zap size={9} />{powerUsed}W
              </span>
            </div>
          </div>
          {/* Compact U-capacity progress bar */}
          <div className="mt-1.5 h-1 w-full rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-300"
              style={{
                width: `${Math.min(100, uUtilPct)}%`,
                background: uUtilPct > 85 ? '#ef4444' : uUtilPct > 65 ? '#f59e0b' : '#06b6d4',
              }}
            />
          </div>
        </div>

        {/* Main 42U Cabinet Column with Brushed EIA-310 Left/Right Rails */}
        <div
          className="flex border-x-2 border-slate-700 bg-slate-950 shadow-2xl"
          style={{ width: outerFrameW }}
        >
          {renderURuler('left')}

          {/* Rack interior bay */}
          {!collapseEmpty ? (
            <div
              ref={rackBodyRef}
              className="relative overflow-visible"
              style={{
                width: RACK_W,
                height: totalU * U_PX,
                background: 'linear-gradient(180deg, #0d1422 0%, #090e18 100%)',
              }}
            >
              {Array.from({ length: totalU }, (_, i) => {
                const u = totalU - i;
                const isGhost = ghostUSet.has(u);
                const isOccupied = occupiedUs.has(u);
                const isHovered = hoveredEmptyU === u && !isOccupied && !isGhost;
                return (
                  <div
                    key={u}
                    className={`absolute ${!isOccupied && !isGhost ? 'cursor-pointer transition-colors' : ''}`}
                    style={{
                      left: 0,
                      right: 0,
                      top: i * U_PX,
                      height: U_PX,
                      borderBottom: u % 5 === 1 ? '1px solid rgba(51,65,85,0.65)' : '1px solid rgba(30,41,59,0.55)',
                      background: isHovered ? 'rgba(14,165,233,0.14)' : 'transparent',
                    }}
                    onMouseEnter={() => { if (!isOccupied && !isGhost) setHoveredEmptyU(u); }}
                    onMouseLeave={() => { if (hoveredEmptyU === u) setHoveredEmptyU(null); }}
                    onClick={() => {
                      if (!isOccupied && !isGhost && onEmptySlotClick) {
                        onEmptySlotClick(u);
                      }
                    }}
                    title={!isOccupied && !isGhost ? (zh ? `点击在 U${u} 快速上架设备` : `Click to mount device at U${u}`) : undefined}
                  >
                    <DroppableSlot
                      uNumber={u}
                      isGhostHere={isGhost}
                      ghostConflict={ghostConflict}
                      ghostHeight={activeDevice?.height_u ?? activeDevice?.u_height ?? 1}
                      ghostIsStart={ghostU === u}
                    />
                    {!isOccupied && !isGhost && (
                      <span className="absolute inset-0 flex items-center justify-center gap-1 text-[8.5px] font-mono pointer-events-none transition-colors">
                        {isHovered ? (
                          <span className="inline-flex items-center gap-1 rounded bg-cyan-500/20 border border-cyan-400/50 px-1.5 py-0.2 text-[9px] font-semibold text-cyan-300">
                            <Plus size={9} /> {zh ? `点击在 U${u} 上架设备` : `Mount at U${u}`}
                          </span>
                        ) : (
                          <span className="text-slate-700/90">U{u}</span>
                        )}
                      </span>
                    )}
                  </div>
                );
              })}

              {sideDevices.map(d => (
                <DraggableDevice
                  key={d.id}
                  device={d}
                  totalU={totalU}
                  viewSide={viewSide}
                  isSelected={d.id === selectedDeviceId}
                  zh={zh}
                  onSelect={onDeviceSelect}
                />
              ))}
            </div>
          ) : (
            <div
              ref={rackBodyRef}
              className="relative overflow-hidden"
              style={{
                width: RACK_W,
                height: collapsedTotalH,
                background: 'linear-gradient(180deg, #0d1422 0%, #090e18 100%)',
              }}
            >
              {(() => {
                let yOffset = 0;
                return finalSegments.map((seg, si) => {
                  if (seg.type === 'collapsed') {
                    const y0 = yOffset;
                    yOffset += COLLAPSED_PH;
                    const segKey = `${seg.uStart}-${seg.uEnd}`;
                    return (
                      <div
                        key={si}
                        className="absolute left-0 right-0 flex items-center justify-center cursor-pointer bg-slate-900/80 hover:bg-cyan-950/40 transition-colors"
                        style={{ top: y0, height: COLLAPSED_PH, borderTop: '1px dashed #334155', borderBottom: '1px dashed #334155' }}
                        onClick={() => toggleSegment(segKey)}
                      >
                        <span className="text-[10px] font-medium text-slate-400 hover:text-cyan-300 flex items-center gap-1.5">
                          <ChevronsUpDown size={12} className="text-cyan-400" />
                          {zh ? `U${seg.uStart}–U${seg.uEnd} · ${seg.count}U 空闲（点击展开）` : `U${seg.uStart}–U${seg.uEnd} · ${seg.count}U free (expand)`}
                        </span>
                      </div>
                    );
                  }
                  const segHeight = (seg.uEnd - seg.uStart + 1) * U_PX;
                  const y0 = yOffset;
                  yOffset += segHeight;
                  const segDevices = sideDevices.filter(d => {
                    const startU = d.start_u ?? 1;
                    const heightU = d.height_u ?? d.u_height ?? 1;
                    const dTop = startU + heightU - 1;
                    return startU <= seg.uEnd && dTop >= seg.uStart;
                  });
                  return (
                    <div key={si} className="absolute left-0 right-0" style={{ top: y0, height: segHeight }}>
                      {Array.from({ length: seg.uEnd - seg.uStart + 1 }, (_, j) => {
                        const u = seg.uEnd - j;
                        const localY = j * U_PX;
                        return (
                          <div
                            key={u}
                            className="absolute left-0 right-0"
                            style={{ top: localY, height: U_PX, borderBottom: '1px solid rgba(30,41,59,0.55)' }}
                          >
                            {!sideDevices.some(d => {
                              const startU = d.start_u ?? 1;
                              const heightU = d.height_u ?? d.u_height ?? 1;
                              return u >= startU && u < startU + heightU;
                            }) && (
                              <span className="absolute inset-0 flex items-center justify-center text-[8px] font-mono text-slate-700 pointer-events-none">
                                U{u}
                              </span>
                            )}
                          </div>
                        );
                      })}
                      {segDevices.map(d => {
                        const rc = getNormalizedRoleColor(d.device_role, d.name, d.model);
                        const startU = d.start_u ?? 1;
                        const heightU = d.height_u ?? d.u_height ?? 1;
                        const devH = heightU * U_PX;
                        const devTop = (seg.uEnd - (startU + heightU - 1)) * U_PX;
                        const isSelected = d.id === selectedDeviceId;
                        return (
                          <div
                            key={d.id}
                            data-device-id={d.id}
                            onClick={() => onDeviceSelect?.(d.id)}
                            className={`absolute left-0.5 right-0.5 flex items-center rounded-[4px] select-none overflow-hidden cursor-pointer ${
                              isSelected ? 'ring-2 ring-cyan-400' : ''
                            }`}
                            style={{
                              top: devTop + 1,
                              height: devH - 2,
                              background: 'linear-gradient(180deg, #253142 0%, #161f2d 55%, #111824 100%)',
                              border: isSelected ? '1px solid #22d3ee' : `1px solid ${rc.bg}88`,
                              borderLeft: `4px solid ${rc.bg}`,
                              color: '#f1f5f9',
                              zIndex: isSelected ? 20 : 10,
                            }}
                          >
                            <div className="flex flex-col items-center justify-around self-stretch w-2 bg-slate-700/75 border-r border-slate-600/70 flex-shrink-0 py-0.5">
                              <span className="w-1 h-1 rounded-full bg-slate-300/80" />
                              <span className="w-1 h-1 rounded-full bg-slate-300/80" />
                            </div>
                            <div className="flex-1 min-w-0 flex items-center gap-1.5 px-1.5 overflow-hidden">
                              <PowerLed status={d.status} size={heightU >= 2 ? 8 : 6} />
                              <span className="flex items-center justify-center rounded-[3px] p-0.5 flex-shrink-0" style={{ background: `${rc.bg}26`, color: rc.bg }}>
                                <DeviceIcon role={d.device_role} name={d.name} model={d.model} size={heightU >= 2 ? 13 : 11} />
                              </span>
                              <span className={`font-bold truncate ${heightU >= 2 ? 'text-[12px]' : 'text-[10.5px]'}`}>{d.name}</span>
                              {d.model && <span className="text-[8.5px] font-mono text-slate-400 truncate hidden sm:inline">{d.model}</span>}
                              <div className="ml-auto flex items-center gap-1.5 flex-shrink-0">
                                <Device2DMiniFaceplate device={d} viewSide={viewSide} heightU={heightU} />
                                <span className="rounded px-1 text-[8.5px] font-mono font-bold" style={{ background: `${rc.bg}28` }}>{heightU}U</span>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                });
              })()}
            </div>
          )}

          {renderURuler('right')}
        </div>

        {/* Physical Cabinet Bottom Steel Plinth Base & Leveling Feet */}
        <div style={{ width: outerFrameW }}>
          <div className="h-3.5 rounded-b-lg border-x-2 border-b-2 border-slate-700 bg-gradient-to-b from-slate-800 to-slate-950 flex items-center justify-between px-4">
            <span className="h-1 w-10 rounded-full bg-slate-700" />
            <span className="text-[8px] font-mono text-slate-500">EIA-310 · {totalU}U</span>
            <span className="h-1 w-10 rounded-full bg-slate-700" />
          </div>
          <div className="flex items-center justify-between px-6">
            <div className="h-2 w-7 rounded-b bg-slate-600 border-x border-b border-slate-500" />
            <div className="h-2 w-7 rounded-b bg-slate-600 border-x border-b border-slate-500" />
          </div>
        </div>

        {nonStandardDevices.length > 0 && (
          <div
            className="mt-3 rounded-lg border p-2"
            style={{ width: outerFrameW, borderColor: 'rgba(245,158,11,0.35)', background: 'rgba(245,158,11,0.06)' }}
          >
            <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold text-amber-500">
              <AlertTriangle size={12} />
              {zh ? '非标准位置 / 待确认设备（不占用标准 U 位）' : 'Non-standard / pending placements (excluded from standard U occupancy)'}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {nonStandardDevices.map(device => {
                const mountKind = (device.mount_kind || 'u_mount').toLowerCase();
                const position = device.position || 'unknown';
                const status = (device.placement_status || '').toLowerCase();
                const detail = status === 'invalid'
                  ? (zh ? '数据异常' : 'Invalid')
                  : mountKind === 'u_mount'
                    ? (zh ? 'U 位待确认' : 'U position pending')
                    : `${mountKind} · ${position}`;
                return (
                  <button
                    key={device.id}
                    type="button"
                    onClick={() => onDeviceSelect?.(device.id)}
                    className="inline-flex max-w-full items-center gap-1 rounded border px-2 py-1 text-left text-[10px] transition-colors hover:border-amber-400 hover:bg-amber-500/10"
                    style={{ borderColor: 'rgba(245,158,11,0.28)', color: 'var(--body-text)' }}
                    title={device.location_note || detail}
                  >
                    <span className="truncate font-medium">{device.name}</span>
                    <span className="shrink-0 text-[9px] text-amber-500">{detail}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <DragOverlay dropAnimation={null}>
        {activeDevice ? (
          <DraggableDevice device={activeDevice} totalU={totalU} viewSide={viewSide} zh={zh} isDragOverlay />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
};

export default RackElevation;
