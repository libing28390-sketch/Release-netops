import React, { useMemo, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Html } from '@react-three/drei';
import { RackVM, RackDisplayMode, RackDeviceVM } from '../types';
import { RackFrame } from './RackFrame';
import { RackDeviceItem } from './RackDeviceItem';
import { CameraController, CameraPreset, DeviceFocusTarget } from './CameraController';
import { RackCableLayer, CableMode, TopologyLinkItem } from './RackCableLayer';
import { RACK_OUTER_WIDTH_DEFAULT, RACK_TOTAL_DEPTH_DEFAULT } from '../adapters/rackViewModel';

interface RackSceneProps {
  rackVM: RackVM;
  selectedDeviceId?: string | null;
  pulledOutDeviceId?: string | null;
  displayMode?: RackDisplayMode;
  cableMode?: CableMode;
  topologyLinks?: TopologyLinkItem[];
  zoomAction?: { type: 'in' | 'out'; timestamp: number } | null;
  focusTarget?: DeviceFocusTarget | null;
  onSelectDevice: (deviceId: string) => void;
  onDoubleClickDevice?: (device: RackDeviceVM) => void;
  onHoverDevice?: (device: RackDeviceVM | null) => void;
  cameraPreset: CameraPreset;
  isDoorOpen: boolean;
  showDoor: boolean;
  showULabels: boolean;
  zh: boolean;
}

interface RackPlacementMarkerProps {
  device: RackDeviceVM;
  index: number;
  rackHeight: number;
  rackWidth: number;
  onSelectDevice: (deviceId: string) => void;
  onHoverDevice?: (device: RackDeviceVM | null) => void;
  zh: boolean;
}

/**
 * Keep malformed and non-U rows visible without pretending they occupy U1.
 * The marker sits just outside the rack and is still selectable, so data
 * quality problems remain actionable in the 3D read-only view.
 */
const RackPlacementMarker: React.FC<RackPlacementMarkerProps> = ({
  device,
  index,
  rackHeight,
  rackWidth,
  onSelectDevice,
  onHoverDevice,
  zh,
}) => {
  const hasKnownU = device.mountKind === 'u_mount' && device.startKnown !== false && device.heightKnown !== false;
  const markerY = hasKnownU
    ? Math.min(rackHeight - 0.3, Math.max(0.3, device.coordinates.centerY))
    : Math.max(0.45, rackHeight - 0.55 - ((index % 8) * 0.45));
  const markerX = rackWidth / 2 + 0.85;
  const label = hasKnownU
    ? `${device.name} · U${device.startU}`
    : `${device.name} · ${device.mountKind || 'unknown'}`;

  return (
    <group
      position={[markerX, markerY, 0]}
      onClick={event => {
        event.stopPropagation();
        onSelectDevice(device.id);
      }}
      onPointerOver={event => {
        event.stopPropagation();
        onHoverDevice?.(device);
      }}
      onPointerOut={event => {
        event.stopPropagation();
        onHoverDevice?.(null);
      }}
    >
      <mesh>
        <boxGeometry args={[0.45, 0.28, 0.45]} />
        <meshBasicMaterial color="#f59e0b" transparent opacity={0.82} />
      </mesh>
      <Html center distanceFactor={16} position={[0.45, 0, 0]}>
        <div className="pointer-events-none whitespace-nowrap rounded border border-amber-400/50 bg-slate-950/90 px-1.5 py-1 text-[9px] text-amber-200 shadow-lg">
          {label}
          <span className="ml-1 text-amber-400/80">({zh ? '待确认' : 'review'})</span>
        </div>
      </Html>
    </group>
  );
};

export const RackScene: React.FC<RackSceneProps> = ({
  rackVM,
  selectedDeviceId,
  pulledOutDeviceId,
  displayMode = 'physical',
  cableMode = 'select',
  topologyLinks = [],
  zoomAction,
  focusTarget,
  onSelectDevice,
  onDoubleClickDevice,
  onHoverDevice,
  cameraPreset,
  isDoorOpen,
  showDoor,
  showULabels,
  zh
}) => {
  const rackHeight = rackVM.totalU * 0.4445;
  const rackWidth = (rackVM.widthMm / 600) * RACK_OUTER_WIDTH_DEFAULT;
  const rackDepth = (rackVM.depthMm / 1000) * RACK_TOTAL_DEPTH_DEFAULT;
  const centerY = rackHeight / 2;
  const controlsRef = useRef<any>(null);

  const occupiedUs = useMemo(() => {
    const s = new Set<number>();
    rackVM.validDevices.forEach(d => {
      for (let u = d.startU; u < d.startU + d.heightU; u++) {
        s.add(u);
      }
    });
    return s;
  }, [rackVM.validDevices]);

  const selectedDevice = useMemo(() => {
    if (!selectedDeviceId) return undefined;
    return rackVM.devices.find(d => d.id === selectedDeviceId);
  }, [rackVM.devices, selectedDeviceId]);

  return (
    <div className="w-full h-full relative select-none">
      <Canvas
        camera={{ position: [14, centerY + 5, 20], fov: 45, near: 0.1, far: 1000 }}
        gl={{
          antialias: true,
          alpha: true,
          powerPreference: 'default',
          preserveDrawingBuffer: false
        }}
        dpr={[1, 2]}
        onCreated={({ gl }) => {
          gl.domElement.addEventListener('webglcontextlost', (e) => {
            e.preventDefault();
            console.warn('WebGL context lost, awaiting restoration...');
          });
        }}
      >
        {/* Studio Lighting Setup */}
        <ambientLight intensity={2.0} color="#f8fafc" />
        <directionalLight position={[12, centerY + 18, 22]} intensity={2.2} color="#ffffff" castShadow />
        <directionalLight position={[-16, centerY + 12, 18]} intensity={1.6} color="#e0f2fe" />
        <directionalLight position={[0, centerY + 15, -24]} intensity={1.8} color="#93c5fd" />
        <pointLight position={[0, rackHeight + 6, 0]} intensity={1.2} color="#ffffff" distance={40} />
        <pointLight position={[0, centerY, 14]} intensity={0.9} color="#e2e8f0" distance={30} />
        <pointLight position={[0, -1.5, 12]} intensity={0.7} color="#38bdf8" distance={25} />

        {/* Camera Transition Controller */}
        <CameraController
          preset={cameraPreset}
          rackHeight={rackHeight}
          rackWidth={rackWidth}
          rackDepth={rackDepth}
          focusTarget={focusTarget}
          zoomAction={zoomAction}
          controlsRef={controlsRef}
        />

        {/* Orbit Controls with Smooth Zoom */}
        <OrbitControls
          ref={controlsRef}
          makeDefault
          target={[0, centerY, 0]}
          minDistance={2}
          maxDistance={60}
          zoomSpeed={1.4}
          maxPolarAngle={Math.PI / 2 + 0.05}
          enableDamping
          dampingFactor={0.12}
        />

        {/* Datacenter Floor Grid */}
        <Grid
          position={[0, -0.46, 0]}
          args={[60, 60]}
          cellSize={1}
          cellThickness={0.6}
          cellColor="#334155"
          sectionSize={5}
          sectionThickness={1.2}
          sectionColor="#0ea5e9"
          fadeDistance={50}
        />

        {/* Main Parametric Rack Enclosure */}
        <RackFrame
          name={rackVM.name}
          totalU={rackVM.totalU}
          widthMm={rackVM.widthMm}
          depthMm={rackVM.depthMm}
          showDoor={showDoor}
          isDoorOpen={isDoorOpen}
          showULabels={showULabels}
          occupiedUs={occupiedUs}
          zh={zh}
        />

        {/* Installed Devices */}
        <group>
          {rackVM.validDevices.map(device => (
            <RackDeviceItem
              key={device.id}
              device={device}
              isSelected={device.id === selectedDeviceId}
              isPulledOut={device.id === pulledOutDeviceId}
              isAnySelected={Boolean(selectedDeviceId)}
              displayMode={displayMode}
              links={topologyLinks}
              onSelect={onSelectDevice}
              onDoubleClick={onDoubleClickDevice}
              onHover={onHoverDevice}
            />
          ))}
          {[...rackVM.invalidDevices, ...(rackVM.nonUDevices || [])].map((device, index) => (
            <RackPlacementMarker
              key={`placement-marker-${device.id}`}
              device={device}
              index={index}
              rackHeight={rackHeight}
              rackWidth={rackWidth}
              onSelectDevice={onSelectDevice}
              onHoverDevice={onHoverDevice}
              zh={zh}
            />
          ))}
        </group>


        {/* Structured 3D Cabling Layer */}
        <RackCableLayer
          rackVM={rackVM}
          selectedDeviceId={selectedDeviceId}
          cableMode={cableMode}
          links={topologyLinks}
        />
      </Canvas>
    </div>
  );
};
