import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  DndContext, DragOverlay, PointerSensor, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent, type DragMoveEvent,
} from '@dnd-kit/core';
import { AlertTriangle, ChevronsUpDown } from 'lucide-react';
import { RackLayout, RackDevice } from '../types';
import { U_PX, RACK_W, LABEL_W } from '../constants';
import { yToU, hasConflict, getNormalizedRoleColor } from '../helpers';
import DroppableSlot from './DroppableSlot';
import DraggableDevice from './DraggableDevice';
import PowerLed from './PowerLed';
import DeviceIcon from './DeviceIcon';

interface RackElevationProps {
  layout: RackLayout;
  viewSide: 'front' | 'rear';
  zh: boolean;
  collapseEmpty: boolean;
  rackScale?: number;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  onDeviceMove: (deviceId: string, newStartU: number) => Promise<void>;
  onDeviceSelect?: (deviceId: string) => void;
  onEmptySlotClick?: (uNumber: number) => void;
}

/**
 * Only confirmed/estimated U geometry may block an editable U slot.  Unknown
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
      // Keep non-U, unknown and invalid rows visible without inventing a U1
      // rectangle. They are presented as clickable placement records below
      // the elevation and remain available to the inspector.
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
          const devHeightU = dev.height_u ?? dev.u_height ?? 1;
          const devTop = devStartU + devHeightU - 1;
          const devBot = devStartU;
          segs.push({ type: 'normal', uStart: devBot, uEnd: devTop });
          u = devBot;
        } else {
          segs.push({ type: 'normal', uStart: u, uEnd: u });
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
  }, [collapseEmpty, totalU, occupiedUs, sideDevices]);

  const finalSegments = useMemo<Segment[]>(() => {
    if (!collapseEmpty) return segments;
    return segments.map(seg => {
      if (seg.type === 'collapsed' && expandedSegments.has(`${seg.uStart}-${seg.uEnd}`)) {
        return { type: 'normal' as const, uStart: seg.uStart, uEnd: seg.uEnd };
      }
      return seg;
    });
  }, [segments, expandedSegments, collapseEmpty]);

  const toggleSegment = useCallback((key: string) => {
    setExpandedSegments(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!collapseEmpty) setExpandedSegments(new Set());
  }, [collapseEmpty]);

  const [activeDevice, setActiveDevice] = useState<RackDevice | null>(null);
  const [ghostU, setGhostU] = useState<number | null>(null);
  const rackBodyRef = useRef<HTMLDivElement>(null);
  const scrollAnimRef = useRef<number | null>(null);

  const stopAutoScroll = useCallback(() => {
    if (scrollAnimRef.current !== null) {
      cancelAnimationFrame(scrollAnimRef.current);
      scrollAnimRef.current = null;
    }
  }, []);

  const startAutoScroll = useCallback((direction: 'up' | 'down', speed: number) => {
    stopAutoScroll();
    const scrollContainer = scrollContainerRef?.current;
    if (!scrollContainer) return;

    const step = () => {
      scrollContainer.scrollTop += direction === 'down' ? speed : -speed;
      scrollAnimRef.current = requestAnimationFrame(step);
    };
    scrollAnimRef.current = requestAnimationFrame(step);
  }, [scrollContainerRef, stopAutoScroll]);

  // Clean up auto scroll on unmount
  useEffect(() => {
    return () => {
      if (scrollAnimRef.current !== null) {
        cancelAnimationFrame(scrollAnimRef.current);
      }
    };
  }, []);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

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
    
    // Auto-scroll when dragging near container boundaries
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

    // Scale-normalized relative Y position inside rack
    const relY = (pointerY - rackRect.top) / currentScale;
    const topU = yToU(relY, totalU);
    const deviceHeightU = activeDevice.height_u ?? activeDevice.u_height ?? 1;
    const startU = topU - deviceHeightU + 1;
    const clamped = Math.max(1, Math.min(totalU - deviceHeightU + 1, startU));
    setGhostU(clamped);
  }, [activeDevice, totalU, rackScale, scrollContainerRef, startAutoScroll, stopAutoScroll]);

  const handleDragEnd = useCallback(async (e: DragEndEvent) => {
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

  const COLLAPSED_PH = 32;
  const collapsedTotalH = useMemo(() => {
    if (!collapseEmpty) return totalU * U_PX;
    let h = 0;
    for (const seg of finalSegments) {
      if (seg.type === 'collapsed') h += COLLAPSED_PH;
      else h += (seg.uEnd - seg.uStart + 1) * U_PX;
    }
    return h;
  }, [collapseEmpty, finalSegments, totalU]);

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragMove={handleDragMove}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="relative select-none">
        <div className="flex">
          {/* Left U labels */}
          {!collapseEmpty ? (
            <div className="flex-shrink-0 flex flex-col" style={{ width: LABEL_W }}>
              {Array.from({ length: totalU }, (_, i) => {
                const u = totalU - i;
                return (
                  <div key={u} className="flex items-center justify-center text-[9px] font-mono tabular-nums" style={{ height: U_PX, color: '#475569' }}>
                    {u}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex-shrink-0 flex flex-col" style={{ width: LABEL_W }}>
              {finalSegments.map((seg, si) => {
                if (seg.type === 'collapsed') {
                  return <div key={si} style={{ height: COLLAPSED_PH }} />;
                }
                return Array.from({ length: seg.uEnd - seg.uStart + 1 }, (_, j) => {
                  const u = seg.uEnd - j;
                  return (
                    <div key={`${si}-${u}`} className="flex items-center justify-center text-[9px] font-mono tabular-nums" style={{ height: U_PX, color: '#475569' }}>
                      {u}
                    </div>
                  );
                });
              })}
            </div>
          )}

          {/* Rack body */}
          {!collapseEmpty ? (
            <div
              ref={rackBodyRef}
              className="relative rounded-lg overflow-hidden"
              style={{
                width: RACK_W,
                height: totalU * U_PX,
                border: '2px solid #334155',
                background: 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)',
              }}
            >
              {Array.from({ length: totalU }, (_, i) => {
                const u = totalU - i;
                const isGhost = ghostUSet.has(u);
                return (
                  <div
                    key={u}
                    className={`absolute ${!occupiedUs.has(u) && !isGhost ? 'cursor-pointer hover:bg-cyan-500/10 transition-colors' : ''}`}
                    style={{ left: 0, right: 0, top: i * U_PX, height: U_PX, borderBottom: '1px solid rgba(30,41,59,0.5)' }}
                    onClick={() => {
                      if (!occupiedUs.has(u) && !isGhost && onEmptySlotClick) {
                        onEmptySlotClick(u);
                      }
                    }}
                    title={!occupiedUs.has(u) && !isGhost ? (zh ? `点击在 U${u} 快速安装设备` : `Click to install device at U${u}`) : undefined}
                  >
                    <DroppableSlot
                      uNumber={u}
                      isGhostHere={isGhost}
                      ghostConflict={ghostConflict}
                      ghostHeight={activeDevice?.height_u ?? activeDevice?.u_height ?? 1}
                      ghostIsStart={ghostU === u}
                    />
                    {!occupiedUs.has(u) && !isGhost && (
                      <span className="absolute inset-0 flex items-center justify-center text-[8px] font-mono text-slate-700 hover:text-cyan-400 pointer-events-none transition-colors">
                        U{u}
                      </span>
                    )}
                  </div>
                );
              })}

              {sideDevices.map(d => (
                <DraggableDevice key={d.id} device={d} totalU={totalU} zh={zh} onSelect={onDeviceSelect} />
              ))}
            </div>
          ) : (
            <div
              ref={rackBodyRef}
              className="relative rounded-lg overflow-hidden"
              style={{
                width: RACK_W,
                height: collapsedTotalH,
                border: '2px solid #334155',
                background: 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)',
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
                        className="absolute left-0 right-0 flex items-center justify-center cursor-pointer hover:bg-slate-800/50 transition-colors"
                        style={{ top: y0, height: COLLAPSED_PH, borderTop: '1px dashed #334155', borderBottom: '1px dashed #334155' }}
                        onClick={() => toggleSegment(segKey)}
                      >
                        <span className="text-[10px] text-slate-500 flex items-center gap-1.5">
                          <ChevronsUpDown size={12} />
                          {zh ? `🔽 包含 ${seg.count}U 可用空间` : `🔽 ${seg.count}U empty space`}
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
                            style={{ top: localY, height: U_PX, borderBottom: '1px solid rgba(30,41,59,0.5)' }}
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
                        return (
                          <div
                            key={d.id}
                            className="absolute left-0.5 right-0.5 flex items-center gap-1.5 rounded-[4px] select-none overflow-hidden"
                            style={{
                              top: devTop + 1,
                              height: devH - 2,
                              background: `linear-gradient(135deg, ${rc.bg}, ${rc.bg}cc)`,
                              border: `1.5px solid ${rc.border}`,
                              color: rc.text,
                              boxShadow: `0 1px 3px ${rc.bg}30`,
                              zIndex: 10,
                            }}
                          >
                            <PowerLed status={d.status} size={heightU >= 2 ? 8 : 6} />
                            <DeviceIcon role={d.device_role} name={d.name} model={d.model} size={heightU >= 2 ? 15 : 12} />
                            <span className={`font-bold truncate ${heightU >= 2 ? 'text-[12px]' : 'text-[10px]'}`}>{d.name}</span>
                            <span className="text-[9px] font-mono opacity-60 pr-1.5 flex-shrink-0 ml-auto">{heightU}U</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                });
              })()}
            </div>
          )}

          {/* Right U labels */}
          {!collapseEmpty ? (
            <div className="flex-shrink-0 flex flex-col" style={{ width: LABEL_W }}>
              {Array.from({ length: totalU }, (_, i) => {
                const u = totalU - i;
                return (
                  <div key={u} className="flex items-center justify-center text-[9px] font-mono tabular-nums" style={{ height: U_PX, color: '#475569' }}>
                    {u}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex-shrink-0 flex flex-col" style={{ width: LABEL_W }}>
              {finalSegments.map((seg, si) => {
                if (seg.type === 'collapsed') {
                  return <div key={si} style={{ height: COLLAPSED_PH }} />;
                }
                return Array.from({ length: seg.uEnd - seg.uStart + 1 }, (_, j) => {
                  const u = seg.uEnd - j;
                  return (
                    <div key={`${si}-${u}`} className="flex items-center justify-center text-[9px] font-mono tabular-nums" style={{ height: U_PX, color: '#475569' }}>
                      {u}
                    </div>
                  );
                });
              })}
            </div>
          )}
        </div>

        {nonStandardDevices.length > 0 && (
          <div
            className="mt-3 rounded-lg border p-2"
            style={{ width: RACK_W + LABEL_W * 2, borderColor: 'rgba(245,158,11,0.35)', background: 'rgba(245,158,11,0.06)' }}
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
          <DraggableDevice device={activeDevice} totalU={totalU} zh={zh} isDragOverlay />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
};

export default RackElevation;
