import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { RackSummary } from '../types';
import { RoomRenderBudget } from './gpuProfile';
import { OdfCabinetUnit } from './OdfCabinetUnit';
import { KebosUpsCabinetUnit } from './KebosUpsUnit';
import { DataCenterMepFireLayer } from './DataCenterMepFireLayer';
import { ImportedGlbAsset } from './roomSerialization';
import {
  computeRackPowerMetrics,
  computeRackThermalMetrics,
  DataCenterEquipmentPlacement,
  DataCenterRoomModel,
  DataCenterTraySegment,
  DataCenterZoneModel,
  RackFleetPlacement,
} from './fleetLayout';

export { computeRackPowerMetrics, computeRackThermalMetrics };
export type RoomAnalysisMode = 'physical' | 'power' | 'thermal';
export type RoomCameraPreset =
  | 'overview'
  | 'aisle'
  | 'trays'
  | 'section'
  | 'cooling'
  | 'odf_inside'
  | 'zone'
  | 'reset';

export interface InterRackLink {
  id: string;
  sourceRackId: string;
  targetRackId: string;
  linkCount: number;
  label: string;
}

export interface RoomLayerVisibility {
  trays: boolean;
  cooling: boolean;
  odf: boolean;
  containment: boolean;
  airflow: boolean;
  architecture: boolean;
  fireMep: boolean;
}

// ---------------------------------------------------------------------------
// Procedural Data Center Textures (offline, cached once, zero network dependency)
// ---------------------------------------------------------------------------
let raisedFloorTexCache: THREE.CanvasTexture | null = null;
let perforatedTileTexCache: THREE.CanvasTexture | null = null;
let standardRackFacadeCache: THREE.CanvasTexture | null = null;
let chassisCoreFacadeCache: THREE.CanvasTexture | null = null;
let serverRackFacadeCache: THREE.CanvasTexture | null = null;
const hmiTexCache = new Map<string, THREE.CanvasTexture>();
const zoneFloorTexCache = new Map<string, THREE.CanvasTexture>();

function getRaisedFloorTexture(): THREE.CanvasTexture {
  if (raisedFloorTexCache) return raisedFloorTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#182230';
  ctx.fillRect(0, 0, 512, 512);

  ctx.fillStyle = 'rgba(148, 163, 184, 0.045)';
  for (let y = 0; y < 512; y += 8) {
    ctx.fillRect(0, y, 512, 2);
  }

  const tile = 256;
  for (let gx = 0; gx < 2; gx++) {
    for (let gy = 0; gy < 2; gy++) {
      const x = gx * tile;
      const y = gy * tile;
      const grad = ctx.createLinearGradient(x, y, x + tile, y + tile);
      grad.addColorStop(0, '#1e2a3a');
      grad.addColorStop(1, '#141c28');
      ctx.fillStyle = grad;
      ctx.fillRect(x + 3, y + 3, tile - 6, tile - 6);

      ctx.strokeStyle = '#0a0f18';
      ctx.lineWidth = 4;
      ctx.strokeRect(x + 2, y + 2, tile - 4, tile - 4);

      ctx.strokeStyle = 'rgba(56, 189, 248, 0.14)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x + 5, y + 5, tile - 10, tile - 10);

      ctx.fillStyle = '#334155';
      for (const cx of [x + 14, x + tile - 14]) {
        for (const cy of [y + 14, y + tile - 14]) {
          ctx.beginPath();
          ctx.arc(cx, cy, 3.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  raisedFloorTexCache = tex;
  return tex;
}

function getPerforatedColdTileTexture(): THREE.CanvasTexture {
  if (perforatedTileTexCache) return perforatedTileTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#192a3d';
  ctx.fillRect(0, 0, 256, 256);

  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 4;
  ctx.strokeRect(4, 4, 248, 248);

  ctx.fillStyle = '#060c14';
  for (let row = 0; row < 12; row++) {
    for (let col = 0; col < 10; col++) {
      ctx.fillRect(18 + col * 22, 18 + row * 19, 15, 11);
    }
  }
  ctx.fillStyle = 'rgba(56, 189, 248, 0.16)';
  ctx.fillRect(10, 10, 236, 236);

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  perforatedTileTexCache = tex;
  return tex;
}

/**
 * Baked 2D front elevation for Standard Network Switch Cabinets (LOD Level 1):
 * renders brushed-silver 1U switches, dark 2U firewall/AC shelves, active green
 * port LEDs, and side vertical cable managers with zero extra 3D polygons.
 */
function getStandardNetworkFacadeTexture(): THREE.CanvasTexture {
  if (standardRackFacadeCache) return standardRackFacadeCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 512;
  const ctx = canvas.getContext('2d')!;

  // Cabinet inner dark frame + side mounting rails
  ctx.fillStyle = '#0d1420';
  ctx.fillRect(0, 0, 256, 512);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, 16, 512);
  ctx.fillRect(240, 0, 16, 512);
  // Subtle rail U ticks
  ctx.fillStyle = '#475569';
  for (let y = 14; y < 500; y += 11) {
    ctx.fillRect(5, y, 5, 3);
    ctx.fillRect(246, y, 5, 3);
  }

  // Top perforated blanking bays (upper unoccupied U space)
  for (let y = 20; y < 290; y += 14) {
    ctx.fillStyle = '#131c2b';
    ctx.fillRect(20, y, 216, 10);
    ctx.fillStyle = 'rgba(148,163,184,0.14)';
    for (let x = 26; x < 230; x += 10) {
      ctx.fillRect(x, y + 3, 5, 4);
    }
  }

  // Lower active 1U silver H3C/Cisco/Huawei style switch stack (U4-U10 silhouette)
  for (let idx = 0; idx < 7; idx++) {
    const y = 300 + idx * 20;
    const isSilver = idx < 5;
    ctx.fillStyle = isSilver ? '#cbd5e1' : '#1f2937';
    ctx.fillRect(20, y, 216, 16);
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 1;
    ctx.strokeRect(20, y, 216, 16);
    // Left green SYS/PSU LEDs
    ctx.fillStyle = '#00e632';
    ctx.fillRect(26, y + 5, 4, 4);
    ctx.fillRect(33, y + 5, 4, 4);
    // Dense SFP/RJ45 port grid
    ctx.fillStyle = '#0b1120';
    for (let p = 0; p < 16; p++) {
      ctx.fillRect(46 + p * 9, y + 3, 6, 4);
      ctx.fillRect(46 + p * 9, y + 9, 6, 4);
    }
    // Right uplinks + yellow/cyan patch accents
    ctx.fillStyle = idx % 2 === 0 ? '#facc15' : '#22d3ee';
    ctx.fillRect(196, y + 4, 8, 8);
    ctx.fillStyle = '#00e632';
    ctx.fillRect(208, y + 5, 4, 4);
  }

  // Bottom 2U AC/Firewall appliance
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(20, 444, 216, 38);
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(28, 456, 34, 14);
  ctx.fillStyle = '#0f172a';
  for (let p = 0; p < 10; p++) {
    ctx.fillRect(74 + p * 14, 452, 10, 8);
    ctx.fillRect(74 + p * 14, 464, 10, 8);
  }
  ctx.fillStyle = '#00e632';
  ctx.fillRect(220, 456, 5, 5);

  // Outer door trim frame
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 506);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  standardRackFacadeCache = tex;
  return tex;
}

/**
 * Baked 2D front elevation for Carrier Modular Core Router/Switch Cabinets
 * (N610E / NE40E / S10500X / C9407R silhouette with top filter grill, high-density
 * vertical/horizontal line-card bays, MPU supervisors, and bottom fan/PSU shelves).
 */
function getChassisCoreFacadeTexture(): THREE.CanvasTexture {
  if (chassisCoreFacadeCache) return chassisCoreFacadeCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 512;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#101723';
  ctx.fillRect(0, 0, 256, 512);

  // Top exhaust / air-intake honeycomb crown (carrier style)
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(14, 14, 228, 72);
  ctx.fillStyle = '#090e17';
  for (let x = 22; x < 234; x += 14) {
    ctx.fillRect(x, 22, 8, 56);
  }
  // Carrier red/blue top accent brand band
  ctx.fillStyle = '#ef4444';
  ctx.fillRect(18, 90, 62, 5);
  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 14px monospace';
  ctx.fillText('CORE CHASSIS', 92, 97);

  // Upper vertical service line-card bay (silver anodized aluminum frontplates)
  ctx.fillStyle = '#d1d8e0';
  ctx.fillRect(18, 106, 220, 152);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2;
  for (let s = 0; s < 8; s++) {
    const sx = 22 + s * 27;
    ctx.fillStyle = s === 3 || s === 4 ? '#94a3b8' : '#e2e8f0';
    ctx.fillRect(sx, 110, 23, 144);
    ctx.strokeRect(sx, 110, 23, 144);
    ctx.fillStyle = '#00e632';
    ctx.fillRect(sx + 8, 116, 6, 4);
    ctx.fillStyle = '#0f172a';
    for (let py = 128; py < 240; py += 12) {
      ctx.fillRect(sx + 5, py, 13, 7);
    }
  }

  // Horizontal high-density QSFP28/SFP28 line-card shelves
  for (let row = 0; row < 6; row++) {
    const ry = 268 + row * 24;
    ctx.fillStyle = row % 2 === 0 ? '#cbd5e1' : '#b8c4d2';
    ctx.fillRect(18, ry, 220, 20);
    ctx.fillStyle = '#0f172a';
    for (let c = 0; c < 14; c++) {
      ctx.fillRect(34 + c * 13, ry + 5, 9, 10);
    }
    ctx.fillStyle = '#00e632';
    ctx.fillRect(22, ry + 7, 6, 5);
  }

  // Bottom modular PSU + fan tray bay
  ctx.fillStyle = '#1f2937';
  ctx.fillRect(18, 418, 220, 76);
  for (let p = 0; p < 4; p++) {
    const px = 24 + p * 53;
    ctx.fillStyle = '#334155';
    ctx.fillRect(px, 424, 47, 64);
    ctx.fillStyle = '#00e632';
    ctx.fillRect(px + 6, 430, 8, 5);
    ctx.fillStyle = p < 2 ? '#dc2626' : '#2563eb';
    ctx.fillRect(px + 6, 476, 35, 5);
  }

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 506);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  chassisCoreFacadeCache = tex;
  return tex;
}

/** Baked 2D front elevation for Compute / Server Cabinets (2U NVMe drive bay stacks). */
function getServerRackFacadeTexture(): THREE.CanvasTexture {
  if (serverRackFacadeCache) return serverRackFacadeCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 512;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#0c131f';
  ctx.fillRect(0, 0, 256, 512);

  for (let i = 0; i < 12; i++) {
    const y = 24 + i * 38;
    ctx.fillStyle = '#1a2332';
    ctx.fillRect(18, y, 220, 32);
    ctx.strokeStyle = '#334155';
    ctx.strokeRect(18, y, 220, 32);
    // 8 front drive caddies
    for (let d = 0; d < 8; d++) {
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(26 + d * 24, y + 5, 20, 22);
      ctx.fillStyle = d % 3 === 0 ? '#10b981' : '#38bdf8';
      ctx.fillRect(28 + d * 24, y + 7, 3, 4);
    }
    ctx.fillStyle = '#00e632';
    ctx.fillRect(222, y + 12, 6, 6);
  }

  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 506);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  serverRackFacadeCache = tex;
  return tex;
}

function getEquipmentHmiTexture(
  kind: 'crac' | 'pdf' | 'ups' | 'battery' | 'odf',
  title: string,
  metric: string,
): THREE.CanvasTexture {
  const key = `${kind}:${title}:${metric}`;
  if (hmiTexCache.has(key)) return hmiTexCache.get(key)!;
  const canvas = document.createElement('canvas');
  canvas.width = 320;
  canvas.height = 128;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = kind === 'odf' ? '#0b172a' : '#06111e';
  ctx.fillRect(0, 0, 320, 128);
  const accent =
    kind === 'crac' ? '#38bdf8'
      : kind === 'pdf' ? '#f59e0b'
      : kind === 'battery' ? '#fb923c'
      : kind === 'odf' ? '#facc15'
      : '#22c55e';
  ctx.strokeStyle = accent;
  ctx.lineWidth = 5;
  ctx.strokeRect(4, 4, 312, 120);

  ctx.fillStyle = accent;
  ctx.font = 'bold 24px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(title, 18, 44);

  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 26px monospace';
  ctx.fillText(metric, 18, 86);

  ctx.fillStyle = kind === 'odf' ? '#38bdf8' : '#22c55e';
  ctx.font = 'bold 14px system-ui, sans-serif';
  ctx.fillText(kind === 'odf' ? '● LC/UPC OPTICAL TRUNK' : '● AUTO NORMAL', 18, 114);

  const tex = new THREE.CanvasTexture(canvas);
  hmiTexCache.set(key, tex);
  return tex;
}

function getZoneFloorStencilTexture(label: string, sublabel: string, accentColor: string): THREE.CanvasTexture {
  const key = `${label}:${sublabel}:${accentColor}`;
  if (zoneFloorTexCache.has(key)) return zoneFloorTexCache.get(key)!;
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 96;
  const ctx = canvas.getContext('2d')!;

  ctx.clearRect(0, 0, 512, 96);
  ctx.fillStyle = 'rgba(8, 15, 28, 0.82)';
  ctx.fillRect(8, 10, 496, 76);
  ctx.strokeStyle = accentColor;
  ctx.lineWidth = 4;
  ctx.strokeRect(8, 10, 496, 76);

  ctx.fillStyle = accentColor;
  ctx.fillRect(8, 10, 14, 76);

  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 34px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(label, 36, 50);

  ctx.fillStyle = accentColor;
  ctx.font = 'bold 20px monospace';
  ctx.fillText(sublabel, 36, 76);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  zoneFloorTexCache.set(key, tex);
  return tex;
}

// ---------------------------------------------------------------------------
// Studio IBL Environment
// ---------------------------------------------------------------------------
export const RoomStudioEnvironment: React.FC = () => {
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
  return null;
};

// ---------------------------------------------------------------------------
// Smooth Camera Controller (Overview, Functional Zones, ODF Internal, Side Section, Click-to-Fly)
// ---------------------------------------------------------------------------
export const RoomCameraController: React.FC<{
  room: DataCenterRoomModel;
  preset: RoomCameraPreset;
  activeZoneId?: string | null;
  selectedOdfId?: string | null;
  presetNonce: number;
  selectedPlacement: RackFleetPlacement | null;
  controlsRef: React.RefObject<any>;
}> = ({ room, preset, activeZoneId, selectedOdfId, presetNonce, selectedPlacement, controlsRef }) => {
  const { camera } = useThree();
  const goalPos = useRef<THREE.Vector3 | null>(null);
  const goalTarget = useRef<THREE.Vector3 | null>(null);
  const animating = useRef(false);
  const lastFlownRackId = useRef<string | null>(selectedPlacement?.rack.id ?? null);

  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;
    const onStart = () => {
      animating.current = false;
    };
    ctrl.addEventListener('start', onStart);
    return () => ctrl.removeEventListener('start', onStart);
  }, [controlsRef]);

  useEffect(() => {
    const { centerX, centerZ, width, depth, maxX } = room.bounds;
    const span = Math.max(10, Math.max(width, depth));

    if (preset === 'zone' && activeZoneId) {
      const zone = room.zones.find(z => z.id === activeZoneId);
      if (zone) {
        const zSpan = Math.max(3.6, Math.max(zone.bounds.width, zone.bounds.depth));
        if (zone.kind === 'odf') {
          // Face the parallel ODF row straight from the 1.80m main service corridor (+Z)
          goalPos.current = new THREE.Vector3(zone.bounds.centerX + 0.55, 1.55, zone.bounds.maxZ + 2.45);
          goalTarget.current = new THREE.Vector3(zone.bounds.centerX, 1.08, zone.bounds.centerZ);
        } else if (zone.kind === 'power_cooling') {
          // Frame the parallel KEBOS UPS + CRAC-W row straight from the main service corridor (+Z)
          const upsMidX = room.upsUnits.length
            ? room.upsUnits.reduce((s, u) => s + u.position[0], 0) / room.upsUnits.length
            : zone.bounds.centerX;
          goalPos.current = new THREE.Vector3(upsMidX + 0.45, 1.52, zone.bounds.maxZ + 2.95);
          goalTarget.current = new THREE.Vector3(upsMidX + 0.2, 1.06, zone.bounds.centerZ);
        } else {
          goalPos.current = new THREE.Vector3(
            zone.bounds.centerX + zSpan * 0.42,
            Math.min(7.5, Math.max(2.6, zSpan * 0.42)),
            zone.bounds.maxZ + Math.max(3.2, zSpan * 0.65),
          );
          goalTarget.current = new THREE.Vector3(zone.bounds.centerX, 1.05, zone.bounds.centerZ);
        }
        animating.current = true;
        return;
      }
    }

    if (preset === 'odf_inside' && room.odfUnits.length > 0) {
      // Flattering 3/4 slightly-elevated close-up facing the front (+Z) of the selected ODF
      const odf = (selectedOdfId && room.odfUnits.find(u => u.id === selectedOdfId)) || room.odfUnits[0];
      goalPos.current = new THREE.Vector3(odf.position[0] + 0.55, 1.42, odf.position[2] + 1.78);
      goalTarget.current = new THREE.Vector3(odf.position[0], 1.1, odf.position[2]);
    } else if (preset === 'section') {
      // Side elevation cutaway showing raised floor, cabinet depth, A/B power ladder vs fiber tray elevation, and drops
      const refRow = room.rows[0];
      const refZ = refRow ? refRow.z : centerZ;
      goalPos.current = new THREE.Vector3(maxX + Math.max(3.6, width * 0.28), 1.85, refZ + 0.55);
      goalTarget.current = new THREE.Vector3(centerX, 1.55, refZ + 0.05);
    } else if (preset === 'aisle' && room.coldAisles.length > 0) {
      const firstAisle = room.coldAisles[0];
      goalPos.current = new THREE.Vector3(firstAisle.centerX - firstAisle.spanX / 2 - 2.2, 1.82, firstAisle.z + 0.35);
      goalTarget.current = new THREE.Vector3(firstAisle.centerX + 0.8, 1.15, firstAisle.z);
    } else if (preset === 'trays') {
      // Top-down overhead routing inspection view
      goalPos.current = new THREE.Vector3(centerX + span * 0.14, Math.min(20, Math.max(9.5, span * 0.85)), centerZ + span * 0.34);
      goalTarget.current = new THREE.Vector3(centerX, 2.35, centerZ);
    } else if (preset === 'cooling') {
      const crac = room.cracUnits[0];
      const tx = crac ? crac.position[0] : centerX + 2.5;
      const tz = crac ? crac.position[2] : centerZ;
      goalPos.current = new THREE.Vector3(tx + 4.8, 3.4, tz + 5.6);
      goalTarget.current = new THREE.Vector3(centerX + 0.8, 1.2, centerZ);
    } else {
      goalPos.current = new THREE.Vector3(
        centerX + Math.min(28, Math.max(7.6, span * 0.58)),
        Math.min(22, Math.max(6.0, span * 0.44)),
        centerZ + Math.min(34, Math.max(9.0, span * 0.68)),
      );
      goalTarget.current = new THREE.Vector3(centerX, 1.2, centerZ);
    }
    animating.current = true;
  }, [preset, activeZoneId, selectedOdfId, presetNonce, room.bounds.centerX, room.bounds.centerZ, room.bounds.width, room.bounds.depth, room.bounds.maxX]);

  useEffect(() => {
    const nextId = selectedPlacement?.rack.id ?? null;
    if (!nextId || nextId === lastFlownRackId.current) return;
    lastFlownRackId.current = nextId;
    const [rx, ry, rz] = selectedPlacement!.position;
    goalPos.current = new THREE.Vector3(rx + 2.6, ry + 1.75, rz + 4.4);
    goalTarget.current = new THREE.Vector3(rx, ry + 0.15, rz);
    animating.current = true;
  }, [selectedPlacement?.rack.id]);

  useFrame((_, delta) => {
    if (!animating.current || !goalPos.current || !goalTarget.current) return;
    const ctrl = controlsRef.current;
    const step = 1 - Math.exp(-5.8 * Math.min(delta, 0.05));
    camera.position.lerp(goalPos.current, step);
    if (ctrl) {
      ctrl.target.lerp(goalTarget.current, step);
      ctrl.update();
    }
    if (
      camera.position.distanceTo(goalPos.current) < 0.035
      && (!ctrl || ctrl.target.distanceTo(goalTarget.current) < 0.035)
    ) {
      animating.current = false;
    }
  });

  return null;
};

// ---------------------------------------------------------------------------
// 1. Raised Floor + Mode-Aware Cold-Aisle Grilles
// ---------------------------------------------------------------------------
const DataCenterFloor: React.FC<{ room: DataCenterRoomModel; analysisMode: RoomAnalysisMode }> = ({
  room,
  analysisMode,
}) => {
  const { width, depth, centerX, centerZ } = room.bounds;

  const floorTex = useMemo(() => {
    const base = getRaisedFloorTexture().clone();
    base.needsUpdate = true;
    base.repeat.set(Math.max(4, Math.round(width / 1.2)), Math.max(4, Math.round(depth / 1.2)));
    return base;
  }, [width, depth]);

  const perfTex = useMemo(() => getPerforatedColdTileTexture(), []);

  useEffect(() => () => floorTex.dispose(), [floorTex]);

  const isThermal = analysisMode === 'thermal';
  const isPower = analysisMode === 'power';

  return (
    <group>
      {/* Main 600x600mm anti-static raised floor */}
      <mesh position={[centerX, 0, centerZ]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[width, depth]} />
        <meshStandardMaterial
          map={floorTex}
          color={isPower ? '#94a3b8' : '#ffffff'}
          roughness={0.42}
          metalness={0.35}
        />
      </mesh>

      {/* Outer perimeter floor plinth lip */}
      <mesh position={[centerX, -0.06, centerZ]}>
        <boxGeometry args={[width + 0.3, 0.12, depth + 0.3]} />
        <meshStandardMaterial color="#0b111c" roughness={0.6} metalness={0.4} />
      </mesh>

      {/* Cold-aisle perforated air supply floor tiles (1.20m GB 50174-2017 cold aisle module) */}
      {room.coldAisles.map(aisle => {
        const stripW = aisle.spanX;
        return (
          <group key={`cold-floor-${aisle.id}`} position={[aisle.centerX, 0.008, aisle.z]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[stripW, aisle.width - 0.08]} />
              <meshStandardMaterial
                map={perfTex}
                roughness={0.35}
                metalness={0.55}
                emissive={isThermal ? '#0ea5e9' : '#0284c7'}
                emissiveIntensity={isThermal ? 0.78 : isPower ? 0.1 : 0.24}
              />
            </mesh>
            {/* Cyan cold-aisle floor guide borders */}
            <mesh position={[0, 0.004, aisle.width / 2 - 0.02]} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[stripW + 0.08, 0.036]} />
              <meshBasicMaterial color={isThermal ? '#38bdf8' : '#0ea5e9'} toneMapped={false} />
            </mesh>
            <mesh position={[0, 0.004, -aisle.width / 2 + 0.02]} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[stripW + 0.08, 0.036]} />
              <meshBasicMaterial color={isThermal ? '#38bdf8' : '#0ea5e9'} toneMapped={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
};

// ---------------------------------------------------------------------------
// 1b. Functional Zone Floor Demarcation & Stencil Signage (zero DOM overlap!)
// ---------------------------------------------------------------------------
const DataCenterZonesLayer: React.FC<{
  zones: DataCenterZoneModel[];
  activeZoneId?: string | null;
  zh: boolean;
}> = ({ zones, activeZoneId, zh }) => (
  <group>
    {zones.map(zone => {
      const { centerX, centerZ, width, depth, maxZ } = zone.bounds;
      const isFocused = activeZoneId === zone.id;
      const label = zh ? zone.labelZh : zone.labelEn;
      const sub = `${zone.labelEn.toUpperCase()} · ${zone.rackCount}${zh ? '柜/架' : ' UNITS'}`;
      const stencilTex = getZoneFloorStencilTexture(label, sub, zone.accentColor);
      const borderT = isFocused ? 0.055 : 0.032;
      const stencilW = Math.min(2.2, Math.max(1.25, width * 0.52));

      return (
        <group key={zone.id}>
          {/* Subtle floor zone tint wash */}
          <mesh position={[centerX, 0.004, centerZ]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[width, depth]} />
            <meshBasicMaterial
              color={zone.accentColor}
              transparent
              opacity={isFocused ? 0.14 : 0.05}
              depthWrite={false}
            />
          </mesh>

          {/* 4-sided painted floor boundary lines */}
          <mesh position={[centerX, 0.012, zone.bounds.minZ]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[width, borderT]} />
            <meshBasicMaterial color={zone.accentColor} transparent opacity={isFocused ? 0.95 : 0.55} toneMapped={false} />
          </mesh>
          <mesh position={[centerX, 0.012, maxZ]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[width, borderT]} />
            <meshBasicMaterial color={zone.accentColor} transparent opacity={isFocused ? 0.95 : 0.55} toneMapped={false} />
          </mesh>
          <mesh position={[zone.bounds.minX, 0.012, centerZ]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[borderT, depth]} />
            <meshBasicMaterial color={zone.accentColor} transparent opacity={isFocused ? 0.95 : 0.55} toneMapped={false} />
          </mesh>
          <mesh position={[zone.bounds.maxX, 0.012, centerZ]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[borderT, depth]} />
            <meshBasicMaterial color={zone.accentColor} transparent opacity={isFocused ? 0.95 : 0.55} toneMapped={false} />
          </mesh>

          {/* Native 3D floor stencil nameplate flush outside zone front edge */}
          <mesh position={[centerX, 0.014, maxZ + 0.24]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[stencilW, stencilW * (96 / 512)]} />
            <meshBasicMaterial map={stencilTex} transparent toneMapped={false} depthWrite={false} />
          </mesh>
        </group>
      );
    })}
  </group>
);

// ---------------------------------------------------------------------------
// 2. Architectural Hall Shell (Cutaway Walls, Columns, Ceiling Trusses, FM-200)
// ---------------------------------------------------------------------------
const DataCenterArchitecture: React.FC<{ room: DataCenterRoomModel }> = ({ room }) => {
  const { minX, minZ, width, depth, centerX, centerZ, ceilingY } = room.bounds;

  const columnXs = useMemo(() => {
    const count = Math.min(14, Math.max(3, Math.round(width / 4.5) + 1));
    return Array.from({ length: count }, (_, i) => minX + (i / (count - 1)) * width);
  }, [minX, width]);

  const columnZs = useMemo(() => {
    const count = Math.min(14, Math.max(3, Math.round(depth / 4.5) + 1));
    return Array.from({ length: count }, (_, i) => minZ + (i / (count - 1)) * depth);
  }, [minZ, depth]);

  return (
    <group>
      {/* Back acoustic steel + glass viewing wall (at minZ) */}
      <mesh position={[centerX, ceilingY / 2, minZ - 0.08]}>
        <boxGeometry args={[width + 0.2, ceilingY, 0.14]} />
        <meshStandardMaterial color="#121a28" roughness={0.55} metalness={0.45} />
      </mesh>
      <mesh position={[centerX, 0.14, minZ + 0.01]}>
        <boxGeometry args={[width, 0.05, 0.03]} />
        <meshBasicMaterial color="#0284c7" toneMapped={false} />
      </mesh>

      {/* Left power-corridor acoustic wall (at minX) */}
      <mesh position={[minX - 0.08, ceilingY / 2, centerZ]}>
        <boxGeometry args={[0.14, ceilingY, depth + 0.2]} />
        <meshStandardMaterial color="#101826" roughness={0.55} metalness={0.45} />
      </mesh>
      <mesh position={[minX + 0.01, 2.35, centerZ]}>
        <boxGeometry args={[0.04, 1.2, depth * 0.72]} />
        <meshStandardMaterial
          color="#38bdf8"
          transparent
          opacity={0.14}
          roughness={0.12}
          metalness={0.2}
        />
      </mesh>

      {/* Structural steel columns along back & left walls */}
      {columnXs.map((cx, i) => (
        <mesh key={`col-b-${i}`} position={[cx, ceilingY / 2, minZ + 0.05]}>
          <boxGeometry args={[0.24, ceilingY, 0.24]} />
          <meshStandardMaterial color="#263244" roughness={0.38} metalness={0.72} />
        </mesh>
      ))}
      {columnZs.map((cz, i) => (
        <mesh key={`col-l-${i}`} position={[minX + 0.05, ceilingY / 2, cz]}>
          <boxGeometry args={[0.24, ceilingY, 0.24]} />
          <meshStandardMaterial color="#263244" roughness={0.38} metalness={0.72} />
        </mesh>
      ))}

      {/* Overhead steel ceiling trusses & linear LED light bars */}
      {columnXs.slice(0, -1).map((cx, i) => {
        const nextX = columnXs[i + 1];
        const midX = (cx + nextX) / 2;
        return (
          <group key={`truss-${i}`} position={[midX, ceilingY - 0.12, centerZ]}>
            <mesh>
              <boxGeometry args={[0.12, 0.14, depth]} />
              <meshStandardMaterial color="#1e293b" roughness={0.45} metalness={0.7} />
            </mesh>
            <mesh position={[0, -0.09, 0]}>
              <boxGeometry args={[0.16, 0.03, depth * 0.76]} />
              <meshBasicMaterial color="#e0f2fe" toneMapped={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
};

// ---------------------------------------------------------------------------
// 3. Cold-Aisle Containment Canopy, Glass End-Doors & Illuminated Row Signage
// ---------------------------------------------------------------------------
const ColdAisleContainment: React.FC<{ room: DataCenterRoomModel }> = ({ room }) => (
  <group>
    {room.coldAisles.map(aisle => {
      const canopyW = aisle.spanX;
      const aisleZ = aisle.z;
      const aisleW = aisle.width;
      const canopyY = 2.02;
      return (
        <group key={`contain-${aisle.id}`}>
          <mesh position={[aisle.centerX, canopyY, aisleZ]}>
            <boxGeometry args={[canopyW, 0.03, aisleW]} />
            <meshStandardMaterial
              color="#7dd3fc"
              transparent
              opacity={0.18}
              roughness={0.12}
              metalness={0.3}
            />
          </mesh>
          {[-aisleW / 2, aisleW / 2].map(dz => (
            <mesh key={dz} position={[aisle.centerX, canopyY, aisleZ + dz]}>
              <boxGeometry args={[canopyW + 0.06, 0.055, 0.055]} />
              <meshStandardMaterial color="#64748b" roughness={0.32} metalness={0.82} />
            </mesh>
          ))}
          <mesh position={[aisle.centerX, canopyY - 0.025, aisleZ]}>
            <boxGeometry args={[canopyW - 0.25, 0.02, 0.06]} />
            <meshBasicMaterial color="#bae6fd" toneMapped={false} />
          </mesh>

          {[-1, 1].map(side => {
            const endX = aisle.centerX + side * (canopyW / 2);
            return (
              <group key={side} position={[endX, 0, aisleZ]}>
                {[-aisleW / 2 + 0.04, aisleW / 2 - 0.04].map(dz => (
                  <mesh key={dz} position={[0, canopyY / 2, dz]}>
                    <boxGeometry args={[0.055, canopyY, 0.055]} />
                    <meshStandardMaterial color="#334155" roughness={0.35} metalness={0.8} />
                  </mesh>
                ))}
                <mesh position={[0, canopyY - 0.02, 0]}>
                  <boxGeometry args={[0.075, 0.14, aisleW]} />
                  <meshStandardMaterial color="#1e293b" roughness={0.4} metalness={0.75} />
                </mesh>
                {[-0.34, 0.34].map(dz => (
                  <mesh key={dz} position={[0, 0.96, dz]}>
                    <boxGeometry args={[0.024, 1.9, 0.42]} />
                    <meshStandardMaterial
                      color="#38bdf8"
                      transparent
                      opacity={0.14}
                      roughness={0.1}
                      metalness={0.2}
                    />
                  </mesh>
                ))}
              </group>
            );
          })}

          <mesh position={[aisle.centerX, canopyY + 0.09, aisleZ + aisleW / 2 + 0.01]}>
            <planeGeometry args={[Math.min(1.6, canopyW * 0.65), 0.15]} />
            <meshBasicMaterial
              map={getEquipmentHmiTexture('crac', aisle.label, 'COLD AISLE 1.2m')}
              toneMapped={false}
            />
          </mesh>
        </group>
      );
    })}
  </group>
);

// ---------------------------------------------------------------------------
// 4. Dual-Layer Overhead Cable Trays + Instanced Curved Top Drops
//    All ladder rungs, hanger rods, waterfall drops & curved trunk whips are
//    GPU-instanced (5 draw calls total for up to 500 racks).
// ---------------------------------------------------------------------------
const TraySegmentMesh: React.FC<{
  segment: DataCenterTraySegment;
  analysisMode: RoomAnalysisMode;
}> = ({ segment, analysisMode }) => {
  const dx = segment.end[0] - segment.start[0];
  const dz = segment.end[2] - segment.start[2];
  const length = Math.max(0.2, Math.hypot(dx, dz));
  const midX = (segment.start[0] + segment.end[0]) / 2;
  const midY = (segment.start[1] + segment.end[1]) / 2;
  const midZ = (segment.start[2] + segment.end[2]) / 2;
  const angle = Math.atan2(dx, dz);
  const isFiber = segment.kind === 'fiber';
  const w = segment.width;
  const isPowerMode = analysisMode === 'power';

  return (
    <group position={[midX, midY, midZ]} rotation={[0, angle, 0]}>
      {isFiber ? (
        <>
          <mesh position={[0, -0.04, 0]}>
            <boxGeometry args={[w, 0.025, length]} />
            <meshStandardMaterial
              color="#eab308"
              roughness={0.35}
              metalness={0.25}
              transparent={isPowerMode}
              opacity={isPowerMode ? 0.26 : 1}
            />
          </mesh>
          {[-w / 2, w / 2].map(sx => (
            <mesh key={sx} position={[sx, 0.01, 0]}>
              <boxGeometry args={[0.024, 0.11, length]} />
              <meshStandardMaterial
                color="#facc15"
                roughness={0.32}
                metalness={0.28}
                transparent={isPowerMode}
                opacity={isPowerMode ? 0.26 : 1}
              />
            </mesh>
          ))}
          <mesh position={[-w * 0.18, -0.008, 0]}>
            <boxGeometry args={[0.055, 0.036, length - 0.08]} />
            <meshStandardMaterial
              color="#06b6d4"
              emissive="#0891b2"
              emissiveIntensity={isPowerMode ? 0.05 : 0.3}
              roughness={0.35}
              transparent={isPowerMode}
              opacity={isPowerMode ? 0.25 : 1}
            />
          </mesh>
          <mesh position={[w * 0.16, -0.01, 0]}>
            <boxGeometry args={[0.048, 0.032, length - 0.08]} />
            <meshStandardMaterial
              color="#fde047"
              emissive="#ca8a04"
              emissiveIntensity={isPowerMode ? 0.04 : 0.24}
              roughness={0.35}
              transparent={isPowerMode}
              opacity={isPowerMode ? 0.25 : 1}
            />
          </mesh>
        </>
      ) : (
        <>
          {[-w / 2, w / 2].map(sx => (
            <mesh key={sx} position={[sx, 0, 0]}>
              <boxGeometry args={[0.026, 0.08, length]} />
              <meshStandardMaterial color="#94a3b8" roughness={0.32} metalness={0.85} />
            </mesh>
          ))}
          {/* Dual A/B Heavy Power Busway Feeds (glow vividly in Power Analysis Mode!) */}
          <mesh position={[-w * 0.22, 0.006, 0]}>
            <boxGeometry args={[0.052, 0.044, length - 0.06]} />
            <meshStandardMaterial
              color="#ef4444"
              emissive={isPowerMode ? '#ef4444' : '#7f1d1d'}
              emissiveIntensity={isPowerMode ? 1.55 : 0.18}
              toneMapped={!isPowerMode}
              roughness={0.36}
              metalness={0.45}
            />
          </mesh>
          <mesh position={[w * 0.22, 0.006, 0]}>
            <boxGeometry args={[0.052, 0.044, length - 0.06]} />
            <meshStandardMaterial
              color="#3b82f6"
              emissive={isPowerMode ? '#3b82f6' : '#1e3a8a'}
              emissiveIntensity={isPowerMode ? 1.55 : 0.18}
              toneMapped={!isPowerMode}
              roughness={0.36}
              metalness={0.45}
            />
          </mesh>
        </>
      )}
    </group>
  );
};

interface InstancedTransform {
  x: number;
  y: number;
  z: number;
  rotY: number;
  sx: number;
  sy: number;
  sz: number;
}

const OverheadCableTrays: React.FC<{
  room: DataCenterRoomModel;
  placements: RackFleetPlacement[];
  analysisMode: RoomAnalysisMode;
}> = ({ room, placements, analysisMode }) => {
  const fiberDropRef = useRef<THREE.InstancedMesh>(null);
  const curvedBundleRef = useRef<THREE.InstancedMesh>(null);
  const powerDropRef = useRef<THREE.InstancedMesh>(null);
  const rungRef = useRef<THREE.InstancedMesh>(null);
  const hangerRef = useRef<THREE.InstancedMesh>(null);

  // Shared curved trunk cable whip geometry arching gracefully from fiber tray into rack roof
  const curvedDropGeo = useMemo(() => {
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.0, 0.74, 0.0),
      new THREE.Vector3(0.06, 0.56, 0.06),
      new THREE.Vector3(0.04, 0.28, 0.03),
      new THREE.Vector3(0.0, 0.0, 0.0),
    ]);
    return new THREE.TubeGeometry(curve, 12, 0.022, 6, false);
  }, []);

  useEffect(() => () => curvedDropGeo.dispose(), [curvedDropGeo]);

  const { rungs, hangers } = useMemo(() => {
    const rungItems: InstancedTransform[] = [];
    const hangerItems: InstancedTransform[] = [];
    const ceilingY = room.bounds.ceilingY;

    room.trays.forEach(segment => {
      const dx = segment.end[0] - segment.start[0];
      const dz = segment.end[2] - segment.start[2];
      const length = Math.max(0.2, Math.hypot(dx, dz));
      const midX = (segment.start[0] + segment.end[0]) / 2;
      const midY = (segment.start[1] + segment.end[1]) / 2;
      const midZ = (segment.start[2] + segment.end[2]) / 2;
      const angle = Math.atan2(dx, dz);
      const sinA = Math.sin(angle);
      const cosA = Math.cos(angle);
      const w = segment.width;

      if (segment.kind !== 'fiber') {
        const rungCount = Math.min(36, Math.max(3, Math.floor(length / 0.48)));
        for (let i = 0; i < rungCount; i++) {
          const localZ = -length / 2 + ((i + 0.5) / rungCount) * length;
          rungItems.push({
            x: midX + localZ * sinA,
            y: midY - 0.028,
            z: midZ + localZ * cosA,
            rotY: angle,
            sx: w,
            sy: 0.016,
            sz: 0.025,
          });
        }
      }

      const hangerCount = Math.min(6, Math.max(2, Math.floor(length / 2.8) + 1));
      const rodH = Math.max(0.2, ceilingY - midY);
      for (let i = 0; i < hangerCount; i++) {
        const localZ = -length / 2 + (hangerCount === 1 ? 0.5 : i / (hangerCount - 1)) * length;
        for (const side of [-1, 1]) {
          const localX = side * (w / 2 + 0.01);
          hangerItems.push({
            x: midX + localX * cosA + localZ * sinA,
            y: midY + rodH / 2,
            z: midZ - localX * sinA + localZ * cosA,
            rotY: 0,
            sx: 0.016,
            sy: rodH,
            sz: 0.016,
          });
        }
      }
    });
    return { rungs: rungItems, hangers: hangerItems };
  }, [room.trays, room.bounds.ceilingY]);

  useEffect(() => {
    const fd = fiberDropRef.current;
    const cb = curvedBundleRef.current;
    const pd = powerDropRef.current;
    const dummy = new THREE.Object3D();

    if (fd && cb && pd) {
      placements.forEach((p, i) => {
        const [x, , z] = p.position;
        const dir = p.facing ?? 1;
        // Yellow waterfall spout right below front fiber raceway
        dummy.position.set(x + dir * 0.14, 2.55, z + dir * 0.24);
        dummy.rotation.set(0, dir === -1 ? Math.PI : 0, 0);
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        fd.setMatrixAt(i, dummy.matrix);

        // Smooth curved optical cable bundle arching from waterfall into cabinet roof entry (Y=2.0m)
        dummy.position.set(x + dir * 0.14, 1.98, z + dir * 0.24);
        dummy.updateMatrix();
        cb.setMatrixAt(i, dummy.matrix);

        // Rear power tap-off box + conduit descending from Y=2.34m to rack roof Y=2.0m
        dummy.position.set(x - dir * 0.18, 2.16, z - dir * 0.24);
        dummy.updateMatrix();
        pd.setMatrixAt(i, dummy.matrix);
      });
      fd.instanceMatrix.needsUpdate = true;
      cb.instanceMatrix.needsUpdate = true;
      pd.instanceMatrix.needsUpdate = true;
    }

    const rm = rungRef.current;
    if (rm) {
      rungs.forEach((item, i) => {
        dummy.position.set(item.x, item.y, item.z);
        dummy.rotation.set(0, item.rotY, 0);
        dummy.scale.set(item.sx, item.sy, item.sz);
        dummy.updateMatrix();
        rm.setMatrixAt(i, dummy.matrix);
      });
      rm.instanceMatrix.needsUpdate = true;
    }

    const hm = hangerRef.current;
    if (hm) {
      hangers.forEach((item, i) => {
        dummy.position.set(item.x, item.y, item.z);
        dummy.rotation.set(0, item.rotY, 0);
        dummy.scale.set(item.sx, item.sy, item.sz);
        dummy.updateMatrix();
        hm.setMatrixAt(i, dummy.matrix);
      });
      hm.instanceMatrix.needsUpdate = true;
    }
  }, [placements, rungs, hangers]);

  const isPowerMode = analysisMode === 'power';

  return (
    <group>
      {room.trays.map(seg => (
        <TraySegmentMesh key={seg.id} segment={seg} analysisMode={analysisMode} />
      ))}

      {/* Instanced yellow fiber waterfall spouts */}
      <instancedMesh ref={fiberDropRef} args={[undefined, undefined, Math.max(1, placements.length)]}>
        <boxGeometry args={[0.18, 0.22, 0.12]} />
        <meshStandardMaterial
          color="#facc15"
          roughness={0.32}
          metalness={0.28}
          transparent={isPowerMode}
          opacity={isPowerMode ? 0.28 : 1}
        />
      </instancedMesh>

      {/* Instanced smooth curved trunk whips arching into cabinet tops */}
      <instancedMesh ref={curvedBundleRef} args={[curvedDropGeo, undefined, Math.max(1, placements.length)]}>
        <meshStandardMaterial
          color="#06b6d4"
          emissive="#0891b2"
          emissiveIntensity={isPowerMode ? 0.05 : 0.32}
          roughness={0.38}
          transparent={isPowerMode}
          opacity={isPowerMode ? 0.24 : 1}
        />
      </instancedMesh>

      {/* Instanced A/B power busway drop tap-off whips */}
      <instancedMesh ref={powerDropRef} args={[undefined, undefined, Math.max(1, placements.length)]}>
        <boxGeometry args={[0.14, 0.44, 0.1]} />
        <meshStandardMaterial
          color={isPowerMode ? '#f59e0b' : '#475569'}
          emissive={isPowerMode ? '#d97706' : '#000000'}
          emissiveIntensity={isPowerMode ? 1.1 : 0}
          roughness={0.35}
          metalness={0.75}
        />
      </instancedMesh>

      {rungs.length > 0 && (
        <instancedMesh ref={rungRef} args={[undefined, undefined, rungs.length]}>
          <boxGeometry args={[1, 1, 1]} />
          <meshStandardMaterial color="#64748b" roughness={0.35} metalness={0.82} />
        </instancedMesh>
      )}

      {hangers.length > 0 && (
        <instancedMesh ref={hangerRef} args={[undefined, undefined, hangers.length]}>
          <boxGeometry args={[1, 1, 1]} />
          <meshStandardMaterial color="#64748b" roughness={0.35} metalness={0.85} />
        </instancedMesh>
      )}

      {/* PDF Column-Head A/B Vertical Power Risers (Y=2.00m roof -> Y=2.34m overhead power ladder) */}
      {room.pdfCabinets.map(pdf => {
        const dir = Math.abs(pdf.rotationY) > Math.PI / 2 ? -1 : 1;
        const riserZ = pdf.position[2] - dir * 0.24;
        return (
          <group key={`pdf-riser-${pdf.id}`} position={[pdf.position[0], 2.17, riserZ]}>
            <mesh>
              <boxGeometry args={[0.3, 0.34, 0.14]} />
              <meshStandardMaterial color="#475569" roughness={0.35} metalness={0.78} />
            </mesh>
            <mesh position={[-0.07, 0, 0.072]}>
              <boxGeometry args={[0.05, 0.34, 0.025]} />
              <meshBasicMaterial color={isPowerMode ? '#ef4444' : '#dc2626'} toneMapped={!isPowerMode} />
            </mesh>
            <mesh position={[0.07, 0, 0.072]}>
              <boxGeometry args={[0.05, 0.34, 0.025]} />
              <meshBasicMaterial color={isPowerMode ? '#3b82f6' : '#2563eb'} toneMapped={!isPowerMode} />
            </mesh>
          </group>
        );
      })}

      {/* DC Busway Bridges connecting KEBOS Battery Banks -> nearest KEBOS UPS Cabinet (Y=2.18m) */}
      {room.batteryUnits.map(batt => {
        if (!room.upsUnits.length) return null;
        const pairedUps = room.upsUnits.reduce((best, cand) =>
          Math.abs(cand.position[0] - batt.position[0]) < Math.abs(best.position[0] - batt.position[0])
            ? cand
            : best,
        );
        const midX = (batt.position[0] + pairedUps.position[0]) / 2;
        const spanX = Math.max(0.4, Math.abs(pairedUps.position[0] - batt.position[0]));
        const bridgeZ = batt.position[2] - 0.12;
        return (
          <group key={`dc-bridge-${batt.id}`} position={[midX, 2.18, bridgeZ]}>
            <mesh>
              <boxGeometry args={[spanX, 0.07, 0.14]} />
              <meshStandardMaterial color="#334155" roughness={0.38} metalness={0.76} />
            </mesh>
            <mesh position={[0, 0.04, 0]}>
              <boxGeometry args={[spanX - 0.06, 0.018, 0.05]} />
              <meshBasicMaterial color="#fb923c" toneMapped={!isPowerMode} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
};

// 5. Dedicated Carrier 576-Core ODF Optical Distribution Frame lives in ./OdfCabinetUnit.tsx

// ---------------------------------------------------------------------------
// 6. Precision CRAC Air Conditioners, PDF Power Cabinets & UPS Units
// ---------------------------------------------------------------------------
const InfraCabinetUnit: React.FC<{
  item: DataCenterEquipmentPlacement;
  showLabel: boolean;
  analysisMode: RoomAnalysisMode;
}> = ({ item, showLabel, analysisMode }) => {
  const hmiTex = useMemo(
    () => getEquipmentHmiTexture(item.kind, item.label, item.sublabel),
    [item.kind, item.label, item.sublabel],
  );
  const { width: w, height: h, depth: d } = item;
  const isInRowCrac = item.kind === 'crac' && item.cracRole === 'inrow';
  const isBattery = item.kind === 'battery';
  const bodyColor =
    item.kind === 'crac' ? '#cbd5e1'
      : item.kind === 'pdf' ? '#1e293b'
      : isBattery ? '#26292e'
      : '#182230';
  const accentColor =
    item.kind === 'crac' ? '#0ea5e9'
      : item.kind === 'pdf' ? '#f59e0b'
      : isBattery ? '#fb923c'
      : '#22c55e';
  const highlightPower = analysisMode === 'power' && (item.kind === 'pdf' || item.kind === 'ups' || isBattery);
  const highlightCooling = analysisMode === 'thermal' && item.kind === 'crac';

  return (
    <group position={item.position} rotation={[0, item.rotationY, 0]}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={bodyColor}
          emissive={highlightPower ? '#92400e' : highlightCooling ? '#0369a1' : '#000000'}
          emissiveIntensity={highlightPower || highlightCooling ? 0.35 : 0}
          roughness={isBattery ? 0.44 : 0.36}
          metalness={0.62}
        />
      </mesh>
      <mesh position={[0, h / 2 - 0.05, d / 2 + 0.012]}>
        <boxGeometry args={[w - 0.08, 0.045, 0.02]} />
        <meshBasicMaterial color={accentColor} toneMapped={false} />
      </mesh>
      <mesh position={[0, h * 0.22, d / 2 + 0.01]}>
        <planeGeometry args={[w * 0.66, 0.24]} />
        <meshBasicMaterial map={hmiTex} toneMapped={false} />
      </mesh>

      {item.kind === 'crac' && (
        <>
          {(isInRowCrac ? [0.02, -0.16, -0.34, -0.52, -0.7] : [-0.22, -0.38, -0.54, -0.7]).map((ly, i) => (
            <mesh key={i} position={[0, ly, d / 2 + 0.008]}>
              <boxGeometry args={[w * 0.8, 0.09, 0.02]} />
              <meshStandardMaterial color="#1e293b" roughness={0.5} metalness={0.65} />
            </mesh>
          ))}
          {isInRowCrac ? (
            /* Flush 2.00m flat-top In-Row CRAC: clears Y=2.34m overhead power ladder cleanly (0.34m gap) */
            <mesh position={[0, h / 2 - 0.015, 0]}>
              <boxGeometry args={[w * 0.9, 0.03, d * 0.86]} />
              <meshStandardMaterial color="#94a3b8" roughness={0.35} metalness={0.72} />
            </mesh>
          ) : (
            /* Perimeter Downflow CRAC-W: low-profile top return-air plenum + base supply grille */
            <>
              <mesh position={[0, h / 2 + 0.08, 0]}>
                <boxGeometry args={[w * 0.92, 0.16, d * 0.88]} />
                <meshStandardMaterial color="#94a3b8" roughness={0.35} metalness={0.72} />
              </mesh>
              <mesh position={[0, h / 2 + 0.08, d * 0.45]}>
                <boxGeometry args={[w * 0.78, 0.1, 0.03]} />
                <meshStandardMaterial
                  color="#0c4a6e"
                  emissive="#0ea5e9"
                  emissiveIntensity={highlightCooling ? 1.15 : 0.35}
                  roughness={0.4}
                />
              </mesh>
            </>
          )}
        </>
      )}

      {isBattery && (
        <>
          {/* 4-tier ventilated VRLA battery tray bays + DC circuit breaker */}
          {[-0.08, -0.3, -0.52, -0.74].map((ly, i) => (
            <mesh key={i} position={[0, ly, d / 2 + 0.009]}>
              <boxGeometry args={[w * 0.82, 0.15, 0.02]} />
              <meshStandardMaterial color="#111419" roughness={0.48} metalness={0.55} />
            </mesh>
          ))}
          {/* DC 480V main breaker switch handle */}
          <mesh position={[-w * 0.24, h * 0.04, d / 2 + 0.016]}>
            <boxGeometry args={[0.11, 0.06, 0.025]} />
            <meshStandardMaterial color="#ea580c" roughness={0.35} metalness={0.45} />
          </mesh>
          {/* Top DC bus conduit stub climbing to Y=2.18m DC bridge */}
          <mesh position={[0, h / 2 + 0.06, -0.12]}>
            <cylinderGeometry args={[0.028, 0.028, 0.12, 10]} />
            <meshStandardMaterial color="#f97316" roughness={0.4} metalness={0.55} />
          </mesh>
        </>
      )}

      {item.kind === 'pdf' && (
        <>
          <mesh position={[-w * 0.22, -0.25, d / 2 + 0.012]}>
            <boxGeometry args={[w * 0.28, 0.9, 0.025]} />
            <meshStandardMaterial
              color="#991b1b"
              emissive={highlightPower ? '#ef4444' : '#000000'}
              emissiveIntensity={highlightPower ? 0.6 : 0}
              roughness={0.4}
              metalness={0.5}
            />
          </mesh>
          <mesh position={[w * 0.22, -0.25, d / 2 + 0.012]}>
            <boxGeometry args={[w * 0.28, 0.9, 0.025]} />
            <meshStandardMaterial
              color="#1d4ed8"
              emissive={highlightPower ? '#3b82f6' : '#000000'}
              emissiveIntensity={highlightPower ? 0.6 : 0}
              roughness={0.4}
              metalness={0.5}
            />
          </mesh>
          <mesh position={[-w * 0.22, 0.02, d / 2 + 0.026]}>
            <boxGeometry args={[0.1, 0.03, 0.01]} />
            <meshBasicMaterial color="#ef4444" toneMapped={false} />
          </mesh>
          <mesh position={[w * 0.22, 0.02, d / 2 + 0.026]}>
            <boxGeometry args={[0.1, 0.03, 0.01]} />
            <meshBasicMaterial color="#3b82f6" toneMapped={false} />
          </mesh>
        </>
      )}

      {item.kind === 'ups' && (
        <>
          {[-0.1, -0.35, -0.6].map((ly, i) => (
            <mesh key={i} position={[0, ly, d / 2 + 0.01]}>
              <boxGeometry args={[w * 0.82, 0.16, 0.02]} />
              <meshStandardMaterial color="#0f172a" roughness={0.45} metalness={0.6} />
            </mesh>
          ))}
        </>
      )}

      {showLabel && (
        <Html position={[0, h / 2 + (item.kind === 'crac' && !isInRowCrac ? 0.32 : 0.18), 0]} center>
          <div className="pointer-events-none whitespace-nowrap rounded border border-slate-700/80 bg-slate-950/92 px-1.5 py-0.5 text-[9px] font-semibold tracking-tight text-slate-200 shadow">
            <span style={{ color: accentColor }}>●</span> {item.label}
          </div>
        </Html>
      )}
    </group>
  );
};

// ---------------------------------------------------------------------------
// 7. Animated Cold Supply / Hot Exhaust Airflow Particles (Throttled for iGPU)
// ---------------------------------------------------------------------------
interface AirflowParticle {
  origin: THREE.Vector3;
  dir: THREE.Vector3;
  travel: number;
  speed: number;
  phase: number;
  isHot: boolean;
}

const DataCenterAirflowStreams: React.FC<{
  room: DataCenterRoomModel;
  placements: RackFleetPlacement[];
  budget?: RoomRenderBudget;
}> = ({ room, placements, budget }) => {
  const coldMeshRef = useRef<THREE.InstancedMesh>(null);
  const hotMeshRef = useRef<THREE.InstancedMesh>(null);
  const lastTickRef = useRef(0);
  const minInterval = 1 / Math.max(10, budget?.airflowFps ?? 24);
  const maxRacks = budget?.maxAirflowRacks ?? 24;
  const particlesPerRack = budget?.airflowParticlesPerRack ?? 2;

  const { coldParticles, hotParticles } = useMemo(() => {
    const cold: AirflowParticle[] = [];
    const hot: AirflowParticle[] = [];

    const sampledRacks = placements.slice(0, maxRacks);
    sampledRacks.forEach((p, idx) => {
      const [rx, , rz] = p.position;
      const dir = p.facing ?? 1;
      const isPowered = (p.rack.power_used_watts || 0) > 0;
      for (let k = 0; k < particlesPerRack; k++) {
        const offsetX = particlesPerRack === 1 ? 0 : (k - (particlesPerRack - 1) / 2) * 0.26;
        cold.push({
          origin: new THREE.Vector3(rx + offsetX, 0.12, rz + dir * 1.08),
          dir: new THREE.Vector3(0, 0.62, -dir * 0.58).normalize(),
          travel: 1.45,
          speed: 0.72 + (idx % 3) * 0.12,
          phase: (idx * 0.31 + k * 0.33) % 1,
          isHot: false,
        });
        if (isPowered || sampledRacks.length <= 2) {
          hot.push({
            origin: new THREE.Vector3(rx + offsetX, 0.55 + k * 0.35, rz - dir * 0.55),
            dir: new THREE.Vector3(0, 0.85, -dir * 0.45).normalize(),
            travel: 1.65,
            speed: 0.68 + (idx % 4) * 0.1,
            phase: (idx * 0.27 + k * 0.37) % 1,
            isHot: true,
          });
        }
      }
    });

    room.cracUnits.slice(0, budget?.mode === 'eco' ? 6 : 10).forEach((crac, idx) => {
      const cracStreams = budget?.mode === 'eco' ? 2 : 4;
      if (crac.cracRole === 'inrow') {
        // Horizontal cold supply out of In-Row CRAC front louvers toward the paired cold aisle
        const cracDir = Math.abs(crac.rotationY) > Math.PI / 2 ? -1 : 1;
        for (let k = 0; k < cracStreams; k++) {
          const yOff = 0.62 + (k / Math.max(1, cracStreams - 1)) * 0.95;
          cold.push({
            origin: new THREE.Vector3(
              crac.position[0] - cracDir * (crac.width * 0.22),
              yOff,
              crac.position[2] + cracDir * (crac.depth / 2 + 0.08),
            ),
            dir: new THREE.Vector3(-cracDir * 0.12, -0.05, cracDir * 0.99).normalize(),
            travel: 1.2,
            speed: 0.92,
            phase: (idx * 0.2 + k * 0.25) % 1,
            isHot: false,
          });
        }
      } else {
        // Perimeter CRAC-W: under-floor cold plenum supply (+Z) + top warm air return intake
        for (let k = 0; k < cracStreams; k++) {
          const xOff = (k - (cracStreams - 1) / 2) * 0.24;
          cold.push({
            origin: new THREE.Vector3(crac.position[0] + xOff, 0.12, crac.position[2] + crac.depth / 2 + 0.08),
            dir: new THREE.Vector3(0, 0.02, 1).normalize(),
            travel: 1.85,
            speed: 0.95,
            phase: (idx * 0.2 + k * 0.25) % 1,
            isHot: false,
          });
          hot.push({
            origin: new THREE.Vector3(crac.position[0] + xOff, 2.78, crac.position[2] + 0.35),
            dir: new THREE.Vector3(0, -0.92, -0.38).normalize(),
            travel: 0.65,
            speed: 0.72,
            phase: (idx * 0.17 + k * 0.25) % 1,
            isHot: true,
          });
        }
      }
    });

    return { coldParticles: cold, hotParticles: hot };
  }, [room.cracUnits, placements, maxRacks, particlesPerRack, budget?.mode]);

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const pos = useMemo(() => new THREE.Vector3(), []);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (t - lastTickRef.current < minInterval) return;
    lastTickRef.current = t;
    const updateBatch = (mesh: THREE.InstancedMesh | null, list: AirflowParticle[]) => {
      if (!mesh) return;
      for (let i = 0; i < list.length; i++) {
        const pt = list[i];
        const frac = (t * pt.speed * 0.45 + pt.phase) % 1;
        pos.copy(pt.origin).addScaledVector(pt.dir, frac * pt.travel);
        const fade = Math.sin(frac * Math.PI);
        dummy.position.copy(pos);
        dummy.scale.set(0.06 * fade + 0.015, 0.06 * fade + 0.015, 0.28 * fade + 0.05);
        dummy.lookAt(pos.x + pt.dir.x, pos.y + pt.dir.y, pos.z + pt.dir.z);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
      mesh.instanceMatrix.needsUpdate = true;
    };
    updateBatch(coldMeshRef.current, coldParticles);
    updateBatch(hotMeshRef.current, hotParticles);
  });

  return (
    <group userData={{ excludeFromExport: true }}>
      <instancedMesh ref={coldMeshRef} args={[undefined, undefined, Math.max(1, coldParticles.length)]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial color="#38bdf8" transparent opacity={0.78} toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={hotMeshRef} args={[undefined, undefined, Math.max(1, hotParticles.length)]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial color="#fb7185" transparent opacity={0.74} toneMapped={false} />
      </instancedMesh>
    </group>
  );
};

// ---------------------------------------------------------------------------
// 8. Real Inter-Rack Overhead Fiber Trunk Cables (along Yellow Fiber Raceway)
// ---------------------------------------------------------------------------
const InterRackTrunkCables: React.FC<{
  links: InterRackLink[];
  placements: RackFleetPlacement[];
  selectedRackId: string;
}> = ({ links, placements, selectedRackId }) => {
  const placementMap = useMemo(() => {
    const m = new Map<string, RackFleetPlacement>();
    placements.forEach(p => m.set(p.rack.id, p));
    return m;
  }, [placements]);

  const curves = useMemo(() => {
    return links
      .map(link => {
        const src = placementMap.get(link.sourceRackId);
        const dst = placementMap.get(link.targetRackId);
        if (!src || !dst) return null;
        const [sx, , sz] = src.position;
        const [dx, , dz] = dst.position;
        const trayY = 2.7;
        const points = [
          new THREE.Vector3(sx + 0.14, 1.9, sz + 0.22),
          new THREE.Vector3(sx + 0.14, trayY, sz + 0.22),
          new THREE.Vector3((sx + dx) / 2, trayY + 0.06, (sz + dz) / 2 + 0.22),
          new THREE.Vector3(dx + 0.14, trayY, dz + 0.22),
          new THREE.Vector3(dx + 0.14, 1.9, dz + 0.22),
        ];
        const curve = new THREE.CatmullRomCurve3(points);
        const geo = new THREE.TubeGeometry(curve, 32, 0.028, 8, false);
        const highlighted = link.sourceRackId === selectedRackId || link.targetRackId === selectedRackId;
        return { link, geo, highlighted };
      })
      .filter(Boolean) as Array<{ link: InterRackLink; geo: THREE.TubeGeometry; highlighted: boolean }>;
  }, [links, placementMap, selectedRackId]);

  useEffect(() => () => curves.forEach(c => c.geo.dispose()), [curves]);

  return (
    <group>
      {curves.map(({ link, geo, highlighted }) => (
        <mesh key={link.id} geometry={geo}>
          <meshStandardMaterial
            color={highlighted ? '#22d3ee' : '#06b6d4'}
            emissive={highlighted ? '#06b6d4' : '#0e7490'}
            emissiveIntensity={highlighted ? 1.4 : 0.65}
            toneMapped={false}
          />
        </mesh>
      ))}
    </group>
  );
};

// ---------------------------------------------------------------------------
// 9. High-Craft Instanced 42U Cabinet Fleet (Multi-Archetype Facades + Real Power & Thermal Modes)
//    IMPORTANT: Never set `vertexColors` on InstancedMesh BoxGeometry (has no vertex color attr);
//    use `color="#ffffff"` so Three.js `setColorAt()` instanceColor renders vividly!
// ---------------------------------------------------------------------------
const physicalHealthAccent = (rack: RackSummary): string => {
  if (rack.data_quality_status === 'invalid') return '#ef4444';
  if (rack.health_status === 'offline') return '#f97316';
  if (rack.health_status === 'healthy') return '#10b981';
  if (rack.health_status === 'partial') return '#eab308';
  if (rack.health_status === 'empty') return '#475569';
  return '#64748b';
};

export const DataCenterRackFleet: React.FC<{
  placements: RackFleetPlacement[];
  selectedRackId: string;
  analysisMode: RoomAnalysisMode;
  maxHtmlLabels?: number;
  castShadow?: boolean;
  zh: boolean;
  onSelectRack: (rackId: string) => void;
  onOpenRack: (rackId: string) => void;
}> = ({
  placements,
  selectedRackId,
  analysisMode,
  maxHtmlLabels = 16,
  castShadow = false,
  zh,
  onSelectRack,
  onOpenRack,
}) => {
  const shellRef = useRef<THREE.InstancedMesh>(null);
  const standardDoorRef = useRef<THREE.InstancedMesh>(null);
  const coreDoorRef = useRef<THREE.InstancedMesh>(null);
  const serverDoorRef = useRef<THREE.InstancedMesh>(null);
  const fillRef = useRef<THREE.InstancedMesh>(null);
  const stripRef = useRef<THREE.InstancedMesh>(null);
  const heatPlumeRef = useRef<THREE.InstancedMesh>(null);
  const [hoveredRackId, setHoveredRackId] = useState<string | null>(null);

  const standardTex = useMemo(() => getStandardNetworkFacadeTexture(), []);
  const coreTex = useMemo(() => getChassisCoreFacadeTexture(), []);
  const serverTex = useMemo(() => getServerRackFacadeTexture(), []);

  useEffect(() => {
    const shell = shellRef.current;
    const stdDoor = standardDoorRef.current;
    const coreDoor = coreDoorRef.current;
    const srvDoor = serverDoorRef.current;
    const fill = fillRef.current;
    const strip = stripRef.current;
    const plume = heatPlumeRef.current;
    if (!shell || !stdDoor || !coreDoor || !srvDoor || !fill || !strip || !plume) return;

    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    const zeroMatrix = new THREE.Matrix4().makeScale(0, 0, 0);

    placements.forEach((placement, index) => {
      const [x, y, z] = placement.position;
      const dir = placement.facing ?? 1;
      const rotY = dir === -1 ? Math.PI : 0;
      const selected = placement.rack.id === selectedRackId;
      const power = computeRackPowerMetrics(placement.rack);
      const thermal = computeRackThermalMetrics(placement.rack);
      const uUtil = Math.max(0.06, Math.min(1, (placement.rack.used_u || 0) / Math.max(1, placement.rack.total_u || 42)));

      // 1. Cabinet outer shell body (unified 2.00m height datum, flush with PDF & In-Row CRAC)
      dummy.position.set(x, y, z);
      dummy.rotation.set(0, rotY, 0);
      dummy.scale.set(selected ? 1.02 : 1, 1, selected ? 1.02 : 1);
      dummy.updateMatrix();
      shell.setMatrixAt(index, dummy.matrix);

      if (analysisMode === 'thermal') {
        shell.setColorAt(index, color.set(thermal.color));
      } else if (analysisMode === 'power') {
        shell.setColorAt(index, color.set(selected ? '#38bdf8' : '#1e293b'));
      } else {
        shell.setColorAt(index, color.set(selected ? '#2e415c' : '#1e293b'));
      }

      // 2. Archetype-specific baked front elevation facade (respects GB 50174 face-to-face cold aisle facing!)
      dummy.position.set(x, y, z + dir * 0.486);
      dummy.rotation.set(0, rotY, 0);
      dummy.scale.set(selected ? 1.02 : 1, 1, 1);
      dummy.updateMatrix();
      stdDoor.setMatrixAt(index, placement.archetype === 'standard' || placement.archetype === 'odf' ? dummy.matrix : zeroMatrix);
      coreDoor.setMatrixAt(index, placement.archetype === 'chassis_core' ? dummy.matrix : zeroMatrix);
      srvDoor.setMatrixAt(index, placement.archetype === 'server' ? dummy.matrix : zeroMatrix);

      // 3. Mode-aware Fill Column
      if (analysisMode === 'power') {
        const loadFrac = power.watts > 0 ? Math.max(0.18, power.utilizationPct / 100) : 0.08;
        const barH = 1.8 * loadFrac;
        dummy.position.set(x, y - 0.92 + barH / 2, z);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(0.68, barH, 0.76);
        dummy.updateMatrix();
        fill.setMatrixAt(index, dummy.matrix);
        fill.setColorAt(index, color.set(power.color));
      } else if (analysisMode === 'physical') {
        const barH = 1.74 * uUtil;
        dummy.position.set(x + dir * 0.355, y - 0.88 + barH / 2, z + dir * 0.494);
        dummy.rotation.set(0, rotY, 0);
        dummy.scale.set(0.052, barH, 0.024);
        dummy.updateMatrix();
        fill.setMatrixAt(index, dummy.matrix);
        fill.setColorAt(index, color.set(selected ? '#22d3ee' : physicalHealthAccent(placement.rack)));
      } else {
        fill.setMatrixAt(index, zeroMatrix);
        fill.setColorAt(index, color.set('#000000'));
      }

      // 4. Top Crown LED Status Bar
      const crownColor =
        analysisMode === 'power'
          ? power.color
          : analysisMode === 'thermal'
            ? thermal.color
            : selected
              ? '#22d3ee'
              : physicalHealthAccent(placement.rack);
      dummy.position.set(x, y + 0.955, z + dir * 0.496);
      dummy.rotation.set(0, rotY, 0);
      dummy.scale.set(selected ? 1.02 : 1, 1, 1);
      dummy.updateMatrix();
      strip.setMatrixAt(index, dummy.matrix);
      strip.setColorAt(index, color.set(crownColor));

      // 5. Rear Hot-Aisle Volumetric Exhaust Heat Plume (Thermal mode only, powered racks only!)
      if (analysisMode === 'thermal' && thermal.watts > 0) {
        const plumeH = Math.min(2.1, 0.85 + (thermal.deltaT / 20) * 1.15);
        dummy.position.set(x, 0.25 + plumeH / 2, z - dir * 0.66);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(0.76, plumeH, 0.44);
        dummy.updateMatrix();
        plume.setMatrixAt(index, dummy.matrix);
        plume.setColorAt(index, color.set(thermal.color));
      } else {
        plume.setMatrixAt(index, zeroMatrix);
        plume.setColorAt(index, color.set('#000000'));
      }
    });

    for (const mesh of [shell, stdDoor, coreDoor, srvDoor, fill, strip, plume]) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  }, [placements, selectedRackId, analysisMode]);

  const selectedPlacement = placements.find(p => p.rack.id === selectedRackId) || null;
  const labeledPlacements = useMemo(() => {
    if (placements.length <= maxHtmlLabels) return placements;
    return placements.filter(p => p.rack.id === selectedRackId || p.rack.id === hoveredRackId);
  }, [placements, maxHtmlLabels, selectedRackId, hoveredRackId]);

  const isPower = analysisMode === 'power';
  const isThermal = analysisMode === 'thermal';

  return (
    <group>
      {/* 1. Cabinet Chassis Shells (color="#ffffff" + NO vertexColors => crisp instanceColor!) */}
      <instancedMesh
        ref={shellRef}
        args={[undefined, undefined, placements.length]}
        castShadow={castShadow && !isPower}
        receiveShadow={castShadow && !isPower}
        onPointerMove={(e: any) => {
          e.stopPropagation();
          const nextId = e.instanceId != null && placements[e.instanceId] ? placements[e.instanceId].rack.id : null;
          if (nextId !== hoveredRackId) setHoveredRackId(nextId);
        }}
        onPointerOut={() => {
          if (hoveredRackId !== null) setHoveredRackId(null);
        }}
        onClick={(e: any) => {
          e.stopPropagation();
          if (e.instanceId != null && placements[e.instanceId]) {
            onSelectRack(placements[e.instanceId].rack.id);
          }
        }}
        onDoubleClick={(e: any) => {
          e.stopPropagation();
          if (e.instanceId != null && placements[e.instanceId]) {
            onOpenRack(placements[e.instanceId].rack.id);
          }
        }}
      >
        <boxGeometry args={[0.82, 2.0, 0.96]} />
        {isThermal ? (
          <meshBasicMaterial color="#ffffff" transparent opacity={0.92} toneMapped={false} />
        ) : (
          <meshStandardMaterial
            color="#ffffff"
            roughness={0.34}
            metalness={0.68}
            transparent={isPower}
            opacity={isPower ? 0.22 : 1}
            depthWrite={!isPower}
          />
        )}
      </instancedMesh>

      {/* 2. Multi-Archetype Baked Front Facades (Standard Network / Modular Core Chassis / Compute Server) */}
      <instancedMesh ref={standardDoorRef} args={[undefined, undefined, placements.length]}>
        <planeGeometry args={[0.74, 1.86]} />
        <meshStandardMaterial
          map={standardTex}
          roughness={0.38}
          metalness={0.48}
          transparent={isPower || isThermal}
          opacity={isPower ? 0.14 : isThermal ? 0.28 : 1}
          depthWrite={!isPower && !isThermal}
        />
      </instancedMesh>
      <instancedMesh ref={coreDoorRef} args={[undefined, undefined, placements.length]}>
        <planeGeometry args={[0.74, 1.86]} />
        <meshStandardMaterial
          map={coreTex}
          roughness={0.34}
          metalness={0.55}
          transparent={isPower || isThermal}
          opacity={isPower ? 0.14 : isThermal ? 0.28 : 1}
          depthWrite={!isPower && !isThermal}
        />
      </instancedMesh>
      <instancedMesh ref={serverDoorRef} args={[undefined, undefined, placements.length]}>
        <planeGeometry args={[0.74, 1.86]} />
        <meshStandardMaterial
          map={serverTex}
          roughness={0.4}
          metalness={0.5}
          transparent={isPower || isThermal}
          opacity={isPower ? 0.14 : isThermal ? 0.28 : 1}
          depthWrite={!isPower && !isThermal}
        />
      </instancedMesh>

      {/* 3. Volumetric Power Load Column (Power Mode) / Slim U-Occupancy Meter (Physical Mode) */}
      <instancedMesh ref={fillRef} args={[undefined, undefined, placements.length]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial
          color="#ffffff"
          transparent
          opacity={isPower ? 0.92 : 0.85}
          toneMapped={false}
        />
      </instancedMesh>

      {/* 4. Top Crown LED Status Bar */}
      <instancedMesh ref={stripRef} args={[undefined, undefined, placements.length]}>
        <boxGeometry args={[0.76, 0.055, 0.04]} />
        <meshBasicMaterial color="#ffffff" toneMapped={false} />
      </instancedMesh>

      {/* 5. Rear Hot-Aisle Volumetric Exhaust Heat Plume (Thermal Mode, 1 draw call for all racks) */}
      <instancedMesh ref={heatPlumeRef} args={[undefined, undefined, placements.length]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial
          color="#ffffff"
          transparent
          opacity={0.36}
          depthWrite={false}
          toneMapped={false}
        />
      </instancedMesh>

      {/* Glowing cyan floor beacon around the currently selected rack */}
      {selectedPlacement && (
        <mesh
          position={[selectedPlacement.position[0], 0.02, selectedPlacement.position[2]]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <ringGeometry args={[0.66, 0.78, 32]} />
          <meshBasicMaterial color="#22d3ee" side={THREE.DoubleSide} toneMapped={false} />
        </mesh>
      )}

      {/* Zero-blur screen-space cabinet badges dynamically displaying U-usage, Power kW/%, or Exhaust °C */}
      {labeledPlacements.map(p => {
        const power = computeRackPowerMetrics(p.rack);
        const thermal = computeRackThermalMetrics(p.rack);
        const isSelected = p.rack.id === selectedRackId;
        const badgeMetric = isPower
          ? (power.watts > 0 ? `${power.kw}kW · ${power.utilizationPct}%` : (zh ? '空载 0kW' : 'Idle 0kW'))
          : isThermal
            ? `${thermal.exhaustC}°C`
            : `${p.rack.used_u}/${p.rack.total_u}U`;
        const metricColor = isPower
          ? (power.watts > 0 ? 'text-amber-300' : 'text-slate-500')
          : isThermal
            ? (thermal.exhaustC >= 34 ? 'text-rose-300' : thermal.exhaustC >= 27 ? 'text-amber-300' : 'text-sky-300')
            : 'text-slate-400';

        return (
          <Html
            key={`lbl-${p.rack.id}`}
            position={[p.position[0], p.position[1] + 1.08, p.position[2]]}
            center
          >
            <div className={`pointer-events-none whitespace-nowrap rounded px-1.5 py-0.5 text-[9px] font-bold shadow ${
              isSelected
                ? 'border border-cyan-400 bg-cyan-950/95 text-cyan-200'
                : 'border border-slate-700/85 bg-slate-950/92 text-slate-200'
            }`}>
              <span>{p.rack.name}</span>
              <span className={`ml-1 text-[8px] font-semibold ${metricColor}`}>
                {badgeMetric}
              </span>
            </div>
          </Html>
        );
      })}
    </group>
  );
};

// ---------------------------------------------------------------------------
// Complete Data Center Room Composite Scene
// ---------------------------------------------------------------------------
export const DataCenterRoomContent: React.FC<{
  room: DataCenterRoomModel;
  placements: RackFleetPlacement[];
  selectedRackId: string;
  selectedOdfId?: string | null;
  odfDoorOpen?: boolean;
  activeZoneId?: string | null;
  analysisMode: RoomAnalysisMode;
  layers: RoomLayerVisibility;
  interRackLinks: InterRackLink[];
  renderBudget?: RoomRenderBudget;
  roomRootRef?: React.RefObject<THREE.Group | null>;
  customModels?: ImportedGlbAsset[];
  zh: boolean;
  onSelectRack: (rackId: string) => void;
  onOpenRack: (rackId: string) => void;
  onInspectOdf?: (unit?: DataCenterEquipmentPlacement) => void;
}> = ({
  room,
  placements,
  selectedRackId,
  selectedOdfId,
  odfDoorOpen = false,
  activeZoneId,
  analysisMode,
  layers,
  interRackLinks,
  renderBudget,
  roomRootRef,
  customModels,
  zh,
  onSelectRack,
  onOpenRack,
  onInspectOdf,
}) => {
  const maxHtmlLabels = renderBudget?.maxHtmlLabels ?? 16;
  const showInfraLabels = placements.length <= maxHtmlLabels;
  const showAirflowEffective = layers.airflow || analysisMode === 'thermal';

  return (
    <group ref={roomRootRef} name="DataCenterHall3D">
      <DataCenterFloor room={room} analysisMode={analysisMode} />
      {layers.architecture && (
        <>
          <DataCenterZonesLayer zones={room.zones} activeZoneId={activeZoneId} zh={zh} />
          <DataCenterArchitecture room={room} />
        </>
      )}
      {layers.containment && <ColdAisleContainment room={room} />}
      {layers.trays && (
        <OverheadCableTrays
          room={room}
          placements={placements}
          analysisMode={analysisMode}
        />
      )}
      {layers.trays && interRackLinks.length > 0 && (
        <InterRackTrunkCables
          links={interRackLinks}
          placements={placements}
          selectedRackId={selectedRackId}
        />
      )}
      {layers.odf && room.odfUnits.length > 0 && (
        <group>
          {room.odfUnits.map((unit, idx) => {
            const isSelectedOdf = selectedOdfId === unit.id;
            const openThisDoor = Boolean(
              odfDoorOpen && (selectedOdfId ? isSelectedOdf : idx === 0),
            );
            return (
              <OdfCabinetUnit
                key={unit.id}
                item={unit}
                showLabel={showInfraLabels}
                isSelected={isSelectedOdf}
                isDoorOpen={openThisDoor}
                onInspectOdf={() => onInspectOdf?.(unit)}
              />
            );
          })}
        </group>
      )}
      {layers.cooling && (
        <group>
          {room.cracUnits.map(unit => (
            <InfraCabinetUnit key={unit.id} item={unit} showLabel={showInfraLabels} analysisMode={analysisMode} />
          ))}
          {room.pdfCabinets.map(unit => (
            <InfraCabinetUnit key={unit.id} item={unit} showLabel={showInfraLabels} analysisMode={analysisMode} />
          ))}
          {room.batteryUnits.map(unit => (
            <InfraCabinetUnit key={unit.id} item={unit} showLabel={showInfraLabels} analysisMode={analysisMode} />
          ))}
          {room.upsUnits.map(unit => (
            <KebosUpsCabinetUnit
              key={unit.id}
              item={unit}
              showLabel={showInfraLabels}
              highlightPower={analysisMode === 'power'}
            />
          ))}
        </group>
      )}
      {layers.fireMep && <DataCenterMepFireLayer room={room} zh={zh} />}
      {showAirflowEffective && <DataCenterAirflowStreams room={room} placements={placements} budget={renderBudget} />}
      <DataCenterRackFleet
        placements={placements}
        selectedRackId={selectedRackId}
        analysisMode={analysisMode}
        maxHtmlLabels={maxHtmlLabels}
        castShadow={Boolean(renderBudget?.shadows)}
        zh={zh}
        onSelectRack={onSelectRack}
        onOpenRack={onOpenRack}
      />
      {customModels && customModels.length > 0 && (
        <group name="ImportedGlbModels">
          {customModels.map(model => (
            <primitive
              key={model.id}
              object={model.object}
              position={model.position}
              rotation={[0, model.rotationY, 0]}
              scale={model.scale}
            />
          ))}
        </group>
      )}
    </group>
  );
};
