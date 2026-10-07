import React, { useEffect, useRef } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export type CameraPreset = 'front' | 'rear' | 'iso' | 'top' | 'focus_top' | 'focus_bottom' | 'reset';

export interface DeviceFocusTarget {
  centerY: number;
  centerZ?: number;
  width?: number;
  height?: number;
  depth?: number;
  face?: 'front' | 'rear';
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

  // Handle Double-Click Device Close-up Focus
  useEffect(() => {
    if (!focusTarget) return;
    const isRear = focusTarget.face === 'rear';
    const perspectiveFov = camera instanceof THREE.PerspectiveCamera ? camera.fov : 45;
    const aspect = Math.max(0.1, size.width / Math.max(1, size.height));
    const focusHeight = Math.max(0.75, (focusTarget.height || 0.9) + 0.45);
    const focusWidth = Math.max(2.8, (focusTarget.width || Math.min(rackWidth, 4.8)) + 0.4);
    const focusDistance = THREE.MathUtils.clamp(
      calculateRackFitDistance(focusHeight, focusWidth, perspectiveFov, aspect, 1.18),
      3.1,
      7,
    );
    const direction = isRear ? -1 : 1;
    const deviceFaceZ = (focusTarget.centerZ || 0) + direction * ((focusTarget.depth || Math.min(rackDepth * 0.75, 3.8)) / 2);
    targetPos.current.set(0, focusTarget.centerY + 0.15, deviceFaceZ + direction * focusDistance);
    targetLook.current.set(0, focusTarget.centerY, deviceFaceZ);
    isTransitioning.current = true;
  }, [camera, focusTarget, rackDepth, rackWidth, size.height, size.width]);

  // When user drags, stop programmatic animation
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

  // Handle zoom button actions (+ / -)
  useEffect(() => {
    if (!zoomAction) return;
    const ctrl = controlsRef?.current;
    if (!ctrl) return;

    const factor = zoomAction.type === 'in' ? 0.8 : 1.25;
    const dir = new THREE.Vector3().subVectors(camera.position, ctrl.target);
    const newLen = THREE.MathUtils.clamp(dir.length() * factor, 3, 60);
    dir.setLength(newLen);
    targetPos.current.copy(ctrl.target).add(dir);
    targetLook.current.copy(ctrl.target);
    isTransitioning.current = true;
  }, [zoomAction, camera, controlsRef]);

  // Handle Camera Presets
  useEffect(() => {
    // A selected device owns the camera until the user explicitly resets the
    // view. This guard is important when the Inspector opens: its drawer
    // changes the Canvas aspect ratio and must not snap the camera back to the
    // rack-wide preset while the close-up is in progress.
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

    const speed = Math.min(1, delta * 6);
    camera.position.lerp(targetPos.current, speed);

    const ctrl = controlsRef?.current;
    if (ctrl) {
      ctrl.target.lerp(targetLook.current, speed);
      ctrl.update();
    }

    const posDist = camera.position.distanceTo(targetPos.current);
    const lookDist = ctrl ? ctrl.target.distanceTo(targetLook.current) : 0;

    if (posDist < 0.05 && lookDist < 0.05) {
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
