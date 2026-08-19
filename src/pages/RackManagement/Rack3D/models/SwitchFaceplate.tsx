import React, { useMemo } from 'react';
import { DeviceHealthStatus } from '../../types';
import { getSwitchFrontTexture, getSwitchRearTexture } from '../utils/textures';

interface SwitchFaceplateProps {
  width: number;
  height: number;
  depth: number;
  face: 'front' | 'rear';
  deviceName: string;
  vendor: string;
  model: string;
  heightU: number;
  healthStatus: DeviceHealthStatus;
  connectedPortNumbers?: number[];
}

export const SwitchFaceplate: React.FC<SwitchFaceplateProps> = ({
  width,
  height,
  depth,
  face,
  deviceName,
  vendor,
  model,
  heightU,
  healthStatus,
  connectedPortNumbers = []
}) => {
  const frontTexture = useMemo(() => {
    return getSwitchFrontTexture(
      deviceName,
      vendor || 'H3C',
      model || 'S6850-54HF',
      heightU,
      connectedPortNumbers
    );
  }, [deviceName, vendor, model, heightU, connectedPortNumbers]);


  const rearTexture = useMemo(() => {
    return getSwitchRearTexture(vendor || 'Huawei', model || 'CE6885', heightU);
  }, [vendor, model, heightU]);

  const zOffset = depth / 2 + 0.005;

  // LED Colors based on health
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

        {/* Left Mounting Bracket with Screw Hole Details */}
        <mesh position={[-(width / 2) + 0.05, 0, -0.01]}>
          <boxGeometry args={[0.1, height, 0.03]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.85} />
        </mesh>

        {/* Right Mounting Bracket with Screw Hole Details */}
        <mesh position={[(width / 2) - 0.05, 0, -0.01]}>
          <boxGeometry args={[0.1, height, 0.03]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.85} />
        </mesh>

        {/* 3D Physical PWR (Power) LED */}
        <mesh position={[-(width / 2) + 0.26, (height / 2) - 0.08, 0.015]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.02, 0.02, 0.01, 16]} />
          <meshStandardMaterial
            color={healthStatus === 'offline' ? '#334155' : '#22c55e'}
            emissive={healthStatus === 'offline' ? '#000000' : '#22c55e'}
            emissiveIntensity={healthStatus === 'offline' ? 0 : 2.5}
            roughness={0.2}
          />
        </mesh>

        {/* 3D Physical SYS (Health) Status LED */}
        <mesh position={[-(width / 2) + 0.34, (height / 2) - 0.08, 0.015]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.02, 0.02, 0.01, 16]} />
          <meshStandardMaterial
            color={ledConfig.color}
            emissive={ledConfig.emissive}
            emissiveIntensity={ledConfig.intensity}
            roughness={0.2}
          />
        </mesh>
      </group>


      {/* Rear Face Panel (Dual PSUs, Fans, MGMT) */}
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
