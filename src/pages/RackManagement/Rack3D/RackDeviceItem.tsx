import React, { useState, useRef } from 'react';
import * as THREE from 'three';
import { ThreeEvent, useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import { RackDeviceVM, RackDisplayMode } from '../types';
import { ProceduralChassis } from './models/ProceduralChassis';
import { SwitchFaceplate } from './models/SwitchFaceplate';
import { ServerFaceplate } from './models/ServerFaceplate';
import { GenericFaceplate } from './models/GenericFaceplate';

import { TopologyLinkItem } from './RackCableLayer';

interface RackGlbDeviceProps {
  url: string;
  height: number;
  depth: number;
}

const RackGlbDevice: React.FC<RackGlbDeviceProps> = ({ url, height, depth }) => {
  const { scene } = useGLTF(url);
  const clonedScene = React.useMemo(() => scene.clone(true), [scene]);
  // Blender assets use meters and X/Y/Z = left-right/front-back/vertical;
  // the viewer uses X/Y/Z = left-right/vertical/front-back.  The negative
  // local Z scale preserves the positive vertical direction after the X
  // quarter-turn, while local +Y remains viewer-front (+Z).
  return (
    <primitive
      object={clonedScene}
      position={[0, -height / 2, depth / 2]}
      rotation={[Math.PI / 2, 0, 0]}
      scale={[10, 10, -10]}
    />
  );
};

interface RackGlbErrorBoundaryProps {
  resetKey: string;
  fallback: React.ReactNode;
  children: React.ReactNode;
}

interface RackGlbErrorBoundaryState {
  hasError: boolean;
}

/** A bad optional GLB must not take down the complete rack scene. */
class RackGlbErrorBoundary extends React.Component<RackGlbErrorBoundaryProps, RackGlbErrorBoundaryState> {
  state: RackGlbErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): RackGlbErrorBoundaryState {
    return { hasError: true };
  }

  componentDidUpdate(previousProps: RackGlbErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

interface RackDeviceItemProps {
  device: RackDeviceVM;
  isSelected: boolean;
  isPulledOut?: boolean;
  isAnySelected?: boolean;
  displayMode?: RackDisplayMode;
  links?: TopologyLinkItem[];
  onSelect: (deviceId: string) => void;
  onDoubleClick?: (device: RackDeviceVM) => void;
  onHover?: (device: RackDeviceVM | null) => void;
}

export const RackDeviceItem: React.FC<RackDeviceItemProps> = ({
  device,
  isSelected,
  isPulledOut = false,
  isAnySelected = false,
  displayMode = 'physical',
  links = [],
  onSelect,
  onDoubleClick,
  onHover
}) => {
  const [hovered, setHovered] = useState(false);
  const groupRef = useRef<THREE.Group>(null);
  const { coordinates, role, vendor, model, face, healthStatus, metrics } = device;

  // Derive which ports physically have active cable connections
  const connectedPortNumbers = React.useMemo(() => {
    const ports: number[] = [];
    const devName = device.name.toUpperCase();
    (links || []).forEach(l => {
      const isLocal = l.local_device_id === device.id || (l.local_device_name && l.local_device_name.toUpperCase() === devName);
      const isRemote = l.remote_device_id === device.id || (l.remote_device_name && l.remote_device_name.toUpperCase() === devName);
      if (isLocal) {
        const match = (l.local_interface || '').match(/(\d+)$/);
        if (match) ports.push(parseInt(match[1], 10));
      }
      if (isRemote) {
        const match = (l.remote_interface || '').match(/(\d+)$/);
        if (match) ports.push(parseInt(match[1], 10));
      }
    });
    return Array.from(new Set(ports));
  }, [device.id, device.name, links]);

  // Smooth pull-out animation on selection / service maintenance mode
  useFrame((_, delta) => {
    if (!groupRef.current) return;
    const targetZ = isPulledOut ? 3.8 : (isSelected ? 0.6 : 0);
    groupRef.current.position.z = THREE.MathUtils.damp(
      groupRef.current.position.z,
      targetZ,
      12,
      delta
    );
  });

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    onSelect(device.id);
  };

  const handleDoubleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    onSelect(device.id);
    if (onDoubleClick) {
      onDoubleClick(device);
    }
  };

  const handlePointerOver = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(true);
    if (onHover) onHover(device);
    document.body.style.cursor = 'pointer';
  };

  const handlePointerOut = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(false);
    if (onHover) onHover(null);
    document.body.style.cursor = 'auto';
  };

  const renderProceduralFaceplate = () => {
    const normRole = (role || '').toLowerCase();
    if (normRole === 'switch') {
      return (
        <SwitchFaceplate
          width={coordinates.width}
          height={coordinates.height}
          depth={coordinates.depth}
          face={face}
          deviceName={device.name}
          vendor={vendor}
          model={model}
          heightU={device.heightU}
          healthStatus={healthStatus}
          connectedPortNumbers={connectedPortNumbers}
        />
      );
    }

    if (normRole === 'server' || normRole === 'storage') {
      return (
        <ServerFaceplate
          width={coordinates.width}
          height={coordinates.height}
          depth={coordinates.depth}
          face={face}
          deviceName={device.name}
          vendor={vendor}
          model={model}
          heightU={device.heightU}
          healthStatus={healthStatus}
        />
      );
    }
    return (
      <GenericFaceplate
        width={coordinates.width}
        height={coordinates.height}
        depth={coordinates.depth}
        face={face}
        deviceName={device.name}
        role={normRole}
        vendor={vendor}
        model={model}
        heightU={device.heightU}
        healthStatus={healthStatus}
      />
    );
  };

  const renderFaceplate = () => {
    if (device.assetAvailable && device.assetUrl && device.face === 'front') {
      const fallback = renderProceduralFaceplate();
      return (
        <RackGlbErrorBoundary resetKey={device.assetUrl} fallback={fallback}>
          <React.Suspense fallback={fallback}>
            <RackGlbDevice url={device.assetUrl} height={coordinates.height} depth={coordinates.depth} />
          </React.Suspense>
        </RackGlbErrorBoundary>
      );
    }
    return renderProceduralFaceplate();
  };

  return (
    <group
      position={[0, coordinates.centerY, coordinates.centerZ]}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onPointerOver={handlePointerOver}
      onPointerOut={handlePointerOut}
    >
      <group ref={groupRef}>
        {/* Expanded Invisible Hitbox for Instant Click Responsiveness */}
        <mesh
          position={[0, 0, 0]}
          onClick={handleClick}
          onDoubleClick={handleDoubleClick}
          onPointerOver={handlePointerOver}
          onPointerOut={handlePointerOut}
        >
          <boxGeometry args={[coordinates.width + 0.2, coordinates.height + 0.05, coordinates.depth + 0.3]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>

        <ProceduralChassis
          width={coordinates.width}
          height={coordinates.height}
          depth={coordinates.depth}
          healthStatus={healthStatus}
          role={role}
          ratedPowerWatts={metrics.ratedPowerWatts}
          displayMode={displayMode}
          selected={isSelected}
          isPulledOut={isPulledOut}
          isAnySelected={isAnySelected}
        />
        {renderFaceplate()}
      </group>
    </group>
  );
};
