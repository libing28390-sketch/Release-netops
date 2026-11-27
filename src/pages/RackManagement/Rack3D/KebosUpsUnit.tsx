import React, { useEffect, useMemo, useState } from 'react';
import * as THREE from 'three';
import { Html } from '@react-three/drei';
import { DataCenterEquipmentPlacement } from './fleetLayout';

// ---------------------------------------------------------------------------
// 1:1 Procedural High-DPI Textures for KEBOS Power Modular/Tower UPS Cabinet
// Matches reference photo: matte charcoal hexagonal honeycomb door, glossy
// top-center black glass HMI fascia with 7" live mimic LCD, geometric 3-diamond
// KEBOS POWER emblem, mimic status LED flow diagram, power button & left lock.
// ---------------------------------------------------------------------------
const kebosDoorTexCache = new Map<string, THREE.CanvasTexture>();
let kebosSideTexCache: THREE.CanvasTexture | null = null;
let kebosLogoImgCache: HTMLImageElement | null = null;
let kebosLogoLoading = false;
const kebosLogoListeners = new Set<() => void>();
const KEBOS_LOGO_URL = '/assets/images/kebos-logo.png';

function requestKebosLogoImage(onReady: () => void): HTMLImageElement | null {
  if (kebosLogoImgCache && kebosLogoImgCache.complete && kebosLogoImgCache.naturalWidth > 0) {
    return kebosLogoImgCache;
  }
  kebosLogoListeners.add(onReady);
  if (!kebosLogoLoading && typeof Image !== 'undefined') {
    kebosLogoLoading = true;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      kebosLogoImgCache = img;
      // Clear cached door textures so every UPS door immediately redraws with the crisp PNG logo
      kebosDoorTexCache.forEach(tex => tex.dispose());
      kebosDoorTexCache.clear();
      kebosLogoListeners.forEach(fn => fn());
      kebosLogoListeners.clear();
    };
    img.onerror = () => {
      kebosLogoLoading = false;
    };
    img.src = KEBOS_LOGO_URL;
  }
  return null;
}

function drawHexagon(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    const x = cx + r * Math.cos(a);
    const y = cy + r * Math.sin(a);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

function getKebosDoorTexture(loadKw: number, statusLabel: string, highlightPower: boolean): THREE.CanvasTexture {
  const key = `${loadKw.toFixed(1)}:${statusLabel}:${highlightPower ? 1 : 0}`;
  const cached = kebosDoorTexCache.get(key);
  if (cached) return cached;

  const W = 1024;
  const H = 2048;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  // 1. Matte dark anthracite powder-coated steel door base (#2d3137)
  const bodyGrad = ctx.createLinearGradient(0, 0, W, 0);
  bodyGrad.addColorStop(0, '#292d33');
  bodyGrad.addColorStop(0.5, '#333840');
  bodyGrad.addColorStop(1, '#272b31');
  ctx.fillStyle = bodyGrad;
  ctx.fillRect(0, 0, W, H);

  // Subtle metallic perimeter chamfer edge
  ctx.strokeStyle = '#474e58';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, W - 6, H - 6);

  // 2. Full-height hexagonal honeycomb perforation zone (leaving clean top/side/bottom steel borders)
  const meshLeft = 108;
  const meshRight = W - 108;
  const meshTop = 44;
  const meshBottom = H - 54;

  // Recessed black honeycomb backing shadow
  ctx.fillStyle = '#1b1e23';
  ctx.fillRect(meshLeft, meshTop, meshRight - meshLeft, meshBottom - meshTop);

  // Authentic staggered hexagonal perforations
  const hexR = 6.2;
  const dx = hexR * Math.sqrt(3) + 3.2;
  const dy = hexR * 1.5 + 2.8;
  ctx.fillStyle = '#07090d';
  let rowIdx = 0;
  for (let y = meshTop + 10; y < meshBottom - 8; y += dy) {
    const offset = (rowIdx % 2) * (dx / 2);
    for (let x = meshLeft + 10 + offset; x < meshRight - 10; x += dx) {
      drawHexagon(ctx, x, y, hexR);
      ctx.fill();
    }
    rowIdx += 1;
  }

  // Subtle steel bridge highlight across mesh
  ctx.strokeStyle = 'rgba(255,255,255,0.035)';
  ctx.lineWidth = 2;
  ctx.strokeRect(meshLeft, meshTop, meshRight - meshLeft, meshBottom - meshTop);

  // 3. Top-center recessed glossy piano-black glass control fascia (exact KEBOS proportions)
  const bezelW = 358;
  const bezelH = 516;
  const bezelX = (W - bezelW) / 2;
  const bezelY = 52;

  // Outer matte steel cutout frame around glass fascia
  ctx.fillStyle = '#25292f';
  ctx.fillRect(bezelX - 18, bezelY - 10, bezelW + 36, bezelH + 26);

  // Glossy jet-black acrylic panel
  const glassGrad = ctx.createLinearGradient(bezelX, bezelY, bezelX + bezelW, bezelY + bezelH);
  glassGrad.addColorStop(0, '#13171d');
  glassGrad.addColorStop(0.32, '#0a0d12');
  glassGrad.addColorStop(1, '#12161d');
  ctx.fillStyle = glassGrad;
  ctx.fillRect(bezelX, bezelY, bezelW, bezelH);

  // Subtle diagonal glass specular reflection streak (matching photo!)
  ctx.save();
  ctx.beginPath();
  ctx.rect(bezelX, bezelY, bezelW, bezelH);
  ctx.clip();
  const shine = ctx.createLinearGradient(bezelX, bezelY, bezelX + bezelW * 0.75, bezelY + bezelH * 0.65);
  shine.addColorStop(0, 'rgba(255,255,255,0.09)');
  shine.addColorStop(0.55, 'rgba(255,255,255,0.02)');
  shine.addColorStop(0.56, 'rgba(255,255,255,0)');
  ctx.fillStyle = shine;
  ctx.fillRect(bezelX, bezelY, bezelW, bezelH);
  ctx.restore();

  ctx.strokeStyle = highlightPower ? '#f59e0b' : '#2e343e';
  ctx.lineWidth = highlightPower ? 4 : 3;
  ctx.strokeRect(bezelX, bezelY, bezelW, bezelH);

  // 4. 7-inch Color LCD Touchscreen inside upper fascia (1:1 mimic diagram)
  const lcdX = bezelX + 46;
  const lcdY = bezelY + 42;
  const lcdW = bezelW - 92;
  const lcdH = 166;

  ctx.fillStyle = '#181c22';
  ctx.fillRect(lcdX - 4, lcdY - 4, lcdW + 8, lcdH + 8);
  ctx.fillStyle = '#1f2329';
  ctx.fillRect(lcdX, lcdY, lcdW, lcdH);

  // Top status bar of LCD
  ctx.fillStyle = '#101419';
  ctx.fillRect(lcdX, lcdY, lcdW, 18);
  ctx.fillStyle = '#cbd5e1';
  ctx.font = 'bold 10px monospace';
  ctx.textAlign = 'left';
  ctx.fillText('KEBOS POWER · ONLINE', lcdX + 8, lcdY + 13);
  ctx.fillStyle = '#22c55e';
  ctx.textAlign = 'right';
  ctx.fillText(`${loadKw.toFixed(1)}kW`, lcdX + lcdW - 8, lcdY + 13);

  // Left vertical telemetry summary panel inside LCD
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(lcdX + 8, lcdY + 26, 48, 52);
  ctx.fillStyle = '#0f172a';
  ctx.font = 'bold 9px monospace';
  ctx.textAlign = 'left';
  ctx.fillText('IN:380V', lcdX + 11, lcdY + 39);
  ctx.fillText('OUT:220V', lcdX + 11, lcdY + 52);
  ctx.fillText('50.0Hz', lcdX + 11, lcdY + 65);

  // Power mimic flow blocks inside LCD (AC/DC -> DC/AC -> LOAD + BATT + BYPASS)
  // Flow lines
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.moveTo(lcdX + 74, lcdY + 86);
  ctx.lineTo(lcdX + 242, lcdY + 86);
  ctx.stroke();

  // Bypass upper dashed/amber line
  ctx.strokeStyle = '#94a3b8';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(lcdX + 74, lcdY + 50);
  ctx.lineTo(lcdX + 242, lcdY + 50);
  ctx.lineTo(lcdX + 242, lcdY + 86);
  ctx.stroke();

  // Battery branch below
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(lcdX + 158, lcdY + 86);
  ctx.lineTo(lcdX + 158, lcdY + 114);
  ctx.stroke();

  // Colored mimic icons (matching screenshot 2's red/yellow/green power blocks!)
  const drawLcdBlock = (bx: number, by: number, bw: number, bh: number, fill: string, text: string) => {
    ctx.fillStyle = fill;
    ctx.fillRect(bx, by, bw, bh);
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    ctx.strokeRect(bx, by, bw, bh);
    ctx.fillStyle = '#0b111a';
    ctx.font = 'bold 9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(text, bx + bw / 2, by + bh / 2 + 3);
  };
  drawLcdBlock(lcdX + 66, lcdY + 42, 24, 16, '#e2e8f0', '~');
  drawLcdBlock(lcdX + 144, lcdY + 42, 26, 16, '#cbd5e1', 'BYP');
  drawLcdBlock(lcdX + 66, lcdY + 76, 26, 20, '#f59e0b', 'AC');
  drawLcdBlock(lcdX + 114, lcdY + 74, 30, 24, '#eab308', 'REC');
  drawLcdBlock(lcdX + 174, lcdY + 74, 30, 24, '#22c55e', 'INV');
  drawLcdBlock(lcdX + 224, lcdY + 74, 30, 24, '#10b981', 'OUT');
  drawLcdBlock(lcdX + 142, lcdY + 108, 32, 18, '#22c55e', 'BAT');

  // Bottom 6-button LCD icon toolbar
  ctx.fillStyle = '#0f1318';
  ctx.fillRect(lcdX, lcdY + lcdH - 26, lcdW, 26);
  const dockColors = ['#ef4444', '#38bdf8', '#f59e0b', '#22c55e', '#a855f7', '#94a3b8'];
  for (let i = 0; i < 6; i++) {
    const ix = lcdX + 10 + i * 42;
    ctx.fillStyle = '#334155';
    ctx.fillRect(ix, lcdY + lcdH - 22, 34, 18);
    ctx.fillStyle = dockColors[i];
    ctx.fillRect(ix + 10, lcdY + lcdH - 18, 14, 10);
  }

  // 5. Official KEBOS POWER Logo (uploaded official white PNG composited cleanly onto glossy black fascia)
  const logoCenterX = W / 2;
  const logoY = bezelY + 278;

  if (kebosLogoImgCache && kebosLogoImgCache.complete && kebosLogoImgCache.naturalWidth > 0) {
    // Preserve exact 1024x374 (2.738:1) aspect ratio of the uploaded official KEBOS logo
    const drawW = 248;
    const drawH = Math.round(drawW * (kebosLogoImgCache.naturalHeight / kebosLogoImgCache.naturalWidth));
    ctx.drawImage(
      kebosLogoImgCache,
      Math.round(logoCenterX - drawW / 2),
      Math.round(logoY - drawH / 2),
      drawW,
      drawH,
    );
  } else {
    // Instant crisp vector fallback while the PNG streams in (or in headless test DOM)
    const drawDiamond = (dx: number, dy: number, s: number) => {
      ctx.beginPath();
      ctx.moveTo(dx, dy - s);
      ctx.lineTo(dx + s, dy);
      ctx.lineTo(dx, dy + s);
      ctx.lineTo(dx - s, dy);
      ctx.closePath();
      ctx.fill();
    };
    ctx.fillStyle = '#f8fafc';
    const iconX = logoCenterX - 78;
    drawDiamond(iconX - 12, logoY, 10.5);
    drawDiamond(iconX + 1, logoY - 13, 10.5);
    drawDiamond(iconX + 1, logoY + 13, 10.5);

    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 28px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('KEBOS', iconX + 22, logoY + 2);
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '600 12px system-ui, sans-serif';
    ctx.fillText('Beyond ideas', iconX + 38, logoY + 20);
  }

  // 6. Silkscreened Mimic Power-Flow Status Diagram below KEBOS logo (BYPASS / LINE / INV / LOAD / BATT / FAULT)
  const diagY = bezelY + 356;
  ctx.strokeStyle = '#cbd5e1';
  ctx.lineWidth = 2;
  // Main horizontal line LINE -> INV -> LOAD
  ctx.beginPath();
  ctx.moveTo(logoCenterX - 62, diagY);
  ctx.lineTo(logoCenterX + 62, diagY);
  // Bypass upper bridge
  ctx.moveTo(logoCenterX - 38, diagY);
  ctx.lineTo(logoCenterX - 38, diagY - 22);
  ctx.lineTo(logoCenterX + 38, diagY - 22);
  ctx.lineTo(logoCenterX + 38, diagY);
  // Battery lower drop
  ctx.moveTo(logoCenterX, diagY);
  ctx.lineTo(logoCenterX, diagY + 24);
  ctx.stroke();

  // Live glowing indicator LEDs on mimic schematic
  const drawLed = (lx: number, ly: number, color: string) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.fill();
  };
  drawLed(logoCenterX - 54, diagY, '#22c55e'); // LINE green
  drawLed(logoCenterX, diagY, '#22c55e'); // INV green
  drawLed(logoCenterX + 54, diagY, '#22c55e'); // LOAD green
  drawLed(logoCenterX, diagY - 22, '#475569'); // BYPASS off
  drawLed(logoCenterX, diagY + 24, '#22c55e'); // BATT green
  drawLed(logoCenterX + 42, diagY + 24, '#475569'); // FAULT off

  ctx.fillStyle = '#cbd5e1';
  ctx.font = 'bold 10px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('BYPASS', logoCenterX, diagY - 30);
  ctx.fillText('LINE', logoCenterX - 54, diagY + 16);
  ctx.fillText('INV', logoCenterX, diagY - 7);
  ctx.fillText('LOAD', logoCenterX + 54, diagY + 16);
  ctx.fillText('BATT', logoCenterX, diagY + 41);
  ctx.fillText('FAULT', logoCenterX + 42, diagY + 41);

  // 7. Bottom Circular POWER Push-Button Icon (⏻ POWER)
  const pwrY = bezelY + 450;
  ctx.strokeStyle = '#e2e8f0';
  ctx.lineWidth = 2.6;
  ctx.beginPath();
  ctx.arc(logoCenterX, pwrY, 13, -Math.PI * 0.32, Math.PI * 1.32);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(logoCenterX, pwrY - 17);
  ctx.lineTo(logoCenterX, pwrY - 4);
  ctx.stroke();
  ctx.fillStyle = '#cbd5e1';
  ctx.font = 'bold 11px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('POWER', logoCenterX, pwrY + 27);

  // 8. Signature Round Black Flush Key-Lock on Left Door Frame (matching Screenshot 2!)
  ctx.fillStyle = '#090b0f';
  ctx.beginPath();
  ctx.arc(54, H * 0.505, 16, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#525b66';
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.fillStyle = '#475569';
  ctx.fillRect(51, H * 0.505 - 7, 6, 14);

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  kebosDoorTexCache.set(key, tex);
  return tex;
}

function getKebosSideTexture(): THREE.CanvasTexture {
  if (kebosSideTexCache) return kebosSideTexCache;
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 512;
  const ctx = canvas.getContext('2d')!;

  const grad = ctx.createLinearGradient(0, 0, 256, 512);
  grad.addColorStop(0, '#2c3036');
  grad.addColorStop(0.5, '#262a30');
  grad.addColorStop(1, '#202429');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 256, 512);

  ctx.strokeStyle = '#3d444d';
  ctx.lineWidth = 4;
  ctx.strokeRect(4, 4, 248, 504);

  // Subtle industrial side louver slot rows at top & bottom
  ctx.fillStyle = '#111419';
  for (const bandY of [42, 412]) {
    for (let i = 0; i < 8; i++) {
      ctx.fillRect(36, bandY + i * 8, 184, 3.5);
    }
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  kebosSideTexCache = tex;
  return tex;
}

// ---------------------------------------------------------------------------
// KEBOS Power Industrial Cabinet UPS Unit (1:1 Visual Match to Reference Photo)
// ---------------------------------------------------------------------------
export const KebosUpsCabinetUnit: React.FC<{
  item: DataCenterEquipmentPlacement;
  showLabel: boolean;
  highlightPower: boolean;
}> = ({ item, showLabel, highlightPower }) => {
  const { width: w, height: h, depth: d } = item;
  const footClearance = 0.115; // Visible industrial casters + stainless leveling feet below chassis!
  const chassisH = h - footClearance;
  const chassisCenterY = footClearance / 2;

  const [logoRevision, setLogoRevision] = useState(0);
  useEffect(() => {
    const onLogoReady = () => setLogoRevision(v => v + 1);
    const ready = requestKebosLogoImage(onLogoReady);
    if (ready) setLogoRevision(v => v + 1);
    return () => {
      kebosLogoListeners.delete(onLogoReady);
    };
  }, []);

  const doorTex = useMemo(
    () => getKebosDoorTexture(item.loadKw ?? 18.4, item.sublabel, highlightPower),
    [item.loadKw, item.sublabel, highlightPower, logoRevision],
  );
  const sideTex = useMemo(() => getKebosSideTexture(), []);

  return (
    <group position={item.position} rotation={[0, item.rotationY, 0]}>
      {/* 1. Main Powder-Coated Anthracite Steel UPS Enclosure */}
      <mesh position={[0, chassisCenterY, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, chassisH, d]} />
        <meshStandardMaterial
          map={sideTex}
          color={highlightPower ? '#3f4650' : '#ffffff'}
          emissive={highlightPower ? '#92400e' : '#000000'}
          emissiveIntensity={highlightPower ? 0.22 : 0}
          roughness={0.52}
          metalness={0.56}
        />
      </mesh>

      {/* 2. Front Door Slab + 1:1 High-DPI KEBOS Hexagonal Mesh & Glossy HMI Fascia */}
      <mesh position={[0, chassisCenterY, d / 2 + 0.008]}>
        <boxGeometry args={[w - 0.006, chassisH - 0.006, 0.016]} />
        <meshStandardMaterial color="#272b31" roughness={0.5} metalness={0.58} />
      </mesh>
      <mesh position={[0, chassisCenterY, d / 2 + 0.018]}>
        <planeGeometry args={[w - 0.01, chassisH - 0.01]} />
        <meshStandardMaterial
          map={doorTex}
          roughness={0.44}
          metalness={0.42}
          emissiveMap={doorTex}
          emissive={highlightPower ? '#fde68a' : '#ffffff'}
          emissiveIntensity={highlightPower ? 0.34 : 0.14}
        />
      </mesh>

      {/* Subtle 3D Recessed Glass Gloss Overlay right over the Top-Center KEBOS HMI Bezel */}
      <mesh position={[0, chassisCenterY + chassisH * 0.345, d / 2 + 0.022]}>
        <boxGeometry args={[w * 0.355, chassisH * 0.255, 0.006]} />
        <meshStandardMaterial
          color="#0a0d12"
          transparent
          opacity={0.18}
          roughness={0.08}
          metalness={0.3}
          depthWrite={false}
        />
      </mesh>

      {/* 3. Signature Heavy-Duty Swivel Casters (4 × Black Industrial Wheels + Chrome Fork Brackets) */}
      {([-1, 1] as const).map(sx =>
        ([-1, 1] as const).map(sz => {
          const cx = sx * (w * 0.32);
          const cz = sz * (d * 0.34);
          return (
            <group key={`caster-${sx}-${sz}`} position={[cx, -h / 2 + 0.055, cz]}>
              {/* Brushed stainless caster fork bracket */}
              <mesh position={[0, 0.032, 0]}>
                <boxGeometry args={[0.072, 0.058, 0.058]} />
                <meshStandardMaterial color="#cbd5e1" roughness={0.28} metalness={0.86} />
              </mesh>
              {/* Solid black polyurethane wheel */}
              <mesh position={[0, -0.01, 0]} rotation={[0, 0, Math.PI / 2]}>
                <cylinderGeometry args={[0.044, 0.044, 0.042, 16]} />
                <meshStandardMaterial color="#111419" roughness={0.68} metalness={0.22} />
              </mesh>
            </group>
          );
        }),
      )}

      {/* 4. Signature Outer Corner Stainless Threaded Leveling Feet (4 × Chrome Bell Pads) */}
      {([-1, 1] as const).map(sx =>
        ([-1, 1] as const).map(sz => {
          const fx = sx * (w * 0.445);
          const fz = sz * (d * 0.42);
          return (
            <group key={`foot-${sx}-${sz}`} position={[fx, -h / 2, fz]}>
              {/* Threaded steel spindle */}
              <mesh position={[0, footClearance * 0.55, 0]}>
                <cylinderGeometry args={[0.009, 0.009, footClearance * 0.9, 10]} />
                <meshStandardMaterial color="#94a3b8" roughness={0.25} metalness={0.9} />
              </mesh>
              {/* Flared stainless bell foot pad flush on raised floor */}
              <mesh position={[0, 0.014, 0]}>
                <cylinderGeometry args={[0.016, 0.032, 0.028, 14]} />
                <meshStandardMaterial color="#cbd5e1" roughness={0.22} metalness={0.88} />
              </mesh>
            </group>
          );
        }),
      )}

      {/* Top A/B Power Output Cable Conduit Stubs */}
      {[-0.14, 0.14].map((ox, i) => (
        <mesh key={`conduit-${i}`} position={[ox, h / 2 + 0.14, -0.08]}>
          <cylinderGeometry args={[0.032, 0.032, 0.28, 12]} />
          <meshStandardMaterial color={i === 0 ? '#dc2626' : '#2563eb'} roughness={0.42} metalness={0.55} />
        </mesh>
      ))}

      {showLabel && (
        <Html position={[0, h / 2 + 0.22, 0]} center>
          <div className="pointer-events-none whitespace-nowrap rounded border border-emerald-500/60 bg-slate-950/92 px-1.5 py-0.5 text-[9px] font-semibold tracking-tight text-slate-200 shadow">
            <span className="text-emerald-400">●</span> {item.label}
          </div>
        </Html>
      )}
    </group>
  );
};
