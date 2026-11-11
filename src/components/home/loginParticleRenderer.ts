import * as THREE from 'three';
import {
  simulationVertexShader, simulationFragmentShader,
  particleVertexShader, particleFragmentShader,
} from './loginParticleShaders';

const TEXTURE_SIZE = 256;

// Bridson sampling gives every particle breathing room, without the visible
// diagonal lattice or dense dust of a screen-filling quasi-random sequence.
function sampleParticleAnchors(minDistance: number): number[] {
  const cell = minDistance / Math.SQRT2;
  const side = Math.ceil(2 / cell);
  const grid = new Int32Array(side * side).fill(-1);
  const points: number[] = [];
  const active: number[] = [];
  const insert = (x: number, y: number) => {
    const index = points.length / 2;
    points.push(x, y);
    active.push(index);
    grid[Math.floor(y / cell) * side + Math.floor(x / cell)] = index;
  };
  insert(Math.random() * 2, Math.random() * 2);
  while (active.length) {
    const activeIndex = Math.floor(Math.random() * active.length);
    const index = active[activeIndex];
    let found = false;
    for (let attempt = 0; attempt < 20; attempt++) {
      const angle = Math.random() * Math.PI * 2;
      const radius = minDistance * (1 + Math.random());
      const x = points[index * 2] + Math.cos(angle) * radius;
      const y = points[index * 2 + 1] + Math.sin(angle) * radius;
      if (x < 0 || y < 0 || x >= 2 || y >= 2) continue;
      const column = Math.floor(x / cell), row = Math.floor(y / cell);
      let clear = true;
      for (let gy = Math.max(0, row - 2); gy <= Math.min(side - 1, row + 2) && clear; gy++) {
        for (let gx = Math.max(0, column - 2); gx <= Math.min(side - 1, column + 2); gx++) {
          const other = grid[gy * side + gx];
          if (other >= 0 && Math.hypot(points[other * 2] - x, points[other * 2 + 1] - y) < minDistance) {
            clear = false;
            break;
          }
        }
      }
      if (clear) { insert(x, y); found = true; break; }
    }
    if (!found) active.splice(activeIndex, 1);
  }
  return points.map(value => value - 1);
}

export function createLoginParticleRenderer(container: HTMLDivElement): () => void {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setClearColor(0xffffff, 0);
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  camera.position.z = 3.1;
  const scene = new THREE.Scene();
  const anchors = sampleParticleAnchors(motionPreference.matches ? 0.027 : 0.01547);
  const count = anchors.length / 2;
  const state = new Float32Array(TEXTURE_SIZE * TEXTURE_SIZE * 4);
  const uv = new Float32Array(count * 2);
  const seeds = new Float32Array(count * 4);
  for (let index = 0; index < count; index++) {
    state[index * 4] = anchors[index * 2];
    state[index * 4 + 1] = anchors[index * 2 + 1];
    uv[index * 2] = ((index % TEXTURE_SIZE) + 0.5) / TEXTURE_SIZE;
    uv[index * 2 + 1] = (Math.floor(index / TEXTURE_SIZE) + 0.5) / TEXTURE_SIZE;
    for (let channel = 0; channel < 4; channel++) seeds[index * 4 + channel] = Math.random();
  }
  const references = new THREE.DataTexture(state, TEXTURE_SIZE, TEXTURE_SIZE, THREE.RGBAFormat, THREE.FloatType);
  references.needsUpdate = true;
  const ring = new THREE.Vector2();
  const pointer = new THREE.Vector2();
  const target = new THREE.Vector2();
  const simulationUniforms = {
    stateTexture: { value: references as THREE.Texture }, referenceTexture: { value: references },
    ringCenter: { value: ring }, time: { value: 0 }, delta: { value: 1 / 60 },
    resolution: { value: new THREE.Vector2(TEXTURE_SIZE, TEXTURE_SIZE) },
  };
  const simulationMaterial = new THREE.ShaderMaterial({
    uniforms: simulationUniforms, vertexShader: simulationVertexShader,
    fragmentShader: simulationFragmentShader, depthTest: false, depthWrite: false,
  });
  const simulationScene = new THREE.Scene();
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), simulationMaterial);
  simulationScene.add(quad);
  const simulationCamera = new THREE.Camera();
  const makeTarget = () => new THREE.WebGLRenderTarget(TEXTURE_SIZE, TEXTURE_SIZE, {
    type: THREE.HalfFloatType, format: THREE.RGBAFormat,
    minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter,
    depthBuffer: false, stencilBuffer: false,
  });
  let readTarget = makeTarget(), writeTarget = makeTarget();
  const canSimulate = renderer.extensions.has('EXT_color_buffer_float');
  let simulated = false;
  // Unsupported floating-point targets still get a sparse static field.
  if (!canSimulate) {
    for (let index = 0; index < count; index++) {
      state[index * 4 + 2] = 0.3 + Math.random() * 0.6;
      state[index * 4 + 3] = state[index * 4 + 2] * 0.5;
    }
    references.needsUpdate = true;
  }
  const particleUniforms = {
    stateTexture: { value: references as THREE.Texture }, ringCenter: { value: ring },
    time: { value: 0 }, pixelRatio: { value: 1 }, particleScale: { value: 1 },
  };
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  geometry.setAttribute('referenceUv', new THREE.BufferAttribute(uv, 2));
  geometry.setAttribute('seed', new THREE.BufferAttribute(seeds, 4));
  const material = new THREE.ShaderMaterial({
    uniforms: particleUniforms, vertexShader: particleVertexShader, fragmentShader: particleFragmentShader,
    transparent: true, depthWrite: false, depthTest: false,
  });
  const points = new THREE.Points(geometry, material);
  points.scale.setScalar(5);
  points.frustumCulled = false;
  scene.add(points);
  let frame = 0, lastFrame = 0, elapsed = 0;
  let pointerInside = false, disposed = false, contextLost = false;
  let width = 1, height = 1;
  const render = (delta: number) => {
    if (contextLost) return;
    if (canSimulate) {
      simulationUniforms.stateTexture.value = simulated ? readTarget.texture : references;
      simulationUniforms.time.value = elapsed;
      simulationUniforms.delta.value = delta;
      renderer.setRenderTarget(writeTarget);
      renderer.render(simulationScene, simulationCamera);
      renderer.setRenderTarget(null);
      particleUniforms.stateTexture.value = writeTarget.texture;
      [readTarget, writeTarget] = [writeTarget, readTarget];
      simulated = true;
    }
    particleUniforms.time.value = elapsed;
    renderer.render(scene, camera);
  };
  const resize = () => {
    const bounds = container.getBoundingClientRect();
    width = Math.max(bounds.width, 1); height = Math.max(bounds.height, 1);
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(pixelRatio);
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    particleUniforms.pixelRatio.value = pixelRatio;
    particleUniforms.particleScale.value = width / 2000 * 0.59;
    render(1 / 60);
  };
  const animate = (now: number) => {
    frame = 0;
    if (disposed || document.hidden || (motionPreference.matches && !pointerInside) || contextLost) return;
    const delta = lastFrame ? Math.min((now - lastFrame) / 1000, 0.05) : 1 / 60;
    lastFrame = now; elapsed += delta;
    const noiseX = Math.sin(elapsed * 0.66 + 94.234) * 0.65 + Math.sin(elapsed * 0.24) * 0.35;
    const noiseY = Math.sin(elapsed * 0.75 + 21.028) * 0.65 + Math.sin(elapsed * 0.31) * 0.35;
    const targetX = pointerInside ? pointer.x + noiseX * 0.1 : noiseX * 0.2;
    const targetY = pointerInside ? pointer.y + noiseY * 0.1 : noiseY * 0.1;
    ring.lerp(target.set(targetX, targetY), 1 - Math.exp(-(pointerInside ? 1.212 : 0.603) * delta));
    render(delta);
    frame = requestAnimationFrame(animate);
  };
  const syncAnimation = () => {
    cancelAnimationFrame(frame); frame = 0; lastFrame = 0;
    if (disposed || document.hidden || contextLost) return;
    if ((motionPreference.matches && !pointerInside) || !canSimulate) {
      elapsed = 0; ring.set(0, 0); simulated = false;
      // Settle a single stationary frame instead of leaving half-grown points.
      for (let index = 0; index < (canSimulate ? 30 : 1); index++) render(1 / 60);
    } else frame = requestAnimationFrame(animate);
  };
  const onPointerMove = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return;
    const bounds = container.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / width * 2 - 1;
    const y = -((event.clientY - bounds.top) / height * 2 - 1);
    const halfHeight = Math.tan(THREE.MathUtils.degToRad(20)) * camera.position.z;
    pointer.set(x * halfHeight * camera.aspect * 0.175, y * halfHeight * 0.175);
    pointerInside = Math.abs(x) <= 1 && Math.abs(y) <= 1;
    // Reduced motion keeps the idle field still, while deliberate pointer input
    // can still move it. Resume only when no animation is already scheduled.
    if (motionPreference.matches && pointerInside && !frame && canSimulate) syncAnimation();
  };
  const onPointerLeave = () => {
    pointerInside = false;
    if (motionPreference.matches) syncAnimation();
  };
  const onContextLost = (event: Event) => { event.preventDefault(); contextLost = true; cancelAnimationFrame(frame); };
  const onContextRestored = () => { contextLost = false; simulated = false; syncAnimation(); };
  container.appendChild(renderer.domElement);
  resize(); syncAnimation();
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  window.addEventListener('pointermove', onPointerMove, { passive: true });
  document.documentElement.addEventListener('pointerleave', onPointerLeave);
  window.addEventListener('blur', onPointerLeave);
  document.addEventListener('visibilitychange', syncAnimation);
  motionPreference.addEventListener('change', syncAnimation);
  renderer.domElement.addEventListener('webglcontextlost', onContextLost);
  renderer.domElement.addEventListener('webglcontextrestored', onContextRestored);
  return () => {
    disposed = true; cancelAnimationFrame(frame); observer.disconnect();
    window.removeEventListener('pointermove', onPointerMove);
    document.documentElement.removeEventListener('pointerleave', onPointerLeave);
    window.removeEventListener('blur', onPointerLeave);
    document.removeEventListener('visibilitychange', syncAnimation);
    motionPreference.removeEventListener('change', syncAnimation);
    renderer.domElement.removeEventListener('webglcontextlost', onContextLost);
    renderer.domElement.removeEventListener('webglcontextrestored', onContextRestored);
    geometry.dispose(); material.dispose(); simulationMaterial.dispose(); quad.geometry.dispose();
    references.dispose(); readTarget.dispose(); writeTarget.dispose(); renderer.dispose(); renderer.domElement.remove();
  };
}
