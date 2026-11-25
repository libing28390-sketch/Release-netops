import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import {
  Activity,
  Box,
  Boxes,
  Building2,
  Cable,
  Cpu,
  Download,
  ExternalLink,
  FileJson,
  Flame,
  Hand,
  Layers,
  MousePointer2,
  Network,
  Rotate3d,
  RotateCcw,
  RotateCw,
  ShieldAlert,
  Snowflake,
  Sparkles,
  Trash2,
  Upload,
  Wind,
  X,
  Zap,
} from 'lucide-react';
import { RackSummary } from '../types';
import { API } from '../constants';
import { authHeaders } from '../helpers';
import {
  buildDataCenterRoomModel,
  buildRackFleetLayout,
  computeRackPowerMetrics,
  computeRackThermalMetrics,
  DataCenterEquipmentPlacement,
  OdfFrameRoomInput,
} from './fleetLayout';
import { isWebGLAvailable } from './utils/webgl';
import {
  detectGpuProfile,
  GraphicsQualityMode,
  loadGraphicsPreference,
  resolveRoomRenderBudget,
  saveGraphicsPreference,
} from './gpuProfile';
import {
  DataCenterRoomContent,
  InterRackLink,
  RoomAnalysisMode,
  RoomCameraController,
  RoomCameraPreset,
  RoomLayerVisibility,
  RoomStudioEnvironment,
} from './DataCenterRoomScene';
import {
  disposeGlbObject,
  exportRoomToBlueprintJson,
  exportRoomToGlb,
  exportRoomToThreeSceneJson,
  ImportedGlbAsset,
  parseLocalGlbFile,
  triggerBrowserDownload,
} from './roomSerialization';

function buildDemo100Racks(): RackSummary[] {
  return Array.from({ length: 100 }, (_, i) => {
    const zoneTag =
      i < 20 ? 'CORE'
      : i < 64 ? 'SRV'
      : i < 82 ? 'FW'
      : 'APP';
    const powerW =
      zoneTag === 'SRV' ? 2800 + (i % 5) * 450
      : zoneTag === 'CORE' ? 2200 + (i % 4) * 300
      : 1600 + (i % 3) * 250;
    const usedU = Math.min(40, 12 + (i * 3) % 26);
    return {
      id: `demo-rack-${i + 1}`,
      name: `${zoneTag}-${String(i + 1).padStart(3, '0')}`,
      datacenter: 'DEMO-DC-01',
      site_label: 'DEMO-DC-01',
      floor: '2F',
      room: 'A1模块化机房',
      row: String.fromCharCode(65 + Math.floor(i / 10)),
      total_u: 42,
      description: '100-rack GB 50174 dual-pod layout simulation',
      status: 'active',
      created_at: '',
      updated_at: '',
      device_count: 10,
      front_used: 10,
      rear_used: 0,
      used_u: usedU,
      available_u: 42 - usedU,
      u_utilization_pct: Math.round((usedU / 42) * 100),
      power_used_watts: powerW,
      power_utilization_pct: Math.min(92, Math.round((powerW / 5000) * 100)),
      monitored_device_count: 10,
      healthy_device_count: 10,
      offline_device_count: 0,
      unknown_monitoring_device_count: 0,
      unlinked_asset_count: 0,
      unmonitored_device_count: 0,
      invalid_device_count: 0,
      health_status: 'healthy',
      data_quality_status: 'complete',
    };
  });
}

interface RackFleetOverviewProps {
  racks: RackSummary[];
  selectedRackId: string;
  onSelectRack: (rackId: string) => void;
  onOpenRack: (rackId: string) => void;
  onOpenOdfManager?: (frameId?: string) => void;
  zh: boolean;
}

export const RackFleetOverview: React.FC<RackFleetOverviewProps> = ({
  racks,
  selectedRackId,
  onSelectRack,
  onOpenRack,
  onOpenOdfManager,
  zh,
}) => {
  const [odfFrames, setOdfFrames] = useState<OdfFrameRoomInput[]>([]);
  const [selectedOdfId, setSelectedOdfId] = useState<string | null>(null);
  const [odfDoorOpen, setOdfDoorOpen] = useState(false);
  const [demo100Mode, setDemo100Mode] = useState(false);

  const effectiveRacks = useMemo(
    () => (demo100Mode ? buildDemo100Racks() : racks),
    [demo100Mode, racks],
  );
  const placements = useMemo(() => buildRackFleetLayout(effectiveRacks), [effectiveRacks]);
  const room = useMemo(() => buildDataCenterRoomModel(placements, odfFrames), [placements, odfFrames]);
  const selected = effectiveRacks.find(rack => rack.id === selectedRackId) || null;
  const selectedPlacement = placements.find(p => p.rack.id === selectedRackId) || null;
  const selectedOdfUnit = useMemo(
    () => (selectedOdfId ? room.odfUnits.find(u => u.id === selectedOdfId) || null : null),
    [selectedOdfId, room.odfUnits],
  );
  const webglSupported = useMemo(() => isWebGLAvailable(), []);
  const controlsRef = useRef<any>(null);
  const roomRootRef = useRef<THREE.Group | null>(null);
  const glbFileInputRef = useRef<HTMLInputElement | null>(null);
  const [customModels, setCustomModels] = useState<ImportedGlbAsset[]>([]);
  const customModelsRef = useRef<ImportedGlbAsset[]>([]);
  customModelsRef.current = customModels;
  const [activeCustomModelId, setActiveCustomModelId] = useState<string | null>(null);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [exportBusy, setExportBusy] = useState<string | null>(null);
  const [ioNotice, setIoNotice] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);

  useEffect(() => {
    if (!ioNotice) return;
    const timer = window.setTimeout(() => setIoNotice(null), 4500);
    return () => window.clearTimeout(timer);
  }, [ioNotice]);

  useEffect(() => {
    return () => {
      for (const m of customModelsRef.current) {
        disposeGlbObject(m.object);
      }
    };
  }, []);

  // Load authoritative CMDB ODF frames so 3D ODF cabinets reflect live core occupancy & tray metadata
  useEffect(() => {
    let cancelled = false;
    async function loadOdfFrames() {
      try {
        const res = await fetch(`${API}/odf/frames`, { headers: authHeaders() });
        if (!res.ok || cancelled) return;
        const json = await res.json();
        const items: OdfFrameRoomInput[] = Array.isArray(json?.data)
          ? json.data
          : Array.isArray(json)
            ? json
            : [];
        if (!cancelled) setOdfFrames(items);
      } catch {
        if (!cancelled) setOdfFrames([]);
      }
    }
    loadOdfFrames();
    return () => {
      cancelled = true;
    };
  }, []);

  const gpuProfile = useMemo(() => detectGpuProfile(effectiveRacks.length), [effectiveRacks.length]);
  const [graphicsMode, setGraphicsMode] = useState<GraphicsQualityMode>(() => {
    const pref = loadGraphicsPreference();
    return pref === 'auto' ? detectGpuProfile(effectiveRacks.length).recommendedMode : pref;
  });
  const renderBudget = useMemo(
    () => resolveRoomRenderBudget(graphicsMode, effectiveRacks.length),
    [graphicsMode, effectiveRacks.length],
  );
  const [analysisMode, setAnalysisMode] = useState<RoomAnalysisMode>('physical');
  const [cameraPreset, setCameraPreset] = useState<RoomCameraPreset>('overview');
  const [activeZoneId, setActiveZoneId] = useState<string | null>(null);
  const [presetNonce, setPresetNonce] = useState(0);
  const [interactionMode, setInteractionMode] = useState<'orbit' | 'pan'>('orbit');
  const [spacePanning, setSpacePanning] = useState(false);

  const toggleGraphicsMode = () => {
    setGraphicsMode(prev => {
      const next: GraphicsQualityMode = prev === 'eco' ? 'high' : 'eco';
      saveGraphicsPreference(next);
      return next;
    });
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return;
      const tag = (document.activeElement?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'button') return;
      e.preventDefault();
      setSpacePanning(true);
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') setSpacePanning(false);
    };
    const onBlur = () => setSpacePanning(false);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
    };
  }, []);

  const isPanActive = interactionMode === 'pan' || spacePanning;
  const mouseButtons = useMemo(
    () => (isPanActive
      ? { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE }
      : { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }),
    [isPanActive],
  );

  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;
    ctrl.mouseButtons = mouseButtons;
    if ('zoomToCursor' in ctrl) {
      ctrl.zoomToCursor = true;
    }
  }, [mouseButtons]);

  const [layers, setLayers] = useState<RoomLayerVisibility>(() => ({
    trays: true,
    cooling: true,
    odf: true,
    containment: true,
    airflow: resolveRoomRenderBudget(
      loadGraphicsPreference() === 'auto' ? detectGpuProfile(racks.length).recommendedMode : (loadGraphicsPreference() as GraphicsQualityMode),
      racks.length,
    ).airflowDefault,
    architecture: true,
    fireMep: true,
  }));
  const [interRackLinks, setInterRackLinks] = useState<InterRackLink[]>([]);

  // Derive real cross-rack overhead fiber trunk links from lightweight rack device-index + LLDP topology
  // (single batch request instead of N×/layout waterfall)
  useEffect(() => {
    if (demo100Mode || racks.length < 2 || racks.length > 200) {
      setInterRackLinks([]);
      return;
    }
    let cancelled = false;
    async function loadInterRackTrunks() {
      try {
        const rackIdsParam = racks.map(r => r.id).join(',');
        const [topoRes, indexRes] = await Promise.all([
          fetch(`${API}/topology/links?limit=800`, { headers: authHeaders() }),
          fetch(`${API}/racks/device-index?rack_ids=${encodeURIComponent(rackIdsParam)}`, { headers: authHeaders() }),
        ]);
        if (!topoRes.ok || !indexRes.ok || cancelled) return;
        const [topoData, indexData] = await Promise.all([topoRes.json(), indexRes.json()]);
        const rawLinks: any[] = Array.isArray(topoData) ? topoData : (topoData?.links || []);
        const rawIndex = indexData?.data ?? indexData ?? {};
        const deviceToRack = new Map<string, string>();
        if (Array.isArray(rawIndex)) {
          for (const d of rawIndex) {
            const rackId = String(d.rack_id || '').trim();
            if (!rackId) continue;
            for (const key of [d.id, d.network_device_id, d.name, d.network_hostname, d.hostname, d.physical_hostname]) {
              if (key) deviceToRack.set(String(key).trim().toLowerCase(), rackId);
            }
          }
        } else if (rawIndex && typeof rawIndex === 'object') {
          for (const [rackId, entries] of Object.entries(rawIndex as Record<string, any[]>)) {
            if (!Array.isArray(entries)) continue;
            for (const d of entries) {
              for (const key of [d.id, d.network_device_id, d.name, d.network_hostname, d.hostname, d.physical_hostname]) {
                if (key) deviceToRack.set(String(key).trim().toLowerCase(), rackId);
              }
            }
          }
        }

        const pairCounts = new Map<string, { a: string; b: string; count: number }>();
        for (const l of rawLinks) {
          const srcRack = deviceToRack.get(String(l.source_device_id || '').trim().toLowerCase())
            || deviceToRack.get(String(l.source_hostname_resolved || l.source_hostname || '').trim().toLowerCase());
          const dstRack = deviceToRack.get(String(l.target_device_id || '').trim().toLowerCase())
            || deviceToRack.get(String(l.target_hostname_resolved || l.target_hostname || '').trim().toLowerCase());
          if (!srcRack || !dstRack || srcRack === dstRack) continue;
          const [a, b] = srcRack < dstRack ? [srcRack, dstRack] : [dstRack, srcRack];
          const k = `${a}::${b}`;
          const prev = pairCounts.get(k);
          if (prev) prev.count += 1;
          else pairCounts.set(k, { a, b, count: 1 });
        }

        if (!cancelled) {
          setInterRackLinks(
            Array.from(pairCounts.entries()).map(([k, v]) => ({
              id: k,
              sourceRackId: v.a,
              targetRackId: v.b,
              linkCount: v.count,
              label: `${v.count} LLDP`,
            })),
          );
        }
      } catch {
        if (!cancelled) setInterRackLinks([]);
      }
    }
    loadInterRackTrunks();
    return () => {
      cancelled = true;
    };
  }, [demo100Mode, racks]);

  const toggleDemo100Mode = () => {
    setDemo100Mode(prev => !prev);
    setCameraPreset('overview');
    setActiveZoneId(null);
    setOdfDoorOpen(false);
    setPresetNonce(n => n + 1);
  };

  const toggleLayer = (key: keyof RoomLayerVisibility) => {
    setLayers(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const applyPreset = (preset: RoomCameraPreset, zoneId: string | null = null) => {
    setCameraPreset(preset);
    setActiveZoneId(zoneId);
    if (preset === 'odf_inside') {
      const targetOdf = selectedOdfUnit || room.odfUnits[0] || null;
      if (targetOdf) setSelectedOdfId(targetOdf.id);
      setOdfDoorOpen(true);
    } else if (preset === 'overview' || preset === 'reset') {
      setOdfDoorOpen(false);
    }
    setPresetNonce(n => n + 1);
  };

  const handleInspectOdf = (unit?: DataCenterEquipmentPlacement) => {
    const target = unit || selectedOdfUnit || room.odfUnits[0] || null;
    if (target) setSelectedOdfId(target.id);
    setOdfDoorOpen(true);
    setCameraPreset('odf_inside');
    setActiveZoneId('zone-odf');
    setPresetNonce(n => n + 1);
  };

  const handleSelectRackFromScene = (rackId: string) => {
    setSelectedOdfId(null);
    setOdfDoorOpen(false);
    onSelectRack(rackId);
  };

  const navigateToOdfCmdb = (frameId?: string) => {
    if (onOpenOdfManager) {
      onOpenOdfManager(frameId);
      return;
    }
    const targetPath = frameId ? `/cmdb/odf?frameId=${encodeURIComponent(frameId)}` : '/cmdb/odf';
    try {
      window.history.pushState({}, '', targetPath);
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch {
      window.location.assign(targetPath);
    }
  };

  const activeCustomModel = useMemo(
    () => customModels.find(m => m.id === activeCustomModelId) || customModels[customModels.length - 1] || null,
    [customModels, activeCustomModelId],
  );

  const handleImportGlbFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setExportBusy('import');
    try {
      const corridorZ = room.upsUnits[0]
        ? room.upsUnits[0].position[2] + room.upsUnits[0].depth / 2 + 0.9
        : room.bounds.centerZ;
      const defaultPos: [number, number, number] = [
        room.bounds.centerX + customModels.length * 0.9,
        0,
        corridorZ,
      ];
      const imported = await parseLocalGlbFile(file, defaultPos);
      setCustomModels(prev => [...prev, imported]);
      setActiveCustomModelId(imported.id);
      setIoNotice({
        tone: 'ok',
        text: zh
          ? `已导入模型 ${imported.name}（${imported.sizeMeters.join('×')}m），放置于主走廊`
          : `Imported ${imported.name} (${imported.sizeMeters.join('×')}m) into main corridor`,
      });
    } catch (err) {
      setIoNotice({
        tone: 'err',
        text: zh
          ? `GLB 解析失败: ${err instanceof Error ? err.message : String(err)}`
          : `Failed to parse GLB: ${err instanceof Error ? err.message : String(err)}`,
      });
    } finally {
      setExportBusy(null);
    }
  };

  const updateActiveCustomModel = (updater: (prev: ImportedGlbAsset) => ImportedGlbAsset) => {
    if (!activeCustomModel) return;
    setCustomModels(prev => prev.map(m => (m.id === activeCustomModel.id ? updater(m) : m)));
  };

  const removeCustomModel = (id: string) => {
    setCustomModels(prev => {
      const target = prev.find(m => m.id === id);
      if (target) disposeGlbObject(target.object);
      const next = prev.filter(m => m.id !== id);
      setActiveCustomModelId(curr => (curr === id ? (next[next.length - 1]?.id ?? null) : curr));
      return next;
    });
  };

  const getFileStamp = () => new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

  const handleExportGlb = async () => {
    if (!roomRootRef.current) {
      setIoNotice({ tone: 'err', text: zh ? '3D 场景尚未就绪，请先切至 3D 视图' : '3D scene not ready yet' });
      return;
    }
    setExportMenuOpen(false);
    setExportBusy('glb');
    try {
      const blob = await exportRoomToGlb(roomRootRef.current);
      triggerBrowserDownload(blob, `datacenter-hall-${getFileStamp()}.glb`);
      const sizeMb = (blob.size / (1024 * 1024)).toFixed(2);
      setIoNotice({
        tone: 'ok',
        text: zh ? `已导出整机房 3D 模型 (.glb · ${sizeMb} MB)` : `Exported 3D Hall GLB (${sizeMb} MB)`,
      });
    } catch (err) {
      setIoNotice({
        tone: 'err',
        text: zh ? `GLB 导出失败: ${err instanceof Error ? err.message : String(err)}` : `GLB export failed`,
      });
    } finally {
      setExportBusy(null);
    }
  };

  const handleExportBlueprintJson = () => {
    setExportMenuOpen(false);
    setExportBusy('blueprint');
    try {
      const blob = exportRoomToBlueprintJson({
        room,
        placements,
        analysisMode,
        layers: layers as unknown as Record<string, boolean>,
        interRackLinks,
        customModels,
      });
      triggerBrowserDownload(blob, `datacenter-blueprint-${getFileStamp()}.json`);
      const sizeKb = (blob.size / 1024).toFixed(1);
      setIoNotice({
        tone: 'ok',
        text: zh ? `已导出机房蓝图配置 JSON (${sizeKb} KB)` : `Exported Blueprint JSON (${sizeKb} KB)`,
      });
    } finally {
      setExportBusy(null);
    }
  };

  const handleExportThreeSceneJson = () => {
    if (!roomRootRef.current) {
      setIoNotice({ tone: 'err', text: zh ? '3D 场景尚未就绪，请先切至 3D 视图' : '3D scene not ready yet' });
      return;
    }
    setExportMenuOpen(false);
    setExportBusy('scene-json');
    try {
      const blob = exportRoomToThreeSceneJson(roomRootRef.current);
      triggerBrowserDownload(blob, `datacenter-scene-${getFileStamp()}.scene.json`);
      const sizeMb = (blob.size / (1024 * 1024)).toFixed(2);
      setIoNotice({
        tone: 'ok',
        text: zh ? `已导出 Three.js 完整场景 JSON (${sizeMb} MB)` : `Exported Three.js Scene JSON (${sizeMb} MB)`,
      });
    } catch (err) {
      setIoNotice({
        tone: 'err',
        text: zh ? `场景 JSON 导出失败: ${err instanceof Error ? err.message : String(err)}` : `Scene JSON export failed`,
      });
    } finally {
      setExportBusy(null);
    }
  };

  if (!effectiveRacks.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm" style={{ color: 'var(--muted-text)' }}>
        {zh ? '当前筛选没有可展示的机柜摘要' : 'No rack summaries match the current filters.'}
      </div>
    );
  }

  const span = Math.max(10, Math.max(room.bounds.width, room.bounds.depth));
  const selectedPower = selected ? computeRackPowerMetrics(selected) : null;
  const selectedThermal = selected ? computeRackThermalMetrics(selected) : null;

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[#080d16] text-slate-200">
      {/* Docked Dark Data Center Room Control Bar (wraps cleanly, never clips right edge) */}
      <div className="z-20 flex shrink-0 flex-wrap items-center justify-between gap-1.5 border-b border-slate-800/90 bg-slate-950/95 px-2.5 py-1.5 text-[11px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="flex items-center gap-1 rounded-md border border-cyan-500/35 bg-cyan-500/10 px-2 py-0.5 font-bold text-cyan-300">
            <Building2 size={12} />
            {zh ? '整机房 3D' : '3D Hall'}
          </span>

          {/* Dynamic Functional Zone + Engineering Section Camera Tabs */}
          <div className="flex flex-wrap items-center rounded-lg border border-slate-800 bg-slate-900/90 p-0.5">
            <button
              type="button"
              onClick={() => applyPreset('overview', null)}
              className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                cameraPreset === 'overview' && !activeZoneId ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {zh ? '总览' : 'Overview'}
            </button>
            {room.zones.map(zone => (
              <button
                key={zone.id}
                type="button"
                onClick={() => applyPreset('zone', zone.id)}
                className={`flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  cameraPreset === 'zone' && activeZoneId === zone.id
                    ? 'bg-cyan-600 text-white'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
                title={`${zh ? zone.labelZh : zone.labelEn} (${zone.rackCount})`}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: zone.accentColor }} />
                <span>{zh ? zone.labelZh : zone.labelEn}</span>
              </button>
            ))}
            {room.odfUnits.length > 0 && (
              <button
                type="button"
                onClick={() => applyPreset('odf_inside', 'zone-odf')}
                className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  cameraPreset === 'odf_inside' ? 'bg-amber-600 text-white' : 'text-amber-300/90 hover:bg-slate-800 hover:text-amber-200'
                }`}
                title={zh ? '近距离检查 ODF 熔配盘与盘纤轮' : 'Inspect ODF splice trays & spools'}
              >
                {zh ? 'ODF 内部' : 'ODF Inside'}
              </button>
            )}
            <div className="mx-0.5 h-3 w-[1px] bg-slate-700" />
            {([
              { id: 'aisle', label: zh ? '冷通道' : 'Aisle' },
              { id: 'trays', label: zh ? '俯视走线' : 'Trays' },
              { id: 'section', label: zh ? '侧视剖面' : 'Section' },
            ] as Array<{ id: RoomCameraPreset; label: string }>).map(btn => (
              <button
                key={btn.id}
                type="button"
                onClick={() => applyPreset(btn.id, null)}
                className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  cameraPreset === btn.id ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {btn.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => applyPreset('reset', null)}
              className="ml-0.5 rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              title={zh ? '重置机房视角' : 'Reset View'}
            >
              <RotateCcw size={11} />
            </button>
          </div>

          {/* Orbit vs Pan Mouse Mode Toggle */}
          <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900/90 p-0.5 text-[10px]">
            <button
              type="button"
              onClick={() => setInteractionMode('orbit')}
              className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium ${
                interactionMode === 'orbit' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '左键旋转视角（右键或按住空格平移，滚轮指向缩放）' : 'Orbit mode'}
            >
              <Rotate3d size={10} />
              {zh ? '旋转' : 'Orbit'}
            </button>
            <button
              type="button"
              onClick={() => setInteractionMode('pan')}
              className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium ${
                interactionMode === 'pan' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '左键平移画面' : 'Pan mode'}
            >
              <Hand size={10} />
              {zh ? '平移' : 'Pan'}
            </button>
          </div>

          {/* Infrastructure Layer Toggles */}
          <div className="flex flex-wrap items-center gap-1 rounded-lg border border-slate-800 bg-slate-900/90 px-1.5 py-0.5">
            <span className="mr-0.5 flex items-center text-[10px] text-slate-500">
              <Layers size={10} />
            </span>
            <button
              type="button"
              onClick={() => toggleLayer('trays')}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.trays ? 'bg-amber-500/20 text-amber-300 border border-amber-500/35' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Cable size={10} />
              {zh ? '桥架' : 'Trays'}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer('odf')}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.odf ? 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/35' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Network size={10} />
              {zh ? 'ODF' : 'ODF'}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer('cooling')}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.cooling ? 'bg-sky-500/20 text-sky-300 border border-sky-500/35' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Snowflake size={10} />
              {zh ? '空调/配电' : 'CRAC/PDF'}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer('containment')}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.containment ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/35' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Box size={10} />
              {zh ? '冷通道' : 'Aisle'}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer('airflow')}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.airflow ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/35' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Wind size={10} />
              {zh ? '气流' : 'Airflow'}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer('architecture')}
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.architecture ? 'bg-slate-700/80 text-slate-200 border border-slate-600/60' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {zh ? '分区/墙柱' : 'Zones'}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer('fireMep')}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                layers.fireMep ? 'bg-rose-500/20 text-rose-300 border border-rose-500/35' : 'text-slate-500 hover:text-slate-300'
              }`}
              title={zh ? 'GB 50174/50370 气体灭火管网、烟温感、冷冻水路与漏水检测、等电位接地' : 'FM-200 fire suppression, CHW piping, leak detection & grounding'}
            >
              <ShieldAlert size={10} />
              {zh ? '消防/水路' : 'Fire/MEP'}
            </button>
          </div>
        </div>

        {/* Right Side: Eco/High GPU Toggle + Real / Power / Thermal Mode + Compact KPIs */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={toggleGraphicsMode}
            data-testid="room-graphics-toggle"
            className={`flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-semibold transition-colors ${
              graphicsMode === 'eco'
                ? 'border-emerald-500/45 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25'
                : 'border-violet-500/45 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25'
            }`}
            title={zh
              ? (graphicsMode === 'eco'
                ? `已启用核显流畅模式（禁用实时阴影/IBL/1x采样/实例合批）${gpuProfile.renderer ? ` · GPU: ${gpuProfile.renderer}` : ''} · 点击切换高清画质`
                : `当前高清画质 · 点击切回核显流畅模式`)
              : (graphicsMode === 'eco' ? 'Integrated GPU Eco Mode (click for High)' : 'High Quality Mode (click for Eco)')}
          >
            {graphicsMode === 'eco' ? <Cpu size={11} /> : <Sparkles size={11} />}
            <span>{graphicsMode === 'eco' ? (zh ? '核显流畅' : 'iGPU Eco') : (zh ? '高清' : 'High')}</span>
          </button>

          <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900/90 p-0.5 text-[10px]">
            <button
              type="button"
              onClick={() => setAnalysisMode('physical')}
              className={`flex items-center gap-1 rounded-md px-2 py-0.5 font-medium ${
                analysisMode === 'physical' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '真实机柜外观与设备健康状态' : 'Physical appearance & health'}
            >
              <Activity size={10} />
              {zh ? '实景' : 'Real'}
            </button>
            <button
              type="button"
              onClick={() => setAnalysisMode('power')}
              className={`flex items-center gap-1 rounded-md px-2 py-0.5 font-medium ${
                analysisMode === 'power' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '透视机柜功率负载柱 + 点亮 UPS/PDF/A-B 强电母线' : 'X-ray power capacity columns & A/B busway view'}
            >
              <Zap size={10} />
              {zh ? '电力' : 'Power'}
            </button>
            <button
              type="button"
              onClick={() => setAnalysisMode('thermal')}
              className={`flex items-center gap-1 rounded-md px-2 py-0.5 font-medium ${
                analysisMode === 'thermal' ? 'bg-rose-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? 'CFD 冷热通道温度场 + 背面热排风羽流' : 'CFD thermal heatmap & hot-aisle plumes'}
            >
              <Flame size={10} />
              {zh ? '热力' : 'Thermal'}
            </button>
          </div>

          <div className="hidden items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900/80 px-2 py-0.5 text-[10px] text-slate-300 2xl:flex">
            <span>{room.totals.rackCount}{zh ? '柜' : 'R'}</span>
            <span className="text-slate-600">|</span>
            <span className="text-amber-300">{room.totals.totalPowerKw}kW</span>
          </div>

          <button
            type="button"
            onClick={toggleDemo100Mode}
            data-testid="room-demo-100-btn"
            className={`flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-semibold transition-colors ${
              demo100Mode
                ? 'border-amber-400/70 bg-amber-500/25 text-amber-200 hover:bg-amber-500/35'
                : 'border-slate-700 bg-slate-900/90 text-slate-300 hover:bg-slate-800'
            }`}
            title={zh ? '非破坏性切换为 100 个机柜预览 GB 50174 双列微模块布局（不影响真实 CMDB）' : 'Preview 100-rack GB 50174 Dual-Pod hall layout (non-destructive)'}
          >
            <Boxes size={10} />
            <span>{demo100Mode ? (zh ? '退出 100 柜预览' : 'Exit 100R') : (zh ? '模拟 100 柜' : '100R Demo')}</span>
          </button>

          {/* Import External GLB & Export Hall (GLB / Blueprint JSON / Three.js Scene JSON) */}
          <input
            ref={glbFileInputRef}
            type="file"
            accept=".glb,.gltf"
            onChange={handleImportGlbFile}
            className="hidden"
          />
          <button
            type="button"
            disabled={exportBusy !== null}
            onClick={() => glbFileInputRef.current?.click()}
            data-testid="room-import-glb-btn"
            className="flex items-center gap-1 rounded-lg border border-indigo-500/45 bg-indigo-500/15 px-2 py-0.5 text-[10px] font-semibold text-indigo-200 transition-colors hover:bg-indigo-500/25 disabled:opacity-50"
            title={zh ? '导入外部 .glb / .gltf 3D 设备模型并放入机房' : 'Import .glb / .gltf 3D model into hall'}
          >
            <Upload size={10} />
            <span>{zh ? '导入 GLB' : 'Import GLB'}</span>
          </button>

          <div className="relative">
            <button
              type="button"
              disabled={exportBusy !== null}
              onClick={() => setExportMenuOpen(prev => !prev)}
              data-testid="room-export-menu-btn"
              className="flex items-center gap-1 rounded-lg border border-teal-500/45 bg-teal-500/15 px-2 py-0.5 text-[10px] font-semibold text-teal-200 transition-colors hover:bg-teal-500/25 disabled:opacity-50"
              title={zh ? '导出整机房 .glb 模型、蓝图 .json 或 Three.js 场景 JSON' : 'Export 3D Hall (.glb / Blueprint .json / Scene .json)'}
            >
              <Download size={10} />
              <span>{exportBusy ? (zh ? '导出中...' : 'Exporting...') : (zh ? '导出 3D/JSON' : 'Export')}</span>
            </button>
            {exportMenuOpen && (
              <div className="absolute right-0 top-full z-40 mt-1.5 w-64 rounded-xl border border-slate-700/80 bg-slate-950/98 p-1.5 text-[11px] shadow-2xl">
                <button
                  type="button"
                  onClick={handleExportBlueprintJson}
                  className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-slate-200 hover:bg-slate-800/80"
                >
                  <FileJson size={14} className="mt-0.5 shrink-0 text-amber-400" />
                  <div>
                    <div className="font-semibold text-amber-200">{zh ? '导出机房蓝图配置 (.json)' : 'Export Blueprint (.json)'}</div>
                    <div className="text-[9px] text-slate-400">{zh ? 'CMDB 机柜坐标 + GB 50174 分区与基础设施元数据' : 'Lightweight CMDB rack layout & infra metadata'}</div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={handleExportGlb}
                  className="mt-0.5 flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-slate-200 hover:bg-slate-800/80"
                >
                  <Boxes size={14} className="mt-0.5 shrink-0 text-cyan-400" />
                  <div>
                    <div className="font-semibold text-cyan-200">{zh ? '导出整机房 3D 模型 (.glb)' : 'Export 3D Hall (.glb)'}</div>
                    <div className="text-[9px] text-slate-400">{zh ? '标准二进制 glTF，兼容 Blender / 数字孪生大屏' : 'Binary glTF for Blender & digital-twin viewers'}</div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={handleExportThreeSceneJson}
                  className="mt-0.5 flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-slate-200 hover:bg-slate-800/80"
                >
                  <FileJson size={14} className="mt-0.5 shrink-0 text-emerald-400" />
                  <div>
                    <div className="font-semibold text-emerald-200">{zh ? '导出 Three.js 场景 (.scene.json)' : 'Export Three.js Scene (.json)'}</div>
                    <div className="text-[9px] text-slate-400">{zh ? '含几何体、材质、纹理贴图与已合批实例网格' : 'Full Three.js ObjectLoader JSON with textures'}</div>
                  </div>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main 3D Data Center Hall Canvas */}
      <div className={`relative min-h-0 flex-1 ${isPanActive ? 'cursor-grab active:cursor-grabbing' : ''}`}>
        {webglSupported ? (
          <Canvas
            shadows={renderBudget.shadows}
            camera={{
              position: [
                room.bounds.centerX + Math.min(28, Math.max(7.2, span * 0.56)),
                Math.min(22, Math.max(5.8, span * 0.44)),
                room.bounds.centerZ + Math.min(34, Math.max(8.4, span * 0.68)),
              ],
              fov: 42,
              near: 0.05,
              far: 320,
            }}
            dpr={renderBudget.dpr}
            gl={{
              antialias: true,
              alpha: false,
              powerPreference: graphicsMode === 'eco' ? 'default' : 'high-performance',
              toneMapping: THREE.ACESFilmicToneMapping,
              toneMappingExposure: 1.08,
              preserveDrawingBuffer: false,
            }}
          >
            <color attach="background" args={['#080d16']} />
            <fog attach="fog" args={['#080d16', Math.max(36, span * 1.9), Math.max(90, span * 4.5)]} />
            {renderBudget.useIbl ? (
              <RoomStudioEnvironment />
            ) : (
              <hemisphereLight args={['#dbeafe', '#1e293b', 0.85]} />
            )}
            <ambientLight intensity={renderBudget.useIbl ? 0.48 : 0.62} color="#dbeafe" />
            <directionalLight
              position={[12, 18, 14]}
              intensity={renderBudget.useIbl ? 1.35 : 1.45}
              color="#ffffff"
              castShadow={renderBudget.shadows}
              shadow-mapSize-width={1024}
              shadow-mapSize-height={1024}
            />
            <directionalLight position={[-12, 10, -8]} intensity={0.65} color="#93c5fd" />

            <RoomCameraController
              room={room}
              preset={cameraPreset}
              activeZoneId={activeZoneId}
              selectedOdfId={selectedOdfId}
              presetNonce={presetNonce}
              selectedPlacement={selectedPlacement}
              controlsRef={controlsRef}
            />

            <DataCenterRoomContent
              room={room}
              placements={placements}
              selectedRackId={selectedRackId}
              selectedOdfId={selectedOdfId}
              odfDoorOpen={odfDoorOpen}
              activeZoneId={activeZoneId}
              analysisMode={analysisMode}
              layers={layers}
              interRackLinks={interRackLinks}
              renderBudget={renderBudget}
              roomRootRef={roomRootRef}
              customModels={customModels}
              zh={zh}
              onSelectRack={handleSelectRackFromScene}
              onOpenRack={onOpenRack}
              onInspectOdf={handleInspectOdf}
            />

            <OrbitControls
              ref={controlsRef}
              makeDefault
              target={[room.bounds.centerX, 1.15, room.bounds.centerZ]}
              enableDamping
              dampingFactor={0.08}
              screenSpacePanning
              zoomToCursor
              mouseButtons={mouseButtons}
              panSpeed={1.15}
              zoomSpeed={1.2}
              minDistance={1.4}
              maxDistance={150}
              maxPolarAngle={Math.PI / 2 - 0.04}
            />
          </Canvas>
        ) : (
          <div className="grid h-full content-start grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-2 overflow-auto p-4">
            {effectiveRacks.map(rack => (
              <button
                key={rack.id}
                type="button"
                onClick={() => onSelectRack(rack.id)}
                onDoubleClick={() => onOpenRack(rack.id)}
                className={`rounded-lg border p-3 text-left ${rack.id === selectedRackId ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 bg-slate-900'}`}
              >
                <div className="font-semibold">{rack.name}</div>
                <div className="mt-1 text-[10px] text-slate-400">{rack.site_label} / {rack.floor || '—'} / {rack.room || '—'} / {rack.row || '—'}</div>
              </button>
            ))}
          </div>
        )}

        {/* 100-Rack Simulation Active Banner */}
        {demo100Mode && !ioNotice && (
          <div className="absolute left-1/2 top-3 z-20 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-amber-500/50 bg-slate-950/92 px-3 py-1 text-[10px] font-medium text-amber-200 shadow-xl">
            <span>
              {zh
                ? `仿真预览模式：100 机柜 GB 50174 双列微模块（${room.rows.length} 排 · ${room.coldAisles.length} 封闭冷通道 · ${room.upsUnits.length} 台 UPS · 总负载 ${room.totals.totalPowerKw}kW）`
                : `100-Rack Simulation (${room.rows.length} rows · ${room.coldAisles.length} cold aisles · ${room.upsUnits.length} UPS)`}
            </span>
            <button
              type="button"
              onClick={toggleDemo100Mode}
              className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-semibold hover:bg-amber-500/30"
            >
              {zh ? '返回实景' : 'Exit'}
            </button>
          </div>
        )}

        {/* Import / Export Status Toast */}
        {ioNotice && (
          <div
            className={`absolute left-1/2 top-3 z-30 flex -translate-x-1/2 items-center gap-2 rounded-lg border px-3 py-1.5 text-[11px] font-medium shadow-xl ${
              ioNotice.tone === 'err'
                ? 'border-rose-500/50 bg-rose-950/95 text-rose-200'
                : 'border-teal-500/50 bg-slate-950/95 text-teal-200'
            }`}
          >
            <span>{ioNotice.text}</span>
            <button type="button" onClick={() => setIoNotice(null)} className="text-slate-400 hover:text-white">
              <X size={12} />
            </button>
          </div>
        )}

        {/* Active Imported GLB Placement Controls Bar */}
        {activeCustomModel && (
          <div className="absolute left-3 top-3 z-20 flex flex-wrap items-center gap-1.5 rounded-xl border border-indigo-500/40 bg-slate-950/95 px-2.5 py-1.5 text-[10px] shadow-2xl">
            <Boxes size={12} className="text-indigo-400" />
            <span className="max-w-36 truncate font-semibold text-indigo-200" title={activeCustomModel.name}>
              {activeCustomModel.name}
            </span>
            <span className="text-slate-500">
              ({activeCustomModel.sizeMeters.join('×')}m)
            </span>
            {customModels.length > 1 && (
              <select
                value={activeCustomModel.id}
                onChange={e => setActiveCustomModelId(e.target.value)}
                className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-[10px] text-slate-200"
              >
                {customModels.map((m, idx) => (
                  <option key={m.id} value={m.id}>
                    #{idx + 1} {m.name}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              onClick={() =>
                updateActiveCustomModel(m => ({ ...m, rotationY: m.rotationY + Math.PI / 2 }))
              }
              className="flex items-center gap-0.5 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-slate-200 hover:bg-slate-800"
              title={zh ? '顺时针旋转 90°' : 'Rotate 90°'}
            >
              <RotateCw size={10} /> 90°
            </button>
            <button
              type="button"
              onClick={() =>
                updateActiveCustomModel(m => ({ ...m, scale: Number(Math.max(0.25, m.scale * 0.85).toFixed(2)) }))
              }
              className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-slate-200 hover:bg-slate-800"
              title={zh ? '缩小' : 'Scale down'}
            >
              -
            </button>
            <span className="font-mono text-indigo-300">{activeCustomModel.scale}×</span>
            <button
              type="button"
              onClick={() =>
                updateActiveCustomModel(m => ({ ...m, scale: Number(Math.min(4, m.scale * 1.15).toFixed(2)) }))
              }
              className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-slate-200 hover:bg-slate-800"
              title={zh ? '放大' : 'Scale up'}
            >
              +
            </button>
            <div className="flex items-center gap-0.5">
              {([
                { label: '←', dx: -0.3, dz: 0 },
                { label: '→', dx: 0.3, dz: 0 },
                { label: '↑', dx: 0, dz: -0.3 },
                { label: '↓', dx: 0, dz: 0.3 },
              ]).map(nudge => (
                <button
                  key={nudge.label}
                  type="button"
                  onClick={() =>
                    updateActiveCustomModel(m => ({
                      ...m,
                      position: [
                        Number((m.position[0] + nudge.dx).toFixed(2)),
                        m.position[1],
                        Number((m.position[2] + nudge.dz).toFixed(2)),
                      ],
                    }))
                  }
                  className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-slate-300 hover:bg-slate-800"
                >
                  {nudge.label}
                </button>
              ))}
            </div>
            {selectedPlacement && (
              <button
                type="button"
                onClick={() =>
                  updateActiveCustomModel(m => ({
                    ...m,
                    position: [
                      selectedPlacement.position[0],
                      0,
                      Number((selectedPlacement.position[2] + selectedPlacement.facing * 1.05).toFixed(2)),
                    ],
                    attachedRackId: selectedPlacement.rack.id,
                  }))
                }
                className="rounded border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-0.5 text-cyan-200 hover:bg-cyan-500/25"
                title={zh ? '移至当前选中机柜前方' : 'Move in front of selected rack'}
              >
                {zh ? '移至选中柜' : 'Snap Rack'}
              </button>
            )}
            <button
              type="button"
              onClick={() => removeCustomModel(activeCustomModel.id)}
              className="rounded border border-rose-500/40 bg-rose-500/15 p-1 text-rose-300 hover:bg-rose-500/25"
              title={zh ? '移除该导入模型' : 'Remove imported model'}
            >
              <Trash2 size={10} />
            </button>
          </div>
        )}

        {/* Bottom-left Dynamic Mode Legend & Live Hall Telemetry Summary */}
        <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-2.5 rounded-xl border border-slate-700/70 bg-slate-950/92 px-3 py-1.5 text-[10px] shadow-xl">
          {analysisMode === 'power' ? (
            <>
              <span className="font-bold text-amber-400 flex items-center gap-1">
                <Zap size={11} />
                {zh ? '电力负载:' : 'Power Load:'}
              </span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-slate-600" />{zh ? '空载' : 'Idle'}</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-sky-400" />&lt;35%</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-emerald-400" />35-60%</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-amber-400" />60-80%</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-red-500" />≥80%</span>
              <span className="h-3 w-[1px] bg-slate-700" />
              <span className="text-amber-300 font-semibold">
                {zh ? `全厅 ${room.totals.totalPowerKw} kW · 峰值 ${room.totals.peakPowerRackName} (${room.totals.peakPowerKw} kW)` : `Hall ${room.totals.totalPowerKw} kW · Peak ${room.totals.peakPowerRackName} (${room.totals.peakPowerKw} kW)`}
              </span>
            </>
          ) : analysisMode === 'thermal' ? (
            <>
              <span className="font-bold text-rose-400 flex items-center gap-1">
                <Flame size={11} />
                {zh ? 'CFD 排风温度:' : 'Thermal Exhaust:'}
              </span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-blue-600" />19.5°C</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-cyan-400" />21-27°C</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-amber-400" />27-34°C</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-orange-500" />34-42°C</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-red-500" />≥42°C</span>
              <span className="h-3 w-[1px] bg-slate-700" />
              <span className="text-rose-300 font-semibold">
                {zh ? `最高排风 ${room.totals.hottestRackName} (${room.totals.hottestTempC}°C)` : `Hottest ${room.totals.hottestRackName} (${room.totals.hottestTempC}°C)`}
              </span>
            </>
          ) : (
            <>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-yellow-400" />{zh ? '弱电光纤槽道 / ODF' : 'Fiber Tray / ODF'}</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-slate-400" />{zh ? '强电 A/B 母线' : 'A/B Power Tray'}</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-sky-400" />{zh ? '冷通道 / CRAC' : 'Cold / CRAC'}</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-rose-400" />{zh ? '热排风' : 'Hot Exhaust'}</span>
              {interRackLinks.length > 0 && (
                <span className="rounded border border-cyan-500/35 bg-cyan-500/10 px-1.5 py-0.5 text-cyan-300">
                  {interRackLinks.length} {zh ? '组跨柜光缆' : 'inter-rack trunks'}
                </span>
              )}
            </>
          )}
        </div>

        {/* Bottom-right CMDB ODF Inspector Card (when an ODF is selected) OR Selected Rack Drill-down Card */}
        {selectedOdfUnit ? (
          <div className="absolute bottom-3 right-3 w-80 rounded-xl border border-amber-500/40 bg-slate-950/95 p-3 text-xs shadow-2xl">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-bold text-white">{selectedOdfUnit.label}</span>
                </div>
                <div className="mt-0.5 truncate text-[10px] text-slate-400">
                  {selectedOdfUnit.odfFrame
                    ? `${selectedOdfUnit.odfFrame.vendor || 'ODF'} ${selectedOdfUnit.odfFrame.model || ''} · ${selectedOdfUnit.odfFrame.site_label || '默认站点'}${selectedOdfUnit.odfFrame.room ? ` / ${selectedOdfUnit.odfFrame.room}` : ''}`
                    : (zh ? '尚未在 CMDB 中建档（当前为规划位预览）' : 'Not yet registered in CMDB (planned placeholder)')}
                </div>
              </div>
              <span
                className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-semibold ${
                  selectedOdfUnit.isPlaceholder
                    ? 'border-slate-600/70 bg-slate-800/80 text-slate-300'
                    : 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                }`}
              >
                {selectedOdfUnit.isPlaceholder
                  ? (zh ? '未录入 CMDB' : 'Unregistered')
                  : (zh ? 'CMDB 实态' : 'CMDB Live')}
              </span>
            </div>

            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[10px]">
              <div className="rounded bg-slate-900 p-1.5">
                <strong className="block text-amber-300">
                  {selectedOdfUnit.odfFrame
                    ? `${selectedOdfUnit.odfFrame.occupied_cores}/${selectedOdfUnit.odfFrame.total_cores}`
                    : `0/${selectedOdfUnit.fiberCores || 576}`}
                </strong>
                {zh ? '在用/总芯数' : 'Used/Total'}
              </div>
              <div className="rounded bg-slate-900 p-1.5">
                <strong className="block text-white">
                  {selectedOdfUnit.odfFrame ? `${selectedOdfUnit.odfFrame.utilization_pct}%` : '—'}
                </strong>
                {zh ? '纤芯利用率' : 'Utilization'}
              </div>
              <div className="rounded bg-slate-900 p-1.5">
                <strong className={`block ${(selectedOdfUnit.odfFrame?.fault_cores || 0) > 0 ? 'text-rose-400' : 'text-emerald-300'}`}>
                  {selectedOdfUnit.odfFrame
                    ? (selectedOdfUnit.odfFrame.fault_cores > 0
                      ? `${selectedOdfUnit.odfFrame.fault_cores} ${zh ? '故障' : 'Fault'}`
                      : `${selectedOdfUnit.odfFrame.tray_count} ${zh ? '盘' : 'Trays'}`)
                    : '12 盘'}
                </strong>
                {(selectedOdfUnit.odfFrame?.fault_cores || 0) > 0
                  ? (zh ? '异常告警' : 'Faults')
                  : (zh ? '熔配单元' : 'Subracks')}
              </div>
            </div>

            {selectedOdfUnit.odfFrame?.trays && selectedOdfUnit.odfFrame.trays.length > 0 && (
              <div className="mt-2 max-h-24 space-y-1 overflow-auto rounded-lg border border-slate-800 bg-slate-900/70 p-1.5 text-[10px]">
                {selectedOdfUnit.odfFrame.trays.slice(0, 6).map(tray => {
                  const pct = Math.min(100, Math.round((tray.occupied_count / Math.max(1, tray.port_count)) * 100));
                  return (
                    <div key={tray.id} className="flex items-center gap-2">
                      <span className="w-8 shrink-0 font-mono font-bold text-slate-300">{tray.tray_code}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className={`h-full rounded-full ${tray.fault_count > 0 ? 'bg-rose-500' : tray.fiber_mode.includes('OM') ? 'bg-cyan-500' : 'bg-amber-400'}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-14 shrink-0 text-right font-mono text-[9px] text-slate-400">
                        {tray.occupied_count}/{tray.port_count}F
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="mt-2 flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setOdfDoorOpen(prev => !prev)}
                className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-[11px] font-medium text-slate-200 hover:bg-slate-800"
              >
                {odfDoorOpen ? (zh ? '关闭玻璃门' : 'Close Door') : (zh ? '开门检视' : 'Open Door')}
              </button>
              <button
                type="button"
                onClick={() => navigateToOdfCmdb(selectedOdfUnit.odfFrame?.id)}
                className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-amber-600 px-3 py-2 text-[11px] font-semibold text-white hover:bg-amber-500"
              >
                <ExternalLink size={12} />
                {selectedOdfUnit.isPlaceholder
                  ? (zh ? '去 CMDB 建档 ODF' : 'Register ODF in CMDB')
                  : (zh ? '进入 ODF 光配管理' : 'Open ODF CMDB')}
              </button>
            </div>
            <div className="mt-1.5 flex items-center justify-between text-[9px] text-slate-500">
              <span>{zh ? '3D 纤芯密度与端子状态实时同步 CMDB' : '3D fiber density synced live with CMDB'}</span>
              <button
                type="button"
                onClick={() => {
                  setSelectedOdfId(null);
                  setOdfDoorOpen(false);
                }}
                className="text-slate-400 hover:text-slate-200"
              >
                {zh ? '关闭' : 'Dismiss'}
              </button>
            </div>
          </div>
        ) : selected && selectedPower && selectedThermal && (
          <div className="absolute bottom-3 right-3 w-72 rounded-xl border border-cyan-500/35 bg-slate-950/95 p-3 text-xs shadow-2xl">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-bold text-white">{selected.name}</div>
                <div className="mt-0.5 truncate text-[10px] text-slate-400">
                  {selected.site_label} / {selected.floor || '—'} / {selected.room || '—'} / {selected.row || '—'}
                </div>
              </div>
              <span className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[9px] text-cyan-300">
                {selectedPlacement?.archetype === 'chassis_core'
                  ? (zh ? '框式核心柜' : 'Core Chassis')
                  : selectedPlacement?.archetype === 'odf'
                    ? 'ODF'
                    : (zh ? '智能分区' : 'Zoned')}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[10px]">
              <div className="rounded bg-slate-900 p-1.5">
                <strong className="block text-white">{selected.used_u}/{selected.total_u}U</strong>
                {zh ? 'U位占用' : 'U Used'}
              </div>
              <div className="rounded bg-slate-900 p-1.5">
                <strong className="block text-amber-300">{selectedPower.kw} kW</strong>
                {zh ? `负载 ${selectedPower.utilizationPct}%` : `Load ${selectedPower.utilizationPct}%`}
              </div>
              <div className="rounded bg-slate-900 p-1.5">
                <strong className={`block ${selectedThermal.exhaustC >= 34 ? 'text-rose-400' : selectedThermal.exhaustC >= 27 ? 'text-amber-300' : 'text-sky-300'}`}>
                  {selectedThermal.exhaustC}°C
                </strong>
                {zh ? '估算排风' : 'Exhaust'}
              </div>
            </div>
            <button
              type="button"
              onClick={() => onOpenRack(selected.id)}
              className="mt-2 flex w-full items-center justify-center gap-1 rounded-lg bg-cyan-600 px-3 py-2 text-[11px] font-semibold text-white hover:bg-cyan-700"
            >
              <ExternalLink size={12} /> {zh ? '下钻单机柜 3D 孪生' : 'Open 3D Rack Twin'}
            </button>
            <div className="mt-1.5 flex items-center justify-center gap-1 text-[9px] text-slate-500">
              <MousePointer2 size={9} />{zh ? '单击聚焦机柜 · 双击下钻 · 点 ODF 看熔配盘' : 'Click to focus · Double-click to open · Click ODF'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
