import React, { useMemo } from 'react';
import { DeviceHealthStatus } from '../../types';
import { getGenericFrontTexture, getGenericRearTexture } from '../utils/textures';

interface GenericFaceplateProps {
  width: number;
  height: number;
  depth: number;
  face: 'front' | 'rear';
  deviceName: string;
  role: string;
  vendor: string;
  model: string;
  heightU: number;
  healthStatus: DeviceHealthStatus;
}

export const GenericFaceplate: React.FC<GenericFaceplateProps> = ({
  width,
  height,
  depth,
  face,
  deviceName,
  role,
  vendor,
  model,
  heightU,
  healthStatus
}) => {
  const frontTexture = useMemo(() => {
    return getGenericFrontTexture(deviceName, role || 'Appliance', vendor || 'Generic', model || '', heightU);
  }, [deviceName, role, vendor, model, heightU]);

  const rearTexture = useMemo(() => {
    return getGenericRearTexture(vendor || 'Generic', heightU);
  }, [vendor, heightU]);

  const zOffset = depth / 2 + 0.005;

  const ledConfig = useMemo(() => {
    switch (healthStatus) {
      case 'healthy':
        return { color: '#22c55e', emissive: '#22c55e', intensity: 2.0 };
      case 'warning':
        return { color: '#f59e0b', emissive: '#f59e0b', intensity: 2.0 };
      case 'critical':
        return { color: '#ef4444', emissive: '#ef4444', intensity: 2.5 };
      case 'offline':
        return { color: '#475569', emissive: '#1e293b', intensity: 0.1 };
      default:
        return { color: '#94a3b8', emissive: '#475569', intensity: 0.6 };
    }
  }, [healthStatus]);

  return (
    <group>
      {/* Front Face Panel */}
      <group position={[0, 0, zOffset]}>
        <mesh position={[0, 0, 0]}>
          <planeGeometry args={[width - 0.16, height - 0.02]} />
          <meshStandardMaterial
            map={frontTexture}
            roughness={0.4}
            metalness={0.65}
          />
        </mesh>

        {/* Left Mounting Bracket */}
        <mesh position={[-(width / 2) + 0.05, 0, -0.01]}>
          <boxGeometry args={[0.1, height, 0.03]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.85} />
        </mesh>

        {/* Right Mounting Bracket */}
        <mesh position={[(width / 2) - 0.05, 0, -0.01]}>
          <boxGeometry args={[0.1, height, 0.03]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.85} />
        </mesh>

        {/* 3D Physical PWR (Power) LED */}
        <mesh position={[-(width / 2) + 0.24, (height / 2) - 0.08, 0.015]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.02, 0.02, 0.01, 16]} />
          <meshStandardMaterial
            color={healthStatus === 'offline' ? '#334155' : '#22c55e'}
            emissive={healthStatus === 'offline' ? '#000000' : '#22c55e'}
            emissiveIntensity={healthStatus === 'offline' ? 0 : 2.5}
            roughness={0.2}
          />
        </mesh>

        {/* 3D Physical SYS (Health) Status LED */}
        <mesh position={[-(width / 2) + 0.32, (height / 2) - 0.08, 0.015]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.02, 0.02, 0.01, 16]} />
          <meshStandardMaterial
            color={ledConfig.color}
            emissive={ledConfig.emissive}
            emissiveIntensity={ledConfig.intensity}
            roughness={0.2}
          />
        </mesh>
      </group>


      {/* Rear Face Panel */}
      <group position={[0, 0, -zOffset]} rotation={[0, Math.PI, 0]}>
        <mesh position={[0, 0, 0]}>
          <planeGeometry args={[width - 0.16, height - 0.02]} />
          <meshStandardMaterial
            map={rearTexture}
            roughness={0.45}
            metalness={0.65}
          />
        </mesh>
      </group>
    </group>
  );
};
