import React, { useState, useRef } from 'react';
import * as THREE from 'three';
import { ThreeEvent, useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import { RackDeviceVM, RackDisplayMode } from '../types';
import { ProceduralChassis } from './models/ProceduralChassis';
import { SwitchFaceplate } from './models/SwitchFaceplate';
import { ServerFaceplate } from './models/ServerFaceplate';
import { GenericFaceplate } from './models/GenericFaceplate';
import { PatchPanelFaceplate } from './models/PatchPanelFaceplate';
import { QsfpPortAssembly } from './models/QsfpPortAssembly';
import { SfpModuleAssembly, type SfpModuleMedia } from './models/SfpModuleAssembly';

import { getPortPhysicalCoordinates, TopologyLinkItem } from './RackCableLayer';

interface RackGlbDeviceProps {
  url: string;
  height: number;
  depth: number;
  face: RackDeviceVM['face'];
  healthStatus: RackDeviceVM['healthStatus'];
  connectedPortNumbers: number[];
}

type LedMaterial = THREE.Material & {
  emissive?: THREE.Color;
  emissiveIntensity?: number;
  color?: THREE.Color;
};

interface AnimatedGlbLed {
  material: LedMaterial;
  channel: 'power' | 'system' | 'alarm' | 'port';
  portIndex?: number;
  connectionFace?: 'front' | 'rear';
  lane: 'primary' | 'secondary';
  connected: boolean;
  baseIntensity: number;
  baseOpacity: number;
  phase: number;
}

interface RackGlbSceneState {
  scene: THREE.Object3D;
  leds: AnimatedGlbLed[];
}

const RackGlbDevice: React.FC<RackGlbDeviceProps> = ({
  url,
  height,
  depth,
  face,
  healthStatus,
  connectedPortNumbers,
}) => {
  const { scene } = useGLTF(url);
  const sceneState = React.useMemo<RackGlbSceneState>(() => {
    const clonedScene = scene.clone(true);
    const leds: AnimatedGlbLed[] = [];
    let ledIndex = 0;
    const connectedPorts = new Set(connectedPortNumbers);

    clonedScene.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;

      const metadata = object.userData?.extras || object.userData;
      const componentType = String(metadata?.component_type || '').toLowerCase();
      const objectName = String(object.name || '').toUpperCase();
      const isQsfpAssemblyPart = face === 'front'
        && /^PORT_QSFP_\d+(?:_|$)/.test(objectName)
        && componentType !== 'port_label';
      if (isQsfpAssemblyPart) {
        // Keep source labels/anchors, but replace the solid source cage, slot
        // lips and lane meshes with the readable front overlay below.
        object.visible = false;
      }
      const sourceMaterials = Array.isArray(object.material) ? object.material : [object.material];
      const isStatusLed = componentType === 'status_led'
        || /STATUS|POWER|SYSTEM|ALARM/.test(objectName)
        || sourceMaterials.some(material => /MAT_LED_(GREEN|BLUE|AMBER)/.test(String(material.name || '').toUpperCase()));
      const isPortLed = componentType === 'port_led'
        || (objectName.includes('LED') && !isStatusLed)
        || sourceMaterials.some(material => String(material.name || '').toUpperCase().includes('MAT_LED_PORT'));
      const rawPortIndex = Number(metadata?.port_index);
      const portIndex = Number.isFinite(rawPortIndex) ? rawPortIndex : undefined;
      const connectionFace = metadata?.connection_face === 'rear' ? 'rear' : metadata?.connection_face === 'front' ? 'front' : undefined;
      const statusChannel: AnimatedGlbLed['channel'] = /ALARM|FAULT/.test(objectName)
        ? 'alarm'
        : /POWER|PSU|AC[_ -]?OK/.test(objectName)
          ? 'power'
          : 'system';
      const lane: AnimatedGlbLed['lane'] = /(?:^|[_-])B(?:$|[_-])/.test(objectName)
        ? 'secondary'
        : 'primary';
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
          channel: materialIsPortLed ? 'port' : statusChannel,
          portIndex,
          connectionFace,
          lane,
          connected: materialIsPortLed
            && portIndex != null
            && connectedPorts.has(portIndex)
            && (!connectionFace || connectionFace === face),
          baseIntensity: material.emissive && typeof material.emissiveIntensity === 'number'
            ? Math.max(0.8, material.emissiveIntensity)
            : 1,
          baseOpacity: material.opacity,
          phase: ledIndex * 0.37
        });
        ledIndex += 1;
        return material;
      });

      object.material = Array.isArray(object.material) ? clonedMaterials : clonedMaterials[0];
    });

    return { scene: clonedScene, leds };
  }, [scene, face, connectedPortNumbers]);

  useFrame(({ clock }) => {
    const time = clock.getElapsedTime();
    sceneState.leds.forEach(led => {
      let color = '#1f2937';
      let emissive = '#000000';
      let intensity = 0;

      if (led.channel === 'port') {
        if (led.connected) {
          // A connected link is represented by a steady green link LED. The
          // secondary lens is kept dimmer because activity/speed telemetry is
          // not part of the rack read model and must not be fabricated.
          color = led.lane === 'secondary' ? '#236c57' : '#4dffad';
          emissive = led.lane === 'secondary' ? '#126447' : '#20d889';
          intensity = led.lane === 'secondary'
            ? 0.65 + Math.sin(time * 1.6 + led.phase) * 0.08
            : 2.8;
        }
      } else if (healthStatus !== 'offline') {
        if (led.channel === 'power') {
          color = '#4dffad';
          emissive = '#20d889';
          intensity = 2.25 + Math.sin(time * 1.7 + led.phase) * 0.12;
        } else if (led.channel === 'system') {
          if (healthStatus === 'critical') {
            color = '#ff5d66';
            emissive = '#ef4444';
            intensity = 3.8 + Math.sin(time * 8 + led.phase) * 1.1;
          } else if (healthStatus === 'warning') {
            // Collector/telemetry warnings do not extinguish the physical
            // system-ready lamp. Real switches keep SYS green and use the
            // dedicated ALM lens for the amber blink.
            color = '#4dffad';
            emissive = '#22c55e';
            intensity = 1.9 + Math.sin(time * 2.8 + led.phase) * 0.35;
          } else if (healthStatus === 'healthy') {
            color = '#4dffad';
            emissive = '#22c55e';
            // Normal switches keep a clearly visible green heartbeat instead
            // of a barely perceptible one-frame pulse at rack scale.
            intensity = 0.85 + (0.5 + 0.5 * Math.sin(time * 3.2 + led.phase)) * 2.9;
          } else {
            color = '#8aa4b8';
            emissive = '#416274';
            intensity = 0.4 + Math.sin(time * 1.4 + led.phase) * 0.08;
          }
        } else if (healthStatus === 'critical') {
          color = '#ff4f58';
          emissive = '#ef4444';
          intensity = Math.sin(time * 11 + led.phase) > 0 ? 4.8 : 0.08;
        } else if (healthStatus === 'warning') {
          color = '#ffc34d';
          emissive = '#f59e0b';
          intensity = Math.sin(time * 5.5 + led.phase) > 0 ? 4.2 : 0.06;
        }
      }

      if (led.material.color) led.material.color.set(color);
      if (led.material.emissive) led.material.emissive.set(emissive);
      if (typeof led.material.emissiveIntensity === 'number') {
        led.material.emissiveIntensity = intensity;
      } else if (led.material.color) {
        // BasicMaterial fallback for older GLB exports without emissive.
        led.material.color.set(color);
        led.material.opacity = led.baseOpacity * (intensity > 0 ? 0.95 : 0.45);
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

const S6800_QSFP_PORTS = [49, 50, 51, 52, 53, 54] as const;

function isS6800Identity(device: RackDeviceVM): boolean {
  const identity = `${device.assetKey || ''} ${device.vendor || ''} ${device.model || ''}`.toLowerCase();
  return identity.includes('s6800') || identity.includes('s6850');
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
  const showQsfpOverlay = useGlbAsset && face === 'front' && isS6800Identity(device);
  const showSfpModules = useGlbAsset && face === 'front' && isS6800Identity(device);

  // Derive which ports physically have active cable connections
  const connectedPortNumbers = React.useMemo(() => {
    const ports: number[] = [];
    const devName = device.name.toUpperCase();
    const deviceIdentity = `${device.assetKey || ''} ${device.vendor || ''} ${device.model || ''}`.toLowerCase();
    const isS6800 = deviceIdentity.includes('s6800') || deviceIdentity.includes('s6850');
    const normalizePortNumber = (interfaceName: string) => {
      const match = interfaceName.match(/(\d+)$/);
      if (!match) return null;
      const rawPort = parseInt(match[1], 10);
      const isHighSpeedPort = /(?:qsfp|fge|hge|40ge|100ge|40g|100g|fortygig|hundredgig)/i.test(interfaceName);
      const normalizedPort = isHighSpeedPort && rawPort <= 6 ? 49 + rawPort - 1 : rawPort;
      return isS6800 ? Math.max(1, Math.min(54, normalizedPort)) : rawPort;
    };
    (links || []).forEach(l => {
      const isLocal = l.local_device_id === device.id || (l.local_device_name && l.local_device_name.toUpperCase() === devName);
      const isRemote = l.remote_device_id === device.id || (l.remote_device_name && l.remote_device_name.toUpperCase() === devName);
      if (isLocal) {
        const portNumber = normalizePortNumber(l.local_interface || '');
        if (portNumber != null) ports.push(portNumber);
      }
      if (isRemote) {
        const portNumber = normalizePortNumber(l.remote_interface || '');
        if (portNumber != null) ports.push(portNumber);
      }
    });
    return Array.from(new Set(ports));
  }, [device.assetKey, device.id, device.model, device.name, device.vendor, links]);

  const connectedSfpModules = React.useMemo<Array<{ portNumber: number; media: SfpModuleMedia }>>(() => {
    if (!isS6800Identity(device)) return [];

    const modulePriority: Record<SfpModuleMedia, number> = {
      unknown: 0,
      copper: 1,
      dac: 2,
      fiber: 3,
    };
    const modules = new Map<number, SfpModuleMedia>();
    const normalizePortNumber = (interfaceName: string) => {
      const match = interfaceName.match(/(\d+)$/);
      if (!match) return null;
      const rawPort = parseInt(match[1], 10);
      const isCompactHighSpeed = /(?:qsfp|fge|hge|40ge|100ge|40g|100g|fortygig|hundredgig)/i.test(interfaceName);
      const normalizedPort = isCompactHighSpeed && rawPort <= 6 ? 49 + rawPort - 1 : rawPort;
      return Math.max(1, Math.min(54, normalizedPort));
    };
    const inferMedia = (link: TopologyLinkItem, interfaceName: string): SfpModuleMedia => {
      if (link.cable_type === 'fiber' || link.cable_type === 'dac' || link.cable_type === 'copper') {
        return link.cable_type;
      }
      if (/(sfp|xge|10ge|fge|hge|qsfp|40ge|100ge|forty|hundred)/i.test(interfaceName)) return 'fiber';
      if (/(dac)/i.test(interfaceName)) return 'dac';
      if (/(^|[^a-z])(ge|gigabit|ethernet)/i.test(interfaceName)) return 'copper';
      return 'unknown';
    };

    (links || []).forEach(link => {
      const endpoints: Array<{ interfaceName: string; belongsToDevice: boolean }> = [
        {
          interfaceName: link.local_interface || '',
          belongsToDevice: link.local_device_id === device.id
            || Boolean(link.local_device_name && link.local_device_name.toUpperCase() === device.name.toUpperCase()),
        },
        {
          interfaceName: link.remote_interface || '',
          belongsToDevice: link.remote_device_id === device.id
            || Boolean(link.remote_device_name && link.remote_device_name.toUpperCase() === device.name.toUpperCase()),
        },
      ];
      endpoints.forEach(({ interfaceName, belongsToDevice }) => {
        if (!belongsToDevice) return;
        const portNumber = normalizePortNumber(interfaceName);
        if (portNumber == null || portNumber > 48) return;
        const media = inferMedia(link, interfaceName);
        const previous = modules.get(portNumber);
        if (!previous || modulePriority[media] > modulePriority[previous]) modules.set(portNumber, media);
      });
    });

    return Array.from(modules.entries())
      .sort(([left], [right]) => left - right)
      .map(([portNumber, media]) => ({ portNumber, media }));
  }, [device.id, device.name, device.assetKey, device.model, device.vendor, links]);

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

    if (normRole === 'patch_panel' || normRole === 'patch panel' || normRole === '配线架') {
      return (
        <PatchPanelFaceplate
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
            <group>
              <RackGlbDevice
                url={device.assetUrl}
                height={coordinates.height}
                depth={coordinates.depth}
                face={face}
                healthStatus={healthStatus}
                connectedPortNumbers={connectedPortNumbers}
              />
              {showSfpModules && connectedSfpModules.map(({ portNumber, media }) => {
                const port = getPortPhysicalCoordinates(`GE1/0/${portNumber}`, true, true);
                return (
                  <SfpModuleAssembly
                    key={`sfp-module-${portNumber}`}
                    x={port.x}
                    yOffset={port.yOffset}
                    frontZ={coordinates.depth / 2}
                    media={media}
                  />
                );
              })}
              {showQsfpOverlay && S6800_QSFP_PORTS.map(portNumber => (
                <QsfpPortAssembly
                  key={portNumber}
                  portNumber={portNumber}
                  x={getPortPhysicalCoordinates(`XGE1/0/${portNumber}`, true, true).x}
                  frontZ={coordinates.depth / 2}
                  connected={connectedPortNumbers.includes(portNumber)}
                />
              ))}
            </group>
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
