import React, { useMemo } from 'react';
import { DeviceHealthStatus } from '../../types';
import { getSwitchFrontTexture, getSwitchRearTexture } from '../utils/textures';
import { FaceplateStatusLeds } from './FaceplateStatusLeds';

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
      connectedPortNumbers,
      healthStatus,
    );
  }, [deviceName, vendor, model, heightU, connectedPortNumbers, healthStatus]);

  const rearTexture = useMemo(() => {
    return getSwitchRearTexture(vendor || 'Huawei', model || 'CE6885', heightU);
  }, [vendor, model, heightU]);

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

        <FaceplateStatusLeds width={width} height={height} healthStatus={healthStatus} />
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
