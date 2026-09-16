import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface NetworkParticle {
  pos: THREE.Vector3;
  anchor: THREE.Vector3;
  velocity: THREE.Vector3;
  rotZ: number;
  baseScale: THREE.Vector3;
  layer: 'far' | 'mid' | 'near';
  color: THREE.Color;
  noiseSeed: number;
  orbitRadius: number;
  orbitAngle: number;
  orbitSpeed: number;
}

export const ThreeCyberNetwork: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [webglSupported, setWebglSupported] = useState(true);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    try {
      const canvasTest = document.createElement('canvas');
      if (!window.WebGLRenderingContext || (!canvasTest.getContext('webgl') && !canvasTest.getContext('experimental-webgl'))) {
        setWebglSupported(false);
        return;
      }
    } catch {
      setWebglSupported(false);
      return;
    }

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let animationFrameId: number;
    let width = window.innerWidth;
    let height = window.innerHeight;

    // Scene, Camera, Renderer
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 0, 8.5);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Nexora NetOps Spatial Color Palette
    const colorBrandBlue = new THREE.Color('#2563EB'); // Nexora Blue
    const colorSkyBlue   = new THREE.Color('#0284C7'); // Cyan/Sky
    const colorCyan      = new THREE.Color('#0EA5E9'); // Light Cyan
    const colorViolet    = new THREE.Color('#7C3AED'); // Deep Violet
    const colorPurple    = new THREE.Color('#8B5CF6'); // Purple
    const colorIndigo    = new THREE.Color('#4F46E5'); // Indigo
    const colorAmber     = new THREE.Color('#F59E0B'); // Rare Amber Accent

    const palette = [
      colorBrandBlue,
      colorSkyBlue,
      colorCyan,
      colorViolet,
      colorPurple,
      colorIndigo,
    ];

    // Hierarchy: Far (120), Mid (150), Near (14)
    const FAR_COUNT = 120;
    const MID_COUNT = 150;
    const NEAR_COUNT = 14;
    const TOTAL_COUNT = FAR_COUNT + MID_COUNT + NEAR_COUNT;

    const particles: NetworkParticle[] = [];

    // Cylinder Geometry: unit length 1.0, radius 0.009
    const geom = new THREE.CylinderGeometry(0.009, 0.009, 1.0, 8);
    geom.rotateZ(Math.PI / 2); // align along X axis

    const mat = new THREE.MeshBasicMaterial({
      transparent: true,
      opacity: 0.90,
    });

    const instancedMesh = new THREE.InstancedMesh(geom, mat, TOTAL_COUNT);
    instancedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    scene.add(instancedMesh);

    let pIndex = 0;

    // 1. FAR LAYER: Micro background network nodes
    for (let i = 0; i < FAR_COUNT; i++, pIndex++) {
      const angle = i * 2.3999632;
      const r = 2.0 + Math.pow(i / FAR_COUNT, 0.7) * 4.6 + (Math.random() - 0.5) * 0.35;
      const x = Math.cos(angle) * r * 1.4;
      const y = Math.sin(angle) * r * 0.95;
      const z = -2.5 + Math.random() * 1.4;

      const anchor = new THREE.Vector3(x, y, z);
      const pos = anchor.clone();
      const velocity = new THREE.Vector3(0, 0, 0);

      const baseScale = new THREE.Vector3(0.030 + Math.random() * 0.015, 0.7, 0.7);
      const pColor = palette[i % palette.length].clone();

      particles.push({
        pos,
        anchor,
        velocity,
        rotZ: angle,
        baseScale,
        layer: 'far',
        color: pColor,
        noiseSeed: Math.random() * 200,
        orbitRadius: r,
        orbitAngle: angle,
        orbitSpeed: (0.004 + Math.random() * 0.006) * (Math.random() > 0.5 ? 1 : -1),
      });

      instancedMesh.setColorAt(pIndex, pColor);
    }

    // 2. MID LAYER: Flowing Network Capsule Field (Generous white space)
    for (let i = 0; i < MID_COUNT; i++, pIndex++) {
      const angle = i * 2.3999632;
      const r = 1.6 + Math.pow(i / MID_COUNT, 0.75) * 3.5 + (Math.random() - 0.5) * 0.25;
      const x = Math.cos(angle) * r * 1.35;
      const y = Math.sin(angle) * r * 0.95;
      const z = -0.4 + Math.random() * 1.0;

      const anchor = new THREE.Vector3(x, y, z);
      const pos = anchor.clone();
      const velocity = new THREE.Vector3(0, 0, 0);

      const isShort = Math.random() < 0.4;
      const baseScale = new THREE.Vector3(
        isShort ? 0.045 + Math.random() * 0.015 : 0.075 + Math.random() * 0.025,
        0.95 + Math.random() * 0.2,
        0.95 + Math.random() * 0.2
      );

      let pColor: THREE.Color;
      if (Math.random() < 0.035) {
        pColor = colorAmber.clone();
      } else {
        const normAngle = ((angle % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2)) / (Math.PI * 2);
        const colorIdx = Math.floor(normAngle * palette.length) % palette.length;
        pColor = palette[colorIdx].clone();
      }

      particles.push({
        pos,
        anchor,
        velocity,
        rotZ: angle,
        baseScale,
        layer: 'mid',
        color: pColor,
        noiseSeed: Math.random() * 200,
        orbitRadius: r,
        orbitAngle: angle,
        orbitSpeed: (0.007 + Math.random() * 0.010) * (Math.random() > 0.5 ? 1 : -1),
      });

      instancedMesh.setColorAt(pIndex, pColor);
    }

    // 3. NEAR LAYER: Soft spatial floaters
    for (let i = 0; i < NEAR_COUNT; i++, pIndex++) {
      const angle = (i / NEAR_COUNT) * Math.PI * 2 + 0.3;
      const r = 2.2 + Math.random() * 2.8;
      const x = Math.cos(angle) * r * 1.35;
      const y = Math.sin(angle) * r * 0.95;
      const z = 1.2 + Math.random() * 0.9;

      const anchor = new THREE.Vector3(x, y, z);
      const pos = anchor.clone();
      const velocity = new THREE.Vector3(0, 0, 0);

      const baseScale = new THREE.Vector3(0.095 + Math.random() * 0.025, 1.15, 1.15);
      const pColor = Math.random() > 0.5 ? colorBrandBlue.clone() : colorViolet.clone();

      particles.push({
        pos,
        anchor,
        velocity,
        rotZ: angle + 0.2,
        baseScale,
        layer: 'near',
        color: pColor,
        noiseSeed: Math.random() * 200,
        orbitRadius: r,
        orbitAngle: angle,
        orbitSpeed: 0.010 * (Math.random() > 0.5 ? 1 : -1),
      });

      instancedMesh.setColorAt(pIndex, pColor);
    }

    if (instancedMesh.instanceColor) {
      instancedMesh.instanceColor.needsUpdate = true;
    }

    // 4. Faint Telemetry Lines (Connecting nearby mid-layer nodes)
    const MAX_LINE_SEGMENTS = 35;
    const linePositions = new Float32Array(MAX_LINE_SEGMENTS * 2 * 3);
    const lineColors = new Float32Array(MAX_LINE_SEGMENTS * 2 * 3);

    const lineGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    lineGeometry.setAttribute('color', new THREE.BufferAttribute(lineColors, 3));

    const lineMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.15,
      linewidth: 1,
    });
    const lineMesh = new THREE.LineSegments(lineGeometry, lineMaterial);
    scene.add(lineMesh);

    // Mouse Tracking in 3D Space (Raycaster on plane Z = 0)
    const raycaster = new THREE.Raycaster();
    const mouseNDC = new THREE.Vector2(9999, 9999);
    const planeZ0 = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

    const mouse3D = new THREE.Vector3(9999, 9999, 0);
    const prevMouse3D = new THREE.Vector3(9999, 9999, 0);
    const mouseVelocity = new THREE.Vector2(0, 0);
    let hasMouseMoved = false;

    const onMouseMove = (e: MouseEvent) => {
      mouseNDC.x = (e.clientX / window.innerWidth) * 2 - 1;
      mouseNDC.y = -(e.clientY / window.innerHeight) * 2 + 1;

      raycaster.setFromCamera(mouseNDC, camera);
      const intersection = new THREE.Vector3();
      raycaster.ray.intersectPlane(planeZ0, intersection);

      if (intersection) {
        if (!hasMouseMoved) {
          prevMouse3D.copy(intersection);
          hasMouseMoved = true;
        } else {
          prevMouse3D.copy(mouse3D);
        }
        mouse3D.copy(intersection);
        mouseVelocity.set(
          (mouse3D.x - prevMouse3D.x) * 0.5,
          (mouse3D.y - prevMouse3D.y) * 0.5
        );
      }
    };

    const onMouseLeave = () => {
      mouse3D.set(9999, 9999, 0);
      mouseVelocity.set(0, 0);
      hasMouseMoved = false;
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseleave', onMouseLeave);

    const dummy = new THREE.Object3D();
    const clock = new THREE.Clock();

    const animate = () => {
      if (!prefersReducedMotion) {
        animationFrameId = requestAnimationFrame(animate);
      }
      const elapsedTime = clock.getElapsedTime();

      // Mouse momentum decay
      mouseVelocity.multiplyScalar(0.90);

      // Interactive Anti-Gravity Repulsion Field (Active wave around cursor)
      const influenceRadius = 2.6;
      const forceStrength = 0.32;
      const cycleTime = elapsedTime * 0.32;

      for (let i = 0; i < TOTAL_COUNT; i++) {
        const p = particles[i];

        // 1. Organic Harmonic Orbit Position (Resting State)
        const layerSpeedFactor = p.layer === 'far' ? 0.35 : p.layer === 'mid' ? 0.75 : 1.1;
        const currentAngle = p.orbitAngle + elapsedTime * p.orbitSpeed * layerSpeedFactor;
        const harmonic = Math.sin(cycleTime + p.noiseSeed) * 0.035;
        const effectiveR = p.orbitRadius * (1 + harmonic);

        const targetX = Math.cos(currentAngle) * effectiveR * 1.35;
        const targetY = Math.sin(currentAngle) * effectiveR * 0.95;
        const targetZ = p.anchor.z + Math.cos(cycleTime * 0.8 + p.noiseSeed * 0.5) * 0.04;

        // 2. Active Cursor Repulsion Wave (Dynamic interaction at cursor B)
        const dx = p.pos.x - mouse3D.x;
        const dy = p.pos.y - mouse3D.y;
        const dz = p.pos.z - mouse3D.z;
        const distSq = dx * dx + dy * dy + dz * dz;
        const dist = Math.sqrt(distSq);

        if (dist < influenceRadius && dist > 0.001) {
          const normDist = 1.0 - dist / influenceRadius;
          const repulse = (Math.pow(normDist, 1.8) * forceStrength) / (dist + 0.12);

          // Push outward radially from cursor
          p.velocity.x += (dx / dist) * repulse;
          p.velocity.y += (dy / dist) * repulse;
          p.velocity.z += (dz / dist) * repulse * 0.5;

          // Drag with mouse velocity flow
          p.velocity.x += mouseVelocity.x * normDist * 0.35;
          p.velocity.y += mouseVelocity.y * normDist * 0.35;
        }

        // 3. Spring restoring force (Particles at old coordinate A smoothly relax back to resting orbit at A)
        const springK = 0.042;
        p.velocity.x += (targetX - p.pos.x) * springK;
        p.velocity.y += (targetY - p.pos.y) * springK;
        p.velocity.z += (targetZ - p.pos.z) * springK;

        // 4. Damping
        p.velocity.multiplyScalar(0.915);
        p.pos.add(p.velocity);

        // 5. Dynamic Rotation:
        // When disturbed near cursor: points away from cursor (atan2(dy, dx))
        // When resting: aligns with curved orbit stream
        let targetRot: number;
        if (dist < influenceRadius) {
          targetRot = Math.atan2(dy, dx);
        } else {
          const tangentAngle = currentAngle + Math.PI / 2;
          const radialAngle = Math.atan2(p.pos.y, p.pos.x);
          targetRot = radialAngle * 0.65 + tangentAngle * 0.35;
        }
        p.rotZ += (targetRot - p.rotZ) * 0.08;

        // 6. Velocity Stretch
        const speed = p.velocity.length();
        const stretch = 1.0 + Math.min(speed * 3.2, 0.7);

        dummy.position.copy(p.pos);
        dummy.rotation.set(0, 0, p.rotZ);
        dummy.scale.set(p.baseScale.x * stretch, p.baseScale.y, p.baseScale.z);
        dummy.updateMatrix();

        instancedMesh.setMatrixAt(i, dummy.matrix);
      }

      instancedMesh.instanceMatrix.needsUpdate = true;

      // Update faint telemetry lines between nearby mid-layer nodes
      let lineIdx = 0;
      const positions = lineGeometry.attributes.position.array as Float32Array;
      const colors = lineGeometry.attributes.color.array as Float32Array;

      for (let i = FAR_COUNT; i < FAR_COUNT + MID_COUNT && lineIdx < MAX_LINE_SEGMENTS; i += 3) {
        const p1 = particles[i];
        for (let j = i + 1; j < Math.min(i + 8, FAR_COUNT + MID_COUNT) && lineIdx < MAX_LINE_SEGMENTS; j++) {
          const p2 = particles[j];
          const distSq = p1.pos.distanceToSquared(p2.pos);
          if (distSq < 1.4 && distSq > 0.15) {
            const idx6 = lineIdx * 6;
            positions[idx6]     = p1.pos.x;
            positions[idx6 + 1] = p1.pos.y;
            positions[idx6 + 2] = p1.pos.z;

            positions[idx6 + 3] = p2.pos.x;
            positions[idx6 + 4] = p2.pos.y;
            positions[idx6 + 5] = p2.pos.z;

            colors[idx6]     = p1.color.r;
            colors[idx6 + 1] = p1.color.g;
            colors[idx6 + 2] = p1.color.b;

            colors[idx6 + 3] = p2.color.r;
            colors[idx6 + 4] = p2.color.g;
            colors[idx6 + 5] = p2.color.b;

            lineIdx++;
          }
        }
      }

      for (let k = lineIdx * 6; k < MAX_LINE_SEGMENTS * 6; k++) {
        positions[k] = 0;
      }
      lineGeometry.attributes.position.needsUpdate = true;
      lineGeometry.attributes.color.needsUpdate = true;

      // Subtle parallax camera tracking (3-8px)
      if (mouse3D.x < 1000) {
        camera.position.x += (mouse3D.x * 0.03 - camera.position.x) * 0.025;
        camera.position.y += (mouse3D.y * 0.03 - camera.position.y) * 0.025;
        camera.lookAt(0, 0, 0);
      }

      renderer.render(scene, camera);
    };

    animate();

    const handleResize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
      if (prefersReducedMotion) {
        renderer.render(scene, camera);
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseleave', onMouseLeave);
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
      geom.dispose();
      mat.dispose();
      lineGeometry.dispose();
      lineMaterial.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  if (!webglSupported) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 w-full h-full pointer-events-auto z-0 select-none overflow-hidden"
    />
  );
};

export default ThreeCyberNetwork;
