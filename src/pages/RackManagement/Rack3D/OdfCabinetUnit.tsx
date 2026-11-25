import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { Html } from '@react-three/drei';
import { DataCenterEquipmentPlacement, OdfTrayRoomSummary } from './fleetLayout';

// ---------------------------------------------------------------------------
// Refined Tier-4 Carrier ODF Palette (harmonized with KEBOS UPS & IT racks)
// Matte anthracite-gunmetal enclosure, titanium frame rails, smoked tempered
// glass front door, and restrained optical-standard accents (no neon glare).
// ---------------------------------------------------------------------------
const PALETTE = {
  cabinetShell: '#1e242d',
  cabinetPlinth: '#12171f',
  cabinetBack: '#0d121a',
  frameRail: '#596678',
  frameTrim: '#738296',
  trayBody: '#171e29',
  trayBezel: '#252f3e',
  trayRecess: '#0a0f17',
  troughMetal: '#1a2230',
  combPlastic: '#0e141e',
  doorFrame: '#252d3a',
  doorHandle: '#8c9bae',
  glassTint: '#0e1726',
  // Restrained carrier-grade optical hues (realistic under IDC lighting)
  os2Cage: '#1c4480',
  om4Cage: '#1b6170',
  apcCage: '#1b5d3f',
  os2Fiber: '#c89b2c',
  om4Fiber: '#3a8899',
  faultRed: '#dc2626',
  dustCap: '#8a97a8',
  copperBus: '#b86c25',
  waterfallBody: '#27303d',
  waterfallTrim: '#9e7a24',
} as const;

const odfCrownTexCache = new Map<string, THREE.CanvasTexture>();
const odfLabelStripTexCache = new Map<string, THREE.CanvasTexture>();

function getOdfCrownTexture(
  label: string,
  subText: string,
  statusColor: string,
): THREE.CanvasTexture {
  const key = `${label}|${subText}|${statusColor}`;
  const cached = odfCrownTexCache.get(key);
  if (cached) return cached;

  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 88;
  const ctx = canvas.getContext('2d')!;

  const grad = ctx.createLinearGradient(0, 0, 512, 88);
  grad.addColorStop(0, '#0c1118');
  grad.addColorStop(0.55, '#151c27');
  grad.addColorStop(1, '#0b0f16');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 88);

  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2;
  ctx.strokeRect(2, 2, 508, 84);

  // Subtle metallic gold-amber vertical indicator bar
  ctx.fillStyle = statusColor;
  ctx.fillRect(12, 14, 6, 60);

  ctx.fillStyle = '#e2e8f0';
  ctx.font = 'bold 26px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'left';
  const title = label.replace(/\s*光纤配线架$/, '').slice(0, 22);
  ctx.fillText(title, 28, 40);

  ctx.fillStyle = '#8b9cb3';
  ctx.font = '600 15px monospace';
  ctx.fillText(subText.slice(0, 44), 28, 66);

  // Crisp status LED
  ctx.fillStyle = statusColor;
  ctx.beginPath();
  ctx.arc(482, 44, 6, 0, Math.PI * 2);
  ctx.fill();

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  odfCrownTexCache.set(key, tex);
  return tex;
}

/** Crisp dark-anodized circuit designation strip reflecting real CMDB tray metadata. */
function getOdfDesignationStripTexture(
  trayCode: string,
  trayLabel: string,
  fiberMode: string,
  occupiedCount: number,
  portCount: number,
  faultCount: number,
): THREE.CanvasTexture {
  const key = `${trayCode}|${trayLabel}|${fiberMode}|${occupiedCount}/${portCount}|${faultCount}`;
  const cached = odfLabelStripTexCache.get(key);
  if (cached) return cached;

  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 64;
  const ctx = canvas.getContext('2d')!;

  // Dark brushed slate strip instead of harsh bright-white stripes
  ctx.fillStyle = '#1b2330';
  ctx.fillRect(0, 0, 1024, 64);
  ctx.strokeStyle = '#3b485c';
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, 1022, 62);

  const upperMode = (fiberMode || 'OS2').toUpperCase();
  const isMultimode = upperMode.includes('OM');
  const isApc = upperMode.includes('APC');
  const badgeColor = faultCount > 0
    ? '#b91c1c'
    : isMultimode
      ? '#1d6878'
      : isApc
        ? '#1d6644'
        : '#1e4785';

  ctx.fillStyle = badgeColor;
  ctx.fillRect(0, 0, 94, 64);
  ctx.fillStyle = '#f1f5f9';
  ctx.font = 'bold 28px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(trayCode.slice(0, 4), 47, 42);

  // Left: tray business designation or default range
  ctx.fillStyle = '#cbd5e1';
  ctx.font = 'bold 21px system-ui, monospace';
  ctx.textAlign = 'left';
  const desc = trayLabel?.trim()
    ? trayLabel.trim().slice(0, 28)
    : `${upperMode} · LC/UPC 48F MODULAR TRAY`;
  ctx.fillText(desc, 114, 40);

  // Divider
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(748, 12);
  ctx.lineTo(748, 52);
  ctx.stroke();

  // Right: live core occupancy readout
  ctx.fillStyle = faultCount > 0 ? '#fca5a5' : occupiedCount > 0 ? '#e2c16b' : '#64748b';
  ctx.font = 'bold 21px monospace';
  ctx.textAlign = 'right';
  const statText = faultCount > 0
    ? `${occupiedCount}/${portCount}F · ${faultCount} ERR`
    : `${occupiedCount}/${portCount}F ${upperMode}`;
  ctx.fillText(statText, 1004, 40);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  odfLabelStripTexCache.set(key, tex);
  return tex;
}

interface ResolvedTraySpec {
  trayNo: number;
  trayCode: string;
  label: string;
  portCount: number;
  fiberMode: string;
  occupiedCount: number;
  reservedCount: number;
  faultCount: number;
}

function resolveTrays(item: DataCenterEquipmentPlacement): ResolvedTraySpec[] {
  const frame = item.odfFrame;
  if (frame && Array.isArray(frame.trays) && frame.trays.length > 0) {
    return frame.trays.slice(0, 16).map((t: OdfTrayRoomSummary) => ({
      trayNo: t.tray_no,
      trayCode: t.tray_code || `A${String(t.tray_no).padStart(2, '0')}`,
      label: t.label || '',
      portCount: Math.max(12, t.port_count || frame.ports_per_tray || 48),
      fiberMode: (t.fiber_mode || frame.fiber_mode || 'OS2').toUpperCase(),
      occupiedCount: Math.max(0, t.occupied_count || 0),
      reservedCount: Math.max(0, t.reserved_count || 0),
      faultCount: Math.max(0, t.fault_count || 0),
    }));
  }
  const count = Math.min(16, Math.max(4, frame?.tray_count || 12));
  const perTray = frame?.ports_per_tray || 48;
  const isPlaceholder = Boolean(item.isPlaceholder || !frame);
  return Array.from({ length: count }, (_, idx) => {
    const isOm4 = idx >= Math.floor(count * 0.75);
    // Placeholder shows a clean, restrained partial preview (3 trays lightly patched)
    const previewOccupied = isPlaceholder && (idx === 2 || idx === 5 || idx === count - 2) ? 12 : 0;
    return {
      trayNo: idx + 1,
      trayCode: `A${String(idx + 1).padStart(2, '0')}`,
      label: isPlaceholder
        ? (idx === 5 ? '待录入 CMDB · 熔配预留' : '')
        : '',
      portCount: perTray,
      fiberMode: (frame?.fiber_mode && frame.fiber_mode !== 'MIXED')
        ? frame.fiber_mode.toUpperCase()
        : (isOm4 ? 'OM4' : 'OS2'),
      occupiedCount: previewOccupied,
      reservedCount: 0,
      faultCount: 0,
    };
  });
}

// ---------------------------------------------------------------------------
// High-Craft Tier-4 Carrier ODF Cabinet Unit (CMDB-Driven + Smoked Glass Door)
// ---------------------------------------------------------------------------
export const OdfCabinetUnit: React.FC<{
  item: DataCenterEquipmentPlacement;
  showLabel: boolean;
  isSelected?: boolean;
  isDoorOpen?: boolean;
  onInspectOdf?: () => void;
}> = ({ item, showLabel, isSelected = false, isDoorOpen = false, onInspectOdf }) => {
  const { width: w, height: h, depth: d } = item;
  const frame = item.odfFrame || null;
  const isPlaceholder = Boolean(item.isPlaceholder || !frame);

  const trays = useMemo(() => resolveTrays(item), [item]);
  const trayCount = trays.length;
  const ringCount = 10;

  // Dynamic vertical spacing that adapts neatly to 6/12/15-tray ODF models
  const bayCenterX = 0;
  const trayW = 0.49;
  const usableH = h - 0.34;
  const trayPitch = Math.min(0.148, usableH / Math.max(1, trayCount));
  const trayH = Math.min(0.102, trayPitch * 0.72);
  const trayD = 0.295;
  const trayStartY = -h / 2 + 0.23 + (usableH - trayPitch * trayCount) * 0.5;
  const zBack = -d / 2 + 0.02;
  const zTrayCenter = -0.028;
  const zTrayFront = zTrayCenter + trayD / 2;

  // Only pull out a single inspection tray when the glass door is opened!
  const openTrayIdx = useMemo(() => {
    if (!isDoorOpen) return -1;
    const firstActive = trays.findIndex(t => t.occupiedCount > 0 || t.faultCount > 0);
    return firstActive >= 0 ? firstActive : Math.floor(trayCount / 2);
  }, [isDoorOpen, trays, trayCount]);

  const leftChimneyX = -w / 2 + 0.092;
  const rightChimneyX = w / 2 - 0.092;

  // Smoothly animate the smoked tempered-glass front door hinge
  const doorPivotRef = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    const pivot = doorPivotRef.current;
    if (!pivot) return;
    const targetRot = isDoorOpen ? -1.92 : 0; // Swings open 110° left when inspecting ODF interior
    const step = 1 - Math.exp(-7.5 * Math.min(delta, 0.05));
    pivot.rotation.y = THREE.MathUtils.lerp(pivot.rotation.y, targetRot, step);
  });

  const totalCores = frame?.total_cores ?? item.fiberCores ?? trayCount * 48;
  const occupiedCores = frame?.occupied_cores ?? 0;
  const faultCores = frame?.fault_cores ?? 0;
  const crownStatusColor = faultCores > 0
    ? '#ef4444'
    : isPlaceholder
      ? '#64748b'
      : occupiedCores > 0
        ? '#10b981'
        : '#c89b2c';

  const crownSubText = frame
    ? `${occupiedCores}/${totalCores}F (${frame.utilization_pct}%) · ${(frame.vendor || 'CARRIER').toUpperCase()} ${frame.model || frame.connector_type || 'LC/UPC'}`
    : `${totalCores}F ODF · 规划占位 (未录入 CMDB)`;

  const crownTex = useMemo(
    () => getOdfCrownTexture(item.label, crownSubText, crownStatusColor),
    [item.label, crownSubText, crownStatusColor],
  );

  const labelTextures = useMemo(
    () => trays.map(t =>
      getOdfDesignationStripTexture(
        t.trayCode,
        t.label,
        t.fiberMode,
        t.occupiedCount,
        t.portCount,
        t.faultCount,
      ),
    ),
    [trays],
  );

  // Sleek cable management hoops & splice coil geometry
  const cableHoopGeo = useMemo(() => {
    const pts = [
      new THREE.Vector3(-0.022, 0, -0.02),
      new THREE.Vector3(-0.022, 0, 0.022),
      new THREE.Vector3(0.02, 0, 0.022),
      new THREE.Vector3(0.022, 0, -0.008),
    ];
    return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 12, 0.0034, 6, false);
  }, []);
  const coilRingGeo = useMemo(() => new THREE.TorusGeometry(0.035, 0.002, 6, 20), []);

  useEffect(() => () => {
    cableHoopGeo.dispose();
    coilRingGeo.dispose();
  }, [cableHoopGeo, coilRingGeo]);

  // InstancedMesh refs
  const chassisBodyRef = useRef<THREE.InstancedMesh>(null);
  const trimBarRef = useRef<THREE.InstancedMesh>(null);
  const recessBayRef = useRef<THREE.InstancedMesh>(null);
  const handleRef = useRef<THREE.InstancedMesh>(null);
  const troughRef = useRef<THREE.InstancedMesh>(null);
  const combFingerRef = useRef<THREE.InstancedMesh>(null);
  const sideFingerRef = useRef<THREE.InstancedMesh>(null);
  const lcCageOs2Ref = useRef<THREE.InstancedMesh>(null);
  const lcCageOm4Ref = useRef<THREE.InstancedMesh>(null);
  const lcBoreRef = useRef<THREE.InstancedMesh>(null);
  const lcBootYellowRef = useRef<THREE.InstancedMesh>(null);
  const lcBootAquaRef = useRef<THREE.InstancedMesh>(null);
  const lcBootFaultRef = useRef<THREE.InstancedMesh>(null);
  const lcDustCapRef = useRef<THREE.InstancedMesh>(null);
  const hoopRef = useRef<THREE.InstancedMesh>(null);
  const velcroRef = useRef<THREE.InstancedMesh>(null);

  // Build realistic combed 2.4mm LC fiber strands strictly proportional to REAL CMDB tray occupancy
  const mergedFibers = useMemo(() => {
    const os2Parts: THREE.BufferGeometry[] = [];
    const om4Parts: THREE.BufferGeometry[] = [];
    const armorParts: THREE.BufferGeometry[] = [];

    const topY = h / 2 + 0.62;
    const innerSpan = trayW - 0.052;
    const blkStep = innerSpan / 4;
    const colStep = (blkStep - 0.014) / 6;

    const addCleanTube = (
      points: THREE.Vector3[],
      radius: number,
      target: THREE.BufferGeometry[],
      tubularSegments = 18,
    ) => {
      const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.45);
      const geo = new THREE.TubeGeometry(curve, tubularSegments, radius, 5, false);
      if (geo.getAttribute('uv')) geo.deleteAttribute('uv');
      target.push(geo);
    };

    let os2LowestActiveY: number | null = null;
    let om4LowestActiveY: number | null = null;
    let os2StrandCount = 0;
    let om4StrandCount = 0;

    trays.forEach((tray, i) => {
      const isOm4 = tray.fiberMode.includes('OM');
      const occupiedDuplex = Math.min(24, Math.ceil((tray.occupiedCount + tray.faultCount) / 2));
      if (occupiedDuplex <= 0) return;

      // Render up to 8 cleanly combed visual ribbon strands per tray proportional to occupied ports
      const strandsForTray = Math.min(8, Math.max(1, Math.ceil(occupiedDuplex / 3)));
      const ty = trayStartY + i * trayPitch - 0.008;
      const troughY = trayStartY + i * trayPitch - trayH / 2 - 0.01;
      const pullOut = i === openTrayIdx ? 0.11 : 0;
      const sideSign = isOm4 ? 1 : -1;
      const chimneyX = isOm4 ? rightChimneyX - 0.006 : leftChimneyX + 0.006;

      if (isOm4) {
        om4LowestActiveY = om4LowestActiveY === null ? troughY : Math.min(om4LowestActiveY, troughY);
        om4StrandCount += strandsForTray;
      } else {
        os2LowestActiveY = os2LowestActiveY === null ? troughY : Math.min(os2LowestActiveY, troughY);
        os2StrandCount += strandsForTray;
      }

      for (let sIdx = 0; sIdx < strandsForTray; sIdx++) {
        const duplexSlot = Math.min(
          occupiedDuplex - 1,
          Math.floor((sIdx * occupiedDuplex) / strandsForTray),
        );
        const blk = Math.floor(duplexSlot / 6);
        const col = duplexSlot % 6;
        const blkLeft = bayCenterX - innerSpan / 2 + blk * blkStep + 0.007;
        const px = blkLeft + (col + 0.5) * colStep;
        const zBoot = zTrayFront + 0.015 + pullOut;

        const ribbonZ = zTrayFront + 0.02 + (sIdx % 4) * 0.0034;
        const ribbonY = troughY + 0.002 + Math.floor(sIdx / 4) * 0.0028;

        const loomCol = (sIdx + i * 2) % 5;
        const loomLayer = (sIdx + i) % 2;
        const loomX = chimneyX + (loomCol - 2) * 0.0038;
        const loomZ = 0.064 + (loomLayer - 0.5) * 0.004;
        const edgeX = sideSign * (trayW / 2 + 0.004);

        const pts = [
          new THREE.Vector3(px, ty - 0.002, zBoot),
          new THREE.Vector3(px + sideSign * 0.008, ty - 0.024, zBoot + 0.01),
          new THREE.Vector3(px + sideSign * 0.02, ribbonY, ribbonZ + pullOut * 0.35),
          new THREE.Vector3(edgeX - sideSign * 0.018, ribbonY, ribbonZ),
          new THREE.Vector3(edgeX + sideSign * 0.026, ribbonY + 0.008, (ribbonZ + loomZ) * 0.5),
          new THREE.Vector3(loomX, ribbonY + 0.045, loomZ),
          new THREE.Vector3(loomX, Math.min(h / 2 - 0.1, ribbonY + 0.18), loomZ),
        ];
        addCleanTube(pts, 0.00125, isOm4 ? om4Parts : os2Parts, 16);
      }
    });

    // Vertical combed ribbon looms only where active fibers exist (proportional thickness, never blunt!)
    const buildLoom = (
      xCenter: number,
      yStart: number,
      strandTotal: number,
      target: THREE.BufferGeometry[],
    ) => {
      const cols = Math.min(5, Math.max(2, Math.ceil(strandTotal / 6)));
      const layers = strandTotal >= 12 ? 2 : 1;
      for (let c = 0; c < cols; c++) {
        for (let l = 0; l < layers; l++) {
          const dx = (c - (cols - 1) / 2) * 0.004;
          const dz = (l - (layers - 1) / 2) * 0.004;
          addCleanTube(
            [
              new THREE.Vector3(xCenter + dx, yStart + 0.02, 0.064 + dz),
              new THREE.Vector3(xCenter + dx, (yStart + h / 2 - 0.14) * 0.5, 0.064 + dz),
              new THREE.Vector3(xCenter + dx, h / 2 - 0.12, 0.06 + dz),
              new THREE.Vector3(xCenter + dx * 0.85, h / 2 + 0.08, 0.024 + dz * 0.7),
              new THREE.Vector3(xCenter + dx * 0.7, h / 2 + 0.3, 0.005 + dz * 0.5),
              new THREE.Vector3(xCenter + dx * 0.6, topY, 0.0),
            ],
            0.00135,
            target,
            18,
          );
        }
      }
    };

    if (os2LowestActiveY !== null && os2StrandCount > 0) {
      buildLoom(leftChimneyX + 0.006, os2LowestActiveY, os2StrandCount, os2Parts);
    }
    if (om4LowestActiveY !== null && om4StrandCount > 0) {
      buildLoom(rightChimneyX - 0.006, om4LowestActiveY, om4StrandCount, om4Parts);
    }

    // Rear armored indoor/outdoor backbone feeder trunks clamped along left back channel
    for (const dx of [-0.018, 0.014]) {
      addCleanTube(
        [
          new THREE.Vector3(leftChimneyX + dx, -h / 2 + 0.02, -0.095),
          new THREE.Vector3(leftChimneyX + dx, -h / 2 + 0.36, -0.095),
          new THREE.Vector3(leftChimneyX + dx, 0.2, -0.105),
          new THREE.Vector3(leftChimneyX + dx, h / 2 - 0.22, -0.105),
        ],
        0.0095,
        armorParts,
        10,
      );
    }

    const os2Merged = os2Parts.length ? mergeGeometries(os2Parts, false) : null;
    const om4Merged = om4Parts.length ? mergeGeometries(om4Parts, false) : null;
    const armorMerged = armorParts.length ? mergeGeometries(armorParts, false) : null;
    os2Parts.forEach(g => g.dispose());
    om4Parts.forEach(g => g.dispose());
    armorParts.forEach(g => g.dispose());

    return { os2: os2Merged, om4: om4Merged, armor: armorMerged };
  }, [trays, h, trayW, trayH, trayStartY, trayPitch, zTrayFront, leftChimneyX, rightChimneyX, openTrayIdx]);

  useEffect(() => () => {
    mergedFibers.os2?.dispose();
    mergedFibers.om4?.dispose();
    mergedFibers.armor?.dispose();
  }, [mergedFibers]);

  // Populate InstancedMesh hardware transforms cleanly driven by real CMDB tray occupancy
  useEffect(() => {
    const dummy = new THREE.Object3D();
    const zero = new THREE.Matrix4().makeScale(0, 0, 0);

    const cb = chassisBodyRef.current;
    const tb = trimBarRef.current;
    const rb = recessBayRef.current;
    const hd = handleRef.current;
    const tr = troughRef.current;
    if (cb && tb && rb && hd && tr) {
      let trimIdx = 0;
      let handleIdx = 0;
      for (let i = 0; i < trayCount; i++) {
        const y = trayStartY + i * trayPitch;
        const isOpen = i === openTrayIdx;
        const pullOut = isOpen ? 0.11 : 0;

        dummy.position.set(bayCenterX, isOpen ? y - trayH * 0.35 : y, zTrayCenter + pullOut);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(trayW, isOpen ? trayH * 0.28 : trayH, trayD);
        dummy.updateMatrix();
        cb.setMatrixAt(i, dummy.matrix);

        for (const dy of [trayH / 2 - 0.004, -trayH / 2 + 0.004]) {
          dummy.position.set(bayCenterX, y + dy, zTrayFront + 0.003 + pullOut);
          dummy.scale.set(trayW + 0.004, 0.007, 0.007);
          dummy.updateMatrix();
          tb.setMatrixAt(trimIdx++, dummy.matrix);
        }

        dummy.position.set(bayCenterX, y - 0.006, zTrayFront + 0.001 + pullOut);
        dummy.scale.set(trayW - 0.036, Math.min(0.054, trayH * 0.54), 0.006);
        dummy.updateMatrix();
        rb.setMatrixAt(i, dummy.matrix);

        for (const sx of [-1, 1]) {
          dummy.position.set(bayCenterX + sx * (trayW / 2 - 0.01), y - 0.004, zTrayFront + 0.01 + pullOut);
          dummy.scale.set(0.007, Math.min(0.044, trayH * 0.45), 0.014);
          dummy.updateMatrix();
          hd.setMatrixAt(handleIdx++, dummy.matrix);
        }

        dummy.position.set(bayCenterX, y - trayH / 2 - 0.014, zTrayFront + 0.018);
        dummy.scale.set(trayW + 0.018, 0.006, 0.038);
        dummy.updateMatrix();
        tr.setMatrixAt(i, dummy.matrix);
      }
      cb.instanceMatrix.needsUpdate = true;
      tb.instanceMatrix.needsUpdate = true;
      rb.instanceMatrix.needsUpdate = true;
      hd.instanceMatrix.needsUpdate = true;
      tr.instanceMatrix.needsUpdate = true;
    }

    const cf = combFingerRef.current;
    if (cf) {
      let idx = 0;
      for (let i = 0; i < trayCount; i++) {
        const y = trayStartY + i * trayPitch - trayH / 2 - 0.005;
        for (let k = 0; k < 8; k++) {
          const fx = bayCenterX - trayW * 0.44 + (k / 7) * (trayW * 0.88);
          dummy.position.set(fx, y, zTrayFront + 0.035);
          dummy.rotation.set(0, 0, 0);
          dummy.scale.set(0.0045, 0.018, 0.007);
          dummy.updateMatrix();
          cf.setMatrixAt(idx++, dummy.matrix);
        }
      }
      cf.instanceMatrix.needsUpdate = true;
    }

    const sf = sideFingerRef.current;
    if (sf) {
      let idx = 0;
      for (const sx of [-1, 1]) {
        for (let r = 0; r < 28; r++) {
          const fy = -h / 2 + 0.2 + r * 0.064;
          dummy.position.set(sx * (trayW / 2 + 0.02), fy, zTrayFront + 0.008);
          dummy.rotation.set(0, 0, 0);
          dummy.scale.set(0.022, 0.009, 0.042);
          dummy.updateMatrix();
          sf.setMatrixAt(idx++, dummy.matrix);
        }
      }
      sf.instanceMatrix.needsUpdate = true;
    }

    const os2Cage = lcCageOs2Ref.current;
    const om4Cage = lcCageOm4Ref.current;
    const bore = lcBoreRef.current;
    const yBoot = lcBootYellowRef.current;
    const aBoot = lcBootAquaRef.current;
    const fBoot = lcBootFaultRef.current;
    const dCap = lcDustCapRef.current;
    if (os2Cage && om4Cage && bore && yBoot && aBoot && fBoot && dCap) {
      let os2Idx = 0;
      let om4Idx = 0;
      let boreIdx = 0;
      let yBootIdx = 0;
      let aBootIdx = 0;
      let fBootIdx = 0;
      let capIdx = 0;

      const innerSpan = trayW - 0.052;
      const blkStep = innerSpan / 4;
      const colStep = (blkStep - 0.014) / 6;

      trays.forEach((tray, i) => {
        const y = trayStartY + i * trayPitch - 0.007;
        const pullOut = i === openTrayIdx ? 0.11 : 0;
        const isOm4 = tray.fiberMode.includes('OM');
        const occupiedDuplex = Math.min(24, Math.ceil(tray.occupiedCount / 2));
        const faultDuplex = Math.min(24 - occupiedDuplex, Math.ceil(tray.faultCount / 2));

        for (let blk = 0; blk < 4; blk++) {
          const blkLeft = bayCenterX - innerSpan / 2 + blk * blkStep + 0.007;
          for (let col = 0; col < 6; col++) {
            const duplexSlot = blk * 6 + col;
            const px = blkLeft + (col + 0.5) * colStep;
            const zCage = zTrayFront + 0.006 + pullOut;

            dummy.position.set(px, y, zCage);
            dummy.rotation.set(0, 0, 0);
            dummy.scale.set(0.0114, Math.min(0.034, trayH * 0.34), 0.011);
            dummy.updateMatrix();
            if (isOm4 && om4Idx < om4Cage.count) om4Cage.setMatrixAt(om4Idx++, dummy.matrix);
            else if (os2Idx < os2Cage.count) os2Cage.setMatrixAt(os2Idx++, dummy.matrix);

            dummy.position.set(px, y, zCage + 0.0052);
            dummy.scale.set(0.008, Math.min(0.026, trayH * 0.26), 0.003);
            dummy.updateMatrix();
            if (boreIdx < bore.count) bore.setMatrixAt(boreIdx++, dummy.matrix);

            if (duplexSlot < occupiedDuplex) {
              dummy.position.set(px, y - 0.0025, zCage + 0.0095);
              dummy.rotation.set(0.22, 0, 0);
              dummy.scale.set(0.005, 0.0088, 0.0105);
              dummy.updateMatrix();
              if (isOm4 && aBootIdx < aBoot.count) aBoot.setMatrixAt(aBootIdx++, dummy.matrix);
              else if (yBootIdx < yBoot.count) yBoot.setMatrixAt(yBootIdx++, dummy.matrix);
            } else if (duplexSlot < occupiedDuplex + faultDuplex) {
              dummy.position.set(px, y - 0.0025, zCage + 0.0095);
              dummy.rotation.set(0.22, 0, 0);
              dummy.scale.set(0.0052, 0.009, 0.011);
              dummy.updateMatrix();
              if (fBootIdx < fBoot.count) fBoot.setMatrixAt(fBootIdx++, dummy.matrix);
            } else {
              dummy.position.set(px, y, zCage + 0.0072);
              dummy.rotation.set(0, 0, 0);
              dummy.scale.set(0.007, Math.min(0.02, trayH * 0.2), 0.0035);
              dummy.updateMatrix();
              if (capIdx < dCap.count) dCap.setMatrixAt(capIdx++, dummy.matrix);
            }
          }
        }
      });

      while (os2Idx < os2Cage.count) os2Cage.setMatrixAt(os2Idx++, zero);
      while (om4Idx < om4Cage.count) om4Cage.setMatrixAt(om4Idx++, zero);
      while (boreIdx < bore.count) bore.setMatrixAt(boreIdx++, zero);
      while (yBootIdx < yBoot.count) yBoot.setMatrixAt(yBootIdx++, zero);
      while (aBootIdx < aBoot.count) aBoot.setMatrixAt(aBootIdx++, zero);
      while (fBootIdx < fBoot.count) fBoot.setMatrixAt(fBootIdx++, zero);
      while (capIdx < dCap.count) dCap.setMatrixAt(capIdx++, zero);

      for (const m of [os2Cage, om4Cage, bore, yBoot, aBoot, fBoot, dCap]) {
        m.instanceMatrix.needsUpdate = true;
      }
    }

    const hp = hoopRef.current;
    if (hp) {
      let hIdx = 0;
      for (const sx of [-1, 1]) {
        const cx = sx < 0 ? leftChimneyX + 0.006 : rightChimneyX - 0.006;
        for (let k = 0; k < ringCount; k++) {
          const hy = -h / 2 + 0.25 + k * 0.175;
          dummy.position.set(cx, hy, 0.064);
          dummy.rotation.set(0, sx < 0 ? 0 : Math.PI, 0);
          dummy.scale.set(1, 1, 1);
          dummy.updateMatrix();
          hp.setMatrixAt(hIdx++, dummy.matrix);
        }
      }
      hp.instanceMatrix.needsUpdate = true;
    }

    const vc = velcroRef.current;
    if (vc) {
      let vIdx = 0;
      for (const cx of [leftChimneyX + 0.006, rightChimneyX - 0.006]) {
        for (let k = 0; k < 10; k++) {
          const vy = -h / 2 + 0.23 + k * 0.175;
          dummy.position.set(cx, vy, 0.062);
          dummy.rotation.set(0, 0, 0);
          dummy.scale.set(0.028, 0.01, 0.016);
          dummy.updateMatrix();
          vc.setMatrixAt(vIdx++, dummy.matrix);
        }
      }
      vc.instanceMatrix.needsUpdate = true;
    }
  }, [trays, trayCount, h, trayW, trayH, trayD, trayStartY, trayPitch, zTrayCenter, zTrayFront, leftChimneyX, rightChimneyX, openTrayIdx]);

  const maxSlots = Math.max(1, trayCount * 24);
  const openTrayY = openTrayIdx >= 0 ? trayStartY + openTrayIdx * trayPitch : 0;
  const doorH = h - 0.2;
  const doorW = w - 0.044;

  return (
    <group
      position={item.position}
      rotation={[0, item.rotationY, 0]}
      onClick={e => {
        e.stopPropagation();
        onInspectOdf?.();
      }}
    >
      {/* 1. Matte Anthracite-Gunmetal Carrier ODF Cabinet Shell (harmonized with KEBOS UPS & racks) */}
      <mesh position={[0, -h / 2 + 0.055, 0]}>
        <boxGeometry args={[w, 0.11, d]} />
        <meshStandardMaterial color={PALETTE.cabinetPlinth} roughness={0.58} metalness={0.55} />
      </mesh>
      <mesh position={[0, -h / 2 + 0.055, d / 2 + 0.002]}>
        <boxGeometry args={[w - 0.1, 0.048, 0.006]} />
        <meshStandardMaterial color="#090d14" roughness={0.7} metalness={0.35} />
      </mesh>

      {/* Top Crown Header */}
      <mesh position={[0, h / 2 - 0.044, 0]}>
        <boxGeometry args={[w, 0.088, d]} />
        <meshStandardMaterial color={PALETTE.cabinetShell} roughness={0.44} metalness={0.64} />
      </mesh>
      <mesh position={[0, h / 2 - 0.044, d / 2 + 0.003]}>
        <planeGeometry args={[w - 0.032, 0.074]} />
        <meshBasicMaterial map={crownTex} toneMapped={false} />
      </mesh>

      {/* Restrained Dual Dark-Anodized Top Fiber Entry Chutes with subtle amber trim */}
      {[leftChimneyX + 0.006, rightChimneyX - 0.006].map((hx, idx) => (
        <group key={`horn-${idx}`} position={[hx, h / 2 + 0.042, 0.02]}>
          <mesh>
            <boxGeometry args={[0.095, 0.084, 0.095]} />
            <meshStandardMaterial color={PALETTE.waterfallBody} roughness={0.46} metalness={0.52} />
          </mesh>
          <mesh position={[0, 0.044, 0]}>
            <boxGeometry args={[0.118, 0.016, 0.115]} />
            <meshStandardMaterial color={PALETTE.waterfallTrim} roughness={0.38} metalness={0.32} />
          </mesh>
        </group>
      ))}

      {/* Matte Anthracite Side Enclosures + Brushed Titanium Front Stiles */}
      {[-1, 1].map(side => (
        <group key={`side-${side}`}>
          <mesh position={[side * (w / 2 - 0.011), 0.01, 0]}>
            <boxGeometry args={[0.022, h - 0.176, d]} />
            <meshStandardMaterial color={PALETTE.cabinetShell} roughness={0.48} metalness={0.62} />
          </mesh>
          <mesh position={[side * (w / 2 - 0.011), 0.01, d / 2 - 0.006]}>
            <boxGeometry args={[0.02, h - 0.17, 0.012]} />
            <meshStandardMaterial color={PALETTE.frameRail} roughness={0.34} metalness={0.78} />
          </mesh>
        </group>
      ))}
      <mesh position={[0, 0.01, zBack]}>
        <boxGeometry args={[w - 0.036, h - 0.18, 0.022]} />
        <meshStandardMaterial color={PALETTE.cabinetBack} roughness={0.62} metalness={0.45} />
      </mesh>

      {/* Inner 19" Vertical Mounting Rails */}
      {[-1, 1].map(side => (
        <mesh key={`rail-${side}`} position={[side * (trayW / 2 + 0.012), 0.01, zTrayFront - 0.01]}>
          <boxGeometry args={[0.018, h - 0.21, 0.032]} />
          <meshStandardMaterial color="#2d3748" roughness={0.4} metalness={0.75} />
        </mesh>
      ))}

      {/* Bare Copper Grounding Busbar + Feeder Clamp */}
      <mesh position={[bayCenterX, -h / 2 + 0.142, zTrayFront - 0.06]}>
        <boxGeometry args={[trayW * 0.88, 0.018, 0.009]} />
        <meshStandardMaterial color={PALETTE.copperBus} roughness={0.28} metalness={0.86} />
      </mesh>
      <mesh position={[leftChimneyX, -h / 2 + 0.195, -0.065]}>
        <boxGeometry args={[0.1, 0.032, 0.036]} />
        <meshStandardMaterial color={PALETTE.frameRail} roughness={0.36} metalness={0.8} />
      </mesh>

      {/* 2. Instanced Subrack Hardware (Dynamic Tray Count) */}
      <instancedMesh ref={chassisBodyRef} args={[undefined, undefined, trayCount]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.trayBody} roughness={0.44} metalness={0.62} />
      </instancedMesh>
      <instancedMesh ref={trimBarRef} args={[undefined, undefined, trayCount * 2]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.frameTrim} roughness={0.34} metalness={0.76} />
      </instancedMesh>
      <instancedMesh ref={recessBayRef} args={[undefined, undefined, trayCount]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.trayRecess} roughness={0.66} metalness={0.3} />
      </instancedMesh>
      <instancedMesh ref={handleRef} args={[undefined, undefined, trayCount * 2]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.frameTrim} roughness={0.3} metalness={0.84} />
      </instancedMesh>
      <instancedMesh ref={troughRef} args={[undefined, undefined, trayCount]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.troughMetal} roughness={0.5} metalness={0.58} />
      </instancedMesh>
      <instancedMesh ref={combFingerRef} args={[undefined, undefined, trayCount * 8]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.combPlastic} roughness={0.56} metalness={0.3} />
      </instancedMesh>
      <instancedMesh ref={sideFingerRef} args={[undefined, undefined, 2 * 28]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.troughMetal} roughness={0.52} metalness={0.32} />
      </instancedMesh>

      {/* Dark-Anodized CMDB Circuit Designation Strips */}
      {labelTextures.map((tex, i) => {
        const y = trayStartY + i * trayPitch + trayH * 0.31;
        const pullOut = i === openTrayIdx ? 0.11 : 0;
        return (
          <mesh key={`lbl-strip-${i}`} position={[bayCenterX, y, zTrayFront + 0.005 + pullOut]}>
            <planeGeometry args={[trayW - 0.04, Math.min(0.018, trayH * 0.18)]} />
            <meshStandardMaterial map={tex} roughness={0.48} metalness={0.14} />
          </mesh>
        );
      })}

      {/* 3. Real 3D LC/UPC Duplex Adapter Cages + CMDB-Driven Boots & Dust Caps */}
      <instancedMesh ref={lcCageOs2Ref} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.os2Cage} roughness={0.36} metalness={0.18} />
      </instancedMesh>
      <instancedMesh ref={lcCageOm4Ref} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.om4Cage} roughness={0.36} metalness={0.18} />
      </instancedMesh>
      <instancedMesh ref={lcBoreRef} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color="#030712" roughness={0.74} metalness={0.12} />
      </instancedMesh>
      <instancedMesh ref={lcBootYellowRef} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.os2Fiber} roughness={0.42} metalness={0.08} />
      </instancedMesh>
      <instancedMesh ref={lcBootAquaRef} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.om4Fiber} roughness={0.42} metalness={0.08} />
      </instancedMesh>
      <instancedMesh ref={lcBootFaultRef} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.faultRed} roughness={0.35} metalness={0.12} />
      </instancedMesh>
      <instancedMesh ref={lcDustCapRef} args={[undefined, undefined, maxSlots]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={PALETTE.dustCap} roughness={0.48} metalness={0.12} />
      </instancedMesh>

      {/* 4. Pulled-Out Inspection Splice Tray (visible ONLY when front glass door is open) */}
      {openTrayIdx >= 0 && (
        <group position={[bayCenterX, openTrayY, zTrayCenter + 0.11]}>
          {[-1, 1].map(side => (
            <mesh key={`open-wall-${side}`} position={[side * (trayW / 2 - 0.007), 0, 0]}>
              <boxGeometry args={[0.011, trayH, trayD]} />
              <meshStandardMaterial color={PALETTE.frameTrim} roughness={0.34} metalness={0.74} />
            </mesh>
          ))}
          <mesh position={[0, -trayH * 0.14, 0.025]}>
            <boxGeometry args={[trayW - 0.044, 0.013, 0.21]} />
            <meshStandardMaterial color="#cbd5e1" roughness={0.44} metalness={0.1} />
          </mesh>
          {[-0.066, 0.066].map((hx, idx) => (
            <group key={`splice-blk-${idx}`} position={[hx, -trayH * 0.02, 0.03]}>
              <mesh>
                <boxGeometry args={[0.084, 0.011, 0.092]} />
                <meshStandardMaterial color="#334155" roughness={0.48} metalness={0.42} />
              </mesh>
              {[-0.032, -0.016, 0, 0.016, 0.032].map((sz, sIdx) => (
                <mesh key={sIdx} position={[0, 0.007, sz]} rotation={[0, 0, Math.PI / 2]}>
                  <cylinderGeometry args={[0.002, 0.002, 0.068, 6]} />
                  <meshStandardMaterial color="#94a3b8" roughness={0.28} metalness={0.35} />
                </mesh>
              ))}
            </group>
          ))}
          {[-0.14, 0.14].map((cx, idx) => (
            <mesh
              key={`coil-${idx}`}
              geometry={coilRingGeo}
              position={[cx, -trayH * 0.03, 0.03]}
              rotation={[Math.PI / 2, 0, 0]}
            >
              <meshStandardMaterial color={PALETTE.os2Fiber} roughness={0.4} metalness={0.08} />
            </mesh>
          ))}
        </group>
      )}

      {/* 5. Side Cable Hoops & Matte-Black Velcro Loom Straps */}
      <instancedMesh ref={hoopRef} args={[cableHoopGeo, undefined, ringCount * 2]}>
        <meshStandardMaterial color="#475569" roughness={0.38} metalness={0.76} />
      </instancedMesh>
      <instancedMesh ref={velcroRef} args={[undefined, undefined, 20]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color="#0b0f17" roughness={0.86} metalness={0.08} />
      </instancedMesh>

      {/* 6. Merged Ultra-Fine 2.4mm CMDB-Proportional Fiber Looms */}
      {mergedFibers.os2 && (
        <mesh geometry={mergedFibers.os2}>
          <meshStandardMaterial color={PALETTE.os2Fiber} roughness={0.42} metalness={0.06} />
        </mesh>
      )}
      {mergedFibers.om4 && (
        <mesh geometry={mergedFibers.om4}>
          <meshStandardMaterial color={PALETTE.om4Fiber} roughness={0.42} metalness={0.06} />
        </mesh>
      )}
      {mergedFibers.armor && (
        <mesh geometry={mergedFibers.armor}>
          <meshStandardMaterial color="#111827" roughness={0.64} metalness={0.26} />
        </mesh>
      )}

      {/* 7. Full-Height Recessed Smoked Tempered-Glass Front Door (pivots smoothly open on inspection!) */}
      <group
        ref={doorPivotRef}
        position={[-w / 2 + 0.022, 0.008, d / 2 - 0.004]}
      >
        <group position={[doorW / 2, 0, 0]}>
          {/* Smoked tempered glass pane */}
          <mesh position={[0, 0, 0.002]}>
            <planeGeometry args={[doorW - 0.068, doorH - 0.072]} />
            <meshPhysicalMaterial
              color={PALETTE.glassTint}
              transparent
              opacity={0.28}
              roughness={0.12}
              metalness={0.15}
              reflectivity={0.65}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
          {/* Left & Right extruded dark-anodized aluminum door stiles */}
          {[-1, 1].map(sx => (
            <mesh key={`dstile-${sx}`} position={[sx * (doorW / 2 - 0.017), 0, 0.004]}>
              <boxGeometry args={[0.034, doorH, 0.016]} />
              <meshStandardMaterial color={PALETTE.doorFrame} roughness={0.38} metalness={0.72} />
            </mesh>
          ))}
          {/* Top & Bottom door rails */}
          {[-1, 1].map(sy => (
            <mesh key={`drail-${sy}`} position={[0, sy * (doorH / 2 - 0.018), 0.004]}>
              <boxGeometry args={[doorW, 0.036, 0.016]} />
              <meshStandardMaterial color={PALETTE.doorFrame} roughness={0.38} metalness={0.72} />
            </mesh>
          ))}
          {/* Subtle thin carrier accent line along top door rail */}
          <mesh position={[0, doorH / 2 - 0.038, 0.013]}>
            <boxGeometry args={[doorW - 0.068, 0.005, 0.002]} />
            <meshStandardMaterial color={crownStatusColor} roughness={0.35} metalness={0.4} />
          </mesh>
          {/* Brushed chrome vertical swing-handle lock on right stile */}
          <group position={[doorW / 2 - 0.017, -0.02, 0.016]}>
            <mesh>
              <boxGeometry args={[0.022, 0.145, 0.012]} />
              <meshStandardMaterial color="#141a24" roughness={0.42} metalness={0.65} />
            </mesh>
            <mesh position={[0, 0.008, 0.01]}>
              <boxGeometry args={[0.012, 0.095, 0.008]} />
              <meshStandardMaterial color={PALETTE.doorHandle} roughness={0.26} metalness={0.88} />
            </mesh>
          </group>
        </group>
      </group>

      {/* Floor Selection Beacon when inspected */}
      {isSelected && (
        <mesh position={[0, -h / 2 + 0.018, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.56, 0.66, 32]} />
          <meshBasicMaterial color={isPlaceholder ? '#94a3b8' : '#e2b64c'} side={THREE.DoubleSide} toneMapped={false} />
        </mesh>
      )}

      {showLabel && (
        <Html position={[0, h / 2 + 0.24, 0]} center>
          <div
            className={`pointer-events-none whitespace-nowrap rounded border px-1.5 py-0.5 text-[9px] font-bold shadow ${
              isSelected
                ? 'border-amber-400 bg-amber-950/95 text-amber-200'
                : isPlaceholder
                  ? 'border-slate-600/80 bg-slate-950/92 text-slate-300'
                  : 'border-amber-500/50 bg-slate-950/92 text-amber-200'
            }`}
          >
            <span
              className="mr-1 inline-block h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: crownStatusColor }}
            />
            {item.label.replace(/\s*光纤配线架$/, '')}
            {frame
              ? ` · ${occupiedCores}/${totalCores}芯`
              : ` · ${totalCores}芯 (未建档)`}
          </div>
        </Html>
      )}
    </group>
  );
};
