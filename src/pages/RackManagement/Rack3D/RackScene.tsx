import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, Grid, Html } from '@react-three/drei';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { RackVM, RackDisplayMode, RackDeviceVM } from '../types';
import { RackAssetFrame } from './RackAssetFrame';
import { RackDeviceItem } from './RackDeviceItem';
import { CameraController, CameraPreset, DeviceFocusTarget } from './CameraController';
import { RackCableLayer, CableMode, TopologyLinkItem } from './RackCableLayer';
import { RackInfrastructureLayer } from './RackInfrastructureLayer';
import { RACK_OUTER_WIDTH_DEFAULT, RACK_TOTAL_DEPTH_DEFAULT } from '../adapters/rackViewModel';
import { GraphicsQualityMode } from './gpuProfile';
import {
  getSoftContactShadowTexture,
  getFloorLightPoolTexture,
  getRaisedFloorPbrTextures,
  getPerforatedColdTileTexture,
  getStudioSkyGradientTexture,
} from './roomTextures';

export type SceneInteractionMode = 'orbit' | 'pan';
export type SingleRackLightingMode = 'daylight' | 'standby' | 'lights_out';

interface RackSceneProps {
  rackVM: RackVM;
  selectedDeviceId?: string | null;
  pulledOutDeviceId?: string | null;
  displayMode?: RackDisplayMode;
  cableMode?: CableMode;
  topologyLinks?: TopologyLinkItem[];
  showPreviewCables?: boolean;
  zoomAction?: { type: 'in' | 'out'; timestamp: number } | null;
  focusTarget?: DeviceFocusTarget | null;
  interactionMode?: SceneInteractionMode;
  graphicsMode?: GraphicsQualityMode;
  lightingMode?: SingleRackLightingMode;
  cabinetLightsOn?: boolean;
  onSelectDevice: (deviceId: string) => void;
  onDoubleClickDevice?: (device: RackDeviceVM, hitPoint?: { x: number; y: number; z: number }) => void;
  onHoverDevice?: (device: RackDeviceVM | null) => void;
  cameraPreset: CameraPreset;
  isDoorOpen: boolean;
  showDoor: boolean;
  showULabels: boolean;
  showPowerCords?: boolean;
  showBlankingPanels?: boolean;
  showAirflow?: boolean;
  showBayContext?: boolean;
  zh: boolean;
}

/** Realistic Data Center Bay Staging around the focused single rack (raised floor, cold grate, overhead trays & subtle bay context). */
const SingleRackBayStaging: React.FC<{
  rackHeight: number;
  rackWidth: number;
  rackDepth: number;
  showBayContext: boolean;
}> = ({ rackHeight, rackWidth, rackDepth, showBayContext }) => {
  const { floorMap, floorRoughness, perfTex, shadowTex, lightPoolTex, skyTex } = useMemo(() => {
    const base = getRaisedFloorPbrTextures();
    const map = base.map.clone();
    const rough = base.roughnessMap.clone();
    map.needsUpdate = true;
    rough.needsUpdate = true;
    map.repeat.set(9, 9);
    rough.repeat.set(9, 9);
    return {
      floorMap: map,
      floorRoughness: rough,
      perfTex: getPerforatedColdTileTexture(),
      shadowTex: getSoftContactShadowTexture(),
      lightPoolTex: getFloorLightPoolTexture(),
      skyTex: getStudioSkyGradientTexture(),
    };
  }, []);

  useEffect(() => () => {
    floorMap.dispose();
    floorRoughness.dispose();
  }, [floorMap, floorRoughness]);

  const floorY = -1.07;
  const trayY = rackHeight + 2.35;

  return (
    <group>
      {/* Subtle architectural midnight-to-slate studio gradient dome */}
      <mesh scale={[-1, 1, 1]}>
        <sphereGeometry args={[180, 20, 12]} />
        <meshBasicMaterial map={skyTex} side={THREE.BackSide} depthWrite={false} />
      </mesh>

      {/* Baked studio contact AO shadow & cool floor reflection light pool */}
      <mesh position={[0, floorY + 0.015, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[rackWidth + 3.6, rackDepth + 3.6]} />
        <meshBasicMaterial map={shadowTex} transparent opacity={0.88} depthWrite={false} />
      </mesh>
      <mesh position={[0, floorY + 0.01, 2.5]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[22, 22]} />
        <meshBasicMaterial map={lightPoolTex} transparent opacity={0.72} depthWrite={false} />
      </mesh>

      {showBayContext ? (
        <group>
          {/* Satin 600x600mm Anti-Static Raised Floor Bay */}
          <mesh position={[0, floorY, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[52, 52]} />
            <meshStandardMaterial
              map={floorMap}
              roughnessMap={floorRoughness}
              color="#eef2f6"
              roughness={0.4}
              metalness={0.25}
            />
          </mesh>

          {/* Front Perforated Cold-Aisle Chilled Air Intake Grate */}
          <group position={[0, floorY + 0.02, rackDepth / 2 + 4.4]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[16, 6.2]} />
              <meshStandardMaterial
                map={perfTex}
                roughness={0.32}
                metalness={0.62}
                emissive="#0284c7"
                emissiveIntensity={0.42}
              />
            </mesh>
            <mesh position={[0, 0.01, 3.16]} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[16.4, 0.16]} />
              <meshBasicMaterial color="#38bdf8" toneMapped={false} />
            </mesh>
            <mesh position={[0, 0.01, -3.16]} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[16.4, 0.16]} />
              <meshBasicMaterial color="#38bdf8" toneMapped={false} />
            </mesh>
          </group>

          {/* Subtle Non-Interactive Neighboring Bay Ghost Cabinets (provides immediate real-row scale) */}
          {[-1, 1].map(side => (
            <group
              key={`ghost-bay-${side}`}
              position={[side * (rackWidth + 0.55), rackHeight / 2 - 0.1, 0]}
            >
              <mesh>
                <boxGeometry args={[rackWidth * 0.96, rackHeight + 0.65, rackDepth * 0.96]} />
                <meshStandardMaterial
                  color="#0e1624"
                  roughness={0.55}
                  metalness={0.55}
                  transparent
                  opacity={0.34}
                  depthWrite={false}
                />
              </mesh>
              <mesh position={[0, rackHeight / 2 + 0.32, rackDepth * 0.48]}>
                <boxGeometry args={[rackWidth * 0.88, 0.14, 0.06]} />
                <meshBasicMaterial color="#1e3a5f" transparent opacity={0.55} />
              </mesh>
            </group>
          ))}

          {/* Overhead Dual-Layer Yellow Fiber Raceway + Galvanized A/B Power Tray feeding the cabinet */}
          <group position={[0, trayY, 0]}>
            {/* Upper yellow fiber trough (front-aligned) */}
            <mesh position={[0, 0.6, rackDepth * 0.22]}>
              <boxGeometry args={[26, 0.16, 2.1]} />
              <meshStandardMaterial color="#eab308" roughness={0.35} metalness={0.28} />
            </mesh>
            <mesh position={[0, 0.92, rackDepth * 0.22 + 1.0]}>
              <boxGeometry args={[26, 0.55, 0.14]} />
              <meshStandardMaterial color="#facc15" roughness={0.32} metalness={0.28} />
            </mesh>
            <mesh position={[0, 0.92, rackDepth * 0.22 - 1.0]}>
              <boxGeometry args={[26, 0.55, 0.14]} />
              <meshStandardMaterial color="#facc15" roughness={0.32} metalness={0.28} />
            </mesh>
            {/* Fiber waterfall drop-out into cabinet roof */}
            <mesh position={[1.1, -0.52, rackDepth * 0.22]}>
              <boxGeometry args={[1.15, 2.35, 0.62]} />
              <meshStandardMaterial color="#facc15" roughness={0.32} metalness={0.3} />
            </mesh>

            {/* Lower galvanized steel power ladder & Red/Blue A/B busway (rear-aligned) */}
            <mesh position={[0, -0.35, -rackDepth * 0.24 - 1.05]}>
              <boxGeometry args={[26, 0.42, 0.15]} />
              <meshStandardMaterial color="#94a3b8" roughness={0.34} metalness={0.82} />
            </mesh>
            <mesh position={[0, -0.35, -rackDepth * 0.24 + 1.05]}>
              <boxGeometry args={[26, 0.42, 0.15]} />
              <meshStandardMaterial color="#94a3b8" roughness={0.34} metalness={0.82} />
            </mesh>
            <mesh position={[0, -0.3, -rackDepth * 0.24 - 0.45]}>
              <boxGeometry args={[26, 0.28, 0.34]} />
              <meshStandardMaterial color="#dc2626" roughness={0.4} metalness={0.45} />
            </mesh>
            <mesh position={[0, -0.3, -rackDepth * 0.24 + 0.45]}>
              <boxGeometry args={[26, 0.28, 0.34]} />
              <meshStandardMaterial color="#2563eb" roughness={0.4} metalness={0.45} />
            </mesh>
            {/* Rear A/B power drop conduits descending cleanly into cabinet roof */}
            <mesh position={[-1.4, -1.08, -rackDepth * 0.24]}>
              <cylinderGeometry args={[0.16, 0.16, 1.5, 10]} />
              <meshStandardMaterial color="#991b1b" roughness={0.4} metalness={0.6} />
            </mesh>
            <mesh position={[1.4, -1.08, -rackDepth * 0.24]}>
              <cylinderGeometry args={[0.16, 0.16, 1.5, 10]} />
              <meshStandardMaterial color="#1d4ed8" roughness={0.4} metalness={0.6} />
            </mesh>
          </group>
        </group>
      ) : (
        <Grid
          position={[0, floorY, 0]}
          args={[60, 60]}
          cellSize={1}
          cellThickness={0.55}
          cellColor="#1e293b"
          sectionSize={5}
          sectionThickness={1.1}
          sectionColor="#0ea5e9"
          fadeDistance={48}
        />
      )}
    </group>
  );
};

/** Offline Studio HDRI reflection map — kept active in BOTH Eco and High modes for 100% PBR brightness parity! */
const StudioEnvironment: React.FC<{ lightingMode: SingleRackLightingMode }> = ({ lightingMode }) => {
  const { gl, scene } = useThree();
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const env = new RoomEnvironment();
    const rt = pmrem.fromScene(env, 0.04);
    scene.environment = rt.texture;
    return () => {
      scene.environment = null;
      rt.dispose();
      env.dispose();
      pmrem.dispose();
    };
  }, [gl, scene]);

  useEffect(() => {
    (scene as any).environmentIntensity =
      lightingMode === 'daylight' ? 1.05 : lightingMode === 'standby' ? 0.38 : 0.12;
  }, [scene, lightingMode]);

  return null;
};

interface RackPlacementMarkerProps {
  device: RackDeviceVM;
  index: number;
  rackHeight: number;
  rackWidth: number;
  onSelectDevice: (deviceId: string) => void;
  onHoverDevice?: (device: RackDeviceVM | null) => void;
  zh: boolean;
}

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
  showPreviewCables = false,
  zoomAction,
  focusTarget,
  interactionMode = 'orbit',
  graphicsMode = 'high',
  lightingMode = 'daylight',
  cabinetLightsOn = true,
  onSelectDevice,
  onDoubleClickDevice,
  onHoverDevice,
  cameraPreset,
  isDoorOpen,
  showDoor,
  showULabels,
  showPowerCords = true,
  showBlankingPanels = false,
  showAirflow = false,
  showBayContext = true,
  zh,
}) => {
  const rackHeight = rackVM.totalU * 0.4445;
  const rackWidth = (rackVM.widthMm / 600) * RACK_OUTER_WIDTH_DEFAULT;
  const rackDepth = (rackVM.depthMm / 1000) * RACK_TOTAL_DEPTH_DEFAULT;
  const centerY = rackHeight / 2;
  const controlsRef = useRef<any>(null);
  const [spacePanning, setSpacePanning] = useState(false);

  // Hold Spacebar anywhere outside inputs to temporarily switch Left-Drag into Pan mode
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

  // Sync dynamic mouseButtons & zoomToCursor onto live OrbitControls instance without resetting target
  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;
    ctrl.mouseButtons = mouseButtons;
    if ('zoomToCursor' in ctrl) {
      ctrl.zoomToCursor = true;
    }
  }, [mouseButtons]);

  const occupiedUs = useMemo(() => {
    const s = new Set<number>();
    rackVM.validDevices.forEach(d => {
      for (let u = d.startU; u < d.startU + d.heightU; u++) {
        s.add(u);
      }
    });
    return s;
  }, [rackVM.validDevices]);

  return (
    <div className={`w-full h-full relative select-none ${isPanActive ? 'cursor-grab active:cursor-grabbing' : ''}`}>
      <Canvas
        camera={{ position: [14, centerY + 4, 21], fov: 42, near: 0.03, far: 1000 }}
        gl={{
          antialias: true,
          alpha: true,
          powerPreference: graphicsMode === 'eco' ? 'default' : 'high-performance',
          toneMapping: THREE.ACESFilmicToneMapping,
          toneMappingExposure: 1.12,
          preserveDrawingBuffer: false,
        }}
        dpr={graphicsMode === 'eco' ? [1, 1] : [1, 1.75]}
        onCreated={({ gl }) => {
          gl.domElement.addEventListener('webglcontextlost', (e) => {
            e.preventDefault();
            console.warn('WebGL context lost, awaiting restoration...');
          });
        }}
      >
        {/* Offline Studio IBL (active in BOTH Eco & High for metallic parity) + Independent Lighting Rig */}
        <StudioEnvironment lightingMode={lightingMode} />
        <hemisphereLight
          args={[
            lightingMode === 'daylight' ? '#f8fafc' : '#60a5fa',
            lightingMode === 'daylight' ? '#94a3b8' : '#0f172a',
            lightingMode === 'daylight' ? 0.78 : lightingMode === 'standby' ? 0.24 : 0.08,
          ]}
        />
        <ambientLight
          intensity={lightingMode === 'daylight' ? 0.56 : lightingMode === 'standby' ? 0.18 : 0.06}
          color={lightingMode === 'daylight' ? '#f8fafc' : '#93c5fd'}
        />
        <directionalLight
          position={[11, centerY + 14, 18]}
          intensity={lightingMode === 'daylight' ? 1.65 : lightingMode === 'standby' ? 0.48 : 0.14}
          color={lightingMode === 'daylight' ? '#fffcf7' : '#bae6fd'}
        />
        <directionalLight
          position={[-15, centerY + 10, 12]}
          intensity={lightingMode === 'daylight' ? 0.92 : lightingMode === 'standby' ? 0.28 : 0.08}
          color="#bae6fd"
        />
        <directionalLight
          position={[0, centerY + 12, -18]}
          intensity={lightingMode === 'daylight' ? 1.2 : lightingMode === 'standby' ? 0.36 : 0.1}
          color="#dbeafe"
        />
        {lightingMode !== 'lights_out' && (
          <pointLight
            position={[0, 1.8, rackDepth / 2 + 5.5]}
            intensity={lightingMode === 'daylight' ? 0.95 : 1.9}
            distance={22}
            color="#38bdf8"
          />
        )}

        <CameraController
          preset={cameraPreset}
          rackHeight={rackHeight}
          rackWidth={rackWidth}
          rackDepth={rackDepth}
          focusTarget={focusTarget}
          zoomAction={zoomAction}
          controlsRef={controlsRef}
        />

        <OrbitControls
          ref={controlsRef}
          makeDefault
          target={[0, centerY, 0]}
          minDistance={0.55}
          maxDistance={60}
          rotateSpeed={0.85}
          zoomSpeed={1.25}
          panSpeed={1.15}
          screenSpacePanning
          zoomToCursor
          mouseButtons={mouseButtons}
          maxPolarAngle={Math.PI / 2 + 0.04}
          enableDamping
          dampingFactor={0.08}
        />

        {/* Datacenter Raised Floor Bay Staging + Studio Sky Dome & Overhead Tray Drops */}
        <SingleRackBayStaging
          rackHeight={rackHeight}
          rackWidth={rackWidth}
          rackDepth={rackDepth}
          showBayContext={showBayContext}
        />

        {/* Native Y-Up PBR 42U Cabinet */}
        <RackAssetFrame
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
          showPreviewWhenEmpty={showPreviewCables}
        />

        {/* Rear Dual 0U PDU AC Power Cords, Smart LCDs, M6 Screws, Blanking Panels & Cold/Hot Airflow */}
        <RackInfrastructureLayer
          rackVM={rackVM}
          occupiedUs={occupiedUs}
          rackWidth={rackWidth}
          rackDepth={rackDepth}
          showPowerCords={showPowerCords}
          showBlankingPanels={showBlankingPanels}
          showAirflow={showAirflow}
          cabinetLightsOn={cabinetLightsOn}
        />
      </Canvas>
    </div>
  );
};
