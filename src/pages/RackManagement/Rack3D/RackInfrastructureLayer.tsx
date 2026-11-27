import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { RackVM } from '../types';
import { U_HEIGHT_3D } from '../adapters/rackViewModel';
import { getPduMeterTexture, getRackSmartHeaderTexture } from './roomTextures';

interface RackInfrastructureLayerProps {
  rackVM: RackVM;
  occupiedUs: Set<number>;
  rackWidth: number;
  rackDepth: number;
  showPowerCords?: boolean;
  showBlankingPanels?: boolean;
  showAirflow?: boolean;
  cabinetLightsOn?: boolean;
}

/**
 * High-Craft Cabinet Hardware Details:
 *  - Top-of-Rack Illuminated Smart OLED Telemetry Bezel (Name, U-Usage, kW, Intake Temp)
 *  - Dual Interior Vertical Cabinet LED Light Strips (adds crisp studio depth inside cabinet)
 *  - Instanced Brushed-Steel M6 Rack-Mount Cage-Nut Screws on every device ear
 *  - Rear 0U Smart PDU Digital Amp/Voltage OLED Meters (A-Red / B-Blue) & Rear Lacing Bars
 */
const RackSmartCabinetDetails: React.FC<{
  rackVM: RackVM;
  rackWidth: number;
  rackDepth: number;
  cabinetLightsOn: boolean;
}> = ({ rackVM, rackWidth, rackDepth, cabinetLightsOn }) => {
  const screwRef = useRef<THREE.InstancedMesh>(null);
  const rackHeight = rackVM.totalU * U_HEIGHT_3D;
  const kw = Math.max(0, (rackVM.ratedPowerTotalWatts || 0) / 1000);

  const headerTex = useMemo(
    () => getRackSmartHeaderTexture(rackVM.name, rackVM.usedU, rackVM.totalU, rackVM.ratedPowerTotalWatts || 0),
    [rackVM.name, rackVM.usedU, rackVM.totalU, rackVM.ratedPowerTotalWatts],
  );
  const pduATex = useMemo(() => getPduMeterTexture('A', kw), [kw]);
  const pduBTex = useMemo(() => getPduMeterTexture('B', kw), [kw]);

  // 4 brushed-steel M6 mounting screws per device (top/bottom on left & right rack ears)
  const screwPositions = useMemo(() => {
    const pts: Array<[number, number, number]> = [];
    rackVM.validDevices.forEach(dev => {
      const zFace = dev.coordinates.centerZ + (dev.face === 'rear' ? -1 : 1) * (dev.coordinates.depth / 2 + 0.165);
      const yOff = Math.min(0.14, dev.coordinates.height * 0.3);
      for (const sx of [-2.28, 2.28]) {
        pts.push([sx, dev.coordinates.centerY + yOff, zFace]);
        pts.push([sx, dev.coordinates.centerY - yOff, zFace]);
      }
    });
    return pts;
  }, [rackVM.validDevices]);

  useEffect(() => {
    const mesh = screwRef.current;
    if (!mesh || !screwPositions.length) return;
    const dummy = new THREE.Object3D();
    screwPositions.forEach(([x, y, z], i) => {
      dummy.position.set(x, y, z);
      dummy.rotation.set(Math.PI / 2, 0, 0);
      dummy.scale.set(1, 1, 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }, [screwPositions]);

  const pduX = Math.max(2.38, rackWidth / 2 - 0.46);
  const pduRearFaceZ = -rackDepth * 0.33 - 0.34;
  const meterY = Math.min(rackHeight - 2.2, Math.max(4.5, rackHeight * 0.48));

  return (
    <group>
      {/* Top-of-Rack Illuminated Smart LCD Bezel */}
      <group position={[0, rackHeight + 0.34, rackDepth / 2 + 0.06]}>
        <mesh position={[0, 0, -0.04]}>
          <boxGeometry args={[rackWidth * 0.88, 0.56, 0.1]} />
          <meshStandardMaterial color="#111927" roughness={0.32} metalness={0.78} />
        </mesh>
        <mesh position={[0, 0, 0.018]}>
          <planeGeometry args={[rackWidth * 0.84, 0.48]} />
          <meshBasicMaterial map={headerTex} toneMapped={false} />
        </mesh>
      </group>

      {/* Dual Interior Vertical Cabinet Cool-White LED Strip Bars (controlled by Cabinet Light switch!) */}
      {[-1, 1].map(side => (
        <mesh
          key={`int-led-${side}`}
          position={[side * (rackWidth / 2 - 0.24), rackHeight / 2, rackDepth * 0.445]}
        >
          <boxGeometry args={[0.032, rackHeight - 0.5, 0.025]} />
          <meshBasicMaterial
            color={cabinetLightsOn ? '#e0f2fe' : '#1e293b'}
            transparent
            opacity={cabinetLightsOn ? 0.78 : 0.4}
            toneMapped={!cabinetLightsOn}
          />
        </mesh>
      ))}
      {cabinetLightsOn && (
        <pointLight
          position={[0, rackHeight * 0.65, rackDepth * 0.2]}
          intensity={1.35}
          distance={rackHeight * 1.1}
          color="#e0f2fe"
        />
      )}

      {/* Instanced Brushed-Steel M6 Rack-Mount Cage-Nut Screws (1 Draw Call) */}
      {screwPositions.length > 0 && (
        <instancedMesh ref={screwRef} args={[undefined, undefined, screwPositions.length]}>
          <cylinderGeometry args={[0.032, 0.032, 0.028, 8]} />
          <meshStandardMaterial color="#cbd5e1" roughness={0.22} metalness={0.92} />
        </instancedMesh>
      )}

      {/* Rear Dual 0U Smart PDU Digital OLED Amp Meters (Feed-A Red / Feed-B Blue) */}
      <group position={[-pduX, meterY, pduRearFaceZ]} rotation={[0, Math.PI, 0]}>
        <mesh position={[0, 0, -0.04]}>
          <boxGeometry args={[0.42, 0.86, 0.1]} />
          <meshStandardMaterial color="#181f2b" roughness={0.35} metalness={0.75} />
        </mesh>
        <mesh position={[0, 0, 0.015]}>
          <planeGeometry args={[0.36, 0.78]} />
          <meshBasicMaterial map={pduATex} toneMapped={false} />
        </mesh>
      </group>
      <group position={[pduX, meterY, pduRearFaceZ]} rotation={[0, Math.PI, 0]}>
        <mesh position={[0, 0, -0.04]}>
          <boxGeometry args={[0.42, 0.86, 0.1]} />
          <meshStandardMaterial color="#181f2b" roughness={0.35} metalness={0.75} />
        </mesh>
        <mesh position={[0, 0, 0.015]}>
          <planeGeometry args={[0.36, 0.78]} />
          <meshBasicMaterial map={pduBTex} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
};

/**
 * Rear Dual A/B AC Power Cords connecting each installed device's dual hot-swap
 * PSU-1 (A-Feed Red) and PSU-2 (B-Feed Blue) C14 inlets cleanly to the cabinet's
 * left & right 0U vertical smart PDUs, plus rear steel lacing support bars.
 */
const RearDualPowerCords: React.FC<{
  rackVM: RackVM;
  rackWidth: number;
  rackDepth: number;
}> = ({ rackVM, rackWidth, rackDepth }) => {
  const { cords, lacingYs } = useMemo(() => {
    const pduX = Math.max(2.38, rackWidth / 2 - 0.46);
    const pduZ = -rackDepth * 0.33;

    const list: Array<{
      id: string;
      geo: THREE.TubeGeometry;
      color: string;
      plugStart: [number, number, number];
      plugEnd: [number, number, number];
    }> = [];
    const ys: number[] = [];

    rackVM.validDevices.forEach((dev, idx) => {
      const role = (dev.role || '').toLowerCase();
      if (role.includes('patch_panel') || role.includes('patch panel') || role.includes('配线')) {
        return;
      }
      const rearZ = dev.coordinates.centerZ - dev.coordinates.depth / 2 - 0.14;
      const y = dev.coordinates.centerY;
      if (idx % 3 === 0) ys.push(y - 0.18);

      // Feed A (Red): Left PSU C14 inlet (-1.77) -> Left 0U A-PDU (-pduX)
      const aStart = new THREE.Vector3(-1.77, y, rearZ);
      const aEnd = new THREE.Vector3(-pduX, y, pduZ - 0.25);
      const aCurve = new THREE.CatmullRomCurve3([
        aStart,
        new THREE.Vector3(-1.77, y - 0.02, rearZ - 0.48),
        new THREE.Vector3(-pduX - 0.08, y - 0.04, rearZ - 0.36),
        new THREE.Vector3(-pduX, y - 0.01, pduZ - 0.56),
        aEnd,
      ]);
      list.push({
        id: `${dev.id}-psu-a`,
        geo: new THREE.TubeGeometry(aCurve, 22, 0.032, 7, false),
        color: '#dc2626',
        plugStart: [aStart.x, aStart.y, aStart.z],
        plugEnd: [aEnd.x, aEnd.y, aEnd.z],
      });

      // Feed B (Blue): Right PSU C14 inlet (+1.33) -> Right 0U B-PDU (+pduX)
      const bStart = new THREE.Vector3(1.33, y, rearZ);
      const bEnd = new THREE.Vector3(pduX, y, pduZ - 0.25);
      const bCurve = new THREE.CatmullRomCurve3([
        bStart,
        new THREE.Vector3(1.33, y - 0.02, rearZ - 0.48),
        new THREE.Vector3(pduX + 0.08, y - 0.04, rearZ - 0.36),
        new THREE.Vector3(pduX, y - 0.01, pduZ - 0.56),
        bEnd,
      ]);
      list.push({
        id: `${dev.id}-psu-b`,
        geo: new THREE.TubeGeometry(bCurve, 22, 0.032, 7, false),
        color: '#2563eb',
        plugStart: [bStart.x, bStart.y, bStart.z],
        plugEnd: [bEnd.x, bEnd.y, bEnd.z],
      });
    });

    return { cords: list, lacingYs: ys };
  }, [rackVM.validDevices, rackWidth, rackDepth]);

  useEffect(() => () => cords.forEach(c => c.geo.dispose()), [cords]);

  return (
    <group>
      {/* Rear horizontal steel cable-lacing support bars */}
      {lacingYs.map((ly, i) => (
        <mesh key={`lace-${i}`} position={[0, ly, -rackDepth * 0.44]}>
          <boxGeometry args={[rackWidth - 0.85, 0.045, 0.045]} />
          <meshStandardMaterial color="#334155" roughness={0.38} metalness={0.82} />
        </mesh>
      ))}
      {cords.map(c => (
        <group key={c.id}>
          <mesh geometry={c.geo}>
            <meshStandardMaterial color={c.color} roughness={0.42} metalness={0.22} />
          </mesh>
          {/* Molded IEC C13 plugs at PSU & 0U PDU ends */}
          <mesh position={c.plugStart}>
            <boxGeometry args={[0.14, 0.11, 0.18]} />
            <meshStandardMaterial color="#111827" roughness={0.4} metalness={0.35} />
          </mesh>
          <mesh position={c.plugEnd}>
            <boxGeometry args={[0.13, 0.11, 0.16]} />
            <meshStandardMaterial color="#111827" roughness={0.4} metalness={0.35} />
          </mesh>
        </group>
      ))}
    </group>
  );
};

/**
 * Tool-less 1U Anti-Dust Blanking Panels (Cold-Aisle Thermal Containment)
 * rendered via a single InstancedMesh for all unoccupied U positions.
 */
const RackBlankingPanels: React.FC<{
  totalU: number;
  occupiedUs: Set<number>;
  rackDepth: number;
}> = ({ totalU, occupiedUs, rackDepth }) => {
  const panelRef = useRef<THREE.InstancedMesh>(null);
  const clipRef = useRef<THREE.InstancedMesh>(null);

  const emptyUs = useMemo(() => {
    const out: number[] = [];
    for (let u = 1; u <= totalU; u++) {
      if (!occupiedUs.has(u)) out.push(u);
    }
    return out;
  }, [totalU, occupiedUs]);

  useEffect(() => {
    const panel = panelRef.current;
    const clip = clipRef.current;
    if (!panel || !clip || emptyUs.length === 0) return;
    const dummy = new THREE.Object3D();
    const frontZ = rackDepth * 0.42 + 0.04;

    emptyUs.forEach((u, idx) => {
      const y = (u - 0.5) * U_HEIGHT_3D;
      dummy.position.set(0, y, frontZ);
      dummy.scale.set(1, 1, 1);
      dummy.updateMatrix();
      panel.setMatrixAt(idx, dummy.matrix);

      dummy.position.set(-2.22, y, frontZ + 0.045);
      dummy.updateMatrix();
      clip.setMatrixAt(idx * 2, dummy.matrix);

      dummy.position.set(2.22, y, frontZ + 0.045);
      dummy.updateMatrix();
      clip.setMatrixAt(idx * 2 + 1, dummy.matrix);
    });
    panel.instanceMatrix.needsUpdate = true;
    clip.instanceMatrix.needsUpdate = true;
  }, [emptyUs, rackDepth]);

  if (!emptyUs.length) return null;

  return (
    <group>
      <instancedMesh ref={panelRef} args={[undefined, undefined, emptyUs.length]}>
        <boxGeometry args={[4.76, U_HEIGHT_3D - 0.025, 0.06]} />
        <meshStandardMaterial color="#151d29" roughness={0.52} metalness={0.55} />
      </instancedMesh>
      <instancedMesh ref={clipRef} args={[undefined, undefined, emptyUs.length * 2]}>
        <boxGeometry args={[0.12, 0.16, 0.04]} />
        <meshStandardMaterial color="#475569" roughness={0.35} metalness={0.78} />
      </instancedMesh>
    </group>
  );
};

/**
 * Single-Rack Animated Front Cold-Air Intake & Rear Hot-Air Exhaust Flow Layer.
 */
const RackAirflowLayer: React.FC<{ rackVM: RackVM; rackDepth: number }> = ({ rackVM, rackDepth }) => {
  const coldRef = useRef<THREE.InstancedMesh>(null);
  const hotRef = useRef<THREE.InstancedMesh>(null);
  const lastTickRef = useRef(0);

  const streams = useMemo(() => {
    const cold: Array<{ x: number; y: number; phase: number; speed: number }> = [];
    const hot: Array<{ x: number; y: number; phase: number; speed: number }> = [];
    const devices = rackVM.validDevices.slice(0, 24);
    devices.forEach((dev, idx) => {
      for (let lane = -1; lane <= 1; lane++) {
        cold.push({
          x: lane * 1.35,
          y: dev.coordinates.centerY,
          phase: (idx * 0.23 + (lane + 1) * 0.31) % 1,
          speed: 0.72 + (idx % 3) * 0.12,
        });
        hot.push({
          x: lane * 1.25,
          y: dev.coordinates.centerY,
          phase: (idx * 0.19 + (lane + 1) * 0.37) % 1,
          speed: 0.8 + (idx % 3) * 0.14,
        });
      }
    });
    return { cold, hot };
  }, [rackVM.validDevices]);

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const frontZ = rackDepth * 0.42;

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (t - lastTickRef.current < 0.035) return;
    lastTickRef.current = t;
    if (coldRef.current) {
      streams.cold.forEach((s, i) => {
        const frac = (t * s.speed * 0.55 + s.phase) % 1;
        const z = frontZ + 3.4 - frac * 3.1;
        const fade = Math.sin(frac * Math.PI);
        dummy.position.set(s.x, s.y, z);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(0.11 * fade + 0.02, 0.06 * fade + 0.015, 0.72 * fade + 0.12);
        dummy.updateMatrix();
        coldRef.current!.setMatrixAt(i, dummy.matrix);
      });
      coldRef.current.instanceMatrix.needsUpdate = true;
    }
    if (hotRef.current) {
      streams.hot.forEach((s, i) => {
        const frac = (t * s.speed * 0.58 + s.phase) % 1;
        const z = -frontZ - 0.3 - frac * 2.8;
        const y = s.y + frac * frac * 1.65;
        const fade = Math.sin(frac * Math.PI);
        dummy.position.set(s.x, y, z);
        dummy.rotation.set(0.35 * frac, 0, 0);
        dummy.scale.set(0.13 * fade + 0.02, 0.07 * fade + 0.015, 0.76 * fade + 0.14);
        dummy.updateMatrix();
        hotRef.current!.setMatrixAt(i, dummy.matrix);
      });
      hotRef.current.instanceMatrix.needsUpdate = true;
    }
  });

  if (!streams.cold.length) return null;

  return (
    <group>
      <instancedMesh ref={coldRef} args={[undefined, undefined, streams.cold.length]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial color="#38bdf8" transparent opacity={0.78} toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={hotRef} args={[undefined, undefined, streams.hot.length]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial color="#fb7185" transparent opacity={0.76} toneMapped={false} />
      </instancedMesh>
    </group>
  );
};

export const RackInfrastructureLayer: React.FC<RackInfrastructureLayerProps> = ({
  rackVM,
  occupiedUs,
  rackWidth,
  rackDepth,
  showPowerCords = true,
  showBlankingPanels = false,
  showAirflow = false,
  cabinetLightsOn = true,
}) => (
  <group>
    <RackSmartCabinetDetails
      rackVM={rackVM}
      rackWidth={rackWidth}
      rackDepth={rackDepth}
      cabinetLightsOn={cabinetLightsOn}
    />
    {showPowerCords && (
      <RearDualPowerCords rackVM={rackVM} rackWidth={rackWidth} rackDepth={rackDepth} />
    )}
    {showBlankingPanels && (
      <RackBlankingPanels totalU={rackVM.totalU} occupiedUs={occupiedUs} rackDepth={rackDepth} />
    )}
    {showAirflow && <RackAirflowLayer rackVM={rackVM} rackDepth={rackDepth} />}
  </group>
);
