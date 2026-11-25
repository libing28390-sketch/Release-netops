import React, { useState, useEffect, useRef } from 'react';
import {
  RotateCcw,
  Layers,
  AlertTriangle,
  Info,
  Maximize2,
  Minimize2,
  Search,
  Activity,
  Zap,
  Tag,
  Cable,
  Eye,
  ZoomIn,
  ZoomOut,
  Columns3,
  RefreshCw,
  ChevronDown,
  Hand,
  Lightbulb,
  Moon,
  Rotate3d,
  Sun,
  Crosshair,
} from 'lucide-react';
import { RackVM, RackDisplayMode, RackDeviceVM } from '../types';
import { isWebGLAvailable } from './utils/webgl';
import { RackScene, SceneInteractionMode, SingleRackLightingMode } from './RackScene';
import { CameraPreset, DeviceFocusTarget } from './CameraController';
import { RackDeviceTooltip } from './RackDeviceTooltip';
import { CableMode, TopologyLinkItem } from './RackCableLayer';
import { API } from '../constants';
import { authHeaders } from '../helpers';
import { normalizeRackTopologyLinks, RawTopologyLinkItem } from './topology';
import { inferRackProfile } from '../rackProfiles';
import {
  detectGpuProfile,
  GraphicsQualityMode,
  loadGraphicsPreference,
  saveGraphicsPreference,
} from './gpuProfile';

interface Rack3DContainerProps {
  rackVM: RackVM;
  selectedDeviceId?: string | null;
  onSelectDevice: (deviceId: string) => void;
  onFallbackTo2D: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void | Promise<void>;
  zh: boolean;
}

interface RackLayerMenuPanelProps {
  zh: boolean;
  showDoor: boolean;
  isDoorOpen: boolean;
  showULabels: boolean;
  showPowerCords: boolean;
  showBlankingPanels: boolean;
  showAirflow: boolean;
  showBayContext: boolean;
  cabinetLightsOn: boolean;
  cableMode: CableMode;
  showPreviewCables: boolean;
  displayMode: RackDisplayMode;
  graphicsMode: GraphicsQualityMode;
  onToggleDoor: () => void;
  onToggleDoorOpen: () => void;
  onToggleULabels: () => void;
  onTogglePowerCords: () => void;
  onToggleBlankingPanels: () => void;
  onToggleAirflow: () => void;
  onToggleBayContext: () => void;
  onToggleCabinetLights: () => void;
  onCableModeChange: (mode: CableMode) => void;
  onDisplayModeChange: (mode: RackDisplayMode) => void;
  onGraphicsModeChange: (mode: GraphicsQualityMode) => void;
}

const RackLayerMenuPanel: React.FC<RackLayerMenuPanelProps> = ({
  zh,
  showDoor,
  isDoorOpen,
  showULabels,
  showPowerCords,
  showBlankingPanels,
  showAirflow,
  showBayContext,
  cabinetLightsOn,
  cableMode,
  showPreviewCables,
  displayMode,
  graphicsMode,
  onToggleDoor,
  onToggleDoorOpen,
  onToggleULabels,
  onTogglePowerCords,
  onToggleBlankingPanels,
  onToggleAirflow,
  onToggleBayContext,
  onToggleCabinetLights,
  onCableModeChange,
  onDisplayModeChange,
  onGraphicsModeChange
}) => (
  <div
    data-testid="rack-layer-panel"
    className="absolute right-3 top-16 z-20 w-72 max-w-[calc(100%-1.5rem)] max-h-[calc(100%-7rem)] overflow-y-auto space-y-2 rounded-xl border border-slate-700 bg-slate-950/95 p-2.5 shadow-2xl backdrop-blur-xl"
  >
    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{zh ? '机柜辅助' : 'Rack helpers'}</span>
      <span className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[9px] text-cyan-300">{zh ? '侧边面板' : 'Side panel'}</span>
    </div>

    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{zh ? '显示' : 'Display'}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onToggleDoor}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${showDoor ? 'bg-cyan-600/20 text-cyan-300' : 'bg-slate-800 text-slate-400'}`}
        >
          {showDoor ? (zh ? '门体显示' : 'Door shown') : (zh ? '门体隐藏' : 'Door hidden')}
        </button>
        <button
          type="button"
          onClick={onToggleDoorOpen}
          disabled={!showDoor}
          className={`rounded-md px-2 py-1 text-[10px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
            isDoorOpen ? 'bg-emerald-600/20 text-emerald-300' : 'bg-slate-800 text-slate-300'
          }`}
        >
          {isDoorOpen ? (zh ? '开门' : 'Open') : (zh ? '关门' : 'Closed')}
        </button>
        <button
          type="button"
          onClick={onToggleULabels}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${showULabels ? 'bg-cyan-600/20 text-cyan-300' : 'bg-slate-800 text-slate-400'}`}
        >
          {zh ? 'U 标尺' : 'U labels'}
        </button>
      </div>
    </div>

    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{zh ? '设施' : 'Infra'}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onTogglePowerCords}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${showPowerCords ? 'bg-red-600/20 text-red-300' : 'bg-slate-800 text-slate-400'}`}
        >
          {zh ? '背面供电线' : 'PSU Cords'}
        </button>
        <button
          type="button"
          onClick={onToggleBlankingPanels}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${showBlankingPanels ? 'bg-cyan-600/20 text-cyan-300' : 'bg-slate-800 text-slate-400'}`}
        >
          {zh ? '盲板' : 'Blanking'}
        </button>
        <button
          type="button"
          onClick={onToggleAirflow}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${showAirflow ? 'bg-sky-600/20 text-sky-300' : 'bg-slate-800 text-slate-400'}`}
        >
          {zh ? '冷热气流' : 'Airflow'}
        </button>
        <button
          type="button"
          onClick={onToggleBayContext}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${showBayContext ? 'bg-cyan-600/20 text-cyan-300' : 'bg-slate-800 text-slate-400'}`}
        >
          {zh ? '机房环境' : 'Bay Env'}
        </button>
        <button
          type="button"
          onClick={onToggleCabinetLights}
          className={`rounded-md px-2 py-1 text-[10px] font-medium ${cabinetLightsOn ? 'bg-amber-500/20 text-amber-200' : 'bg-slate-800 text-slate-400'}`}
        >
          {zh ? '柜内灯' : 'Cab LED'}
        </button>
      </div>
    </div>

    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{zh ? '线缆' : 'Cables'}</span>
      <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-xs">
        <button
          type="button"
          onClick={() => onCableModeChange('select')}
          className={`flex items-center gap-1 rounded-md px-2 py-0.5 font-medium transition-all ${
            cableMode === 'select' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '按需点亮选中跳线' : 'Cables On Select'}
        >
          <Cable size={11} />
          <span>{zh ? '按需' : 'Select'}</span>
        </button>
        <button
          type="button"
          onClick={() => onCableModeChange('all')}
          className={`rounded-md px-1.5 py-0.5 font-medium transition-all ${
            cableMode === 'all' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '显示全部走线' : 'All Cables'}
        >
          {zh ? '全线' : 'All'}
        </button>
        <button
          type="button"
          onClick={() => onCableModeChange('off')}
          className={`rounded-md px-1.5 py-0.5 font-medium transition-all ${
            cableMode === 'off' ? 'bg-slate-700 text-slate-200' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '隐藏全部跳线' : 'Hide Cables'}
        >
          {zh ? '关' : 'Off'}
        </button>
      </div>
    </div>
    {showPreviewCables && (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] leading-4 text-amber-200">
        {zh ? '当前没有已验证拓扑，画面显示预览线缆；不会写入 CMDB。点击“关”可隐藏。' : 'No verified topology is available. Preview cables are visual-only and never written to CMDB. Click Off to hide them.'}
      </div>
    )}

    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{zh ? '着色' : 'Coloring'}</span>
      <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-xs">
        <button
          type="button"
          onClick={() => onDisplayModeChange('physical')}
          className={`rounded-md px-2 py-0.5 font-medium transition-all ${
            displayMode === 'physical' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '物理真实外观' : 'Physical View'}
        >
          {zh ? '真容' : 'Real'}
        </button>
        <button
          type="button"
          onClick={() => onDisplayModeChange('health')}
          className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-all ${
            displayMode === 'health' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '告警健康热力' : 'Health Heatmap'}
        >
          <Activity size={11} />
          <span>{zh ? '健康' : 'Health'}</span>
        </button>
        <button
          type="button"
          onClick={() => onDisplayModeChange('role')}
          className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-all ${
            displayMode === 'role' ? 'bg-purple-600 text-white' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '设备角色' : 'Device role'}
        >
          <Tag size={11} />
        </button>
        <button
          type="button"
          onClick={() => onDisplayModeChange('power')}
          className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-all ${
            displayMode === 'power' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '额定功耗热力' : 'Power Heatmap'}
        >
          <Zap size={11} />
        </button>
      </div>
    </div>

    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{zh ? '渲染' : 'GPU'}</span>
      <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-[10px]">
        <button
          type="button"
          onClick={() => onGraphicsModeChange('eco')}
          className={`rounded-md px-2 py-0.5 font-medium transition-all ${
            graphicsMode === 'eco' ? 'bg-emerald-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '核显流畅模式：1x 分辨率 + 轻量光照，集成显卡高帧率' : 'iGPU Eco Mode'}
        >
          {zh ? '核显流畅' : 'iGPU Eco'}
        </button>
        <button
          type="button"
          onClick={() => onGraphicsModeChange('high')}
          className={`rounded-md px-2 py-0.5 font-medium transition-all ${
            graphicsMode === 'high' ? 'bg-violet-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={zh ? '高清画质模式：高分采样 + IBL 环境反射' : 'High Quality Mode'}
        >
          {zh ? '高清画质' : 'High'}
        </button>
      </div>
    </div>
  </div>
);

class ThreeErrorBoundary extends React.Component<
  { children: React.ReactNode; onFallback: () => void; zh: boolean },
  { hasError: boolean; errorMsg: string }
> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, errorMsg: '' };
  }

  static getDerivedStateFromError(error: any) {
    return { hasError: true, errorMsg: error?.message || '3D 渲染发生异常' };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full p-6 text-center space-y-3" style={{ background: 'var(--card-bg)' }}>
          <AlertTriangle size={36} className="text-amber-500" />
          <h4 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
            {this.props.zh ? '3D 机柜渲染暂时不可用' : '3D Rack Rendering Unavailable'}
          </h4>
          <p className="text-xs max-w-md" style={{ color: 'var(--muted-text)' }}>
            {this.state.errorMsg}
          </p>
          <button
            onClick={this.props.onFallback}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors"
          >
            {this.props.zh ? '切回 2D 平面机柜视图' : 'Switch to 2D Rack View'}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

type DeviceMacroSpot = 'left' | 'middle' | 'right' | 'rear' | 'full';

export const Rack3DContainer: React.FC<Rack3DContainerProps> = ({
  rackVM,
  selectedDeviceId,
  onSelectDevice,
  onFallbackTo2D,
  isFullscreen,
  onToggleFullscreen,
  zh
}) => {
  const [webglSupported, setWebglSupported] = useState<boolean | null>(null);
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>('reset');
  const [focusTarget, setFocusTarget] = useState<DeviceFocusTarget | null>(null);
  const [focusedDeviceId, setFocusedDeviceId] = useState<string | null>(null);
  const [activeSpot, setActiveSpot] = useState<DeviceMacroSpot | 'custom'>('full');
  const [interactionMode, setInteractionMode] = useState<SceneInteractionMode>('orbit');
  const [graphicsMode, setGraphicsMode] = useState<GraphicsQualityMode>(() => {
    const pref = loadGraphicsPreference();
    return pref === 'auto' ? detectGpuProfile(1).recommendedMode : pref;
  });
  const [tooltipCollapsed, setTooltipCollapsed] = useState(false);
  const [pulledOutDeviceId, setPulledOutDeviceId] = useState<string | null>(null);
  const [zoomAction, setZoomAction] = useState<{ type: 'in' | 'out'; timestamp: number } | null>(null);
  // Keep the equipment face unobstructed in the first 3D frame. The door is
  // still available from More layers when a closed-cabinet presentation is needed.
  const [isDoorOpen, setIsDoorOpen] = useState(false);
  const [showDoor, setShowDoor] = useState(false);
  const [showULabels, setShowULabels] = useState(true);
  const [showPowerCords, setShowPowerCords] = useState(true);
  const [showBlankingPanels, setShowBlankingPanels] = useState(false);
  const [showAirflow, setShowAirflow] = useState(false);
  const [showBayContext, setShowBayContext] = useState(true);
  const [lightingMode, setLightingMode] = useState<SingleRackLightingMode>('daylight');
  const [cabinetLightsOn, setCabinetLightsOn] = useState(true);

  const cycleLightingMode = () => {
    setLightingMode(prev => (prev === 'daylight' ? 'standby' : prev === 'standby' ? 'lights_out' : 'daylight'));
  };
  const [displayMode, setDisplayMode] = useState<RackDisplayMode>('physical');
  const [cableMode, setCableMode] = useState<CableMode>('all');
  const [rawTopologyLinks, setRawTopologyLinks] = useState<RawTopologyLinkItem[]>([]);
  const [topologyStatus, setTopologyStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [topologyTruncated, setTopologyTruncated] = useState(false);
  const [topologyReloadKey, setTopologyReloadKey] = useState(0);
  const [hoveredDevice, setHoveredDevice] = useState<RackDeviceVM | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearchDropdown, setShowSearchDropdown] = useState(false);
  const [showDataIssues, setShowDataIssues] = useState(false);
  const [showLayerMenu, setShowLayerMenu] = useState(false);

  const recentSpotFocusRef = useRef<{ deviceId: string; ts: number } | null>(null);
  const lastAutoFocusedDeviceIdRef = useRef<string | null>(null);
  const hoverClearTimerRef = useRef<number | null>(null);

  const handleHoverDevice = (device: RackDeviceVM | null) => {
    if (hoverClearTimerRef.current !== null) {
      window.clearTimeout(hoverClearTimerRef.current);
      hoverClearTimerRef.current = null;
    }
    if (device) {
      setHoveredDevice(device);
    } else {
      // Short grace delay lets users glide from a 3D device onto the bottom-right tooltip card
      hoverClearTimerRef.current = window.setTimeout(() => {
        setHoveredDevice(null);
        hoverClearTimerRef.current = null;
      }, 360);
    }
  };

  useEffect(() => () => {
    if (hoverClearTimerRef.current !== null) window.clearTimeout(hoverClearTimerRef.current);
  }, []);

  const handleGraphicsModeChange = (mode: GraphicsQualityMode) => {
    setGraphicsMode(mode);
    saveGraphicsPreference(mode);
  };

  const nonUDevices = rackVM.nonUDevices || [];
  const placementIssueDevices = [...rackVM.invalidDevices, ...nonUDevices];
  const hasPlacementIssues = placementIssueDevices.length > 0 || !rackVM.dataQuality.valid;

  const focusedDevice = React.useMemo(() => {
    const id = focusedDeviceId || selectedDeviceId;
    if (!id) return null;
    return rackVM.validDevices.find(item => item.id === id) || null;
  }, [focusedDeviceId, selectedDeviceId, rackVM.validDevices]);

  const handlePresetChange = (preset: CameraPreset) => {
    setFocusTarget(null);
    setFocusedDeviceId(null);
    setActiveSpot('full');
    setCameraPreset(preset);
  };

  const focusDeviceSpot = (device: RackDeviceVM, spot: DeviceMacroSpot) => {
    const w = device.coordinates.width || 4.78;
    const h = device.coordinates.height || 0.44;
    const tallFactor = h > 1.2 ? Math.min(2.4, h * 0.72) : 0;
    const base = {
      centerY: device.coordinates.centerY,
      centerZ: device.coordinates.centerZ,
      width: w,
      height: h,
      depth: device.coordinates.depth,
      timestamp: Date.now(),
    };
    setFocusedDeviceId(device.id);
    setActiveSpot(spot);
    recentSpotFocusRef.current = { deviceId: device.id, ts: Date.now() };

    if (spot === 'left') {
      setFocusTarget({
        ...base,
        centerX: -w * 0.36,
        face: 'front',
        distance: Math.max(1.18, 1.18 + tallFactor * 0.55),
        spotLabel: zh ? '左侧灯/铭牌' : 'Left LEDs',
      });
    } else if (spot === 'middle') {
      setFocusTarget({
        ...base,
        centerX: -w * 0.03,
        face: 'front',
        distance: Math.max(1.48, 1.48 + tallFactor * 0.65),
        spotLabel: zh ? '中段端口区' : 'Mid Ports',
      });
    } else if (spot === 'right') {
      setFocusTarget({
        ...base,
        centerX: w * 0.35,
        face: 'front',
        distance: Math.max(1.18, 1.18 + tallFactor * 0.55),
        spotLabel: zh ? '右侧上联口' : 'Right Uplinks',
      });
    } else if (spot === 'rear') {
      setFocusTarget({
        ...base,
        centerX: 0,
        face: 'rear',
        distance: Math.max(3.15, 3.15 + tallFactor * 0.85),
        spotLabel: zh ? '背面电源/风扇' : 'Rear PSU/Fan',
      });
    } else {
      setFocusTarget({
        ...base,
        centerX: 0,
        face: device.face,
        spotLabel: zh ? '整机正面' : 'Full Front',
      });
    }
  };

  const handleDoubleClickDevice = (
    device: RackDeviceVM,
    hitPoint?: { x: number; y: number; z: number },
  ) => {
    const halfW = (device.coordinates.width || 4.78) * 0.46;
    const halfH = (device.coordinates.height || 0.44) * 0.45;
    const targetX = hitPoint ? Math.max(-halfW, Math.min(halfW, hitPoint.x)) : 0;
    const targetY = hitPoint
      ? Math.max(device.coordinates.centerY - halfH, Math.min(device.coordinates.centerY + halfH, hitPoint.y))
      : device.coordinates.centerY;
    const targetFace: 'front' | 'rear' = hitPoint
      ? (hitPoint.z < (device.coordinates.centerZ || 0) ? 'rear' : 'front')
      : device.face;

    recentSpotFocusRef.current = { deviceId: device.id, ts: Date.now() };
    setFocusedDeviceId(device.id);
    setActiveSpot('custom');
    setFocusTarget({
      centerX: targetX,
      centerY: targetY,
      centerZ: device.coordinates.centerZ,
      width: device.coordinates.width,
      height: device.coordinates.height,
      depth: device.coordinates.depth,
      face: targetFace,
      distance: 1.18,
      spotLabel: zh ? '定点局部特写' : 'Spot Macro',
      timestamp: Date.now(),
    });
  };

  useEffect(() => {
    if (!selectedDeviceId) {
      lastAutoFocusedDeviceIdRef.current = null;
      return;
    }
    // Avoid hijacking the camera on background rackVM polling refreshes when the
    // same device remains selected, or right after a double-click spot macro.
    if (lastAutoFocusedDeviceIdRef.current === selectedDeviceId) return;
    if (
      recentSpotFocusRef.current
      && recentSpotFocusRef.current.deviceId === selectedDeviceId
      && Date.now() - recentSpotFocusRef.current.ts < 800
    ) {
      lastAutoFocusedDeviceIdRef.current = selectedDeviceId;
      return;
    }

    const device = rackVM.validDevices.find(item => item.id === selectedDeviceId);
    if (!device) return;
    lastAutoFocusedDeviceIdRef.current = selectedDeviceId;
    setFocusedDeviceId(device.id);
    setActiveSpot('full');
    setFocusTarget({
      centerX: 0,
      centerY: device.coordinates.centerY,
      centerZ: device.coordinates.centerZ,
      width: device.coordinates.width,
      height: device.coordinates.height,
      depth: device.coordinates.depth,
      face: device.face,
      spotLabel: zh ? '整机正面' : 'Full Front',
      timestamp: Date.now()
    });
  }, [selectedDeviceId, rackVM.validDevices, zh]);

  useEffect(() => {
    setWebglSupported(isWebGLAvailable());
  }, []);

  // Fetch topology links for inter-device cabling
  useEffect(() => {
    let cancelled = false;
    async function loadTopology() {
      setTopologyStatus('loading');
      try {
        const params = new URLSearchParams({ limit: '500', rack_id: rackVM.id });
        if (rackVM.siteId) params.set('site_id', rackVM.siteId);
        const res = await fetch(`${API}/topology/links?${params.toString()}`, {
          headers: authHeaders()
        });
        if (!res.ok) throw new Error('Topology fetch failed');
        const data = await res.json();
        if (cancelled) return;
        const rawLinks = Array.isArray(data) ? data : (data?.links || []);
        setRawTopologyLinks(rawLinks);
        setTopologyTruncated(Boolean(data?.truncated));
        setTopologyStatus('ready');
      } catch {
        if (cancelled) return;
        setRawTopologyLinks([]);
        setTopologyTruncated(false);
        setTopologyStatus('error');
      }
    }
    loadTopology();
    return () => {
      cancelled = true;
    };
  }, [rackVM.id, rackVM.siteId, topologyReloadKey]);

  const topologyLinks: TopologyLinkItem[] = React.useMemo(
    () => normalizeRackTopologyLinks(rawTopologyLinks, rackVM),
    [rawTopologyLinks, rackVM],
  );
  // A rack view must never present an ordinal demo cable as if it were an
  // observed connection. Only verified topology rows (normally LLDP-backed)
  // are passed to the 3D line layer; an empty response stays visibly empty.
  const showPreviewCables = false;
  const topologySourceLabel = React.useMemo(() => {
    const sources = Array.from(new Set(
      topologyLinks
        .map(link => link.discovery_source?.trim().toUpperCase())
        .filter(Boolean),
    ));
    return sources.length > 0 ? sources.join(' / ') : '';
  }, [topologyLinks]);
  const rackProfile = React.useMemo(
    () => inferRackProfile(rackVM.devices),
    [rackVM.devices],
  );

  // Search filtered devices
  const filteredDevices = React.useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase().trim();
    return rackVM.devices.filter(
      d =>
        d.name.toLowerCase().includes(q) ||
        d.vendor.toLowerCase().includes(q) ||
        d.model.toLowerCase().includes(q) ||
        d.serialNumber.toLowerCase().includes(q) ||
        d.role.toLowerCase().includes(q)
    );
  }, [rackVM.devices, searchQuery]);

  // Active device for tooltip
  const activeTooltipDevice = React.useMemo(() => {
    if (hoveredDevice) return hoveredDevice;
    if (selectedDeviceId) {
      return rackVM.devices.find(d => d.id === selectedDeviceId) || null;
    }
    return null;
  }, [hoveredDevice, selectedDeviceId, rackVM.devices]);

  // Health summary counts
  const healthyCount = rackVM.devices.filter(d => d.healthStatus === 'healthy').length;
  const warningCount = rackVM.devices.filter(d => d.healthStatus === 'warning').length;
  const criticalCount = rackVM.devices.filter(d => d.healthStatus === 'critical').length;
  const offlineCount = rackVM.devices.filter(d => d.healthStatus === 'offline').length;
  const unknownCount = rackVM.devices.filter(d => d.healthStatus === 'unknown').length;

  if (webglSupported === false) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center space-y-3" style={{ background: 'var(--card-bg)' }}>
        <Info size={36} className="text-cyan-500" />
        <h4 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
          {zh ? '当前浏览器或环境不支持 WebGL 硬件加速' : 'WebGL Not Supported in Current Browser'}
        </h4>
        <p className="text-xs max-w-md" style={{ color: 'var(--muted-text)' }}>
          {zh
            ? '系统已自动保护并为您切换到 2D 平面机柜管理。'
            : 'The system has safely switched to the 2D rack management view.'}
        </p>
        <button
          onClick={onFallbackTo2D}
          className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors"
        >
          {zh ? '返回 2D 视图' : 'Back to 2D View'}
        </button>
      </div>
    );
  }

  return (
    <ThreeErrorBoundary onFallback={onFallbackTo2D} zh={zh}>
      <div
        className="w-full h-full relative overflow-hidden flex flex-col select-none"
        style={{ background: '#090d16' }}
      >
        {/* Docked Single-Header 3D Control Bar (zero overlap with 3D rack or search box) */}
        <div className="shrink-0 z-20 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/90 bg-slate-950/95 px-2.5 py-1.5 text-slate-200">
        <div className="flex flex-wrap items-center gap-1">
          <span className="flex items-center gap-1 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-[10px] font-bold text-cyan-300">
            <Eye size={11} />
            {zh ? '只读' : 'Read-only'}
          </span>
          <span
            className="max-w-[13rem] truncate rounded-lg border border-slate-600/70 bg-slate-900/80 px-2 py-1 text-[10px] font-semibold text-slate-200"
            title={zh ? rackProfile.descriptionZh : rackProfile.descriptionEn}
          >
            {zh ? rackProfile.labelZh : rackProfile.labelEn}
          </span>
          <button
            type="button"
            onClick={onFallbackTo2D}
            className="flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-semibold text-slate-300 hover:bg-slate-800 hover:text-white"
            title={zh ? '切换到 2D，并保留当前机柜和设备选择' : 'Switch to 2D and keep the current rack and device selection'}
          >
            <Columns3 size={11} />
            {zh ? '在 2D 中查看' : 'View in 2D'}
          </button>
          <div className="w-[1px] h-3.5 bg-slate-700/80" />
          {/* Camera View Presets */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => handlePresetChange('front')}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                cameraPreset === 'front' && !focusTarget ? 'bg-cyan-600 text-white shadow-md' : 'hover:bg-slate-800/80 text-slate-300'
              }`}
              title={zh ? '正面视角' : 'Front View'}
            >
              {zh ? '正面' : 'Front'}
            </button>
            <button
              onClick={() => handlePresetChange('rear')}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                cameraPreset === 'rear' && !focusTarget ? 'bg-cyan-600 text-white shadow-md' : 'hover:bg-slate-800/80 text-slate-300'
              }`}
              title={zh ? '背面视角（电源与风扇）' : 'Rear View'}
            >
              {zh ? '背面' : 'Rear'}
            </button>
            <button
              onClick={() => handlePresetChange('iso')}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                cameraPreset === 'iso' && !focusTarget ? 'bg-cyan-600 text-white shadow-md' : 'hover:bg-slate-800/80 text-slate-300'
              }`}
              title={zh ? '45° 等轴视角' : 'Isometric View'}
            >
              {zh ? '45°' : '45°'}
            </button>
            <button
              onClick={() => handlePresetChange('top')}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                cameraPreset === 'top' && !focusTarget ? 'bg-cyan-600 text-white shadow-md' : 'hover:bg-slate-800/80 text-slate-300'
              }`}
              title={zh ? '顶部俯视' : 'Top View'}
            >
              {zh ? '俯视' : 'Top'}
            </button>
            <button
              onClick={() => handlePresetChange('focus_top')}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                cameraPreset === 'focus_top' && !focusTarget ? 'bg-cyan-600 text-white shadow-md' : 'hover:bg-slate-800/80 text-slate-300'
              }`}
              title={zh ? '聚焦顶部设备 (U35-U42)' : 'Focus Top (U35-U42)'}
            >
              {zh ? '聚焦顶部' : 'Top 8U'}
            </button>
            <button
              onClick={() => handlePresetChange('focus_bottom')}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                cameraPreset === 'focus_bottom' && !focusTarget ? 'bg-cyan-600 text-white shadow-md' : 'hover:bg-slate-800/80 text-slate-300'
              }`}
              title={zh ? '聚焦底部设备 (U1-U10)' : 'Focus Bottom (U1-U10)'}
            >
              {zh ? '聚焦底部' : 'Bot 8U'}
            </button>

            <button
              onClick={() => handlePresetChange('reset')}
              className="p-1 rounded-lg text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
              title={zh ? '重置视角' : 'Reset Camera'}
            >
              <RotateCcw size={12} />
            </button>

            {/* Direct Zoom In / Out Buttons (macro depth enabled) */}
            <button
              onClick={() => setZoomAction({ type: 'in', timestamp: Date.now() })}
              className="p-1 rounded-lg text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
              title={zh ? '放大视角 (+，支持微距看端口)' : 'Zoom In (+)'}
            >
              <ZoomIn size={12} />
            </button>
            <button
              onClick={() => setZoomAction({ type: 'out', timestamp: Date.now() })}
              className="p-1 rounded-lg text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
              title={zh ? '缩小视角 (-)' : 'Zoom Out (-)'}
            >
              <ZoomOut size={12} />
            </button>
          </div>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          {/* Orbit vs Pan Mouse Mode Toggle (eliminates awkward mouse dragging in close-up) */}
          <div
            className="flex items-center rounded-lg border border-slate-700/80 bg-slate-900 p-0.5 text-[11px]"
            title={zh ? '切换左键拖动方式：旋转或平移（随时可按住空格键或右键临时平移，滚轮指向缩放）' : 'Toggle left-drag Orbit / Pan (or hold Space / Right-drag to pan, scroll to zoom at cursor)'}
          >
            <button
              type="button"
              onClick={() => setInteractionMode('orbit')}
              className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-colors ${
                interactionMode === 'orbit' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '左键旋转视角（右键或按住空格平移）' : 'Left-drag Orbit (Right-drag or hold Space to Pan)'}
            >
              <Rotate3d size={11} />
              <span>{zh ? '旋转' : 'Orbit'}</span>
            </button>
            <button
              type="button"
              onClick={() => setInteractionMode('pan')}
              className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-colors ${
                interactionMode === 'pan' ? 'bg-amber-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '左键平移画面（像看图纸一样滑动查看任意端口细节）' : 'Left-drag Pan across ports & LEDs'}
            >
              <Hand size={11} />
              <span>{zh ? '平移' : 'Pan'}</span>
            </button>
          </div>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          {/* Independent Single-Rack Lighting System Switch */}
          <button
            type="button"
            onClick={cycleLightingMode}
            className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-semibold transition-colors ${
              lightingMode === 'daylight'
                ? 'border-amber-400/50 bg-amber-400/15 text-amber-200 hover:bg-amber-400/25'
                : lightingMode === 'standby'
                  ? 'border-sky-400/50 bg-sky-500/15 text-sky-200 hover:bg-sky-500/25'
                  : 'border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
            title={zh ? '切换独立照明系统：巡检全亮 → 值守节能 → 熄灯观察指示灯（更多图层中可单独开关柜内灯）' : 'Cycle Lighting: Daylight -> Standby -> Lights-Out'}
          >
            {lightingMode === 'daylight' ? <Sun size={11} /> : lightingMode === 'standby' ? <Lightbulb size={11} /> : <Moon size={11} />}
            <span>
              {lightingMode === 'daylight'
                ? (zh ? '照明·全亮' : 'Day')
                : lightingMode === 'standby'
                  ? (zh ? '照明·值守' : 'Eco')
                  : (zh ? '照明·熄灯' : 'Off')}
            </span>
          </button>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          <div className="relative">
            <button
              type="button"
              aria-expanded={showLayerMenu}
              onClick={() => setShowLayerMenu(value => !value)}
              className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold transition-colors ${
                showLayerMenu ? 'bg-cyan-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              }`}
            >
              <Layers size={12} />
              {zh ? '更多图层' : 'More layers'}
              <ChevronDown size={11} className={showLayerMenu ? 'rotate-180 transition-transform' : 'transition-transform'} />
            </button>
          </div>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          {/* Read-only pull-out visualization */}
          {selectedDeviceId && (
            <>
              <button
                onClick={() => setPulledOutDeviceId(pulledOutDeviceId === selectedDeviceId ? null : selectedDeviceId)}
                className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold transition-all ${
                  pulledOutDeviceId === selectedDeviceId
                    ? 'bg-amber-600 text-white shadow-lg shadow-amber-900/50 ring-1 ring-amber-400 animate-pulse'
                    : 'bg-slate-900 hover:bg-slate-800 text-amber-300 border border-amber-500/50'
                }`}
                title={zh ? '只读观察动画，不改变设备状态' : 'Read-only inspection animation; no state change'}
              >
                <Layers size={11} />
                <span>{pulledOutDeviceId === selectedDeviceId ? (zh ? '收回设备' : 'Push In') : (zh ? '拉出观察' : 'Inspect')}</span>
              </button>
              <div className="w-[1px] h-3.5 bg-slate-700/80" />
            </>
          )}

          {/* Fullscreen Button */}
          <button
            onClick={onToggleFullscreen}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
            title={zh ? (isFullscreen ? '退出全屏' : '全屏显示') : (isFullscreen ? 'Exit Fullscreen' : 'Fullscreen')}
          >
            {isFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
            <span>{isFullscreen ? (zh ? '退出' : 'Exit') : (zh ? '全屏' : 'Full')}</span>
          </button>
        </div>

        {/* Top-Right Floating Island (Search Box & Capacity/Power Stats) */}
        <div className="flex items-center gap-2">
          {/* Quick Search */}
          <div className="relative">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl shadow-lg backdrop-blur-xl bg-slate-950/90 border border-slate-700/70 text-slate-200 text-xs">
              <Search size={12} className="text-slate-400" />
              <input
                type="search"
                placeholder={zh ? '搜索设备...' : 'Search device...'}
                value={searchQuery}
                onChange={e => {
                  setSearchQuery(e.target.value);
                  setShowSearchDropdown(true);
                }}
                onFocus={() => setShowSearchDropdown(true)}
                className="bg-transparent border-none outline-none text-xs w-28 text-slate-100 placeholder-slate-500"
              />
            </div>

            {/* Search Dropdown */}
            {showSearchDropdown && filteredDevices.length > 0 && (
              <div className="absolute left-0 top-full mt-1.5 w-72 max-h-60 overflow-y-auto rounded-xl shadow-2xl backdrop-blur-xl bg-slate-950/95 border border-slate-700 p-1 z-30 space-y-0.5">
                {filteredDevices.map(d => (
                  <button
                    key={d.id}
                    onClick={() => {
                      onSelectDevice(d.id);
                      setShowSearchDropdown(false);
                      setSearchQuery('');
                    }}
                    className="w-full text-left p-2 rounded-lg hover:bg-cyan-950/60 hover:border-cyan-500/30 border border-transparent transition-all flex items-center justify-between"
                  >
                    <div className="truncate">
                      <div className="text-xs font-semibold text-cyan-300 truncate">{d.name}</div>
                      <div className="text-[10px] text-slate-400">
                        {d.mountKind === 'u_mount' ? `U${d.startU}-U${d.endU}` : `${d.mountKind || 'unknown'} / ${d.position || 'unknown'}`}
                        {' · '}{d.vendor} {d.model}
                      </div>
                    </div>
                    <span className="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 flex-shrink-0">
                      {d.role}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Stats Badges */}
          <div className="flex items-center gap-2 p-1.5 rounded-xl shadow-lg backdrop-blur-xl bg-slate-950/90 border border-slate-700/70 text-slate-200 text-xs">
            <div className="flex items-center gap-1 px-2">
              <span className="text-slate-400">{zh ? 'U位:' : 'U:'}</span>
              <span className="font-semibold text-cyan-400">
                {rackVM.usedU}/{rackVM.totalU}U
              </span>
              <span className="text-[10px] text-slate-500">
                ({rackVM.availableU}U {zh ? '空闲' : 'free'})
              </span>
            </div>

            {rackVM.ratedPowerTotalWatts > 0 && (
              <>
                <div className="w-[1px] h-3 bg-slate-700" />
                <div className="flex items-center gap-1 px-1.5 text-amber-400">
                  <Zap size={11} />
                  <span>{rackVM.ratedPowerTotalWatts} W</span>
                </div>
              </>
            )}

            {hasPlacementIssues && (
              <button
                onClick={() => setShowDataIssues(!showDataIssues)}
                className="flex items-center gap-1 px-2 py-0.5 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/40 hover:bg-amber-500/30 transition-colors text-[11px]"
              >
                <AlertTriangle size={11} />
                {placementIssueDevices.length} {zh ? '位置待确认' : 'Placement issues'}
              </button>
            )}
          </div>
        </div>
        </div>

        {showLayerMenu && (
          <RackLayerMenuPanel
            zh={zh}
            showDoor={showDoor}
            isDoorOpen={isDoorOpen}
            showULabels={showULabels}
            showPowerCords={showPowerCords}
            showBlankingPanels={showBlankingPanels}
            showAirflow={showAirflow}
            showBayContext={showBayContext}
            cabinetLightsOn={cabinetLightsOn}
            cableMode={cableMode}
            showPreviewCables={showPreviewCables}
            displayMode={displayMode}
            graphicsMode={graphicsMode}
            onToggleDoor={() => setShowDoor(value => !value)}
            onToggleDoorOpen={() => setIsDoorOpen(value => !value)}
            onToggleULabels={() => setShowULabels(value => !value)}
            onTogglePowerCords={() => setShowPowerCords(value => !value)}
            onToggleBlankingPanels={() => setShowBlankingPanels(value => !value)}
            onToggleAirflow={() => setShowAirflow(value => !value)}
            onToggleBayContext={() => setShowBayContext(value => !value)}
            onToggleCabinetLights={() => setCabinetLightsOn(value => !value)}
            onCableModeChange={setCableMode}
            onDisplayModeChange={setDisplayMode}
            onGraphicsModeChange={handleGraphicsModeChange}
          />
        )}

        {/* 3D Scene Viewport */}
        <div className={`relative flex-1 min-h-0 w-full transition-[padding] duration-200 ${showLayerMenu ? 'pr-72' : ''}`}>
          {/* One-Click Local Macro Inspection Bar (top-center single sleek line — never collides with bottom tooltip/legend) */}
          {focusTarget && focusedDevice && (
            <div
              data-testid="device-macro-bar"
              className="absolute top-2.5 left-1/2 -translate-x-1/2 z-20 flex max-w-[calc(100%-1.5rem)] items-center gap-1 overflow-x-auto whitespace-nowrap rounded-xl border border-cyan-500/60 bg-slate-950/92 px-2.5 py-1 text-[11px] text-slate-200 shadow-2xl"
            >
              <span className="flex items-center gap-1 pr-1 font-semibold text-cyan-300">
                <Crosshair size={11} className="shrink-0 text-cyan-400" />
                <span className="max-w-[7.5rem] truncate">{focusedDevice.name}</span>
              </span>
              <div className="h-3 w-[1px] shrink-0 bg-slate-700" />
              {([
                { id: 'left', label: zh ? '左侧灯' : 'Left LEDs' },
                { id: 'middle', label: zh ? '中段口' : 'Mid Ports' },
                { id: 'right', label: zh ? '右侧上联' : 'Uplinks' },
                { id: 'rear', label: zh ? '背面电源' : 'Rear PSU' },
                { id: 'full', label: zh ? '整机' : 'Full' },
              ] as Array<{ id: DeviceMacroSpot; label: string }>).map(spot => (
                <button
                  key={spot.id}
                  type="button"
                  onClick={() => focusDeviceSpot(focusedDevice, spot.id)}
                  className={`shrink-0 rounded-lg px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                    activeSpot === spot.id
                      ? 'bg-cyan-600 text-white shadow-sm'
                      : 'bg-slate-900/90 text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`}
                >
                  {spot.label}
                </button>
              ))}
              <div className="h-3 w-[1px] shrink-0 bg-slate-700" />
              <button
                type="button"
                onClick={() => handlePresetChange('reset')}
                className="shrink-0 rounded-lg bg-slate-800 px-2 py-0.5 text-[10px] font-bold text-slate-200 hover:bg-slate-700 hover:text-white transition-colors"
              >
                {zh ? '恢复全景' : 'Reset'}
              </button>
            </div>
          )}

          <RackScene
            rackVM={rackVM}
            selectedDeviceId={selectedDeviceId}
            pulledOutDeviceId={pulledOutDeviceId}
            displayMode={displayMode}
            cableMode={cableMode}
            topologyLinks={topologyLinks}
            showPreviewCables={showPreviewCables}
            zoomAction={zoomAction}
            focusTarget={focusTarget}
            interactionMode={interactionMode}
            graphicsMode={graphicsMode}
            lightingMode={lightingMode}
            cabinetLightsOn={cabinetLightsOn}
            onSelectDevice={onSelectDevice}
            onDoubleClickDevice={handleDoubleClickDevice}
            onHoverDevice={handleHoverDevice}
            cameraPreset={cameraPreset}
            isDoorOpen={isDoorOpen}
            showDoor={showDoor}
            showULabels={showULabels}
            showPowerCords={showPowerCords}
            showBlankingPanels={showBlankingPanels}
            showAirflow={showAirflow}
            showBayContext={showBayContext}
            zh={zh}
          />
        </div>

        {/* Power Heatmap Legend Overlay */}
        {displayMode === 'power' && (
          <div className="absolute bottom-12 left-3 z-10 flex items-center gap-2 px-3 py-1.5 rounded-xl shadow-xl backdrop-blur-xl bg-slate-950/95 border border-slate-700 text-xs text-slate-200 animate-in fade-in slide-in-from-bottom-2">
            <span className="font-bold text-amber-400 flex items-center gap-1">
              <Zap size={11} />
              <span>{zh ? '功耗热力:' : 'Heatmap:'}</span>
            </span>
            <div className="flex items-center gap-2 text-[10px]">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm bg-cyan-500 inline-block shadow-[0_0_4px_#06b6d4]" /> &lt;250W
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500 inline-block shadow-[0_0_4px_#10b981]" /> 250-500W
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm bg-amber-500 inline-block shadow-[0_0_4px_#f59e0b]" /> 500-800W
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm bg-red-500 inline-block shadow-[0_0_4px_#ef4444]" /> &gt;800W
              </span>
            </div>
          </div>
        )}

        {/* Bottom Clean Status Strip (Health Breakdown + Macro Navigation Hint) */}
        <div className="absolute bottom-3 left-3 z-10 flex flex-wrap items-center gap-2.5 px-3 py-1.5 rounded-xl shadow-lg backdrop-blur-xl bg-slate-950/85 border border-slate-700/60 text-xs text-slate-300">
          <div className="flex items-center gap-1 text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
            <span>{zh ? '正常' : 'Normal'} {healthyCount}</span>
          </div>
          {warningCount > 0 && (
            <div className="flex items-center gap-1 text-amber-400">
              <span className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_6px_#fbbf24]" />
              <span>{zh ? '警告' : 'Warning'} {warningCount}</span>
            </div>
          )}
          {criticalCount > 0 && (
            <div className="flex items-center gap-1 text-red-400">
              <span className="w-2 h-2 rounded-full bg-red-400 shadow-[0_0_6px_#f87171] animate-pulse" />
              <span>{zh ? '严重' : 'Critical'} {criticalCount}</span>
            </div>
          )}
          {offlineCount > 0 && (
            <div className="flex items-center gap-1 text-slate-400">
              <span className="w-2 h-2 rounded-full bg-slate-500" />
              <span>{zh ? '离线' : 'Offline'} {offlineCount}</span>
            </div>
          )}
          {unknownCount > 0 && (
            <div className="flex items-center gap-1 text-slate-400">
              <span className="w-2 h-2 rounded-full bg-slate-600" />
              <span>{zh ? '无遥测' : 'Unknown'} {unknownCount}</span>
            </div>
          )}
          <div className="w-[1px] h-3 bg-slate-700" />
          <div
            className={`flex items-center gap-1 ${topologyStatus === 'error' || topologyTruncated || showPreviewCables ? 'text-amber-400' : 'text-cyan-300'}`}
            title={showPreviewCables
              ? (zh ? '当前机柜没有已验证拓扑；画面中的线缆是视觉预览，不代表 CMDB 连接' : 'This rack has no verified topology; visible cables are a visual preview and do not represent CMDB connections.')
              : topologyTruncated
                ? (zh ? '拓扑接口仅返回前 500 条；当前机柜可能仍有未展示链路' : 'The topology API returned only the first 500 rows; this rack may have undisplayed links.')
                : undefined}
          >
            <Cable size={11} />
            <span>
              {topologyStatus === 'loading'
                ? (zh ? '拓扑加载中' : 'Loading topology')
                : topologyStatus === 'error'
                  ? (zh ? '拓扑不可用' : 'Topology unavailable')
                  : topologyLinks.length === 0
                    ? (showPreviewCables ? (zh ? '预览线缆 · 未关联' : 'Preview cables · unlinked') : (zh ? '无已验证链路' : 'No verified links'))
                    : `${zh ? '已验证链路' : 'Verified links'} ${topologyLinks.length}${topologySourceLabel ? ` · ${topologySourceLabel}` : ''}`}
              {topologyTruncated ? (zh ? '（结果已截断）' : ' (truncated)') : ''}
            </span>
            {topologyStatus === 'error' && (
              <button
                type="button"
                onClick={() => setTopologyReloadKey(value => value + 1)}
                className="ml-1 flex items-center gap-1 rounded border border-amber-500/40 px-1.5 py-0.5 text-[10px] hover:bg-amber-500/10"
                title={zh ? '重新请求拓扑数据' : 'Retry topology request'}
              >
                <RefreshCw size={10} /> {zh ? '重试' : 'Retry'}
              </button>
            )}
          </div>
          <div className="hidden xl:block w-[1px] h-3 bg-slate-700" />
          <span className="hidden xl:inline text-[10px] text-slate-400">
            {zh ? '滚轮指向缩放 · 双击定点特写 · 空格/右键平移 · 方向键微调' : 'Scroll to cursor · Dbl-click macro · Space/Right-drag pan · Arrows nudge'}
          </span>
        </div>

        {/* Floating Device Tooltip HUD (collapsible so it never blocks close-ups) */}
        {activeTooltipDevice && (
          <RackDeviceTooltip
            device={activeTooltipDevice}
            onOpenDetail={onSelectDevice}
            collapsed={tooltipCollapsed}
            onToggleCollapsed={() => setTooltipCollapsed(v => !v)}
            onMouseEnter={() => {
              if (hoverClearTimerRef.current !== null) {
                window.clearTimeout(hoverClearTimerRef.current);
                hoverClearTimerRef.current = null;
              }
            }}
            onMouseLeave={() => handleHoverDevice(null)}
            zh={zh}
          />
        )}

        {/* Data Quality Issues Panel */}
        {showDataIssues && hasPlacementIssues && (
          <div className="absolute bottom-12 left-4 z-20 w-96 rounded-xl shadow-2xl backdrop-blur-xl bg-slate-950/95 border border-amber-500/50 p-4 text-slate-100">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
              <div className="flex items-center gap-2 text-amber-400 font-bold text-xs">
                <AlertTriangle size={14} />
                {zh ? '机柜数据质量检查报告' : 'Data Quality Issues'}
              </div>
              <button
                onClick={() => setShowDataIssues(false)}
                className="text-slate-400 hover:text-white text-xs"
              >
                ✕
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto space-y-2 text-xs">
              {placementIssueDevices.map(dev => {
                const isUMount = dev.mountKind === 'u_mount';
                const hasKnownUPlacement = isUMount && dev.startKnown !== false && dev.heightKnown !== false;
                const placement = isUMount
                  ? (hasKnownUPlacement
                    ? (dev.heightU > 1 ? `U${dev.startU}–U${dev.endU}` : `U${dev.startU}`)
                    : (zh ? 'U 位待确认' : 'U position pending'))
                  : `${dev.mountKind || 'unknown'} / ${dev.position || 'unknown'}`;
                return (
                <div key={dev.id} className="p-2 rounded-lg bg-slate-900/90 border border-slate-800">
                  <div className="font-semibold text-slate-200">{dev.name} · {placement}</div>
                  <ul className="list-disc list-inside text-[11px] text-amber-300/90 mt-1 space-y-0.5">
                    {(dev.dataQuality.issues.length > 0 ? dev.dataQuality.issues : [zh ? '非 U 设备不参与标准 U 位占用计算，请按位置说明管理。' : 'Non-U equipment is excluded from standard U occupancy; use the placement note for its physical location.']).map((issue, idx) => (
                      <li key={idx}>{issue}</li>
                    ))}
                  </ul>
                </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </ThreeErrorBoundary>
  );
};
