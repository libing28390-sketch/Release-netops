import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import { RackVM, RackDeviceVM } from '../types';

export type CableMode = 'select' | 'all' | 'off';

export interface TopologyLinkItem {
  id: string;
  local_device_id: string;
  local_device_name?: string;
  local_interface: string;
  remote_device_id?: string;
  remote_device_name?: string;
  remote_interface: string;
  speed_mbps?: number;
  status: 'up' | 'down' | 'degraded' | 'stale' | 'unknown';
  cable_type?: 'fiber' | 'dac' | 'copper';
}

interface RackCableLayerProps {
  rackVM: RackVM;
  selectedDeviceId?: string | null;
  cableMode: CableMode;
  links?: TopologyLinkItem[];
}

/**
 * Animated Glowing Data Traffic Pulse along the cable curve
 */
const CableTrafficParticle: React.FC<{
  curve: THREE.CatmullRomCurve3;
  isFiber: boolean;
  speed?: number;
  offset?: number;
}> = ({ curve, isFiber, speed = 0.35, offset = 0 }) => {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const progress = ((clock.elapsedTime * speed) + offset) % 1.0;
    const position = curve.getPointAt(progress);
    meshRef.current.position.copy(position);
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[isFiber ? 0.03 : 0.038, 8, 8]} />
      <meshStandardMaterial
        color={isFiber ? '#38bdf8' : '#fbbf24'}
        emissive={isFiber ? '#38bdf8' : '#fbbf24'}
        emissiveIntensity={3.5}
        roughness={0.1}
      />
    </mesh>
  );
};

const RackCableTube: React.FC<{
  curve: THREE.CatmullRomCurve3;
  radius: number;
  color: string;
  emissiveColor: string;
  emissiveIntensity: number;
}> = ({ curve, radius, color, emissiveColor, emissiveIntensity }) => {
  const geometry = useMemo(
    () => new THREE.TubeGeometry(curve, 36, radius, 8, false),
    [curve, radius],
  );

  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color={color}
        roughness={0.3}
        metalness={0.5}
        emissive={emissiveColor}
        emissiveIntensity={emissiveIntensity}
      />
    </mesh>
  );
};

/**
 * Calculate precise 3D physical port X and Y coordinates on the switch faceplate
 * based on authentic 3-module enterprise panel layout.
 */
function getPortPhysicalCoordinates(interfaceName: string, is48Port = true): { x: number; yOffset: number } {
  const name = (interfaceName || '').toLowerCase().trim();

  // Management / Console Ports (Left Zone)
  if (name.includes('mgmt') || name.includes('m-eth')) {
    return { x: -1.15, yOffset: 0.04 };
  }
  if (name.includes('console')) {
    return { x: -1.02, yOffset: 0.04 };
  }
  if (name.includes('usb')) {
    return { x: -0.88, yOffset: -0.02 };
  }

  // 40G / 100G QSFP28 Uplink Ports (Right Zone)
  if (name.includes('100g') || name.includes('40g') || name.includes('qsfp')) {
    const match = name.match(/(\d+)$/);
    const qsfpIdx = match ? (parseInt(match[1], 10) - 1) : 0;
    const clampedIdx = Math.max(0, Math.min(5, qsfpIdx));
    const startUplinkX = is48Port ? 1.05 : 1.15;
    return { x: startUplinkX + clampedIdx * 0.12, yOffset: 0 };
  }

  // Business Ports (48 ports for S6850 or 24 ports for F1090)
  const match = name.match(/(\d+)$/);
  const portNum = match ? parseInt(match[1], 10) : 0;
  const isBottom = portNum % 2 === 1;
  const colIndex = Math.min(is48Port ? 23 : 11, Math.floor(portNum / 2));

  const startBusinessX = -0.72;
  const stepX = is48Port ? 0.065 : 0.105;
  const quadGap = Math.floor(colIndex / 4) * (is48Port ? 0.015 : 0.025);
  const x = startBusinessX + colIndex * stepX + quadGap;
  const yOffset = isBottom ? -0.04 : 0.04;

  return { x, yOffset };
}


export const RackCableLayer: React.FC<RackCableLayerProps> = ({
  rackVM,
  selectedDeviceId,
  cableMode = 'select',
  links = []
}) => {
  if (cableMode === 'off') return null;

  // Build device lookup map by ID and Name
  const deviceMap = useMemo(() => {
    const map = new Map<string, RackDeviceVM>();
    rackVM.devices.forEach(d => {
      map.set(d.id, d);
      if (d.networkDeviceId) map.set(d.networkDeviceId, d);
      map.set(d.name.toLowerCase(), d);
      map.set(d.name.replace(/[^a-zA-Z0-9]/g, '').toLowerCase(), d);
    });
    return map;
  }, [rackVM.devices]);

  // Compute cables
  const activeCables = useMemo(() => {
    return links
      .map(link => {
        const srcDev =
          deviceMap.get(link.local_device_id) ||
          deviceMap.get((link.local_device_name || '').toLowerCase()) ||
          deviceMap.get((link.local_device_name || '').replace(/[^a-zA-Z0-9]/g, '').toLowerCase());

        const dstName = (link.remote_device_name || '').toLowerCase();
        const dstDev =
          (link.remote_device_id ? deviceMap.get(link.remote_device_id) : null) ||
          deviceMap.get(dstName) ||
          deviceMap.get(dstName.replace(/[^a-zA-Z0-9]/g, ''));

        if (!srcDev) return null;

        // Check if attached to selected device
        const isConnectedToSelected =
          Boolean(selectedDeviceId) &&
          (srcDev.id === selectedDeviceId || (dstDev && dstDev.id === selectedDeviceId));

        if (cableMode === 'select' && !isConnectedToSelected) {
          return null;
        }

        const isHighlighted = isConnectedToSelected;

        // Handle pull-out offset
        const srcPullOffset = srcDev.id === selectedDeviceId ? 0.6 : 0;
        const dstPullOffset = dstDev && dstDev.id === selectedDeviceId ? 0.6 : 0;

        // Exact Physical Port Coordinate for Source
        const srcCoords = getPortPhysicalCoordinates(link.local_interface);
        const startX = srcCoords.x;
        const startY = srcDev.coordinates.centerY + srcCoords.yOffset;
        const startZ = srcDev.coordinates.centerZ + srcDev.coordinates.depth / 2 + 0.05 + srcPullOffset;

        // Exact Physical Port Coordinate for Destination
        const dstCoords = getPortPhysicalCoordinates(link.remote_interface);
        const endX = dstDev ? dstCoords.x : -1.8;
        const endY = dstDev ? (dstDev.coordinates.centerY + dstCoords.yOffset) : (rackVM.totalU * 0.4445);
        const endZ = dstDev
          ? dstDev.coordinates.centerZ + dstDev.coordinates.depth / 2 + 0.05 + dstPullOffset
          : startZ;

        // Standard Professional Vertical Cable Raceway (X = -2.25, outside rack faceplate)
        const trunkX = -2.25;
        const trunkZ = Math.max(startZ, endZ) + 0.12;

        // Cable egress drop underneath the chassis bezel (Y - 0.16) to avoid blocking nameplate
        const srcTrayY = srcDev.coordinates.centerY - 0.16;
        const dstTrayY = dstDev ? (dstDev.coordinates.centerY - 0.16) : endY;

        // Construct 8-point structured curve cleanly routed below faceplate into vertical raceway
        const curve = new THREE.CatmullRomCurve3([
          new THREE.Vector3(startX, startY, startZ),
          new THREE.Vector3(startX, startY, startZ + 0.15),
          new THREE.Vector3(startX, srcTrayY, startZ + 0.18),
          new THREE.Vector3(trunkX, srcTrayY, trunkZ),
          new THREE.Vector3(trunkX, dstTrayY, trunkZ),
          new THREE.Vector3(endX, dstTrayY, endZ + 0.18),
          new THREE.Vector3(endX, endY, endZ + 0.15),
          new THREE.Vector3(endX, endY, endZ)
        ], false, 'catmullrom', 0.12);

        const midPoint = curve.getPoint(0.5);

        return {
          link,
          curve,
          midPoint,
          isHighlighted,
          srcDev,
          dstDev
        };
      })
      .filter(Boolean) as Array<{
        link: TopologyLinkItem;
        curve: THREE.CatmullRomCurve3;
        midPoint: THREE.Vector3;
        isHighlighted: boolean;
        srcDev: RackDeviceVM;
        dstDev?: RackDeviceVM;
      }>;
  }, [links, deviceMap, selectedDeviceId, cableMode, rackVM.totalU]);

  // If in 'select' mode, highlight the primary connection
  const highlightedCables = activeCables.filter(c => c.isHighlighted);
  const primaryCable = highlightedCables[0] || null;

  return (
    <group>
      {activeCables.map((item, idx) => {
        const { link, curve, isHighlighted } = item;
        const isFiber = link.cable_type === 'fiber';
        const cableColor = link.status === 'down'
          ? '#ef4444'
          : link.status === 'degraded'
            ? '#f59e0b'
            : link.status === 'stale'
              ? '#64748b'
              : isFiber
                ? '#06b6d4'
                : isHighlighted ? '#38bdf8' : '#475569';
        const emissiveColor = isHighlighted ? (isFiber ? '#06b6d4' : '#0ea5e9') : '#000000';
        const emissiveIntensity = isHighlighted ? 1.4 : 0;
        // Slender professional cabling (Fiber 2.5mm, Cat6 5mm)
        const radius = isHighlighted ? (isFiber ? 0.013 : 0.017) : (isFiber ? 0.009 : 0.013);

        return (
          <group key={link.id || idx}>
            {/* Cable 3D Tube */}
            <RackCableTube
              curve={curve}
              radius={radius}
              color={cableColor}
              emissiveColor={emissiveColor}
              emissiveIntensity={emissiveIntensity}
            />

            {/* Dynamic Data Traffic Flow Particles */}
            {(isHighlighted || cableMode === 'all') && (
              <>
                <CableTrafficParticle
                  curve={curve}
                  isFiber={isFiber}
                  speed={isHighlighted ? 0.6 : 0.25}
                  offset={0}
                />
                {isHighlighted && (
                  <CableTrafficParticle
                    curve={curve}
                    isFiber={isFiber}
                    speed={0.6}
                    offset={0.5}
                  />
                )}
              </>
            )}
          </group>
        );
      })}

      {/* Floating 3D Badge Positioned to Left Side (X = -3.8, NEVER blocking rack center) */}
      {primaryCable && (
        <Html
          position={[-3.8, primaryCable.srcDev.coordinates.centerY, primaryCable.midPoint.z + 0.1]}
          center
          distanceFactor={16}
        >
          <div className="px-2.5 py-1.5 rounded-lg text-[10px] font-mono whitespace-nowrap shadow-2xl backdrop-blur-md bg-slate-950/95 border border-cyan-400 text-cyan-200 pointer-events-none animate-in fade-in zoom-in-95">
            <div className="font-bold text-white flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
              <span>
                {primaryCable.srcDev.name}:{primaryCable.link.local_interface} ⇄ {primaryCable.dstDev?.name || primaryCable.link.remote_device_name}:{primaryCable.link.remote_interface}
              </span>
            </div>
            <div className="text-[9px] text-amber-300 mt-0.5">
              {primaryCable.link.cable_type === 'fiber'
                ? '光纤链路'
                : primaryCable.link.cable_type === 'dac'
                  ? 'DAC 链路'
                  : primaryCable.link.cable_type === 'copper'
                    ? '铜缆链路'
                    : '物理链路'}
              {primaryCable.link.speed_mbps ? ` · ${primaryCable.link.speed_mbps} Mbps` : ''}
              {` · ${primaryCable.link.status.toUpperCase()}`}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
};
