import React, { useMemo, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid } from '@react-three/drei';
import { RackVM, RackDisplayMode, RackDeviceVM } from '../types';
import { RackFrame } from './RackFrame';
import { RackDeviceItem } from './RackDeviceItem';
import { CameraController, CameraPreset, DeviceFocusTarget } from './CameraController';
import { RackCableLayer, CableMode, TopologyLinkItem } from './RackCableLayer';

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
}

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
  showULabels
}) => {
  const rackHeight = rackVM.totalU * 0.4445;
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
          preserveDrawingBuffer: true
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
