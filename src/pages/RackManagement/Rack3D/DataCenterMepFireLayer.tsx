import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { DataCenterRoomModel } from './fleetLayout';

// ---------------------------------------------------------------------------
// Module-level cached signage CanvasTextures (zero network dependency)
// ---------------------------------------------------------------------------
let exitSignTexCache: THREE.CanvasTexture | null = null;
let gasWarningTexCache: THREE.CanvasTexture | null = null;
let leakPanelTexCache: THREE.CanvasTexture | null = null;
let mebPanelTexCache: THREE.CanvasTexture | null = null;

function getExitSignTexture(): THREE.CanvasTexture {
  if (exitSignTexCache) return exitSignTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 96;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#059669';
  ctx.fillRect(0, 0, 256, 96);
  ctx.strokeStyle = '#a7f3d0';
  ctx.lineWidth = 4;
  ctx.strokeRect(4, 4, 248, 88);

  // Stylized running-person pictogram
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(46, 28, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.lineWidth = 6;
  ctx.strokeStyle = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(46, 38);
  ctx.lineTo(42, 60);
  ctx.lineTo(28, 78);
  ctx.moveTo(42, 60);
  ctx.lineTo(58, 76);
  ctx.moveTo(30, 48);
  ctx.lineTo(62, 44);
  ctx.stroke();

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 30px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('EXIT', 82, 48);
  ctx.font = 'bold 20px system-ui, sans-serif';
  ctx.fillStyle = '#ecfdf5';
  ctx.fillText('安全出口', 82, 76);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  exitSignTexCache = tex;
  return tex;
}

function getGasWarningTexture(): THREE.CanvasTexture {
  if (gasWarningTexCache) return gasWarningTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 88;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#450a0a';
  ctx.fillRect(0, 0, 256, 88);
  ctx.strokeStyle = '#ef4444';
  ctx.lineWidth = 4;
  ctx.strokeRect(4, 4, 248, 80);

  ctx.fillStyle = '#ef4444';
  ctx.fillRect(14, 16, 14, 56);

  ctx.fillStyle = '#fef2f2';
  ctx.font = 'bold 26px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('放气勿入', 40, 46);
  ctx.fillStyle = '#fca5a5';
  ctx.font = 'bold 14px monospace';
  ctx.fillText('FM-200 GAS DISCHARGE', 40, 70);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  gasWarningTexCache = tex;
  return tex;
}

function getLeakPanelTexture(): THREE.CanvasTexture {
  if (leakPanelTexCache) return leakPanelTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 160;
  canvas.height = 112;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, 160, 112);
  ctx.strokeStyle = '#facc15';
  ctx.lineWidth = 4;
  ctx.strokeRect(3, 3, 154, 106);

  ctx.fillStyle = '#facc15';
  ctx.font = 'bold 18px system-ui, sans-serif';
  ctx.fillText('漏水检测 LEAK', 14, 30);

  ctx.fillStyle = '#052e16';
  ctx.fillRect(14, 42, 132, 34);
  ctx.fillStyle = '#22c55e';
  ctx.font = 'bold 18px monospace';
  ctx.fillText('0 LEAK OK', 24, 65);

  ctx.fillStyle = '#94a3b8';
  ctx.font = '12px monospace';
  ctx.fillText('ZONE CRAC-W', 14, 96);

  const tex = new THREE.CanvasTexture(canvas);
  leakPanelTexCache = tex;
  return tex;
}

function getMebPanelTexture(): THREE.CanvasTexture {
  if (mebPanelTexCache) return mebPanelTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 160;
  canvas.height = 112;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, 160, 112);
  ctx.strokeStyle = '#d97706';
  ctx.lineWidth = 4;
  ctx.strokeRect(3, 3, 154, 106);

  // PE Green/Yellow safety stripe
  ctx.fillStyle = '#16a34a';
  ctx.fillRect(12, 12, 68, 10);
  ctx.fillStyle = '#facc15';
  ctx.fillRect(80, 12, 68, 10);

  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 20px system-ui, sans-serif';
  ctx.fillText('MEB 等电位', 14, 52);
  ctx.fillStyle = '#fbbf24';
  ctx.font = 'bold 14px monospace';
  ctx.fillText('R <= 1.0 OHM', 14, 82);

  const tex = new THREE.CanvasTexture(canvas);
  mebPanelTexCache = tex;
  return tex;
}

interface PipeSeg {
  cx: number;
  cy: number;
  cz: number;
  len: number;
  axis: 'x' | 'y' | 'z';
}

interface Vec3Point {
  x: number;
  y: number;
  z: number;
}

/**
 * GB 50174-2017 & GB 50370-2005 Compliant Fire Suppression, HVAC Chilled-Water / Leak Protection,
 * and Equipotential Grounding Layer (iGPU InstancedMesh batched).
 * - Fire: FM-200 manifolded cylinder bank, ceiling red pipe grid at Y=3.55m, 360° nozzles, dual smoke/heat detectors,
 *   high-wall pressure relief damper, EXIT/Gas-Discharge signs, manual/auto emergency buttons & CO2 extinguishers.
 * - Water: Dedicated CHW Supply/Return headers strictly behind/under perimeter CRAC-W (never over IT racks or UPS),
 *   waterproof floor dam curb + continuous yellow leak-detection rope & zone monitor.
 * - Electrical Grounding: Continuous copper equipotential bonding bar along back/left walls + MEB terminal box.
 */
export const DataCenterMepFireLayer: React.FC<{
  room: DataCenterRoomModel;
  zh: boolean;
}> = ({ room }) => {
  const nozzleRef = useRef<THREE.InstancedMesh>(null);
  const hangerRef = useRef<THREE.InstancedMesh>(null);
  const detectorBodyRef = useRef<THREE.InstancedMesh>(null);
  const detectorLedRef = useRef<THREE.InstancedMesh>(null);

  const exitTex = useMemo(() => getExitSignTexture(), []);
  const gasTex = useMemo(() => getGasWarningTexture(), []);
  const leakTex = useMemo(() => getLeakPanelTexture(), []);
  const mebTex = useMemo(() => getMebPanelTexture(), []);

  const { minX, maxX, minZ, maxZ, centerX, ceilingY } = room.bounds;
  const FIRE_PIPE_Y = 3.55; // Well above FIBER_TRAY_Y (2.68m) and below ceilingY (4.25m)

  const perimeterCracs = useMemo(
    () => room.cracUnits.filter(u => u.cracRole === 'perimeter'),
    [room.cracUnits],
  );

  // 1. FM-200 Cylinder Bank position tucked neatly along the back-left wall
  const fmBankOriginX = minX + 0.72;
  const fmBankZ = minZ + 0.34;
  const fmOffsets = [0, 0.34, 0.68, 1.02];
  const pilotOffset = 1.34;
  const manifoldXMin = fmBankOriginX - 0.14;
  const manifoldXMax = fmBankOriginX + pilotOffset + 0.12;
  const riserX = fmBankOriginX + pilotOffset * 0.5;

  // 2. Ceiling FM-200 Piping Network, Nozzles & Hangers
  const { firePipes, nozzles, pipeHangers } = useMemo(() => {
    const pipes: PipeSeg[] = [];
    const nozzlePts: Vec3Point[] = [];
    const hangerPts: Vec3Point[] = [];

    const lastAisleZ = room.coldAisles.length > 0
      ? room.coldAisles[room.coldAisles.length - 1].z
      : maxZ - 1.5;

    // Infra corridor fire branch sits in front of UPS/CRAC/ODF corridor
    const infraRef = room.upsUnits[0] || room.cracUnits[0];
    const infraBranchZ = infraRef ? infraRef.position[2] + infraRef.depth / 2 + 0.75 : minZ + 2.2;
    const infraSpanMinX = Math.max(minX + 1.0, riserX);
    const infraSpanMaxX = Math.min(maxX - 1.0, (room.odfUnits[room.odfUnits.length - 1]?.position[0] ?? centerX + 2) + 0.5);

    const headerX = Math.max(minX + 0.9, riserX);
    const headerEndZ = Math.max(infraBranchZ, lastAisleZ);

    // Feeder from cylinder manifold riser to main Z header
    if (Math.abs(infraBranchZ - fmBankZ) > 0.15) {
      pipes.push({
        cx: headerX,
        cy: FIRE_PIPE_Y,
        cz: (fmBankZ + headerEndZ) / 2,
        len: Math.max(0.5, headerEndZ - fmBankZ),
        axis: 'z',
      });
    }

    // Main horizontal branch over the 1.80m Main Service Corridor
    const infraLen = Math.max(2.0, infraSpanMaxX - infraSpanMinX);
    const infraMidX = (infraSpanMinX + infraSpanMaxX) / 2;
    pipes.push({
      cx: infraMidX,
      cy: FIRE_PIPE_Y,
      cz: infraBranchZ,
      len: infraLen,
      axis: 'x',
    });
    const infraNozzleCount = Math.max(2, Math.min(5, Math.round(infraLen / 2.6)));
    for (let i = 0; i < infraNozzleCount; i++) {
      const nx = infraSpanMinX + ((i + 0.5) / infraNozzleCount) * infraLen;
      nozzlePts.push({ x: nx, y: FIRE_PIPE_Y - 0.1, z: infraBranchZ });
    }
    hangerPts.push(
      { x: infraSpanMinX + 0.4, y: (FIRE_PIPE_Y + ceilingY) / 2, z: infraBranchZ },
      { x: infraSpanMaxX - 0.4, y: (FIRE_PIPE_Y + ceilingY) / 2, z: infraBranchZ },
    );

    // Dedicated branch centered directly over each Enclosed Cold Aisle
    room.coldAisles.forEach(aisle => {
      const bMinX = Math.min(headerX, aisle.centerX - aisle.spanX / 2 + 0.35);
      const bMaxX = aisle.centerX + aisle.spanX / 2 - 0.35;
      const bLen = Math.max(1.2, bMaxX - bMinX);
      pipes.push({
        cx: (bMinX + bMaxX) / 2,
        cy: FIRE_PIPE_Y,
        cz: aisle.z,
        len: bLen,
        axis: 'x',
      });

      const aisleSpan = Math.max(1.0, aisle.spanX - 0.7);
      const count = Math.max(2, Math.min(8, Math.round(aisleSpan / 2.4)));
      for (let i = 0; i < count; i++) {
        const nx = aisle.centerX - aisleSpan / 2 + ((i + 0.5) / count) * aisleSpan;
        nozzlePts.push({ x: nx, y: FIRE_PIPE_Y - 0.1, z: aisle.z });
      }
      hangerPts.push(
        { x: aisle.centerX - aisleSpan / 2 + 0.25, y: (FIRE_PIPE_Y + ceilingY) / 2, z: aisle.z },
        { x: aisle.centerX + aisleSpan / 2 - 0.25, y: (FIRE_PIPE_Y + ceilingY) / 2, z: aisle.z },
      );
    });

    if (room.coldAisles.length === 0) {
      nozzlePts.push({ x: centerX, y: FIRE_PIPE_Y - 0.1, z: infraBranchZ });
    }

    return { firePipes: pipes, nozzles: nozzlePts, pipeHangers: hangerPts };
  }, [room.coldAisles, room.upsUnits, room.cracUnits, room.odfUnits, minX, maxX, minZ, maxZ, centerX, ceilingY, riserX, fmBankZ]);

  // 3. Ceiling Smoke + Heat Dual Detector Grid (InstancedMesh, scales cleanly to 30m+ halls)
  const detectors = useMemo(() => {
    const pts: Vec3Point[] = [];
    const cols = Math.max(2, Math.min(10, Math.round(room.bounds.width / 3.8)));
    const rowsCount = Math.max(2, Math.min(8, Math.round(room.bounds.depth / 3.8)));
    const spanX = Math.max(2, room.bounds.width - 2.4);
    const spanZ = Math.max(2, room.bounds.depth - 2.4);
    for (let r = 0; r < rowsCount; r++) {
      const z = minZ + 1.2 + ((r + 0.5) / rowsCount) * spanZ;
      for (let c = 0; c < cols; c++) {
        const x = minX + 1.2 + ((c + 0.5) / cols) * spanX;
        pts.push({ x, y: ceilingY - 0.16, z });
      }
    }
    return pts;
  }, [room.bounds.width, room.bounds.depth, minX, minZ, ceilingY]);

  useEffect(() => {
    const dummy = new THREE.Object3D();

    const nm = nozzleRef.current;
    if (nm) {
      nozzles.forEach((pt, i) => {
        dummy.position.set(pt.x, pt.y, pt.z);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        nm.setMatrixAt(i, dummy.matrix);
      });
      nm.instanceMatrix.needsUpdate = true;
    }

    const hm = hangerRef.current;
    if (hm) {
      const rodLen = Math.max(0.2, ceilingY - FIRE_PIPE_Y);
      pipeHangers.forEach((pt, i) => {
        dummy.position.set(pt.x, pt.y, pt.z);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(0.016, rodLen, 0.016);
        dummy.updateMatrix();
        hm.setMatrixAt(i, dummy.matrix);
      });
      hm.instanceMatrix.needsUpdate = true;
    }

    const dm = detectorBodyRef.current;
    const dl = detectorLedRef.current;
    if (dm && dl) {
      detectors.forEach((pt, i) => {
        dummy.position.set(pt.x, pt.y, pt.z);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        dm.setMatrixAt(i, dummy.matrix);

        dummy.position.set(pt.x + 0.045, pt.y - 0.028, pt.z);
        dummy.updateMatrix();
        dl.setMatrixAt(i, dummy.matrix);
      });
      dm.instanceMatrix.needsUpdate = true;
      dl.instanceMatrix.needsUpdate = true;
    }
  }, [nozzles, pipeHangers, detectors, ceilingY]);

  // 4. Perimeter CRAC-W Chilled Water Piping, Waterproof Dam & Leak Detection Rope Bounds
  const cracWaterZone = useMemo(() => {
    if (!perimeterCracs.length) return null;
    const xMin = Math.min(...perimeterCracs.map(c => c.position[0] - c.width / 2));
    const xMax = Math.max(...perimeterCracs.map(c => c.position[0] + c.width / 2));
    const zMin = Math.min(...perimeterCracs.map(c => c.position[2] - c.depth / 2));
    const zMax = Math.max(...perimeterCracs.map(c => c.position[2] + c.depth / 2));
    const pad = 0.16;
    return {
      damMinX: xMin - pad,
      damMaxX: xMax + pad,
      damMinZ: zMin - pad,
      damMaxZ: zMax + pad,
      damCenterX: (xMin + xMax) / 2,
      damCenterZ: (zMin + zMax) / 2,
      damW: xMax - xMin + pad * 2,
      damD: zMax - zMin + pad * 2,
      pipeHeaderZ: zMin - 0.28,
      pipeStartX: xMin - 0.12,
      pipeEndX: xMax + 0.12,
    };
  }, [perimeterCracs]);

  // 5. Egress Exit & Safety Hardware Coordinates on Left Wall near Front Corridor
  const egressZ = maxZ - 1.35;
  const wallLeftX = minX + 0.08;
  const wallBackZ = minZ + 0.08;

  return (
    <group>
      {/* ==================== A. FM-200 GAS SUPPRESSION SYSTEM ==================== */}
      {/* Manifold Rack Baseplate, Safety Strip, Steel Frame & Clamping Rails */}
      <group>
        <mesh position={[riserX, 0.02, fmBankZ]}>
          <boxGeometry args={[manifoldXMax - manifoldXMin + 0.24, 0.04, 0.44]} />
          <meshStandardMaterial color="#1e293b" roughness={0.45} metalness={0.7} />
        </mesh>
        {/* Yellow/black hazard perimeter floor trim */}
        <mesh position={[riserX, 0.008, fmBankZ + 0.23]}>
          <boxGeometry args={[manifoldXMax - manifoldXMin + 0.28, 0.012, 0.04]} />
          <meshStandardMaterial color="#facc15" roughness={0.4} />
        </mesh>
        {/* Upright steel rack struts */}
        {[manifoldXMin - 0.06, manifoldXMax + 0.06].map((sx, idx) => (
          <mesh key={`fm-post-${idx}`} position={[sx, 1.05, fmBankZ - 0.12]}>
            <boxGeometry args={[0.05, 2.06, 0.05]} />
            <meshStandardMaterial color="#334155" roughness={0.35} metalness={0.78} />
          </mesh>
        ))}
        {/* Horizontal retention clamping bars */}
        {[0.82, 1.32, 1.98].map((ry, idx) => (
          <mesh key={`fm-bar-${idx}`} position={[riserX, ry, fmBankZ - 0.12]}>
            <boxGeometry args={[manifoldXMax - manifoldXMin + 0.16, 0.05, 0.05]} />
            <meshStandardMaterial color="#475569" roughness={0.35} metalness={0.78} />
          </mesh>
        ))}

        {/* 4 x Red FM-200 Agent Cylinders + Valves + Pressure Gauges + Flex Hoses */}
        {fmOffsets.map((offset, idx) => {
          const cx = fmBankOriginX + offset;
          return (
            <group key={`fm-cyl-${idx}`} position={[cx, 0.04, fmBankZ]}>
              <mesh position={[0, 0.68, 0]}>
                <cylinderGeometry args={[0.135, 0.135, 1.32, 16]} />
                <meshStandardMaterial color="#dc2626" roughness={0.28} metalness={0.55} />
              </mesh>
              <mesh position={[0, 1.34, 0]}>
                <sphereGeometry args={[0.135, 14, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
                <meshStandardMaterial color="#dc2626" roughness={0.28} metalness={0.55} />
              </mesh>
              {/* Brass/Silver Valve & Pressure Gauge */}
              <mesh position={[0, 1.52, 0]}>
                <cylinderGeometry args={[0.036, 0.048, 0.14, 12]} />
                <meshStandardMaterial color="#cbd5e1" roughness={0.24} metalness={0.86} />
              </mesh>
              <mesh position={[0, 1.52, 0.05]} rotation={[Math.PI / 2, 0, 0]}>
                <cylinderGeometry args={[0.026, 0.026, 0.018, 12]} />
                <meshStandardMaterial color="#22c55e" roughness={0.3} />
              </mesh>
              {/* High-pressure discharge flex riser to collector manifold */}
              <mesh position={[0, 1.78, -0.04]}>
                <cylinderGeometry args={[0.022, 0.022, 0.42, 10]} />
                <meshStandardMaterial color="#1f2937" roughness={0.45} metalness={0.65} />
              </mesh>
            </group>
          );
        })}

        {/* Nitrogen Pilot Actuation Cylinder */}
        <group position={[fmBankOriginX + pilotOffset, 0.04, fmBankZ]}>
          <mesh position={[0, 0.48, 0]}>
            <cylinderGeometry args={[0.085, 0.085, 0.92, 14]} />
            <meshStandardMaterial color="#15803d" roughness={0.3} metalness={0.55} />
          </mesh>
          <mesh position={[0, 0.99, 0]}>
            <cylinderGeometry args={[0.03, 0.04, 0.12, 10]} />
            <meshStandardMaterial color="#e2e8f0" roughness={0.24} metalness={0.85} />
          </mesh>
          <mesh position={[0, 1.09, 0]}>
            <boxGeometry args={[0.08, 0.08, 0.08]} />
            <meshStandardMaterial color="#f59e0b" roughness={0.35} metalness={0.5} />
          </mesh>
        </group>

        {/* Horizontal Red Collector Manifold & Vertical Riser up to FIRE_PIPE_Y=3.55m */}
        <mesh position={[riserX, 2.02, fmBankZ - 0.04]} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.048, 0.048, manifoldXMax - manifoldXMin + 0.1, 12]} />
          <meshStandardMaterial color="#dc2626" roughness={0.32} metalness={0.62} />
        </mesh>
        <mesh position={[riserX, (2.02 + FIRE_PIPE_Y) / 2, fmBankZ - 0.04]}>
          <cylinderGeometry args={[0.045, 0.045, FIRE_PIPE_Y - 2.02, 12]} />
          <meshStandardMaterial color="#dc2626" roughness={0.32} metalness={0.62} />
        </mesh>
      </group>

      {/* Ceiling Seamless Red Fire Suppression Pipe Network */}
      {firePipes.map((seg, idx) => (
        <mesh
          key={`fpipe-${idx}`}
          position={[seg.cx, seg.cy, seg.cz]}
          rotation={[
            seg.axis === 'z' ? Math.PI / 2 : 0,
            0,
            seg.axis === 'x' ? Math.PI / 2 : 0,
          ]}
        >
          <cylinderGeometry args={[0.038, 0.038, seg.len, 10]} />
          <meshStandardMaterial color="#dc2626" roughness={0.34} metalness={0.6} />
        </mesh>
      ))}

      {/* Instanced 360° Full-Flooding Discharge Nozzles */}
      {nozzles.length > 0 && (
        <instancedMesh ref={nozzleRef} args={[undefined, undefined, nozzles.length]}>
          <cylinderGeometry args={[0.022, 0.044, 0.14, 10]} />
          <meshStandardMaterial color="#cbd5e1" roughness={0.25} metalness={0.88} />
        </instancedMesh>
      )}

      {/* Instanced Fire Pipe Ceiling Hangers */}
      {pipeHangers.length > 0 && (
        <instancedMesh ref={hangerRef} args={[undefined, undefined, pipeHangers.length]}>
          <boxGeometry args={[1, 1, 1]} />
          <meshStandardMaterial color="#64748b" roughness={0.35} metalness={0.85} />
        </instancedMesh>
      )}

      {/* Dual Smoke + Thermal Ceiling Detector Matrix */}
      {detectors.length > 0 && (
        <>
          <instancedMesh ref={detectorBodyRef} args={[undefined, undefined, detectors.length]}>
            <cylinderGeometry args={[0.075, 0.085, 0.055, 14]} />
            <meshStandardMaterial color="#e2e8f0" roughness={0.35} metalness={0.2} />
          </instancedMesh>
          <instancedMesh ref={detectorLedRef} args={[undefined, undefined, detectors.length]}>
            <sphereGeometry args={[0.014, 8, 8]} />
            <meshBasicMaterial color="#ef4444" toneMapped={false} />
          </instancedMesh>
        </>
      )}

      {/* Fail-Open Fire-Link Electromagnetic Latch Strips on Enclosed Cold Aisle Roofs */}
      {room.coldAisles.map((aisle, idx) => (
        <mesh key={`aisle-firelink-${idx}`} position={[aisle.centerX, 2.045, aisle.z]}>
          <boxGeometry args={[Math.max(1.2, aisle.spanX * 0.4), 0.022, 0.05]} />
          <meshStandardMaterial color="#ef4444" emissive="#991b1b" emissiveIntensity={0.4} roughness={0.3} />
        </mesh>
      ))}

      {/* High-Wall Auto Pressure Relief Damper (自动泄压口) on Back Wall */}
      <group position={[centerX + 1.2, 3.25, wallBackZ]}>
        <mesh>
          <boxGeometry args={[0.92, 0.56, 0.08]} />
          <meshStandardMaterial color="#334155" roughness={0.38} metalness={0.72} />
        </mesh>
        {[-0.16, -0.06, 0.04, 0.14].map((ly, i) => (
          <mesh key={`damper-blade-${i}`} position={[0, ly, 0.035]} rotation={[0.25, 0, 0]}>
            <boxGeometry args={[0.8, 0.065, 0.02]} />
            <meshStandardMaterial color="#94a3b8" roughness={0.32} metalness={0.78} />
          </mesh>
        ))}
        <mesh position={[0, 0.31, 0.03]}>
          <boxGeometry args={[0.42, 0.045, 0.025]} />
          <meshBasicMaterial color="#ef4444" toneMapped={false} />
        </mesh>
      </group>

      {/* Left-Front Egress Safety Station: EXIT, 放气勿入, Emergency Button Box & CO2 Extinguishers */}
      <group position={[wallLeftX, 0, egressZ]} rotation={[0, Math.PI / 2, 0]}>
        {/* Green EXIT 安全出口 Sign Box */}
        <mesh position={[0, 2.55, 0]}>
          <boxGeometry args={[0.72, 0.27, 0.06]} />
          <meshStandardMaterial color="#065f46" roughness={0.3} />
        </mesh>
        <mesh position={[0, 2.55, 0.032]}>
          <planeGeometry args={[0.7, 0.25]} />
          <meshBasicMaterial map={exitTex} toneMapped={false} />
        </mesh>

        {/* Red 放气勿入 Gas Discharge Strobe Sign */}
        <mesh position={[0, 2.9, 0]}>
          <boxGeometry args={[0.72, 0.24, 0.06]} />
          <meshStandardMaterial color="#450a0a" roughness={0.3} />
        </mesh>
        <mesh position={[0, 2.9, 0.032]}>
          <planeGeometry args={[0.7, 0.22]} />
          <meshBasicMaterial map={gasTex} toneMapped={false} />
        </mesh>

        {/* Manual / Auto Emergency Start-Stop Box at 1.45m */}
        <mesh position={[0.48, 1.45, 0]}>
          <boxGeometry args={[0.24, 0.32, 0.07]} />
          <meshStandardMaterial color="#b91c1c" roughness={0.32} metalness={0.45} />
        </mesh>
        <mesh position={[0.42, 1.47, 0.042]}>
          <cylinderGeometry args={[0.028, 0.028, 0.02, 12]} />
          <meshBasicMaterial color="#22c55e" toneMapped={false} />
        </mesh>
        <mesh position={[0.54, 1.47, 0.042]}>
          <cylinderGeometry args={[0.028, 0.028, 0.02, 12]} />
          <meshBasicMaterial color="#ef4444" toneMapped={false} />
        </mesh>

        {/* Dual Portable CO2 Fire Extinguishers */}
        {[-0.22, 0.06].map((ex, i) => (
          <group key={`co2-${i}`} position={[ex, 0, 0.24]}>
            <mesh position={[0, 0.34, 0]}>
              <cylinderGeometry args={[0.078, 0.078, 0.64, 14]} />
              <meshStandardMaterial color="#dc2626" roughness={0.3} metalness={0.5} />
            </mesh>
            <mesh position={[0, 0.69, 0]}>
              <cylinderGeometry args={[0.025, 0.032, 0.08, 10]} />
              <meshStandardMaterial color="#cbd5e1" roughness={0.25} metalness={0.85} />
            </mesh>
            {/* Characteristic CO2 black horn nozzle */}
            <mesh position={[0.06, 0.62, 0.02]} rotation={[0, 0, -0.55]}>
              <cylinderGeometry args={[0.036, 0.015, 0.16, 10]} />
              <meshStandardMaterial color="#0f172a" roughness={0.5} />
            </mesh>
          </group>
        ))}
      </group>

      {/* ==================== B. CHILLED WATER PIPING, DAM & LEAK DETECTION ==================== */}
      {cracWaterZone && (
        <group>
          {/* Waterproof Containment Dam Curb tightly enclosing ONLY CRAC-W footprint */}
          {[
            { pos: [cracWaterZone.damCenterX, 0.028, cracWaterZone.damMinZ] as [number, number, number], size: [cracWaterZone.damW, 0.056, 0.05] as [number, number, number] },
            { pos: [cracWaterZone.damCenterX, 0.028, cracWaterZone.damMaxZ] as [number, number, number], size: [cracWaterZone.damW, 0.056, 0.05] as [number, number, number] },
            { pos: [cracWaterZone.damMinX, 0.028, cracWaterZone.damCenterZ] as [number, number, number], size: [0.05, 0.056, cracWaterZone.damD] as [number, number, number] },
            { pos: [cracWaterZone.damMaxX, 0.028, cracWaterZone.damCenterZ] as [number, number, number], size: [0.05, 0.056, cracWaterZone.damD] as [number, number, number] },
          ].map((curb, i) => (
            <group key={`dam-curb-${i}`} position={curb.pos}>
              <mesh>
                <boxGeometry args={curb.size} />
                <meshStandardMaterial color="#334155" roughness={0.45} metalness={0.55} />
              </mesh>
              <mesh position={[0, 0.029, 0]}>
                <boxGeometry args={[curb.size[0], 0.008, curb.size[2]]} />
                <meshStandardMaterial color="#eab308" roughness={0.4} />
              </mesh>
            </group>
          ))}

          {/* Continuous Bright Yellow Locating Leak-Detection Sensing Rope inside the CRAC-W Dam */}
          {[
            { pos: [cracWaterZone.damCenterX, 0.014, cracWaterZone.damMinZ + 0.055] as [number, number, number], size: [cracWaterZone.damW - 0.1, 0.016, 0.016] as [number, number, number] },
            { pos: [cracWaterZone.damCenterX, 0.014, cracWaterZone.damMaxZ - 0.055] as [number, number, number], size: [cracWaterZone.damW - 0.1, 0.016, 0.016] as [number, number, number] },
            { pos: [cracWaterZone.damMinX + 0.055, 0.014, cracWaterZone.damCenterZ] as [number, number, number], size: [0.016, 0.016, cracWaterZone.damD - 0.1] as [number, number, number] },
            { pos: [cracWaterZone.damMaxX - 0.055, 0.014, cracWaterZone.damCenterZ] as [number, number, number], size: [0.016, 0.016, cracWaterZone.damD - 0.1] as [number, number, number] },
          ].map((rope, i) => (
            <mesh key={`leak-rope-${i}`} position={rope.pos}>
              <boxGeometry args={rope.size} />
              <meshBasicMaterial color="#facc15" toneMapped={false} />
            </mesh>
          ))}

          {/* Wall/Post-Mounted Leak Detection Controller Box behind CRAC-W */}
          <group position={[cracWaterZone.damMinX - 0.24, 1.38, wallBackZ]}>
            <mesh>
              <boxGeometry args={[0.26, 0.19, 0.07]} />
              <meshStandardMaterial color="#1e293b" roughness={0.38} metalness={0.65} />
            </mesh>
            <mesh position={[0, 0, 0.038]}>
              <planeGeometry args={[0.24, 0.17]} />
              <meshBasicMaterial map={leakTex} toneMapped={false} />
            </mesh>
          </group>

          {/* Insulated CHW Supply (Blue) & Return (Orange-Red) Headers Strictly Behind CRAC-W */}
          <mesh
            position={[cracWaterZone.damCenterX, 0.24, cracWaterZone.pipeHeaderZ]}
            rotation={[0, 0, Math.PI / 2]}
          >
            <cylinderGeometry args={[0.044, 0.044, cracWaterZone.pipeEndX - cracWaterZone.pipeStartX, 12]} />
            <meshStandardMaterial color="#0284c7" roughness={0.35} metalness={0.45} />
          </mesh>
          <mesh
            position={[cracWaterZone.damCenterX, 0.42, cracWaterZone.pipeHeaderZ]}
            rotation={[0, 0, Math.PI / 2]}
          >
            <cylinderGeometry args={[0.044, 0.044, cracWaterZone.pipeEndX - cracWaterZone.pipeStartX, 12]} />
            <meshStandardMaterial color="#ea580c" roughness={0.35} metalness={0.45} />
          </mesh>
          {/* Condensate Drain Header (Grey) */}
          <mesh
            position={[cracWaterZone.damCenterX, 0.1, cracWaterZone.pipeHeaderZ]}
            rotation={[0, 0, Math.PI / 2]}
          >
            <cylinderGeometry args={[0.022, 0.022, cracWaterZone.pipeEndX - cracWaterZone.pipeStartX, 10]} />
            <meshStandardMaterial color="#64748b" roughness={0.4} metalness={0.6} />
          </mesh>

          {/* Per-CRAC Vertical Supply/Return Branches + Isolation Valve Handwheels */}
          {perimeterCracs.map((crac, i) => (
            <group key={`chw-drop-${i}`}>
              <mesh position={[crac.position[0] - 0.16, 0.42, cracWaterZone.pipeHeaderZ + 0.1]}>
                <boxGeometry args={[0.055, 0.44, 0.2]} />
                <meshStandardMaterial color="#0284c7" roughness={0.38} metalness={0.4} />
              </mesh>
              <mesh position={[crac.position[0] + 0.16, 0.52, cracWaterZone.pipeHeaderZ + 0.1]}>
                <boxGeometry args={[0.055, 0.44, 0.2]} />
                <meshStandardMaterial color="#ea580c" roughness={0.38} metalness={0.4} />
              </mesh>
              {/* Metallic butterfly isolation valve handwheels */}
              <mesh position={[crac.position[0] - 0.16, 0.56, cracWaterZone.pipeHeaderZ - 0.04]} rotation={[Math.PI / 2, 0, 0]}>
                <cylinderGeometry args={[0.045, 0.045, 0.02, 12]} />
                <meshStandardMaterial color="#ef4444" roughness={0.3} metalness={0.65} />
              </mesh>
              <mesh position={[crac.position[0] + 0.16, 0.66, cracWaterZone.pipeHeaderZ - 0.04]} rotation={[Math.PI / 2, 0, 0]}>
                <cylinderGeometry args={[0.045, 0.045, 0.02, 12]} />
                <meshStandardMaterial color="#ef4444" roughness={0.3} metalness={0.65} />
              </mesh>
            </group>
          ))}
        </group>
      )}

      {/* ==================== C. EQUIPOTENTIAL GROUNDING BUSBAR & MEB BOX ==================== */}
      <group>
        {/* Back wall perimeter copper grounding busbar (Y=0.06m) */}
        <mesh position={[centerX, 0.06, wallBackZ + 0.04]}>
          <boxGeometry args={[Math.max(2, room.bounds.width - 0.6), 0.04, 0.018]} />
          <meshStandardMaterial color="#d97706" roughness={0.28} metalness={0.88} />
        </mesh>
        {/* Left wall copper grounding busbar (Y=0.06m) */}
        <mesh position={[wallLeftX + 0.04, 0.06, room.bounds.centerZ]}>
          <boxGeometry args={[0.018, 0.04, Math.max(2, room.bounds.depth - 0.6)]} />
          <meshStandardMaterial color="#d97706" roughness={0.28} metalness={0.88} />
        </mesh>
        {/* MEB Equipotential Grounding Terminal Box on Left Wall near Power Bank */}
        <group position={[wallLeftX, 0.58, minZ + 1.45]} rotation={[0, Math.PI / 2, 0]}>
          <mesh>
            <boxGeometry args={[0.3, 0.22, 0.08]} />
            <meshStandardMaterial color="#1e293b" roughness={0.36} metalness={0.65} />
          </mesh>
          <mesh position={[0, 0, 0.042]}>
            <planeGeometry args={[0.28, 0.2]} />
            <meshBasicMaterial map={mebTex} toneMapped={false} />
          </mesh>
        </group>
      </group>
    </group>
  );
};
