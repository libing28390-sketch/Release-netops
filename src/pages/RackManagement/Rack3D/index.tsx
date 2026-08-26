import React, { useState, useEffect, useRef } from 'react';
import {
  RotateCcw,
  Layers,
  AlertTriangle,
  DoorClosed,
  DoorOpen,
  Info,
  Maximize2,
  Minimize2,
  Search,
  Activity,
  Zap,
  Tag,
  Cable,
  ZoomIn,
  ZoomOut
} from 'lucide-react';
import { RackVM, RackDisplayMode, RackDeviceVM } from '../types';
import { isWebGLAvailable } from './utils/webgl';
import { RackScene } from './RackScene';
import { CameraPreset, DeviceFocusTarget } from './CameraController';
import { RackDeviceTooltip } from './RackDeviceTooltip';
import { CableMode, TopologyLinkItem } from './RackCableLayer';
import { API } from '../constants';
import { authHeaders } from '../helpers';

interface Rack3DContainerProps {
  rackVM: RackVM;
  selectedDeviceId?: string | null;
  onSelectDevice: (deviceId: string) => void;
  onFallbackTo2D: () => void;
  zh: boolean;
}

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

export const Rack3DContainer: React.FC<Rack3DContainerProps> = ({
  rackVM,
  selectedDeviceId,
  onSelectDevice,
  onFallbackTo2D,
  zh
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [webglSupported, setWebglSupported] = useState<boolean | null>(null);
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>('reset');
  const [focusTarget, setFocusTarget] = useState<DeviceFocusTarget | null>(null);
  const [pulledOutDeviceId, setPulledOutDeviceId] = useState<string | null>(null);
  const [zoomAction, setZoomAction] = useState<{ type: 'in' | 'out'; timestamp: number } | null>(null);
  const [isDoorOpen, setIsDoorOpen] = useState(true); // Default open 100°
  const [showDoor, setShowDoor] = useState(true);
  const [showULabels, setShowULabels] = useState(true);
  const [displayMode, setDisplayMode] = useState<RackDisplayMode>('physical');
  const [cableMode, setCableMode] = useState<CableMode>('select');
  const [topologyLinks, setTopologyLinks] = useState<TopologyLinkItem[]>([]);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [hoveredDevice, setHoveredDevice] = useState<RackDeviceVM | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearchDropdown, setShowSearchDropdown] = useState(false);
  const [showDataIssues, setShowDataIssues] = useState(false);

  const handlePresetChange = (preset: CameraPreset) => {
    setFocusTarget(null);
    setCameraPreset(preset);
  };

  const handleDoubleClickDevice = (device: RackDeviceVM) => {
    setFocusTarget({
      centerY: device.coordinates.centerY,
      face: device.face,
      timestamp: Date.now()
    });
  };

  useEffect(() => {
    setWebglSupported(isWebGLAvailable());
  }, []);

  // Fetch topology links for inter-device cabling
  useEffect(() => {
    let cancelled = false;
    async function loadTopology() {
      try {
        const res = await fetch(`${API}/topology/links?limit=500`, {
          headers: authHeaders()
        });
        if (!res.ok) throw new Error('Topology fetch failed');
        const data = await res.json();
        if (cancelled) return;
        const rawLinks = Array.isArray(data) ? data : (data?.links || []);
        setTopologyLinks(rawLinks);
      } catch (err) {
        // Fallback default links handled in RackCableLayer
      }
    }
    loadTopology();
    return () => {
      cancelled = true;
    };
  }, []);

  // Listen for fullscreen change events
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

  const handleToggleFullscreen = async () => {
    if (!containerRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await containerRef.current.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (err) {
      console.error('Fullscreen toggle error:', err);
    }
  };

  // Search filtered devices
  const filteredDevices = React.useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase().trim();
    return rackVM.validDevices.filter(
      d =>
        d.name.toLowerCase().includes(q) ||
        d.vendor.toLowerCase().includes(q) ||
        d.model.toLowerCase().includes(q) ||
        d.serialNumber.toLowerCase().includes(q) ||
        d.role.toLowerCase().includes(q)
    );
  }, [rackVM.validDevices, searchQuery]);

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
        ref={containerRef}
        className="w-full h-full relative overflow-hidden flex flex-col select-none"
        style={{ background: '#090d16' }}
      >
        {/* Top Floating Control Bar (Left Island) */}
        <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 p-1.5 rounded-xl shadow-2xl backdrop-blur-xl bg-slate-950/90 border border-slate-700/70 text-slate-200">
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

            {/* Direct Zoom In / Out Buttons */}
            <button
              onClick={() => setZoomAction({ type: 'in', timestamp: Date.now() })}
              className="p-1 rounded-lg text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
              title={zh ? '放大视角 (+)' : 'Zoom In (+)'}
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

          {/* Door Toggle */}
          <button
            onClick={() => setIsDoorOpen(!isDoorOpen)}
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium transition-all ${
              isDoorOpen ? 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/30' : 'hover:bg-slate-800 text-slate-300'
            }`}
            title={zh ? '开门 / 关门' : 'Toggle Door'}
          >
            {isDoorOpen ? <DoorOpen size={12} /> : <DoorClosed size={12} />}
            <span>{isDoorOpen ? (zh ? '开门' : 'Open') : (zh ? '关门' : 'Closed')}</span>
          </button>

          {/* U-labels Toggle */}
          <button
            onClick={() => setShowULabels(!showULabels)}
            className={`flex items-center gap-1 px-1.5 py-1 rounded-lg text-xs font-medium transition-all ${
              showULabels ? 'bg-cyan-600/20 text-cyan-400 border border-cyan-500/30' : 'hover:bg-slate-800 text-slate-300'
            }`}
            title={zh ? 'U 位刻度标尺' : 'U Labels'}
          >
            <Layers size={12} />
          </button>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          {/* Cable Mode Selector */}
          <div className="flex items-center rounded-lg p-0.5 bg-slate-900 border border-slate-800 text-xs">
            <button
              onClick={() => setCableMode('select')}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-md font-medium transition-all ${
                cableMode === 'select' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '按需点亮选中跳线' : 'Cables On Select'}
            >
              <Cable size={11} />
              <span>{zh ? '按需' : 'Select'}</span>
            </button>
            <button
              onClick={() => setCableMode('all')}
              className={`px-1.5 py-0.5 rounded-md font-medium transition-all ${
                cableMode === 'all' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '显示全部走线' : 'All Cables'}
            >
              {zh ? '全线' : 'All'}
            </button>
            <button
              onClick={() => setCableMode('off')}
              className={`px-1.5 py-0.5 rounded-md font-medium transition-all ${
                cableMode === 'off' ? 'bg-slate-700 text-slate-200' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '隐藏全部跳线' : 'Hide Cables'}
            >
              {zh ? '关' : 'Off'}
            </button>
          </div>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          {/* Display Mode Switcher */}
          <div className="flex items-center rounded-lg p-0.5 bg-slate-900 border border-slate-800 text-xs">
            <button
              onClick={() => setDisplayMode('physical')}
              className={`px-2 py-0.5 rounded-md font-medium transition-all ${
                displayMode === 'physical' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '物理真实外观' : 'Physical View'}
            >
              {zh ? '真容' : 'Real'}
            </button>
            <button
              onClick={() => setDisplayMode('health')}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md font-medium transition-all ${
                displayMode === 'health' ? 'bg-emerald-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '告警健康热力' : 'Health Heatmap'}
            >
              <Activity size={11} />
              <span>{zh ? '健康' : 'Health'}</span>
            </button>
            <button
              onClick={() => setDisplayMode('role')}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md font-medium transition-all ${
                displayMode === 'role' ? 'bg-purple-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '设备角色分类' : 'Role Classification'}
            >
              <Tag size={11} />
            </button>
            <button
              onClick={() => setDisplayMode('power')}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md font-medium transition-all ${
                displayMode === 'power' ? 'bg-amber-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
              title={zh ? '额定功耗热力' : 'Power Heatmap'}
            >
              <Zap size={11} />
            </button>
          </div>

          <div className="w-[1px] h-3.5 bg-slate-700/80" />

          {/* Maintenance Pull-Out Button */}
          {selectedDeviceId && (
            <>
              <button
                onClick={() => setPulledOutDeviceId(pulledOutDeviceId === selectedDeviceId ? null : selectedDeviceId)}
                className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold transition-all ${
                  pulledOutDeviceId === selectedDeviceId
                    ? 'bg-amber-600 text-white shadow-lg shadow-amber-900/50 ring-1 ring-amber-400 animate-pulse'
                    : 'bg-slate-900 hover:bg-slate-800 text-amber-300 border border-amber-500/50'
                }`}
                title={zh ? '沿导轨抽出 38cm 检修设备' : 'Pull Out 38cm for Maintenance'}
              >
                <Layers size={11} />
                <span>{pulledOutDeviceId === selectedDeviceId ? (zh ? '推回' : 'Push In') : (zh ? '抽出检修' : 'Pull Out')}</span>
              </button>
              <div className="w-[1px] h-3.5 bg-slate-700/80" />
            </>
          )}

          {/* Fullscreen Button */}
          <button
            onClick={handleToggleFullscreen}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
            title={zh ? (isFullscreen ? '退出全屏' : '全屏显示') : (isFullscreen ? 'Exit Fullscreen' : 'Fullscreen')}
          >
            {isFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
            <span>{isFullscreen ? (zh ? '退出' : 'Exit') : (zh ? '全屏' : 'Full')}</span>
          </button>
        </div>

        {/* Top-Right Floating Island (Search Box & Capacity/Power Stats) */}
        <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
          {/* Quick Search */}
          <div className="relative">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl shadow-lg backdrop-blur-xl bg-slate-950/90 border border-slate-700/70 text-slate-200 text-xs">
              <Search size={12} className="text-slate-400" />
              <input
                type="text"
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
              <div className="absolute right-0 top-full mt-1.5 w-72 max-h-60 overflow-y-auto rounded-xl shadow-2xl backdrop-blur-xl bg-slate-950/95 border border-slate-700 p-1 z-30 space-y-0.5">
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
                      <div className="text-[10px] text-slate-400">U{d.startU}-U{d.endU} · {d.vendor} {d.model}</div>
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

            {!rackVM.dataQuality.valid && (
              <button
                onClick={() => setShowDataIssues(!showDataIssues)}
                className="flex items-center gap-1 px-2 py-0.5 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/40 hover:bg-amber-500/30 transition-colors text-[11px]"
              >
                <AlertTriangle size={11} />
                {rackVM.invalidDevices.length} {zh ? '异常' : 'Issues'}
              </button>
            )}
          </div>
        </div>

        {/* Close-up Focus Mode Floating Badge */}
        {focusTarget && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2.5 px-3.5 py-1.5 rounded-full shadow-2xl backdrop-blur-xl bg-slate-950/95 border border-cyan-500/70 text-xs text-cyan-200 animate-in fade-in slide-in-from-top-2">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            <span className="font-semibold">{zh ? '已平滑对焦设备特写' : 'Device Focused'}</span>
            <button
              onClick={() => handlePresetChange('reset')}
              className="ml-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-cyan-600 hover:bg-cyan-500 text-white transition-colors shadow-md"
            >
              {zh ? '恢复全景' : 'Reset'}
            </button>
          </div>
        )}

        {/* 3D Scene Viewport */}
        <div className="flex-1 w-full h-full">
          <RackScene
            rackVM={rackVM}
            selectedDeviceId={selectedDeviceId}
            pulledOutDeviceId={pulledOutDeviceId}
            displayMode={displayMode}
            cableMode={cableMode}
            topologyLinks={topologyLinks}
            zoomAction={zoomAction}
            focusTarget={focusTarget}
            onSelectDevice={onSelectDevice}
            onDoubleClickDevice={handleDoubleClickDevice}
            onHoverDevice={setHoveredDevice}
            cameraPreset={cameraPreset}
            isDoorOpen={isDoorOpen}
            showDoor={showDoor}
            showULabels={showULabels}
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

        {/* Bottom Clean Status Strip (Health Breakdown) */}
        <div className="absolute bottom-3 left-3 z-10 flex items-center gap-3 px-3 py-1.5 rounded-xl shadow-lg backdrop-blur-xl bg-slate-950/85 border border-slate-700/60 text-xs text-slate-300">
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
        </div>

        {/* Floating Device Tooltip HUD */}
        {activeTooltipDevice && (
          <RackDeviceTooltip
            device={activeTooltipDevice}
            onOpenDetail={onSelectDevice}
            zh={zh}
          />
        )}

        {/* Data Quality Issues Panel */}
        {showDataIssues && !rackVM.dataQuality.valid && (
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
              {rackVM.invalidDevices.map(dev => (
                <div key={dev.id} className="p-2 rounded-lg bg-slate-900/90 border border-slate-800">
                  <div className="font-semibold text-slate-200">{dev.name} (U{dev.startU})</div>
                  <ul className="list-disc list-inside text-[11px] text-amber-300/90 mt-1 space-y-0.5">
                    {dev.dataQuality.issues.map((issue, idx) => (
                      <li key={idx}>{issue}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </ThreeErrorBoundary>
  );
};
