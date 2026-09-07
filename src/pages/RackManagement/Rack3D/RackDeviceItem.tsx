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

type LedMaterial = THREE.Material & {
  emissive?: THREE.Color;
  emissiveIntensity?: number;
  color?: THREE.Color;
};

interface AnimatedGlbLed {
  material: LedMaterial;
  isStatusLed: boolean;
  baseIntensity: number;
  baseColor?: THREE.Color;
  baseOpacity: number;
  phase: number;
}

interface RackGlbSceneState {
  scene: THREE.Object3D;
  leds: AnimatedGlbLed[];
}

const RackGlbDevice: React.FC<RackGlbDeviceProps> = ({ url, height, depth }) => {
  const { scene } = useGLTF(url);
  const sceneState = React.useMemo<RackGlbSceneState>(() => {
    const clonedScene = scene.clone(true);
    const leds: AnimatedGlbLed[] = [];
    let ledIndex = 0;

    clonedScene.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;

      const metadata = object.userData?.extras || object.userData;
      const componentType = String(metadata?.component_type || '').toLowerCase();
      const objectName = String(object.name || '').toUpperCase();
      const sourceMaterials = Array.isArray(object.material) ? object.material : [object.material];
      const isStatusLed = componentType === 'status_led'
        || /STATUS|POWER|SYSTEM|ALARM/.test(objectName)
        || sourceMaterials.some(material => /MAT_LED_(GREEN|BLUE|AMBER)/.test(String(material.name || '').toUpperCase()));
      const isPortLed = componentType === 'port_led'
        || (objectName.includes('LED') && !isStatusLed)
        || sourceMaterials.some(material => String(material.name || '').toUpperCase().includes('MAT_LED_PORT'));
      const clonedMaterials = sourceMaterials.map(sourceMaterial => {
        const materialName = String(sourceMaterial.name || '').toUpperCase();
        const materialIsStatusLed = isStatusLed && (componentType === 'status_led' || /MAT_LED_(GREEN|BLUE|AMBER)/.test(materialName) || !materialName);
        const materialIsPortLed = isPortLed && (componentType === 'port_led' || materialName.includes('MAT_LED_PORT') || !materialName);
        if (!materialIsStatusLed && !materialIsPortLed) return sourceMaterial;

        // GLTF clones share materials by default. Clone only LED materials so
        // each device can animate independently without changing every other
        // instance that uses the same asset.
        const material = sourceMaterial.clone() as LedMaterial;
        // Disable tone mapping for tiny lenses: their color remains legible
        // both in a full-rack view and in a close-up inspection. The color/
        // opacity fallback also keeps animation working for basic materials.
        material.toneMapped = false;
        leds.push({
          material,
          isStatusLed: materialIsStatusLed,
          baseIntensity: material.emissive && typeof material.emissiveIntensity === 'number'
            ? Math.max(0.9, material.emissiveIntensity)
            : 1,
          baseColor: material.color?.clone(),
          baseOpacity: material.opacity,
          phase: ledIndex * 0.37
        });
        ledIndex += 1;
        return material;
      });

      object.material = Array.isArray(object.material) ? clonedMaterials : clonedMaterials[0];
      if (isStatusLed || isPortLed) {
        // A small geometry lift improves the silhouette at distance without
        // changing the physical port layout or the generated GLB dimensions.
        const visibilityScale = isStatusLed ? 1.28 : 1.10;
        object.scale.multiplyScalar(visibilityScale);
      }
    });

    return { scene: clonedScene, leds };
  }, [scene]);

  useFrame(({ clock }) => {
    const time = clock.getElapsedTime();
    sceneState.leds.forEach(led => {
      const pulse = 0.5 + 0.5 * Math.sin(time * (led.isStatusLed ? 3.0 : 1.8) + led.phase);
      // Status/power lamps visibly breathe; port indicators keep a steadier
      // activity pulse so the front panel remains readable at distance.
      const multiplier = led.isStatusLed ? 0.18 + pulse * 1.5 : 0.55 + pulse * 0.65;
      if (led.material.emissive && typeof led.material.emissiveIntensity === 'number') {
        led.material.emissiveIntensity = led.baseIntensity * multiplier;
      } else if (led.baseColor && led.material.color) {
        led.material.color.copy(led.baseColor).multiplyScalar(0.65 + pulse * 0.7);
        led.material.opacity = led.baseOpacity * (0.7 + pulse * 0.3);
      }
    });
  });

  // Blender assets use meters and X/Y/Z = left-right/front-back/vertical;
  // the viewer uses X/Y/Z = left-right/vertical/front-back.  The negative
  // local Z scale preserves the positive vertical direction after the X
  // quarter-turn, while local +Y remains viewer-front (+Z).
  return (
    <primitive
      object={sceneState.scene}
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
  // The production GLB contains both front and rear assemblies.  Use it for
  // either face so rear inspection exposes the real PSU/fan/management
  // details instead of silently reverting to the older procedural shell.
  const useGlbAsset = Boolean(device.assetAvailable && device.assetUrl && (device.face === 'front' || device.face === 'rear'));

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
    if (useGlbAsset && device.assetUrl) {
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

        {!useGlbAsset && (
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
        )}
        {renderFaceplate()}
      </group>
    </group>
  );
};
