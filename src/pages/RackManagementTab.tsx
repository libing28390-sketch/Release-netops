/**
 * RackManagementTab - Production-grade draggable rack visualization
 *
 * - @dnd-kit drag engine: snap-to-grid, conflict detection, drag preview
 * - 42U rack elevation (front/rear views)
 * - Power status LEDs
 * - PNG export
 * - Full CRUD for devices / racks / device types
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  DndContext, DragOverlay, useDraggable, useDroppable,
  PointerSensor, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent, type DragMoveEvent,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import {
  Plus, Trash2, Search, X, RefreshCw, Pencil,
  Server, ShieldAlert, HardDrive, Zap,
  LayoutGrid, AlertTriangle,
  Package, Layers, Eye, Download, GripVertical,
  Maximize2, Minimize2, ChevronsUpDown, PanelRightClose, PanelRightOpen,
} from 'lucide-react';
import { AssetReadonlyDetailInner, normalizeAssetApiRow } from '../components/AssetReadonlyDetail';

/* ================================================================
   Types
   ================================================================ */

interface Rack {
  id: string; name: string; datacenter: string; room: string;
  row: string; total_u: number; description: string; status: string;
  created_at: string; updated_at: string;
}

interface DeviceType {
  id: string; model: string; vendor: string; u_height: number;
  device_role: string; is_full_depth: number; description: string;
}

interface RackDevice {
  id: string; name: string; rack_id: string; device_type_id: string;
  start_u: number; position: string; status: string;
  serial_number: string; asset_id: string;
  model: string; vendor: string; u_height: number;
  device_role: string; is_full_depth: number;
}

interface RackLayout {
  id: string; name: string; datacenter: string; room: string;
  row: string; total_u: number; description: string; status: string;
  devices: RackDevice[];
  front_used: number; rear_used: number;
  total_used: number; available_u: number;
}

interface RackStats {
  total_racks: number; total_devices: number;
  total_u: number; used_u: number; utilization: number;
}

interface Props {
  language: string;
  t: (key: string) => string;
}

/* ================================================================
   Constants
   ================================================================ */

const ROLE_COLORS: Record<string, { bg: string; border: string; text: string; label: string; labelZh: string }> = {
  switch:      { bg: '#10b981', border: '#059669', text: '#ffffff', label: 'Switch',      labelZh: '交换机' },
  router:      { bg: '#3b82f6', border: '#2563eb', text: '#ffffff', label: 'Router',      labelZh: '路由器' },
  firewall:    { bg: '#ef4444', border: '#dc2626', text: '#ffffff', label: 'Firewall',    labelZh: '防火墙' },
  server:      { bg: '#6366f1', border: '#4f46e5', text: '#ffffff', label: 'Server',      labelZh: '服务器' },
  storage:     { bg: '#a855f7', border: '#9333ea', text: '#ffffff', label: 'Storage',     labelZh: '存储' },
  pdu:         { bg: '#f59e0b', border: '#d97706', text: '#000000', label: 'PDU',         labelZh: 'PDU' },
  ups:         { bg: '#eab308', border: '#ca8a04', text: '#000000', label: 'UPS',         labelZh: 'UPS' },
  patch_panel: { bg: '#64748b', border: '#475569', text: '#ffffff', label: 'Patch Panel', labelZh: '配线架' },
  other:       { bg: '#94a3b8', border: '#64748b', text: '#ffffff', label: 'Other',       labelZh: '其他' },
};

/** Pixels per rack unit */
const U_PX = 26;
/** Width of the rack content area in px */
const RACK_W = 400;
/** Width of each U-number label column */
const LABEL_W = 28;

const API = '/api';

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('netops_token') || '';
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

/* ================================================================
   API helpers
   ================================================================ */

function formatErrorDetail(detail: any): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((err: any) => {
      if (typeof err === 'object' && err.msg) {
        const field = Array.isArray(err.loc) ? err.loc[err.loc.length - 1] : 'field';
        return `${field}: ${err.msg}`;
      }
      return String(err);
    }).join('; ');
  }
  if (typeof detail === 'object') return JSON.stringify(detail);
  return 'Request failed';
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}
async function postJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}
async function putJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, { method: 'PUT', headers: authHeaders(), body: JSON.stringify(body) });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}
async function deleteJson(url: string): Promise<void> {
  const res = await fetch(url, { method: 'DELETE', headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
}

/** Map a physical asset to a device_types row. Uses vendor/model and optional asset.u_height to disambiguate. */
function matchDeviceTypeId(
  asset: { vendor: string; model: string; u_height?: number },
  types: DeviceType[],
): string {
  if (!types.length) return '';
  const norm = (s: string) => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const av = norm(asset.vendor);
  const am = norm(asset.model);
  if (!am && !av) return '';

  const exacts = types.filter(dt => norm(dt.vendor) === av && norm(dt.model) === am);
  if (exacts.length === 1) return exacts[0].id;
  if (exacts.length > 1 && asset.u_height != null && asset.u_height > 0) {
    const byH = exacts.find(dt => dt.u_height === asset.u_height);
    if (byH) return byH.id;
  }
  if (exacts.length > 0) return exacts[0].id;

  const modelOnly = types.filter(dt => norm(dt.model) === am);
  if (modelOnly.length === 1) return modelOnly[0].id;

  const vendorLoose = types.filter(
    dt => av && norm(dt.vendor) === av && am && (norm(dt.model).includes(am) || am.includes(norm(dt.model))),
  );
  if (vendorLoose.length === 1) return vendorLoose[0].id;

  const fuzzy = types.filter(dt => am && (am.includes(norm(dt.model)) || norm(dt.model).includes(am)));
  if (fuzzy.length === 1) return fuzzy[0].id;

  return '';
}

/** Prefer planned RU from asset (planned_start_u or numeric rack_unit), else first free slot. */
function pickStartUForAsset(
  layout: RackLayout,
  position: string,
  uH: number,
  asset: { planned_start_u?: number | null; rack_unit?: string },
): number {
  const side = layout.devices.filter(d => d.position === position);
  let candidate: number | null = null;
  if (asset.planned_start_u != null && asset.planned_start_u >= 1) {
    candidate = asset.planned_start_u;
  } else {
    const ru = String(asset.rack_unit || '').trim();
    if (/^\d+$/.test(ru)) {
      const n = parseInt(ru, 10);
      if (n >= 1 && n <= layout.total_u) candidate = n;
    }
  }
  if (candidate != null && !hasConflict(candidate, uH, layout.total_u, side)) {
    return candidate;
  }
  return findFirstFreeStartU(layout.total_u, uH, side) ?? 1;
}

/* ================================================================
   Helpers
   ================================================================ */

const DeviceIcon: React.FC<{ role: string; size?: number }> = ({ role, size = 14 }) => {
  switch (role) {
    case 'switch': return <Layers size={size} />;
    case 'router': return <Zap size={size} />;
    case 'firewall': return <ShieldAlert size={size} />;
    case 'server': return <Server size={size} />;
    case 'storage': return <HardDrive size={size} />;
    case 'ups': case 'pdu': return <Zap size={size} />;
    default: return <Package size={size} />;
  }
};

/** Convert U-number to top-offset px (U42 at top, U1 at bottom) */
function uToY(uNumber: number, totalU: number): number {
  return (totalU - uNumber) * U_PX;
}

/** Convert Y-offset to U-number (snap) */
function yToU(y: number, totalU: number): number {
  const u = totalU - Math.floor(y / U_PX);
  return Math.max(1, Math.min(totalU, u));
}

/** Check whether placing a device at targetU would overlap with any other. */
function hasConflict(
  targetU: number,
  uHeight: number,
  totalU: number,
  devices: RackDevice[],
  excludeId?: string,
): boolean {
  if (targetU < 1 || targetU + uHeight - 1 > totalU) return true;
  const tTop = targetU + uHeight - 1;
  for (const d of devices) {
    if (d.id === excludeId) continue;
    const dTop = d.start_u + d.u_height - 1;
    if (targetU <= dTop && tTop >= d.start_u) return true;
  }
  return false;
}

/** Lowest start_u that fits uHeight without overlapping others on the same panel (front/rear). */
function findFirstFreeStartU(
  totalU: number,
  uHeight: number,
  onSideDevices: RackDevice[],
): number | null {
  if (uHeight < 1 || totalU < 1) return null;
  for (let u = 1; u <= totalU - uHeight + 1; u++) {
    if (!hasConflict(u, uHeight, totalU, onSideDevices)) return u;
  }
  return null;
}

const INSTALL_ASSET_PAGE_SIZE = 500;

/* ================================================================
   PowerLed
   ================================================================ */

const PowerLed: React.FC<{ status: string; size?: number }> = ({ status, size = 8 }) => {
  const color = status === 'active' ? '#4ade80' : status === 'planned' ? '#fbbf24' : '#ef4444';
  return (
    <span
      className="inline-block rounded-full flex-shrink-0"
      style={{
        width: size, height: size,
        background: color,
        boxShadow: status === 'active' ? `0 0 6px ${color}80` : 'none',
      }}
    />
  );
};

/* ================================================================
   DraggableDevice — single continuous block per device
   ================================================================ */

const STATUS_LABEL: Record<string, { zh: string; en: string }> = {
  active:  { zh: '通电运行', en: 'Powered On' },
  offline: { zh: '已断电',   en: 'Powered Off' },
  planned: { zh: '规划中',   en: 'Planned' },
};

const DraggableDevice: React.FC<{
  device: RackDevice;
  totalU: number;
  zh: boolean;
  isDragOverlay?: boolean;
  onSelect?: (deviceId: string) => void;
}> = ({ device, totalU, zh, isDragOverlay = false, onSelect }) => {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: device.id,
    data: { device },
  });
  const [showTooltip, setShowTooltip] = useState(false);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const rc = ROLE_COLORS[device.device_role] || ROLE_COLORS.other;
  const h = device.u_height * U_PX;
  const topPx = uToY(device.start_u + device.u_height - 1, totalU);

  const style: React.CSSProperties = isDragOverlay
    ? { width: RACK_W - 4, height: h - 2 }
    : {
        position: 'absolute' as const,
        left: 2, right: 2,
        top: topPx + 1,
        height: h - 2,
        transform: CSS.Translate.toString(transform),
        transition: isDragging ? 'none' : 'top 0.2s ease, opacity 0.15s ease',
        opacity: isDragging ? 0.35 : 1,
        zIndex: isDragging ? 50 : (showTooltip ? 40 : 10),
      };

  const endU = device.start_u + device.u_height - 1;
  const roleName = zh ? (ROLE_COLORS[device.device_role]?.labelZh || device.device_role) : (ROLE_COLORS[device.device_role]?.label || device.device_role);
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
                {zh ? '电源' : 'Power'}: <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: powerColor, boxShadow: device.status === 'active' ? `0 0 6px ${powerColor}` : 'none' }} />
                <span style={{ color: powerColor }}>{zh ? statusInfo.zh : statusInfo.en}</span>
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

/* ================================================================
   DroppableSlot — each U-slot is a drop target
   ================================================================ */

const DroppableSlot: React.FC<{
  uNumber: number;
  isGhostHere: boolean;
  ghostConflict: boolean;
  ghostHeight: number;
  ghostIsStart: boolean;
}> = ({ uNumber, isGhostHere, ghostConflict, ghostHeight, ghostIsStart }) => {
  const { setNodeRef } = useDroppable({ id: `slot-${uNumber}` });

  return (
    <div
      ref={setNodeRef}
      className="absolute"
      style={{ left: 0, right: 0, top: 0, height: U_PX }}
    >
      {isGhostHere && ghostIsStart && (
        <div
          className="absolute inset-x-0 rounded-[3px] pointer-events-none transition-all duration-100"
          style={{
            top: 0,
            height: ghostHeight * U_PX - 2,
            background: ghostConflict ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)',
            border: ghostConflict ? '2px dashed #ef4444' : '2px dashed #10b981',
            zIndex: 5,
          }}
        />
      )}
    </div>
  );
};

/* ================================================================
   RackElevation — main rack diagram with DnD
   ================================================================ */

const RackElevation: React.FC<{
  layout: RackLayout;
  viewSide: 'front' | 'rear';
  zh: boolean;
  collapseEmpty: boolean;
  onDeviceMove: (deviceId: string, newStartU: number) => Promise<void>;
  onDeviceSelect?: (deviceId: string) => void;
}> = ({ layout, viewSide, zh, collapseEmpty, onDeviceMove, onDeviceSelect }) => {
  const totalU = layout.total_u;
  const sideDevices = useMemo(
    () => layout.devices.filter(d => d.position === viewSide),
    [layout.devices, viewSide],
  );

  // Compute which U-slots are occupied
  const occupiedUs = useMemo(() => {
    const s = new Set<number>();
    for (const d of sideDevices) {
      for (let u = d.start_u; u < d.start_u + d.u_height; u++) s.add(u);
    }
    return s;
  }, [sideDevices]);

  // Compute collapsed segments: runs of >3 empty U-slots get collapsed
  type Segment = { type: 'normal'; uStart: number; uEnd: number } | { type: 'collapsed'; uStart: number; uEnd: number; count: number };
  const [expandedSegments, setExpandedSegments] = useState<Set<string>>(new Set());

  const segments = useMemo<Segment[]>(() => {
    if (!collapseEmpty) return [{ type: 'normal', uStart: 1, uEnd: totalU }];
    const segs: Segment[] = [];
    let emptyRunStart: number | null = null;
    // Iterate from top (totalU) to bottom (1) of the rack visually
    for (let u = totalU; u >= 1; u--) {
      if (!occupiedUs.has(u)) {
        if (emptyRunStart === null) emptyRunStart = u;
      } else {
        if (emptyRunStart !== null) {
          const runCount = emptyRunStart - u; // from u+1 to emptyRunStart
          if (runCount > 3) {
            segs.push({ type: 'collapsed', uStart: u + 1, uEnd: emptyRunStart, count: runCount });
          } else {
            segs.push({ type: 'normal', uStart: u + 1, uEnd: emptyRunStart });
          }
          emptyRunStart = null;
        }
        // Find device top boundary to include entire device
        const dev = sideDevices.find(d => u >= d.start_u && u < d.start_u + d.u_height);
        if (dev) {
          const devTop = dev.start_u + dev.u_height - 1;
          const devBot = dev.start_u;
          segs.push({ type: 'normal', uStart: devBot, uEnd: devTop });
          u = devBot; // skip to bottom of device
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

  // Merge adjacent normal segments and flatten
  const finalSegments = useMemo<Segment[]>(() => {
    if (!collapseEmpty) return segments;
    // Check if user expanded any collapsed segments
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

  // Reset expanded segments when collapseEmpty toggles off
  useEffect(() => {
    if (!collapseEmpty) setExpandedSegments(new Set());
  }, [collapseEmpty]);

  const [activeDevice, setActiveDevice] = useState<RackDevice | null>(null);
  const [ghostU, setGhostU] = useState<number | null>(null);
  const rackBodyRef = useRef<HTMLDivElement>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const ghostConflict = useMemo(() => {
    if (!activeDevice || ghostU === null) return true;
    return hasConflict(ghostU, activeDevice.u_height, totalU, sideDevices, activeDevice.id);
  }, [activeDevice, ghostU, totalU, sideDevices]);

  const handleDragStart = useCallback((e: DragStartEvent) => {
    const dev = e.active.data.current?.device as RackDevice | undefined;
    if (dev) {
      setActiveDevice(dev);
      setGhostU(dev.start_u);
    }
  }, []);

  const handleDragMove = useCallback((e: DragMoveEvent) => {
    if (!activeDevice || !rackBodyRef.current) return;
    const rackRect = rackBodyRef.current.getBoundingClientRect();
    const pointerY = (e.activatorEvent as PointerEvent).clientY + (e.delta.y ?? 0);
    const relY = pointerY - rackRect.top;
    const topU = yToU(relY, totalU);
    const startU = topU - activeDevice.u_height + 1;
    const clamped = Math.max(1, Math.min(totalU - activeDevice.u_height + 1, startU));
    setGhostU(clamped);
  }, [activeDevice, totalU]);

  const handleDragEnd = useCallback(async (e: DragEndEvent) => {
    if (activeDevice && ghostU !== null && !hasConflict(ghostU, activeDevice.u_height, totalU, sideDevices, activeDevice.id)) {
      if (ghostU !== activeDevice.start_u) {
        await onDeviceMove(activeDevice.id, ghostU);
      }
    }
    setActiveDevice(null);
    setGhostU(null);
  }, [activeDevice, ghostU, totalU, sideDevices, onDeviceMove]);

  const handleDragCancel = useCallback(() => {
    setActiveDevice(null);
    setGhostU(null);
  }, []);

  const ghostUSet = useMemo(() => {
    if (!activeDevice || ghostU === null) return new Set<number>();
    const s = new Set<number>();
    for (let u = ghostU; u < ghostU + activeDevice.u_height; u++) s.add(u);
    return s;
  }, [activeDevice, ghostU]);

  /* Collapsed-mode height: sum segment heights */
  const COLLAPSED_PH = 32; // height of collapsed placeholder
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
              {/* U-slot grid + droppable areas */}
              {Array.from({ length: totalU }, (_, i) => {
                const u = totalU - i;
                const isGhost = ghostUSet.has(u);
                return (
                  <div
                    key={u}
                    className="absolute"
                    style={{ left: 0, right: 0, top: i * U_PX, height: U_PX, borderBottom: '1px solid rgba(30,41,59,0.5)' }}
                  >
                    <DroppableSlot
                      uNumber={u}
                      isGhostHere={isGhost}
                      ghostConflict={ghostConflict}
                      ghostHeight={activeDevice?.u_height ?? 1}
                      ghostIsStart={ghostU === u}
                    />
                    {!sideDevices.some(d => u >= d.start_u && u < d.start_u + d.u_height) && !isGhost && (
                      <span className="absolute inset-0 flex items-center justify-center text-[8px] font-mono text-slate-700 pointer-events-none">
                        U{u}
                      </span>
                    )}
                  </div>
                );
              })}

              {/* Device blocks */}
              {sideDevices.map(d => (
                <DraggableDevice key={d.id} device={d} totalU={totalU} zh={zh} onSelect={onDeviceSelect} />
              ))}
            </div>
          ) : (
            /* Collapsed mode — render segments */
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
                  // Normal segment — render U slots
                  const segHeight = (seg.uEnd - seg.uStart + 1) * U_PX;
                  const y0 = yOffset;
                  yOffset += segHeight;
                  const segDevices = sideDevices.filter(d => {
                    const dTop = d.start_u + d.u_height - 1;
                    return d.start_u <= seg.uEnd && dTop >= seg.uStart;
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
                            {!sideDevices.some(d => u >= d.start_u && u < d.start_u + d.u_height) && (
                              <span className="absolute inset-0 flex items-center justify-center text-[8px] font-mono text-slate-700 pointer-events-none">
                                U{u}
                              </span>
                            )}
                          </div>
                        );
                      })}
                      {/* Devices in this segment */}
                      {segDevices.map(d => {
                        const rc = ROLE_COLORS[d.device_role] || ROLE_COLORS.other;
                        const devH = d.u_height * U_PX;
                        const devTop = (seg.uEnd - (d.start_u + d.u_height - 1)) * U_PX;
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
                            <PowerLed status={d.status} size={d.u_height >= 2 ? 8 : 6} />
                            <DeviceIcon role={d.device_role} size={d.u_height >= 2 ? 15 : 12} />
                            <span className={`font-bold truncate ${d.u_height >= 2 ? 'text-[12px]' : 'text-[10px]'}`}>{d.name}</span>
                            <span className="text-[9px] font-mono opacity-60 pr-1.5 flex-shrink-0 ml-auto">{d.u_height}U</span>
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
      </div>

      {/* Drag overlay */}
      <DragOverlay dropAnimation={null}>
        {activeDevice ? (
          <DraggableDevice device={activeDevice} totalU={totalU} zh={zh} isDragOverlay />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
};

/* ================================================================
   Main Component
   ================================================================ */

const RackManagementTab: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';

  const [racks, setRacks] = useState<Rack[]>([]);
  const [deviceTypes, setDeviceTypes] = useState<DeviceType[]>([]);
  const [stats, setStats] = useState<RackStats | null>(null);
  const [selectedRackId, setSelectedRackId] = useState('');
  const [layout, setLayout] = useState<RackLayout | null>(null);
  const [viewSide, setViewSide] = useState<'front' | 'rear'>('front');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [dcFilter, setDcFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [allLayouts, setAllLayouts] = useState<RackLayout[]>([]);

  /* -- Zoom / Collapse / Sidebar states -- */
  const [rackScale, setRackScale] = useState(1);
  const [collapseEmpty, setCollapseEmpty] = useState(false);
  const [showDeviceList, setShowDeviceList] = useState(true);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [drawerAssetDetail, setDrawerAssetDetail] = useState<ReturnType<typeof normalizeAssetApiRow> | null>(null);
  const [drawerAssetLoading, setDrawerAssetLoading] = useState(false);
  const rackScrollRef = useRef<HTMLDivElement>(null);

  const [confirmDeleteRack, setConfirmDeleteRack] = useState<{ rackId: string; rackName: string } | null>(null);
  const [blockedDeleteRack, setBlockedDeleteRack] = useState<{ rackName: string; deviceCount: number } | null>(null);
  const [confirmRemoveDevice, setConfirmRemoveDevice] = useState<{ deviceId: string; deviceName: string } | null>(null);

  const [showRackModal, setShowRackModal] = useState(false);
  const [editingRack, setEditingRack] = useState<Rack | null>(null);
  const [showDeviceModal, setShowDeviceModal] = useState(false);
  const [showDeviceTypeModal, setShowDeviceTypeModal] = useState(false);

  const [rackForm, setRackForm] = useState({ name: '', datacenter: '', room: '', row: '', total_u: 42, description: '' });
  const [deviceForm, setDeviceForm] = useState({ name: '', device_type_id: '', start_u: 1, position: 'front' as string, status: 'active', serial_number: '', asset_id: '' });
  const [dtForm, setDtForm] = useState({ model: '', vendor: '', u_height: 1, device_role: 'switch', description: '' });
  const [formError, setFormError] = useState('');

  // Asset selection for device installation (fields align with physical_assets / asset API)
  interface Asset {
    id: string; asset_tag: string; serial_number: string; vendor: string; model: string; hostname: string; status: string;
    u_height?: number; planned_start_u?: number | null; rack_unit?: string;
  }
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetTotal, setAssetTotal] = useState(0);
  const [assetPage, setAssetPage] = useState(1);
  const [assetSearch, setAssetSearch] = useState('');
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);

  const datacenters = useMemo(() => {
    const dcs = new Set(racks.map(r => r.datacenter).filter(Boolean));
    return Array.from(dcs).sort();
  }, [racks]);

  const filteredRacks = useMemo(() => {
    let list = racks;
    if (dcFilter) list = list.filter(r => r.datacenter === dcFilter);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      // Build a set of rack IDs that have matching devices
      const rackIdsWithMatchingDevices = new Set<string>();
      for (const ly of allLayouts) {
        for (const d of ly.devices) {
          if (
            d.name.toLowerCase().includes(q) ||
            d.model.toLowerCase().includes(q) ||
            d.vendor.toLowerCase().includes(q) ||
            d.device_role.toLowerCase().includes(q) ||
            (d.serial_number && d.serial_number.toLowerCase().includes(q)) ||
            (d.asset_id && d.asset_id.toLowerCase().includes(q))
          ) {
            rackIdsWithMatchingDevices.add(ly.id);
          }
        }
      }
      list = list.filter(r =>
        r.name.toLowerCase().includes(q) ||
        r.datacenter.toLowerCase().includes(q) ||
        r.room.toLowerCase().includes(q) ||
        r.row.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        rackIdsWithMatchingDevices.has(r.id)
      );
    }
    return list;
  }, [racks, dcFilter, searchQuery, allLayouts]);

  /* -- Data Fetchers -- */

  const loadRacks = useCallback(async () => {
    try {
      const data = await fetchJson<Rack[]>(`${API}/racks`);
      setRacks(data);
      if (!selectedRackId && data.length > 0) setSelectedRackId(data[0].id);
      // Load all layouts for cross-rack device search
      const layouts = await Promise.all(
        data.map(r => fetchJson<RackLayout>(`${API}/racks/${r.id}/layout`).catch(() => null))
      );
      setAllLayouts(layouts.filter((l): l is RackLayout => l !== null));
    } catch (e: any) { setError(e.message); }
  }, [selectedRackId]);

  const loadDeviceTypes = useCallback(async () => {
    try { setDeviceTypes(await fetchJson<DeviceType[]>(`${API}/device-types`)); } catch {}
  }, []);

  const loadStats = useCallback(async () => {
    try { setStats(await fetchJson<RackStats>(`${API}/racks/stats`)); } catch {}
  }, []);

  const fetchInstallAssets = useCallback(async (q: string, page: number, append: boolean) => {
    try {
      setAssetsLoading(true);
      const params = new URLSearchParams({
        page_size: String(INSTALL_ASSET_PAGE_SIZE),
        page: String(page),
      });
      const t = q.trim();
      if (t) params.set('q', t);
      const res = await fetch(`${API}/assets?${params.toString()}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const items = json.items || [];
      const total = typeof json.total === 'number' ? json.total : items.length;
      if (append) {
        setAssets(prev => [...prev, ...items]);
      } else {
        setAssets(items);
      }
      setAssetTotal(total);
      setAssetPage(page);
    } catch (e: any) {
      console.error('Failed to load assets:', e.message);
      if (!append) {
        setAssets([]);
        setAssetTotal(0);
      }
    } finally {
      setAssetsLoading(false);
    }
  }, []);

  const loadLayout = useCallback(async (rackId: string) => {
    if (!rackId) return;
    setLoading(true);
    try {
      setLayout(await fetchJson<RackLayout>(`${API}/racks/${rackId}/layout`));
      setError('');
    } catch (e: any) { setError(e.message); setLayout(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadRacks(); loadDeviceTypes(); loadStats(); }, []);
  useEffect(() => { if (selectedRackId) loadLayout(selectedRackId); }, [selectedRackId, loadLayout]);

  /** After a rack is deleted, clear invalid selection and pick a remaining rack (avoids 404 layout fetch). */
  useEffect(() => {
    if (racks.length === 0) {
      if (selectedRackId) {
        setSelectedRackId('');
        setLayout(null);
      }
      return;
    }
    if (selectedRackId && !racks.some(r => r.id === selectedRackId)) {
      setSelectedRackId(racks[0].id);
    }
  }, [racks, selectedRackId]);

  useEffect(() => {
    if (!showDeviceModal) return;
    const delay = assetSearch.trim().length === 0 ? 0 : 280;
    const id = window.setTimeout(() => { fetchInstallAssets(assetSearch, 1, false); }, delay);
    return () => clearTimeout(id);
  }, [showDeviceModal, assetSearch, fetchInstallAssets]);

  const installAssetsCanLoadMore = assetTotal > 0 && assets.length < assetTotal;

  const refresh = () => { loadRacks(); loadStats(); if (selectedRackId) loadLayout(selectedRackId); };

  // Handle device selection - open drawer
  const handleDeviceSelect = (deviceId: string) => {
    setSelectedDeviceId(deviceId);
    setDrawerVisible(true);
  };

  // Handle drawer close
  const handleDrawerClose = () => {
    setDrawerVisible(false);
    setSelectedDeviceId(null);
    setDrawerAssetDetail(null);
    setDrawerAssetLoading(false);
  };

  useEffect(() => {
    if (!drawerVisible || !selectedDeviceId || !layout) {
      setDrawerAssetDetail(null);
      setDrawerAssetLoading(false);
      return;
    }
    const device = layout.devices.find(d => d.id === selectedDeviceId);
    if (!device?.asset_id) {
      setDrawerAssetDetail(null);
      setDrawerAssetLoading(false);
      return;
    }
    let cancelled = false;
    setDrawerAssetLoading(true);
    (async () => {
      try {
        const res = await fetch(`${API}/assets/${device.asset_id}`, { headers: authHeaders() });
        if (!res.ok) throw new Error('asset fetch failed');
        const row = await res.json();
        if (!cancelled) setDrawerAssetDetail(normalizeAssetApiRow(row as Record<string, unknown>));
      } catch {
        if (!cancelled) setDrawerAssetDetail(null);
      } finally {
        if (!cancelled) setDrawerAssetLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [drawerVisible, selectedDeviceId, layout]);

  // Handle escape key to close drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && drawerVisible) {
        handleDrawerClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [drawerVisible]);

  /* -- Rack CRUD -- */

  const openNewRack = () => {
    setEditingRack(null);
    setRackForm({ name: '', datacenter: '', room: '', row: '', total_u: 42, description: '' });
    setFormError(''); setShowRackModal(true);
  };
  const openEditRack = (rack: Rack) => {
    setEditingRack(rack);
    setRackForm({ name: rack.name, datacenter: rack.datacenter, room: rack.room, row: rack.row, total_u: rack.total_u, description: rack.description });
    setFormError(''); setShowRackModal(true);
  };
  const saveRack = async () => {
    setFormError('');
    try {
      if (editingRack) {
        await putJson(`${API}/racks/${editingRack.id}`, rackForm);
      } else {
        const created = await postJson<Rack>(`${API}/racks`, rackForm);
        setSelectedRackId(created.id);
      }
      setShowRackModal(false); refresh();
    } catch (e: any) { setFormError(e.message); }
  };
  const handleDeleteRack = async (rackId: string) => {
    setError('');
    try {
      const lay = await fetchJson<RackLayout>(`${API}/racks/${rackId}/layout`);
      if (lay.devices.length > 0) {
        const rack = racks.find(r => r.id === rackId);
        setBlockedDeleteRack({ rackName: rack?.name || '', deviceCount: lay.devices.length });
        return;
      }
      const rack = racks.find(r => r.id === rackId);
      setConfirmDeleteRack({ rackId, rackName: rack?.name || '' });
    } catch (e: any) {
      setError(e.message);
      return;
    }
  };

  const confirmDeleteRackAction = async () => {
    if (!confirmDeleteRack) return;
    const { rackId } = confirmDeleteRack;
    setConfirmDeleteRack(null);
    setError('');
    try {
      await deleteJson(`${API}/racks/${rackId}`);
      if (selectedRackId === rackId) {
        setSelectedRackId('');
        setLayout(null);
      }
      await loadRacks();
      loadStats();
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* -- Device Install -- */

  const closeInstallModal = () => {
    setFormError('');
    setShowDeviceModal(false);
  };

  const openInstallDevice = () => {
    setSelectedAsset(null);
    setAssetSearch('');
    setAssetTotal(0);
    setAssetPage(1);
    setDeviceForm({ name: '', device_type_id: '', start_u: 1, position: 'front', status: 'active', serial_number: '', asset_id: '' });
    setFormError('');
    setShowDeviceModal(true);
  };

  const resolveStartUForInstall = (deviceTypeId: string, position: string): number => {
    const uH = deviceTypes.find(dt => dt.id === deviceTypeId)?.u_height ?? 1;
    if (!layout || !selectedRackId) return 1;
    if (selectedAsset) {
      return pickStartUForAsset(layout, position, uH, selectedAsset);
    }
    const sideDevices = layout.devices.filter(d => d.position === position);
    return findFirstFreeStartU(layout.total_u, uH, sideDevices) ?? 1;
  };

  const handleAssetSelect = (asset: Asset) => {
    setSelectedAsset(asset);
    const matchedId = matchDeviceTypeId(asset, deviceTypes);
    const position = 'front';
    const uH = matchedId
      ? (deviceTypes.find(dt => dt.id === matchedId)?.u_height ?? 1)
      : Math.max(1, asset.u_height ?? 1);
    const startU =
      layout && selectedRackId ? pickStartUForAsset(layout, position, uH, asset) : 1;
    setDeviceForm({
      name: asset.hostname || asset.asset_tag || '',
      device_type_id: matchedId,
      start_u: startU,
      position,
      status: asset.status === 'in_storage' ? 'offline' : asset.status === 'active' ? 'active' : 'planned',
      serial_number: asset.serial_number || '',
      asset_id: asset.id || '',
    });
  };

  const saveDevice = async () => {
    setFormError('');
    if (!deviceForm.name.trim()) {
      setFormError(zh ? '设备名称不能为空' : 'Device name is required');
      return;
    }
    if (!deviceForm.device_type_id) {
      setFormError(zh ? '请选择设备型号' : 'Please select a device type');
      return;
    }
    if (!selectedRackId) {
      setFormError(zh ? '请先选择机柜' : 'Please select a rack first');
      return;
    }
    const dt = deviceTypes.find(x => x.id === deviceForm.device_type_id);
    const uH = dt?.u_height ?? 1;
    if (layout) {
      const sideDevices = layout.devices.filter(d => d.position === deviceForm.position);
      if (hasConflict(deviceForm.start_u, uH, layout.total_u, sideDevices)) {
        const sugg = findFirstFreeStartU(layout.total_u, uH, sideDevices);
        setFormError(
          zh
            ? `当前${deviceForm.position === 'front' ? '前' : '后'}面板 U${deviceForm.start_u} 已被占用或与现有设备重叠。${sugg != null ? `可尝试起始 U${sugg}。` : '无足够连续空位。'}`
            : `${deviceForm.position} side: U${deviceForm.start_u} overlaps existing gear.${sugg != null ? ` Try start U${sugg}.` : ' No contiguous space.'}`,
        );
        return;
      }
    }
    try {
      await postJson(`${API}/rack-devices`, {
        name: deviceForm.name,
        rack_id: selectedRackId,
        device_type_id: deviceForm.device_type_id,
        start_u: deviceForm.start_u,
        position: deviceForm.position,
        status: deviceForm.status,
        serial_number: deviceForm.serial_number || '',
        asset_id: deviceForm.asset_id || '',
      });
      closeInstallModal(); loadLayout(selectedRackId); loadStats();
    } catch (e: any) { setFormError(e.message); }
  };
  const handleRemoveDevice = async (deviceId: string, deviceName: string) => {
    setConfirmRemoveDevice({ deviceId, deviceName });
  };

  const confirmRemoveDeviceAction = async () => {
    if (!confirmRemoveDevice) return;
    const { deviceId } = confirmRemoveDevice;
    setConfirmRemoveDevice(null);
    setError('');
    try {
      await deleteJson(`${API}/rack-devices/${deviceId}`);
      if (selectedDeviceId === deviceId) {
        setSelectedDeviceId(null);
        setDrawerVisible(false);
        setDrawerAssetDetail(null);
        setDrawerAssetLoading(false);
      }
      loadLayout(selectedRackId);
      loadStats();
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* -- Device Type -- */

  const openNewDeviceType = () => {
    setDtForm({ model: '', vendor: '', u_height: 1, device_role: 'switch', description: '' });
    setFormError(''); setShowDeviceTypeModal(true);
  };
  const saveDeviceType = async () => {
    setFormError('');
    try { await postJson(`${API}/device-types`, dtForm); setShowDeviceTypeModal(false); loadDeviceTypes(); }
    catch (e: any) { setFormError(e.message); }
  };

  /* -- Drag-to-move -- */

  const handleDeviceMove = useCallback(async (deviceId: string, newStartU: number) => {
    try {
      await putJson(`${API}/rack-devices/${deviceId}`, { start_u: newStartU });
      loadLayout(selectedRackId);
    } catch (e: any) {
      setError(e.message);
      loadLayout(selectedRackId);
    }
  }, [selectedRackId, loadLayout]);

  /* -- Fit-to-screen zoom -- */
  const handleFitToScreen = useCallback(() => {
    if (!rackScrollRef.current || !layout) return;
    const containerH = rackScrollRef.current.clientHeight - 40; // subtract label header
    const rackH = layout.total_u * U_PX + 8; // +border
    if (rackH <= 0) return;
    const fit = Math.min(1, containerH / rackH);
    setRackScale(Math.max(0.3, Math.round(fit * 100) / 100));
  }, [layout]);

  const handleResetZoom = useCallback(() => setRackScale(1), []);

  /* -- Download PNG -- */

  const handleDownloadRack = useCallback(() => {
    if (!layout) return;
    const totalU = layout.total_u;
    const side = viewSide;
    const devices = layout.devices.filter(d => d.position === side);

    const scale = 2;
    const uH = 28;
    const lw = 32;
    const rw = 420;
    const totalW = lw + rw + lw;
    const headerH = 48;
    const footerH = 60;
    const totalH = headerH + totalU * uH + footerH;

    const canvas = document.createElement('canvas');
    canvas.width = totalW * scale;
    canvas.height = totalH * scale;
    const ctx = canvas.getContext('2d')!;
    ctx.scale(scale, scale);

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, totalW, totalH);

    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 14px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`${layout.name} - ${side === 'front' ? (zh ? '前视图' : 'Front') : (zh ? '后视图' : 'Rear')}`, totalW / 2, 20);
    ctx.font = '10px system-ui, sans-serif';
    ctx.fillStyle = '#64748b';
    ctx.fillText(`${layout.datacenter}${layout.room ? ' / ' + layout.room : ''} | ${layout.total_used}U / ${totalU}U`, totalW / 2, 36);

    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 2;
    ctx.strokeRect(lw, headerH, rw, totalU * uH);

    const devMap = new Map<number, (typeof devices)[0]>();
    const spanned = new Set<number>();
    for (const d of devices) {
      devMap.set(d.start_u, d);
      for (let u = d.start_u + 1; u < d.start_u + d.u_height; u++) spanned.add(u);
    }

    for (let i = 0; i < totalU; i++) {
      const uNumber = totalU - i;
      if (spanned.has(uNumber)) continue;
      const y = headerH + i * uH;
      const device = devMap.get(uNumber);
      const h = device ? device.u_height * uH : uH;

      ctx.fillStyle = '#64748b';
      ctx.font = '9px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(String(uNumber), lw / 2, y + h / 2 + 3);
      ctx.fillText(String(uNumber), lw + rw + lw / 2, y + h / 2 + 3);

      if (device) {
        const rc = ROLE_COLORS[device.device_role] || ROLE_COLORS.other;
        ctx.fillStyle = rc.bg;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        ctx.roundRect(lw + 2, y + 1, rw - 4, h - 2, 3);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = rc.border;
        ctx.lineWidth = 1;
        ctx.stroke();

        const ledX = lw + 12;
        const ledY = y + h / 2;
        ctx.beginPath();
        ctx.arc(ledX, ledY, 4, 0, Math.PI * 2);
        ctx.fillStyle = device.status === 'active' ? '#4ade80' : device.status === 'planned' ? '#fbbf24' : '#ef4444';
        ctx.fill();

        ctx.fillStyle = rc.text;
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(device.name, lw + 24, y + h / 2 + 4);
        ctx.font = '9px system-ui, sans-serif';
        ctx.globalAlpha = 0.7;
        ctx.fillText(`${device.vendor} ${device.model}`, lw + 24 + ctx.measureText(device.name).width + 8, y + h / 2 + 4);
        ctx.globalAlpha = 1;
        ctx.textAlign = 'right';
        ctx.font = '9px monospace';
        ctx.fillStyle = rc.text;
        ctx.globalAlpha = 0.7;
        ctx.fillText(`${device.u_height}U`, lw + rw - 10, y + h / 2 + 3);
        ctx.globalAlpha = 1;
      } else {
        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = 0.5;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(lw + 2, y + 1, rw - 4, uH - 2);
        ctx.setLineDash([]);
      }
    }

    const legendY = headerH + totalU * uH + 16;
    ctx.font = '9px system-ui, sans-serif';
    ctx.textAlign = 'left';
    let lx = 10;
    for (const [label, color] of [
      [zh ? '通电' : 'ON', '#4ade80'],
      [zh ? '断电' : 'OFF', '#ef4444'],
      [zh ? '规划' : 'Plan', '#fbbf24'],
    ] as const) {
      ctx.beginPath();
      ctx.arc(lx + 4, legendY, 3, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(label, lx + 10, legendY + 3);
      lx += ctx.measureText(label).width + 22;
    }
    lx += 10;
    for (const [, rc] of Object.entries(ROLE_COLORS)) {
      ctx.fillStyle = rc.bg;
      ctx.fillRect(lx, legendY - 5, 10, 10);
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(zh ? rc.labelZh : rc.label, lx + 14, legendY + 3);
      lx += ctx.measureText(zh ? rc.labelZh : rc.label).width + 22;
      if (lx > totalW - 30) break;
    }

    const link = document.createElement('a');
    link.download = `rack-${layout.name}-${side}-${new Date().toISOString().slice(0, 10)}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }, [layout, viewSide, zh]);

  /* ===================== RENDER ===================== */

  const selectedRack = racks.find(r => r.id === selectedRackId);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* -- Header + Stats row -- */}
      <div className="flex-shrink-0 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
        <div className="flex items-center gap-4">
          <div>
            <h2 className="text-lg font-bold" style={{ color: 'var(--heading-text)' }}>
              {zh ? '机柜管理' : 'Rack Management'}
            </h2>
            <p className="text-[11px]" style={{ color: 'var(--muted-text)' }}>
              {zh ? '拖拽设备调整U位 · 可视化机柜布局' : 'Drag devices to reposition · Visual rack layout'}
            </p>
          </div>
          {stats && (
            <div className="hidden lg:flex items-center gap-3 ml-2">
              {[
                { label: zh ? '机柜' : 'Racks', value: stats.total_racks, color: '#06b6d4', icon: <LayoutGrid size={14} /> },
                { label: zh ? '设备' : 'Devices', value: stats.total_devices, color: '#6366f1', icon: <Server size={14} /> },
                { label: zh ? 'U位' : 'U', value: `${stats.used_u}/${stats.total_u}`, color: '#10b981', icon: <Layers size={14} /> },
                { label: zh ? '利用率' : 'Util', value: `${stats.utilization}%`, color: stats.utilization > 80 ? '#ef4444' : stats.utilization > 60 ? '#f59e0b' : '#10b981', icon: <Eye size={14} /> },
              ].map((s, i) => (
                <div key={i} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
                  <span style={{ color: s.color }}>{s.icon}</span>
                  <span className="text-[11px] font-bold" style={{ color: s.color }}>{s.value}</span>
                  <span className="text-[10px]" style={{ color: 'var(--muted-text)' }}>{s.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={openNewDeviceType} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', color: 'var(--body-text)' }}>
            <Package size={14} /> {zh ? '设备型号' : 'Device Types'}
          </button>
          <button onClick={openNewRack} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors">
            <Plus size={14} /> {zh ? '新建机柜' : 'New Rack'}
          </button>
          <button onClick={refresh} className="p-1.5 rounded-lg transition-colors" style={{ color: 'var(--muted-text)' }} title={zh ? '刷新' : 'Refresh'}>
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* -- Stats cards (small screens) -- */}
      {stats && (
        <div className="flex-shrink-0 grid grid-cols-2 sm:grid-cols-4 gap-2 lg:hidden">
          {[
            { label: zh ? '机柜总数' : 'Racks', value: stats.total_racks, color: '#06b6d4', icon: <LayoutGrid size={16} /> },
            { label: zh ? '已安装设备' : 'Devices', value: stats.total_devices, color: '#6366f1', icon: <Server size={16} /> },
            { label: zh ? '总U位' : 'Total U', value: `${stats.used_u} / ${stats.total_u}`, color: '#10b981', icon: <Layers size={16} /> },
            { label: zh ? '利用率' : 'Utilization', value: `${stats.utilization}%`, color: stats.utilization > 80 ? '#ef4444' : stats.utilization > 60 ? '#f59e0b' : '#10b981', icon: <Eye size={16} /> },
          ].map((s, i) => (
            <div key={i} className="rounded-lg px-3 py-2" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] font-medium" style={{ color: 'var(--muted-text)' }}>{s.label}</p>
                  <p className="text-lg font-bold" style={{ color: s.color }}>{s.value}</p>
                </div>
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: s.color + '15', color: s.color }}>{s.icon}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* -- Main: Rack List + Elevation (fills remaining height) -- */}
      <div className="flex gap-3 flex-1 min-h-0">
        {/* Left: rack list */}
        <div className="w-56 flex-shrink-0 rounded-xl overflow-hidden flex flex-col" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
          <div className="p-3 space-y-2 border-b" style={{ borderColor: 'var(--card-border)' }}>
            <div className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5" style={{ background: 'var(--app-hover-bg)' }}>
              <Search size={14} style={{ color: 'var(--muted-text)' }} />
              <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder={zh ? '搜索机柜/设备...' : 'Search rack/device...'} className="flex-1 bg-transparent text-xs outline-none" style={{ color: 'var(--body-text)' }} />
              {searchQuery && <button onClick={() => setSearchQuery('')}><X size={12} style={{ color: 'var(--muted-text)' }} /></button>}
            </div>
            {datacenters.length > 1 && (
              <select value={dcFilter} onChange={e => setDcFilter(e.target.value)} className="w-full text-[11px] rounded-lg px-2 py-1.5 outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}>
                <option value="">{zh ? '全部数据中心' : 'All DCs'}</option>
                {datacenters.map(dc => <option key={dc} value={dc}>{dc}</option>)}
              </select>
            )}
          </div>
          <div className="flex-1 overflow-auto p-1.5 space-y-0.5">
            {filteredRacks.length === 0 ? (
              <p className="text-center text-xs py-8" style={{ color: 'var(--muted-text)' }}>{zh ? '暂无机柜' : 'No racks'}</p>
            ) : filteredRacks.map(rack => (
              <button
                key={rack.id}
                onClick={() => setSelectedRackId(rack.id)}
                className={`w-full text-left rounded-lg px-3 py-2 transition-all group ${rack.id === selectedRackId ? 'ring-1 ring-cyan-500/50' : ''}`}
                style={{ background: rack.id === selectedRackId ? 'var(--app-hover-bg)' : 'transparent', color: 'var(--body-text)' }}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold truncate">{rack.name}</span>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={(e) => { e.stopPropagation(); openEditRack(rack); }} className="p-0.5 rounded hover:bg-black/10"><Pencil size={11} /></button>
                    <button onClick={(e) => { e.stopPropagation(); handleDeleteRack(rack.id); }} className="p-0.5 rounded hover:bg-red-100 text-red-500"><Trash2 size={11} /></button>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  {rack.datacenter && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: '#06b6d415', color: '#06b6d4' }}>{rack.datacenter}</span>}
                  <span className="text-[10px]" style={{ color: 'var(--muted-text)' }}>{rack.total_u}U</span>
                </div>
                {/* Show matching device names when searching */}
                {searchQuery && (() => {
                  const q = searchQuery.toLowerCase();
                  const ly = allLayouts.find(l => l.id === rack.id);
                  const matches = ly?.devices.filter(d =>
                    d.name.toLowerCase().includes(q) ||
                    d.model.toLowerCase().includes(q) ||
                    d.vendor.toLowerCase().includes(q) ||
                    (d.serial_number && d.serial_number.toLowerCase().includes(q))
                  ) || [];
                  return matches.length > 0 ? (
                    <div className="mt-1 space-y-0.5">
                      {matches.slice(0, 3).map(m => (
                        <div key={m.id} className="text-[9px] truncate flex items-center gap-1" style={{ color: '#06b6d4' }}>
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: (ROLE_COLORS[m.device_role]?.bg || '#94a3b8') }} />
                          {m.name} <span style={{ color: 'var(--muted-text)' }}>U{m.start_u}</span>
                        </div>
                      ))}
                      {matches.length > 3 && <span className="text-[9px]" style={{ color: 'var(--muted-text)' }}>+{matches.length - 3} {zh ? '更多' : 'more'}</span>}
                    </div>
                  ) : null;
                })()}
              </button>
            ))}
          </div>
        </div>

        {/* Center: rack elevation */}
        <div className="flex-1 rounded-xl overflow-hidden flex flex-col relative" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
          {selectedRack && layout ? (
            <>
              {/* Toolbar */}
              <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ borderColor: 'var(--card-border)' }}>
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
                    {selectedRack.name}
                    <span className="text-[11px] font-normal ml-2" style={{ color: 'var(--muted-text)' }}>
                      {selectedRack.datacenter}{selectedRack.room ? ` / ${selectedRack.room}` : ''}
                    </span>
                  </h3>
                  <div className="flex items-center rounded-lg p-0.5" style={{ background: 'var(--app-hover-bg)' }}>
                    <button onClick={() => setViewSide('front')} className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${viewSide === 'front' ? 'bg-cyan-600 text-white shadow-sm' : ''}`} style={viewSide !== 'front' ? { color: 'var(--muted-text)' } : {}}>
                      {zh ? '前面板' : 'Front'}
                    </button>
                    <button onClick={() => setViewSide('rear')} className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${viewSide === 'rear' ? 'bg-cyan-600 text-white shadow-sm' : ''}`} style={viewSide !== 'rear' ? { color: 'var(--muted-text)' } : {}}>
                      {zh ? '后面板' : 'Rear'}
                    </button>
                  </div>
                  {/* Zoom controls */}
                  <div className="flex items-center gap-1">
                    <button onClick={handleFitToScreen} className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors hover:bg-cyan-50" style={{ color: 'var(--muted-text)' }} title={zh ? '适应屏幕' : 'Fit to Screen'}>
                      <Maximize2 size={12} />
                    </button>
                    <button onClick={handleResetZoom} className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors hover:bg-cyan-50" style={{ color: 'var(--muted-text)' }} title={zh ? '原始大小' : '100%'}>
                      100%
                    </button>
                  </div>

                  {/* Collapse empty & sidebar toggles */}
                  <div className="flex items-center gap-1 ml-3 pl-3 border-l" style={{ borderColor: 'var(--card-border)' }}>
                    <button
                      onClick={() => setCollapseEmpty(!collapseEmpty)}
                      className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${collapseEmpty ? 'bg-cyan-600/20 text-cyan-600' : 'hover:bg-cyan-50'}`}
                      style={!collapseEmpty ? { color: 'var(--muted-text)' } : {}}
                      title={zh ? '折叠空U位' : 'Collapse empty'}
                    >
                      {collapseEmpty ? <ChevronsUpDown size={12} /> : <Layers size={12} />}
                      {collapseEmpty ? (zh ? '已折叠' : 'Collapsed') : (zh ? '全展开' : 'Expand')}
                    </button>
                    <button
                      onClick={() => setShowDeviceList(!showDeviceList)}
                      className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${showDeviceList ? 'bg-cyan-600/20 text-cyan-600' : 'hover:bg-cyan-50'}`}
                      style={!showDeviceList ? { color: 'var(--muted-text)' } : {}}
                      title={zh ? '设备栏' : 'Device list'}
                    >
                      {showDeviceList ? <PanelRightOpen size={12} /> : <PanelRightClose size={12} />}
                      {showDeviceList ? (zh ? '已显示' : 'Shown') : (zh ? '已隐藏' : 'Hidden')}
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium" style={{ color: 'var(--muted-text)' }}>
                    {layout.total_used}U / {layout.total_u}U ({layout.available_u}U {zh ? '可用' : 'free'})
                  </span>
                  <button onClick={handleDownloadRack} className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} title={zh ? '下载' : 'Download'}>
                    <Download size={12} /> PNG
                  </button>
                  <button onClick={openInstallDevice} className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors">
                    <Plus size={12} /> {zh ? '安装' : 'Install'}
                  </button>
                </div>
              </div>

              {/* Content */}
              <div className="flex-1 min-h-0 overflow-y-auto p-3" ref={rackScrollRef} style={{ paddingRight: drawerVisible ? 396 : undefined }}>
                <div className="text-[10px] font-semibold text-center mb-1.5 sticky top-0 z-10 pb-1" style={{ color: 'var(--muted-text)', background: 'var(--card-bg)' }}>
                  {viewSide === 'front' ? (zh ? '▼ 前面板 · 可拖拽' : '▼ Front · Draggable') : (zh ? '▼ 后面板 · 可拖拽' : '▼ Rear · Draggable')}
                </div>
                <div style={{ transform: `scale(${rackScale})`, transformOrigin: 'top center' }}>
                  <RackElevation
                    layout={layout}
                    viewSide={viewSide}
                    zh={zh}
                    collapseEmpty={collapseEmpty}
                    onDeviceMove={handleDeviceMove}
                    onDeviceSelect={handleDeviceSelect}
                  />
                </div>
              </div>

              {/* Device Detail Drawer Overlay */}
              {drawerVisible && selectedDeviceId && (() => {
                const device = layout.devices.find(d => d.id === selectedDeviceId);
                if (!device) return null;
                const rc = ROLE_COLORS[device.device_role] || ROLE_COLORS.other;
                const statusInfo = STATUS_LABEL[device.status] || { zh: device.status, en: device.status };
                const endU = device.start_u + device.u_height - 1;
                return (
                  <AnimatePresence>
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      onClick={handleDrawerClose}
                      className="absolute inset-0 z-40 bg-black/20"
                      style={{ borderRadius: 'inherit' }}
                    />
                    <motion.div
                      initial={{ x: '100%' }}
                      animate={{ x: 0 }}
                      exit={{ x: '100%' }}
                      transition={{ duration: 0.3, ease: 'easeOut' }}
                      className="absolute right-0 top-0 bottom-0 z-50 flex flex-col w-96 rounded-xl overflow-hidden"
                      style={{ background: 'var(--card-bg)', boxShadow: '-2px 0 12px rgba(0,0,0,0.15)' }}
                    >
                      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--card-border)' }}>
                        <h3 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>{device.name}</h3>
                        <button onClick={handleDrawerClose} className="p-1 rounded-lg hover:bg-black/5">
                          <X size={18} style={{ color: 'var(--muted-text)' }} />
                        </button>
                      </div>
                      <div className="flex-1 overflow-y-auto p-4 space-y-2">
                        {drawerAssetLoading && (
                          <div className="text-xs flex items-center gap-2 mb-3" style={{ color: 'var(--muted-text)' }}>
                            <RefreshCw size={12} className="animate-spin" />
                            {zh ? '正在加载资产详情…' : 'Loading asset details...'}
                          </div>
                        )}
                        {drawerAssetDetail ? (
                          <div className="rounded-xl border border-black/10 bg-white p-3">
                            <AssetReadonlyDetailInner asset={drawerAssetDetail} zh={zh} />
                          </div>
                        ) : (
                          <>
                            <div className="flex gap-2 flex-wrap mb-4">
                              <span className="text-xs px-2.5 py-1 rounded-lg font-semibold" style={{ background: rc.bg + '20', color: rc.bg }}>
                                {zh ? rc.labelZh : rc.label}
                              </span>
                              <span className="text-xs px-2.5 py-1 rounded-lg font-semibold flex items-center gap-1" style={{ background: device.status === 'active' ? '#4ade80' + '20' : device.status === 'planned' ? '#fbbf24' + '20' : '#ef4444' + '20', color: device.status === 'active' ? '#4ade80' : device.status === 'planned' ? '#fbbf24' : '#ef4444' }}>
                                <span className="w-2 h-2 rounded-full" style={{ background: 'currentColor' }} />
                                {zh ? statusInfo.zh : statusInfo.en}
                              </span>
                            </div>
                            <div className="grid grid-cols-2 gap-x-2.5 gap-y-2 text-[11px]">
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '厂商' : 'Vendor'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.vendor || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.model || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '序列号' : 'Serial No.'}</label>
                                <div className="px-2.5 py-1.5 rounded border font-mono text-[10px]" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.serial_number || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '资产ID' : 'Asset ID'}</label>
                                <div className="px-2.5 py-1.5 rounded border font-mono text-[10px]" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.asset_id || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? 'U位' : 'Unit'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>U{device.start_u}{endU !== device.start_u ? `-U${endU}` : ''}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '位置' : 'Side'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.position === 'front' ? (zh ? '前面板' : 'Front') : (zh ? '后面板' : 'Rear')}</div>
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                      <div className="p-4 border-t" style={{ borderColor: 'var(--card-border)' }}>
                        <button onClick={() => handleRemoveDevice(device.id, device.name)} className="w-full px-3 py-2 rounded-lg text-[12px] font-medium text-red-500 hover:bg-red-50/80">{zh ? '移除设备' : 'Remove'}</button>
                      </div>
                    </motion.div>
                  </AnimatePresence>
                );
              })()}
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--muted-text)' }}>
              {loading ? <RefreshCw size={20} className="animate-spin" /> : (zh ? '请选择机柜' : 'Select a rack')}
            </div>
          )}
        </div>

        {/* Right: device list */}
        {/* Right: installed device list */}
        <div className="w-64 flex-shrink-0 rounded-xl overflow-hidden flex flex-col" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
          {!layout ? (
            <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--muted-text)' }}>
              {zh ? '请选择机柜' : 'Select a rack'}
            </div>
          ) : (
            <>
              <div className="p-3 border-b" style={{ borderColor: 'var(--card-border)' }}>
                <h4 className="text-[12px] font-semibold" style={{ color: 'var(--heading-text)' }}>
                  {zh ? '已安装设备' : 'Installed Devices'} ({layout?.devices.length || 0})
                </h4>
                <p className="text-[10px] mt-1" style={{ color: 'var(--muted-text)' }}>
                  {zh ? '点击查看详情' : 'Click to view details'}
                </p>
              </div>
              <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5">
                {layout.devices.length === 0 ? (
                  <p className="text-xs py-6 text-center" style={{ color: 'var(--muted-text)' }}>
                    {zh ? '暂无设备' : 'No devices'}
                  </p>
                ) : layout.devices.map(d => {
                  const rc = ROLE_COLORS[d.device_role] || ROLE_COLORS.other;
                  const isSelected = selectedDeviceId === d.id;
                  return (
                    <button
                      key={d.id}
                      onClick={() => handleDeviceSelect(d.id)}
                      className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-all text-[12px] ${isSelected ? 'ring-1 ring-cyan-500 bg-cyan-50' : 'hover:bg-black/5 border border-transparent'}`}
                    >
                      <div className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0" style={{ background: rc.bg + '20', color: rc.bg }}>
                        <DeviceIcon role={d.device_role} size={12} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold truncate" style={{ color: 'var(--heading-text)' }}>{d.name}</p>
                        <p className="text-[10px]" style={{ color: 'var(--muted-text)' }}>U{d.start_u}</p>
                      </div>
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: d.status === 'active' ? '#4ade80' : d.status === 'planned' ? '#fbbf24' : '#ef4444' }} />
                    </button>
                  );
                })}
              </div>
            </>
          )}
          {/* Legend */}
          {layout && layout.devices.length > 0 && (
            <div className="p-3 border-t space-y-1.5" style={{ borderColor: 'var(--card-border)' }}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '电源' : 'Power'}:</span>
                {[
                  { color: '#4ade80', glow: true,  label: zh ? '通电' : 'ON' },
                  { color: '#ef4444', glow: false, label: zh ? '断电' : 'OFF' },
                  { color: '#fbbf24', glow: false, label: zh ? '规划' : 'Plan' },
                ].map((item, i) => (
                  <div key={i} className="flex items-center gap-1">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{
                        background: item.color,
                        boxShadow: item.glow ? `0 0 4px ${item.color}` : 'none',
                      }}
                    />
                    <span className="text-[9px]" style={{ color: 'var(--muted-text)' }}>{item.label}</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '设备类型' : 'Device Types'}:</span>
                {Object.entries(ROLE_COLORS).map(([role, rc]) => (
                  <div key={role} className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded" style={{ background: rc.bg }} />
                    <span className="text-[9px]" style={{ color: 'var(--muted-text)' }}>{zh ? rc.labelZh : rc.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* -- Error toast -- */}
      {error && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-600 text-white text-sm shadow-lg">
          <AlertTriangle size={16} />
          <span className="max-w-xs truncate">{error}</span>
          <button onClick={() => setError('')}><X size={14} /></button>
        </div>
      )}

      <AnimatePresence>
        {blockedDeleteRack && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setBlockedDeleteRack(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-red-50">
                <div className="rounded-2xl bg-red-100 p-3 text-red-700"><AlertTriangle size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-red-900">{zh ? '无法删除机柜' : 'Cannot Delete Rack'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `机柜 ${blockedDeleteRack.rackName || ''} 当前还有 ${blockedDeleteRack.deviceCount} 台已安装设备。请先移除机柜中的设备，然后再删除机柜。`
                      : `Rack ${blockedDeleteRack.rackName || ''} still contains ${blockedDeleteRack.deviceCount} installed devices. Remove those devices before deleting the rack.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setBlockedDeleteRack(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '知道了' : 'Got it'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}

        {confirmDeleteRack && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setConfirmDeleteRack(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-red-50">
                <div className="rounded-2xl bg-red-100 p-3 text-red-700"><AlertTriangle size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-red-900">{zh ? '确认删除机柜' : 'Confirm Delete Rack'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `确认要删除机柜 ${confirmDeleteRack.rackName || ''} 吗？此操作会永久删除该空机柜，无法撤销。`
                      : `Are you sure you want to delete rack ${confirmDeleteRack.rackName || ''}? This will permanently remove the empty rack.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setConfirmDeleteRack(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={confirmDeleteRackAction} className="px-4 py-2 rounded-xl bg-red-600 text-white text-sm font-semibold hover:bg-red-700 transition-all">
                  {zh ? '删除机柜' : 'Delete Rack'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}

        {confirmRemoveDevice && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setConfirmRemoveDevice(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-amber-50">
                <div className="rounded-2xl bg-amber-100 p-3 text-amber-700"><AlertTriangle size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-amber-900">{zh ? '确认移除设备' : 'Confirm Remove Device'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `确认要将设备 ${confirmRemoveDevice.deviceName} 从机柜中移除吗？该设备记录将保留。`
                      : `Remove ${confirmRemoveDevice.deviceName} from the rack? The asset record will remain intact.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setConfirmRemoveDevice(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={confirmRemoveDeviceAction} className="px-4 py-2 rounded-xl bg-red-600 text-white text-sm font-semibold hover:bg-red-700 transition-all">
                  {zh ? '移除设备' : 'Remove Device'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ========== MODAL: Create/Edit Rack ========== */}
      <AnimatePresence>
        {showRackModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowRackModal(false)}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-md rounded-2xl shadow-2xl p-6" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }} onClick={e => e.stopPropagation()}>
              <h3 className="text-base font-bold mb-4" style={{ color: 'var(--heading-text)' }}>
                {editingRack ? (zh ? '编辑机柜' : 'Edit Rack') : (zh ? '新建机柜' : 'New Rack')}
              </h3>
              <div className="space-y-3">
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '机柜名称' : 'Name'} *</label>
                  <input value={rackForm.name} onChange={e => setRackForm({ ...rackForm, name: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} placeholder="A-01" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '数据中心' : 'Datacenter'}</label>
                    <input value={rackForm.datacenter} onChange={e => setRackForm({ ...rackForm, datacenter: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '机房' : 'Room'}</label>
                    <input value={rackForm.room} onChange={e => setRackForm({ ...rackForm, room: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '列' : 'Row'}</label>
                    <input value={rackForm.row} onChange={e => setRackForm({ ...rackForm, row: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '总U位' : 'Total U'}</label>
                    <input type="number" min={1} max={60} value={rackForm.total_u} onChange={e => setRackForm({ ...rackForm, total_u: parseInt(e.target.value) || 42 })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                </div>
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '备注' : 'Description'}</label>
                  <textarea value={rackForm.description} onChange={e => setRackForm({ ...rackForm, description: e.target.value })} rows={2} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none resize-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                </div>
              </div>
              {formError && <p className="text-xs text-red-500 mt-2">{formError}</p>}
              <div className="flex justify-end gap-2 mt-5">
                <button onClick={() => setShowRackModal(false)} className="px-4 py-1.5 rounded-lg text-xs font-medium" style={{ color: 'var(--muted-text)' }}>{zh ? '取消' : 'Cancel'}</button>
                <button onClick={saveRack} className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700">{zh ? '保存' : 'Save'}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ========== MODAL: Install Device ========== */}
      <AnimatePresence>
        {showDeviceModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={closeInstallModal}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-xl rounded-2xl shadow-2xl p-6" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }} onClick={e => e.stopPropagation()}>
              <h3 className="text-base font-bold mb-4" style={{ color: 'var(--heading-text)' }}>
                {zh ? '安装设备到机柜' : 'Install Device to Rack'}
              </h3>

              <div className="space-y-4 max-h-[70vh] overflow-y-auto">
                {/* Search Input */}
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '搜索设备（名称或SN号）' : 'Search Device (Name or SN)'} *</label>
                  <div className="relative mt-1">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--muted-text)' }} />
                    <input
                      value={assetSearch}
                      onChange={e => setAssetSearch(e.target.value)}
                      placeholder={zh ? '输入设备名称或SN号...' : 'Enter device name or SN...'}
                      className="w-full pl-9 pr-3 py-2 text-sm rounded-lg outline-none focus:ring-2 ring-cyan-500/30"
                      style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                      autoComplete="off"
                    />
                  </div>
                  {!assetSearch.trim() && assetTotal > INSTALL_ASSET_PAGE_SIZE && (
                    <p className="mt-1.5 text-[10px] leading-snug" style={{ color: 'var(--muted-text)' }}>
                      {zh
                        ? `资产库共 ${assetTotal} 台，当前每页 ${INSTALL_ASSET_PAGE_SIZE} 条；可点「加载更多」或输入关键字筛选。`
                        : `${assetTotal} assets; listing ${INSTALL_ASSET_PAGE_SIZE} per page. Use “Load more” or type to filter.`}
                    </p>
                  )}
                </div>

                {/* Device list (server-side search via ?q=) */}
                <div>
                  {assetsLoading ? (
                    <div className="p-3 text-center text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '加载中...' : 'Loading...'}</div>
                  ) : assets.length === 0 ? (
                    <div className="p-3 text-center text-[11px]" style={{ color: 'var(--muted-text)' }}>
                      {assetSearch.trim()
                        ? (zh ? '未找到匹配的设备' : 'No devices match your search')
                        : (zh ? '资产库中无可用设备' : 'No devices available in asset library')}
                    </div>
                  ) : (
                    <div className="max-h-56 overflow-y-auto rounded-lg border" style={{ borderColor: 'var(--card-border)', background: 'var(--app-hover-bg)' }}>
                      {assets.map(a => (
                        <button
                          key={a.id}
                          onClick={() => {
                            handleAssetSelect(a);
                            setAssetSearch('');
                          }}
                          className={`w-full text-left p-3 border-b transition-colors hover:opacity-80 ${
                            selectedAsset?.id === a.id ? 'bg-cyan-500/20' : ''
                          }`}
                          style={{ borderColor: 'var(--card-border)' }}
                        >
                          <div className="font-semibold text-[11px]">{a.hostname || a.asset_tag}</div>
                          <div className="text-[10px] mt-0.5" style={{ color: 'var(--muted-text)' }}>
                            {a.vendor} {a.model} • SN: {a.serial_number || '—'}
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                  {assets.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px]" style={{ color: 'var(--muted-text)' }}>
                      <span>
                        {zh ? `已加载 ${assets.length} / ${assetTotal} 台` : `Loaded ${assets.length} / ${assetTotal}`}
                      </span>
                      {installAssetsCanLoadMore && (
                        <button
                          type="button"
                          disabled={assetsLoading}
                          onClick={() => fetchInstallAssets(assetSearch, assetPage + 1, true)}
                          className="px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-opacity disabled:opacity-50"
                          style={{ borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                        >
                          {assetsLoading ? (zh ? '加载中…' : 'Loading…') : (zh ? '加载更多' : 'Load more')}
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Selected Device Details */}
                {selectedAsset && (
                  <div className="rounded-lg p-4" style={{ background: 'var(--app-hover-bg)', border: '2px solid var(--card-border)' }}>
                    <div className="text-sm font-bold mb-3" style={{ color: 'var(--heading-text)' }}>
                      {zh ? '✓ 已选择设备信息' : '✓ Selected Device Information'}
                    </div>
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-3 text-[11px]">
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '设备名称' : 'Device Name'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>{selectedAsset.hostname || selectedAsset.asset_tag}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '序列号' : 'Serial No'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600, fontFamily: 'monospace' }}>{selectedAsset.serial_number || '—'}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '制造商' : 'Vendor'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>{selectedAsset.vendor}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>{selectedAsset.model}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '状态' : 'Status'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>
                            {selectedAsset.status === 'active' ? (zh ? '在用' : 'In Use') :
                             selectedAsset.status === 'in_storage' ? (zh ? '库存中' : 'In Storage') :
                             selectedAsset.status === 'maintenance' ? (zh ? '维护中' : 'Maintenance') :
                             selectedAsset.status === 'inactive' ? (zh ? '闲置' : 'Idle') : selectedAsset.status}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Deployment Configuration */}
                {selectedAsset && (
                  <div className="space-y-3 pt-2 border-t" style={{ borderColor: 'var(--card-border)' }}>
                    <div className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
                      {zh ? '部署配置' : 'Deployment Configuration'}
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '设备名称' : 'Device Name'} *</label>
                      <input
                        value={deviceForm.name}
                        onChange={e => setDeviceForm({ ...deviceForm, name: e.target.value })}
                        className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                        style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                      />
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '设备型号' : 'Device Type'} *</label>
                      <select
                        value={deviceForm.device_type_id}
                        onChange={e => {
                          const device_type_id = e.target.value;
                          const start_u = resolveStartUForInstall(device_type_id, deviceForm.position);
                          setDeviceForm({ ...deviceForm, device_type_id, start_u });
                        }}
                        className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                        style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                      >
                        <option value="" disabled>{zh ? '选择设备型号' : 'Select device type'}</option>
                        {deviceTypes.map(dt => (
                          <option key={dt.id} value={dt.id}>{dt.vendor} {dt.model} ({dt.u_height}U - {dt.device_role})</option>
                        ))}
                      </select>
                      {selectedAsset && !deviceForm.device_type_id && deviceTypes.length > 0 && (
                        <p className="mt-1.5 text-[10px] leading-snug text-amber-600 dark:text-amber-400">
                          {zh
                            ? '未根据厂商/型号自动匹配机柜设备类型，请手动选择；若列表中无对应型号，请先在「设备型号」中新增。'
                            : 'No device type matched this asset’s vendor/model — pick one manually, or add a device type first.'}
                        </p>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '起始U位' : 'Start U'} *</label>
                        <input
                          type="number"
                          min={1}
                          max={layout?.total_u || 60}
                          value={deviceForm.start_u}
                          onChange={e => setDeviceForm({ ...deviceForm, start_u: parseInt(e.target.value) || 1 })}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                          style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '面板' : 'Side'}</label>
                        <select
                          value={deviceForm.position}
                          onChange={e => {
                            const position = e.target.value;
                            const start_u = resolveStartUForInstall(deviceForm.device_type_id, position);
                            setDeviceForm({ ...deviceForm, position, start_u });
                          }}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                          style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                        >
                          <option value="front">{zh ? '前面板' : 'Front'}</option>
                          <option value="rear">{zh ? '后面板' : 'Rear'}</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '状态' : 'Status'}</label>
                        <select
                          value={deviceForm.status}
                          onChange={e => setDeviceForm({ ...deviceForm, status: e.target.value })}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                          style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                        >
                          <option value="active">{zh ? '在线' : 'Active'}</option>
                          <option value="offline">{zh ? '离线' : 'Offline'}</option>
                          <option value="planned">{zh ? '规划中' : 'Planned'}</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}

                {formError && <p className="text-xs text-red-500 mt-2">{formError}</p>}
              </div>

              <div className="flex justify-end gap-2 mt-6 pt-4 border-t" style={{ borderColor: 'var(--card-border)' }}>
                {selectedAsset && (
                  <button
                    onClick={() => {
                      setFormError('');
                      setSelectedAsset(null);
                      setAssetSearch('');
                      setDeviceForm({ name: '', device_type_id: '', start_u: 1, position: 'front', status: 'active', serial_number: '', asset_id: '' });
                    }}
                    className="px-4 py-1.5 rounded-lg text-xs font-medium"
                    style={{ color: 'var(--muted-text)' }}
                  >
                    {zh ? '重新选择' : 'Reselect'}
                  </button>
                )}
                <button
                  onClick={closeInstallModal}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium"
                  style={{ color: 'var(--muted-text)' }}
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={saveDevice}
                  disabled={!selectedAsset}
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white"
                  style={{
                    background: selectedAsset ? 'rgb(6, 182, 212)' : 'rgb(156, 163, 175)',
                    cursor: selectedAsset ? 'pointer' : 'not-allowed',
                  }}
                >
                  {zh ? '确认安装' : 'Confirm Install'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ========== MODAL: Device Types ========== */}
      <AnimatePresence>
        {showDeviceTypeModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowDeviceTypeModal(false)}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-2xl shadow-2xl p-6" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }} onClick={e => e.stopPropagation()}>
              <h3 className="text-base font-bold mb-4" style={{ color: 'var(--heading-text)' }}>
                {zh ? '设备型号管理' : 'Device Type Management'}
              </h3>
              <div className="max-h-48 overflow-auto mb-4 rounded-lg" style={{ border: '1px solid var(--card-border)' }}>
                <table className="w-full text-[11px]">
                  <thead>
                    <tr style={{ background: 'var(--app-hover-bg)' }}>
                      <th className="px-2 py-1.5 text-left font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}</th>
                      <th className="px-2 py-1.5 text-left font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '厂商' : 'Vendor'}</th>
                      <th className="px-2 py-1.5 text-center font-semibold" style={{ color: 'var(--muted-text)' }}>U</th>
                      <th className="px-2 py-1.5 text-left font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '角色' : 'Role'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deviceTypes.map(dt => (
                      <tr key={dt.id} style={{ borderTop: '1px solid var(--card-border)' }}>
                        <td className="px-2 py-1.5 font-medium" style={{ color: 'var(--body-text)' }}>{dt.model}</td>
                        <td className="px-2 py-1.5" style={{ color: 'var(--muted-text)' }}>{dt.vendor}</td>
                        <td className="px-2 py-1.5 text-center font-mono" style={{ color: 'var(--body-text)' }}>{dt.u_height}</td>
                        <td className="px-2 py-1.5">
                          <span className="px-1.5 py-0.5 rounded-full text-[9px] font-semibold" style={{ background: (ROLE_COLORS[dt.device_role]?.bg || '#94a3b8') + '20', color: ROLE_COLORS[dt.device_role]?.bg || '#94a3b8' }}>
                            {zh ? (ROLE_COLORS[dt.device_role]?.labelZh || dt.device_role) : (ROLE_COLORS[dt.device_role]?.label || dt.device_role)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pt-3 border-t" style={{ borderColor: 'var(--card-border)' }}>
                <p className="text-[11px] font-semibold mb-2" style={{ color: 'var(--heading-text)' }}>{zh ? '添加新型号' : 'Add New Type'}</p>
                <div className="grid grid-cols-2 gap-2">
                  <input value={dtForm.model} onChange={e => setDtForm({ ...dtForm, model: e.target.value })} placeholder={zh ? '型号 *' : 'Model *'} className="rounded-lg px-3 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  <input value={dtForm.vendor} onChange={e => setDtForm({ ...dtForm, vendor: e.target.value })} placeholder={zh ? '厂商' : 'Vendor'} className="rounded-lg px-3 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  <div className="flex items-center gap-2">
                    <label className="text-[10px] flex-shrink-0" style={{ color: 'var(--muted-text)' }}>U{zh ? '高度' : ' Height'}:</label>
                    <input type="number" min={1} max={20} value={dtForm.u_height} onChange={e => setDtForm({ ...dtForm, u_height: parseInt(e.target.value) || 1 })} className="w-16 rounded-lg px-2 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <select value={dtForm.device_role} onChange={e => setDtForm({ ...dtForm, device_role: e.target.value })} className="rounded-lg px-2 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}>
                    {Object.entries(ROLE_COLORS).map(([key, rc]) => (
                      <option key={key} value={key}>{zh ? rc.labelZh : rc.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              {formError && <p className="text-xs text-red-500 mt-2">{formError}</p>}
              <div className="flex justify-end gap-2 mt-4">
                <button onClick={() => setShowDeviceTypeModal(false)} className="px-4 py-1.5 rounded-lg text-xs font-medium" style={{ color: 'var(--muted-text)' }}>{zh ? '关闭' : 'Close'}</button>
                <button onClick={saveDeviceType} className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700">{zh ? '添加' : 'Add'}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default RackManagementTab;
