import React, { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { DeviceHealthStatus } from '../../types';

type StatusChannel = 'power' | 'system' | 'alarm';

interface FaceplateStatusLedsProps {
  width: number;
  height: number;
  healthStatus: DeviceHealthStatus;
}

interface LedVisualState {
  color: string;
  emissive: string;
  intensity: number;
}

const CHANNELS: StatusChannel[] = ['power', 'system', 'alarm'];

function getLedVisualState(
  channel: StatusChannel,
  healthStatus: DeviceHealthStatus,
  time: number,
): LedVisualState {
  if (healthStatus === 'offline') {
    return { color: '#1f2937', emissive: '#000000', intensity: 0 };
  }

  if (channel === 'power') {
    // Power is a supply indicator, not a proxy for the health alarm. Keep it
    // green while the device is reachable and only extinguish it offline.
    return {
      color: '#42f5a7',
      emissive: '#35d98c',
      intensity: 2.25 + Math.sin(time * 1.7) * 0.12,
    };
  }

  if (channel === 'system') {
    if (healthStatus === 'critical') {
      return { color: '#ff5b61', emissive: '#ef4444', intensity: 3.8 + Math.sin(time * 8) * 1.1 };
    }
    if (healthStatus === 'warning') {
      // Keep SYS green for a reachable device; the ALM lens carries the
      // amber warning blink, matching how physical switch panels behave.
      return { color: '#42f5a7', emissive: '#22c55e', intensity: 1.9 + Math.sin(time * 2.8) * 0.35 };
    }
    if (healthStatus === 'healthy') {
      return { color: '#42f5a7', emissive: '#22c55e', intensity: 0.85 + (0.5 + 0.5 * Math.sin(time * 3.2)) * 2.9 };
    }
    return { color: '#8aa4b8', emissive: '#416274', intensity: 0.45 + Math.sin(time * 1.4) * 0.08 };
  }

  if (healthStatus === 'critical') {
    const strobe = Math.sin(time * 11) > 0 ? 4.8 : 0.08;
    return { color: '#ff4f58', emissive: '#ef4444', intensity: strobe };
  }
  if (healthStatus === 'warning') {
    const blink = Math.sin(time * 5.5) > 0 ? 4.2 : 0.06;
    return { color: '#ffc34d', emissive: '#f59e0b', intensity: blink };
  }
  // A healthy or unknown device has no active alarm. Keep the lens visible as
  // an unlit smoked bezel rather than rendering a misleading green alarm.
  return {
    color: healthStatus === 'unknown' ? '#263542' : '#1b2a31',
    emissive: '#000000',
    intensity: 0,
  };
}

/**
 * Physical three-lamp status cluster used by procedural faceplates. The GLB
 * assets carry their own LED meshes and use the same state vocabulary in
 * RackDeviceItem, so this remains a lightweight fallback only.
 */
export const FaceplateStatusLeds: React.FC<FaceplateStatusLedsProps> = ({
  width,
  height,
  healthStatus,
}) => {
  const materialsRef = useRef<Array<THREE.MeshStandardMaterial | null>>([]);
  const initialState = useMemo(
    () => CHANNELS.map(channel => getLedVisualState(channel, healthStatus, 0)),
    [healthStatus],
  );
  const clusterX = -(width / 2) + Math.min(0.28, Math.max(0.2, width * 0.1));
  const clusterY = height / 2 - Math.min(0.09, Math.max(0.065, height * 0.18));

  useFrame(({ clock }) => {
    const time = clock.elapsedTime;
    CHANNELS.forEach((channel, index) => {
      const material = materialsRef.current[index];
      if (!material) return;
      const state = getLedVisualState(channel, healthStatus, time);
      material.color.set(state.color);
      material.emissive.set(state.emissive);
      material.emissiveIntensity = state.intensity;
    });
  });

  return (
    <group position={[clusterX, clusterY, 0.015]}>
      <mesh position={[0.08, 0, -0.012]}>
        <boxGeometry args={[0.34, 0.13, 0.024]} />
        <meshStandardMaterial color="#101923" roughness={0.55} metalness={0.55} />
      </mesh>
      {initialState.map((state, index) => (
        <group key={CHANNELS[index]} position={[(index - 1) * 0.095, 0, 0]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.027, 0.027, 0.012, 16]} />
            <meshStandardMaterial
              ref={material => {
                materialsRef.current[index] = material;
              }}
              color={state.color}
              emissive={state.emissive}
              emissiveIntensity={state.intensity}
              roughness={0.16}
              metalness={0.12}
              toneMapped={false}
            />
          </mesh>
          <mesh position={[0, 0, -0.007]}>
            <ringGeometry args={[0.031, 0.04, 16]} />
            <meshBasicMaterial color="#020617" transparent opacity={0.9} />
          </mesh>
        </group>
      ))}
    </group>
  );
};

export default FaceplateStatusLeds;
