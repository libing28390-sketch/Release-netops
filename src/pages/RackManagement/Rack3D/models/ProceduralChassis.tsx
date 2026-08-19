import React, { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { DeviceHealthStatus, RackDisplayMode } from '../../types';

interface ProceduralChassisProps {
  width: number;
  height: number;
  depth: number;
  healthStatus: DeviceHealthStatus;
  role: string;
  ratedPowerWatts: number;
  displayMode?: RackDisplayMode;
  selected?: boolean;
  isAnySelected?: boolean;
}

export const ProceduralChassis: React.FC<ProceduralChassisProps> = ({
  width,
  height,
  depth,
  healthStatus,
  role,
  ratedPowerWatts,
  displayMode = 'physical',
  selected = false,
  isAnySelected = false
}) => {
  const isOffline = healthStatus === 'offline';


  const { bodyColor, roughness, metalness, emissive, emissiveIntensity } = useMemo(() => {
    // When another device is selected, slightly dim unselected devices
    const dimFactor = isAnySelected && !selected ? 0.75 : 1.0;

    // Default: High-grade gunmetal cold-rolled industrial steel chassis
    const baseColor = isOffline ? '#334155' : (isAnySelected && !selected ? '#18202c' : '#283344');

    if (displayMode === 'health') {
      switch (healthStatus) {
        case 'healthy':
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#059669', emissiveIntensity: 0.08 * dimFactor };
        case 'warning':
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#d97706', emissiveIntensity: 0.12 * dimFactor };
        case 'critical':
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#dc2626', emissiveIntensity: 0.18 * dimFactor };
        default:
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#000000', emissiveIntensity: 0 };
      }
    }

    if (displayMode === 'role') {
      const r = (role || '').toLowerCase();
      let accent = '#0284c7';
      if (r.includes('router')) accent = '#7c3aed';
      else if (r.includes('server')) accent = '#059669';
      else if (r.includes('firewall')) accent = '#c026d3';
      else if (r.includes('storage')) accent = '#ea580c';

      return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: accent, emissiveIntensity: 0.08 * dimFactor };
    }

    // Default 'physical' mode: Authentic dark gunmetal steel
    return {
      bodyColor: baseColor,
      roughness: isOffline ? 0.75 : 0.4,
      metalness: isOffline ? 0.3 : 0.7,
      emissive: '#000000',
      emissiveIntensity: 0,
    };
  }, [healthStatus, isOffline, selected, isAnySelected, displayMode, role, ratedPowerWatts]);

  const edgeGeo = useMemo(() => {
    const box = new THREE.BoxGeometry(width + 0.02, height + 0.02, depth + 0.02);
    const edges = new THREE.EdgesGeometry(box);
    box.dispose();
    return edges;
  }, [width, height, depth]);

  return (
    <group>

      {/* Main Metal Box */}
      <mesh castShadow receiveShadow>
        <boxGeometry args={[width, height, depth]} />
        <meshStandardMaterial
          color={bodyColor}
          roughness={roughness}
          metalness={metalness}
          emissive={emissive}
          emissiveIntensity={emissiveIntensity}
        />
      </mesh>

      {/* Selected Edge Highlight Box */}
      {selected && (
        <lineSegments geometry={edgeGeo}>
          <lineBasicMaterial color="#38bdf8" linewidth={2} />
        </lineSegments>
      )}
    </group>
  );
};
