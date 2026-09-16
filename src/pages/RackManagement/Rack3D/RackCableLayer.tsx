import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import { RackVM, RackDeviceVM } from '../types';
import { RACK_INNER_WIDTH } from '../adapters/rackViewModel';

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
  link_kind?: 'physical' | 'aggregation' | string;
  member_index?: number;
  member_count?: number;
  aggregation_name?: string;
  discovery_source?: string;
  aggregation_protocol?: string;
  /**
   * A visual-only fallback used when a rack has no topology rows yet. It is
   * deliberately marked so the UI can explain that these are not CMDB links.
   */
  is_preview?: boolean;
}

interface RackCableLayerProps {
  rackVM: RackVM;
  selectedDeviceId?: string | null;
  cableMode: CableMode;
  links?: TopologyLinkItem[];
  showPreviewWhenEmpty?: boolean;
}

/**
 * Animated Glowing Data Traffic Pulse along the cable curve
 */
const CableTrafficParticle: React.FC<{
  curve: THREE.Curve<THREE.Vector3>;
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
      <sphereGeometry args={[isFiber ? 0.014 : 0.017, 8, 8]} />
      <meshStandardMaterial
        color={isFiber ? '#4b88bc' : '#d1a021'}
        emissive={isFiber ? '#2e6499' : '#8f6814'}
        emissiveIntensity={1.6}
        roughness={0.1}
        toneMapped={false}
      />
    </mesh>
  );
};

const RackCableTube: React.FC<{
  curve: THREE.Curve<THREE.Vector3>;
  radius: number;
  color: string;
  emissiveColor: string;
  emissiveIntensity: number;
  opacity?: number;
}> = ({ curve, radius, color, emissiveColor, emissiveIntensity, opacity = 1 }) => {
  const geometry = useMemo(
    () => new THREE.TubeGeometry(curve, 36, radius, 8, false),
    [curve, radius],
  );

  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <mesh geometry={geometry} renderOrder={10}>
      <meshStandardMaterial
        color={color}
        roughness={0.3}
        metalness={0.5}
        emissive={emissiveColor}
        emissiveIntensity={emissiveIntensity}
        toneMapped={false}
        transparent={opacity < 1}
        opacity={opacity}
      />
    </mesh>
  );
};

/**
 * A slim horizontal cable-management finger below each populated device.
 * Real racks hide the first bend behind this lip; keeping it as a dark,
 * non-emissive piece also gives the coloured cords a clean contrast line.
 */
const RackCableManagerRail: React.FC<{
  width: number;
  y: number;
  z: number;
}> = ({ width, y, z }) => (
  <group position={[0, y, z]} renderOrder={4}>
    <mesh position={[0, 0, -0.012]} renderOrder={4}>
      <boxGeometry args={[width, 0.07, 0.07]} />
      <meshStandardMaterial color="#0a1118" roughness={0.48} metalness={0.72} />
    </mesh>
    <mesh position={[0, 0.037, 0.018]} renderOrder={5}>
      <boxGeometry args={[Math.max(0.2, width - 0.08), 0.012, 0.018]} />
      <meshStandardMaterial color="#3b4a56" roughness={0.36} metalness={0.78} />
    </mesh>
  </group>
);

interface RackCableSideRacewayProps {
  sideSign: -1 | 1;
  x: number;
  yMin: number;
  yMax: number;
  z: number;
}

/**
 * Narrow vertical raceway and mechanical tie points for the real cable
 * bundle.  The raceway sits behind the coloured tubes; the dark straps cross
 * the bundle at sparse intervals just like the hook-and-loop ties in the
 * reference cabinet photo.
 */
const RackCableSideRaceway: React.FC<RackCableSideRacewayProps> = ({
  sideSign,
  x,
  yMin,
  yMax,
  z,
}) => {
  const padding = 0.22;
  const span = Math.max(0.42, yMax - yMin + padding * 2);
  const centerY = (yMin + yMax) / 2;
  const tieCount = Math.max(2, Math.min(8, Math.ceil(span / 0.8)));
  const ties = Array.from({ length: tieCount }, (_, index) => {
    const ratio = tieCount === 1 ? 0.5 : index / (tieCount - 1);
    return centerY - (span / 2 - padding) + ratio * (span - padding * 2);
  });

  return (
    <group position={[0, 0, 0]} renderOrder={4}>
      <mesh position={[x, centerY, z - 0.08]} renderOrder={4}>
        <boxGeometry args={[0.13, span, 0.13]} />
        <meshStandardMaterial color="#0a1118" roughness={0.5} metalness={0.72} />
      </mesh>
      <mesh position={[x - sideSign * 0.054, centerY, z - 0.006]} renderOrder={5}>
        <boxGeometry args={[0.014, span - 0.06, 0.018]} />
        <meshStandardMaterial color="#344754" roughness={0.34} metalness={0.76} />
      </mesh>
      {ties.map((tieY, index) => (
        <group key={`raceway-tie-${sideSign}-${index}`} position={[x, tieY, z + 0.012]} renderOrder={7}>
          <mesh>
            <boxGeometry args={[0.34, 0.026, 0.15]} />
            <meshStandardMaterial color="#05090d" roughness={0.56} metalness={0.62} />
          </mesh>
          <mesh position={[sideSign * 0.08, 0, 0.01]}>
            <boxGeometry args={[0.018, 0.034, 0.016]} />
            <meshStandardMaterial color="#677985" roughness={0.32} metalness={0.82} />
          </mesh>
        </group>
      ))}
    </group>
  );
};

// The rack assets leave a small EIA-310 seam between adjacent 1U devices.
// Keeping the visible tray run inside that seam is what lets every device
// retain a readable cable path without painting a line over the next
// faceplate.  The value is intentionally below the 20 mm nominal gap so the
// tube radius still has a little breathing room at rack-wide zoom.
const CABLE_SEAM_INSET = 0.006;

const RackCablePlug: React.FC<{
  position: THREE.Vector3;
  color: string;
  isQsfp: boolean;
  isFiber: boolean;
  opacity?: number;
}> = ({ position, color, isQsfp, isFiber, opacity = 1 }) => {
  const width = isQsfp ? 0.118 : 0.072;
  const height = isQsfp ? 0.078 : 0.048;
  return (
    <group position={position} renderOrder={12}>
      {/* Short plug/boot sits partly inside the cage and partly outside the
          faceplate, making the cable-to-module connection unambiguous. */}
      <mesh position={[0, 0, -0.014]}>
        <boxGeometry args={[width, height, isQsfp ? 0.042 : 0.032]} />
        <meshStandardMaterial
          color="#17212a"
          roughness={0.34}
          metalness={0.64}
          transparent={opacity < 1}
          opacity={opacity}
        />
      </mesh>
      {(!isFiber || isQsfp) && (
        <mesh position={[0, 0, 0.008]}>
          <boxGeometry args={[width * 0.52, isQsfp ? 0.010 : 0.007, 0.006]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.18}
            roughness={0.22}
            metalness={0.48}
            toneMapped={false}
            transparent={opacity < 1}
            opacity={opacity}
          />
        </mesh>
      )}
      {isFiber && !isQsfp ? (
        [-0.011, 0.011].map(fiberOffset => (
          <mesh key={fiberOffset} position={[fiberOffset, 0.002, 0.038]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.004, 0.005, 0.060, 8]} />
            <meshStandardMaterial
              color={color}
              emissive={color}
              emissiveIntensity={0.58}
              roughness={0.24}
              metalness={0.28}
              toneMapped={false}
              transparent={opacity < 1}
              opacity={opacity}
            />
          </mesh>
        ))
      ) : (
        <mesh position={[0, 0, 0.036]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[isQsfp ? 0.015 : 0.010, isQsfp ? 0.018 : 0.013, 0.054, 8]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.55}
            roughness={0.26}
            metalness={0.35}
            toneMapped={false}
            transparent={opacity < 1}
            opacity={opacity}
          />
        </mesh>
      )}
    </group>
  );
};

function compactInterfaceLabel(value: string): string {
  return String(value || '')
    .replace(/^Ten-GigabitEthernet/i, 'XGE')
    .replace(/^FortyGigE/i, 'FGE')
    .replace(/^HundredGigE/i, 'HGE')
    .replace(/^GigabitEthernet/i, 'GE')
    .replace(/^FastEthernet/i, 'FE')
    .slice(0, 18);
}

function getS6800PortNumber(interfaceName: string): number {
  const name = String(interfaceName || '').toLowerCase().trim();
  const trailingNumber = name.match(/(\d+)$/);
  const rawPort = trailingNumber ? parseInt(trailingNumber[1], 10) : 1;
  const isCompactHighSpeed = /(?:qsfp|fge|hge|40ge|100ge|40g|100g|fortygig|hundredgig)/i.test(name);
  const normalizedPort = isCompactHighSpeed && rawPort <= 6 ? 49 + rawPort - 1 : rawPort;
  return Math.max(1, Math.min(54, normalizedPort));
}

function isS6800QsfpInterface(interfaceName: string, isS6800: boolean): boolean {
  if (!isS6800) return /(?:qsfp|40g|100g|fge|hge|forty|hundred)/i.test(interfaceName);
  return getS6800PortNumber(interfaceName) >= 49;
}

export function getPortConnectorOffset(interfaceName: string, isS6800: boolean): number {
  if (isS6800QsfpInterface(interfaceName, isS6800)) return 0.24;
  const name = String(interfaceName || '').toLowerCase();
  if (isS6800 && getS6800PortNumber(interfaceName) <= 48) return 0.218;
  if (/(?:sfp|10ge|25ge|xge)/i.test(name)) return 0.218;
  return 0.105;
}

interface CableLaneOffset {
  source: number;
  target: number;
}

/**
 * Give each endpoint a small deterministic lane. The offset is only applied
 * after the physical port lead, so the line still lands on the exact port but
 * the bundle fans out cleanly before entering the vertical raceway.
 */
function buildCableLaneOffsets(links: TopologyLinkItem[]): Map<string, CableLaneOffset> {
  const endpointGroups = new Map<string, Array<{ id: string; interfaceName: string; memberIndex?: number }>>();
  links.forEach(link => {
    const sourceKey = `source:${link.local_device_id || link.local_device_name || ''}`;
    const targetKey = `target:${link.remote_device_id || link.remote_device_name || ''}`;
    endpointGroups.set(sourceKey, [
      ...(endpointGroups.get(sourceKey) || []),
      { id: link.id, interfaceName: link.local_interface, memberIndex: link.member_index },
    ]);
    if (link.remote_device_id || link.remote_device_name) {
      endpointGroups.set(targetKey, [
        ...(endpointGroups.get(targetKey) || []),
        { id: link.id, interfaceName: link.remote_interface, memberIndex: link.member_index },
      ]);
    }
  });

  const offsets = new Map<string, CableLaneOffset>();
  // Assign each side explicitly so source and target bundles can be fanned out
  // independently even when a link connects two devices with different port
  // densities.
  endpointGroups.forEach((items, groupKey) => {
    const side = groupKey.startsWith('source:') ? 'source' : 'target';
    const sorted = [...items].sort((left, right) => {
      const memberOrder = (left.memberIndex ?? Number.MAX_SAFE_INTEGER) - (right.memberIndex ?? Number.MAX_SAFE_INTEGER);
      return memberOrder || left.interfaceName.localeCompare(right.interfaceName);
    });
    const spacing = Math.min(0.06, 0.42 / Math.max(1, sorted.length - 1));
    sorted.forEach((item, index) => {
      const current = offsets.get(item.id) || { source: 0, target: 0 };
      current[side] = (index - (sorted.length - 1) / 2) * spacing;
      offsets.set(item.id, current);
    });
  });
  return offsets;
}

/**
 * Calculate precise 3D physical port X and Y coordinates on the switch faceplate
 * based on authentic 3-module enterprise panel layout.
 */
export function getPortPhysicalCoordinates(
  interfaceName: string,
  is48Port = true,
  isS6800 = false,
  deviceRole?: string,
  deviceWidth?: number,
): { x: number; yOffset: number } {
  const name = (interfaceName || '').toLowerCase().trim();
  const trailingNumber = name.match(/(\d+)$/);

  // Passive CAT6 patch panels use a full-width 12x2 keystone field.  Keep
  // their endpoint mapping separate from a switch's compact business-port
  // bank so a future patch-panel link lands on the matching socket instead of
  // collapsing into the middle of the panel.
  const normalizedRole = String(deviceRole || '').toLowerCase();
  if (normalizedRole.includes('patch_panel') || normalizedRole.includes('patch panel') || normalizedRole.includes('配线')) {
    const rawPort = trailingNumber ? parseInt(trailingNumber[1], 10) : 1;
    const portNumber = Math.max(1, Math.min(24, rawPort));
    const columns = 12;
    const safeDeviceWidth = Math.max(0.1, Number(deviceWidth) || RACK_INNER_WIDTH - 0.04);
    const portWidth = Math.min(0.205, (safeDeviceWidth - 0.7) / (columns + 1));
    const portGap = (safeDeviceWidth - 0.66 - portWidth * columns) / (columns - 1);
    const portStartX = -(safeDeviceWidth - 0.66) / 2;
    const column = (portNumber - 1) % columns;
    const row = portNumber <= columns ? 0 : 1;
    return {
      x: portStartX + column * (portWidth + portGap),
      yOffset: row === 0 ? 0.068 : -0.068,
    };
  }

  // The supplied S6800 front reference has three 16-port SFP+ banks followed
  // by two 3-port QSFP28 banks. Keep cable endpoints on those real bank
  // positions instead of using the older generic 48-port approximation.
  if (isS6800) {
    const isHighSpeedPort = /(?:qsfp|fge|hge|40ge|100ge|40g|100g|fortygig|hundredgig)/i.test(name);
    const rawPort = trailingNumber ? parseInt(trailingNumber[1], 10) : 1;
    // S6800-family inventories use both QSFP1..6 and native names such as
    // XGE1/0/49 / FortyGigE1/0/53. Preserve an explicit 49–54 suffix; only
    // compact QSFP1..6 notation needs the 49-based expansion.
    const normalizedPort = isHighSpeedPort && rawPort <= 6 ? 49 + rawPort - 1 : rawPort;
    const portNumber = Math.max(1, Math.min(54, normalizedPort));
    const bankWidths = [0.7524, 0.7524, 0.7524, 0.5814, 0.5814];
    const bankGap = 0.06;
    let bankIndex = 0;
    let offset = 0;
    if (portNumber <= 48) {
      bankIndex = Math.floor((portNumber - 1) / 16);
      offset = (portNumber - 1) % 16;
    } else {
      bankIndex = portNumber <= 51 ? 3 : 4;
      offset = (portNumber - (bankIndex === 3 ? 49 : 52));
    }
    const bankLeft = -1.60 + bankWidths.slice(0, bankIndex).reduce((sum, width) => sum + width + bankGap, 0);
    const bankWidth = bankWidths[bankIndex];
    const columns: number = bankIndex < 3 ? 8 : 3;
    const column = columns === 1 ? 0 : offset % columns;
    const x = bankLeft + (columns === 1 ? bankWidth / 2 : column * (bankWidth / (columns - 1)));
    // The GLB lays out each SFP bank bottom row first (ports 01–08), then
    // top row (09–16). Keep the endpoint on that physical row instead of
    // mirroring the two rows vertically.
    return { x, yOffset: bankIndex < 3 ? (offset < columns ? -0.067 : 0.067) : 0 };
  }

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

function isS6800Device(device: RackDeviceVM): boolean {
  const identity = `${device.assetKey || ''} ${device.vendor || ''} ${device.model || ''}`.toLowerCase();
  return identity.includes('s6800') || identity.includes('s6850');
}

export const RackCableLayer: React.FC<RackCableLayerProps> = ({
  rackVM,
  selectedDeviceId,
  cableMode = 'select',
  links = [],
  showPreviewWhenEmpty = false,
}) => {
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

  const previewLinks = useMemo<TopologyLinkItem[]>(() => {
    if (!showPreviewWhenEmpty || links.length > 0) return [];
    const devices = rackVM.validDevices
      .filter(device => device.face === 'front')
      .sort((left, right) => left.startU - right.startU || left.name.localeCompare(right.name));
    if (devices.length === 0) return [];
    if (devices.length === 1) {
      const device = devices[0];
      return [{
        id: `preview-cable-${device.id}-uplink`,
        local_device_id: device.id,
        local_device_name: device.name,
        local_interface: 'SFP+1',
        remote_device_name: 'UPLINK PREVIEW',
        remote_interface: 'SFP+1',
        status: 'unknown',
        cable_type: 'fiber',
        is_preview: true,
      }];
    }
    return devices.slice(0, Math.min(6, devices.length)).slice(0, -1).map((device, index) => {
      const remote = devices[index + 1];
      return {
        id: `preview-cable-${device.id}-${remote.id}`,
        local_device_id: device.id,
        local_device_name: device.name,
        local_interface: `SFP+${index + 1}`,
        remote_device_id: remote.id,
        remote_device_name: remote.name,
        remote_interface: `SFP+${index + 2}`,
        status: 'unknown',
        cable_type: index % 2 === 0 ? 'fiber' : 'copper',
        is_preview: true,
      };
    });
  }, [links.length, rackVM.validDevices, showPreviewWhenEmpty]);

  const effectiveLinks = links.length > 0 ? links : previewLinks;
  const laneOffsets = useMemo(() => buildCableLaneOffsets(effectiveLinks), [effectiveLinks]);
  const [hoveredCableId, setHoveredCableId] = useState<string | null>(null);

  // Compute cables
  const activeCables = useMemo(() => {
    return effectiveLinks
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

        if (cableMode === 'select' && !isConnectedToSelected && !link.is_preview) {
          return null;
        }

        const isHighlighted = isConnectedToSelected;
        const lane = laneOffsets.get(link.id) || { source: 0, target: 0 };

        // Handle pull-out offset
        const srcPullOffset = srcDev.id === selectedDeviceId ? 0.6 : 0;
        const dstPullOffset = dstDev && dstDev.id === selectedDeviceId ? 0.6 : 0;

        // Exact Physical Port Coordinate for Source
        const srcIsS6800 = isS6800Device(srcDev);
        const srcIsQsfp = isS6800QsfpInterface(link.local_interface, srcIsS6800);
        const srcCoords = getPortPhysicalCoordinates(
          link.local_interface,
          true,
          srcIsS6800,
          srcDev.role,
          srcDev.coordinates.width,
        );
        const startX = srcCoords.x;
        const startY = srcDev.coordinates.centerY + srcCoords.yOffset;
        const startZ = srcDev.coordinates.centerZ
          + srcDev.coordinates.depth / 2
          + getPortConnectorOffset(link.local_interface, srcIsS6800)
          + srcPullOffset;

        // Exact Physical Port Coordinate for Destination
        const dstIsS6800 = Boolean(dstDev && isS6800Device(dstDev));
        const dstIsQsfp = isS6800QsfpInterface(link.remote_interface, dstIsS6800);
        const dstCoords = getPortPhysicalCoordinates(
          link.remote_interface,
          true,
          dstIsS6800,
          dstDev?.role,
          dstDev?.coordinates.width,
        );
        const endX = dstDev ? dstCoords.x : -1.8;
        const endY = dstDev ? (dstDev.coordinates.centerY + dstCoords.yOffset) : (rackVM.totalU * 0.4445);
        const endZ = dstDev
          ? dstDev.coordinates.centerZ
            + dstDev.coordinates.depth / 2
            + getPortConnectorOffset(link.remote_interface, dstIsS6800)
            + dstPullOffset
          : startZ;

        // Standard professional vertical cable raceway.  Choose the side
        // nearest the physical receptacles so QSFPs leave on the right and
        // SFP/RJ45 banks leave on the left.  Both ends of the current rack
        // links use matching sides; if a future cross-side link appears we
        // still keep the source side as its deterministic visual lane.
        const routeSideSign = dstDev
          ? (startX >= 0 && endX >= 0 ? 1 : -1)
          : (startX >= 0 ? 1 : -1);
        // Keep the raceway just inside the front mounting rails (the 19-inch
        // opening is about ±2.41 in the default rack).  A compact base plus a
        // restrained lane spread gives the bundle a visible home without
        // pushing the lines outside the cabinet shell.
        const routeLaneX = routeSideSign * (2.35 + lane.source * 0.68 + lane.target * 0.24);
        // Keep the endpoint drop behind the front plane, but expose the
        // shared bundle in a dedicated side cable lane. This is important for
        // links between non-adjacent devices: hiding the whole route behind
        // the chassis made the other devices' cables appear to be missing.
        const srcFaceZ = srcDev.coordinates.centerZ + srcDev.coordinates.depth / 2 + srcPullOffset;
        const dstFaceZ = dstDev
          ? dstDev.coordinates.centerZ + dstDev.coordinates.depth / 2 + dstPullOffset
          : srcFaceZ;
        const hiddenRouteZ = Math.min(srcFaceZ, dstFaceZ) - 0.18;
        // The production S6800 GLB has a shallow bezel lip in front of the
        // nominal `depth / 2` plane (roughly the same depth as its SFP/QSFP
        // connector).  A tray placed at `faceZ + 0.06` therefore ends up
        // behind the bezel and disappears except below the bottom device.
        // Lift only the shared tray/trunk above the real connector face; the
        // port lead itself still uses the exact receptacle depth below.
        const srcConnectorDepth = getPortConnectorOffset(link.local_interface, srcIsS6800);
        const dstConnectorDepth = dstDev
          ? getPortConnectorOffset(link.remote_interface, dstIsS6800)
          : srcConnectorDepth;
        const visibleTrunkZ = Math.max(srcFaceZ, dstFaceZ)
          + Math.max(0.035, srcConnectorDepth, dstConnectorDepth)
          // Stay visibly in front of the GLB bezel/latch geometry.  The
          // resulting run is still in the lower seam, so it cannot cover a
          // port, but it remains readable for every device in a rack-wide
          // front view instead of only for the bottom-most device.
          + 0.12;

        // Every front device sits on the same 0.4445 m U pitch.  Put the
        // visible horizontal run on the *lower seam* of the endpoint itself;
        // this is the only shared boundary that remains clear when switches
        // are stacked with no spare U.  Do not add the full lane offset to Y:
        // a ±0.09 m fan-out would move a line into the neighbouring face.
        const trayLane = (offset: number) => THREE.MathUtils.clamp(offset * 0.03, -0.006, 0.006);
        const getSeamY = (device: RackDeviceVM, offset: number) =>
          device.coordinates.centerY
          - device.coordinates.height / 2
          - CABLE_SEAM_INSET
          + trayLane(offset);
        const srcTrayY = getSeamY(srcDev, lane.source);
        const dstTrayY = dstDev ? getSeamY(dstDev, lane.target) : endY;

        // Construct the physical lead as an 8-point rear-depth curve.  The
        // public tray is rendered as three explicit straight runs below; this
        // split is deliberate because a smoothed spline can bow through a
        // neighbouring chassis even when its control points sit in a seam.
        const curve = new THREE.CatmullRomCurve3([
          new THREE.Vector3(startX, startY, startZ),
          new THREE.Vector3(startX, startY, startZ + 0.07),
          // Once the plug clears the receptacle, move behind the device
          // before dropping. This keeps the vertical transition from
          // painting a neighbouring port row in front-view close-ups.
          new THREE.Vector3(startX, srcTrayY, hiddenRouteZ),
          new THREE.Vector3(routeLaneX, srcTrayY, hiddenRouteZ),
          new THREE.Vector3(routeLaneX, dstTrayY, hiddenRouteZ),
          new THREE.Vector3(endX, dstTrayY, hiddenRouteZ),
          new THREE.Vector3(endX, endY, endZ + 0.07),
          new THREE.Vector3(endX, endY, endZ)
        ], false, 'centripetal', 0.08);

        // Keep the shared tray completely deterministic and planar.  These
        // segments are the only intentionally front-facing cable geometry:
        // source seam -> side raceway -> destination seam.  Since both seams
        // are below their own faceplates, a line can never cover a port row.
        const makeTrayCurve = (fromX: number, toX: number, y: number) => {
          const direction = Math.sign(toX - fromX) || 1;
          const runLength = Math.abs(toX - fromX);
          const slack = Math.min(0.12, Math.max(0.025, runLength * 0.12));
          return new THREE.CatmullRomCurve3([
            new THREE.Vector3(fromX, y, visibleTrunkZ),
            new THREE.Vector3(fromX + direction * slack, y - 0.014, visibleTrunkZ),
            new THREE.Vector3(toX - direction * slack, y - 0.014, visibleTrunkZ),
            new THREE.Vector3(toX, y, visibleTrunkZ),
          ], false, 'centripetal', 0.18);
        };
        const sourceTrayCurve = makeTrayCurve(startX, routeLaneX, srcTrayY);
        const trunkCurve = new THREE.LineCurve3(
          new THREE.Vector3(routeLaneX, srcTrayY, visibleTrunkZ),
          new THREE.Vector3(routeLaneX, dstTrayY, visibleTrunkZ),
        );
        const trayCurves: THREE.Curve<THREE.Vector3>[] = [sourceTrayCurve, trunkCurve];
        if (dstDev) {
          trayCurves.push(makeTrayCurve(routeLaneX, endX, dstTrayY));
        }

        const midPoint = curve.getPoint(0.5);

        return {
          link,
          curve,
          trayCurves,
          trafficCurve: trunkCurve,
          midPoint,
          isHighlighted,
          srcDev,
          dstDev,
          srcIsQsfp,
          dstIsQsfp,
          routeSideSign: routeSideSign as -1 | 1,
          routeLaneX,
          srcTrayY,
          dstTrayY,
          visibleTrunkZ,
        };
      })
      .filter(Boolean) as Array<{
        link: TopologyLinkItem;
        curve: THREE.CatmullRomCurve3;
        trayCurves: THREE.Curve<THREE.Vector3>[];
        trafficCurve: THREE.Curve<THREE.Vector3>;
        midPoint: THREE.Vector3;
        isHighlighted: boolean;
        srcDev: RackDeviceVM;
        dstDev?: RackDeviceVM;
        srcIsQsfp: boolean;
        dstIsQsfp: boolean;
        routeSideSign: -1 | 1;
        routeLaneX: number;
        srcTrayY: number;
        dstTrayY: number;
        visibleTrunkZ: number;
      }>;
  }, [effectiveLinks, laneOffsets, deviceMap, selectedDeviceId, cableMode, rackVM.totalU]);

  // If in 'select' mode, highlight the primary connection
  const highlightedCables = activeCables.filter(c => c.isHighlighted);
  const primaryCable = highlightedCables.find(c => c.link.link_kind === 'aggregation') || highlightedCables[0] || null;
  const hoveredCable = hoveredCableId ? activeCables.find(item => item.link.id === hoveredCableId) || null : null;
  const displayCable = hoveredCable || primaryCable;
  const cableManagerDevices = useMemo(() => {
    const linkedDeviceIds = new Set<string>();
    activeCables.forEach(item => {
      linkedDeviceIds.add(item.srcDev.id);
      if (item.dstDev) linkedDeviceIds.add(item.dstDev.id);
    });
    return rackVM.validDevices.filter(device =>
      device.face === 'front' && linkedDeviceIds.has(device.id),
    );
  }, [activeCables, rackVM.validDevices]);
  const cableSideRaceways = useMemo(() => {
    const bundles = new Map<number, {
      x: number;
      yMin: number;
      yMax: number;
      z: number;
      count: number;
    }>();
    activeCables.forEach(item => {
      const side = item.routeSideSign;
      const previous = bundles.get(side);
      const yMin = Math.min(item.srcTrayY, item.dstTrayY);
      const yMax = Math.max(item.srcTrayY, item.dstTrayY);
      if (!previous) {
        bundles.set(side, {
          x: item.routeLaneX,
          yMin,
          yMax,
          z: item.visibleTrunkZ,
          count: 1,
        });
        return;
      }
      const nextCount = previous.count + 1;
      previous.x = (previous.x * previous.count + item.routeLaneX) / nextCount;
      previous.yMin = Math.min(previous.yMin, yMin);
      previous.yMax = Math.max(previous.yMax, yMax);
      previous.z = Math.max(previous.z, item.visibleTrunkZ);
      previous.count = nextCount;
    });
    return Array.from(bundles.entries()).map(([side, bundle]) => ({
      sideSign: side as -1 | 1,
      ...bundle,
    }));
  }, [activeCables]);

  useEffect(() => {
    if (hoveredCableId && !activeCables.some(item => item.link.id === hoveredCableId)) {
      setHoveredCableId(null);
    }
  }, [activeCables, hoveredCableId]);

  // Keep all hooks above unconditional; hide the rendered layer only after
  // React has completed hook evaluation for both cable modes.
  if (cableMode === 'off') return null;

  return (
    <group>
      {cableSideRaceways.map(bundle => (
        <RackCableSideRaceway
          key={`cable-raceway-${bundle.sideSign}`}
          sideSign={bundle.sideSign}
          x={bundle.x}
          yMin={bundle.yMin}
          yMax={bundle.yMax}
          z={bundle.z}
        />
      ))}
      {cableManagerDevices.map(device => {
        const faceZ = device.coordinates.centerZ + device.coordinates.depth / 2;
        const seamY = device.coordinates.centerY - device.coordinates.height / 2 - CABLE_SEAM_INSET;
        return (
          <RackCableManagerRail
            key={`cable-manager-${device.id}`}
            width={Math.max(0.2, device.coordinates.width - 0.08)}
            y={seamY}
            // The production GLB has a shallow bezel in front of the nominal
            // face plane.  Keep the tray fascia just behind the cable run but
            // in front of that bezel so it reads as a physical manager bar at
            // rack-wide zoom instead of disappearing into the chassis.
            z={faceZ + 0.28}
          />
        );
      })}
      {activeCables.map((item, idx) => {
        const { link, curve, trayCurves, trafficCurve, isHighlighted, srcIsQsfp, dstIsQsfp } = item;
        const isDimmed = Boolean(hoveredCableId && hoveredCableId !== link.id);
        const isAggregationMember = link.link_kind === 'aggregation' && (link.member_count || 0) > 1;
        const isSecondaryAggregationMember = isAggregationMember && (link.member_index || 0) > 0;
        const isFiber = link.cable_type === 'fiber';
        const cableColor = link.is_preview
          ? (isFiber ? '#2e72b8' : '#a87918')
          : link.status === 'down'
          ? '#c43b45'
          : link.status === 'degraded'
            ? '#c88924'
            : link.status === 'stale'
              ? '#64748b'
              : link.status === 'up'
                ? (isFiber ? '#2f78c4' : '#d1a021')
                : (isFiber ? '#4b88bc' : '#b98b22');
        const emissiveColor = link.status === 'down'
          ? '#8f2732'
          : isFiber ? '#1f4f8c' : '#8f6814';
        const emissiveIntensity = link.is_preview
          ? 0.18
          : isHighlighted
            ? 0.78
            : link.status === 'up'
              ? 0.38
              : link.status === 'unknown'
                ? 0.24
                : 0.16;
        const visibleEmissiveIntensity = isDimmed
          ? emissiveIntensity * 0.22
          : isSecondaryAggregationMember
            ? emissiveIntensity * 0.72
            : emissiveIntensity;
        // Keep the physical cable slender, but large enough to remain legible
        // at the rack-wide camera distance.
        const radius = isAggregationMember
          ? (isHighlighted ? (isFiber ? 0.012 : 0.016) : (isFiber ? 0.009 : 0.013))
          : isHighlighted
            ? (isFiber ? 0.016 : 0.023)
            : (isFiber ? 0.011 : 0.017);
        const trayRadius = Math.max(radius * 0.68, isFiber ? 0.006 : 0.008);
        const showTraffic = !link.is_preview && (isHighlighted || link.status === 'up');

        return (
          <group
            key={link.id || idx}
            onPointerOver={event => {
              event.stopPropagation();
              setHoveredCableId(link.id);
            }}
            onPointerOut={event => {
              event.stopPropagation();
              setHoveredCableId(current => current === link.id ? null : current);
            }}
          >
            {/* Cable 3D Tube */}
            <RackCableTube
              curve={curve}
              radius={radius}
              color={cableColor}
              emissiveColor={emissiveColor}
              emissiveIntensity={visibleEmissiveIntensity}
              opacity={isDimmed ? 0.22 : 1}
            />

            {/* Front-facing tray runs are separate from the rear-depth lead so
                spline interpolation cannot drift through a port face. */}
            {trayCurves.map((trayCurve, trayIndex) => (
              <RackCableTube
                key={`tray-${link.id}-${trayIndex}`}
                curve={trayCurve}
                radius={trayRadius}
                color={cableColor}
                emissiveColor={emissiveColor}
                emissiveIntensity={visibleEmissiveIntensity}
                opacity={isDimmed ? 0.22 : 1}
              />
            ))}

            {/* A short physical boot at each verified endpoint makes the
                fiber/patch lead visibly enter the SFP or QSFP receptacle. */}
            <RackCablePlug
              position={curve.getPoint(0)}
              color={cableColor}
              isQsfp={srcIsQsfp}
              isFiber={isFiber}
              opacity={isDimmed ? 0.22 : 1}
            />
            {item.dstDev && (
              <RackCablePlug
                position={curve.getPoint(1)}
                color={cableColor}
                isQsfp={dstIsQsfp}
                isFiber={isFiber}
                opacity={isDimmed ? 0.22 : 1}
              />
            )}

            {/* Dynamic Data Traffic Flow Particles */}
            {showTraffic && (isHighlighted || cableMode === 'all') && (
              <>
                <CableTrafficParticle
                  curve={trafficCurve}
                  isFiber={isFiber}
                  speed={isHighlighted ? 0.6 : 0.25}
                  offset={0}
                />
                {isHighlighted && (
                  <CableTrafficParticle
                    curve={trafficCurve}
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

      {/* Floating 3D Badge Positioned just outside the left rail. Keep the
          distance scale restrained so a device close-up does not turn this
          small annotation into a giant billboard. */}
      {displayCable && (
        <Html
          position={[-2.45, displayCable.srcDev.coordinates.centerY, displayCable.midPoint.z + 0.1]}
          style={{ transform: 'translateY(-50%)' }}
          distanceFactor={5}
        >
          <div className="px-2.5 py-1.5 rounded-lg text-[10px] font-mono whitespace-nowrap shadow-2xl backdrop-blur-md bg-slate-950/95 border border-cyan-400 text-cyan-200 pointer-events-none animate-in fade-in zoom-in-95">
            <div className="font-bold text-white flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${displayCable.link.is_preview ? 'bg-amber-400 shadow-[0_0_6px_#fbbf24]' : 'bg-emerald-400 shadow-[0_0_6px_#34d399]'}`} />
              <span>
                {displayCable.link.is_preview ? '示例布线 · ' : ''}
                {displayCable.srcDev.name}:{compactInterfaceLabel(displayCable.link.local_interface)} ⇄ {displayCable.dstDev?.name || displayCable.link.remote_device_name}:{compactInterfaceLabel(displayCable.link.remote_interface)}
              </span>
            </div>
            <div className="text-[9px] text-amber-300 mt-0.5">
              {displayCable.link.is_preview
                ? '仅视觉预览，不写入 CMDB'
                : displayCable.link.cable_type === 'fiber'
                ? '光纤链路'
                : displayCable.link.cable_type === 'dac'
                ? 'DAC 链路'
                : displayCable.link.cable_type === 'copper'
                ? '铜缆链路'
                : '物理链路'}
              {displayCable.link.speed_mbps ? ` · ${displayCable.link.speed_mbps} Mbps` : ''}
              {displayCable.link.discovery_source ? ` · ${displayCable.link.discovery_source.toUpperCase()}` : ''}
              {displayCable.link.link_kind === 'aggregation' && displayCable.link.member_count
                ? ` · LAG ${Number(displayCable.link.member_index || 0) + 1}/${displayCable.link.member_count}`
                : ''}
              {` · ${displayCable.link.status.toUpperCase()}`}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
};
