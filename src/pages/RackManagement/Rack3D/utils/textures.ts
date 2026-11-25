import * as THREE from 'three';
import type { DeviceHealthStatus, DevicePhysicalPortProfile } from '../../types';
import { resolveHardwareFaceplateSpec } from '../deviceSlotSpec';

const textureCache = new Map<string, THREE.CanvasTexture>();

/** Draw a small recessed lens with a controlled halo. The glow is deliberately
 * subtle so a dense port bank still reads as hardware instead of neon art. */
function drawLedLens(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
  active: boolean,
  radius = 5,
) {
  ctx.save();
  if (active) {
    ctx.shadowColor = color;
    ctx.shadowBlur = radius * 2.5;
  }
  const lens = ctx.createRadialGradient(x - radius * 0.35, y - radius * 0.35, radius * 0.1, x, y, radius);
  lens.addColorStop(0, active ? '#f8fffb' : '#40515a');
  lens.addColorStop(0.22, color);
  lens.addColorStop(1, active ? '#0b5a43' : '#101b24');
  ctx.fillStyle = lens;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = active ? `${color}cc` : '#334155';
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.restore();
}

function drawPortCage(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  active: boolean,
  ledY: number,
) {
  const cavity = ctx.createLinearGradient(x, y, x, y + height);
  cavity.addColorStop(0, '#02050a');
  cavity.addColorStop(0.5, '#111d28');
  cavity.addColorStop(1, '#03070d');
  ctx.fillStyle = cavity;
  ctx.fillRect(x, y, width, height);
  ctx.strokeStyle = active ? '#3e6d67' : '#475569';
  ctx.lineWidth = active ? 1.6 : 1.1;
  ctx.strokeRect(x, y, width, height);

  // SFP cage contacts / transceiver mouth.
  ctx.fillStyle = '#0a1119';
  ctx.fillRect(x + 2, y + 5, Math.max(2, width - 4), Math.max(4, height - 10));
  ctx.strokeStyle = '#263746';
  ctx.lineWidth = 0.7;
  ctx.beginPath();
  for (let contact = 1; contact < 4; contact++) {
    const contactX = x + (width * contact) / 4;
    ctx.moveTo(contactX, y + 8);
    ctx.lineTo(contactX, y + height - 8);
  }
  ctx.stroke();
  drawLedLens(ctx, x + width / 2, ledY, active ? '#41f1a6' : '#1e3a3a', active, Math.max(2.5, Math.min(4.5, width * 0.13)));
}

/**
 * EIA-310-D compliant vertical mounting rail texture with U markings and square cage nut holes.
 */
export function getRackRailTexture(totalU = 42): THREE.CanvasTexture {
  const cacheKey = `rack_rail_${totalU}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 256;
  const height = totalU * 128;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // Gunmetal matte steel background
  const grad = ctx.createLinearGradient(0, 0, width, 0);
  grad.addColorStop(0, '#242e3d');
  grad.addColorStop(0.25, '#334155');
  grad.addColorStop(0.75, '#242e3d');
  grad.addColorStop(1, '#18202c');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, width, height);

  // Outer bevel line
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 3;
  ctx.strokeRect(1, 1, width - 2, height - 2);

  // Render each U division (U1 at bottom)
  for (let u = 1; u <= totalU; u++) {
    const yTop = (totalU - u) * 128;
    const isMajor = u % 5 === 0 || u === 1 || u === totalU;

    // Horizontal U separator line
    ctx.strokeStyle = isMajor ? '#38bdf8' : '#334155';
    ctx.lineWidth = isMajor ? 2.5 : 1.5;
    ctx.beginPath();
    ctx.moveTo(8, yTop + 127);
    ctx.lineTo(width - 8, yTop + 127);
    ctx.stroke();

    // 3 standard EIA-310-D square mounting holes
    const holePositions = [32, 64, 96];
    holePositions.forEach(offsetY => {
      const hy = yTop + offsetY - 8;
      const hx = width - 68;
      ctx.fillStyle = '#090d16';
      ctx.fillRect(hx, hy, 24, 16);
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(hx, hy, 24, 16);
    });

    // U Number label
    ctx.fillStyle = isMajor ? '#38bdf8' : '#cbd5e1';
    ctx.font = isMajor ? 'bold 44px system-ui, -apple-system, sans-serif' : 'bold 36px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${u}`, 72, yTop + 64);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Top nameplate texture for the rack header.
 */
export function getNameplateTexture(name: string): THREE.CanvasTexture {
  const cacheKey = `nameplate_${name}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 1024;
  const height = 160;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // Dark matte steel bar
  const grad = ctx.createLinearGradient(0, 0, width, height);
  grad.addColorStop(0, '#1e293b');
  grad.addColorStop(0.5, '#0f172a');
  grad.addColorStop(1, '#1e293b');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 3;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 52px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(name.toUpperCase(), width / 2, height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.anisotropy = 16;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Honeycomb mesh texture for the rack door.
 */
export function getHoneycombDoorTexture(): THREE.CanvasTexture {
  const cacheKey = 'honeycomb_door';
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, size, size);

  const hexRadius = 7;
  const hexWidth = hexRadius * Math.sqrt(3);
  const hexHeight = hexRadius * 2;
  const rowSpacing = hexHeight * 0.75;

  ctx.fillStyle = 'rgba(0, 0, 0, 0.85)';
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 1;

  for (let y = 0; y < size + hexHeight; y += rowSpacing) {
    const rowIdx = Math.floor(y / rowSpacing);
    const xOffset = (rowIdx % 2 === 1) ? hexWidth / 2 : 0;

    for (let x = -hexWidth; x < size + hexWidth; x += hexWidth) {
      const cx = x + xOffset;
      const cy = y;

      ctx.beginPath();
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i;
        const hx = cx + hexRadius * Math.cos(angle);
        const hy = cy + hexRadius * Math.sin(angle);
        if (i === 0) ctx.moveTo(hx, hy);
        else ctx.lineTo(hx, hy);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(4, 16);
  texture.anisotropy = 16;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Switch Front Faceplate (Ports, SFP+ cages, minimal brand/model badge).
 */
export function getSwitchFrontTexture(
  deviceName = 'SWITCH',
  vendor = 'Huawei',
  model = 'CE6885',
  heightU = 1,
  connectedPortNumbers: number[] = [],
  healthStatus: DeviceHealthStatus = 'unknown',
): THREE.CanvasTexture {
  const portsKey = connectedPortNumbers.slice().sort((a, b) => a - b).join('_');
  const cacheKey = `switch_front_${deviceName}_${vendor}_${model}_${heightU}_${healthStatus}_${portsKey}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 2048;
  const height = heightU * 256;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // Dark industrial gunmetal chassis face
  const grad = ctx.createLinearGradient(0, 0, 0, height);
  grad.addColorStop(0, '#283344');
  grad.addColorStop(0.5, '#192230');
  grad.addColorStop(1, '#283344');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  // Left Brand & Model Plaque (X: 36 ~ 300)
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(36, 20, 270, height - 40);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(36, 20, 270, height - 40);

  // Device Name
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 34px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(deviceName.toUpperCase().slice(0, 12), 48, height / 2 - 22);

  // Vendor + Model
  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 18px system-ui, -apple-system, sans-serif';
  ctx.fillText(`${vendor.toUpperCase()} ${model.toUpperCase().slice(0, 10)}`, 48, height / 2 + 24);

  // Recessed status cluster. The procedural 3D lenses are animated separately;
  // these silkscreen marks keep the faceplate legible at full-rack distance.
  ctx.fillStyle = '#060b12';
  ctx.fillRect(238, 20, 76, height - 40);
  ctx.strokeStyle = '#263746';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(238, 20, 76, height - 40);

  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 11px monospace';
  ctx.textAlign = 'right';
  const statusRows = [
    { label: 'PWR', color: healthStatus === 'offline' ? '#1e293b' : '#38d996', active: healthStatus !== 'offline' },
    { label: 'SYS', color: healthStatus === 'critical' ? '#ef4444' : healthStatus === 'healthy' || healthStatus === 'warning' ? '#38d996' : '#416274', active: healthStatus !== 'offline' },
    { label: 'ALM', color: healthStatus === 'critical' ? '#ef4444' : healthStatus === 'warning' ? '#f59e0b' : '#1e293b', active: healthStatus === 'critical' || healthStatus === 'warning' },
  ];
  statusRows.forEach((row, index) => {
    const y = height / 2 + (index - 1) * 32;
    ctx.fillStyle = '#94a3b8';
    ctx.fillText(row.label, 274, y + 3);
    drawLedLens(ctx, 295, y, row.color, row.active, 4.5);
  });

  // Zone 1: Dedicated Management, Console & USB Section (X: 316 ~ 476)
  ctx.fillStyle = '#0b111e';
  ctx.fillRect(316, 20, 160, height - 40);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2;
  ctx.strokeRect(316, 20, 160, height - 40);

  // MGMT RJ45 Jack (Top Left)
  ctx.fillStyle = '#020617';
  ctx.fillRect(326, 32, 36, 44);
  ctx.strokeStyle = '#eab308'; // Yellow MGMT tab
  ctx.strokeRect(326, 32, 36, 44);
  ctx.fillStyle = '#22c55e';
  ctx.fillRect(338, 24, 12, 4); // MGMT Link LED
  ctx.fillStyle = '#cbd5e1';
  ctx.font = 'bold 10px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('MGMT', 344, 86);

  // CONSOLE RJ45 Jack (Top Right)
  ctx.fillStyle = '#020617';
  ctx.fillRect(376, 32, 36, 44);
  ctx.strokeStyle = '#06b6d4'; // Cyan Console tab
  ctx.strokeRect(376, 32, 40, 44);
  ctx.fillStyle = '#cbd5e1';
  ctx.fillText('CONSOLE', 394, 86);

  // USB 2.0/3.0 Type-A Port (Right)
  ctx.fillStyle = '#020617';
  ctx.fillRect(426, 40, 40, 26);
  ctx.strokeStyle = '#64748b';
  ctx.strokeRect(426, 40, 40, 26);
  ctx.fillStyle = '#38bdf8'; // Blue USB 3.0 insert
  ctx.fillRect(436, 45, 20, 16);
  ctx.fillStyle = '#94a3b8';
  ctx.fillText('USB', 446, 86);

  // Zone 2: Business Traffic Ports (Adaptive: 48 ports for S6850 / 24 ports for others)
  const is48Port = model.includes('6850') || model.includes('6800') || model.includes('48') || model.includes('54') || model.includes('56');
  const cols = is48Port ? 24 : 12;
  const startX = 490;
  const portW = is48Port ? 28 : 42;
  const portH = 48;
  const gapX = is48Port ? 34 : 50;

  for (let c = 0; c < cols; c++) {
    const px = startX + c * gapX + (is48Port ? Math.floor(c / 4) * 6 : Math.floor(c / 4) * 12);

    // Top port (Even port: 0, 2, 4, 6... / 1, 3, 5, 7...)
    const topPortNum = c * 2;
    const isTopConnected = connectedPortNumbers.includes(topPortNum);
    const pyTop = height / 2 - portH - 6;
    drawPortCage(ctx, px, pyTop, portW, portH, isTopConnected, pyTop - 7);

    // Bottom port
    const bottomPortNum = c * 2 + 1;
    const isBottomConnected = connectedPortNumbers.includes(bottomPortNum);
    const pyBottom = height / 2 + 6;
    drawPortCage(ctx, px, pyBottom, portW, portH, isBottomConnected, pyBottom + portH + 7);
  }

  // Zone 3: High-Speed 40G/100G QSFP28 Uplink Area
  const qsfpStartX = is48Port ? (startX + 24 * gapX + 42) : 1680;
  const qsfpW = is48Port ? 56 : 68;
  const qsfpH = 50;
  const qsfpCols = is48Port ? 6 : 4;

  for (let q = 0; q < qsfpCols; q++) {
    const qx = qsfpStartX + q * (qsfpW + 10);
    const qsfpConnected = connectedPortNumbers.includes(49 + q);
    drawPortCage(ctx, qx, height / 2 - qsfpH / 2, qsfpW, qsfpH, qsfpConnected, height / 2 - qsfpH / 2 - 7);

    // QSFP Pull-tab & LED
    ctx.fillStyle = qsfpConnected ? '#22c55e' : '#1e3a46';
    ctx.fillRect(qx + 12, height / 2 - qsfpH / 2 - 6, 28, 4);
    drawLedLens(ctx, qx + qsfpW - 12, height / 2 - qsfpH / 2 - 7, qsfpConnected ? '#41f1a6' : '#1e3a3a', qsfpConnected, 3.5);
    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`100G-${q + 1}`, qx + qsfpW / 2, height / 2 + qsfpH / 2 + 16);
  }




  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Switch Rear Faceplate (Dual Hot-Swap PSUs, Fan exhaust, Rear MGMT).
 */
export function getSwitchRearTexture(
  vendor = 'Huawei',
  model = 'CE6885',
  heightU = 1
): THREE.CanvasTexture {
  const cacheKey = `switch_rear_${vendor}_${model}_${heightU}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 2048;
  const height = heightU * 256;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // Dark matte chassis rear
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  // Left Dual Hot-Swap Power Supply Units (PSU1 & PSU2)
  const psuWidth = 360;
  [40, 440].forEach((psuX, idx) => {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(psuX, 20, psuWidth, height - 40);
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 2.5;
    ctx.strokeRect(psuX, 20, psuWidth, height - 40);

    // AC Power socket
    ctx.fillStyle = '#020617';
    ctx.fillRect(psuX + 30, height / 2 - 36, 90, 72);
    ctx.strokeStyle = '#94a3b8';
    ctx.strokeRect(psuX + 30, height / 2 - 36, 90, 72);

    // Power handle
    ctx.fillStyle = '#475569';
    ctx.fillRect(psuX + psuWidth - 60, 36, 30, height - 72);

    // PSU Label
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 22px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`PSU-${idx + 1} 600W`, psuX + 140, height / 2 - 10);
    ctx.fillStyle = '#22c55e';
    ctx.fillText('● AC OK', psuX + 140, height / 2 + 20);
  });

  // Middle Dual Fan Modules (FAN 1..4)
  const fanStartX = 840;
  const fanModuleW = 200;
  for (let f = 0; f < 4; f++) {
    const fx = fanStartX + f * (fanModuleW + 20);
    ctx.fillStyle = '#090d16';
    ctx.fillRect(fx, 20, fanModuleW, height - 40);
    ctx.strokeStyle = '#334155';
    ctx.strokeRect(fx, 20, fanModuleW, height - 40);

    // Circular fan exhaust grill
    ctx.beginPath();
    ctx.arc(fx + fanModuleW / 2, height / 2, (height - 60) / 2, 0, Math.PI * 2);
    ctx.fillStyle = '#020617';
    ctx.fill();
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = '#64748b';
    ctx.font = 'bold 16px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`FAN ${f + 1}`, fx + fanModuleW / 2, height / 2);
  }

  // Right Side Grounding Lug & Console/MGMT
  const rightX = width - 280;
  ctx.fillStyle = '#090d16';
  ctx.fillRect(rightX, 20, 240, height - 40);
  ctx.strokeStyle = '#475569';
  ctx.strokeRect(rightX, 20, 240, height - 40);

  ctx.fillStyle = '#cbd5e1';
  ctx.font = 'bold 18px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('MGMT / CONSOLE', rightX + 120, height / 2 - 14);
  ctx.fillStyle = '#eab308';
  ctx.fillText('⏚ GND', rightX + 120, height / 2 + 18);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Server Front Faceplate (Hot-swap drive bays, power button, brand plaque).
 */
export function getServerFrontTexture(
  deviceName = 'SERVER',
  vendor = 'Dell',
  model = 'R760',
  heightU = 2
): THREE.CanvasTexture {
  const cacheKey = `server_front_${deviceName}_${vendor}_${model}_${heightU}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 2048;
  const height = heightU * 256;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // Dark matte steel chassis
  ctx.fillStyle = '#18202c';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  // Left Server Control Panel & Plaque
  ctx.fillStyle = '#090d16';
  ctx.fillRect(36, 24, 420, height - 48);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(36, 24, 420, height - 48);

  // Power Button with illuminated ring
  ctx.beginPath();
  ctx.arc(84, height / 2 - 24, 26, 0, Math.PI * 2);
  ctx.fillStyle = '#0284c7';
  ctx.fill();
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 3;
  ctx.stroke();

  // Device Name
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 40px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(deviceName.toUpperCase().slice(0, 15), 130, height / 2 - 24);

  // Vendor + Model
  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 24px system-ui, -apple-system, sans-serif';
  ctx.fillText(`${vendor.toUpperCase()} ${model.toUpperCase().slice(0, 12)}`, 56, height / 2 + 30);

  // Hot-swap Drive Bays Array
  const bayRows = Math.min(4, Math.max(1, heightU));
  const bayCols = 8;
  const startX = 480;
  const availableW = width - startX - 40;
  const bayW = availableW / bayCols - 14;
  const bayH = (height - 48) / bayRows - 10;

  for (let r = 0; r < bayRows; r++) {
    for (let c = 0; c < bayCols; c++) {
      const bx = startX + c * (bayW + 14);
      const by = 24 + r * (bayH + 10);

      ctx.fillStyle = '#1e293b';
      ctx.fillRect(bx, by, bayW, bayH);
      ctx.strokeStyle = '#475569';
      ctx.lineWidth = 2;
      ctx.strokeRect(bx, by, bayW, bayH);

      // Latch handle
      ctx.fillStyle = '#334155';
      ctx.fillRect(bx + 8, by + bayH - 24, bayW - 16, 16);

      // Activity LED
      ctx.fillStyle = '#10b981';
      ctx.fillRect(bx + 8, by + 8, 12, 8);

      ctx.fillStyle = '#94a3b8';
      ctx.font = 'bold 18px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('SAS', bx + bayW / 2, by + bayH / 2 - 4);
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Server Rear Faceplate (Dual 1600W PSUs, PCIe expansion slots, high CFM exhaust fans).
 */
export function getServerRearTexture(
  vendor = 'Dell',
  model = 'R760',
  heightU = 2
): THREE.CanvasTexture {
  const cacheKey = `server_rear_${vendor}_${model}_${heightU}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 2048;
  const height = heightU * 256;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // Dark steel rear
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  // Dual Hot-Swap Server Power Supplies (PSU1 & PSU2)
  const psuW = 420;
  [40, 480].forEach((psuX, idx) => {
    ctx.fillStyle = '#090d16';
    ctx.fillRect(psuX, 20, psuW, height - 40);
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 2.5;
    ctx.strokeRect(psuX, 20, psuW, height - 40);

    ctx.fillStyle = '#020617';
    ctx.fillRect(psuX + 30, height / 2 - 44, 110, 88);
    ctx.strokeStyle = '#94a3b8';
    ctx.strokeRect(psuX + 30, height / 2 - 44, 110, 88);

    // Orange release latch
    ctx.fillStyle = '#ea580c';
    ctx.fillRect(psuX + psuW - 50, 36, 24, height - 72);

    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 24px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`PSU-${idx + 1} 1400W`, psuX + 160, height / 2 - 12);
    ctx.fillStyle = '#10b981';
    ctx.fillText('● 80 PLUS PLATINUM', psuX + 160, height / 2 + 22);
  });

  // Middle PCIe Riser Bracket Area
  const pcieX = 940;
  const pcieW = width - pcieX - 40;
  ctx.fillStyle = '#090d16';
  ctx.fillRect(pcieX, 20, pcieW, height - 40);
  ctx.strokeStyle = '#475569';
  ctx.strokeRect(pcieX, 20, pcieW, height - 40);

  // PCIe Slots
  const slotCount = 4;
  const slotW = (pcieW - 60) / slotCount;
  for (let s = 0; s < slotCount; s++) {
    const sx = pcieX + 30 + s * slotW;
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(sx, 40, slotW - 16, height - 80);
    ctx.strokeStyle = '#64748b';
    ctx.strokeRect(sx, 40, slotW - 16, height - 80);

    ctx.fillStyle = '#64748b';
    ctx.font = 'bold 16px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`SLOT ${s + 1}`, sx + (slotW - 16) / 2, height / 2);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Generic Appliance Front Faceplate.
 */
export function getGenericFrontTexture(
  deviceName = 'APPLIANCE',
  role = 'device',
  vendor = 'Generic',
  model = '',
  heightU = 1
): THREE.CanvasTexture {
  const cacheKey = `generic_front_${deviceName}_${role}_${vendor}_${model}_${heightU}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 2048;
  const height = heightU * 256;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  // Center plaque
  ctx.fillStyle = '#090d16';
  ctx.fillRect(width / 2 - 450, height / 2 - 64, 900, 128);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(width / 2 - 450, height / 2 - 64, 900, 128);

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 44px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(deviceName.toUpperCase(), width / 2, height / 2 - 20);

  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 24px system-ui, -apple-system, sans-serif';
  ctx.fillText(`${vendor.toUpperCase()} ${role.toUpperCase()} ${model.toUpperCase()}`, width / 2, height / 2 + 28);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}

/**
 * Generic Appliance Rear Faceplate.
 */
export function getGenericRearTexture(
  vendor = 'Generic',
  heightU = 1
): THREE.CanvasTexture {
  const cacheKey = `generic_rear_${vendor}_${heightU}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const width = 2048;
  const height = heightU * 256;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 6;
  ctx.strokeRect(4, 4, width - 8, height - 8);

  // Dual AC inputs
  [60, 480].forEach((psuX, i) => {
    ctx.fillStyle = '#090d16';
    ctx.fillRect(psuX, 24, 380, height - 48);
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 2;
    ctx.strokeRect(psuX, 24, 380, height - 48);

    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 22px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`AC INLET ${i + 1}`, psuX + 190, height / 2);
  });

  // Vent grill
  const ventX = 900;
  const ventW = width - ventX - 60;
  ctx.fillStyle = '#090d16';
  ctx.fillRect(ventX, 24, ventW, height - 48);
  ctx.strokeStyle = '#475569';
  ctx.strokeRect(ventX, 24, ventW, height - 48);

  ctx.fillStyle = '#64748b';
  ctx.font = 'bold 20px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('EXHAUST VENTILATION', ventX + ventW / 2, height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}


/**
 * 2048x256 brushed-metal silkscreen faceplate overlay for RackVision v2 GLB devices.
 * Draws authentic brand/model typography, brushed metal grain, and exact port numbers
 * aligned 1:1 with the 3D recessed port cages, leaving transparent windows over the
 * physical cavities & LEDs so real 3D depth shines through.
 */
export function getRealisticFaceplateSilkscreenTexture(
  deviceName: string,
  vendor: string,
  model: string,
  role: string,
  assetKey?: string,
  heightU = 1,
  physicalPortProfile?: DevicePhysicalPortProfile | null,
): THREE.CanvasTexture {
  const idStr = `${assetKey || ''} ${vendor} ${model} ${role}`.toLowerCase();
  const spec = resolveHardwareFaceplateSpec({ vendor, model, role, assetKey, heightU, physicalPortProfile });
  const kind = idStr.includes('s6800') || idStr.includes('s6850') || idStr.includes('s6805')
    ? 's6800'
    : spec.formFactor === 'ups'
      ? 'ups'
      : spec.formFactor === 'chassis'
        ? 'chassis'
        : spec.formFactor === 'firewall'
          ? 'firewall'
          : spec.formFactor === 'wireless_ac'
            ? 'wireless_ac'
            : 'switch';

  const realCountTag = physicalPortProfile ? `${physicalPortProfile.total_ports}p_${physicalPortProfile.up_count}u` : 'static';
  const cacheKey = `v4_silkscreen_${kind}_${spec.vendorStyle}_${spec.portDensity}_${heightU}_${realCountTag}_${deviceName}_${vendor}_${model}`;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey)!;
  }

  const W = 2048;
  const H = kind === 'chassis'
    ? Math.min(1536, Math.max(768, Math.round(heightU * 140)))
    : kind === 'ups'
      ? Math.min(768, Math.max(512, Math.round(heightU * 240)))
      : 256;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  const toPxX = (worldX: number) => ((worldX + 2.20) / 4.40) * W;

  // Dedicated Rack-Mount UPS (2U / 3U) Front Faceplate with Live Graphical LCD Console
  if (kind === 'ups') {
    const bgUps = ctx.createLinearGradient(0, 0, 0, H);
    bgUps.addColorStop(0, '#1a202c');
    bgUps.addColorStop(0.5, '#11161f');
    bgUps.addColorStop(1, '#0c1017');
    ctx.fillStyle = bgUps;
    ctx.fillRect(0, 0, W, H);

    // Transparent window over left 3D battery-pack honeycomb vent grille
    const ventX0 = toPxX(-2.06);
    const ventX1 = toPxX(0.32);
    ctx.clearRect(ventX0, H * 0.14, ventX1 - ventX0, H * 0.72);
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 3;
    ctx.strokeRect(ventX0, H * 0.14, ventX1 - ventX0, H * 0.72);

    // Brand + model nameplate above battery bay
    const upsBrand = (vendor || 'SMART-UPS').toUpperCase().slice(0, 14);
    ctx.fillStyle = '#f8fafc';
    ctx.font = '900 28px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(upsBrand, ventX0 + 8, H * 0.075);
    ctx.fillStyle = '#38bdf8';
    ctx.font = 'bold 20px monospace';
    ctx.fillText(`${model || `${heightU}U ONLINE UPS`} · ${deviceName}`, ventX0 + 230, H * 0.075);

    // Right Graphical LCD Telemetry Screen (matches 3D LCD recess around x=+1.15)
    const lcdX = toPxX(0.68);
    const lcdW = toPxX(1.62) - lcdX;
    const lcdY = H * 0.18;
    const lcdH = H * 0.44;
    ctx.fillStyle = '#062038';
    ctx.fillRect(lcdX, lcdY, lcdW, lcdH);
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 3;
    ctx.strokeRect(lcdX, lcdY, lcdW, lcdH);

    ctx.fillStyle = '#38bdf8';
    ctx.font = 'bold 20px monospace';
    ctx.fillText('ONLINE · DOUBLE CONVERSION', lcdX + 16, lcdY + lcdH * 0.22);
    ctx.fillStyle = '#f8fafc';
    ctx.font = '900 32px monospace';
    ctx.fillText('220V IN -> 220V OUT', lcdX + 16, lcdY + lcdH * 0.54);
    ctx.fillStyle = '#4ade80';
    ctx.font = 'bold 22px monospace';
    ctx.fillText('LOAD 42%   BATT 100%   50.0Hz', lcdX + 16, lcdY + lcdH * 0.82);

    // 4 Status LED legends right of LCD (clear holes for 3D animated LEDs)
    const ledX = toPxX(1.78);
    ctx.clearRect(ledX - 18, H * 0.16, 44, H * 0.62);
    const ledLabels = ['MAINS', 'BATT', 'BYP', 'ALM'];
    ctx.font = 'bold 16px monospace';
    ctx.fillStyle = '#cbd5e1';
    ledLabels.forEach((lbl, idx) => {
      const ly = H * (0.24 + idx * 0.14);
      ctx.fillText(lbl, ledX + 26, ly);
    });

    // 5 tactile control button labels below LCD
    const btns = ['ESC', '▲', '▼', 'ENT', 'PWR'];
    ctx.font = 'bold 16px monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = '#94a3b8';
    btns.forEach((bLbl, idx) => {
      const bx = lcdX + 46 + idx * ((lcdW - 92) / 4);
      ctx.fillText(bLbl, bx, H * 0.82);
    });

    const upsTex = new THREE.CanvasTexture(canvas);
    upsTex.minFilter = THREE.LinearMipMapLinearFilter;
    upsTex.magFilter = THREE.LinearFilter;
    upsTex.anisotropy = 16;
    upsTex.generateMipmaps = true;
    upsTex.needsUpdate = true;
    textureCache.set(cacheKey, upsTex);
    return upsTex;
  }

  // Dedicated Multi-U Modular Core Chassis Faceplate (Slot-by-Slot: MPU + LPU + Power Shelf)
  if (kind === 'chassis') {
    const isLight = spec.vendorStyle === 'h3c';
    const bgCh = ctx.createLinearGradient(0, 0, 0, H);
    bgCh.addColorStop(0, isLight ? '#cfd6df' : '#1e2736');
    bgCh.addColorStop(1, isLight ? '#aeb8c6' : '#111827');
    ctx.fillStyle = bgCh;
    ctx.fillRect(0, 0, W, H);

    const accent = spec.vendorStyle === 'cisco'
      ? '#00bceb'
      : spec.vendorStyle === 'ruijie'
        ? '#3b82f6'
        : '#dc2626';
    ctx.fillStyle = accent;
    ctx.fillRect(0, 0, W, 16);

    // Top Chassis Vendor & Model Identity Strip
    ctx.fillStyle = isLight ? '#0f172a' : '#f8fafc';
    ctx.font = '900 32px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const vTitle = (vendor || spec.vendorStyle).toUpperCase();
    ctx.fillText(`${vTitle}  ${model || 'MODULAR CORE CHASSIS'}`, 28, H * 0.032);
    ctx.fillStyle = accent;
    ctx.font = 'bold 22px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`${deviceName} · ${heightU}U MODULAR CHASSIS`, W - 28, H * 0.032);

    // Per-Slot Horizontal Card Silkscreen + Transparent Cutouts over 3D Line Cards & Ejectors
    spec.chassisSlots.forEach(slot => {
      const y0 = Math.round(slot.yTopFrac * H);
      const y1 = Math.round(slot.yBotFrac * H);
      const sh = Math.max(24, y1 - y0);

      // Empty chassis slots stay sealed with a brushed blank filler plate
      if (slot.kind === 'blank') {
        ctx.fillStyle = isLight ? '#9aa5b4' : '#18212f';
        ctx.fillRect(16, y0, W - 32, sh);
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.45)';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(16, y0, W - 32, sh);
        ctx.fillStyle = isLight ? '#334155' : '#64748b';
        ctx.font = 'bold 16px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(slot.label, W / 2, y0 + sh / 2);
        return;
      }

      // Clear center 3D port cage window + left/right ejector lever windows
      ctx.clearRect(toPxX(-2.12), y0 + 22, toPxX(2.12) - toPxX(-2.12), Math.max(10, sh - 26));

      // Crisp slot header bar with slot number & card model
      ctx.fillStyle = slot.kind === 'mpu'
        ? 'rgba(14, 165, 233, 0.25)'
        : slot.kind === 'power_shelf'
          ? 'rgba(245, 158, 11, 0.22)'
          : 'rgba(15, 23, 42, 0.82)';
      ctx.fillRect(16, y0, W - 32, 22);
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.5)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(16, y0, W - 32, sh);

      ctx.fillStyle = slot.kind === 'mpu' ? '#38bdf8' : slot.kind === 'power_shelf' ? '#fbbf24' : '#e2e8f0';
      ctx.font = 'bold 16px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(slot.label, 30, y0 + 11);

      if (slot.portCount > 0 && slot.kind !== 'mpu') {
        ctx.fillStyle = '#94a3b8';
        ctx.font = 'bold 14px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${slot.portCount}× ${slot.portType.toUpperCase()} · HOT-SWAP`, W - 30, y0 + 11);
      }
    });

    const chTex = new THREE.CanvasTexture(canvas);
    chTex.minFilter = THREE.LinearMipMapLinearFilter;
    chTex.magFilter = THREE.LinearFilter;
    chTex.anisotropy = 16;
    chTex.generateMipmaps = true;
    chTex.needsUpdate = true;
    textureCache.set(cacheKey, chTex);
    return chTex;
  }

  // 1. Subtle brushed anodized titanium/aluminum faceplate finish
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  if (kind === 's6800') {
    // Official H3C S6850 brushed silver-aluminum faceplate
    bg.addColorStop(0, 'rgba(222, 228, 235, 0.98)');
    bg.addColorStop(0.5, 'rgba(200, 208, 218, 0.96)');
    bg.addColorStop(1, 'rgba(178, 188, 200, 0.98)');
  } else if (kind === 'firewall') {
    bg.addColorStop(0, 'rgba(30, 36, 46, 0.92)');
    bg.addColorStop(0.5, 'rgba(18, 23, 32, 0.88)');
    bg.addColorStop(1, 'rgba(12, 16, 24, 0.94)');
  } else if (kind === 'wireless_ac') {
    bg.addColorStop(0, 'rgba(42, 54, 70, 0.92)');
    bg.addColorStop(0.5, 'rgba(26, 36, 50, 0.88)');
    bg.addColorStop(1, 'rgba(18, 25, 36, 0.94)');
  } else {
    bg.addColorStop(0, 'rgba(38, 48, 62, 0.92)');
    bg.addColorStop(0.5, 'rgba(22, 30, 42, 0.86)');
    bg.addColorStop(1, 'rgba(15, 21, 31, 0.94)');
  }
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Micro horizontal brushed-metal lines
  ctx.fillStyle = kind === 's6800' ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.025)';
  for (let y = 2; y < H; y += 4) {
    ctx.fillRect(0, y, W, 1);
  }
  // Top/bottom machined chamfer highlights
  ctx.fillStyle = kind === 's6800' ? 'rgba(255, 255, 255, 0.65)' : 'rgba(226, 232, 240, 0.22)';
  ctx.fillRect(0, 0, W, 3);
  ctx.fillStyle = 'rgba(15, 23, 42, 0.55)';
  ctx.fillRect(0, H - 3, W, 3);

  // 2. Left silkscreen: Brand badge + Hostname + PWR/SYS/ALM + CON/MGMT
  const brand = (vendor || 'H3C').toUpperCase().slice(0, 10);
  if (kind === 's6800') {
    // Official H3C S6850 top-left white/silver identity plate + red H3C logo + SYS/PSU/FAN LEDs
    ctx.fillStyle = '#f1f5f9';
    ctx.fillRect(8, 6, 250, 56);
    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(8, 6, 250, 56);
    // Iconic red H3C logo
    ctx.fillStyle = '#dc2626';
    ctx.font = '900 22px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('H3C', 18, 24);
    ctx.fillStyle = '#334155';
    ctx.font = 'bold 14px system-ui, -apple-system, sans-serif';
    ctx.fillText(`${model || 'S6850'} Series`, 74, 24);
    // SYS / PSU / FAN micro LED recessed sockets (live 3D LEDs protrude & blink through these)
    const sysLeds = [
      { label: 'SYS', x: 24 },
      { label: 'PSU', x: 96 },
      { label: 'FAN', x: 168 },
    ];
    ctx.font = 'bold 12px monospace';
    for (const sl of sysLeds) {
      ctx.fillStyle = '#475569';
      ctx.fillText(sl.label, sl.x, 48);
      ctx.fillStyle = '#1e293b';
      ctx.beginPath();
      ctx.arc(sl.x + 34, 48, 5.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    // Iconic top-strip hexagonal honeycomb ventilation grill across the rest of the top bar
    ctx.fillStyle = '#111827';
    const hexStart = 268;
    const hexEnd = W - 16;
    for (let row = 0; row < 3; row++) {
      const cy = 15 + row * 15;
      const xShift = row % 2 === 0 ? 0 : 9;
      for (let cx = hexStart + xShift; cx < hexEnd; cx += 18) {
        ctx.beginPath();
        for (let k = 0; k < 6; k++) {
          const ang = (Math.PI / 3) * k + Math.PI / 6;
          const hx = cx + 6.2 * Math.cos(ang);
          const hy = cy + 6.2 * Math.sin(ang);
          if (k === 0) ctx.moveTo(hx, hy);
          else ctx.lineTo(hx, hy);
        }
        ctx.closePath();
        ctx.fill();
      }
    }
    // Small silver SFP28 & QSFP28 badges embedded in the honeycomb strip
    ctx.fillStyle = '#dce3eb';
    ctx.fillRect(toPxX(-0.44) - 40, 44, 80, 18);
    ctx.fillRect(toPxX(1.71) - 44, 44, 88, 18);
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 12px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('SFP28', toPxX(-0.44), 54);
    ctx.fillText('QSFP28', toPxX(1.71), 54);

    // Bottom silver lip micro-ventilation dots (edge-to-edge like the official S6850 photo)
    ctx.fillStyle = '#1e293b';
    for (let vx = 30; vx < W - 20; vx += 26) {
      ctx.beginPath();
      ctx.arc(vx, H - 15, 4.6, 0, Math.PI * 2);
      ctx.fill();
    }
  } else {
    const accentColor = kind === 'firewall' ? '#f59e0b' : kind === 'wireless_ac' ? '#22d3ee' : '#e11d48';
    ctx.fillStyle = accentColor;
    ctx.fillRect(14, 18, 8, H - 36);

    ctx.clearRect(54, 48, 44, 162);
    ctx.clearRect(126, 54, 78, 148);

    ctx.fillStyle = '#94a3b8';
    ctx.font = 'bold 14px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('PWR', 100, 68);
    ctx.fillText('SYS', 100, 128);
    ctx.fillText('ALM', 100, 188);

    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 13px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('CON', 165, 36);
    ctx.fillText('MGMT', 165, 222);

    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 18px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(brand, 28, 30);
    ctx.fillStyle = '#38bdf8';
    ctx.font = 'bold 16px monospace';
    ctx.fillText(deviceName.slice(0, 14), 28, 228);
  }

  // 3. Port Bank Transparent Cutouts + Silkscreen Port Numbers (exact 1:1 with GLB)
  if (kind === 's6800') {
    // Official H3C S6850: 4 x 12-port SFP28 banks + 1 x 8-port QSFP28 bank (4 cols x 2 rows)
    // Top row Y=+0.0044m -> py ~ 76..126; Center silver strip -> py ~ 126..154; Bottom row Y=-0.0084m -> py ~ 154..204
    const sfpBankWidths = [0.76, 0.76, 0.76, 0.76];
    const sfpBankGap = 0.08;
    let bankLeft = -2.08;

    const drawCenterStripLabel = (px: number, oddPort: number, evenPort: number, isQsfp: boolean) => {
      const dx = isQsfp ? 22 : 13;
      const triColor = isQsfp ? '#0284c7' : '#15803d';
      ctx.font = isQsfp ? 'bold 14px monospace' : 'bold 13px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      // Left of column: ▲ pointing UP to top odd port + odd port number
      ctx.fillStyle = triColor;
      ctx.beginPath();
      ctx.moveTo(px - dx, 129);
      ctx.lineTo(px - dx - 5, 136);
      ctx.lineTo(px - dx + 5, 136);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = '#0f172a';
      ctx.fillText(`${oddPort}`, px - dx, 145);

      // Right of column: even port number + ▼ pointing DOWN to bottom even port
      ctx.fillStyle = '#0f172a';
      ctx.fillText(`${evenPort}`, px + dx, 135);
      ctx.fillStyle = triColor;
      ctx.beginPath();
      ctx.moveTo(px + dx, 151);
      ctx.lineTo(px + dx - 5, 144);
      ctx.lineTo(px + dx + 5, 144);
      ctx.closePath();
      ctx.fill();
    };

    for (let bankIndex = 0; bankIndex < 4; bankIndex++) {
      const bw = sfpBankWidths[bankIndex];
      const x0 = toPxX(bankLeft - 0.068);
      const x1 = toPxX(bankLeft + bw + 0.068);

      // Transparent cutouts ONLY for top & bottom cages, leaving the center silver strip solid & crisp!
      ctx.clearRect(x0, 76, x1 - x0, 50);
      ctx.clearRect(x0, 154, x1 - x0, 50);

      // Brushed silver center numbering bar
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(x0, 126, x1 - x0, 28);
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = 1.4;
      ctx.strokeRect(x0, 76, x1 - x0, 128);

      const cols = 6;
      for (let col = 0; col < cols; col++) {
        const px = toPxX(bankLeft + col * (bw / (cols - 1)));
        const oddPort = bankIndex * 12 + col * 2 + 1;
        const evenPort = bankIndex * 12 + col * 2 + 2;
        drawCenterStripLabel(px, oddPort, evenPort, false);
      }
      bankLeft += bw + sfpBankGap;
    }

    // Right-side QSFP28 / High-Speed Uplink bank — honors real CMDB port count (e.g. 54 ports = cols 0..2; 56 ports = cols 0..3)
    const qsfpLeft = 1.34;
    const qsfpWidth = 0.74;
    const maxRealPort = physicalPortProfile?.slots?.[0]?.max_port || 56;
    const activeQsfpCols = maxRealPort <= 54 ? 3 : 4;
    const activeRightEdge = activeQsfpCols === 3
      ? qsfpLeft + 2 * (qsfpWidth / 3) + 0.105
      : qsfpLeft + qsfpWidth + 0.105;
    const qx0 = toPxX(qsfpLeft - 0.105);
    const qx1 = toPxX(activeRightEdge);

    ctx.clearRect(qx0, 76, qx1 - qx0, 50);
    ctx.clearRect(qx0, 154, qx1 - qx0, 50);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(qx0, 126, qx1 - qx0, 28);
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1.6;
    ctx.strokeRect(qx0, 76, qx1 - qx0, 128);

    for (let col = 0; col < activeQsfpCols; col++) {
      const px = toPxX(qsfpLeft + col * (qsfpWidth / 3));
      const oddPort = 49 + col * 2;
      const evenPort = 50 + col * 2;
      drawCenterStripLabel(px, oddPort, evenPort, true);
    }
    if (physicalPortProfile && physicalPortProfile.total_ports > 0) {
      ctx.fillStyle = '#0f172a';
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`${physicalPortProfile.total_ports}P·${physicalPortProfile.up_count}UP`, 250, 24);
    }
  } else if (kind === 'firewall') {
    // Authentic H3C SecPath F1090 Next-Gen Firewall front silkscreen (synced with real CMDB start port)
    const fwStart = physicalPortProfile?.slots?.[0]?.min_port ?? 1;
    ctx.fillStyle = '#dc2626';
    ctx.font = '900 18px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('H3C', 28, 30);
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 14px system-ui, -apple-system, sans-serif';
    ctx.fillText(`SecPath ${model || 'F1090'}`, 76, 30);

    const fwBanks = [
      { label: `GE ${fwStart}-${fwStart + 3}`, startPort: fwStart, cols: 2, xStart: -1.45, xEnd: -1.25, color: '#f59e0b' },
      { label: `GE ${fwStart + 4}-${fwStart + 15}`, startPort: fwStart + 4, cols: 6, xStart: -0.85, xEnd: -0.05, color: '#38bdf8' },
      { label: `GE/SFP+ ${fwStart + 16}-${fwStart + 23}`, startPort: fwStart + 16, cols: 4, xStart: 0.25, xEnd: 0.82, color: '#22d3ee' },
    ];
    for (const bank of fwBanks) {
      const px0 = toPxX(bank.xStart - 0.08);
      const px1 = toPxX(bank.xEnd + 0.08);
      ctx.clearRect(px0, 56, px1 - px0, 144);
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.42)';
      ctx.lineWidth = 1.6;
      ctx.strokeRect(px0, 56, px1 - px0, 144);
      ctx.fillStyle = bank.color;
      ctx.font = 'bold 14px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(bank.label, (px0 + px1) / 2, 22);

      ctx.font = 'bold 12px monospace';
      for (let c = 0; c < bank.cols; c++) {
        const xDm = bank.cols === 1 ? bank.xStart : bank.xStart + (c / (bank.cols - 1)) * (bank.xEnd - bank.xStart);
        const px = toPxX(xDm);
        const topP = bank.startPort + c * 2;
        const botP = topP + 1;
        ctx.fillStyle = '#e2e8f0';
        ctx.fillText(`${topP}▲`, px, 46);
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`${botP}▼`, px, 214);
      }
    }
    const exp0 = toPxX(1.10);
    const exp1 = toPxX(2.02);
    ctx.clearRect(exp0, 56, exp1 - exp0, 144);
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.45)';
    ctx.strokeRect(exp0, 56, exp1 - exp0, 144);
    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 13px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(
      physicalPortProfile ? `SLOT 1 · ${physicalPortProfile.total_ports}P (${physicalPortProfile.up_count} UP)` : 'SLOT 1 · FIC-NGFW EXPANSION',
      (exp0 + exp1) / 2,
      24,
    );
    ctx.fillStyle = '#64748b';
    ctx.font = 'bold 11px monospace';
    ctx.fillText('HIGH-SPEED SECURITY MODULE BAY', (exp0 + exp1) / 2, 220);
  } else if (kind === 'wireless_ac') {
    // Authentic H3C WX5540H 28-port Wireless Controller silkscreen (synced with real CMDB ports 0..27)
    const acStart = physicalPortProfile?.slots?.[0]?.min_port ?? 0;
    const grill0 = toPxX(-1.56);
    const grill1 = toPxX(-0.68);
    ctx.clearRect(grill0, 62, grill1 - grill0, 134);
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
    ctx.lineWidth = 1.6;
    ctx.strokeRect(grill0, 62, grill1 - grill0, 134);

    ctx.fillStyle = '#dc2626';
    ctx.font = '900 18px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('H3C', toPxX(-1.54), 28);
    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 14px system-ui, -apple-system, sans-serif';
    ctx.fillText(`${model || 'WX5540H'}`, toPxX(-1.30), 28);
    ctx.fillStyle = '#22d3ee';
    ctx.font = 'bold 12px monospace';
    ctx.fillText(
      physicalPortProfile
        ? `${deviceName} · ${physicalPortProfile.total_ports}P (${physicalPortProfile.up_count} UP)`
        : `${deviceName} · WLAN AC`,
      toPxX(-1.54),
      220,
    );

    const acBanks = [
      { label: `GE ${acStart}-${acStart + 11}`, startPort: acStart, cols: 6, xStart: -0.52, xEnd: 0.24, color: '#cbd5e1' },
      { label: `GE ${acStart + 12}-${acStart + 23}`, startPort: acStart + 12, cols: 6, xStart: 0.36, xEnd: 1.12, color: '#cbd5e1' },
      { label: `10G SFP+ ${acStart + 24}-${acStart + 27}`, startPort: acStart + 24, cols: 2, xStart: 1.45, xEnd: 1.75, color: '#22d3ee' },
    ];
    for (const bank of acBanks) {
      const px0 = toPxX(bank.xStart - 0.08);
      const px1 = toPxX(bank.xEnd + 0.08);
      ctx.clearRect(px0, 56, px1 - px0, 144);
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
      ctx.strokeRect(px0, 56, px1 - px0, 144);
      ctx.fillStyle = bank.color;
      ctx.font = 'bold 13px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(bank.label, (px0 + px1) / 2, 24);
      ctx.font = 'bold 11px monospace';
      for (let c = 0; c < bank.cols; c++) {
        const px = toPxX(bank.xStart + (c / (bank.cols - 1)) * (bank.xEnd - bank.xStart));
        const topP = bank.startPort + c * 2;
        ctx.fillStyle = '#e2e8f0';
        ctx.fillText(`${topP}▲`, px, 46);
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`${topP + 1}▼`, px, 214);
      }
    }
  } else {
    // Vendor-authentic & slot-driven 1U box switch silkscreen (Cisco / Huawei / Ruijie / H3C Campus / Generic)
    const accent = spec.vendorStyle === 'cisco'
      ? '#00bceb'
      : spec.vendorStyle === 'huawei'
        ? '#e11d48'
        : spec.vendorStyle === 'ruijie'
          ? '#3b82f6'
          : '#38bdf8';
    const vendorLabel = spec.vendorStyle === 'cisco'
      ? 'CISCO'
      : spec.vendorStyle === 'huawei'
        ? 'HUAWEI'
        : spec.vendorStyle === 'ruijie'
          ? 'Ruijie'
          : brand;

    ctx.fillStyle = accent;
    ctx.font = '900 20px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(vendorLabel, 26, 26);
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 14px monospace';
    ctx.fillText((model || `${spec.portDensity}P SWITCH`).slice(0, 22), 118, 26);

    for (const bank of spec.boxBanks) {
      const pad = bank.kind === 'qsfp' ? 0.10 : 0.068;
      const px0 = toPxX(bank.xStart - pad);
      const px1 = toPxX(bank.xEnd + pad);
      ctx.clearRect(px0, 56, px1 - px0, 144);
      ctx.strokeStyle = bank.modular ? accent : 'rgba(148, 163, 184, 0.42)';
      ctx.lineWidth = bank.modular ? 2 : 1.4;
      ctx.strokeRect(px0, 56, px1 - px0, 144);

      ctx.fillStyle = bank.modular ? accent : '#cbd5e1';
      ctx.font = 'bold 13px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(bank.label, (px0 + px1) / 2, 22);

      ctx.font = 'bold 11px monospace';
      for (let c = 0; c < bank.cols; c++) {
        const xDm = bank.cols === 1
          ? bank.xStart
          : bank.xStart + (c / (bank.cols - 1)) * (bank.xEnd - bank.xStart);
        const px = toPxX(xDm);
        const odd = bank.startPort + c * 2;
        ctx.fillStyle = '#e2e8f0';
        ctx.fillText(`${odd}▲`, px, 46);
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`${odd + 1}▼`, px, 214);
      }
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearMipMapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.needsUpdate = true;
  textureCache.set(cacheKey, texture);
  return texture;
}
