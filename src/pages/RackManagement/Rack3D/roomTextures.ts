import * as THREE from 'three';

/**
 * High-craft offline procedural PBR + Emissive texture studio for the 3D Data Center Hall.
 * All textures are generated once and cached in memory — zero external network requests,
 * minimal VRAM footprint, and crisp visuals on both discrete and integrated GPUs.
 */

let floorPbrCache: { map: THREE.CanvasTexture; roughnessMap: THREE.CanvasTexture } | null = null;
let perfTileCache: THREE.CanvasTexture | null = null;
let wallPanelCache: THREE.CanvasTexture | null = null;
let rackDoorCache: {
  populatedMap: THREE.CanvasTexture;
  populatedEmissive: THREE.CanvasTexture;
  emptyMap: THREE.CanvasTexture;
} | null = null;
let contactShadowCache: THREE.CanvasTexture | null = null;
let thermalPlumeCache: THREE.CanvasTexture | null = null;
let lightPoolCache: THREE.CanvasTexture | null = null;
let rearDoorCache: { map: THREE.CanvasTexture; emissive: THREE.CanvasTexture } | null = null;
let exitSignCache: THREE.CanvasTexture | null = null;
let skyDomeCache: THREE.CanvasTexture | null = null;
let ceilingGridCache: THREE.CanvasTexture | null = null;
const equipFaceCache = new Map<string, THREE.CanvasTexture>();
const signCache = new Map<string, THREE.CanvasTexture>();
const nocMonitorCache = new Map<string, THREE.CanvasTexture>();
const rackHeaderCache = new Map<string, THREE.CanvasTexture>();
const pduMeterCache = new Map<string, THREE.CanvasTexture>();

function makeCanvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return [c, c.getContext('2d')!];
}

// ---------------------------------------------------------------------------
// 1. Brushed Anti-Static 600x600mm Raised Floor (Diffuse + Specular Roughness)
// ---------------------------------------------------------------------------
export function getRaisedFloorPbrTextures(): {
  map: THREE.CanvasTexture;
  roughnessMap: THREE.CanvasTexture;
} {
  if (floorPbrCache) return floorPbrCache;

  const [c, ctx] = makeCanvas(512, 512);
  const [rc, rctx] = makeCanvas(512, 512);

  // Crisp dark micro-grout seams
  ctx.fillStyle = '#475569';
  ctx.fillRect(0, 0, 512, 512);
  rctx.fillStyle = '#dcdcdc'; // matte grout seams
  rctx.fillRect(0, 0, 512, 512);

  const tile = 256;
  for (let gx = 0; gx < 2; gx++) {
    for (let gy = 0; gy < 2; gy++) {
      const x = gx * tile;
      const y = gy * tile;
      const checker = (gx + gy) % 2 === 0;

      // Authentic light pearl-gray / brushed anti-static HPL raised floor tiles (real Tier-4 IDC look)
      const grad = ctx.createLinearGradient(x, y, x + tile, y + tile);
      grad.addColorStop(0, checker ? '#b8c3d0' : '#aebac8');
      grad.addColorStop(0.5, checker ? '#aeb9c7' : '#a4b1c0');
      grad.addColorStop(1, checker ? '#a0acb9' : '#98a4b2');
      ctx.fillStyle = grad;
      ctx.fillRect(x + 2, y + 2, tile - 4, tile - 4);

      // Realistic HPL anti-static terrazzo micro-speckle
      for (let i = 0; i < 220; i++) {
        const sx = x + 6 + ((i * 73 + gx * 31) % (tile - 12));
        const sy = y + 6 + ((i * 137 + gy * 47) % (tile - 12));
        ctx.fillStyle = i % 3 === 0 ? 'rgba(255, 255, 255, 0.22)' : 'rgba(51, 65, 85, 0.14)';
        ctx.fillRect(sx, sy, 2, 2);
      }

      // Subtle beveled metallic tile edge highlight
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x + 3.5, y + 3.5, tile - 7, tile - 7);

      // Corner stainless leveling caps
      ctx.fillStyle = '#64748b';
      for (const px of [x + 12, x + tile - 12]) {
        for (const py of [y + 12, y + tile - 12]) {
          ctx.beginPath();
          ctx.arc(px, py, 2.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Satin semi-gloss specular reflection map (catches ceiling LED troffers cleanly!)
      const rgrad = rctx.createLinearGradient(x, y, x + tile, y + tile);
      rgrad.addColorStop(0, checker ? '#484848' : '#545454');
      rgrad.addColorStop(1, checker ? '#5c5c5c' : '#4c4c4c');
      rctx.fillStyle = rgrad;
      rctx.fillRect(x + 3, y + 3, tile - 6, tile - 6);
    }
  }

  const map = new THREE.CanvasTexture(c);
  map.wrapS = THREE.RepeatWrapping;
  map.wrapT = THREE.RepeatWrapping;
  map.anisotropy = 4;

  const roughnessMap = new THREE.CanvasTexture(rc);
  roughnessMap.wrapS = THREE.RepeatWrapping;
  roughnessMap.wrapT = THREE.RepeatWrapping;
  roughnessMap.anisotropy = 4;

  floorPbrCache = { map, roughnessMap };
  return floorPbrCache;
}

// ---------------------------------------------------------------------------
// 2. Perforated Cold-Aisle Chilled Air Supply Floor Grating
// ---------------------------------------------------------------------------
export function getPerforatedColdTileTexture(): THREE.CanvasTexture {
  if (perfTileCache) return perfTileCache;
  const [c, ctx] = makeCanvas(256, 256);

  // Authentic brushed stainless steel high-airflow perforated cold-aisle floor grating
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(0, 0, 256, 256);

  ctx.strokeStyle = '#64748b';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 250);

  // Dark deep under-floor plenum recesses through precision linear diffuser slots
  ctx.fillStyle = '#0f1d2e';
  for (let row = 0; row < 16; row++) {
    ctx.fillRect(14, 13 + row * 14.8, 228, 7.5);
  }
  // Brushed metallic structural cross ribs
  ctx.fillStyle = '#cbd5e1';
  for (let col = 0; col < 4; col++) {
    ctx.fillRect(14 + col * 74, 10, 5, 236);
  }
  // Subtle cool-blue under-floor plenum reflection along slots
  ctx.fillStyle = 'rgba(56, 189, 248, 0.22)';
  for (let row = 0; row < 16; row++) {
    ctx.fillRect(20, 15 + row * 14.8, 216, 2);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  perfTileCache = tex;
  return tex;
}

// ---------------------------------------------------------------------------
// 3. Modular Architectural Pearl-Silver Acoustic Steel Wall Cladding
// ---------------------------------------------------------------------------
export function getWallPanelTexture(): THREE.CanvasTexture {
  if (wallPanelCache) return wallPanelCache;
  const [c, ctx] = makeCanvas(512, 512);

  // Authentic clean Tier-4 IDC pearl-silver / brushed aluminum-steel acoustic wall panels
  const base = ctx.createLinearGradient(0, 0, 0, 512);
  base.addColorStop(0, '#cfd8e3');
  base.addColorStop(0.55, '#dce3ec');
  base.addColorStop(1, '#bcc7d6');
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, 512, 512);

  // Vertical modular steel cladding seams (4 panels across)
  for (let i = 0; i < 4; i++) {
    const px = i * 128;
    const pgrad = ctx.createLinearGradient(px, 0, px + 128, 0);
    pgrad.addColorStop(0, 'rgba(255, 255, 255, 0.22)');
    pgrad.addColorStop(0.12, 'rgba(255, 255, 255, 0.05)');
    pgrad.addColorStop(0.92, 'rgba(15, 23, 42, 0.06)');
    pgrad.addColorStop(1, 'rgba(15, 23, 42, 0.22)');
    ctx.fillStyle = pgrad;
    ctx.fillRect(px, 0, 128, 512);

    ctx.fillStyle = '#64748b';
    ctx.fillRect(px, 0, 3, 512);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.fillRect(px + 3, 0, 1.5, 512);
  }

  // Horizontal architectural reveal bands
  for (const hy of [88, 366, 466]) {
    ctx.fillStyle = '#64748b';
    ctx.fillRect(0, hy, 512, 3);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
    ctx.fillRect(0, hy + 3, 512, 1.5);
  }

  // Lower brushed stainless baseboard bumper guard
  ctx.fillStyle = '#475569';
  ctx.fillRect(0, 470, 512, 42);
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(0, 470, 512, 4);

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.anisotropy = 4;
  wallPanelCache = tex;
  return tex;
}

// ---------------------------------------------------------------------------
// 4. High-Craft 42U Cabinet Front Mesh Door (Diffuse + Twinkling Hardware LEDs Emissive)
// ---------------------------------------------------------------------------
export function getRackDoorTextures(): {
  populatedMap: THREE.CanvasTexture;
  populatedEmissive: THREE.CanvasTexture;
  emptyMap: THREE.CanvasTexture;
} {
  if (rackDoorCache) return rackDoorCache;

  const drawBaseDoor = (ctx: CanvasRenderingContext2D, populated: boolean, ectx?: CanvasRenderingContext2D) => {
    // Crisp anodized dark-steel outer frame & silver hairline inner reveal
    ctx.fillStyle = '#18202c';
    ctx.fillRect(0, 0, 256, 512);

    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 5;
    ctx.strokeRect(2.5, 2.5, 251, 507);

    // Recessed perforated honeycomb center aperture
    ctx.fillStyle = '#090e16';
    ctx.fillRect(18, 18, 220, 476);

    // Left/Right vertical EIA-310 brushed-steel mounting rails
    ctx.fillStyle = '#334155';
    ctx.fillRect(20, 20, 9, 472);
    ctx.fillRect(227, 20, 9, 472);

    if (ectx) {
      ectx.fillStyle = '#000000';
      ectx.fillRect(0, 0, 256, 512);
    }

    // Realistic internal 1U/2U silver H3C/Cisco switches & dark servers behind the mesh!
    const slotCount = 24;
    for (let i = 0; i < slotCount; i++) {
      const sy = 26 + i * 19;
      if (populated && (i >= 11 || i === 2 || i === 3 || i === 6 || i === 7)) {
        const isSilverSwitch = i >= 12 && i <= 17;
        ctx.fillStyle = isSilverSwitch ? '#8a99ad' : '#253244';
        ctx.fillRect(32, sy, 192, 15);
        // Dark port cages row across switch faceplate
        ctx.fillStyle = '#0b1220';
        ctx.fillRect(46, sy + 4, 152, 7);
        // Bright yellow/cyan fiber patch cords visible behind the perforated glass/mesh!
        if (isSilverSwitch && i % 2 === 0) {
          ctx.fillStyle = '#eab308';
          ctx.fillRect(166, sy + 7, 46, 3);
        }

        if (ectx) {
          // Left SYS/PWR pure hardware green LEDs
          ectx.fillStyle = '#00e632';
          ectx.fillRect(36, sy + 5, 7, 4);
          ectx.fillStyle = '#00c428';
          ectx.fillRect(46, sy + 5, 4, 4);

          // Active link activity LEDs across switch/server ports
          for (let p = 0; p < 12; p++) {
            const hash = (i * 19 + p * 7) % 10;
            if (hash < 4) {
              ectx.fillStyle = hash === 0 ? '#38bdf8' : hash === 1 ? '#f59e0b' : '#00e632';
              ectx.fillRect(60 + p * 12, sy + 5, 5, 4);
            }
          }
          ctx.fillStyle = '#00e632';
          ctx.fillRect(36, sy + 5, 7, 4);
        }
      } else {
        ctx.fillStyle = '#0c121c';
        ctx.fillRect(32, sy, 192, 14);
      }
    }

    // Subtle fine honeycomb perforation overlay (keeps internal hardware & LEDs clearly visible!)
    ctx.fillStyle = 'rgba(11, 17, 27, 0.34)';
    for (let y = 20; y < 492; y += 6) {
      ctx.fillRect(20, y, 216, 1.5);
    }
    for (let x = 20; x < 236; x += 7) {
      ctx.fillRect(x, 20, 1.5, 472);
    }

    // Brushed-chrome vertical swing handle & biometric/key lock on right bezel
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(236, 222, 12, 68);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(239, 230, 6, 52);
    ctx.fillStyle = '#0f172a';
    ctx.beginPath();
    ctx.arc(242, 240, 2.5, 0, Math.PI * 2);
    ctx.fill();
  };

  const [pc, pctx] = makeCanvas(256, 512);
  const [ec, ectx] = makeCanvas(256, 512);
  const [vc, vctx] = makeCanvas(256, 512);

  drawBaseDoor(pctx, true, ectx);
  drawBaseDoor(vctx, false);

  const populatedMap = new THREE.CanvasTexture(pc);
  populatedMap.anisotropy = 4;
  const populatedEmissive = new THREE.CanvasTexture(ec);
  populatedEmissive.anisotropy = 4;
  const emptyMap = new THREE.CanvasTexture(vc);
  emptyMap.anisotropy = 4;

  rackDoorCache = { populatedMap, populatedEmissive, emptyMap };
  return rackDoorCache;
}

// ---------------------------------------------------------------------------
// 5. High-Craft Industrial CRAC / PDF / UPS Front Faceplates (512x1024)
// ---------------------------------------------------------------------------
export function getEquipmentFaceTexture(
  kind: 'crac' | 'pdf' | 'ups',
  label: string,
  metric: string,
): THREE.CanvasTexture {
  const key = `${kind}:${label}:${metric}`;
  if (equipFaceCache.has(key)) return equipFaceCache.get(key)!;

  const [c, ctx] = makeCanvas(384, 768);

  if (kind === 'crac') {
    // Sleek Real-World Precision CRAC (Light Architectural Titanium-Silver + Dark Recessed Louver Grilles)
    const bg = ctx.createLinearGradient(0, 0, 384, 768);
    bg.addColorStop(0, '#cfd8e3');
    bg.addColorStop(0.5, '#bcc8d6');
    bg.addColorStop(1, '#9fb0c4');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, 384, 768);

    // Outer metallic chamfer frame
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 8;
    ctx.strokeRect(4, 4, 376, 760);

    // Dual-door vertical center seam
    ctx.fillStyle = '#475569';
    ctx.fillRect(190, 92, 4, 636);

    // Top illuminated dark-glass header fascia
    ctx.fillStyle = '#0b1220';
    ctx.fillRect(16, 16, 352, 72);
    ctx.fillStyle = '#0ea5e9';
    ctx.fillRect(16, 16, 352, 8);
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 28px system-ui, sans-serif';
    ctx.fillText(label, 30, 62);
    ctx.fillStyle = '#38bdf8';
    ctx.font = 'bold 16px monospace';
    ctx.fillText('PRECISION CRAC', 216, 60);

    // Recessed touchscreen HMI controller on upper-left door
    ctx.fillStyle = '#041221';
    ctx.fillRect(32, 114, 144, 116);
    ctx.strokeStyle = '#0ea5e9';
    ctx.lineWidth = 3;
    ctx.strokeRect(32, 114, 144, 116);
    ctx.fillStyle = '#38bdf8';
    ctx.font = 'bold 28px monospace';
    ctx.fillText('19.5°C', 46, 158);
    ctx.fillStyle = '#94a3b8';
    ctx.font = 'bold 16px monospace';
    ctx.fillText('RH 48% · EC', 46, 186);
    ctx.fillStyle = '#22c55e';
    ctx.font = 'bold 14px monospace';
    ctx.fillText('● COOLING ON', 46, 214);

    // Upper-right pressure gauge & EC fan status LEDs
    ctx.fillStyle = '#111c2b';
    ctx.fillRect(208, 114, 144, 116);
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 2;
    ctx.strokeRect(208, 114, 144, 116);
    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 14px monospace';
    ctx.fillText('AIRFLOW 64%', 222, 146);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(222, 160, 116, 12);
    ctx.fillStyle = '#0ea5e9';
    ctx.fillRect(222, 160, 76, 12);
    ctx.fillStyle = '#22c55e';
    ctx.fillText('● COMP OK', 222, 206);

    // Large dual recessed honeycomb air-return intake grilles
    for (const gx of [26, 204]) {
      ctx.fillStyle = '#080e17';
      ctx.fillRect(gx, 256, 154, 446);
      ctx.strokeStyle = '#475569';
      ctx.lineWidth = 3;
      ctx.strokeRect(gx, 256, 154, 446);
      // Angled louver slats
      for (let ly = 270; ly < 690; ly += 16) {
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(gx + 10, ly, 134, 8);
        ctx.fillStyle = '#0c1829';
        ctx.fillRect(gx + 10, ly + 8, 134, 4);
      }
    }

    // Brushed chrome door handles
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(172, 340, 10, 68);
    ctx.fillRect(202, 340, 10, 68);
  } else if (kind === 'pdf') {
    // Precision Power Distribution Cabinet (Dual A/B Red & Blue Feeder Matrix)
    ctx.fillStyle = '#131b29';
    ctx.fillRect(0, 0, 384, 768);
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 8;
    ctx.strokeRect(4, 4, 376, 760);

    // Top amber power header
    ctx.fillStyle = '#090e18';
    ctx.fillRect(16, 16, 352, 72);
    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(16, 16, 352, 8);
    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 28px system-ui, sans-serif';
    ctx.fillText(label, 30, 62);
    ctx.fillStyle = '#fbbf24';
    ctx.font = 'bold 16px monospace';
    ctx.fillText(metric, 200, 62);

    // Digital A/B Dual Power Analyzer HMI
    ctx.fillStyle = '#050c17';
    ctx.fillRect(28, 108, 328, 104);
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2.5;
    ctx.strokeRect(28, 108, 328, 104);
    ctx.fillStyle = '#ef4444';
    ctx.font = 'bold 18px monospace';
    ctx.fillText('BUS-A  230V · 50Hz', 44, 144);
    ctx.fillStyle = '#3b82f6';
    ctx.fillText('BUS-B  230V · 50Hz', 44, 174);
    ctx.fillStyle = '#22c55e';
    ctx.font = 'bold 14px monospace';
    ctx.fillText('● DUAL FEED BALANCED · SPD OK', 44, 200);

    // Dual A (Red) / B (Blue) Molded-Case Circuit Breaker Columns
    const drawBreakerBank = (bx: number, title: string, accent: string, bgTint: string) => {
      ctx.fillStyle = bgTint;
      ctx.fillRect(bx, 236, 152, 474);
      ctx.strokeStyle = accent;
      ctx.lineWidth = 3;
      ctx.strokeRect(bx, 236, 152, 474);

      ctx.fillStyle = accent;
      ctx.fillRect(bx, 236, 152, 34);
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 18px monospace';
      ctx.fillText(title, bx + 28, 259);

      // 12 individual circuit breaker switches with green ON indicators
      for (let row = 0; row < 12; row++) {
        const by = 284 + row * 34;
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(bx + 14, by, 124, 24);
        ctx.fillStyle = '#334155';
        ctx.fillRect(bx + 22, by + 5, 42, 14);
        ctx.fillStyle = '#22c55e';
        ctx.fillRect(bx + 114, by + 7, 14, 10);
      }
    };
    drawBreakerBank(28, 'A-FEED', '#dc2626', '#211218');
    drawBreakerBank(204, 'B-FEED', '#2563eb', '#101b30');
  } else {
    // Modular 120kVA UPS Power Tower
    ctx.fillStyle = '#151e2c';
    ctx.fillRect(0, 0, 384, 768);
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 8;
    ctx.strokeRect(4, 4, 376, 760);

    // Top emerald status crown
    ctx.fillStyle = '#090f19';
    ctx.fillRect(16, 16, 352, 72);
    ctx.fillStyle = '#10b981';
    ctx.fillRect(16, 16, 352, 8);
    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 26px system-ui, sans-serif';
    ctx.fillText(label, 28, 62);

    // Online UPS Power Mimic LCD Screen
    ctx.fillStyle = '#041418';
    ctx.fillRect(28, 108, 328, 126);
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 3;
    ctx.strokeRect(28, 108, 328, 126);
    ctx.fillStyle = '#34d399';
    ctx.font = 'bold 22px monospace';
    ctx.fillText(metric, 44, 146);
    // Mimic power flow diagram
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(46, 182);
    ctx.lineTo(334, 182);
    ctx.stroke();
    for (const [nx, txt] of [[48, 'AC'], [138, 'RECT'], [228, 'INV'], [300, 'BUS']] as const) {
      ctx.fillStyle = '#065f46';
      ctx.fillRect(nx, 168, 44, 28);
      ctx.fillStyle = '#ecfdf5';
      ctx.font = 'bold 12px monospace';
      ctx.fillText(txt, nx + 7, 187);
    }
    ctx.fillStyle = '#94a3b8';
    ctx.font = 'bold 13px monospace';
    ctx.fillText('BATT 100% · FLOAT · EFF 96.4%', 44, 220);

    // 4 Hot-Swap 30kVA Modular Power Shelves
    for (let m = 0; m < 4; m++) {
      const my = 258 + m * 112;
      ctx.fillStyle = '#0b121e';
      ctx.fillRect(28, my, 328, 96);
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 2;
      ctx.strokeRect(28, my, 328, 96);

      // Perforated cooling slots
      ctx.fillStyle = '#1e293b';
      for (let lx = 44; lx < 276; lx += 14) {
        ctx.fillRect(lx, my + 18, 8, 60);
      }
      // Module handle + green online LED
      ctx.fillStyle = '#64748b';
      ctx.fillRect(296, my + 24, 42, 48);
      ctx.fillStyle = '#00e632';
      ctx.beginPath();
      ctx.arc(317, my + 38, 6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 4;
  equipFaceCache.set(key, tex);
  return tex;
}

// ---------------------------------------------------------------------------
// 6. Soft Contact AO Shadow, Volumetric CFD Thermal Plume & Floor Light Pool
// ---------------------------------------------------------------------------
export function getSoftContactShadowTexture(): THREE.CanvasTexture {
  if (contactShadowCache) return contactShadowCache;
  const [c, ctx] = makeCanvas(128, 128);
  const grad = ctx.createRadialGradient(64, 64, 14, 64, 64, 62);
  grad.addColorStop(0, 'rgba(0, 0, 0, 0.72)');
  grad.addColorStop(0.55, 'rgba(0, 0, 0, 0.42)');
  grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 128, 128);
  contactShadowCache = new THREE.CanvasTexture(c);
  return contactShadowCache;
}

export function getThermalPlumeTexture(): THREE.CanvasTexture {
  if (thermalPlumeCache) return thermalPlumeCache;
  const [c, ctx] = makeCanvas(256, 256);
  // Soft vertical Gaussian heat-plume silhouette (dense core at bottom, diffusing upward)
  const grad = ctx.createRadialGradient(128, 152, 16, 128, 128, 122);
  grad.addColorStop(0, 'rgba(255, 255, 255, 0.92)');
  grad.addColorStop(0.35, 'rgba(255, 255, 255, 0.55)');
  grad.addColorStop(0.7, 'rgba(255, 255, 255, 0.16)');
  grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 256, 256);
  thermalPlumeCache = new THREE.CanvasTexture(c);
  return thermalPlumeCache;
}

export function getFloorLightPoolTexture(): THREE.CanvasTexture {
  if (lightPoolCache) return lightPoolCache;
  const [c, ctx] = makeCanvas(128, 128);
  const grad = ctx.createRadialGradient(64, 64, 4, 64, 64, 62);
  grad.addColorStop(0, 'rgba(186, 230, 253, 0.22)');
  grad.addColorStop(0.5, 'rgba(56, 189, 248, 0.08)');
  grad.addColorStop(1, 'rgba(56, 189, 248, 0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 128, 128);
  lightPoolCache = new THREE.CanvasTexture(c);
  return lightPoolCache;
}

// ---------------------------------------------------------------------------
// 7. Architectural Illuminated Aisle & Hall Signage (Native 3D Planes)
// ---------------------------------------------------------------------------
export function getAisleSignTexture(rowLabel: string): THREE.CanvasTexture {
  const key = `aisle:${rowLabel}`;
  if (signCache.has(key)) return signCache.get(key)!;
  const [c, ctx] = makeCanvas(512, 96);

  ctx.fillStyle = '#071322';
  ctx.fillRect(0, 0, 512, 96);
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 4;
  ctx.strokeRect(3, 3, 506, 90);

  ctx.fillStyle = '#0ea5e9';
  ctx.fillRect(14, 18, 8, 60);

  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 34px system-ui, sans-serif';
  ctx.fillText(rowLabel, 36, 58);

  ctx.fillStyle = '#38bdf8';
  ctx.font = 'bold 22px monospace';
  ctx.textAlign = 'right';
  ctx.fillText('COLD AISLE · 19.5°C', 490, 58);

  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 4;
  signCache.set(key, tex);
  return tex;
}

export function getHallBannerTexture(title: string): THREE.CanvasTexture {
  const key = `hall:${title}`;
  if (signCache.has(key)) return signCache.get(key)!;
  const [c, ctx] = makeCanvas(1024, 112);

  ctx.fillStyle = '#09111d';
  ctx.fillRect(0, 0, 1024, 112);
  ctx.fillStyle = '#0ea5e9';
  ctx.fillRect(0, 104, 1024, 8);
  ctx.fillStyle = 'rgba(56, 189, 248, 0.25)';
  ctx.fillRect(0, 0, 1024, 3);

  ctx.fillStyle = '#38bdf8';
  ctx.font = 'bold 22px monospace';
  ctx.fillText('NEXORA DIGITAL TWIN  //  TIER-IV MODULAR HALL', 36, 40);

  ctx.fillStyle = '#f1f5f9';
  ctx.font = 'bold 36px system-ui, sans-serif';
  ctx.fillText(title, 36, 86);

  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 4;
  signCache.set(key, tex);
  return tex;
}

// ---------------------------------------------------------------------------
// 8. Rear 42U Perforated Door (Shows Dual Red/Blue 0U PDUs & Green PSU LEDs)
// ---------------------------------------------------------------------------
export function getRackRearDoorTextures(): {
  map: THREE.CanvasTexture;
  emissive: THREE.CanvasTexture;
} {
  if (rearDoorCache) return rearDoorCache;
  const [c, ctx] = makeCanvas(256, 512);
  const [ec, ectx] = makeCanvas(256, 512);

  ctx.fillStyle = '#151e2b';
  ctx.fillRect(0, 0, 256, 512);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 506);

  // Split rear double-door vertical seam
  ctx.fillStyle = '#070b12';
  ctx.fillRect(18, 18, 220, 476);

  ectx.fillStyle = '#000000';
  ectx.fillRect(0, 0, 256, 512);

  // Vertical 0U Red (A-Feed) & Blue (B-Feed) smart PDU columns visible behind rear mesh
  ctx.fillStyle = '#7f1d1d';
  ctx.fillRect(24, 34, 16, 444);
  ctx.fillStyle = '#1e3a8a';
  ctx.fillRect(216, 34, 16, 444);
  ectx.fillStyle = '#ef4444';
  ectx.fillRect(28, 232, 8, 22);
  ectx.fillStyle = '#3b82f6';
  ectx.fillRect(220, 232, 8, 22);

  // Rear PSU & fan bay silhouettes with tiny green PSU OK LEDs
  for (let i = 0; i < 12; i++) {
    const sy = 44 + i * 36;
    ctx.fillStyle = '#1b2636';
    ctx.fillRect(46, sy, 164, 24);
    if (i >= 5) {
      ectx.fillStyle = '#00dc30';
      ectx.fillRect(54, sy + 9, 5, 5);
      ectx.fillRect(198, sy + 9, 5, 5);
    }
  }

  // Fine honeycomb rear mesh veil + center split stile
  ctx.fillStyle = 'rgba(12, 19, 31, 0.45)';
  for (let y = 20; y < 492; y += 5) ctx.fillRect(18, y, 220, 1.5);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(123, 16, 10, 480);
  ctx.fillStyle = '#64748b';
  ctx.fillRect(126, 224, 4, 60);

  const map = new THREE.CanvasTexture(c);
  map.anisotropy = 4;
  const emissive = new THREE.CanvasTexture(ec);
  emissive.anisotropy = 4;
  rearDoorCache = { map, emissive };
  return rearDoorCache;
}

// ---------------------------------------------------------------------------
// 9. NOC Wall Operations 3-Screen Telemetry Console Texture
// ---------------------------------------------------------------------------
export function getNocWallMonitorTexture(
  rackCount: number,
  totalKw: number,
  cracCount: number,
  avgUtilPct: number,
): THREE.CanvasTexture {
  const key = `${rackCount}:${totalKw}:${cracCount}:${avgUtilPct}`;
  if (nocMonitorCache.has(key)) return nocMonitorCache.get(key)!;

  const [c, ctx] = makeCanvas(768, 256);
  ctx.fillStyle = '#050b14';
  ctx.fillRect(0, 0, 768, 256);

  // 3 distinct monitor bezel panels
  const drawPanel = (x: number, w: number, title: string, accent: string) => {
    ctx.fillStyle = '#091423';
    ctx.fillRect(x, 12, w, 232);
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 4;
    ctx.strokeRect(x, 12, w, 232);
    ctx.fillStyle = accent;
    ctx.fillRect(x, 12, w, 5);
    ctx.fillStyle = '#94a3b8';
    ctx.font = 'bold 14px monospace';
    ctx.fillText(title, x + 16, 40);
  };

  // Left Screen: PUE & Power KPI
  drawPanel(12, 240, 'POWER & PUE MONITOR', '#f59e0b');
  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 42px monospace';
  ctx.fillText('PUE 1.28', 28, 102);
  ctx.fillStyle = '#fbbf24';
  ctx.font = 'bold 26px monospace';
  ctx.fillText(`${totalKw.toFixed(1)} kW`, 28, 148);
  ctx.fillStyle = '#64748b';
  ctx.font = 'bold 14px monospace';
  ctx.fillText(`RACKS: ${rackCount}  ·  U-LOAD: ${avgUtilPct}%`, 28, 186);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(28, 202, 204, 16);
  ctx.fillStyle = '#10b981';
  ctx.fillRect(28, 202, Math.max(22, Math.min(204, (avgUtilPct / 100) * 204)), 16);

  // Center Screen: Thermal & Airflow Telemetry Waveforms
  drawPanel(264, 240, 'THERMAL CFD TREND', '#38bdf8');
  ctx.strokeStyle = 'rgba(56, 189, 248, 0.18)';
  ctx.lineWidth = 1;
  for (let gy = 70; gy <= 210; gy += 35) {
    ctx.beginPath();
    ctx.moveTo(280, gy);
    ctx.lineTo(488, gy);
    ctx.stroke();
  }
  // Cold supply wave (cyan)
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 3;
  ctx.beginPath();
  for (let i = 0; i <= 14; i++) {
    const px = 280 + i * 14.8;
    const py = 182 - Math.sin(i * 0.55) * 10 - (i % 3) * 2;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();
  // Hot return wave (amber-rose)
  ctx.strokeStyle = '#fb7185';
  ctx.lineWidth = 3;
  ctx.beginPath();
  for (let i = 0; i <= 14; i++) {
    const px = 280 + i * 14.8;
    const py = 112 - Math.cos(i * 0.45) * 14 - (i % 2) * 3;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.fillStyle = '#38bdf8';
  ctx.font = 'bold 14px monospace';
  ctx.fillText('SUPPLY 19.5°C', 280, 224);
  ctx.fillStyle = '#fb7185';
  ctx.fillText('RETURN 30.8°C', 392, 224);

  // Right Screen: HVAC & Infrastructure Health
  drawPanel(516, 240, 'INFRASTRUCTURE HEALTH', '#10b981');
  const rows = [
    ['CRAC COOLING', `${cracCount} ONLINE`, '#38bdf8'],
    ['UPS DUAL BUS', 'A+B 99.9%', '#10b981'],
    ['COLD AISLE', '48% RH OK', '#34d399'],
    ['FM-200 FIRE', 'ARMED STD', '#22c55e'],
  ] as const;
  rows.forEach(([k, v, col], idx) => {
    const ry = 76 + idx * 42;
    ctx.fillStyle = '#0f1c2e';
    ctx.fillRect(530, ry - 20, 212, 32);
    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 13px monospace';
    ctx.fillText(k, 540, ry);
    ctx.fillStyle = col;
    ctx.fillText(v, 650, ry);
  });

  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 4;
  nocMonitorCache.set(key, tex);
  return tex;
}

// ---------------------------------------------------------------------------
// 10. Architectural Illuminated Green EXIT Sign
// ---------------------------------------------------------------------------
export function getExitSignTexture(): THREE.CanvasTexture {
  if (exitSignCache) return exitSignCache;
  const [c, ctx] = makeCanvas(256, 96);
  ctx.fillStyle = '#064e3b';
  ctx.fillRect(0, 0, 256, 96);
  ctx.strokeStyle = '#34d399';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 90);
  ctx.fillStyle = '#ecfdf5';
  ctx.font = 'bold 34px system-ui, sans-serif';
  ctx.fillText('EXIT', 28, 60);
  ctx.font = 'bold 22px system-ui, sans-serif';
  ctx.fillStyle = '#6ee7b7';
  ctx.fillText('安全出口 →', 122, 58);
  exitSignCache = new THREE.CanvasTexture(c);
  return exitSignCache;
}

// ---------------------------------------------------------------------------
// 11. Subtle Architectural Studio Gradient Sky Dome Texture
// ---------------------------------------------------------------------------
export function getStudioSkyGradientTexture(): THREE.CanvasTexture {
  if (skyDomeCache) return skyDomeCache;
  const [c, ctx] = makeCanvas(64, 512);
  const grad = ctx.createLinearGradient(0, 0, 0, 512);
  grad.addColorStop(0, '#050914');     // deep midnight zenith
  grad.addColorStop(0.45, '#0b1526');  // cool architectural slate
  grad.addColorStop(0.55, '#13233b');  // soft studio horizon glow
  grad.addColorStop(0.7, '#09111f');   // lower floor shadow falloff
  grad.addColorStop(1, '#04070d');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 64, 512);
  skyDomeCache = new THREE.CanvasTexture(c);
  return skyDomeCache;
}

// ---------------------------------------------------------------------------
// 12. Single-Rack Top-of-Rack Illuminated Smart LCD Bezel
// ---------------------------------------------------------------------------
export function getRackSmartHeaderTexture(
  rackName: string,
  usedU: number,
  totalU: number,
  watts: number,
): THREE.CanvasTexture {
  const key = `${rackName}:${usedU}/${totalU}:${watts}`;
  if (rackHeaderCache.has(key)) return rackHeaderCache.get(key)!;
  const [c, ctx] = makeCanvas(1024, 128);

  // Brushed gunmetal top bezel housing
  const bg = ctx.createLinearGradient(0, 0, 1024, 0);
  bg.addColorStop(0, '#0c1320');
  bg.addColorStop(0.5, '#152033');
  bg.addColorStop(1, '#0c1320');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, 1024, 128);

  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, 1020, 124);
  ctx.fillStyle = '#0ea5e9';
  ctx.fillRect(4, 4, 1016, 6);

  // Left: Cabinet ID + Online indicator
  ctx.fillStyle = '#00e632';
  ctx.beginPath();
  ctx.arc(46, 68, 12, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 52px system-ui, sans-serif';
  ctx.fillText(rackName, 76, 86);

  // Center-right: Smart OLED Telemetry Readout Strip
  ctx.fillStyle = '#040c17';
  ctx.fillRect(380, 24, 616, 82);
  ctx.strokeStyle = '#0284c7';
  ctx.lineWidth = 2;
  ctx.strokeRect(380, 24, 616, 82);

  const kw = (watts / 1000).toFixed(2);
  const items = [
    ['CAPACITY', `${usedU}/${totalU} U`, '#38bdf8', 402],
    ['RATED LOAD', `${kw} kW`, '#fbbf24', 604],
    ['INTAKE', '21.4°C · OK', '#34d399', 804],
  ] as const;

  items.forEach(([label, val, col, x]) => {
    ctx.fillStyle = '#64748b';
    ctx.font = 'bold 16px monospace';
    ctx.fillText(label, x, 48);
    ctx.fillStyle = col;
    ctx.font = 'bold 28px monospace';
    ctx.fillText(val, x, 86);
  });

  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 4;
  rackHeaderCache.set(key, tex);
  return tex;
}

// ---------------------------------------------------------------------------
// 13. Rear 0U Vertical Smart PDU Digital Amp Meter Readout
// ---------------------------------------------------------------------------
export function getPduMeterTexture(feed: 'A' | 'B', kw: number): THREE.CanvasTexture {
  const amps = Math.max(0.4, (kw * 1000) / 2 / 220).toFixed(1);
  const key = `${feed}:${amps}`;
  if (pduMeterCache.has(key)) return pduMeterCache.get(key)!;
  const [c, ctx] = makeCanvas(128, 256);

  const accent = feed === 'A' ? '#ef4444' : '#3b82f6';
  ctx.fillStyle = '#090e18';
  ctx.fillRect(0, 0, 128, 256);
  ctx.strokeStyle = accent;
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 122, 250);

  ctx.fillStyle = accent;
  ctx.fillRect(6, 6, 116, 38);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 22px monospace';
  ctx.fillText(`PDU-${feed}`, 26, 33);

  // Digital 7-segment style OLED amp meter
  ctx.fillStyle = '#020810';
  ctx.fillRect(14, 58, 100, 110);
  ctx.fillStyle = feed === 'A' ? '#fca5a5' : '#93c5fd';
  ctx.font = 'bold 36px monospace';
  ctx.fillText(`${amps}A`, 18, 108);
  ctx.fillStyle = '#34d399';
  ctx.font = 'bold 20px monospace';
  ctx.fillText('230V', 32, 148);

  // Outlet bank status LEDs
  for (let i = 0; i < 4; i++) {
    ctx.fillStyle = '#00e632';
    ctx.beginPath();
    ctx.arc(32 + i * 21, 212, 6, 0, Math.PI * 2);
    ctx.fill();
  }

  const tex = new THREE.CanvasTexture(c);
  pduMeterCache.set(key, tex);
  return tex;
}

// ---------------------------------------------------------------------------
// 14. Architectural 600x600mm Suspended Acoustic Ceiling Grid
// ---------------------------------------------------------------------------
export function getCeilingGridTexture(): THREE.CanvasTexture {
  if (ceilingGridCache) return ceilingGridCache;
  const [c, ctx] = makeCanvas(256, 256);

  ctx.fillStyle = '#94a3b8'; // T-bar aluminum suspension grid
  ctx.fillRect(0, 0, 256, 256);

  for (let gx = 0; gx < 2; gx++) {
    for (let gy = 0; gy < 2; gy++) {
      const x = gx * 128;
      const y = gy * 128;
      ctx.fillStyle = '#d8e0ea';
      ctx.fillRect(x + 4, y + 4, 120, 120);
      // Micro acoustic perforation texture
      ctx.fillStyle = 'rgba(71, 85, 105, 0.12)';
      for (let i = 0; i < 60; i++) {
        ctx.fillRect(x + 10 + ((i * 37) % 108), y + 10 + ((i * 53) % 108), 2, 2);
      }
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  ceilingGridCache = tex;
  return tex;
}

