// High-DPI Curl-Noise Telemetry Flow Field Renderer for the Nexora Login Screen.
// Renders sweeping full-viewport tapered silk filaments, multi-strand optical
// backbone streams with elongated data-packet streaks, aerodynamic login-card
// deflection, magnetic cursor wake, and crisp click pulse rings on pure #FFFFFF.

interface FlowParticle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  speed: number;
  thickness: number;
  hueJitter: number;
  emeraldAccent: boolean;
  trailX: Float32Array;
  trailY: Float32Array;
  trailLen: number;
  trailHead: number;
}

interface Shockwave {
  x: number;
  y: number;
  radius: number;
  maxRadius: number;
  alpha: number;
}

interface OpticalRibbon {
  yRatio: number;
  amplitude: number;
  freq: number;
  phase: number;
  speed: number;
  packetT: number;
  packetSpeed: number;
  rgb: readonly [number, number, number];
}

const TRAIL_CAPACITY = 26;

function hash2(ix: number, iy: number): number {
  const n = Math.sin(ix * 127.1 + iy * 311.7) * 43758.5453123;
  return n - Math.floor(n);
}

function valueNoise2D(x: number, y: number): number {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);

  const a = hash2(ix, iy);
  const b = hash2(ix + 1, iy);
  const c = hash2(ix, iy + 1);
  const d = hash2(ix + 1, iy + 1);

  return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy;
}

function fbmNoise2D(x: number, y: number): number {
  return valueNoise2D(x, y) * 0.72 + valueNoise2D(x * 2.02 + 17.3, y * 2.02 - 9.1) * 0.28;
}

function curlField(x: number, y: number, t: number): [number, number] {
  const eps = 0.02;
  const nx = x + t * 0.11;
  const ny = y - t * 0.06;
  const n1 = fbmNoise2D(nx, ny + eps);
  const n2 = fbmNoise2D(nx, ny - eps);
  const n3 = fbmNoise2D(nx + eps, ny);
  const n4 = fbmNoise2D(nx - eps, ny);
  const dNdy = (n1 - n2) / (2 * eps);
  const dNdx = (n3 - n4) / (2 * eps);
  return [dNdy, -dNdx];
}

const PALETTE: readonly [number, number, number][] = [
  [37, 99, 235],   // Cobalt Blue     #2563EB
  [14, 165, 233],  // Sky Azure       #0EA5E9
  [6, 182, 212],   // Luminous Cyan   #06B6D4
  [79, 70, 229],   // Electric Indigo #4F46E5
  [124, 58, 237],  // Vivid Violet    #7C3AED
];
const EMERALD_RGB: readonly [number, number, number] = [16, 185, 129]; // #10B981

function sampleSectorColor(
  nx: number,
  ny: number,
  t: number,
  jitter: number,
  emeraldAccent: boolean,
  energy: number,
): [number, number, number] {
  if (emeraldAccent) {
    return [
      Math.round(EMERALD_RGB[0] * (1 - energy * 0.2) + 6 * energy * 0.2),
      Math.round(EMERALD_RGB[1] * (1 - energy * 0.1) + 212 * energy * 0.1),
      Math.round(EMERALD_RGB[2] * (1 - energy * 0.1) + 190 * energy * 0.1),
    ];
  }
  const sector = (valueNoise2D(nx * 1.55 + t * 0.07, ny * 1.35 - t * 0.04) + jitter * 0.15 + 1) % 1;
  const scaled = sector * (PALETTE.length - 1);
  const idx = Math.floor(scaled);
  const frac = scaled - idx;
  const c0 = PALETTE[idx];
  const c1 = PALETTE[Math.min(idx + 1, PALETTE.length - 1)];
  let r = c0[0] + (c1[0] - c0[0]) * frac;
  let g = c0[1] + (c1[1] - c0[1]) * frac;
  let b = c0[2] + (c1[2] - c0[2]) * frac;
  if (energy > 0.05) {
    const boost = Math.min(energy, 1) * 0.42;
    r = r + (6 - r) * boost;
    g = g + (182 - g) * boost;
    b = b + (245 - b) * boost;
  }
  return [Math.round(r), Math.round(g), Math.round(b)];
}

export function createLoginParticleRenderer(container: HTMLDivElement): () => void {
  const canvas = document.createElement('canvas');
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.display = 'block';
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return () => {};

  container.appendChild(canvas);

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let width = 1;
  let height = 1;
  let dpr = 1;
  let disposed = false;
  let rafId = 0;
  let lastTime = 0;
  let elapsed = 0;

  const pointer = {
    x: -9999,
    y: -9999,
    vx: 0,
    vy: 0,
    active: false,
    smoothX: -9999,
    smoothY: -9999,
  };

  let obstacleRect: { cx: number; cy: number; rx: number; ry: number } | null = null;
  let isAuthenticating = false;

  const shockwaves: Shockwave[] = [];
  const particles: FlowParticle[] = [];

  const ribbons: OpticalRibbon[] = [
    { yRatio: 0.15, amplitude: 42, freq: 0.0021, phase: 0.4, speed: 0.25, packetT: 0.14, packetSpeed: 0.11, rgb: [37, 99, 235] },
    { yRatio: 0.30, amplitude: 52, freq: 0.0017, phase: 1.9, speed: 0.20, packetT: 0.62, packetSpeed: 0.09, rgb: [6, 182, 212] },
    { yRatio: 0.50, amplitude: 48, freq: 0.0019, phase: 3.1, speed: 0.22, packetT: 0.85, packetSpeed: 0.10, rgb: [79, 70, 229] },
    { yRatio: 0.72, amplitude: 46, freq: 0.0020, phase: 4.5, speed: 0.21, packetT: 0.36, packetSpeed: 0.095, rgb: [14, 165, 233] },
    { yRatio: 0.87, amplitude: 36, freq: 0.0023, phase: 5.4, speed: 0.26, packetT: 0.71, packetSpeed: 0.12, rgb: [124, 58, 237] },
  ];

  const spawnParticle = (p: FlowParticle, initial = false) => {
    let x = Math.random() * width;
    let y = Math.random() * height;
    if (obstacleRect) {
      for (let attempt = 0; attempt < 3; attempt++) {
        const nx = (x - obstacleRect.cx) / obstacleRect.rx;
        const ny = (y - obstacleRect.cy) / obstacleRect.ry;
        if (nx * nx + ny * ny > 0.9) break;
        x = Math.random() * width;
        y = Math.random() * height;
      }
    }
    p.x = x;
    p.y = y;
    p.vx = 1.6;
    p.vy = -0.25;
    p.maxLife = 220 + Math.random() * 240;
    p.life = initial ? Math.random() * p.maxLife * 0.75 : 0;
    p.speed = 1.9 + Math.random() * 1.65;
    p.thickness = 1.45 + Math.random() * 1.55;
    p.hueJitter = (Math.random() - 0.5) * 2;
    p.emeraldAccent = Math.random() < 0.085;
    p.trailLen = 1;
    p.trailHead = 0;
    p.trailX[0] = x;
    p.trailY[0] = y;
  };

  const syncParticlePool = () => {
    const area = width * height;
    const baseCount = motionQuery.matches
      ? Math.min(90, Math.max(55, Math.round(area / 20000)))
      : Math.min(340, Math.max(170, Math.round(area / 5200)));

    while (particles.length < baseCount) {
      const p: FlowParticle = {
        x: 0,
        y: 0,
        vx: 0,
        vy: 0,
        life: 0,
        maxLife: 280,
        speed: 2.4,
        thickness: 1.8,
        hueJitter: 0,
        emeraldAccent: false,
        trailX: new Float32Array(TRAIL_CAPACITY),
        trailY: new Float32Array(TRAIL_CAPACITY),
        trailLen: 0,
        trailHead: 0,
      };
      spawnParticle(p, true);
      particles.push(p);
    }
    if (particles.length > baseCount) {
      particles.length = baseCount;
    }
  };

  const refreshObstacle = () => {
    const obstacle = container.parentElement?.querySelector<HTMLElement>('[data-login-particle-obstacle]');
    if (!obstacle) {
      obstacleRect = null;
      isAuthenticating = false;
      return;
    }
    const cBounds = container.getBoundingClientRect();
    const oBounds = obstacle.getBoundingClientRect();
    obstacleRect = {
      cx: oBounds.left - cBounds.left + oBounds.width * 0.5,
      cy: oBounds.top - cBounds.top + oBounds.height * 0.5,
      rx: oBounds.width * 0.5 + 42,
      ry: oBounds.height * 0.5 + 42,
    };
    isAuthenticating = obstacle.getAttribute('data-login-authenticating') === 'true';
  };

  const resize = () => {
    const bounds = container.getBoundingClientRect();
    width = Math.max(1, bounds.width);
    height = Math.max(1, bounds.height);
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    refreshObstacle();
    syncParticlePool();
  };

  const drawAmbientGlows = (t: number) => {
    const glows: Array<{ x: number; y: number; r: number; color: string }> = [
      {
        x: width * (0.18 + Math.sin(t * 0.18) * 0.08),
        y: height * (0.28 + Math.cos(t * 0.14) * 0.08),
        r: Math.max(width, height) * 0.42,
        color: 'rgba(37, 99, 235, 0.055)',
      },
      {
        x: width * (0.82 + Math.cos(t * 0.16) * 0.08),
        y: height * (0.68 + Math.sin(t * 0.21) * 0.08),
        r: Math.max(width, height) * 0.44,
        color: 'rgba(6, 182, 212, 0.055)',
      },
      {
        x: width * (0.70 + Math.sin(t * 0.13 + 1.4) * 0.07),
        y: height * (0.20 + Math.cos(t * 0.17 + 0.8) * 0.06),
        r: Math.max(width, height) * 0.34,
        color: 'rgba(124, 58, 237, 0.042)',
      },
    ];

    for (const g of glows) {
      const grad = ctx.createRadialGradient(g.x, g.y, 0, g.x, g.y, g.r);
      grad.addColorStop(0, g.color);
      grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);
    }

    if (pointer.active && pointer.smoothX > -1000) {
      const pGrad = ctx.createRadialGradient(
        pointer.smoothX,
        pointer.smoothY,
        0,
        pointer.smoothX,
        pointer.smoothY,
        240,
      );
      pGrad.addColorStop(0, 'rgba(6, 182, 212, 0.08)');
      pGrad.addColorStop(0.5, 'rgba(37, 99, 235, 0.03)');
      pGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = pGrad;
      ctx.fillRect(0, 0, width, height);
    }
  };

  const ribbonYAt = (rib: OpticalRibbon, x: number, t: number): number => {
    const baseY = height * rib.yRatio;
    const wave =
      Math.sin(x * rib.freq + t * rib.speed + rib.phase) * rib.amplitude +
      Math.cos(x * rib.freq * 0.55 - t * rib.speed * 0.7 + rib.phase) * (rib.amplitude * 0.45);
    let y = baseY + wave;
    if (pointer.active && pointer.smoothX > -1000) {
      const dx = x - pointer.smoothX;
      const dy = y - pointer.smoothY;
      const dist = Math.hypot(dx, dy);
      if (dist < 240 && dist > 1) {
        const pull = 1 - dist / 240;
        y += (dy / dist) * pull * pull * 32;
      }
    }
    return y;
  };

  const drawOpticalRibbons = (dt: number, t: number) => {
    const segments = 44;
    const stepX = width / segments;
    ctx.lineCap = 'round';

    for (const rib of ribbons) {
      const [r, g, b] = rib.rgb;
      ctx.beginPath();
      for (let i = 0; i <= segments; i++) {
        const x = i * stepX;
        const y = ribbonYAt(rib, x, t);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.105)`;
      ctx.lineWidth = 1.15;
      ctx.stroke();

      rib.packetT = (rib.packetT + rib.packetSpeed * dt) % 1;
      const fadeEdge = Math.sin(rib.packetT * Math.PI);
      if (fadeEdge > 0.03) {
        const headX = rib.packetT * width;
        const tailX = Math.max(0, headX - 88);
        const headY = ribbonYAt(rib, headX, t);
        const tailY = ribbonYAt(rib, tailX, t);
        const pGrad = ctx.createLinearGradient(tailX, tailY, headX, headY);
        pGrad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
        pGrad.addColorStop(0.65, `rgba(${r}, ${g}, ${b}, ${(0.45 * fadeEdge).toFixed(3)})`);
        pGrad.addColorStop(1, `rgba(${r}, ${g}, ${b}, ${(0.92 * fadeEdge).toFixed(3)})`);

        ctx.beginPath();
        const streakSteps = 10;
        for (let k = 0; k <= streakSteps; k++) {
          const sx = tailX + ((headX - tailX) * k) / streakSteps;
          const sy = ribbonYAt(rib, sx, t);
          if (k === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        }
        ctx.strokeStyle = pGrad;
        ctx.lineWidth = 2.4;
        ctx.stroke();
      }
    }
  };

  const drawShockwaves = (dt: number) => {
    for (let i = shockwaves.length - 1; i >= 0; i--) {
      const sw = shockwaves[i];
      sw.radius += 460 * dt;
      sw.alpha = Math.max(0, 1 - sw.radius / sw.maxRadius);
      if (sw.alpha <= 0.015) {
        shockwaves.splice(i, 1);
        continue;
      }
      const ease = sw.alpha * sw.alpha;
      ctx.beginPath();
      ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(37, 99, 235, ${(ease * 0.28).toFixed(3)})`;
      ctx.lineWidth = 1.6;
      ctx.stroke();
    }
  };

  const stepAndDrawParticles = (dt: number, t: number, draw = true) => {
    const scaleStep = dt * 60;
    const fieldScale = 0.0018;
    const reduced = motionQuery.matches;

    if (draw) {
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
    }

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.life += scaleStep;
      if (
        p.life >= p.maxLife ||
        p.x < -50 ||
        p.x > width + 50 ||
        p.y < -50 ||
        p.y > height + 50
      ) {
        spawnParticle(p, false);
        continue;
      }

      const [cx, cy] = curlField(p.x * fieldScale, p.y * fieldScale, t);
      let targetVx = (cx * 1.15 + 0.85) * p.speed;
      let targetVy = (cy * 1.15 - 0.16) * p.speed;
      let energy = 0;

      if (pointer.active && pointer.smoothX > -1000) {
        const dx = p.x - pointer.smoothX;
        const dy = p.y - pointer.smoothY;
        const distSq = dx * dx + dy * dy;
        const radius = 260;
        if (distSq < radius * radius && distSq > 4) {
          const dist = Math.sqrt(distSq);
          const falloff = 1 - dist / radius;
          const force = falloff * falloff;
          const invD = 1 / dist;
          const tx = -dy * invD;
          const ty = dx * invD;
          const rx = dx * invD;
          const ry = dy * invD;
          targetVx += (tx * 3.2 + rx * 1.5) * force + pointer.vx * force * 0.26;
          targetVy += (ty * 3.2 + ry * 1.5) * force + pointer.vy * force * 0.26;
          energy = Math.max(energy, force * 1.25);
        }
      }

      for (let s = 0; s < shockwaves.length; s++) {
        const sw = shockwaves[s];
        const dx = p.x - sw.x;
        const dy = p.y - sw.y;
        const dist = Math.hypot(dx, dy);
        const band = Math.abs(dist - sw.radius);
        if (band < 64 && dist > 1) {
          const waveStrength = (1 - band / 64) * sw.alpha;
          targetVx += (dx / dist) * waveStrength * 5.2;
          targetVy += (dy / dist) * waveStrength * 5.2;
          energy = Math.max(energy, waveStrength * 1.4);
        }
      }

      let cardFade = 1;
      if (obstacleRect) {
        const dx = p.x - obstacleRect.cx;
        const dy = p.y - obstacleRect.cy;
        const nx = dx / obstacleRect.rx;
        const ny = dy / obstacleRect.ry;
        const ellipDist = Math.hypot(nx, ny);

        if (isAuthenticating) {
          if (ellipDist > 0.72 && ellipDist < 2.8) {
            const pull = (1 - (ellipDist - 0.72) / 2.08) * 4.0;
            const d = Math.max(1, Math.hypot(dx, dy));
            targetVx += (-dx / d) * pull;
            targetVy += (-dy / d) * pull;
            energy = Math.max(energy, 0.9);
          }
        } else if (ellipDist < 1.38 && ellipDist > 0.01) {
          const repel = Math.pow(1 - ellipDist / 1.38, 1.45);
          const d = Math.max(1, Math.hypot(dx, dy));
          const sign = dy >= 0 ? 1 : -1;
          targetVx += (dx / d) * repel * 3.0 + 1.1 * repel;
          targetVy += (dy / d) * repel * 3.0 + sign * 0.85 * repel;
          energy = Math.max(energy, repel * 0.55);
        }
        if (ellipDist < 0.94) {
          cardFade = Math.max(0.08, (ellipDist - 0.58) / 0.36);
        }
      }

      if (reduced) {
        targetVx *= 0.22;
        targetVy *= 0.22;
      }

      const inertia = 1 - Math.exp(-6.0 * dt);
      p.vx += (targetVx - p.vx) * inertia;
      p.vy += (targetVy - p.vy) * inertia;

      p.x += p.vx * scaleStep;
      p.y += p.vy * scaleStep;

      p.trailHead = (p.trailHead + 1) % TRAIL_CAPACITY;
      p.trailX[p.trailHead] = p.x;
      p.trailY[p.trailHead] = p.y;
      if (p.trailLen < TRAIL_CAPACITY) p.trailLen++;

      if (!draw || p.trailLen < 3) continue;

      const fadeIn = Math.min(1, p.life / 30);
      const fadeOut = Math.min(1, (p.maxLife - p.life) / 42);
      const baseAlpha = fadeIn * fadeOut * cardFade * (0.62 + Math.min(energy, 1) * 0.34);
      if (baseAlpha <= 0.02) continue;

      const [r, g, b] = sampleSectorColor(
        p.x / width,
        p.y / height,
        t,
        p.hueJitter,
        p.emeraldAccent,
        energy,
      );

      const tailIndex = (p.trailHead - (p.trailLen - 1) + TRAIL_CAPACITY) % TRAIL_CAPACITY;
      const tailX = p.trailX[tailIndex];
      const tailY = p.trailY[tailIndex];
      const headX = p.trailX[p.trailHead];
      const headY = p.trailY[p.trailHead];

      const span = Math.hypot(headX - tailX, headY - tailY);
      if (span < 2 || span > 260) continue;

      const grad = ctx.createLinearGradient(tailX, tailY, headX, headY);
      grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
      grad.addColorStop(0.45, `rgba(${r}, ${g}, ${b}, ${(baseAlpha * 0.42).toFixed(3)})`);
      grad.addColorStop(0.85, `rgba(${r}, ${g}, ${b}, ${(baseAlpha * 0.85).toFixed(3)})`);
      grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, ${baseAlpha.toFixed(3)})`);

      ctx.beginPath();
      for (let k = 0; k < p.trailLen; k++) {
        const idx = (tailIndex + k) % TRAIL_CAPACITY;
        const px = p.trailX[idx];
        const py = p.trailY[idx];
        if (k === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = grad;
      ctx.lineWidth = p.thickness * (1 + Math.min(energy, 1) * 0.45);
      ctx.stroke();

      if (energy > 0.15 || p.thickness > 2.2) {
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${Math.min(1, baseAlpha * 1.1).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(headX, headY, p.thickness * 0.65, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  };

  let obstacleSyncTick = 0;
  const frame = (now: number) => {
    rafId = 0;
    if (disposed || document.hidden) return;
    const dt = lastTime ? Math.min((now - lastTime) / 1000, 0.05) : 1 / 60;
    lastTime = now;
    elapsed += dt;

    if (pointer.active) {
      if (pointer.smoothX < -1000) {
        pointer.smoothX = pointer.x;
        pointer.smoothY = pointer.y;
      } else {
        const lerp = 1 - Math.exp(-12 * dt);
        pointer.smoothX += (pointer.x - pointer.smoothX) * lerp;
        pointer.smoothY += (pointer.y - pointer.smoothY) * lerp;
      }
    }
    pointer.vx *= Math.exp(-8 * dt);
    pointer.vy *= Math.exp(-8 * dt);

    if (++obstacleSyncTick % 15 === 0) {
      refreshObstacle();
    }

    ctx.clearRect(0, 0, width, height);
    drawAmbientGlows(elapsed);
    drawOpticalRibbons(dt, elapsed);
    drawShockwaves(dt);
    stepAndDrawParticles(dt, elapsed, true);

    rafId = requestAnimationFrame(frame);
  };

  const start = () => {
    if (disposed || document.hidden || rafId) return;
    lastTime = 0;
    rafId = requestAnimationFrame(frame);
  };

  const stop = () => {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
  };

  const onPointerMove = (e: PointerEvent) => {
    if (e.pointerType === 'touch') return;
    const bounds = container.getBoundingClientRect();
    const nx = e.clientX - bounds.left;
    const ny = e.clientY - bounds.top;
    if (pointer.active) {
      pointer.vx = Math.max(-18, Math.min(18, (nx - pointer.x) * 0.45));
      pointer.vy = Math.max(-18, Math.min(18, (ny - pointer.y) * 0.45));
    }
    pointer.x = nx;
    pointer.y = ny;
    pointer.active = nx >= 0 && nx <= width && ny >= 0 && ny <= height;
  };

  const onPointerDown = (e: PointerEvent) => {
    if (e.pointerType === 'touch') return;
    const target = e.target as HTMLElement | null;
    if (target?.closest('[data-login-particle-obstacle]')) return;
    const bounds = container.getBoundingClientRect();
    const x = e.clientX - bounds.left;
    const y = e.clientY - bounds.top;
    if (shockwaves.length < 3) {
      shockwaves.push({
        x,
        y,
        radius: 10,
        maxRadius: Math.min(width, height) * 0.34,
        alpha: 1,
      });
    }
  };

  const onPointerLeave = () => {
    pointer.active = false;
    pointer.vx = 0;
    pointer.vy = 0;
  };

  const onVisibilityChange = () => {
    if (document.hidden) stop();
    else start();
  };

  const onMotionChange = () => {
    syncParticlePool();
  };

  resize();
  for (let i = 0; i < 28; i++) {
    elapsed += 1 / 60;
    stepAndDrawParticles(1 / 60, elapsed, false);
  }
  start();

  const observer = new ResizeObserver(resize);
  observer.observe(container);
  window.addEventListener('pointermove', onPointerMove, { passive: true });
  window.addEventListener('pointerdown', onPointerDown, { passive: true });
  document.documentElement.addEventListener('pointerleave', onPointerLeave);
  window.addEventListener('blur', onPointerLeave);
  document.addEventListener('visibilitychange', onVisibilityChange);
  motionQuery.addEventListener('change', onMotionChange);

  return () => {
    disposed = true;
    stop();
    observer.disconnect();
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerdown', onPointerDown);
    document.documentElement.removeEventListener('pointerleave', onPointerLeave);
    window.removeEventListener('blur', onPointerLeave);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    motionQuery.removeEventListener('change', onMotionChange);
    canvas.remove();
  };
}
