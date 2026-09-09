import React, { useMemo } from 'react';
import { DeviceHealthStatus } from '../../types';
import { getGenericFrontTexture, getGenericRearTexture } from '../utils/textures';
import { FaceplateStatusLeds } from './FaceplateStatusLeds';

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

        <FaceplateStatusLeds width={width} height={height} healthStatus={healthStatus} />
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
