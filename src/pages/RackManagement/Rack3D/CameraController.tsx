import React, { useEffect, useRef } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export type CameraPreset = 'front' | 'rear' | 'iso' | 'top' | 'focus_top' | 'focus_bottom' | 'reset';

export interface DeviceFocusTarget {
  centerX?: number;
  centerY: number;
  centerZ?: number;
  width?: number;
  height?: number;
  depth?: number;
  face?: 'front' | 'rear';
  /** Explicit standoff distance from faceplate for macro close-up spots. */
  distance?: number;
  /** Optional short badge label for the focused region. */
  spotLabel?: string;
  timestamp: number;
}

interface CameraControllerProps {
  preset: CameraPreset;
  rackHeight: number;
  rackWidth: number;
  rackDepth: number;
  focusTarget?: DeviceFocusTarget | null;
  zoomAction?: { type: 'in' | 'out'; timestamp: number } | null;
  controlsRef?: React.RefObject<any>;
  onPresetApplied?: () => void;
}

export function calculateRackFitDistance(
  height: number,
  width: number,
  verticalFovDegrees: number,
  aspect: number,
  padding = 1.18,
): number {
  const verticalFov = THREE.MathUtils.degToRad(verticalFovDegrees);
  const safeAspect = Math.max(0.1, aspect);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * safeAspect);
  return Math.max(
    height / (2 * Math.tan(verticalFov / 2)),
    width / (2 * Math.tan(horizontalFov / 2)),
  ) * padding;
}

export interface FocusCameraPose {
  position: [number, number, number];
  lookAt: [number, number, number];
  distance: number;
}

export function calculateDeviceFocusPose(
  focusTarget: DeviceFocusTarget,
  rackWidth: number,
  rackDepth: number,
  verticalFovDegrees: number,
  aspect: number,
): FocusCameraPose {
  const isRear = focusTarget.face === 'rear';
  const direction = isRear ? -1 : 1;
  const targetX = focusTarget.centerX ?? 0;
  const targetY = focusTarget.centerY;
  const deviceFaceZ = (focusTarget.centerZ || 0)
    + direction * ((focusTarget.depth || Math.min(rackDepth * 0.75, 3.8)) / 2 + 0.14);

  const isMacroSpot = typeof focusTarget.distance === 'number' && Number.isFinite(focusTarget.distance);
  let focusDistance: number;
  if (isMacroSpot) {
    focusDistance = THREE.MathUtils.clamp(focusTarget.distance as number, 0.62, 12);
  } else {
    const focusHeight = Math.max(0.65, (focusTarget.height || 0.9) + 0.38);
    const focusWidth = Math.max(2.4, (focusTarget.width || Math.min(rackWidth, 4.8)) + 0.35);
    focusDistance = THREE.MathUtils.clamp(
      calculateRackFitDistance(focusHeight, focusWidth, verticalFovDegrees, aspect, 1.14),
      2.2,
      7.0,
    );
  }

  // Keep macro close-ups nearly perpendicular to the faceplate so ports & LEDs
  // are never foreshortened or obscured by upper/lower rack flanges.
  const pitchLift = isMacroSpot ? 0.02 : 0.1;
  return {
    position: [targetX, targetY + pitchLift, deviceFaceZ + direction * focusDistance],
    lookAt: [targetX, targetY, deviceFaceZ],
    distance: focusDistance,
  };
}

export const CameraController: React.FC<CameraControllerProps> = ({
  preset,
  rackHeight,
  rackWidth,
  rackDepth,
  focusTarget,
  zoomAction,
  controlsRef,
  onPresetApplied
}) => {
  const { camera, size } = useThree();

  const targetPos = useRef(new THREE.Vector3(0, rackHeight / 2, 28));
  const targetLook = useRef(new THREE.Vector3(0, rackHeight / 2, 0));
  const isTransitioning = useRef(false);
  const lastAppliedFocusTsRef = useRef<number | null>(null);
  const sizeRef = useRef(size);
  sizeRef.current = size;

  // Handle device selection, double-click exact-spot macro, and section-jump focus.
  // Keyed on focusTarget.timestamp so opening/closing the right-side Inspector drawer
  // or resizing the browser never snaps the user's carefully positioned macro view back.
  useEffect(() => {
    if (!focusTarget) {
      lastAppliedFocusTsRef.current = null;
      return;
    }
    if (lastAppliedFocusTsRef.current === focusTarget.timestamp) return;
    lastAppliedFocusTsRef.current = focusTarget.timestamp;

    const perspectiveFov = camera instanceof THREE.PerspectiveCamera ? camera.fov : 45;
    const aspect = Math.max(0.1, sizeRef.current.width / Math.max(1, sizeRef.current.height));
    const pose = calculateDeviceFocusPose(focusTarget, rackWidth, rackDepth, perspectiveFov, aspect);
    targetPos.current.set(...pose.position);
    targetLook.current.set(...pose.lookAt);
    isTransitioning.current = true;
  }, [camera, focusTarget, rackDepth, rackWidth]);

  // When user drags or zooms manually, immediately cancel programmatic camera flight
  useEffect(() => {
    const ctrl = controlsRef?.current;
    if (!ctrl) return;

    const handleStart = () => {
      isTransitioning.current = false;
    };

    ctrl.addEventListener('start', handleStart);
    return () => {
      ctrl.removeEventListener('start', handleStart);
    };
  }, [controlsRef]);

  // Keyboard micro-panning (Arrow keys / WASD) for smooth port-by-port close-up sliding
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const activeTag = (document.activeElement?.tagName || '').toLowerCase();
      if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;

      let rightSteps = 0;
      let upSteps = 0;
      switch (event.key) {
        case 'ArrowLeft':
        case 'a':
        case 'A':
          rightSteps = -1;
          break;
        case 'ArrowRight':
        case 'd':
        case 'D':
          rightSteps = 1;
          break;
        case 'ArrowUp':
        case 'w':
        case 'W':
          upSteps = 1;
          break;
        case 'ArrowDown':
        case 's':
        case 'S':
          upSteps = -1;
          break;
        default:
          return;
      }

      const ctrl = controlsRef?.current;
      if (!ctrl) return;
      event.preventDefault();
      isTransitioning.current = false;

      const dist = camera.position.distanceTo(ctrl.target);
      const step = Math.max(0.08, Math.min(1.2, dist * 0.14));

      const rightVec = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0).normalize();
      const upVec = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1).normalize();
      const deltaVec = new THREE.Vector3()
        .addScaledVector(rightVec, rightSteps * step)
        .addScaledVector(upVec, upSteps * step);

      camera.position.add(deltaVec);
      ctrl.target.add(deltaVec);
      ctrl.update();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [camera, controlsRef]);

  // Handle zoom button actions (+ / -) with true macro close-up depth down to 0.62
  useEffect(() => {
    if (!zoomAction) return;
    const ctrl = controlsRef?.current;
    if (!ctrl) return;

    const factor = zoomAction.type === 'in' ? 0.72 : 1.38;
    const dir = new THREE.Vector3().subVectors(camera.position, ctrl.target);
    const newLen = THREE.MathUtils.clamp(dir.length() * factor, 0.62, 60);
    dir.setLength(newLen);
    targetPos.current.copy(ctrl.target).add(dir);
    targetLook.current.copy(ctrl.target);
    isTransitioning.current = true;
  }, [zoomAction, camera, controlsRef]);

  // Handle Camera Presets
  useEffect(() => {
    // A selected/focused device owns the camera until the user explicitly resets the view.
    if (focusTarget) return;
    const centerY = rackHeight / 2;
    const perspectiveFov = camera instanceof THREE.PerspectiveCamera ? camera.fov : 45;
    const aspect = Math.max(0.1, size.width / Math.max(1, size.height));
    const distanceZ = Math.max(12, calculateRackFitDistance(rackHeight + 1.2, rackWidth + 1.5, perspectiveFov, aspect));
    const topDistance = Math.max(10, calculateRackFitDistance(rackDepth + 2, rackWidth + 2, perspectiveFov, aspect, 1.1));

    switch (preset) {
      case 'front':
        targetPos.current.set(0, centerY, distanceZ);
        targetLook.current.set(0, centerY, 0);
        break;
      case 'rear':
        targetPos.current.set(0, centerY, -distanceZ);
        targetLook.current.set(0, centerY, 0);
        break;
      case 'iso':
        targetPos.current.set(distanceZ * 0.7, centerY + Math.min(8, rackHeight * 0.35), distanceZ * 0.8);
        targetLook.current.set(0, centerY, 0);
        break;
      case 'top':
        targetPos.current.set(0, rackHeight + topDistance, 0.1);
        targetLook.current.set(0, centerY, 0);
        break;
      case 'focus_top':
        // Smoothly zoom in and focus on upper rack (U32 ~ U42)
        targetPos.current.set(0, rackHeight * 0.82 + 1, 14);
        targetLook.current.set(0, rackHeight * 0.82, 0);
        break;
      case 'focus_bottom':
        // Smoothly zoom in and focus on lower rack (U1 ~ U12)
        targetPos.current.set(0, rackHeight * 0.2 + 1, 14);
        targetLook.current.set(0, rackHeight * 0.2, 0);
        break;
      case 'reset':
      default:
        targetPos.current.set(distanceZ * 0.6, centerY + 5, distanceZ * 0.8);
        targetLook.current.set(0, centerY, 0);
        break;
    }
    isTransitioning.current = true;
    if (onPresetApplied) onPresetApplied();
  }, [preset, rackHeight, rackWidth, rackDepth, size.width, size.height, camera, onPresetApplied, focusTarget]);

  useFrame((_, delta) => {
    if (!isTransitioning.current) return;

    const speed = Math.min(1, delta * 7.5);
    camera.position.lerp(targetPos.current, speed);

    const ctrl = controlsRef?.current;
    if (ctrl) {
      ctrl.target.lerp(targetLook.current, speed);
      ctrl.update();
    }

    const posDist = camera.position.distanceTo(targetPos.current);
    const lookDist = ctrl ? ctrl.target.distanceTo(targetLook.current) : 0;

    if (posDist < 0.025 && lookDist < 0.025) {
      camera.position.copy(targetPos.current);
      if (ctrl) {
        ctrl.target.copy(targetLook.current);
        ctrl.update();
      }
      isTransitioning.current = false;
    }
  });

  return null;
};
