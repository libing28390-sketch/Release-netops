import React, { useEffect, useRef } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export type CameraPreset = 'front' | 'rear' | 'iso' | 'top' | 'focus_top' | 'focus_bottom' | 'reset';

export interface DeviceFocusTarget {
  centerY: number;
  face?: 'front' | 'rear';
  timestamp: number;
}

interface CameraControllerProps {
  preset: CameraPreset;
  rackHeight: number;
  focusTarget?: DeviceFocusTarget | null;
  zoomAction?: { type: 'in' | 'out'; timestamp: number } | null;
  controlsRef?: React.RefObject<any>;
  onPresetApplied?: () => void;
}

export const CameraController: React.FC<CameraControllerProps> = ({
  preset,
  rackHeight,
  focusTarget,
  zoomAction,
  controlsRef,
  onPresetApplied
}) => {
  const { camera } = useThree();

  const targetPos = useRef(new THREE.Vector3(0, rackHeight / 2, 28));
  const targetLook = useRef(new THREE.Vector3(0, rackHeight / 2, 0));
  const isTransitioning = useRef(false);

  // Handle Double-Click Device Close-up Focus
  useEffect(() => {
    if (!focusTarget) return;
    const isRear = focusTarget.face === 'rear';
    const distZ = isRear ? -8.5 : 8.5;
    targetPos.current.set(0, focusTarget.centerY + 0.15, distZ);
    targetLook.current.set(0, focusTarget.centerY, 0);
    isTransitioning.current = true;
  }, [focusTarget]);

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
    const centerY = rackHeight / 2;
    const distanceZ = Math.max(22, rackHeight * 1.35);

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
        targetPos.current.set(distanceZ * 0.75, centerY + 8, distanceZ * 0.85);
        targetLook.current.set(0, centerY, 0);
        break;
      case 'top':
        targetPos.current.set(0, rackHeight + distanceZ * 0.9, 0.1);
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
  }, [preset, rackHeight, onPresetApplied]);

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
