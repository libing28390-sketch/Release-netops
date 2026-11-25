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
import { getRealisticFaceplateSilkscreenTexture } from './utils/textures';

interface RackGlbDeviceProps {
  url: string;
  width: number;
  height: number;
  depth: number;
  face: RackDeviceVM['face'];
  healthStatus: RackDeviceVM['healthStatus'];
  connectedPortNumbers: number[];
  hardwareSensors?: { psu_status?: string; fan_status?: string } | null;
}

type LedMaterial = THREE.Material & {
  emissive?: THREE.Color;
  emissiveIntensity?: number;
  color?: THREE.Color;
};

interface AnimatedGlbLed {
  material: LedMaterial;
  channel: 'power' | 'system' | 'fan' | 'alarm' | 'port';
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
  nativeHeightM: number;
}

const RackGlbDevice: React.FC<RackGlbDeviceProps> = ({
  url,
  width,
  height,
  depth,
  face,
  healthStatus,
  connectedPortNumbers,
  hardwareSensors,
}) => {
  const { scene } = useGLTF(url);
  const lastLedTickRef = useRef(0);
  const connectedPortsKey = connectedPortNumbers.join(',');
  const sceneState = React.useMemo<RackGlbSceneState>(() => {
    const clonedScene = scene.clone(true);
    const leds: AnimatedGlbLed[] = [];
    let ledIndex = 0;
    const connectedPorts = new Set(
      connectedPortsKey ? connectedPortsKey.split(',').map(Number).filter(Number.isFinite) : [],
    );

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
      const statusChannel: AnimatedGlbLed['channel'] = /ALARM|ALM|FAULT/.test(objectName)
        ? 'alarm'
        : /FAN/.test(objectName)
          ? 'fan'
          : /POWER|PWR|PSU|AC[_ -]?OK/.test(objectName)
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

    clonedScene.updateMatrixWorld(true);
    const nativeBox = new THREE.Box3().setFromObject(clonedScene);
    const nativeSize = new THREE.Vector3();
    nativeBox.getSize(nativeSize);
    const nativeHeightM = Number.isFinite(nativeSize.y) && nativeSize.y > 0.01 ? nativeSize.y : 0.04355;

    return { scene: clonedScene, leds, nativeHeightM };
  }, [scene, face, connectedPortsKey]);

  React.useEffect(() => () => {
    sceneState.leds.forEach(led => {
      try {
        led.material.dispose();
      } catch {
        // Ignore already-disposed material
      }
    });
  }, [sceneState]);

  useFrame(({ clock }) => {
    const time = clock.getElapsedTime();
    // Throttle LED updates to ~15Hz to keep frame budget lean across dense racks
    if (time - lastLedTickRef.current < 0.065) return;
    lastLedTickRef.current = time;
    sceneState.leds.forEach(led => {
      let color = '#1f2937';
      let emissive = '#000000';
      let intensity = 0;

      if (led.channel === 'port') {
        if (led.connected) {
          // Authentic pure hardware LED green (zero blue/cyan cast so it never
          // washes out to mint/white against the brushed-silver S6850 faceplate).
          const fastWave = Math.sin(time * 13.5 + led.phase * 3.1);
          const burstGate = Math.sin(time * 3.7 + led.phase * 1.9);
          const isPacketBurst = fastWave > -0.15 && burstGate > -0.35;
          if (led.lane === 'secondary') {
            color = isPacketBurst ? '#f59e0b' : '#3b2406';
            emissive = isPacketBurst ? '#d97706' : '#1f1203';
            intensity = isPacketBurst ? 1.35 : 0.15;
          } else {
            color = isPacketBurst ? '#00e632' : '#0a3a14';
            emissive = isPacketBurst ? '#00c428' : '#041f09';
            intensity = isPacketBurst ? 1.65 : 0.22;
          }
        }
      } else if (healthStatus !== 'offline') {
        if (led.channel === 'power') {
          if (hardwareSensors?.psu_status === 'fault') {
            color = '#ff2424';
            emissive = '#dc2626';
            intensity = Math.sin(time * 9 + led.phase) > 0 ? 1.85 : 0.1;
          } else {
            // Power / PSU LED: pure saturated hardware emerald green with gentle breathing
            const pulse = 0.5 + 0.5 * Math.sin(time * 2.4 + led.phase);
            color = '#00dc30';
            emissive = '#00b824';
            intensity = 1.25 + pulse * 0.45;
          }
        } else if (led.channel === 'fan') {
          // FAN LED (S6850): pure green when healthy, amber/red on sensor/device fault
          if (hardwareSensors?.fan_status === 'fault' || healthStatus === 'critical') {
            color = '#ff2424';
            emissive = '#dc2626';
            intensity = Math.sin(time * 10 + led.phase) > 0 ? 1.85 : 0.1;
          } else if (healthStatus === 'warning') {
            color = '#ff9900';
            emissive = '#ea580c';
            intensity = Math.sin(time * 5 + led.phase) > 0 ? 1.65 : 0.1;
          } else {
            color = '#00cf2c';
            emissive = '#00a820';
            intensity = 1.3;
          }
        } else if (led.channel === 'system') {
          if (healthStatus === 'critical') {
            color = '#ff2424';
            emissive = '#dc2626';
            intensity = Math.sin(time * 9 + led.phase) > 0 ? 1.85 : 0.12;
          } else if (healthStatus === 'warning') {
            color = '#00dc30';
            emissive = '#00b824';
            intensity = Math.sin(time * 4.5 + led.phase) > 0 ? 1.6 : 0.18;
          } else if (healthStatus === 'healthy') {
            // Standard H3C/enterprise switch SYS pure-green heartbeat (~1 Hz crisp blink)
            const heartbeatOn = Math.sin(time * 5.2 + led.phase) > -0.1;
            color = heartbeatOn ? '#00e632' : '#092e11';
            emissive = heartbeatOn ? '#00c428' : '#031807';
            intensity = heartbeatOn ? 1.7 : 0.12;
          } else {
            color = '#64748b';
            emissive = '#334155';
            intensity = 0.35 + Math.sin(time * 1.4 + led.phase) * 0.08;
          }
        } else if (healthStatus === 'critical') {
          // ALM LED: fast red blink on critical
          color = '#ff1e1e';
          emissive = '#dc2626';
          intensity = Math.sin(time * 11 + led.phase) > 0 ? 1.95 : 0.08;
        } else if (healthStatus === 'warning') {
          // ALM LED: amber blink on warning
          color = '#ff9800';
          emissive = '#ea580c';
          intensity = Math.sin(time * 5.5 + led.phase) > 0 ? 1.75 : 0.08;
        }
        // When healthy, ALM LED remains OFF (dark lens #1f2937, intensity 0)
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

  // RackVision v2 GLBs are native Y-up, centered at origin across 1U, 2U, 3U, 8U, 10U.
  // Scaling Y by the GLB's measured native height preserves exact proportions for box,
  // UPS (2U/3U), and modular chassis (8U/10U) hardware alike.
  const sx = 10 * Math.max(0.2, width / 4.786);
  const sy = Math.max(0.2, height / Math.max(0.02, sceneState.nativeHeightM));
  const sz = 10 * Math.max(0.2, depth / 8.4);

  return (
    <primitive
      object={sceneState.scene}
      position={[0, 0, 0]}
      rotation={[0, face === 'rear' ? Math.PI : 0, 0]}
      scale={[sx, sy, sz]}
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
  onDoubleClick?: (device: RackDeviceVM, hitPoint?: { x: number; y: number; z: number }) => void;
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
  const silkscreenTexture = React.useMemo(
    () => (useGlbAsset
      ? getRealisticFaceplateSilkscreenTexture(
          device.name,
          vendor,
          model,
          role,
          device.assetKey,
          device.heightU,
          device.physicalPortProfile,
        )
      : null),
    [useGlbAsset, device.name, vendor, model, role, device.assetKey, device.heightU, device.physicalPortProfile],
  );
  const selectionBorderGeo = React.useMemo(() => {
    const box = new THREE.BoxGeometry(coordinates.width + 0.08, coordinates.height + 0.04, 0.04);
    const edges = new THREE.EdgesGeometry(box);
    box.dispose();
    return edges;
  }, [coordinates.width, coordinates.height]);
  // RackVision v2 GLBs include native 3D QSFP28 & SFP+ cages with per-port LEDs;
  // disable the legacy procedural QSFP overlay that caused z-fighting/clipping.
  const showQsfpOverlay = false;
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
      const normalizedPort = isHighSpeedPort && rawPort <= 8 ? 49 + rawPort - 1 : rawPort;
      return isS6800 ? Math.max(1, Math.min(56, normalizedPort)) : rawPort;
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
    // Also illuminate every real physical port with oper_status === 'up' from synced CMDB+SNMP profile
    const profilePorts = device.physicalPortProfile?.ports || [];
    const minPort = device.physicalPortProfile?.slots?.[0]?.min_port ?? 1;
    const isFirewallZeroBased = /(firewall|f10\d\d|secpath|usg)/.test(deviceIdentity) && minPort === 0;
    profilePorts.forEach(p => {
      if (p.oper_status === 'up') {
        const mapped = isFirewallZeroBased ? p.port + 1 : p.port;
        ports.push(mapped);
      }
    });
    return Array.from(new Set(ports));
  }, [device.assetKey, device.id, device.model, device.name, device.vendor, device.physicalPortProfile, links]);

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
    const targetZ = isPulledOut ? 3.2 : 0;
    if (Math.abs(groupRef.current.position.z - targetZ) < 0.002) {
      groupRef.current.position.z = targetZ;
      return;
    }
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
      onDoubleClick(device, e.point ? { x: e.point.x, y: e.point.y, z: e.point.z } : undefined);
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
                width={coordinates.width}
                height={coordinates.height}
                depth={coordinates.depth}
                face={face}
                healthStatus={healthStatus}
                connectedPortNumbers={connectedPortNumbers}
                hardwareSensors={device.physicalPortProfile?.hardware_sensors}
              />
              {/* Mask unused 4th QSFP column (ports 55-56) on real 54-port H3C S6850 devices */}
              {face === 'front' && isS6800Identity(device) && (device.physicalPortProfile?.slots?.[0]?.max_port ?? 56) <= 54 && (
                <mesh position={[1.98, -0.02, coordinates.depth / 2 + 0.166]}>
                  <boxGeometry args={[0.34, 0.28, 0.022]} />
                  <meshStandardMaterial color="#cfd6df" roughness={0.32} metalness={0.72} />
                </mesh>
              )}
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
        {/* High-Resolution 2048x256 Brushed-Metal Silkscreen Overlay (port numbers + brand + model, transparent over 3D port cages) */}
        {useGlbAsset && silkscreenTexture && face === 'front' && (
          <mesh position={[0, 0, coordinates.depth / 2 + 0.145]}>
            <planeGeometry args={[Math.min(coordinates.width - 0.36, 4.40), coordinates.height - 0.015]} />
            <meshStandardMaterial
              map={silkscreenTexture}
              transparent
              roughness={0.34}
              metalness={0.55}
              depthWrite={false}
            />
          </mesh>
        )}
        {(isSelected || hovered) && (
          <lineSegments
            geometry={selectionBorderGeo}
            position={[0, 0, (face === 'rear' ? -1 : 1) * (coordinates.depth / 2 + 0.16)]}
          >
            <lineBasicMaterial
              color={isSelected ? '#22d3ee' : '#38bdf8'}
              transparent
              opacity={isSelected ? 0.95 : 0.55}
            />
          </lineSegments>
        )}
        {useGlbAsset && displayMode !== 'physical' && (() => {
          let tint = '#22c55e';
          if (displayMode === 'health') {
            tint = healthStatus === 'critical' ? '#ef4444'
              : healthStatus === 'warning' ? '#f59e0b'
              : healthStatus === 'offline' ? '#64748b'
              : healthStatus === 'unknown' ? '#94a3b8'
              : '#10b981';
          } else if (displayMode === 'role') {
            const r = (role || '').toLowerCase();
            tint = r.includes('firewall') ? '#f43f5e'
              : r.includes('wireless') || r === 'ac' ? '#22d3ee'
              : r.includes('core') || r.includes('spine') ? '#a855f7'
              : r.includes('server') || r.includes('storage') ? '#10b981'
              : '#3b82f6';
          } else if (displayMode === 'power') {
            const w = metrics.ratedPowerWatts || 0;
            tint = w >= 600 ? '#ef4444' : w >= 250 ? '#f59e0b' : w > 0 ? '#10b981' : '#64748b';
          }
          const faceDir = face === 'rear' ? -1 : 1;
          return (
            <group>
              <mesh position={[0, 0, 0]}>
                <boxGeometry args={[coordinates.width + 0.04, coordinates.height + 0.015, coordinates.depth + 0.18]} />
                <meshBasicMaterial color={tint} transparent opacity={0.22} depthWrite={false} />
              </mesh>
              <mesh position={[0, coordinates.height / 2 - 0.018, faceDir * (coordinates.depth / 2 + 0.158)]}>
                <boxGeometry args={[coordinates.width - 0.36, 0.026, 0.016]} />
                <meshBasicMaterial color={tint} toneMapped={false} />
              </mesh>
            </group>
          );
        })()}
      </group>
    </group>
  );
};
