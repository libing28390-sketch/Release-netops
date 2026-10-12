import React, { useMemo } from 'react';
import { DeviceHealthStatus } from '../../types';
import { getServerFrontTexture, getServerRearTexture } from '../utils/textures';
import { FaceplateStatusLeds } from './FaceplateStatusLeds';

interface ServerFaceplateProps {
  width: number;
  height: number;
  depth: number;
  face: 'front' | 'rear';
  deviceName: string;
  vendor: string;
  model: string;
  heightU: number;
  healthStatus: DeviceHealthStatus;
}

export const ServerFaceplate: React.FC<ServerFaceplateProps> = ({
  width,
  height,
  depth,
  face,
  deviceName,
  vendor,
  model,
  heightU,
  healthStatus
}) => {
  const frontTexture = useMemo(() => {
    return getServerFrontTexture(deviceName, vendor || 'Dell', model || 'R760', heightU);
  }, [deviceName, vendor, model, heightU]);

  const rearTexture = useMemo(() => {
    return getServerRearTexture(vendor || 'Dell', model || 'R760', heightU);
  }, [vendor, model, heightU]);

  const zOffset = depth / 2 + 0.005;

  return (
    <group>
      {/* Front Face Panel (Drives, power, plaque) */}
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

        <FaceplateStatusLeds width={width} height={height} healthStatus={healthStatus} />
      </group>


      {/* Rear Face Panel (Dual 1400W PSUs, PCIe slots) */}
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
