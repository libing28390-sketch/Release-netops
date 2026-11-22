// Aurora Mesh Gradient + Optical Fiber Background Renderer for the Nexora Login Screen.
// Renders a smooth, breathing multi-stop pastel aurora gradient paired with
// three sweeping optical-backbone fiber curves and luminous telemetry pulses.

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
  packetLen: number;
  rgb: readonly [number, number, number];
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
    active: false,
    smoothX: -9999,
    smoothY: -9999,
  };

  let obstacleRect: { cx: number; cy: number; rx: number; ry: number } | null = null;
  let isAuthenticating = false;

  const shockwaves: Shockwave[] = [];

  const ribbons: OpticalRibbon[] = [
    {
      yRatio: 0.22,
      amplitude: 34,
      freq: 0.00175,
      phase: 0.5,
      speed: 0.14,
      packetT: 0.16,
      packetSpeed: 0.075,
      packetLen: 145,
      rgb: [37, 99, 235],   // Cobalt Blue #2563EB
    },
    {
      yRatio: 0.54,
      amplitude: 42,
      freq: 0.00155,
      phase: 2.6,
      speed: 0.11,
      packetT: 0.62,
      packetSpeed: 0.062,
      packetLen: 170,
      rgb: [6, 182, 212],   // Luminous Cyan #06B6D4
    },
    {
      yRatio: 0.81,
      amplitude: 28,
      freq: 0.0019,
      phase: 4.9,
      speed: 0.15,
      packetT: 0.38,
      packetSpeed: 0.068,
      packetLen: 135,
      rgb: [99, 102, 241],  // Indigo #6366F1
    },
  ];

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
      rx: oBounds.width * 0.5 + 56,
      ry: oBounds.height * 0.5 + 52,
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
  };

  const drawAuroraGradient = (t: number) => {
    // 1. Silky diagonal pastel base wash so the white card floats with natural contrast
    const baseGrad = ctx.createLinearGradient(0, 0, width, height);
    baseGrad.addColorStop(0, '#f3f7ff');
    baseGrad.addColorStop(0.45, '#fafcff');
    baseGrad.addColorStop(0.75, '#f4fafe');
    baseGrad.addColorStop(1, '#f5f3ff');
    ctx.fillStyle = baseGrad;
    ctx.fillRect(0, 0, width, height);

    // 2. Slow-breathing layered aurora mesh clouds
    const maxDim = Math.max(width, height);
    const clouds: Array<{ x: number; y: number; r: number; inner: string; mid: string }> = [
      {
        x: width * (0.16 + Math.sin(t * 0.14) * 0.06),
        y: height * (0.20 + Math.cos(t * 0.11) * 0.06),
        r: maxDim * 0.48,
        inner: 'rgba(59, 130, 246, 0.14)',   // Soft Azure
        mid: 'rgba(59, 130, 246, 0.045)',
      },
      {
        x: width * (0.84 + Math.cos(t * 0.12) * 0.06),
        y: height * (0.24 + Math.sin(t * 0.13 + 0.9) * 0.05),
        r: maxDim * 0.44,
        inner: 'rgba(99, 102, 241, 0.12)',   // Periwinkle Indigo
        mid: 'rgba(139, 92, 246, 0.038)',
      },
      {
        x: width * (0.78 + Math.sin(t * 0.13 + 2.1) * 0.06),
        y: height * (0.82 + Math.cos(t * 0.14) * 0.05),
        r: maxDim * 0.48,
        inner: 'rgba(6, 182, 212, 0.13)',    // Luminous Cyan
        mid: 'rgba(14, 165, 233, 0.04)',
      },
      {
        x: width * (0.20 + Math.cos(t * 0.11 + 1.5) * 0.05),
        y: height * (0.84 + Math.sin(t * 0.12 + 0.4) * 0.05),
        r: maxDim * 0.42,
        inner: 'rgba(124, 58, 237, 0.095)',  // Soft Violet
        mid: 'rgba(99, 102, 241, 0.03)',
      },
    ];

    for (const c of clouds) {
      const grad = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, c.r);
      grad.addColorStop(0, c.inner);
      grad.addColorStop(0.55, c.mid);
      grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);
    }

    // 3. Soft center spotlight lift behind title + login card for crisp readability
    const centerLift = ctx.createRadialGradient(
      width * 0.5,
      height * 0.48,
      0,
      width * 0.5,
      height * 0.48,
      Math.min(width, height) * 0.52,
    );
    centerLift.addColorStop(0, 'rgba(255, 255, 255, 0.65)');
    centerLift.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = centerLift;
    ctx.fillRect(0, 0, width, height);

    if (pointer.active && pointer.smoothX > -1000) {
      const pGrad = ctx.createRadialGradient(
        pointer.smoothX,
        pointer.smoothY,
        0,
        pointer.smoothX,
        pointer.smoothY,
        240,
      );
      pGrad.addColorStop(0, 'rgba(6, 182, 212, 0.085)');
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
      Math.cos(x * rib.freq * 0.52 - t * rib.speed * 0.65 + rib.phase) * (rib.amplitude * 0.42);
    let y = baseY + wave;
    if (pointer.active && pointer.smoothX > -1000) {
      const dx = x - pointer.smoothX;
      const dy = y - pointer.smoothY;
      const dist = Math.hypot(dx, dy);
      if (dist < 220 && dist > 1) {
        const pull = 1 - dist / 220;
        y += (dy / dist) * pull * pull * 24;
      }
    }
    return y;
  };

  const drawOpticalRibbons = (dt: number, t: number) => {
    const segments = 56;
    const stepX = width / segments;
    const reduced = motionQuery.matches;
    const speedMult = isAuthenticating ? 1.8 : reduced ? 0.25 : 1;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const rib of ribbons) {
      const [r, g, b] = rib.rgb;

      const trackGrad = ctx.createLinearGradient(0, 0, width, 0);
      trackGrad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
      trackGrad.addColorStop(0.14, `rgba(${r}, ${g}, ${b}, 0.13)`);
      trackGrad.addColorStop(0.5, `rgba(${r}, ${g}, ${b}, 0.085)`);
      trackGrad.addColorStop(0.86, `rgba(${r}, ${g}, ${b}, 0.13)`);
      trackGrad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);

      ctx.beginPath();
      for (let i = 0; i <= segments; i++) {
        const x = i * stepX;
        const y = ribbonYAt(rib, x, t);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = trackGrad;
      ctx.lineWidth = 1.15;
      ctx.stroke();

      rib.packetT = (rib.packetT + rib.packetSpeed * speedMult * dt) % 1;
      const fadeEdge = Math.sin(rib.packetT * Math.PI);
      if (fadeEdge > 0.03) {
        const headX = rib.packetT * width;
        const tailX = Math.max(0, headX - rib.packetLen);
        const headY = ribbonYAt(rib, headX, t);
        const tailY = ribbonYAt(rib, tailX, t);

        let cardDim = 1;
        if (obstacleRect) {
          const od = Math.hypot((headX - obstacleRect.cx) / obstacleRect.rx, (headY - obstacleRect.cy) / obstacleRect.ry);
          if (od < 1.05) cardDim = Math.max(0.15, (od - 0.55) / 0.5);
        }
        const alpha = fadeEdge * cardDim;

        const pGrad = ctx.createLinearGradient(tailX, tailY, headX, headY);
        pGrad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
        pGrad.addColorStop(0.6, `rgba(${r}, ${g}, ${b}, ${(0.30 * alpha).toFixed(3)})`);
        pGrad.addColorStop(1, `rgba(${r}, ${g}, ${b}, ${(0.76 * alpha).toFixed(3)})`);

        ctx.beginPath();
        const streakSteps = 14;
        for (let k = 0; k <= streakSteps; k++) {
          const sx = tailX + ((headX - tailX) * k) / streakSteps;
          const sy = ribbonYAt(rib, sx, t);
          if (k === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        }
        ctx.strokeStyle = pGrad;
        ctx.lineWidth = 2.0;
        ctx.stroke();

        const halo = ctx.createRadialGradient(headX, headY, 0, headX, headY, 8);
        halo.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${(0.68 * alpha).toFixed(3)})`);
        halo.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(headX, headY, 8, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  };

  const drawShockwaves = (dt: number) => {
    for (let i = shockwaves.length - 1; i >= 0; i--) {
      const sw = shockwaves[i];
      sw.radius += 380 * dt;
      sw.alpha = Math.max(0, 1 - sw.radius / sw.maxRadius);
      if (sw.alpha <= 0.015) {
        shockwaves.splice(i, 1);
        continue;
      }
      const ease = sw.alpha * sw.alpha;
      ctx.beginPath();
      ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(37, 99, 235, ${(ease * 0.22).toFixed(3)})`;
      ctx.lineWidth = 1.25;
      ctx.stroke();
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
        const lerp = 1 - Math.exp(-10 * dt);
        pointer.smoothX += (pointer.x - pointer.smoothX) * lerp;
        pointer.smoothY += (pointer.y - pointer.smoothY) * lerp;
      }
    }

    if (++obstacleSyncTick % 30 === 0) {
      refreshObstacle();
    }

    ctx.clearRect(0, 0, width, height);
    drawAuroraGradient(elapsed);
    drawOpticalRibbons(dt, elapsed);
    drawShockwaves(dt);

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
        maxRadius: Math.min(width, height) * 0.28,
        alpha: 1,
      });
    }
  };

  const onPointerLeave = () => {
    pointer.active = false;
  };

  const onVisibilityChange = () => {
    if (document.hidden) stop();
    else start();
  };

  resize();
  start();

  const observer = new ResizeObserver(resize);
  observer.observe(container);
  window.addEventListener('pointermove', onPointerMove, { passive: true });
  window.addEventListener('pointerdown', onPointerDown, { passive: true });
  document.documentElement.addEventListener('pointerleave', onPointerLeave);
  window.addEventListener('blur', onPointerLeave);
  document.addEventListener('visibilitychange', onVisibilityChange);

  return () => {
    disposed = true;
    stop();
    observer.disconnect();
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerdown', onPointerDown);
    document.documentElement.removeEventListener('pointerleave', onPointerLeave);
    window.removeEventListener('blur', onPointerLeave);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    canvas.remove();
  };
}
