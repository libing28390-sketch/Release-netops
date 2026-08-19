import * as THREE from 'three';

const textureCache = new Map<string, THREE.CanvasTexture>();

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
  connectedPortNumbers: number[] = []
): THREE.CanvasTexture {
  const portsKey = connectedPortNumbers.slice().sort((a, b) => a - b).join('_');
  const cacheKey = `switch_front_${deviceName}_${vendor}_${model}_${heightU}_${portsKey}`;
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

  // Silkscreen PWR & SYS LEDs
  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 12px monospace';
  ctx.textAlign = 'right';
  ctx.fillText('PWR', 280, height / 2 - 16);
  ctx.fillStyle = '#22c55e'; // Green Power LED
  ctx.beginPath();
  ctx.arc(292, height / 2 - 16, 5, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#94a3b8';
  ctx.fillText('SYS', 280, height / 2 + 16);
  ctx.fillStyle = '#22c55e'; // Green System Run LED
  ctx.beginPath();
  ctx.arc(292, height / 2 + 16, 5, 0, Math.PI * 2);
  ctx.fill();

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
    ctx.fillStyle = '#020617';
    ctx.fillRect(px, pyTop, portW, portH);
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(px, pyTop, portW, portH);

    // Top port LED: ONLY GREEN IF AN ACTIVE CABLE IS PLUGGED IN!
    ctx.fillStyle = isTopConnected ? '#22c55e' : '#18202c';
    ctx.fillRect(px + (is48Port ? 6 : 12), pyTop - 7, (is48Port ? 16 : 16), 4);

    // Bottom port
    const bottomPortNum = c * 2 + 1;
    const isBottomConnected = connectedPortNumbers.includes(bottomPortNum);
    const pyBottom = height / 2 + 6;
    ctx.fillStyle = '#020617';
    ctx.fillRect(px, pyBottom, portW, portH);
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(px, pyBottom, portW, portH);

    // Bottom port LED: ONLY GREEN IF AN ACTIVE CABLE IS PLUGGED IN!
    ctx.fillStyle = isBottomConnected ? '#22c55e' : '#18202c';
    ctx.fillRect(px + (is48Port ? 6 : 12), pyBottom + portH + 3, (is48Port ? 16 : 16), 4);
  }

  // Zone 3: High-Speed 40G/100G QSFP28 Uplink Area
  const qsfpStartX = is48Port ? (startX + 24 * gapX + 42) : 1680;
  const qsfpW = is48Port ? 56 : 68;
  const qsfpH = 50;
  const qsfpCols = is48Port ? 6 : 4;

  for (let q = 0; q < qsfpCols; q++) {
    const qx = qsfpStartX + q * (qsfpW + 10);
    ctx.fillStyle = '#020617';
    ctx.fillRect(qx, height / 2 - qsfpH / 2, qsfpW, qsfpH);
    ctx.strokeStyle = '#0284c7';
    ctx.lineWidth = 1.8;
    ctx.strokeRect(qx, height / 2 - qsfpH / 2, qsfpW, qsfpH);

    // QSFP Pull-tab & LED
    ctx.fillStyle = '#0284c7';
    ctx.fillRect(qx + 12, height / 2 - qsfpH / 2 - 6, 28, 4);
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
